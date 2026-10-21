"""Unregistered V2 wire foundation against independent synthetic fixtures.

No broker, Qt, device, model, or state adapter is constructed. The fixture is a
reviewed transcription of official V2 fields encoded without production code.
It is not a real official-client capture or interoperability qualification.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import struct
import unittest

from rm_client import referee_profiles
from rm_client.backend.referee import registry
from rm_client.backend.referee.rm2026 import codec as v1
from rm_client.backend.referee.rm2026 import contract as v1_contract
from rm_client.backend.referee.rm2026_v2 import codec, contract
from rm_client.backend.referee.validation import MAX_FIELDS, MAX_PAYLOAD_BYTES

FIXTURE = json.loads((Path(__file__).with_name("fixtures") / "referee_v2_wire.json").read_text())


def literal_varint(value):
    """Independent test encoder; deliberately does not import production wire."""
    value &= (1 << 64) - 1
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def literal_uint(number, value):
    return literal_varint(number * 8) + literal_varint(value)


def restore_bytes(value):
    if isinstance(value, dict):
        if set(value) == {"hex"}:
            return bytes.fromhex(value["hex"])
        return {key: restore_bytes(item) for key, item in value.items()}
    return value


class RefereeV2CodecTests(unittest.TestCase):
    def test_source_and_version_are_pinned_with_explicit_partial_registration(self):
        self.assertEqual(contract.SOURCE_SHA256, FIXTURE["source_sha256"])
        self.assertEqual(codec.PROTOCOL_VERSION, "2.0.0")
        self.assertEqual(v1.PROTOCOL_VERSION, "1.3.1")
        self.assertEqual(referee_profiles.DEFAULT_PROFILE, "rm2026-v1.3.1")
        self.assertEqual(referee_profiles.supported_profiles(),
                         ("rm2026-v1.3.1", "rm2026-v1.1.0-student-readonly", "rm2026-v2.0.0"))
        for name in ("rm2026-v2", "rm2026-v2.0", "RM2026-V2.0.0", "2.0.0", "rm2027-v1.0.0"):
            with self.subTest(profile=name), self.assertRaises(referee_profiles.UnsupportedRefereeProfile):
                registry.get_profile(name)

    def test_all_36_topics_have_exact_directions_rates_and_disposition(self):
        expected = {row["topic"]: (row["direction"], row["rate"], row["section"])
                    for row in FIXTURE["topics"]}
        self.assertEqual(contract.TOPICS, expected)
        self.assertEqual(len(codec.UPLINK_MESSAGES), 11)
        self.assertEqual(len(codec.DOWNLINK_MESSAGES), 25)
        self.assertEqual(len(codec.DECODABLE_MESSAGES), 25)
        self.assertEqual(codec.UPLINK_MESSAGES & codec.DOWNLINK_MESSAGES, frozenset())
        self.assertEqual(codec.ALL_MESSAGES, frozenset(expected))
        self.assertEqual(contract.MAX_QOS, 1)
        self.assertTrue(all(row["max_qos"] == 1 for row in FIXTURE["topics"]))
        self.assertEqual(contract.TOPICS["AirSupportCommand"][1], "触发式")
        self.assertIn("1.3.1", contract.TOPICS["MapClickCmd"][1])

    def test_all_verified_field_indexes_are_independent_exact_transcriptions(self):
        expected = {
            row["topic"]: {field["number"]: (field["name"], field["type"],
                field["cardinality"] == "repeated") for field in row["fields"]}
            for row in FIXTURE["topics"] if row["disposition"] in {"encoded", "decoded"}
        }
        self.assertEqual({key: value for key, value in contract.FIELDS.items()
                          if key not in {"RadarInfoToClient", "RadarSingleRobotInfo"}}, expected)
        self.assertEqual(contract.ALIASES, {("RadarInfoToClient", "robot_info"): "robots"})
        self.assertTrue(all(kind in {"uint32", "uint64", "int32", "float", "bool", "bytes", "string"}
                            for fields in expected.values() for _, kind, _ in fields.values()))

    def test_all_24_decodable_topics_match_independent_golden_bytes(self):
        for row in FIXTURE["topics"]:
            if row["disposition"] != "decoded":
                continue
            with self.subTest(topic=row["topic"]):
                expected = restore_bytes(row["expected"])
                expected["__present__"] = frozenset(field["number"] for field in row["fields"])
                self.assertEqual(codec.decode_message(row["topic"], bytes.fromhex(row["wire_hex"])), expected)

    def test_all_11_uplink_encoders_match_independent_golden_bytes(self):
        for row in FIXTURE["topics"]:
            if row["disposition"] != "encoded":
                continue
            with self.subTest(topic=row["topic"]):
                actual = getattr(codec, row["encoder"])(**restore_bytes(row["arguments"]))
                self.assertEqual(actual, bytes.fromhex(row["wire_hex"]))
                self.assertEqual(codec.decode_message(row["topic"], actual), {})

    def test_added_fields_decode_alone_and_do_not_become_v1_authority(self):
        game = codec.decode_message("GameStatus", b"\x48\x02\x50\x09")
        self.assertEqual((game["game_result"], game["end_reason"], game["__present__"]),
                         (2, 9, frozenset({9, 10})))
        self.assertEqual(v1.decode_message("GameStatus", b"\x48\x02\x50\x09"), {})
        sentry = codec.decode_message("SentryStatusSync", b"\x18\x01")
        self.assertIs(sentry["is_powered"], True)
        self.assertEqual(sentry["__present__"], frozenset({3}))
        self.assertEqual(v1.decode_message("SentryStatusSync", b"\x18\x01"), {})

    def test_omitted_fields_and_explicit_zero_false_have_distinct_presence(self):
        omitted = codec.decode_message("GameStatus", b"\x08\x01")
        zero = codec.decode_message("GameStatus", b"\x48\x00\x50\x00")
        self.assertEqual(omitted["game_result"], 0)
        self.assertEqual(omitted["end_reason"], 0)
        self.assertEqual(omitted["__present__"], frozenset({1}))
        self.assertEqual(zero["game_result"], 0)
        self.assertEqual(zero["__present__"], frozenset({9, 10}))
        false = codec.decode_message("SentryStatusSync", b"\x18\x00")
        self.assertIs(false["is_powered"], False)
        self.assertEqual(false["__present__"], frozenset({3}))
        self.assertEqual(codec.decode_message("SentryStatusSync", b"\x08\x01")["__present__"],
                         frozenset({1}))

    def test_settlement_sentinel_is_transmitted_not_synthesized_or_filtered(self):
        data = codec.decode_message("GameStatus", b"\x28\x04\x48\xff\x01\x50\xff\x01")
        self.assertEqual((data["current_stage"], data["game_result"], data["end_reason"]), (4, 255, 255))
        # Stage applicability and outcome enum policy are the later state owner's job.
        raw = codec.decode_message("GameStatus", b"\x28\x04\x48\x02\x50\x09")
        self.assertEqual((raw["game_result"], raw["end_reason"]), (2, 9))

    def test_command_values_remain_field_one_and_policy_is_separate(self):
        self.assertEqual(contract.SENTRY_COMMAND_IDS, frozenset({1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}))
        self.assertEqual(contract.AIR_SUPPORT_COMMAND_IDS, frozenset({0, 1, 2, 3}))
        for value in contract.SENTRY_COMMAND_IDS:
            self.assertEqual(codec.encode_sentry_ctrl_command(value), bytes((8, value)))
        for value in contract.AIR_SUPPORT_COMMAND_IDS:
            self.assertEqual(codec.encode_air_support_command(value), bytes((8, value)))
        self.assertNotIn(2, contract.SENTRY_COMMAND_IDS)
        self.assertEqual(codec.encode_sentry_ctrl_command(2), b"\x08\x02")
        self.assertEqual(codec.encode_air_support_command(255), b"\x08\xff\x01")
        status = codec.decode_message("AirSupportStatusSync", b"\x28\x02")
        self.assertEqual((status["shooter_status"], status["__present__"]), (2, frozenset({5})))

    def test_radar_descriptor_wrapper_and_explicit_zero_presence(self):
        self.assertEqual(contract.UNAVAILABLE_MESSAGES, frozenset())
        self.assertEqual(contract.FIELDS["RadarInfoToClient"],
                         {1: ("robot_info", "RadarSingleRobotInfo", True)})
        # Synthetic bytes from official213's recovered descriptor, not a capture.
        data = codec.decode_message("RadarInfoToClient", bytes.fromhex(
            "0a07086410c80118020a06080010001800"))
        self.assertEqual(data["robots"], [
            {"target_pos_x": 100, "target_pos_y": 200, "is_high_light": 2,
             "__present__": frozenset({1, 2, 3})},
            {"target_pos_x": 0, "target_pos_y": 0, "is_high_light": 0,
             "__present__": frozenset({1, 2, 3})}])
        self.assertEqual(data["__present__"], frozenset({1}))
        for raw in (b"", b"\x08\x01", b"\x0a\x02\x08", b"\x0a\x02\x0a\x00"):
            self.assertEqual(codec.decode_message("RadarInfoToClient", raw), {})
        self.assertEqual(codec.decode_message("RadarInfoToClient", b"\x0a\x00")
                         ["robots"][0]["__present__"], frozenset())

    def test_repeated_signed_int32_accepts_packed_unpacked_and_mixed(self):
        for name, number, field in (("GlobalUnitStatus", 12, "robot_bullets"),
                                    ("GlobalSpecialMechanism", 2, "mechanism_time_sec"),
                                    ("RobotPathPlanInfo", 4, "offset_x"),
                                    ("RobotPathPlanInfo", 5, "offset_y")):
            with self.subTest(topic=name, field=field):
                packed = literal_varint(number * 8 + 2) + b"\x0b" + literal_varint(-1) + b"\x02"
                unpacked = literal_uint(number, -1) + literal_uint(number, 2)
                self.assertEqual(codec.decode_message(name, packed)[field], [-1, 2])
                self.assertEqual(codec.decode_message(name, unpacked)[field], [-1, 2])
                self.assertEqual(codec.decode_message(name, unpacked + packed)[field], [-1, 2, -1, 2])

    def test_signed_scalar_and_uint64_boundaries(self):
        data = codec.decode_message("GameStatus", literal_uint(6, -(1 << 31)) + literal_uint(7, -1))
        self.assertEqual((data["stage_countdown_sec"], data["stage_elapsed_sec"]), (-(1 << 31), -1))
        self.assertEqual(codec.decode_message("GlobalLogisticsStatus", literal_uint(2, (1 << 64) - 1))
                         ["total_economy_obtained"], (1 << 64) - 1)

    def test_repeated_unsigned_packed_unpacked_and_empty(self):
        for raw, expected in ((b"\x5a\x02\x00\x07", [0, 7]),
                              (b"\x58\x00\x58\x07", [0, 7]), (b"\x5a\x00", [])):
            result = codec.decode_message("GlobalUnitStatus", raw)
            self.assertEqual(result["robot_health"], expected)
            self.assertEqual(result["__present__"], frozenset({11}))

    def test_unknown_fields_are_forward_compatible_but_not_authority(self):
        unknown = literal_uint(100, 7)
        self.assertEqual(codec.decode_message("GameStatus", unknown), {})
        data = codec.decode_message("GameStatus", b"\x28\x04" + unknown)
        self.assertEqual(data["current_stage"], 4)
        self.assertEqual(data["__present__"], frozenset({5, 100}))
        self.assertEqual(codec.decode_message("GameStatus", b"\x28\x04" + b"\xa2\x06\x02\x01"), {})

    def test_singular_last_value_and_unknown_topic(self):
        self.assertEqual(codec.decode_message("GameStatus", b"\x48\x01\x48\x02")["game_result"], 2)
        self.assertEqual(codec.decode_message("Unknown", b"\x08\x01"), {})
        self.assertEqual(codec.decode_message(" GameStatus ", b"\x28\x04")["current_stage"], 4)
        self.assertEqual(codec.topic_message_name(" /prefix/GameStatus/ "), "GameStatus")
        self.assertEqual(codec.topic_message_name("/prefix/Unknown"), "")

    def test_malformed_wire_is_rejected_without_partial_success(self):
        bad_suffixes = (b"\x80", b"\x08", b"\x12\x05x", b"\x1d\x00",
                        b"\x19\x00", b"\x00\x01", b"\x0b", b"\x0e",
                        b"\x08" + b"\xff" * 10, b"\x08" + b"\x80" * 10)
        for suffix in bad_suffixes:
            with self.subTest(suffix=suffix):
                self.assertEqual(codec.decode_message("GameStatus", b"\x28\x04" + suffix), {})
        self.assertEqual(codec.decode_message("GameStatus", b""), {})

    def test_wrong_known_wire_type_is_rejected_for_every_flat_schema(self):
        for name in codec.DECODABLE_MESSAGES:
            for number, (_, kind, repeated) in contract.FIELDS[name].items():
                with self.subTest(topic=name, number=number):
                    wrong = 0 if kind in {"bytes", "string", "float"} else 5
                    payload = literal_varint(number * 8 + wrong) + (b"\x00" if wrong == 0 else bytes(4))
                    self.assertEqual(codec.decode_message(name, payload), {})

    def test_uint32_scalar_and_packed_overflow_rejected(self):
        self.assertEqual(codec.decode_message("GameStatus", literal_uint(9, 1 << 32)), {})
        packed = literal_varint(1 << 32)
        self.assertEqual(codec.decode_message("GlobalUnitStatus", b"\x5a" + bytes([len(packed)]) + packed), {})
        self.assertEqual(codec.decode_message("GlobalUnitStatus", b"\x5a\x01\x80"), {})

    def test_nonfinite_float_and_invalid_utf8_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                self.assertEqual(codec.decode_message("RobotPosition", b"\x0d" + struct.pack("<f", value)), {})
        self.assertEqual(codec.decode_message("Event", b"\x12\x01\xff"), {})

    def test_payload_and_field_count_bounds_retained(self):
        self.assertEqual(codec.decode_message("GameStatus", b"\x08\x00" * (MAX_FIELDS + 1)), {})
        self.assertEqual(codec.decode_message("CustomByteBlock", bytes(MAX_PAYLOAD_BYTES + 1)), {})

    def test_authority_enums_and_custom_block_bounds_retained(self):
        self.assertEqual(codec.decode_message("GameStatus", b"\x28\x06"), {})
        self.assertEqual(codec.decode_message("DeployModeStatusSync", b"\x08\x02"), {})
        for size in (0, 300, 301):
            raw = b"\x0a" + literal_varint(size) + bytes(size)
            data = codec.decode_message("CustomByteBlock", raw)
            if size <= 300:
                self.assertEqual(data["data"], bytes(size))
                self.assertEqual(data["__present__"], frozenset({1}))
            else:
                self.assertEqual(data, {})

    def test_unchanged_encoders_keep_legacy_bytes_and_bounds(self):
        for row in FIXTURE["topics"]:
            if row["disposition"] == "encoded":
                with self.subTest(topic=row["topic"]):
                    self.assertIs(getattr(codec, row["encoder"]), getattr(v1, row["encoder"]))
                    self.assertEqual(getattr(codec, row["encoder"])(**restore_bytes(row["arguments"])),
                                     getattr(v1, row["encoder"])(**restore_bytes(row["arguments"])))
        self.assertEqual(codec.encode_custom_control(bytes(30)), b"\x0a\x1e" + bytes(30))
        with self.assertRaises(ValueError):
            codec.encode_custom_control(bytes(31))
        with self.assertRaises(ValueError):
            codec.encode_map_click_cmd(robot_id=bytes(8))
        self.assertIs(codec.encode_map_click_info_notify, codec.encode_map_click_cmd)

    def test_verified_shared_downlinks_match_v1_without_new_fields(self):
        for row in FIXTURE["topics"]:
            if row["disposition"] != "decoded":
                continue
            with self.subTest(topic=row["topic"]):
                raw = bytes.fromhex(row["wire_hex"])
                old, new = v1.decode_message(row["topic"], raw), codec.decode_message(row["topic"], raw)
                if row["topic"] == "GameStatus":
                    del new["game_result"], new["end_reason"]
                elif row["topic"] == "SentryStatusSync":
                    del new["is_powered"]
                self.assertEqual(new, old)

    def test_v2_tables_have_no_mutable_alias_into_v1(self):
        original = copy.deepcopy(v1_contract.FIELDS)
        decoders = dict(v1._DOWNLINK_DECODERS)
        self.assertIsNot(contract.FIELDS, v1_contract.FIELDS)
        for name in contract.FIELDS:
            self.assertIsNot(contract.FIELDS[name], v1_contract.FIELDS[name])
        previous = contract.FIELDS["GameStatus"][9]
        try:
            contract.FIELDS["GameStatus"][9] = ("temporary", "uint32", False)
            self.assertNotIn(9, v1_contract.FIELDS["GameStatus"])
        finally:
            contract.FIELDS["GameStatus"][9] = previous
        self.assertEqual(v1_contract.FIELDS, original)
        self.assertEqual(v1._DOWNLINK_DECODERS, decoders)


if __name__ == "__main__":
    unittest.main()
