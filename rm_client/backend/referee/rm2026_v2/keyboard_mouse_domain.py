"""Pure KMC value-domain checks; this module grants no publication authority.

Source: RM2026 protocol V2.0.0 section 2.2.1, printed pages 48-50.
The V1.3.1 field and semantic definitions are identical. This optional V2
helper does not alter either encoder, registry, transport, or neutral path.
"""
from __future__ import annotations


def validate_keyboard_mouse_values(
    mouse_x: int = 0,
    mouse_y: int = 0,
    mouse_z: int = 0,
    left_button_down: bool = False,
    right_button_down: bool = False,
    keyboard_value: int = 0,
    mid_button_down: bool = False,
) -> None:
    """Reject coercion, out-of-range axes, and undefined keyboard bits.

    Strict built-in input types are a local API policy. The protocol supplies
    signed int32 axes, three bool states, and the sixteen defined key bits.
    A successful return says only that these seven values are well formed.
    """
    for name, value in (("mouse_x", mouse_x), ("mouse_y", mouse_y),
                        ("mouse_z", mouse_z)):
        if type(value) is not int:
            raise TypeError(f"{name} must be an int (not bool or coercible text)")
        if not -(1 << 31) <= value < (1 << 31):
            raise ValueError(f"{name} must fit signed int32")
    for name, value in (("left_button_down", left_button_down),
                        ("right_button_down", right_button_down),
                        ("mid_button_down", mid_button_down)):
        if type(value) is not bool:
            raise TypeError(f"{name} must be a bool")
    if type(keyboard_value) is not int:
        raise TypeError("keyboard_value must be an int (not bool or coercible text)")
    if not 0 <= keyboard_value <= 0xffff:
        raise ValueError("keyboard_value must use only bits 0 through 15")


def decode_keyboard_mouse_values(payload: bytes) -> dict[str, int | bool]:
    """Decode bounded protobuf defaults/last-wins, then check effective values.

    Missing values become zero/false and unknown fields follow the existing
    bounded validator. Int32 values use the existing low-32-bit signed
    protobuf interpretation, including noncanonical negative representations.
    The effective raw bool value must be 0 or 1 (a local strict policy).
    Empty input is a neutral value set, never an E-stop/publication bypass.
    """
    from .contract import FIELDS
    from ..validation import InvalidRefereePayload, validate_message
    from ..wire import _i, _u, decode_fields

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("KMC payload must be bytes-like")
    frozen = bytes(payload)
    validate_message("KeyboardMouseControl", frozen, FIELDS)
    fields = decode_fields(frozen)
    left = _u(fields, 4)
    right = _u(fields, 5)
    middle = _u(fields, 7)
    if any(value not in (0, 1) for value in (left, right, middle)):
        raise InvalidRefereePayload("effective KMC bool must be encoded as 0 or 1")
    values = {
        "mouse_x": _i(fields, 1),
        "mouse_y": _i(fields, 2),
        "mouse_z": _i(fields, 3),
        "left_button_down": bool(left),
        "right_button_down": bool(right),
        "keyboard_value": _u(fields, 6),
        "mid_button_down": bool(middle),
    }
    validate_keyboard_mouse_values(**values)
    return values
