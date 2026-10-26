"""旧接收端真实请求字节、严格解析及串口生命周期边界。"""
from dataclasses import replace
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rm_client.backend.legacy_receiver import (
    CHANNEL_FREQUENCIES, LegacyReceiverControl, QUERY_STATUS, SET_CONFIG,
    ReceiverFrameParser, channel_payload, discover_receiver_port,
    encode_receiver_command, status_parameters,
)
from rm_client.backend.video_backend import RmVideoBackend
from rm_client.backend.manager import BackendManager

# 2026-10-22 对 COM14 发送并收到真实成功应答的两个完整请求。
QUERY = bytes.fromhex("550d04338a0e0000400961eb31")
CHANNEL_ONE = bytes.fromhex("551304038a0e000040090d0ff20911f2093f9b")
# COM14 原始完整状态帧，2026-10-22；只含接收端参数，不含自定义控制器数据。
STATUS = bytes.fromhex(
    "554304740e8aae140009400a00000ff20906040007812611f2090b00000c57000d2300"
    "ff0000ff0000ff0000ff0000ff0000ff0000ff0000ff0000ff0000ff0000300f")
QUERY_ACK = bytes.fromhex("550f04a20e8a0000c009610001d1ce")


class ReceiverProtocolTests(unittest.TestCase):
    def test_requests_match_device_accepted_bytes(self):
        self.assertEqual(encode_receiver_command(QUERY_STATUS), QUERY)
        self.assertEqual(encode_receiver_command(SET_CONFIG, channel_payload(1)), CHANNEL_ONE)

    def test_command_allowlist_excludes_controls_and_regional_changes(self):
        for command in (0x60, 0x63, 0x55, 0x11, 0xFF):
            with self.assertRaises(ValueError):
                encode_receiver_command(command, b"\0")
        for channel in (0, 7, 101):
            with self.assertRaises(ValueError):
                channel_payload(channel)

    def test_parser_reassembles_split_header_and_relocates_corruption(self):
        parser = ReceiverFrameParser()
        damaged = bytearray(CHANNEL_ONE)
        damaged[-1] ^= 1
        result = []
        stream = b"noise" + bytes(damaged) + QUERY + CHANNEL_ONE
        for byte in stream:
            result.extend(parser.feed(bytes([byte])))
        self.assertEqual([f.packet for f in result], [QUERY, CHANNEL_ONE])
        self.assertGreater(parser.invalid_frames, 0)
        self.assertEqual(parser.buffer, b"")

    def test_only_unique_matching_receiver_can_be_opened(self):
        devices = [SimpleNamespace(device="COM13", vid=0x0403, pid=0x6001),
                   SimpleNamespace(device="COM14", vid=0x2CA3, pid=0x001F)]
        with patch("serial.tools.list_ports.comports", return_value=devices):
            self.assertEqual(discover_receiver_port(), "COM14")
        for candidates in (devices[:1], devices + [devices[-1]]):
            with patch("serial.tools.list_ports.comports", return_value=candidates):
                with self.assertRaises(RuntimeError):
                    discover_receiver_port()

    def test_requests_do_not_count_as_receiver_status(self):
        for frame in ReceiverFrameParser().feed(QUERY + CHANNEL_ONE):
            self.assertIsNone(status_parameters(frame))

    def test_real_status_push_and_query_ack_have_different_meanings(self):
        parser = ReceiverFrameParser()
        ack, status = parser.feed(QUERY_ACK + STATUS)
        self.assertIsNone(status_parameters(ack))
        values = status_parameters(status)
        self.assertEqual(values[15], CHANNEL_FREQUENCIES[1])
        self.assertEqual(status.sequence, 0x14AE)
        self.assertEqual(status.packet, STATUS)
        for changed in (replace(status, sender=0x77), replace(status, receiver=0x01),
                        replace(status, command_set=0), replace(status, flags=0x80),
                        replace(status, payload=status.payload[:-1])):
            self.assertIsNone(status_parameters(changed))


