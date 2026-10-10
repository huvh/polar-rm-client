"""Explicit, reviewed referee profiles. Never infer a year from packet bytes.

Add a new year's codec, contract, adapter and transport policy here. Team USB,
DT7 and PRM1 are deliberately outside this registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .rm2026 import codec
from .student_legacy import codec as student_codec

DEFAULT_PROFILE = "rm2026-v1.3.1"
STUDENT_PREVIEW_PROFILE = "rm2026-v1.1.0-student-readonly"


class UnsupportedRefereeProfile(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RefereeProfile:
    profile_id: str
    year: int
    protocol_version: str
    codec: Any
    mqtt_host: str
    mqtt_port: int
    client_ip: str
    udp_port: int
    udp_codec: str
    uplink_hz: Mapping[str, float]
    max_qos: int = 1
    read_only: bool = False

    def validate_client_id(self, client_id: str) -> str:
        # Official IDs are robot IDs, not player-end 0x0103 or a random UUID.
        value = str(client_id).strip()
        if not value.isascii() or not value.isdigit():
            raise ValueError("MQTT ClientId must be a robot ID (1-9 or 101-109)")
        number = int(value)
        if number not in {*range(1, 10), *range(101, 110)}:
            raise ValueError("MQTT ClientId must be a robot ID (1-9 or 101-109)")
        return str(number)

    def validate_publish(self, topic: str, qos: int) -> tuple[bool, str]:
        if self.read_only:
            return False, f"{self.profile_id}: READ ONLY; no control/economy uplink"
        if str(topic) not in self.codec.UPLINK_MESSAGES:
            return False, f"{self.profile_id}: not an official uplink topic: {topic}"
        if isinstance(qos, bool) or qos not in range(self.max_qos + 1):
            return False, f"{self.profile_id}: QoS must be 0..{self.max_qos}"
        return True, "ok"

    def create_state_adapter(self, host: Any) -> Any:
        # An explicit import also keeps PyInstaller's dependency graph complete.
        if self.profile_id == DEFAULT_PROFILE:
            from .rm2026.state_adapter import Rm2026StateAdapter
            return Rm2026StateAdapter(host)
        if self.profile_id == STUDENT_PREVIEW_PROFILE:
            from .student_legacy.state_adapter import StudentLegacyStateAdapter
            return StudentLegacyStateAdapter(host)
        raise UnsupportedRefereeProfile(self.profile_id)

    def available_actions(self, state: Any) -> list:
        if self.profile_id == DEFAULT_PROFILE:
            from .rm2026.economy_rules import available_actions
            return available_actions(state)
        if self.read_only:
            return []
        raise UnsupportedRefereeProfile(self.profile_id)


_RM2026 = RefereeProfile(
    profile_id=DEFAULT_PROFILE, year=2026, protocol_version="1.3.1", codec=codec,
    mqtt_host="192.168.12.1", mqtt_port=3333, client_ip="192.168.12.2",
    udp_port=3334, udp_codec="hevc",
    # Operator role is not authenticated by this client. Use the stricter
    # semi-automatic operator interval (3 s) for all map marks, also satisfying
    # the gimbal operator's 0.5 s minimum in section 1.3.1.
    uplink_hz=MappingProxyType({
        name: (75.0 if name in {"KeyboardMouseControl", "CustomControl"}
               else 1.0 / 3.0 if name == "MapClickCmd" else 10.0)
        for name in codec.UPLINK_MESSAGES
    }),
)
_STUDENT = RefereeProfile(
    profile_id=STUDENT_PREVIEW_PROFILE, year=2026, protocol_version="1.1.0",
    codec=student_codec, mqtt_host="127.0.0.1", mqtt_port=3333,
    client_ip="192.168.12.2", udp_port=3334, udp_codec="hevc",
    uplink_hz=MappingProxyType({}), read_only=True,
)
_PROFILES = MappingProxyType({_RM2026.profile_id: _RM2026, _STUDENT.profile_id: _STUDENT})


def supported_profiles() -> tuple[str, ...]:
    return tuple(_PROFILES)


def get_profile(profile_id: str = DEFAULT_PROFILE) -> RefereeProfile:
    try:
        return _PROFILES[str(profile_id)]
    except KeyError as exc:
        if str(profile_id).lower() in {"rm2026-v2", "rm2026-v2.0", "rm2026-v2.0.0"}:
            raise UnsupportedRefereeProfile(
                "RM2026 V2.0.0 is recognized but NOT supported; this client supports "
                "V1.3.1 and the read-only V1.1.0 student profile. No V2 control "
                "or automatic protocol downgrade is allowed."
            ) from exc
        raise UnsupportedRefereeProfile(
            f"Unsupported referee profile {profile_id!r}; no automatic fallback"
        ) from exc
