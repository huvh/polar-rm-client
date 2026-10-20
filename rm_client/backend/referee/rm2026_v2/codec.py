"""Pure V2.0.0 foundation: 11 uplink encoders, 24 qualified downlink schemas.

The declared 25th downlink, RadarInfoToClient, is explicitly unavailable until
its incomplete official wrapper is resolved. This module does not register or
activate a profile, apply state, authorize actions, or operate a transport.
"""
from __future__ import annotations

from typing import Any

from .contract import (
    FIELDS, PROTOCOL_VERSION,
    SOURCE_PDF, SOURCE_SHA256, TOPICS, UNAVAILABLE_MESSAGES,
)
from ..rm2026 import codec as _v1
from ..validation import InvalidRefereePayload, validate_message
from ..wire import _b, _bool, _f, _i, _packed, _s, _u, decode_fields

UPLINK_MESSAGES = frozenset(name for name, spec in TOPICS.items() if spec[0] == "uplink")
DOWNLINK_MESSAGES = frozenset(name for name, spec in TOPICS.items() if spec[0] == "downlink")
ALL_MESSAGES = UPLINK_MESSAGES | DOWNLINK_MESSAGES
DECODABLE_MESSAGES = DOWNLINK_MESSAGES - UNAVAILABLE_MESSAGES

# Only flat, verified scalar contracts are enabled. The ambiguous nested Radar
# wrapper is absent from FIELDS, rather than decoded as an empty success.
_SCALAR_READERS = {
    "uint32": _u, "uint64": _u, "int32": _i, "float": _f,
    "bool": _bool, "bytes": _b, "string": _s,
}


def topic_message_name(topic: str) -> str:
    name = str(topic).strip().rstrip("/").rsplit("/", 1)[-1]
    return name if name in ALL_MESSAGES else ""


def decode_message(name: str, payload: bytes) -> dict[str, Any]:
    """Reject malformed/unknown-only/unavailable input; retain exact presence.

    Settlement fields are decoded as transmitted. Their stage-5 applicability
    belongs to the state owner; missing fields are not synthesized as 255.
    """
    name = str(name).strip()
    if name not in DECODABLE_MESSAGES:
        return {}
    payload = bytes(payload)
    try:
        validate_message(name, payload, FIELDS)
    except InvalidRefereePayload:
        return {}
    fields = decode_fields(payload)
    if not fields or not set(fields).intersection(FIELDS[name]):
        return {}
    if name == "GameStatus" and 5 in fields and _u(fields, 5) not in range(6):
        return {}
    if name == "DeployModeStatusSync" and 1 in fields and _u(fields, 1) not in {0, 1}:
        return {}
    if name == "CustomByteBlock" and len(_b(fields, 1)) > 300:
        return {}
    data = {}
    for number, (field_name, kind, repeated) in FIELDS[name].items():
        if repeated:
            values = _packed(fields, number)
            # Both packed and unpacked int32 forms need 32-bit sign extension.
            data[field_name] = [
                _i({number: [value]}, number) if kind == "int32" else value
                for value in values
            ]
        else:
            data[field_name] = _SCALAR_READERS[kind](fields, number)
    data["__present__"] = frozenset(fields)
    return data


# These public encoders are stateless and have identical V1/V2 wire contracts.
# Reuse the functions, not the legacy FIELDS or decoder globals. The legacy
# codec remains unchanged and cannot observe a V2 table mutation.
encode_keyboard_mouse_control = _v1.encode_keyboard_mouse_control
encode_custom_control = _v1.encode_custom_control
encode_map_click_cmd = _v1.encode_map_click_cmd
encode_map_click_info_notify = encode_map_click_cmd
encode_assembly_command = _v1.encode_assembly_command
encode_robot_performance_selection_command = _v1.encode_robot_performance_selection_command
encode_common_command = _v1.encode_common_command
encode_hero_deploy_mode_event_command = _v1.encode_hero_deploy_mode_event_command
encode_rune_activate_command = _v1.encode_rune_activate_command
encode_dart_command = _v1.encode_dart_command
# Enum membership and role/stage eligibility belong to the action policy. The
# wire shape stays one uint32 at field 1 for both versions.
encode_sentry_ctrl_command = _v1.encode_sentry_ctrl_command
encode_air_support_command = _v1.encode_air_support_command