class ReceiverOwnershipTests(unittest.TestCase):
    def test_started_source_updates_request_for_connection_maintenance(self):
        backend = BackendManager()
        self.addCleanup(backend.shutdown)
        backend.set_active_video_source("Legacy VT02 UDP", start=False)
        with patch.object(backend.udp, "running", True):
            backend.set_active_video_source("Legacy VT02 UDP", start=True)
            self.assertTrue(backend._video_source_request.start)
            with patch.object(backend.udp, "poll_connection") as maintain:
                backend._recover_video_decoders()
                maintain.assert_called_once()

    def test_real_status_drives_ready_without_rewriting_matching_channel(self):
        self.check_session(channel=1, expect_write=False)

    def test_mismatch_sets_receiver_only_after_valid_status(self):
        self.check_session(channel=2, expect_write=True)

    def check_session(self, channel, expect_write):
        port = Mock(in_waiting=0)
        delivered = threading.Event()
        port.read.side_effect = lambda count: (time.sleep(.01) or STATUS)
        def write(data):
            if data == encode_receiver_command(SET_CONFIG, channel_payload(channel)):
                delivered.set()
        port.write.side_effect = write
        with patch("serial.Serial", return_value=port), \
             patch("rm_client.backend.video.receiver.discover_receiver_port", return_value="COM14"):
            control = LegacyReceiverControl(channel)
            try:
                control.start()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if (delivered.is_set() if expect_write else control.stats()["ready"]):
                        break
                    time.sleep(.01)
                self.assertEqual(control.stats()["frequency"], CHANNEL_FREQUENCIES[1])
                if expect_write:
                    self.assertTrue(delivered.is_set())
                    self.assertFalse(control.stats()["ready"])
                else:
                    self.assertTrue(control.stats()["ready"])
                    self.assertEqual(port.write.call_args_list[0].args[0], QUERY)
                    self.assertEqual(control.stats()["configuration_writes"], 0)
            finally:
                control.stop()
            self.assertTrue(control.cleanup_complete)
            port.close.assert_called_once()

    def test_stop_during_open_retains_owner_and_prevents_second_start(self):
        entered = threading.Event()
        release = threading.Event()
        port = Mock(in_waiting=0)
        def open_port():
            entered.set()
            release.wait(2)
        port.open.side_effect = open_port
        with patch("serial.Serial", return_value=port), \
             patch("rm_client.backend.video.receiver.discover_receiver_port", return_value="COM14"):
            control = LegacyReceiverControl()
            self.addCleanup(control.stop)
            self.addCleanup(release.set)
            control.start()
            self.assertTrue(entered.wait(1))
            worker = control._thread
            control.request_stop()
            control.start()
            self.assertIs(control._thread, worker)
            self.assertFalse(control.cleanup_complete)
            release.set()
            self.assertTrue(control.wait_closed(1))
            port.close.assert_called_once()
            port.write.assert_not_called()

    def test_close_failure_stays_owned_and_explicit_retry_releases(self):
        control = LegacyReceiverControl()
        port = Mock()
        port.close.side_effect = [OSError("busy"), None]
        control._serial = port
        control._close_serial()
        self.assertFalse(control.cleanup_complete)
        self.assertIs(control._serial, port)
        control.request_stop()
        self.assertTrue(control.wait_closed(1))
        self.assertEqual(port.close.call_count, 2)

    def test_udp_stop_covers_control_even_if_decoder_stop_fails(self):
        backend = RmVideoBackend()
        backend.legacy_control = Mock()
        backend.h265_decoder.request_stop = Mock(side_effect=RuntimeError("decode close"))
        with self.assertRaises(Exception):
            backend.request_stop()
        backend.legacy_control.request_stop.assert_called_once()

    def test_udp_bind_failure_does_not_open_receiver(self):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as owner:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                owner.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            owner.bind(("127.0.0.1", 0))
            backend = RmVideoBackend("127.0.0.1", owner.getsockname()[1])
            self.addCleanup(backend.stop)
            backend.legacy_control_enabled = True
            # 同样的实际 bind 失败路径，不依赖 8080 是否被现场程序占用。
            with patch.object(backend, "_bind_address", return_value=owner.getsockname()), \
                 patch("rm_client.backend.video.udp.LegacyReceiverControl") as control:
                backend.ingress_mode = "legacy-vt02-h264"
                backend.start()
                deadline = time.monotonic() + 1
                while backend.running and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertFalse(backend.running)
                control.assert_not_called()
            backend.stop()


if __name__ == "__main__":
    unittest.main()
