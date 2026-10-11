"""Offline stream lifecycle tests. All I/O endpoints are in-memory fakes."""
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.serial_backend import RmSerialBackend
from rm_client.backend.serial_stream import TcpByteStream, open_serial, open_stream
from rm_client.backend.polar_transport import PolarDriveIntent, PolarLinkTransport, PolarTimestamp
from rm_client.protocol import RefereeFrameCodec


class FakeStream:
    def __init__(self):
        self.is_open = True
        self.written = []
        self.read_error = None
        self.short_write = False

    def read(self, size):
        if self.read_error:
            raise self.read_error
        return b""

    def write(self, data):
        self.written.append(bytes(data))
        return 1 if self.short_write else len(data)

    def close(self):
        self.is_open = False


class LifecycleTests(unittest.TestCase):
    def referee(self):
        backend = RmSerialBackend(mock_writes=False)
        backend._serial = stream = FakeStream()
        backend.connected = True
        return backend, stream

    def polar(self):
        backend = PolarLinkTransport(mock_writes=False)
        backend._serial = stream = FakeStream()
        backend.connected = True
        return backend, stream

    def test_referee_malformed_command_and_payload_fail_without_throwing(self):
        backend, stream = self.referee()
        for command in (None, 'bad', '769', 1.2, -1, 65536, True):
            self.assertFalse(backend.write_frame(command, b'ok')[0])
        for payload in (None, 10, 'text', b'x' * 301):
            self.assertFalse(backend.write_frame(0x0201, payload)[0])
        self.assertEqual(stream.written, [])

    def test_raw_video_route_cannot_bypass_referee_guard(self):
        backend, stream = self.referee()
        codec = RefereeFrameCodec()
        allowed = codec.encode(0x0201, b"ok")
        for command in (0x0310, 0x0311):
            blocked = codec.encode(command, b"video")
            for payload in (blocked, allowed + blocked, blocked + allowed):
                self.assertFalse(backend.write(payload)[0])
        self.assertEqual(stream.written, [])
        self.assertTrue(backend.write(allowed + allowed)[0])

    def test_raw_malformed_referee_frames_are_rejected(self):
        backend, stream = self.referee()
        frame = RefereeFrameCodec().encode(0x0201, b"ok")
        for payload in (b"", frame[:-1], b"junk" + frame, frame + b"junk", frame[:-1] + bytes([frame[-1] ^ 1])):
            self.assertFalse(backend.write(payload)[0])
        self.assertEqual(stream.written, [])

    def test_referee_short_write_closes_epoch(self):
        backend, stream = self.referee()
        stream.short_write = True
        self.assertFalse(backend.write_frame(0x0201, b"ok")[0])
        self.assertFalse(backend.connected)
        self.assertFalse(stream.is_open)
        self.assertIsNone(backend._serial)
        self.assertEqual(backend.frames_written, 0)
        self.assertFalse(backend.write_frame(0x0201, b"ok")[0])
        self.assertEqual(len(stream.written), 1)

    def test_referee_read_error_closes_and_discards_old_frames(self):
        backend, stream = self.referee()
        backend._running = True
        backend._rx.append(object())
        stream.read_error = OSError("gone")
        backend._read_loop()
        self.assertFalse(stream.is_open)
        self.assertIsNone(backend._serial)
        self.assertEqual(backend.drain_frames(), [])

    def test_referee_estop_blocks_even_legacy_bypass(self):
        backend, stream = self.referee()
        backend.trigger_estop()
        self.assertFalse(backend._write_payload(RefereeFrameCodec().encode(0x0201), bypass_estop=True)[0])
        self.assertEqual(stream.written, [])

    def test_tcp_write_error_closes_socket(self):
        closed = []
        def sendall(payload):
            raise socket.timeout("backpressure")
        sock = SimpleNamespace(sendall=sendall, shutdown=lambda how: None, close=lambda: closed.append(True))
        stream = TcpByteStream("fake", 1)
        stream._sock, stream.is_open = sock, True
        with self.assertRaises(RuntimeError):
            stream.write(b"data")
        self.assertIsNone(stream._sock)
        self.assertFalse(stream.is_open)
        self.assertEqual(closed, [True])

    def test_unknown_mode_does_not_open_serial(self):
        with self.assertRaises(ValueError):
            open_stream("typo", port="fake", serial_opener=lambda *a: self.fail("unexpected open"))

    def test_start_does_not_replace_lingering_workers(self):
        lingering = SimpleNamespace(is_alive=lambda: True)
        referee = RmSerialBackend(port="fake")
        referee._reader = lingering
        polar = PolarLinkTransport(port="fake")
        polar._thread = lingering
        with patch.dict(sys.modules, {"serial": SimpleNamespace(Serial=lambda **k: self.fail("opened early"))}):
            referee.start()
        with patch("rm_client.backend.serial_stream.open_stream", side_effect=AssertionError("opened early")):
            polar.start()
        self.assertIs(referee._reader, lingering)
        self.assertIs(polar._thread, lingering)

    def test_stop_retains_timed_out_worker(self):
        for backend, attribute in ((RmSerialBackend(), "_reader"), (PolarLinkTransport(), "_thread")):
            worker = SimpleNamespace(is_alive=lambda: True, join=lambda timeout: None)
            setattr(backend, attribute, worker)
            backend.stop()
            self.assertIs(getattr(backend, attribute), worker)

    def test_polar_submission_is_owned_snapshot(self):
        backend, stream = self.polar()
        intent = PolarDriveIntent(vx=1)
        backend.submit(intent)
        intent.vx = 4
        backend._pump_tx(time.perf_counter())
        self.assertEqual(struct.unpack_from("<f", stream.written[0], 8)[0], 1)

    def test_polar_clear_before_tx_lock_prevents_stale_send(self):
        backend, stream = self.polar()
        backend.submit(PolarDriveIntent(vx=1))
        started = threading.Event()
        def pump():
            started.set()
            backend._pump_tx(time.perf_counter())
        with backend._intent_lock:
            worker = threading.Thread(target=pump)
            worker.start()
            self.assertTrue(started.wait(1))
            backend.clear_intent()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(struct.unpack_from("<f", stream.written[0], 8)[0], 0)

    def test_polar_short_write_preserves_reason_and_closes(self):
        backend, stream = self.polar()
        stream.short_write = True
        backend.submit(PolarDriveIntent(vx=1))
        backend._pump_tx(time.perf_counter())
        self.assertEqual(backend.last_error_code, "STREAM_SHORT_WRITE")
        self.assertFalse(backend.connected)
        self.assertFalse(stream.is_open)
        self.assertEqual(len(stream.written), 1)

    def test_polar_rollover_blocks_output_and_release(self):
        backend, stream = self.polar()
        backend.timestamp._virtual = (1 << 32) - 1
        backend.submit(PolarDriveIntent(vx=1))
        with patch("rm_client.backend.polar_transport.time.time", return_value=0):
            backend._pump_tx(time.perf_counter())
        self.assertTrue(backend.timestamp.roll_detected)
        self.assertEqual(stream.written, [])
        self.assertEqual(backend.last_error_code, "TIMESTAMP_ROLLOVER")
        backend.release_estop()
        self.assertTrue(backend._estop_active)
        self.assertTrue(PolarTimestamp(floor=0xFFFFFFFF).roll_detected)

    def test_polar_backpressure_does_not_send_expired_rc_keys(self):
        backend, stream = self.polar()
        backend.drive_channel = "both"
        now = time.perf_counter()
        backend.submit(PolarDriveIntent(vx=1, key_value=1, produced_at=now))
        with patch("rm_client.backend.polar_transport.time.perf_counter", side_effect=[now, now, now + 1, now + 1, now + 1]):
            backend._pump_tx(now)
        self.assertNotIn(3, [frame[2] for frame in stream.written])
        robots = [frame for frame in stream.written if frame[2] == 1]
        self.assertEqual(struct.unpack_from("<f", robots[-1], 8)[0], 0)

    def test_serial_control_io_has_bounded_write_and_nonblocking_read(self):
        calls = []
        with patch.dict(sys.modules, {"serial": SimpleNamespace(Serial=lambda **kwargs: calls.append(kwargs))}):
            open_serial("fake", 115200)
        self.assertEqual(calls[0]["timeout"], 0)
        self.assertLessEqual(calls[0]["write_timeout"], 0.02)

    def test_invalid_intent_neutralizes_old_command_without_crashing(self):
        for name, value in (("vx", float("nan")), ("vy", float("inf")),
                            ("wz", "bad"), ("vx", 1e100), ("key_value", float("nan")),
                            ("key_value", "bad"), ("produced_at", float("nan")),
                            ("produced_at", time.perf_counter() + 1000)):
            with self.subTest(name=name, value=value):
                backend, stream = self.polar()
                backend.drive_channel = "both"
                backend.submit(PolarDriveIntent(vx=1, key_value=1))
                backend._pump_tx(time.perf_counter())
                stream.written.clear()
                intent = PolarDriveIntent(vx=2)
                setattr(intent, name, value)
                backend.submit(intent)
                self.assertTrue(backend._estop_active)
                self.assertIsNone(backend._intent)
                self.assertEqual(backend.last_error_code, "INVALID_INTENT")
                self.assertTrue(backend.connected)
                robot = next(frame for frame in stream.written if frame[2] == 1)
                self.assertEqual(struct.unpack_from("<fff", robot, 8), (0, 0, 0))
                rc = next(frame for frame in stream.written if frame[2] == 3)
                self.assertEqual(struct.unpack_from("<H", rc, 28)[0], 0)
                backend._pump_tx(time.perf_counter())

    def test_out_of_range_spin_does_not_alias_on(self):
        backend, _ = self.polar()
        for value in (257, -255, float("nan"), "bad"):
            backend.set_spin_command(value)
            self.assertEqual(backend.spin_command(), 0)

    def test_polar_stats_reports_detected_ports(self):
        backend, _ = self.polar()
        with patch("rm_client.backend.polar_transport.describe_ports", return_value=["fake"]):
            self.assertEqual(backend.stats()["detected_ports"], ["fake"])


if __name__ == "__main__":
    unittest.main()
