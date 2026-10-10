"""Year-neutral protobuf wire primitives. No topics or competition policy."""
from __future__ import annotations
import struct
from typing import Any

def encode_varint(value: int) -> bytes:
    value &= 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return encode_varint((field << 3) | wire)


def encode_uint(field: int, value: int) -> bytes:
    return _tag(field, 0) + encode_varint(max(0, int(value)) & 0xFFFFFFFFFFFFFFFF)


def encode_int(field: int, value: int) -> bytes:
    return _tag(field, 0) + encode_varint(int(value) & 0xFFFFFFFFFFFFFFFF)


def encode_bool(field: int, value: bool) -> bytes:
    return encode_uint(field, 1 if value else 0)


def encode_float(field: int, value: float) -> bytes:
    return _tag(field, 5) + struct.pack("<f", float(value))


def encode_bytes(field: int, data: bytes) -> bytes:
    data = bytes(data)
    return _tag(field, 2) + encode_varint(len(data)) + data


def encode_string(field: int, text: str) -> bytes:
    return encode_bytes(field, text.encode("utf-8"))


def encode_packed_uints(field: int, values: list[int]) -> bytes:
    payload = b"".join(encode_varint(max(0, int(v)) & 0xFFFFFFFFFFFFFFFF) for v in values)
    return _tag(field, 2) + encode_varint(len(payload)) + payload


def encode_packed_ints(field: int, values: list[int]) -> bytes:
    payload = b"".join(encode_varint(int(v) & 0xFFFFFFFFFFFFFFFF) for v in values)
    return _tag(field, 2) + encode_varint(len(payload)) + payload


def _read_varint(data: bytes, index: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    while index < len(data) and shift <= 63:
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value & 0xFFFFFFFFFFFFFFFF, index
        shift += 7
    return None


def decode_fields(data: bytes) -> dict[int, list[Any]]:
    """通用 protobuf 字段解析：field -> [value]，值类型为 int/bytes。"""
    values: dict[int, list[Any]] = {}
    index = 0
    while index < len(data):
        key = _read_varint(data, index)
        if key is None:
            break
        tag, index = key
        field, wire_type = tag >> 3, tag & 0x07
        if field <= 0:
            break
        if wire_type == 0:
            item = _read_varint(data, index)
            if item is None:
                break
            value, index = item
        elif wire_type == 1:
            if index + 8 > len(data):
                break
            value = data[index:index + 8]
            index += 8
        elif wire_type == 2:
            length_info = _read_varint(data, index)
            if length_info is None:
                break
            length, index = length_info
            if length < 0 or index + length > len(data):
                break
            value = data[index:index + length]
            index += length
        elif wire_type == 5:
            if index + 4 > len(data):
                break
            value = data[index:index + 4]
            index += 4
        else:
            break
        values.setdefault(field, []).append(value)
    return values


def _u(fields: dict[int, list[Any]], field: int, default: int = 0) -> int:
    values = fields.get(field)
    if not values:
        return default
    value = values[-1]
    return int(value) if isinstance(value, int) else default


def _i(fields: dict[int, list[Any]], field: int, default: int = 0) -> int:
    values = fields.get(field)
    if not values:
        return default
    value = values[-1]
    if not isinstance(value, int):
        return default
    if value >= 1 << 63:
        value -= 1 << 64
    value &= 0xFFFFFFFF
    if value >= 1 << 31:
        value -= 1 << 32
    return value


def _f(fields: dict[int, list[Any]], field: int, default: float = 0.0) -> float:
    values = fields.get(field)
    if not values:
        return default
    value = values[-1]
    if isinstance(value, bytes) and len(value) == 4:
        return float(struct.unpack("<f", value)[0])
    return float(value) if isinstance(value, int) else default


def _b(fields: dict[int, list[Any]], field: int) -> bytes:
    values = fields.get(field)
    if not values:
        return b""
    value = values[-1]
    return bytes(value) if isinstance(value, bytes) else b""


def _s(fields: dict[int, list[Any]], field: int, default: str = "") -> str:
    return _b(fields, field).decode("utf-8", errors="replace") or default


def _bool(fields: dict[int, list[Any]], field: int, default: bool = False) -> bool:
    return bool(_u(fields, field, 1 if default else 0))


def _packed(fields: dict[int, list[Any]], field: int) -> list[int]:
    out: list[int] = []
    for value in fields.get(field, ()):
        if isinstance(value, int):
            out.append(value)
        else:
            index = 0
            while index < len(value):
                item = _read_varint(bytes(value), index)
                if item is None:
                    break
                number, index = item
                out.append(number)
    return out


def _packed_ints(fields: dict[int, list[Any]], field: int) -> list[int]:
    out: list[int] = []
    for value in fields.get(field, ()):
        if isinstance(value, int):
            out.append(value)
        else:
            index = 0
            while index < len(value):
                item = _read_varint(bytes(value), index)
                if item is None:
                    break
                number, index = item
                if number >= 1 << 63:
                    number -= 1 << 64
                number &= 0xFFFFFFFF
                if number >= 1 << 31:
                    number -= 1 << 32
                out.append(number)
    return out


def _sub(fields: dict[int, list[Any]], field: int) -> list[dict[int, list[Any]]]:
    return [decode_fields(bytes(v)) for v in fields.get(field, ()) if isinstance(v, bytes)]

