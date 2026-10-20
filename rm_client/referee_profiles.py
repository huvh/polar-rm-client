"""Reviewed referee identities and connection defaults, with no runtime assembly.

Scenario and model defaults depend on this metadata rather than loading codecs,
annual state adapters, or economy rules. The backend registry composes these
same definitions with its reviewed implementations; it does not repeat values.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


DEFAULT_PROFILE = "rm2026-v1.3.1"
STUDENT_PREVIEW_PROFILE = "rm2026-v1.1.0-student-readonly"
V2_PROFILE = "rm2026-v2.0.0"


class UnsupportedRefereeProfile(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RefereeProfileDefinition:
    profile_id: str
    year: int
    protocol_version: str
    mqtt_host: str
    mqtt_port: int
    client_ip: str
    udp_port: int
    udp_codec: str
    max_qos: int = 1
    read_only: bool = False


_DEFINITIONS = MappingProxyType({
    DEFAULT_PROFILE: RefereeProfileDefinition(
        profile_id=DEFAULT_PROFILE, year=2026, protocol_version="1.3.1",
        mqtt_host="192.168.12.1", mqtt_port=3333, client_ip="192.168.12.2",
        udp_port=3334, udp_codec="hevc",
    ),
    STUDENT_PREVIEW_PROFILE: RefereeProfileDefinition(
        profile_id=STUDENT_PREVIEW_PROFILE, year=2026, protocol_version="1.1.0",
        mqtt_host="127.0.0.1", mqtt_port=3333, client_ip="192.168.12.2",
        udp_port=3334, udp_codec="hevc", read_only=True,
    ),
    V2_PROFILE: RefereeProfileDefinition(
        profile_id=V2_PROFILE, year=2026, protocol_version="2.0.0",
        mqtt_host="192.168.12.1", mqtt_port=3333, client_ip="192.168.12.2",
        udp_port=3334, udp_codec="hevc",
    ),
})


def supported_profiles() -> tuple[str, ...]:
    return tuple(_DEFINITIONS)


def get_profile_definition(profile_id: str = DEFAULT_PROFILE) -> RefereeProfileDefinition:
    try:
        return _DEFINITIONS[str(profile_id)]
    except KeyError as exc:
        if str(profile_id).lower() in {"rm2026-v2", "rm2026-v2.0", "rm2026-v2.0.0"}:
            raise UnsupportedRefereeProfile(
                "Unsupported V2 alias; select exactly rm2026-v2.0.0 for the "
                "partial telemetry and supervised Air profile. No automatic fallback."
            ) from exc
        raise UnsupportedRefereeProfile(
            f"Unsupported referee profile {profile_id!r}; no automatic fallback"
        ) from exc
