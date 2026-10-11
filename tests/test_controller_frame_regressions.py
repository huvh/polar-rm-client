"""Offline boundary regressions for DT7 and custom-controller frames."""
from __future__ import annotations

import json
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend import cc_link as cc
from rm_client.backend import dt7_link as dt7
from rm_client.protocol import crc8, crc16


class ControllerFrameBoundaryTests(unittest.TestCase):
    def test_truncated_dt7_frames_do_not_raise(self):
        for variant in ("dji_rc_v1", "a5_tail"):
            frame = dt7.build_frame(0x2000, bytes(12), 0, frame_variant=variant)
            for end in range(len(frame)):
                self.assertIsNone(dt7.decode_dt7_frame(frame[:end]))

    def test_crc_valid_short_rc_prefix_rejected(self):
        for size in range(4):
            header = bytes((dt7.SOF_RC, size, 1))
            frame = header + bytes((dt7._crc8_init(header, 0x77),)) + bytes(size)
            frame += struct.pack("<H", dt7._crc16_init(frame, 0x1862))
            self.assertIsNone(dt7.decode_dt7_frame(frame))

    def test_dt7_wire_boundaries_round_trip(self):
        for variant, includes, size in (("dji_rc_v1", True, 251),
                                       ("a5_tail", True, 65533),
                                       ("a5_tail", False, 65535)):
            with self.subTest(variant=variant, includes=includes):
                payload = b"x" * size
                frame = dt7.build_frame(0xFFFF, payload, 0xFFFF,
                                       frame_variant=variant, datalen_includes_cmd=includes)
                decoded = dt7.decode_dt7_frame(frame, datalen_includes_cmd=includes)
                self.assertEqual(decoded["payload"], payload)
                self.assertEqual(decoded["cmd_wire"], 0xFFFF)
                with self.assertRaises(dt7.Dt7ConfigError):
                    dt7.build_frame(0xFFFF, payload + b"x", 0,
                                    frame_variant=variant, datalen_includes_cmd=includes)

    def test_no_tail_encoder_also_rejects_length_wrap(self):
        for includes, size in ((True, 65534), (False, 65536)):
            with self.assertRaises(dt7.Dt7ConfigError):
                dt7.build_frame(0x2000, bytes(size), 0, frame_variant="a5_no_tail",
                                datalen_includes_cmd=includes)

    def test_dt7_invalid_wire_identifiers_do_not_wrap(self):
        for value in (-1, 65536, True, 2.5):
            self.assertIsNone(dt7.cmd_wire_of({"cmd_wire": value}))
            with self.assertRaises(dt7.Dt7ConfigError):
                dt7.build_frame(value, b"", 0)
        for value in (-1, 256, True, 1.5):
            with self.assertRaises(dt7.Dt7ConfigError):
                dt7.build_frame(0x2000, b"", 0, protocol_version=value)

    def test_bad_explicit_command_does_not_fall_back_to_other_command(self):
        for value in (-1, 65536, True, 2.5, "8192"):
            self.assertIsNone(dt7.cmd_wire_of({"cmd_wire": value, "cmd_id_keyboard": 32}))

    def test_profile_loader_rejects_invalid_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dt7.json"
            for value in (-1, 256, True, 1.5, None):
                path.write_text(json.dumps({"protocol_version": value}), encoding="utf-8")
                self.assertTrue(dt7.load_profile(str(path))["_profile_error"])

    def test_repeat_count_layouts_are_rejected_before_packing(self):
        for layout in ("<2h", "<0h", "<1h", "< h", "<xh"):
            with self.assertRaises(dt7.Dt7ConfigError):
                dt7.validate_layout(layout, ["mouse_x"])
        self.assertEqual(dt7.validate_layout("<hhhBBHH", dt7.DEFAULT_PROFILE["payload_fields"]), 12)

    def test_malformed_profiles_refuse_without_emission(self):
        for updates in ({"payload_layout": "<2h", "payload_fields": ["mouse_x"]},
                        {"payload_layout": None}, {"payload_fields": None},
                        {"cmd_wire": 65536}, {"protocol_version": 256},
                        {"reserved_value": 65536},
                        {"payload_layout": "<B", "payload_fields": ["reserved"]}):
            profile = dict(dt7.DEFAULT_PROFILE, **updates)
            link = dt7.Dt7KeyMouseLink(profile=profile)
            self.assertFalse(link.send(now=1)[0], updates)
            self.assertEqual(link.last_frame, b"")
            self.assertEqual(link.sent, 0)

    def test_neutral_dt7_reserved_field_stays_1024(self):
        link = dt7.Dt7KeyMouseLink(profile=dict(dt7.DEFAULT_PROFILE))
        self.assertTrue(link.release(now=1)[0])
        payload = dt7.decode_dt7_frame(link.last_frame)["payload"]
        self.assertEqual(payload, bytes(10) + struct.pack("<H", 1024))
        self.assertTrue(link.wire_neutral)

    def test_cc_decode_rejects_oversized_crc_valid_frames(self):
        payload = bytes(cc.MAX_DATA_LENGTH + 1)
        header = b"\xA5" + struct.pack("<H", len(payload)) + b"\x00"
        frame = header + bytes((crc8(header),)) + b"\x06\x03" + payload
        frame += struct.pack("<H", crc16(frame))
        self.assertIsNone(cc.decode_cc_frame(frame))
        payload = payload[:-1]
        self.assertEqual(cc.decode_cc_frame(cc.encode_cc_frame(0x306, payload, 255))["data"], payload)

    def test_cc_bad_key_config_uses_safe_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            for raw in ([], [1], "wrong", True, 7, {"W": True}):
                path.write_text(json.dumps(raw), encoding="utf-8")
                self.assertEqual(cc.load_key_usage(str(path)), cc.HID_USAGE)

    def test_cc_two_key_overflow_reports_actual_dropped_names(self):
        table = {"W": 1, "FORWARD": 1, "A": 2, "SHIFT": 3}
        names = (x for x in ("W", "FORWARD", "UNKNOWN", "A", "SHIFT"))
        self.assertEqual(cc.keys_to_two_usages(names, table), (1, 2, ["UNKNOWN", "SHIFT"]))
        self.assertEqual(cc.keys_to_two_usages(["W", "BAD"], {"W": 1, "BAD": 300}),
                         (1, 0, ["BAD"]))

    def test_cc_release_still_bypasses_rate_limit(self):
        link = cc.CustomControllerLink()
        self.assertTrue(link.send_keymouse(pressed=["W"], now=1)[0])
        self.assertTrue(link.release_all(now=1.001)[0])
        self.assertTrue(link.wire_neutral)
        self.assertEqual(cc.decode_cc_frame(link.last_frame)["data"][:2], b"\x00\x00")

    def test_seeded_decoder_fuzz_never_raises(self):
        rng = random.Random(20261011)
        for size in range(160):
            for sof in (0x5A, 0xA5, 0):
                sample = bytes((sof,)) + bytes(rng.randrange(256) for _ in range(size))
                dt7.decode_dt7_frame(sample)
                cc.decode_cc_frame(sample)
        for variant in ("dji_rc_v1", "a5_tail"):
            frame = dt7.build_frame(0x2000, bytes(12), 0, frame_variant=variant)
            for index in range(len(frame)):
                damaged = bytearray(frame)
                damaged[index] ^= 0x80
                self.assertIsNone(dt7.decode_dt7_frame(bytes(damaged)))


if __name__ == "__main__":
    unittest.main()
