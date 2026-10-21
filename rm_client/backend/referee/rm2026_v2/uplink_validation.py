"""Reviewed V2 value domains and requester roles; never publication permission.

Official protocol V2.0.0 §2.2 and student 12.0.0.213 native command dispatch.
Dart and Sentry are requested by the aerial operator, not their target IDs.
The two-second receipt bound is local policy, not a vendor timing guarantee.
"""
from __future__ import annotations

import math
from typing import Any

from ..validation import InvalidRefereePayload, validate_message
from ..wire import _b, _bool, _f, _u, decode_fields
from .contract import FIELDS, AIR_SUPPORT_COMMAND_IDS, SENTRY_COMMAND_IDS
from .keyboard_mouse_domain import decode_keyboard_mouse_values
from .observations import WireSnapshot

_INFANTRY = frozenset({3, 4, 5, 103, 104, 105})
_HERO = frozenset({1, 101})
_AIR = frozenset({6, 106})
ROLE_IDS = {
    "AssemblyCommand": frozenset({2, 102}),
    "HeroDeployModeEventCommand": _HERO,
    "RuneActivateCommand": _INFANTRY,
    "DartCommand": _AIR,
    "RobotPerformanceSelectionCommand": _INFANTRY | _HERO | _AIR,
    "SentryCtrlCommand": _AIR,
    "AirSupportCommand": _AIR,
}


def fresh_integer(snapshot: WireSnapshot | None, message: str, field: str, now: float) -> int:
    if type(snapshot) is not WireSnapshot:
        raise InvalidRefereePayload("current V2 wire observations required")
    observation = snapshot.get(message, field)
    if observation is None:
        raise InvalidRefereePayload(f"missing {message}.{field}")
    try:
        valid = (type(now) in (int, float) and math.isfinite(now)
                 and type(observation.received_at) in (int, float)
                 and math.isfinite(observation.received_at)
                 and observation.received_at >= 0
                 and 0 <= now - observation.received_at <= 2.0)
    except (OverflowError, TypeError, ValueError):
        valid = False
    if not valid:
        raise InvalidRefereePayload(f"stale or invalid {message}.{field} receipt")
    if type(observation.value) is not int:
        raise InvalidRefereePayload(f"invalid {message}.{field} integer")
    return observation.value


def is_sentry_map(payload: bytes) -> bool:
    # Bound parsing BEFORE routing. Unvalidated arbitrarily long protobuf must
    # not be decoded merely to choose which safety guard to invoke.
    validate_message("MapClickCmd", payload, FIELDS)
    fields = decode_fields(payload)
    return _u(fields, 1) == 2 or any(value in {7, 107} for value in _b(fields, 2))


def validate_uplink(topic: str, payload: bytes, *, snapshot: WireSnapshot | None = None,
                    now: float | None = None, client_id: str | None = None,
                    require_identity: bool = False) -> dict[str, Any]:
    """Validate effective last-wins values, then optional current wire identity.

    Mock demonstrations may omit identity; real final enqueue must require it.
    This function neither grants Safety capabilities nor consumes a token.
    """
    validate_message(topic, payload, FIELDS)
    fields = decode_fields(payload)
    if topic == "KeyboardMouseControl":
        return decode_keyboard_mouse_values(payload)
    values = {name: (_b(fields, number) if kind == "bytes" else
                     _f(fields, number) if kind == "float" else
                     _bool(fields, number) if kind == "bool" else _u(fields, number))
              for number, (name, kind, _) in FIELDS[topic].items()}
    def member(number: int, allowed: set | frozenset | range, label: str) -> None:
        if _u(fields, number) not in allowed:
            raise InvalidRefereePayload(f"{topic}.{label}: unsupported value")
    if topic == "CustomControl" and len(_b(fields, 1)) > 30:
        raise InvalidRefereePayload("CustomControl payload exceeds 30 bytes")
    elif topic == "AssemblyCommand":
        member(1, {0, 1, 2}, "operation")
        if _u(fields, 1) == 0 or 2 in fields:
            member(2, range(1, 5), "difficulty")
    elif topic == "HeroDeployModeEventCommand":
        member(1, {0, 1}, "mode")
    elif topic == "RuneActivateCommand":
        member(1, {1}, "activate")
    elif topic == "DartCommand":
        member(1, range(1, 6), "target_id")
        member(2, {0, 1}, "open")
        member(3, {0, 1}, "launch_confirm")
    elif topic == "RobotPerformanceSelectionCommand":
        member(1, range(5), "shooter")
        member(2, range(5), "chassis")
        member(3, {0, 1}, "sentry_control")
    elif topic == "CommonCommand":
        member(1, range(1, 7), "cmd_type")
        if _u(fields, 1) == 1 and (_u(fields, 2) == 0 or _u(fields, 2) % 10):
            raise InvalidRefereePayload("CommonCommand local 17mm quantity must be a positive multiple of 10")
        if _u(fields, 1) >= 3 and _u(fields, 2) != 0:
            raise InvalidRefereePayload("CommonCommand 3..6 require param=0; remote ammo is one fixed package")
    elif topic == "SentryCtrlCommand":
        member(1, SENTRY_COMMAND_IDS, "command_id")
    elif topic == "AirSupportCommand":
        member(1, AIR_SUPPORT_COMMAND_IDS, "command_id")
    elif topic == "MapClickCmd":
        member(1, {0, 1, 2}, "is_send_all")
        if len(_b(fields, 2)) != 7:
            raise InvalidRefereePayload("MapClickCmd robot_id must contain exactly seven bytes")
        if _u(fields, 3) == 4:
            raise InvalidRefereePayload("V2 custom map mark unavailable: official 213 runtime mode conflicts with protocol 4/5")
        member(3, {1, 2, 3}, "category")
        member(6, {1, 2}, "marking mode")
        if any(value and value not in {*range(1, 10), *range(101, 110)} for value in _b(fields, 2)):
            raise InvalidRefereePayload("MapClickCmd recipient is not an official robot ID")
    if not require_identity:
        return values
    if topic in ROLE_IDS or (topic == "MapClickCmd" and is_sentry_map(payload)):
        if (type(snapshot) is not WireSnapshot or snapshot.profile_id != "rm2026-v2.0.0"
                or snapshot.client_id != str(client_id)):
            raise InvalidRefereePayload("current V2 wire identity must match configured ClientId")
        robot_id = fresh_integer(snapshot, "RobotStaticStatus", "robot_id", now)
        if str(robot_id) != str(client_id):
            raise InvalidRefereePayload("observed robot ID must match configured ClientId")
        if topic in ROLE_IDS and robot_id not in ROLE_IDS[topic]:
            raise InvalidRefereePayload(f"{topic}: requester role is not supported")
        if topic == "RobotPerformanceSelectionCommand":
            own = (_u(fields, 1), _u(fields, 2))
            if robot_id in _AIR:
                if any(own):
                    raise InvalidRefereePayload("aerial performance command is sentry-mode only")
                if fresh_integer(snapshot, "GameStatus", "current_stage", now) != 1:
                    raise InvalidRefereePayload("sentry-control selection requires PREPARE")
            else:
                permitted = {0, 3, 4} if robot_id in _HERO else {0, 1, 2}
                if any(value not in permitted for value in own) or _u(fields, 3) != 0:
                    raise InvalidRefereePayload("performance system does not match requester role")
        elif topic == "MapClickCmd":
            sentry = 107 if robot_id >= 100 else 7
            if any(value and value != sentry for value in _b(fields, 2)):
                raise InvalidRefereePayload("paid map recipients must be the own-team sentry only")
    return values
