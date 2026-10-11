"""Fake-only lifecycle regression tests; no devices or sockets are opened."""
import threading
import time

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rm_client.backend import polar_transport as module
from rm_client.backend.polar_transport import PolarDriveIntent, PolarLinkTransport


class Stream:
    def __init__(self):
        self.is_open = True
        self.closed = threading.Event()
        self.writes = []

    def read(self, size):
        return b""

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def close(self):
        self.is_open = False
        self.closed.set()


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "worker did not finish"
        time.sleep(0.002)


def fake_transport(monkeypatch, opener):
    from rm_client.backend import serial_stream
    monkeypatch.setattr(serial_stream, "open_stream", opener)
    transport = PolarLinkTransport(mock_writes=True)
    transport.transport = "tcp"
    transport.host = "fake-only.invalid"
    return transport


def check_request_start_is_fast_and_single_owner(monkeypatch):
    entered = threading.Event()
    calls = []
    stream = Stream()

    def opener(*args, **kwargs):
        calls.append(kwargs)
        entered.set()
        time.sleep(0.2)
        return stream

    transport = fake_transport(monkeypatch, opener)
    try:
        before = time.monotonic()
        transport.request_start()
        assert time.monotonic() - before < 0.08
        assert entered.wait(1)
        worker = transport._connector_thread
        for _ in range(50):
            transport.request_start()
        assert transport._connector_thread is worker
        wait_for(lambda: transport.connected)
        assert len(calls) == 1
        assert transport._intent is None
    finally:
        transport.stop()
    assert stream.closed.is_set()


def check_pending_open_is_never_published_after_cancel(monkeypatch, cancel):
    entered, release = threading.Event(), threading.Event()
    stream = Stream()

    def opener(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return stream

    transport = fake_transport(monkeypatch, opener)
    transport.request_start()
    assert entered.wait(1)
    transport.submit(PolarDriveIntent(vx=1))
    transport.set_spin_command(1)
    transport.set_gimbal_host_request(True)
    before = time.monotonic()
    if cancel == "config":
        transport.host = "replacement.invalid"
    else:
        getattr(transport, cancel)()
    assert time.monotonic() - before < 0.08
    release.set()
    wait_for(lambda: not transport._connecting and not transport._stopping)
    assert stream.closed.is_set()
    assert not transport.connected
    assert transport._serial is None
    assert not stream.writes
    assert transport._thread is None
    transport.stop()


def check_stop_close_does_not_block_requests_or_open_replacement(monkeypatch):
    close_entered, release = threading.Event(), threading.Event()

    class SlowClose(Stream):
        def close(self):
            close_entered.set()
            assert release.wait(2)
            super().close()

    old, new = SlowClose(), Stream()
    streams = iter([old, new])
    calls = []

    def opener(*args, **kwargs):
        calls.append(kwargs)
        return next(streams)

    transport = fake_transport(monkeypatch, opener)
    transport.start()
    before = time.monotonic()
    transport.request_stop()
    assert time.monotonic() - before < 0.08
    assert close_entered.wait(1)
    worker = transport._stopper_thread
    before = time.monotonic()
    for _ in range(50):
        transport.request_start()
        transport.request_stop()
    assert time.monotonic() - before < 0.08
    assert transport._stopper_thread is worker
    assert len(calls) == 1
    release.set()
    wait_for(lambda: not transport._stopping)
    transport.request_start()
    wait_for(lambda: transport.connected and not transport._connecting)
    assert old.closed.is_set()
    assert transport._serial is new
    assert not new.closed.is_set()
    assert transport._intent is None
    assert transport._estop_active  # reconnect never releases an estop
    transport.stop()
    assert new.closed.is_set()


def check_request_estop_does_not_wait_for_writer_lock(monkeypatch):
    stream = Stream()
    transport = fake_transport(monkeypatch, lambda *a, **kw: stream)
    entered, release = threading.Event(), threading.Event()

    def writer():
        with transport._intent_lock:
            entered.set()
            assert release.wait(2)

    worker = threading.Thread(target=writer)
    worker.start()
    assert entered.wait(1)
    try:
        before = time.monotonic()
        transport.request_estop()
        assert time.monotonic() - before < 0.08
        assert transport._estop_active
        assert transport._intent is None
        assert not stream.writes
    finally:
        release.set()
        worker.join(1)


def check_serial_enumeration_runs_on_connector(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    stream = Stream()
    transport = fake_transport(monkeypatch, lambda *a, **kw: stream)
    transport.transport, transport.port = "serial", "Auto"

    def resolve(port):
        entered.set()
        assert release.wait(2)
        return "fake-serial"

    monkeypatch.setattr(module, "resolve_polar_port", resolve)
    before = time.monotonic()
    transport.request_start()
    assert time.monotonic() - before < 0.08
    assert entered.wait(1)
    transport.stop()
    release.set()
    wait_for(lambda: not transport._connecting)
    assert stream.closed.is_set()
    assert not transport.connected


class AsyncLifecycleTests(unittest.TestCase):
    def run_case(self, function, *args):
        patches = []

        class MonkeyPatch:
            def setattr(self, target, name, value):
                item = patch.object(target, name, value)
                item.start()
                patches.append(item)

        try:
            function(MonkeyPatch(), *args)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_single_owner(self):
        self.run_case(check_request_start_is_fast_and_single_owner)

    def test_cancelled_open(self):
        for cancel in ("stop", "request_stop", "config"):
            with self.subTest(cancel=cancel):
                self.run_case(check_pending_open_is_never_published_after_cancel, cancel)

    def test_slow_close(self):
        self.run_case(check_stop_close_does_not_block_requests_or_open_replacement)

    def test_estop_lock(self):
        self.run_case(check_request_estop_does_not_wait_for_writer_lock)

    def test_enumeration(self):
        self.run_case(check_serial_enumeration_runs_on_connector)


if __name__ == "__main__":
    unittest.main()
