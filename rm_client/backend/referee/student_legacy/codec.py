"""Old Student wire decoding. All uplink, including neutral KMC, is forbidden.

Stable encoder names remain available to the manager, but the profile whitelist
refuses every publish before it can reach a socket. Never synthesize a legacy
RemoteControl from a current KeyboardMouseControl packet.
"""
from __future__ import annotations
from typing import Any
from ..rm2026.codec import *  # stable Python encoder API only
from .. import wire
from ..validation import InvalidRefereePayload, validate_message
from .contract import FIELDS, SOURCE_URL, SOURCE_SHA256

PROTOCOL_VERSION = "1.1.0"
UPLINK_MESSAGES = frozenset()
DOWNLINK_MESSAGES = frozenset({
    "GameStatus", "GlobalUnitStatus", "GlobalLogisticsStatus",
    "GlobalSpecialMechanism", "Event", "RobotInjuryStat", "RobotRespawnStatus",
    "RobotStaticStatus", "RobotDynamicStatus", "RobotModuleStatus",
    "RobotPosition", "Buff", "PenaltyInfo", "RobotPathPlanInfo",
    "RaderInfoToClient", "CustomByteBlock", "TechCoreMotionStateSync",
    "RobotPerformanceSelectionSync", "DeployModeStatusSync", "RuneStatusSync",
    "SentinelStatusSync", "DartSelectTargetStatusSync", "GuardCtrlResult",
    "AirSupportStatusSync",
})
ALL_MESSAGES = DOWNLINK_MESSAGES


def _decode(name: str, fields: dict) -> dict[str, Any]:
    result = {}
    for number, (field_name, kind, repeated) in FIELDS[name].items():
        if kind in FIELDS:
            result[field_name] = [_decode(kind, sub) for sub in wire._sub(fields, number)]
        elif repeated:
            result[field_name] = wire._packed_ints(fields, number) if kind == "int32" else wire._packed(fields, number)
        else:
            reader = {"float": wire._f, "int32": wire._i, "bool": wire._bool,
                      "string": wire._s, "bytes": wire._b}.get(kind, wire._u)
            result[field_name] = reader(fields, number)
    return result


def decode_message(name: str, payload: bytes) -> dict[str, Any]:
    if name not in DOWNLINK_MESSAGES:
        return {}
    try:
        validate_message(name, payload, FIELDS)
    except InvalidRefereePayload:
        return {}
    fields = wire.decode_fields(payload)
    if payload and not set(fields).intersection(FIELDS[name]):
        return {}
    result = _decode(name, fields)
    if name == "GameStatus" and result["current_stage"] not in range(6):
        return {}
    if name == "DeployModeStatusSync" and result["status"] not in {0, 1}:
        return {}
    # Old proto3 scalar fields are non-optional, unlike the current profile.
    result["__present__"] = frozenset(FIELDS[name])
    return result
