"""Bounded, strict protobuf validation, independent of year and UI threads."""
from __future__ import annotations

import math
import struct
from typing import Any

MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_FIELDS = 16384


class InvalidRefereePayload(ValueError):
    pass


def _varint(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if index >= len(data):
            raise InvalidRefereePayload("truncated varint")
        byte = data[index]
        index += 1
        if shift == 63 and byte > 1:
            raise InvalidRefereePayload("varint exceeds uint64")
        value |= (byte & 0x7f) << shift
        if byte < 128:
            return value, index
    raise InvalidRefereePayload("overlong varint")


def parse_wire(data: bytes) -> list[tuple[int, int, Any]]:
    if len(data) > MAX_PAYLOAD_BYTES:
        raise InvalidRefereePayload("payload exceeds 1 MiB")
    fields = []
    index = 0
    while index < len(data):
        tag, index = _varint(data, index)
        field, wire = tag >> 3, tag & 7
        if not 0 < field < (1 << 29):
            raise InvalidRefereePayload("invalid field number")
        if wire == 0:
            value, index = _varint(data, index)
        elif wire in {1, 2, 5}:
            length = 8 if wire == 1 else 4
            if wire == 2:
                length, index = _varint(data, index)
            if index + length > len(data):
                raise InvalidRefereePayload("truncated field")
            value = data[index:index + length]
            index += length
        else:
            raise InvalidRefereePayload("unsupported wire type")
        fields.append((field, wire, value))
        if len(fields) > MAX_FIELDS:
            raise InvalidRefereePayload("too many fields")
    return fields


def validate_message(name: str, payload: bytes, contracts: dict, *, depth: int = 0) -> None:
    if depth > 4:
        raise InvalidRefereePayload("nested message depth exceeds limit")
    contract = contracts[name]
    for number, wire, value in parse_wire(payload):
        spec = contract.get(number)
        if spec is None:
            continue  # Protobuf's forward-compatible unknown-field rule.
        _field_name, kind, repeated = spec
        expected = 5 if kind == "float" else 1 if kind == "double" else 2 if kind in {"bytes", "string"} or kind in contracts else 0
        if repeated and wire == 2 and expected in {0, 1, 5}:
            if expected == 0:
                index = 0
                while index < len(value):
                    item, index = _varint(value, index)
                    if kind == "uint32" and item > 0xffffffff:
                        raise InvalidRefereePayload("packed uint32 overflow")
            elif len(value) % (8 if expected == 1 else 4):
                raise InvalidRefereePayload("truncated packed scalar")
            continue
        if wire != expected:
            raise InvalidRefereePayload(f"{name}.{number}: wrong wire type")
        if kind == "uint32" and value > 0xffffffff:
            raise InvalidRefereePayload("uint32 overflow")
        if kind in {"float", "double"} and not math.isfinite(struct.unpack("<f" if kind == "float" else "<d", value)[0]):
            raise InvalidRefereePayload("nonfinite scalar")
        if kind == "string":
            try:
                value.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise InvalidRefereePayload("invalid UTF-8") from exc
        if kind in contracts:
            validate_message(kind, value, contracts, depth=depth + 1)
