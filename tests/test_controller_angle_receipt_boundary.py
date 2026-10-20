"""Real relay-worker ingress fences with inert serial streams and a fake clock.

Read-start time is a conservative freshness bound, not a hardware wire timestamp.
The paused reads model scheduling/read-return delays after bytes were captured.
No real serial factory, network peer, GUI, firmware or actuator is used.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_client.backend.cc_link import encode_cc_frame
from rm_client.backend.controller_angles import (
    ANGLE_TIMEOUT_S, AngleRelayConfig, ControllerAngleRelay,
)


def frame(sequence):
    return encode_cc_frame(0x0302, bytes(30), sequence)


def until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("inert controller-angle worker did not settle")
        time.sleep(.001)


class CapturedChunk:
    def __init__(self, data, paused=False):
        self.data = data
        self.captured = threading.Event()
        self.returned = threading.Event()
        self.release = threading.Event()
        if not paused:
            self.release.set()


class InertSerial:
    def __init__(self):
        self.chunks = []
        self.all_chunks = []
        self.writes = []
        self.lock = threading.Lock()
        self.is_open = True
        self.reset = threading.Event()

    @property
    def in_waiting(self):
        with self.lock:
            return sum(len(chunk.data) for chunk in self.chunks)

    def push(self, data, *, paused=False):
        chunk = CapturedChunk(data, paused)
        with self.lock:
            self.chunks.append(chunk)
            self.all_chunks.append(chunk)
        return chunk

    def reset_input_buffer(self):
        with self.lock:
            self.chunks.clear()
        self.reset.set()

    def read(self, size):
        with self.lock:
            chunk = self.chunks.pop(0) if self.chunks else None
        if chunk is None:
            return b""
        assert len(chunk.data) <= size
        chunk.captured.set()
        if not chunk.release.wait(2):
            raise TimeoutError("inert read was not released")
        chunk.returned.set()
        return chunk.data

    def write(self, data):
        with self.lock:
            self.writes.append(bytes(data))
        return len(data)

    def close(self):
        self.is_open = False


class ControllerAngleReceiptBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.streams = {name: InertSerial() for name in ("RX", "TX", "NEXT_RX", "NEXT_TX")}
        self.opened = []

        def factory(**options):
            self.opened.append(options["port"])
            return self.streams[options["port"]]

        self.relay = ControllerAngleRelay(time_fn=lambda: self.now, serial_factory=factory)
        self.config = AngleRelayConfig(enabled=True, rx_port="RX", tx_port="TX",
                                       forward=True, mock_output=False)
        self.relay.configure(self.config, authorized=True)
        self.assertTrue(self.streams["RX"].reset.wait(1))

    def tearDown(self):
        for stream in self.streams.values():
            for chunk in stream.all_chunks:
                chunk.release.set()
        self.relay.close()
        self.assertTrue(self.relay.wait_closed(2))
        self.assertTrue(all(not self.streams[name].is_open for name in self.opened))

    def current_sample(self, sequence=1):
        received = self.relay.stats()["received"]
        self.streams[self.config.rx_port].push(frame(sequence))
        until(lambda: self.relay.stats()["received"] == received + 1)

    def barrier(self):
        chunk = self.streams[self.config.rx_port].push(b"", paused=True)
        self.assertTrue(chunk.captured.wait(1))
        return chunk

    def test_prearm_captured_chunk_cannot_become_postarm_input(self):
        self.current_sample()
        self.now = .01
        old = self.streams["RX"].push(frame(2), paused=True)
        self.assertTrue(old.captured.wait(1))
        self.assertTrue(self.relay.arm()[0])
        old.release.set()
        barrier = self.barrier()
        self.assertEqual(self.streams["TX"].writes, [])
        self.assertEqual(self.relay.stats()["received"], 1)
        self.assertTrue(self.relay.armed)
        barrier.release.set()
        self.current_sample(3)
        until(lambda: len(self.streams["TX"].writes) == 1)
        self.assertEqual(self.streams["TX"].writes[0][3], 3)

    def test_read_delayed_beyond_timeout_cannot_publish_freshness_or_allow_arm(self):
        for delay in (ANGLE_TIMEOUT_S, .5):
            with self.subTest(delay=delay):
                chunk = self.streams["RX"].push(frame(1), paused=True)
                self.assertTrue(chunk.captured.wait(1))
                self.now += delay
                self.relay.configure(self.config, authorized=True)
                chunk.release.set()
                barrier = self.barrier()
                try:
                    self.assertFalse(self.relay.stats()["valid"])
                    self.assertFalse(self.relay.arm()[0])
                    self.assertEqual(self.streams["TX"].writes, [])
                finally:
                    barrier.release.set()
        self.current_sample(2)
        self.assertTrue(self.relay.arm()[0])
        self.current_sample(3)
        until(lambda: len(self.streams["TX"].writes) == 1)

    def test_bounded_read_delay_preserves_conservative_receipt_age(self):
        chunk = self.streams["RX"].push(frame(1), paused=True)
        self.assertTrue(chunk.captured.wait(1))
        self.now = .15
        chunk.release.set()
        until(lambda: self.relay.stats()["received"] == 1)
        self.assertAlmostEqual(self.relay.stats()["age_s"], .15)
        self.assertTrue(self.relay.arm()[0])
        self.now = ANGLE_TIMEOUT_S
        self.relay.configure(self.config, authorized=True)
        self.assertFalse(self.relay.stats()["valid"])
        self.assertFalse(self.relay.armed)

    def test_disarm_rearm_rejects_a_preceding_read_and_requires_new_input(self):
        self.current_sample()
        self.assertTrue(self.relay.arm()[0])
        old = self.streams["RX"].push(frame(2), paused=True)
        self.assertTrue(old.captured.wait(1))
        self.assertTrue(self.relay.arm()[0])
        self.relay.disarm()
        self.assertTrue(self.relay.arm()[0])
        old.release.set()
        barrier = self.barrier()
        self.assertEqual(self.streams["TX"].writes, [])
        barrier.release.set()
        self.current_sample(3)
        until(lambda: len(self.streams["TX"].writes) == 1)
        self.assertEqual(self.streams["TX"].writes[0][3], 3)

    def test_lock_delayed_publication_cannot_renew_an_old_read(self):
        chunk = self.streams["RX"].push(frame(1), paused=True)
        self.assertTrue(chunk.captured.wait(1))
        with self.relay._lock:
            chunk.release.set()
            self.assertTrue(chunk.returned.wait(1))
            self.now = .5
            self.relay.configure(self.config, authorized=True)
        barrier = self.barrier()
        self.assertFalse(self.relay.stats()["valid"])
        self.assertFalse(self.relay.arm()[0])
        self.assertEqual(self.streams["TX"].writes, [])
        barrier.release.set()

    def test_prearm_read_is_conservative_even_if_its_bytes_arrive_after_arm(self):
        self.current_sample()
        # The read has begun, but these bytes have not arrived yet. The worker
        # cannot prove their physical arrival time, so this read is fenced out.
        chunk = self.streams["RX"].push(b"", paused=True)
        self.assertTrue(chunk.captured.wait(1))
        self.assertTrue(self.relay.arm()[0])
        chunk.data = frame(2)
        chunk.release.set()
        barrier = self.barrier()
        self.assertEqual(self.relay.stats()["received"], 1)
        self.assertEqual(self.streams["TX"].writes, [])
        barrier.release.set()
        self.current_sample(3)
        until(lambda: len(self.streams["TX"].writes) == 1)

    def test_partial_prearm_frame_is_not_completed_into_an_eligible_sample(self):
        self.current_sample()
        partial = frame(2)
        self.streams["RX"].push(partial[:20])
        barrier = self.barrier()
        self.assertEqual(len(self.relay.decoder.buffer), 20)
        self.assertTrue(self.relay.arm()[0])
        barrier.release.set()
        self.streams["RX"].push(partial[20:])
        barrier = self.barrier()
        self.assertEqual(self.streams["TX"].writes, [])
        self.assertEqual(self.relay.stats()["received"], 1)
        barrier.release.set()
        self.current_sample(3)
        until(lambda: len(self.streams["TX"].writes) == 1)

    def test_true_postarm_split_frame_is_still_accepted(self):
        self.current_sample()
        self.assertTrue(self.relay.arm()[0])
        source = frame(2)
        self.streams["RX"].push(source[:20])
        barrier = self.barrier()
        self.assertEqual(len(self.relay.decoder.buffer), 20)
        self.assertEqual(self.streams["TX"].writes, [])
        barrier.release.set()
        self.streams["RX"].push(source[20:])
        until(lambda: len(self.streams["TX"].writes) == 1)
        self.assertEqual(self.streams["TX"].writes[0][3], 2)

    def test_delayed_read_while_armed_requires_fresh_input_then_explicit_rearm(self):
        self.current_sample()
        self.assertTrue(self.relay.arm()[0])
        delayed = self.streams["RX"].push(frame(2), paused=True)
        self.assertTrue(delayed.captured.wait(1))
        self.now = .5
        self.relay.configure(self.config, authorized=True)
        delayed.release.set()
        barrier = self.barrier()
        self.assertFalse(self.relay.armed)
        self.assertFalse(self.relay.stats()["valid"])
        self.assertEqual(self.streams["TX"].writes, [])
        barrier.release.set()
        self.current_sample(3)
        self.assertFalse(self.relay.armed)
        self.assertTrue(self.relay.stats()["valid"])
        self.assertEqual(self.streams["TX"].writes, [])
        self.assertTrue(self.relay.arm()[0])
        self.assertEqual(self.streams["TX"].writes, [])
        self.current_sample(4)
        until(lambda: len(self.streams["TX"].writes) == 1)

    def test_port_change_retires_captured_chunk_before_new_owner(self):
        self.current_sample()
        old = self.streams["RX"].push(frame(2), paused=True)
        self.assertTrue(old.captured.wait(1))
        self.config = replace(self.config, rx_port="NEXT_RX", tx_port="NEXT_TX")
        self.relay.configure(self.config, authorized=True)
        self.assertEqual(self.opened, ["RX"])
        old.release.set()
        self.assertTrue(self.relay.wait_closed(2))
        self.relay.configure(self.config, authorized=True)
        self.assertTrue(self.streams["NEXT_RX"].reset.wait(1))
        self.assertFalse(self.relay.stats()["valid"])
        self.assertFalse(self.relay.arm()[0])
        self.current_sample(0)
        self.assertTrue(self.relay.arm()[0])
        self.current_sample(1)
        until(lambda: len(self.streams["NEXT_TX"].writes) == 1)
        self.assertEqual(self.streams["TX"].writes, [])

    def test_direct_feed_and_pump_keep_explicit_receipt_contract(self):
        relay = ControllerAngleRelay(time_fn=lambda: self.now, start_workers=False)
        try:
            relay.configure(self.config, authorized=True)
            relay.feed(frame(1), now=0.0)
            self.assertTrue(relay.arm()[0])
            self.assertFalse(relay.pump(lambda data: len(data))[0])
            self.now = .02
            relay.feed(frame(2), now=.01)
            self.assertAlmostEqual(relay.stats()["age_s"], .01)
            writes = []
            self.assertTrue(relay.pump(lambda data: writes.append(data) or len(data))[0])
            self.assertEqual(len(writes), 1)
        finally:
            relay.close()

    def test_arm_discards_direct_api_partial_without_clearing_complete_sample(self):
        relay = ControllerAngleRelay(time_fn=lambda: self.now, start_workers=False)
        try:
            relay.configure(self.config, authorized=True)
            relay.feed(frame(1))
            source = frame(2)
            relay.feed(source[:20])
            self.assertEqual(len(relay.decoder.buffer), 20)
            self.assertTrue(relay.arm()[0])
            self.assertTrue(relay.stats()["valid"])
            self.assertEqual(relay.decoder.buffer, bytearray())
            self.now = .01
            self.assertEqual(relay.feed(source[20:]), [])
            self.assertFalse(relay.pump(lambda data: len(data))[0])
            self.now = ANGLE_TIMEOUT_S
            relay.configure(self.config, authorized=True)
            self.assertFalse(relay.stats()["valid"])
            self.assertFalse(relay.armed)
        finally:
            relay.close()


if __name__ == "__main__":
    unittest.main()
