"""Independent adversarial regressions for the physical angle relay.

Pure in-memory inputs only: no serial device, Qt application, or live robot.
The supported wire contract is pinned to StandardRobot++ 2722e0d: A5/0302,
30 payload bytes, six little-endian finite float radians, reserved tail.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import random
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_client.backend.cc_link import encode_cc_frame, decode_cc_frame
from rm_client.backend.controller_angles import (
    AngleRelayConfig, AngleStreamDecoder, ControllerAngleRelay, ANGLE_TIMEOUT_S,
)
from rm_client.protocol import crc8


def angle_frame(values=(0.1, 0.2, -0.3, 0.4, 0.5, -0.6), *, seq=7,
                tail=bytes(6), cmd=0x0302):
    return encode_cc_frame(cmd, struct.pack("<6f", *values) + tail, seq)


class IndependentAngleDecoderTests(unittest.TestCase):
    def test_every_two_chunk_boundary_and_one_byte_reads(self):
        frame = angle_frame()
        for cut in range(len(frame) + 1):
            with self.subTest(cut=cut):
                decoder = AngleStreamDecoder()
                result = decoder.feed(frame[:cut], now=10.0)
                result += decoder.feed(frame[cut:], now=10.1)
                self.assertEqual(len(result), 1)
        decoder = AngleStreamDecoder()
        result = []
        for byte in frame:
            result += decoder.feed(bytes([byte]), now=10.0)
        self.assertEqual(len(result), 1)

    def test_every_one_bit_corruption_recovers_next_valid_frame(self):
        good = angle_frame()
        for index in range(len(good)):
            for bit in range(8):
                with self.subTest(index=index, bit=bit):
                    damaged = bytearray(good)
                    damaged[index] ^= 1 << bit
                    result = AngleStreamDecoder().feed(bytes(damaged) + good, now=10.0)
                    self.assertEqual(len(result), 1)

    def test_crc8_valid_incomplete_candidate_recovers_after_bounded_deadline(self):
        header = b"\xa5\x77\x00\x00"
        incomplete = header + bytes([crc8(header)]) + b"\x02\x03"
        decoder = AngleStreamDecoder()
        result = decoder.feed(incomplete + angle_frame(), now=10.0)
        result += decoder.feed(b"", now=10.101)
        self.assertEqual(len(result), 1)

    def test_valid_unrelated_payload_is_not_reinterpreted_as_nested_angles(self):
        nested = angle_frame()
        outer = encode_cc_frame(0x0309, nested, 1)
        self.assertEqual(AngleStreamDecoder().feed(outer, now=10.0), [])

    def test_unused_tail_is_zeroed_even_if_it_encodes_nan(self):
        payload = struct.pack("<6f", 0.1, 0.2, -0.3, 0.4, 0.5, -0.6)
        wire = encode_cc_frame(0x0302, payload + b"\x00\x00\xc0\x7f\xa5\xff", 255)
        sample, = AngleStreamDecoder().feed(wire, now=10.0)
        self.assertEqual(sample.payload, payload + bytes(6))
        self.assertEqual(sample.seq, 255)
        self.assertEqual(sample.received_at, 10.0)

    def test_wrong_command_and_exact_payload_length(self):
        decoder = AngleStreamDecoder()
        for cmd in (0x0001, 0x0201, 0x0301, 0x0306, 0x0309, 0x0311):
            with self.subTest(cmd=cmd):
                self.assertEqual(decoder.feed(angle_frame(cmd=cmd), now=10.0), [])
        for length in (0, 1, 23, 24, 28, 29, 31, 119):
            with self.subTest(length=length):
                self.assertEqual(decoder.feed(encode_cc_frame(0x0302, bytes(length), 0), now=10.0), [])
        self.assertEqual(len(decoder.feed(angle_frame(), now=10.1)), 1)

    def test_all_six_channels_reject_nan_and_infinity(self):
        for index in range(6):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(index=index, value=value):
                    values = [0.0] * 6
                    values[index] = value
                    decoder = AngleStreamDecoder()
                    self.assertEqual(decoder.feed(angle_frame(values), now=10.0), [])
                    self.assertEqual(len(decoder.feed(angle_frame(), now=10.1)), 1)

    def test_finite_huge_values_exceed_pinned_source_profile(self):
        for axis in range(6):
            values = [0.1, 0.2, -0.3, 0.4, 0.5, -0.6]
            values[axis] = 1e30
            self.assertEqual(AngleStreamDecoder().feed(angle_frame(values), now=10.0), [])

    def test_sequence_wrap_is_fresh_but_exact_duplicate_is_not(self):
        stream = b"".join(angle_frame(seq=n) for n in (254, 255, 0, 1, 1, 2))
        self.assertEqual(len(AngleStreamDecoder().feed(stream, now=10.0)), 5)

    def test_seeded_noise_then_valid_frame_recovers_without_exception(self):
        rng = random.Random(20261014)
        for size in range(0, 4097, 37):
            noise = bytes(rng.randrange(256) for _ in range(size))
            decoder = AngleStreamDecoder()
            stream = noise + angle_frame()
            result = []
            for offset in range(0, len(stream), 128):
                result += decoder.feed(stream[offset:offset + 128], now=10.0)
            result += decoder.feed(b"", now=10.101)
            self.assertEqual(len(result), 1, size)


class IndependentAngleRelayTests(unittest.TestCase):
    def setUp(self):
        self.clock = [0.0]
        self.relay = ControllerAngleRelay(time_fn=lambda: self.clock[0], start_workers=False)
        self.config = AngleRelayConfig(enabled=True, rx_port="review-rx", tx_port="review-tx",
                                       forward=True, mock_output=False)
        self.relay.configure(self.config, authorized=True)
        self.written = []

    def tearDown(self):
        self.relay.close()

    def writer(self, frame):
        self.written.append(bytes(frame))
        return len(frame)

    def source(self, seq=1, now=None, values=None):
        if now is not None:
            self.clock[0] = now
        self.relay.configure(self.config, authorized=True)
        return self.relay.feed(angle_frame(seq=seq, **({"values": values} if values else {})))

    def arm_with_next(self):
        self.source(seq=1)
        self.assertTrue(self.relay.arm()[0])
        self.source(seq=2, now=0.01)

    def test_startup_and_prearm_cache_cannot_emit(self):
        self.assertFalse(self.relay.arm()[0])
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.source()
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertTrue(self.relay.arm()[0])
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertEqual(self.written, [])
        self.source(seq=2, now=0.01)
        self.assertTrue(self.relay.pump(self.writer)[0])

    def test_latest_sample_only_and_no_timer_replay(self):
        self.arm_with_next()
        for seq in range(3, 9):
            self.source(seq=seq, now=0.01 + seq / 1000,
                        values=(seq / 10, 0.2, -0.3, 0.4, 0.5, -0.6))
        self.assertTrue(self.relay.pump(self.writer)[0])
        frame = decode_cc_frame(self.written[0])
        self.assertEqual(frame["seq"], 8)
        self.assertAlmostEqual(struct.unpack_from("<f", frame["data"])[0], 0.8)
        for now in (0.05, 0.1, 0.2):
            self.clock[0] = now
            self.relay.configure(self.config, authorized=True)
            self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertEqual(len(self.written), 1)

    def test_backwards_clock_invalidates_sample_and_disarms(self):
        self.arm_with_next()
        self.clock[0] = 0.0
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertFalse(self.relay.armed)
        self.assertEqual(self.written, [])

    def test_unrelated_traffic_cannot_sustain_angles(self):
        self.arm_with_next()
        for tick in range(2, 32):
            self.clock[0] = tick / 100
            self.relay.configure(self.config, authorized=True)
            for cmd in (0x0201, 0x0306, 0x0309, 0x0311):
                self.relay.feed(angle_frame(cmd=cmd, seq=tick))
        self.assertFalse(self.relay.stats()["valid"])
        self.assertFalse(self.relay.armed)
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertEqual(self.written, [])

    def test_exact_timeout_is_stale_even_with_current_permission(self):
        self.source(seq=1, now=0.0)
        self.assertTrue(self.relay.arm()[0])
        self.clock[0] = ANGLE_TIMEOUT_S
        self.relay.configure(self.config, authorized=True)
        self.assertFalse(self.relay.stats()["valid"])
        self.assertFalse(self.relay.armed)

    def test_stale_recovery_requires_rearm_and_another_new_frame(self):
        self.arm_with_next()
        self.clock[0] = 0.4
        self.relay.configure(self.config, authorized=True)
        self.assertFalse(self.relay.stats()["valid"])
        # Source restart may reset its 8-bit sequence counter.
        self.source(seq=0, now=0.41)
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertTrue(self.relay.arm()[0])
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.source(seq=1, now=0.45)
        self.assertTrue(self.relay.pump(self.writer)[0])
        self.assertEqual(len(self.written), 1)

    def test_ui_permission_heartbeat_expiry_latches_disarmed(self):
        self.arm_with_next()
        self.clock[0] = 0.27
        self.relay.feed(angle_frame(seq=3))
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.relay.configure(self.config, authorized=True)
        self.assertFalse(self.relay.armed)
        self.assertEqual(self.written, [])

    def test_reconfiguration_and_close_never_replay_pending_sample(self):
        self.arm_with_next()
        self.config = replace(self.config, tx_port="review-tx-2")
        self.relay.configure(self.config, authorized=True)
        self.assertFalse(self.relay.arm()[0])
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.source(seq=0, now=0.05)
        self.assertTrue(self.relay.arm()[0])
        self.source(seq=1, now=0.06)
        self.relay.close()
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertEqual(self.written, [])

    def test_partial_write_does_not_retry_or_auto_rearm(self):
        self.arm_with_next()
        calls = []
        self.assertFalse(self.relay.pump(lambda frame: calls.append(frame) or 1)[0])
        self.source(seq=3, now=0.05)
        self.assertFalse(self.relay.arm()[0])
        self.assertFalse(self.relay.pump(self.writer)[0])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.written, [])

    def test_max_30_hz_even_with_1000_hz_source_and_tick(self):
        self.source(seq=0)
        self.assertTrue(self.relay.arm()[0])
        times = []
        for tick in range(1, 1001):
            self.source(seq=tick & 255, now=tick / 1000)
            if self.relay.pump(self.writer)[0]:
                times.append(self.clock[0])
        self.assertLessEqual(len(times), 30)
        self.assertGreaterEqual(len(times), 28)
        self.assertTrue(all(b - a >= 1 / 30 for a, b in zip(times, times[1:])))

    def test_blocked_writer_does_not_block_disarm_stats_or_reconfiguration(self):
        self.arm_with_next()
        entered, release, ui_done = threading.Event(), threading.Event(), threading.Event()
        def slow_write(frame):
            entered.set()
            release.wait(2)
            return len(frame)
        output = threading.Thread(target=lambda: self.relay.pump(slow_write))
        output.start()
        self.assertTrue(entered.wait(1))
        def ui_actions():
            self.relay.disarm("review disarm")
            self.relay.stats()
            self.relay.configure(replace(self.config, tx_port="review-new"), authorized=True)
            ui_done.set()
        ui = threading.Thread(target=ui_actions)
        ui.start()
        try:
            self.assertTrue(ui_done.wait(0.5), "UI methods waited for serial output")
            self.assertFalse(self.relay.armed)
        finally:
            release.set()
            output.join(2)
            ui.join(2)
        self.assertFalse(output.is_alive())
        self.assertFalse(ui.is_alive())
        self.assertFalse(self.relay.armed)
        self.assertFalse(self.relay.pump(self.writer)[0])


class ReviewStream:
    """Fake serial driver with controllable reads and lifecycle evidence."""
    def __init__(self):
        self.chunks = []
        self.written = []
        self.closed = threading.Event()
        self.reset_done = threading.Event()
        self.error = None
        self.lock = threading.Lock()

    @property
    def in_waiting(self):
        with self.lock:
            return sum(len(chunk) for chunk in self.chunks)

    def push(self, frame):
        with self.lock:
            self.chunks.append(frame)

    def read(self, size):
        with self.lock:
            if self.error:
                raise self.error
            return self.chunks.pop(0) if self.chunks else b""

    def reset_input_buffer(self):
        with self.lock:
            self.chunks.clear()
            self.reset_done.set()

    def write(self, frame):
        self.written.append(bytes(frame))
        return len(frame)

    def close(self):
        self.closed.set()


class IndependentAngleWorkerTests(unittest.TestCase):
    def wait_for(self, condition, label):
        deadline = time.monotonic() + 2
        while not condition() and time.monotonic() < deadline:
            threading.Event().wait(0.005)
        self.assertTrue(condition(), label)

    def test_reconfigure_during_slow_open_has_no_overlapping_worker_or_old_sample(self):
        old_rx, new_rx = ReviewStream(), ReviewStream()
        opening, release = threading.Event(), threading.Event()
        ports = []
        def factory(**kwargs):
            ports.append(kwargs["port"])
            if kwargs["port"] == "review-old-rx":
                opening.set()
                release.wait(2)
                old_rx.push(angle_frame(seq=1))
                return old_rx
            return new_rx
        relay = ControllerAngleRelay(time_fn=lambda: 0.0, serial_factory=factory)
        old_config = AngleRelayConfig(enabled=True, rx_port="review-old-rx", tx_port="review-tx",
                                      forward=True, mock_output=True)
        new_config = replace(old_config, rx_port="review-new-rx")
        try:
            relay.configure(old_config, authorized=True)
            self.assertTrue(opening.wait(1))
            original_worker = relay._thread
            for _ in range(10):
                relay.configure(new_config, authorized=True)
                self.assertIs(relay._thread, original_worker)
            self.assertEqual(ports, ["review-old-rx"])
            release.set()
            original_worker.join(2)
            self.assertFalse(original_worker.is_alive())
            self.assertTrue(old_rx.closed.is_set())
            self.assertFalse(relay.stats()["valid"])
            relay.configure(new_config, authorized=True)
            self.assertTrue(new_rx.reset_done.wait(1))
            self.assertIsNot(relay._thread, original_worker)
            self.assertFalse(relay.arm()[0])
            self.assertEqual(ports, ["review-old-rx", "review-new-rx"])
        finally:
            release.set()
            relay.close()
            if relay._thread:
                relay._thread.join(2)
        self.assertTrue(new_rx.closed.is_set())

    def test_slow_tx_open_rechecks_age_and_never_writes_expired_sample(self):
        now = [0.0]
        rx, tx = ReviewStream(), ReviewStream()
        opening, release = threading.Event(), threading.Event()
        opened = []
        main_thread = threading.get_ident()
        def factory(**kwargs):
            opened.append((kwargs, threading.get_ident()))
            if kwargs["port"] == "review-tx":
                opening.set()
                release.wait(2)
                return tx
            return rx
        relay = ControllerAngleRelay(time_fn=lambda: now[0], serial_factory=factory)
        config = AngleRelayConfig(enabled=True, rx_port="review-rx", tx_port="review-tx",
                                  forward=True, mock_output=False)
        try:
            relay.configure(config, authorized=True)
            self.assertTrue(rx.reset_done.wait(1))
            rx.push(angle_frame(seq=1))
            self.wait_for(lambda: relay.stats()["valid"], "initial valid sample")
            self.assertTrue(relay.arm()[0])
            rx.push(angle_frame(seq=2))
            self.assertTrue(opening.wait(1))
            # A port-open delay may consume the entire freshness budget.
            now[0] = 1.0
            relay.configure(config, authorized=True)
            release.set()
            self.wait_for(lambda: not relay.armed, "expired open must disarm")
            self.assertEqual(tx.written, [])
            self.assertTrue(all(thread != main_thread for _, thread in opened))
            self.assertTrue(all(options["timeout"] == 0 and options["write_timeout"] == 0.020
                                for options, _ in opened))
        finally:
            release.set()
            relay.close()
            relay._thread.join(2)
        self.assertTrue(rx.closed.is_set())
        self.assertTrue(tx.closed.is_set())

    def test_input_error_and_reconnect_need_new_sample_and_explicit_arm(self):
        streams = []
        def factory(**kwargs):
            stream = ReviewStream()
            streams.append(stream)
            return stream
        relay = ControllerAngleRelay(time_fn=lambda: 0.0, serial_factory=factory)
        config = AngleRelayConfig(enabled=True, rx_port="review-rx", tx_port="review-tx",
                                  forward=True, mock_output=True)
        try:
            relay.configure(config, authorized=True)
            self.wait_for(lambda: streams and streams[0].reset_done.is_set(), "RX open")
            first = streams[0]
            first.push(angle_frame(seq=1))
            self.wait_for(lambda: relay.stats()["valid"], "first sample")
            self.assertTrue(relay.arm()[0])
            first.error = OSError("review unplugged")
            self.wait_for(first.closed.is_set, "read failure closes stream")
            relay._thread.join(2)
            self.assertFalse(relay.stats()["valid"])
            self.assertFalse(relay.armed)
            relay.configure(config, authorized=True)
            self.assertEqual(len(streams), 1, "unchanged config must not auto reconnect")
            relay.configure(replace(config, enabled=False), authorized=True)
            relay.configure(config, authorized=True)
            self.wait_for(lambda: len(streams) == 2 and streams[1].reset_done.is_set(), "RX reopen")
            self.assertFalse(relay.arm()[0])
            streams[1].push(angle_frame(seq=0))
            self.wait_for(lambda: relay.stats()["valid"], "restarted source frame")
            self.assertFalse(relay.armed)
            self.assertEqual(relay.stats()["mock_forwarded"], 0)
        finally:
            relay.close()
            if relay._thread:
                relay._thread.join(2)
        self.assertTrue(all(stream.closed.is_set() for stream in streams))


if __name__ == "__main__":
    unittest.main()
