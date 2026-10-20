"""Synthetic KMC domains; no application, broker, or device is acquired."""
import unittest

from rm_client.backend.referee.rm2026_v2.keyboard_mouse_domain import validate_keyboard_mouse_values


class KeyboardMouseValuesTests(unittest.TestCase):
    def test_explicit_zero_and_defaults_are_only_value_validation(self):
        self.assertIsNone(validate_keyboard_mouse_values())
        self.assertIsNone(validate_keyboard_mouse_values(0, 0, 0, False, False, 0, False))

    def test_every_keyboard_bit_and_combinations(self):
        for value in [0, 0xffff, 0x5555, 0xaaaa] + [1 << bit for bit in range(16)]:
            with self.subTest(value=value):
                self.assertIsNone(validate_keyboard_mouse_values(keyboard_value=value))

    def test_every_sixteen_bit_mask(self):
        for value in range(65536):
            self.assertIsNone(validate_keyboard_mouse_values(keyboard_value=value))

    def test_reject_undefined_key_bits_and_negative_values(self):
        for value in [-1, -(1 << 64), 1 << 16, 0xffffffff, 1 << 64]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_keyboard_mouse_values(keyboard_value=value)

    def test_axis_signed_boundaries_and_directions(self):
        for axis in ("mouse_x", "mouse_y", "mouse_z"):
            for value in [-(1 << 31), -65536, -32769, -1, 0, 1, 32768, 65536, (1 << 31)-1]:
                with self.subTest(axis=axis, value=value):
                    self.assertIsNone(validate_keyboard_mouse_values(**{axis: value}))

    def test_reject_axis_overflow_without_clipping(self):
        for axis in ("mouse_x", "mouse_y", "mouse_z"):
            for value in [-(1 << 31)-1, 1 << 31, -(1 << 64), 1 << 64]:
                with self.subTest(axis=axis, value=value), self.assertRaises(ValueError):
                    validate_keyboard_mouse_values(**{axis: value})

    def test_integer_inputs_do_not_coerce(self):
        for field in ("mouse_x", "mouse_y", "mouse_z", "keyboard_value"):
            for value in [False, True, 0.0, 1.5, "0", "1", b"1", None, float("nan"), float("inf")]:
                with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                    validate_keyboard_mouse_values(**{field: value})

    def test_integer_subclasses_are_not_implicitly_admitted(self):
        class CoercibleInt(int):
            pass
        for field in ("mouse_x", "mouse_y", "mouse_z", "keyboard_value"):
            with self.subTest(field=field), self.assertRaises(TypeError):
                validate_keyboard_mouse_values(**{field: CoercibleInt(1)})

    def test_mouse_buttons_are_independent_bools(self):
        for mask in range(8):
            self.assertIsNone(validate_keyboard_mouse_values(
                left_button_down=bool(mask & 1), right_button_down=bool(mask & 2),
                mid_button_down=bool(mask & 4)))

    def test_button_inputs_do_not_use_truthiness(self):
        for field in ("left_button_down", "right_button_down", "mid_button_down"):
            for value in [0, 1, 2, -1, 0.0, 1.0, "", "false", "true", None, [], [1]]:
                with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                    validate_keyboard_mouse_values(**{field: value})

    def test_opposite_keys_and_all_buttons_are_not_invented_eligibility_rules(self):
        self.assertIsNone(validate_keyboard_mouse_values(
            -1, -1, -1, True, True, 0xffff, True))

    def test_no_extra_fields_are_silently_accepted(self):
        with self.assertRaises(TypeError):
            validate_keyboard_mouse_values(side_button_down=True)


from rm_client.backend.referee.rm2026_v2.keyboard_mouse_domain import decode_keyboard_mouse_values
from rm_client.backend.referee.validation import InvalidRefereePayload


def _varint(value):
    data = []
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    return bytes(data + [value])


def _scalar(field, value):
    return _varint(field << 3) + _varint(value)


