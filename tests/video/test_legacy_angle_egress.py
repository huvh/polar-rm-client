"""旧图传直发：官方字节对拍、实际写完成、排队撤权及串口所有权。"""
from pathlib import Path
import queue
import struct
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rm_client.backend.controller_angles import (AngleRelayConfig, ControllerAngleRelay,
                                                 vt02_encoder_payload, angle_payload)
from rm_client.backend.legacy_angle_egress import LegacyAngleEgress, encode_receiver_angles
from rm_client.backend.legacy_receiver import LegacyReceiverControl, ReceiverFrameParser
from rm_client.backend.manager import BackendManager
from rm_client.model import build_default_registry
from rm_client.protocol import RefereeFrameCodec, crc16

# COM13 实读帧；外层校验由本机官方 CRCCheck_VideoSerialPort.cs 原代码独立生成。
SOURCE = bytes.fromhex(
    "a51e0030c302030ddabe3f0000000000000000000000000000000000000000000000000000b0a6")
OFFICIAL_PACKET = bytes.fromhex(
    "553404ac8a770000400963a51e0030c302030ddabe3f0000000000000000000000000000000000000000000000000000b0a6bf17")


def wait_until(predicate):
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return False


class Receiver:
    def __init__(self):
        self.ready = True
        self.owned_port = "COM14"
        self.egress = LegacyAngleEgress()

    def stats(self):
        return {"ready": self.ready}

    def write_angles(self, frame, permit):
        return self.egress.write(frame, permit)


class LegacyAngleTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1.0]
        self.receiver = Receiver()
        self.relay = ControllerAngleRelay(time_fn=lambda: self.clock[0], start_workers=False)
        self.relay.set_legacy_receiver(self.receiver)
        self.config = AngleRelayConfig(True, "COM13", "Stub", True, False, "Legacy Receiver")
        self.relay.configure(self.config, True)
        self.addCleanup(self.relay.close)
        self.addCleanup(self.receiver.egress.cancel)

    def sample(self, seq):
        return RefereeFrameCodec().encode(0x0302, SOURCE[7:-2], seq=seq)

    def arm(self):
        self.relay.feed(self.sample(1))
        self.assertTrue(self.relay.arm()[0])
        self.clock[0] += .01
        self.relay.feed(self.sample(2))

    def queue_pump(self):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.relay.pump()))
        worker.start()
        self.addCleanup(worker.join, 1)
        self.assertTrue(wait_until(lambda: self.receiver.egress._pending is not None))
        return worker, result

    def test_matches_official_crc_implementation_and_custom_data_address(self):
        self.assertEqual(encode_receiver_angles(SOURCE), OFFICIAL_PACKET)
        frame, = ReceiverFrameParser().feed(OFFICIAL_PACKET)
        self.assertEqual((frame.sender, frame.receiver, frame.command_set, frame.command),
                         (0x8A, 0x77, 9, 0x63))
        self.assertEqual(frame.payload, SOURCE)

    def test_vt02_metadata_survives_observed_header_and_tail_removal(self):
        for seq in range(256):
            payload = vt02_encoder_payload(SOURCE[7:-2], seq)
            values, _ = angle_payload(payload)  # 元数据仍满足六浮点范围。
            self.assertEqual(values[0], struct.unpack_from("<f", SOURCE, 7)[0])
            self.assertEqual(values[1] * 256, seq)
            self.assertEqual(values[3:], (3.25, -3.25, 1.0))
            a5 = RefereeFrameCodec().encode(0x0302, payload, seq=seq)
            outer, = ReceiverFrameParser().feed(encode_receiver_angles(a5))
            raw = outer.payload[5:31]  # 实机 VT02 输出 cmd + 六浮点，共 26B。
            self.assertEqual(len(raw), 26)
            self.assertEqual(crc16(raw[:10] + raw[14:]), int(-values[2] * 32768))

    def test_vt02_rejects_multi_axis_input_instead_of_discarding_joints(self):
        data = bytearray(SOURCE[7:-2])
        struct.pack_into("<f", data, 4, 0.5)
        with self.assertRaises(ValueError):
            vt02_encoder_payload(data, 7)

    def test_vt02_route_reuses_receiver_owner_and_preserves_real_write_count(self):
        from dataclasses import replace
        self.config = replace(self.config, output_route="VT02 Encoder")
        self.relay.configure(self.config, True)
        self.arm()
        worker, result = self.queue_pump()
        port = Mock()
        port.write.side_effect = len
        self.receiver.egress.pump(port, True)
        worker.join(1)
        self.assertTrue(result[0][0])
        frame, = ReceiverFrameParser().feed(port.write.call_args.args[0])
        self.assertEqual(frame.sequence, 0)
        self.assertEqual(frame.payload[:5], bytes.fromhex("a51e001302"))
        self.assertEqual(frame.payload[7:-2], vt02_encoder_payload(SOURCE[7:-2], 2))
        self.assertEqual(self.relay.forwarded, 1)
        self.assertEqual(self.receiver.egress.written, 1)

    def test_invalid_inner_frames_never_become_custom_data(self):
        codec = RefereeFrameCodec()
        invalid = [SOURCE[:-1], SOURCE + b"\0", bytes(39),
                   codec.encode(0x0306, bytes(30)), codec.encode(0x0302, bytes(29))]
        for index in (3, 4, 10, 38):
            corrupt = bytearray(SOURCE)
            corrupt[index] ^= 1
            invalid.append(corrupt)
        for frame in invalid:
            with self.assertRaises(ValueError):
                encode_receiver_angles(frame)

    def test_no_tx_port_is_needed_and_queueing_is_not_success(self):
        self.arm()
        worker, result = self.queue_pump()
        self.assertEqual(self.relay.forwarded, 0)
        port = Mock()
        port.write.side_effect = len
        self.receiver.egress.pump(port, True)
        worker.join(1)
        self.assertTrue(result[0][0])
        self.assertEqual(self.relay.forwarded, 1)
        self.assertEqual(self.receiver.egress.written, 1)
        self.assertEqual(port.write.call_args.args[0][11:-2], self.sample(2))
        self.assertFalse(self.relay.pump()[0])  # 同一样本不能重复发送。

    def test_queued_permission_changes_prevent_write_without_breaking_video_owner(self):
        for change in (lambda: self.relay.disarm(),
                       lambda: self.clock.__setitem__(0, 1.4),
                       lambda: setattr(self.receiver, "ready", False),
                       lambda: self.relay.configure(self.config, False),
                       lambda: self.relay.set_legacy_receiver(Receiver())):
            with self.subTest(change=change):
                self.setUp()
                self.arm()
                worker, result = self.queue_pump()
                change()
                port = Mock()
                self.receiver.egress.pump(port, True)
                worker.join(1)
                port.write.assert_not_called()
                self.assertFalse(result[0][0])
                self.assertFalse(self.relay.armed)
                self.assertEqual(self.relay.forwarded, 0)

    def test_short_write_fails_and_does_not_count_as_forwarded(self):
        self.arm()
        worker, result = self.queue_pump()
        port = Mock()
        port.write.return_value = 51
        with self.assertRaises(IOError):
            self.receiver.egress.pump(port, True)
        worker.join(1)
        self.assertFalse(result[0][0])
        self.assertEqual(self.relay.forwarded, 0)
        self.assertEqual(self.receiver.egress.written, 0)
        self.assertFalse(self.relay.armed)

    def test_stop_or_write_deadline_cancels_waiter(self):
        self.arm()
        worker, result = self.queue_pump()
        self.receiver.egress.cancel()
        worker.join(1)
        self.assertFalse(result[0][0])
        port = Mock()
        self.receiver.egress.pump(port, True)
        port.write.assert_not_called()
        with self.assertRaises(TimeoutError):
            self.receiver.egress.write(SOURCE, lambda: True)
        self.receiver.egress.pump(port, True)
        port.write.assert_not_called()

    def test_receiver_disconnected_cannot_arm_and_never_auto_rearms(self):
        self.relay.feed(self.sample(1))
        self.receiver.ready = False
        self.assertFalse(self.relay.arm()[0])
        self.receiver.ready = True
        self.assertTrue(self.relay.arm()[0])
        self.receiver.ready = False
        self.assertFalse(self.relay.stats()["armed"])
        self.receiver.ready = True
        self.assertFalse(self.relay.stats()["armed"])

    def test_vt02_startup_auto_arm_waits_for_receiver_and_preserves_timeout_stop(self):
        from dataclasses import replace
        self.config = replace(self.config, output_route="VT02 Encoder", auto_arm=True)
        self.receiver.ready = False
        self.relay.configure(self.config, True)
        self.relay.feed(self.sample(1))
        self.assertFalse(self.relay.arm_on_startup()[0])
        self.receiver.ready = True
        self.assertTrue(self.relay.arm_on_startup()[0])
        self.assertFalse(self.relay.pump()[0])
        self.relay.feed(self.sample(2))
        worker, result = self.queue_pump()
        port = Mock()
        port.write.side_effect = len
        self.receiver.egress.pump(port, True)
        worker.join(1)
        self.assertTrue(result[0][0])
        self.assertEqual(self.relay.forwarded, 1)
        self.clock[0] += .4
        self.relay.configure(self.config, True)
        self.relay.feed(self.sample(3))
        self.assertFalse(self.relay.arm_on_startup()[0])
        self.assertFalse(self.relay.armed)

    def test_wire_owner_enforces_30hz_after_actual_write_completion(self):
        self.arm()
        worker, result = self.queue_pump()
        port = Mock()
        port.write.side_effect = len
        self.receiver.egress.pump(port, True)
        worker.join(1)
        self.assertTrue(result[0][0])
        self.clock[0] += .05
        self.relay.feed(self.sample(3))
        worker, result = self.queue_pump()
        self.receiver.egress.pump(port, True)
        self.assertEqual(port.write.call_count, 1)
        self.receiver.egress._last_write_at -= .034
        self.receiver.egress.pump(port, True)
        worker.join(1)
        self.assertTrue(result[0][0])
        self.assertEqual(port.write.call_count, 2)

    def test_real_receiver_thread_serializes_status_and_angle_writes(self):
        from test_legacy_receiver_control import STATUS
        port = Mock(in_waiting=0)
        port.read.side_effect = lambda count: (time.sleep(.002) or STATUS)
        writes = []
        def write(packet):
            writes.append((packet, threading.get_ident()))
            return len(packet)
        port.write.side_effect = write
        with patch("serial.Serial", return_value=port), \
                patch("rm_client.backend.video.receiver.discover_receiver_port", return_value="COM14"):
            control = LegacyReceiverControl()
            try:
                control.start()
                self.assertTrue(wait_until(lambda: control.stats()["ready"]))
                self.relay.set_legacy_receiver(control)
                self.arm()
                ok, _ = self.relay.pump()
                self.assertTrue(ok)
                self.assertEqual(control.stats()["angle_packets_written"], 1)
                self.assertEqual({thread_id for _, thread_id in writes}, {control._thread.ident})
                self.assertIn(encode_receiver_angles(self.sample(2)), [data for data, _ in writes])
                self.assertTrue(control.stats()["ready"])
            finally:
                control.stop()
        self.assertTrue(control.cleanup_complete)

    def test_manager_binds_shared_receiver_and_reserves_only_angle_rx(self):
        with patch("rm_client.model.polar_port_choices", return_value=["Stub", "COM13", "COM14"]), \
                patch("rm_client.model.dt7_port_choices", return_value=["Auto"]):
            registry = build_default_registry()
        angles, robot = registry.get("ControllerAngles"), registry.get("RobotLink")
        angles.enabled = robot.enabled = True
        for name, value in (("Angle RX Port", "COM13"), ("Angle TX Port", "Stub"),
                            ("Angle Output", "Legacy Receiver"), ("Forward Angles", True),
                            ("Angle Mock Writes", False)):
            angles.get_setting(name).value = value
        robot.get_setting("Port").value = "Stub"
        robot.get_setting("Allow Drive").value = True
        manager = SimpleNamespace(controller_angles=self.relay, udp=SimpleNamespace(legacy_control=self.receiver),
                                  safety=SimpleNamespace(estop_active=False), state=None,
                                  _backend_transition_blocks_work=lambda: False)
        status = BackendManager._sync_controller_angles(manager, registry)
        self.assertTrue(status["enabled"])
        self.assertTrue(status["legacy_ready"])
        self.assertFalse(status["armed"])
        angles.get_setting("Angle Output").value = "VT02 Encoder"
        status = BackendManager._sync_controller_angles(manager, registry)
        self.assertTrue(status["legacy_ready"])
        self.assertEqual(status["output_route"], "VT02 Encoder")
        angles.get_setting("Angle RX Port").value = "com14"
        status = BackendManager._sync_controller_angles(manager, registry)
        self.assertFalse(status["enabled"])
        self.assertIn("Legacy receiver", status["last_error"])

    def test_worker_opens_only_com13_and_uses_existing_receiver_for_tx(self):
        chunks = queue.Queue()
        rx = Mock(in_waiting=0)
        rx.read.side_effect = lambda count: chunks.get_nowait() if not chunks.empty() else b""
        factory = Mock(return_value=rx)
        relay = ControllerAngleRelay(serial_factory=factory)
        self.addCleanup(relay.wait_closed, 1)
        self.addCleanup(relay.close)
        relay.set_legacy_receiver(self.receiver)
        relay.configure(self.config, True)
        chunks.put(self.sample(1))
        self.assertTrue(wait_until(lambda: relay.stats()["valid"]))
        self.assertTrue(relay.arm()[0])
        chunks.put(self.sample(2))
        self.assertTrue(wait_until(lambda: self.receiver.egress._pending is not None))
        self.assertEqual(relay.owned_ports, ("COM13",))
        port = Mock()
        port.write.side_effect = len
        self.receiver.egress.pump(port, True)
        self.assertTrue(wait_until(lambda: relay.forwarded == 1))
        factory.assert_called_once_with(port="COM13", baudrate=115200, timeout=0, write_timeout=.020)

    def test_receiver_stopping_rejects_new_angles_even_before_close(self):
        control = LegacyReceiverControl()
        control._state = "ready"
        control._last_status_at = time.monotonic()
        control._port = "COM14"
        control._serial = Mock()
        control.request_stop()
        self.assertEqual(control.owned_port, "COM14")
        with self.assertRaises(IOError):
            control.write_angles(SOURCE, lambda: True)
        control._close_serial()
        self.assertEqual(control.owned_port, "")


if __name__ == "__main__":
    unittest.main()
