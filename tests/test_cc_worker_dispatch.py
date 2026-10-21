"""Fake-only tests: CC drivers must never hold up the render/UI thread."""
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.cc_link import AsyncCustomControllerLink, decode_cc_frame, VIRTUAL_KEY


def until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("worker did not reach expected state")


class CCWorkerTests(unittest.TestCase):
    def link(self, **kwargs):
        link = AsyncCustomControllerLink(mock_output=False, **kwargs)
        def cleanup():
            link.close()
            link._thread.join(2)
            self.assertFalse(link._thread.is_alive())
        self.addCleanup(cleanup)
        return link

    def test_blocked_write_mailbox_latest_only_and_nonblocking_close(self):
        entered, unblock = threading.Event(), threading.Event()
        frames = []
        def write(frame):
            frames.append(frame)
            if len(frames) == 1:
                entered.set()
                unblock.wait(2)
            return len(frame)
        link = self.link(write_bytes=write, max_hz=1000)
        self.addCleanup(unblock.set)
        link.send_keymouse(pressed=['W'])
        self.assertTrue(entered.wait(1))
        start = time.monotonic()
        for _ in range(1000):
            link.send_keymouse(pressed=['A'])
        link.send_keymouse(pressed=['D'])
        self.assertLess(time.monotonic() - start, .25)
        self.assertIsNotNone(link._pending)
        unblock.set()
        until(lambda: len(frames) == 2)
        self.assertEqual(decode_cc_frame(frames[1])['data'][0], VIRTUAL_KEY['D'])
        link.release_all()
        until(lambda: link.wire_neutral)
        self.assertEqual(len(frames), 3)
        self.assertTrue(link.release_all()[0])

    def test_neutral_preempts_pending_motion_and_blocks_new_motion(self):
        entered, unblock = threading.Event(), threading.Event()
        frames = []
        def write(frame):
            frames.append(frame)
            if len(frames) == 1:
                entered.set()
                unblock.wait(2)
            return len(frame)
        link = self.link(write_bytes=write, max_hz=1)
        self.addCleanup(unblock.set)
        link.send_keymouse(pressed=['W'])
        self.assertTrue(entered.wait(1))
        link.send_keymouse(pressed=['A'])
        start = time.monotonic()
        self.assertFalse(link.release_all()[0])
        self.assertFalse(link.send_keymouse(pressed=['D'])[0])
        link.close()
        self.assertLess(time.monotonic() - start, .1)
        unblock.set()
        link._thread.join(1)
        self.assertFalse(link._thread.is_alive())
        self.assertEqual(len(frames), 2)
        self.assertEqual(decode_cc_frame(frames[-1])['data'][:2], b'\0\0')
        self.assertTrue(link.wire_neutral)

    def test_failure_discards_pending_motion_and_neutral_retries_are_bounded(self):
        entered, unblock = threading.Event(), threading.Event()
        frames = []
        def write(frame):
            frames.append(frame)
            if len(frames) == 1:
                entered.set()
                unblock.wait(2)
            raise OSError('fake disconnected')
        link = self.link(write_bytes=write, max_hz=1000, retry_interval=.005,
                         release_attempts=3)
        self.addCleanup(unblock.set)
        link.send_keymouse(pressed=['W'])
        self.assertTrue(entered.wait(1))
        link.send_keymouse(pressed=['A'])
        unblock.set()
        until(lambda: len(frames) == 4)
        for _ in range(100):
            self.assertFalse(link.release_all()[0])
        time.sleep(.05)
        self.assertEqual(len(frames), 4)
        self.assertTrue(link.release_pending)
        self.assertFalse(link.wire_neutral)
        self.assertIsNone(link._pending)
        self.assertTrue(all(decode_cc_frame(f)['data'][:2] == b'\0\0'
                            for f in frames[1:]))
        self.assertFalse(link.send_keymouse(pressed=['D'])[0])

    def test_failed_motion_recovers_only_with_new_intent_after_neutral(self):
        frames = []
        def write(frame):
            frames.append(frame)
            return 0 if len(frames) == 1 else len(frame)
        link = self.link(write_bytes=write, max_hz=1000)
        link.send_keymouse(pressed=['W'])
        until(lambda: link.wire_neutral and len(frames) == 2)
        self.assertIsNone(link._pending)
        self.assertFalse(link.send_keymouse(pressed=['D'])[0])
        self.assertFalse(link.rearm(0))
        self.assertTrue(link.rearm(time.perf_counter()))
        link.send_keymouse(pressed=['D'])
        until(lambda: len(frames) == 3)
        self.assertEqual(decode_cc_frame(frames[2])['data'][0], VIRTUAL_KEY['D'])

    def test_enumeration_and_open_are_worker_owned_and_close_invalidates_motion(self):
        for stage in ('resolve', 'open'):
            with self.subTest(stage=stage):
                entered, unblock = threading.Event(), threading.Event()
                frames, threads = [], []
                def stall():
                    threads.append(threading.get_ident())
                    entered.set()
                    unblock.wait(2)
                def resolve(port):
                    if stage == 'resolve':
                        stall()
                    return 'FAKE'
                def serial_factory(*args, **kwargs):
                    if stage == 'open':
                        stall()
                    return SimpleNamespace(write=lambda f: (frames.append(f) or len(f)),
                                           close=lambda: None)
                with patch('rm_client.serial_ports.resolve_cc_port', resolve), \
                     patch.dict(sys.modules, serial=SimpleNamespace(Serial=serial_factory)):
                    link = self.link(max_hz=1000)
                    self.addCleanup(unblock.set)
                    start = time.monotonic()
                    link.send_keymouse(pressed=['W'])
                    self.assertLess(time.monotonic() - start, .1)
                    self.assertTrue(entered.wait(1))
                    link.close()
                    unblock.set()
                    link._thread.join(2)
                    self.assertFalse(link._thread.is_alive())
                    self.assertTrue(all(t != threading.get_ident() for t in threads))
                    self.assertEqual(len(frames), 1)
                    self.assertEqual(decode_cc_frame(frames[0])['data'][:2], b'\0\0')

    def test_exhausted_release_needs_explicit_retry(self):
        frames = []
        failing = [True]
        def write(frame):
            frames.append(frame)
            if failing[0]:
                raise OSError('offline')
            return len(frame)
        link = self.link(write_bytes=write, release_attempts=1)
        link.send_keymouse(pressed=['W'])
        until(lambda: len(frames) == 2 and not link._release_left)
        failing[0] = False
        self.assertFalse(link.release_all()[0])
        link.retry_release()
        until(lambda: link.wire_neutral)
        self.assertEqual(len(frames), 3)

    def test_rate_delayed_expired_mailbox_becomes_neutral(self):
        frames = []
        link = self.link(write_bytes=lambda f: (frames.append(f) or len(f)),
                         max_hz=20, max_intent_age=.01)
        link.send_keymouse(pressed=['W'])
        until(lambda: len(frames) == 1)
        link.send_keymouse(pressed=['A'])
        until(lambda: link.wire_neutral)
        self.assertEqual(len(frames), 2)
        self.assertEqual(decode_cc_frame(frames[-1])['data'][:2], b'\0\0')

    def test_stale_motion_after_slow_open_is_never_written(self):
        frames = []
        def serial_factory(*args, **kwargs):
            time.sleep(.04)
            return SimpleNamespace(write=lambda f: (frames.append(f) or len(f)),
                                   close=lambda: None)
        with patch('rm_client.serial_ports.resolve_cc_port', return_value='FAKE'), \
             patch.dict(sys.modules, serial=SimpleNamespace(Serial=serial_factory)):
            link = self.link(max_intent_age=.01)
            link.send_keymouse(pressed=['W'])
            until(lambda: link.wire_neutral and frames)
            self.assertEqual(len(frames), 1)
            self.assertEqual(decode_cc_frame(frames[0])['data'][:2], b'\0\0')
            link.close()
            link._thread.join(1)


if __name__ == '__main__':
    unittest.main()