class KeyboardMouseWireTests(unittest.TestCase):
    def test_missing_and_empty_use_zero_false_without_any_authority_flag(self):
        values = decode_keyboard_mouse_values(b"")
        self.assertEqual(values, {
            "mouse_x": 0, "mouse_y": 0, "mouse_z": 0,
            "left_button_down": False, "right_button_down": False,
            "keyboard_value": 0, "mid_button_down": False})
        self.assertEqual(len(values), 7)
        self.assertEqual(decode_keyboard_mouse_values(b"\x30\x01")["keyboard_value"], 1)
        self.assertIs(type(values["mouse_x"]), int)
        self.assertIs(type(values["left_button_down"]), bool)

    def test_hand_encoded_fields_are_not_swapped(self):
        payload = bytes.fromhex("0801100218032001280030ff7f3801")
        self.assertEqual(decode_keyboard_mouse_values(payload), {
            "mouse_x": 1, "mouse_y": 2, "mouse_z": 3,
            "left_button_down": True, "right_button_down": False,
            "keyboard_value": 16383, "mid_button_down": True})

    def test_signed_int32_interpretation_including_five_and_ten_byte_negative(self):
        cases = [(0, 0), (1, 1), (0x7fffffff, 2147483647),
                 (0x80000000, -2147483648), (0xffffffff, -1),
                 (1 << 32, 0), ((1 << 32)+1, 1),
                 (0xffffffff80000000, -2147483648),
                 (0xffffffffffffffff, -1)]
        for number, name in [(1, "mouse_x"), (2, "mouse_y"), (3, "mouse_z")]:
            for raw, expected in cases:
                with self.subTest(number=number, raw=raw):
                    self.assertEqual(decode_keyboard_mouse_values(_scalar(number, raw))[name], expected)
        self.assertEqual(decode_keyboard_mouse_values(bytes.fromhex("08ffffffff0f"))["mouse_x"], -1)
        self.assertEqual(decode_keyboard_mouse_values(bytes.fromhex("08ffffffffffffffffff01"))["mouse_x"], -1)

    def test_duplicate_fields_use_effective_last_values(self):
        values = decode_keyboard_mouse_values(
            _scalar(1, 8) + _scalar(1, 3) + _scalar(6, 65536) + _scalar(6, 1)
            + _scalar(4, 2) + _scalar(4, 0))
        self.assertEqual(values["mouse_x"], 3)
        self.assertEqual(values["keyboard_value"], 1)
        self.assertIs(values["left_button_down"], False)

    def test_duplicate_last_invalid_value_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_keyboard_mouse_values(_scalar(6, 1) + _scalar(6, 65536))
        with self.assertRaises(InvalidRefereePayload):
            decode_keyboard_mouse_values(_scalar(4, 0) + _scalar(4, 2))

    def test_raw_keyboard_sixteen_bit_boundaries(self):
        for value in [0, 1, 32768, 65535]:
            self.assertEqual(decode_keyboard_mouse_values(_scalar(6, value))["keyboard_value"], value)
        for value in [65536, 0xffffffff]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_keyboard_mouse_values(_scalar(6, value))

    def test_effective_raw_bool_is_strict_zero_or_one(self):
        for field, name in [(4, "left_button_down"), (5, "right_button_down"), (7, "mid_button_down")]:
            for value in [0, 1]:
                self.assertIs(decode_keyboard_mouse_values(_scalar(field, value))[name], bool(value))
            for value in [2, 3, 0xffffffff, 0xffffffffffffffff]:
                with self.subTest(field=field, value=value), self.assertRaises(InvalidRefereePayload):
                    decode_keyboard_mouse_values(_scalar(field, value))

    def test_unknown_fields_are_ignored_after_bounded_parse(self):
        unknown = bytes.fromhex("4001") + bytes.fromhex("4a03616263")
        unknown += bytes.fromhex("550000807f") + bytes.fromhex("590000000000000000")
        values = decode_keyboard_mouse_values(unknown + _scalar(6, 42))
        self.assertEqual(values["keyboard_value"], 42)
        self.assertEqual(decode_keyboard_mouse_values(unknown), decode_keyboard_mouse_values(b""))

    def test_bytes_like_input_is_detached(self):
        payload = bytearray(b"\x30\x01")
        values = decode_keyboard_mouse_values(payload)
        payload[-1] = 2
        self.assertEqual(values["keyboard_value"], 1)
        self.assertEqual(decode_keyboard_mouse_values(memoryview(payload))["keyboard_value"], 2)
        for payload in [None, "", 0, 1000, [], [8, 1]]:
            with self.subTest(payload=payload), self.assertRaises(TypeError):
                decode_keyboard_mouse_values(payload)

    def test_existing_uint32_overflow_is_still_rejected(self):
        for value in [1 << 32, 0xffffffffffffffff]:
            with self.assertRaises(InvalidRefereePayload):
                decode_keyboard_mouse_values(_scalar(6, value))
        with self.assertRaises(InvalidRefereePayload):
            decode_keyboard_mouse_values(_scalar(6, 1 << 32) + _scalar(6, 0))

    def test_existing_wrong_wire_types_and_truncation_are_rejected(self):
        for payload in [b"\x0d\0\0\0\0", b"\x22\x01\0", b"\x08", b"\x08\x80", b"\x00\0", b"\x4a\x05x"]:
            with self.subTest(payload=payload), self.assertRaises(InvalidRefereePayload):
                decode_keyboard_mouse_values(payload)

    def test_existing_uint64_varint_limit_is_preserved(self):
        for payload in [b"\x08" + b"\xff"*9 + b"\x02", b"\x08" + b"\x80"*10 + b"\x00"]:
            with self.assertRaises(InvalidRefereePayload):
                decode_keyboard_mouse_values(payload)

    def test_existing_field_count_limit_is_preserved_for_unknowns(self):
        self.assertEqual(decode_keyboard_mouse_values(b"\x40\x00"*16384), decode_keyboard_mouse_values(b""))
        with self.assertRaises(InvalidRefereePayload):
            decode_keyboard_mouse_values(b"\x40\x00"*16385)

    def test_existing_payload_size_limit_is_preserved(self):
        length = (1 << 20) - 4
        self.assertEqual(decode_keyboard_mouse_values(b"\x4a"+_varint(length)+b"x"*length), decode_keyboard_mouse_values(b""))
        with self.assertRaises(InvalidRefereePayload):
            decode_keyboard_mouse_values(b"x"*((1 << 20)+1))


if __name__ == "__main__":
    unittest.main()
