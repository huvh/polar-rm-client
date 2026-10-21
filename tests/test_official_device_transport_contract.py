"""Restored official device contracts; synthetic descriptors and writes only."""
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend import cc_link as cc, dt7_link as dt7
from rm_client.backend.radio_km_feedback import _read_counter, evaluate_radio_km_feedback, RadioKmReadback, RadioKmPolicy
from rm_client import serial_ports as ports


def device(vid, pid, **kw):
    return dict(device="COM_TEST", description="USB Serial", vid=vid, pid=pid, **kw)


class OfficialDeviceContractTests(unittest.TestCase):
    def test_verified_vk_defaults_are_not_legacy_hid(self):
        self.assertEqual(cc.keys_to_two_usages(["W", "A"]), (0x57, 0x41, []))
        self.assertEqual(cc.HID_USAGE["W"], 0x1A)
        self.assertEqual(cc.VIRTUAL_KEY["SHIFT"], 0x10)
        self.assertEqual(cc.VIRTUAL_KEY["CTRL"], 0x11)
        for key in ("ALT", "GUI", "SPACE", "ENTER"):
            self.assertNotIn(key, cc.VIRTUAL_KEY)

    def test_verified_vk_is_used_on_wire(self):
        sent = []
        link = cc.CustomControllerLink(mock_output=False, write_bytes=lambda frame: sent.append(frame) or len(frame))
        self.assertTrue(link.send_keymouse(pressed=["S", "V"], now=1)[0])
        self.assertEqual(cc.decode_cc_frame(sent[0])["data"][:2], b"\x53\x56")
        self.assertEqual(cc.keys_to_two_usages(["ALT"]), (0, 0, ["ALT"]))

    def test_missing_or_bad_key_config_falls_back_to_verified_vk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "keys.json"
            self.assertEqual(cc.load_key_usage(str(path)), cc.VIRTUAL_KEY)
            for raw in ("garbage", "[]", '{"W":true}'):
                path.write_text(raw)
                self.assertEqual(cc.load_key_usage(str(path)), cc.VIRTUAL_KEY)

    def test_legacy_hid_requires_explicit_encoding_and_raw_overrides_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "keys.json"
            path.write_text(json.dumps({"_key_encoding": "usb_hid_legacy"}))
            self.assertEqual(cc.load_key_usage(str(path)), cc.HID_USAGE)
            path.write_text(json.dumps({"w": 26}))
            table = cc.load_key_usage(str(path))
            self.assertEqual(table["W"], 26)
            self.assertEqual(table["A"], 0x41)
            path.write_text(json.dumps({"_key_encoding": "unknown"}))
            with self.assertRaises(ValueError):
                cc.load_key_usage(str(path))

    def test_sync_0302_requires_exactly_thirty_bytes_before_write(self):
        writer = Mock(side_effect=lambda b: len(b))
        link = cc.CustomControllerLink(mock_output=False, write_bytes=writer)
        for length in (0, 1, 29, 31, 100):
            self.assertFalse(link.send_robot_interact(bytes(length), now=1)[0])
        writer.assert_not_called()
        self.assertTrue(link.send_robot_interact(bytes(30), now=1)[0])
        self.assertEqual(len(cc.decode_cc_frame(writer.call_args.args[0])["data"]), 30)

    def test_async_0302_requires_exactly_thirty_bytes_before_queue(self):
        link = cc.AsyncCustomControllerLink.__new__(cc.AsyncCustomControllerLink)
        link._queue = Mock(return_value=(True, "queued"))
        for length in (0, 29, 31):
            self.assertFalse(link.send_robot_interact(bytes(length))[0])
        link._queue.assert_not_called()
        self.assertTrue(link.send_robot_interact(bytes(30))[0])
        link._queue.assert_called_once_with(0x302, bytes(30))

    def test_official_video_never_becomes_private_robot_auto(self):
        for pid in (0x001F, 0x1020):
            entry = device(0x2CA3, pid)
            self.assertLess(ports.score_port(entry), ports.AUTO_MIN_SCORE)
            with patch.object(ports, "list_serial_ports", return_value=[entry]):
                self.assertEqual(ports.resolve_port("Auto"), "Stub")
                self.assertEqual(ports.resolve_port("COM_TEST"), "COM_TEST")

    def test_mi_diagnostic_requires_exact_nonconflicting_observation(self):
        for pid, mi in ((0x001F, "04"), (0x1020, "02")):
            self.assertIn("uninitialized", ports.official_device_role(device(0x2CA3, pid, hwid=f"USB\\VID_2CA3&MI_{mi}")))
            for hwid in ("", "MI_00", f"MI_{mi} MI_01"):
                self.assertIn("unconfirmed", ports.official_device_role(device(0x2CA3, pid, hwid=hwid)))

    def test_ftdi_candidate_does_not_widen_auto_admission(self):
        entry = device(0x0403, 0x6010, manufacturer="FTDI")
        self.assertIn("purpose unverified", ports.official_device_role(entry))
        self.assertLess(ports.score_cc_port(entry), 0)
        with patch.object(ports, "list_serial_ports", return_value=[entry]):
            self.assertEqual(ports.resolve_cc_port("Auto"), "Stub")
        self.assertIn("connection unverified", ports.official_device_role(device(0xFFF0, 0x0008)))

    def test_discovery_preserves_passive_descriptor_metadata(self):
        item = SimpleNamespace(device="COM_TEST", description="USB", vid=0x2CA3, pid=0x1020,
                               serial_number="test", hwid="MI_02", interface="Video", manufacturer="DJI")
        with patch("serial.tools.list_ports.comports", return_value=[item]):
            result = ports._scan_serial_ports()[0]
        self.assertEqual((result["hwid"], result["interface"], result["manufacturer"]), ("MI_02", "Video", "DJI"))

    def test_describe_uses_nonblocking_snapshot_and_marks_uninitialized(self):
        entry = device(0x2CA3, 0x1020, hwid="MI_02")
        with patch.object(ports, "port_snapshot", return_value=[entry]), \
             patch.object(ports, "list_serial_ports", side_effect=AssertionError("No blocking scan")):
            self.assertIn("uninitialized", ports.describe_ports()[0])

    def test_reserved_policy_difference_is_preserved_and_digest_bound(self):
        self.assertEqual(dt7.DEFAULT_PROFILE["reserved_value"], 1024)
        official = dict(dt7.DEFAULT_PROFILE, reserved_value=0)
        self.assertNotEqual(dt7.profile_digest(official), dt7.profile_digest(dt7.DEFAULT_PROFILE))

    def test_nonfinite_or_out_of_range_feedback_is_unknown(self):
        for value in (float("inf"), float("-inf"), float("nan"), 1e100, -1, "bad", 2**2000):
            with self.subTest(value=str(value)[:40]):
                self.assertIsNone(_read_counter(value))
                result = evaluate_radio_km_feedback(RadioKmReadback(value, value, key_at=1),
                    requested=True, authorized=False, previous_received=7, now=1.1,
                    policy=RadioKmPolicy("?", None, "unknown"))
                self.assertEqual((result.robot_rx, result.robot_key, result.next_received), (-1, -1, 7))
                self.assertFalse(result.robot_rx_growing)
        result = evaluate_radio_km_feedback(RadioKmReadback(1, 65536, key_at=1),
            requested=True, authorized=False, previous_received=0, now=1.1,
            policy=RadioKmPolicy("?", None, "unknown"))
        self.assertEqual(result.robot_key, -1)

    def test_float32_uint32_boundary_and_existing_fractional_truncation(self):
        rounded = struct.unpack("<f", struct.pack("<f", 2**32-1))[0]
        self.assertEqual(_read_counter(rounded), 2**32)
        self.assertEqual(_read_counter(2.75), 2)
        self.assertIsNone(_read_counter(2**32+1))


if __name__ == "__main__":
    unittest.main()
