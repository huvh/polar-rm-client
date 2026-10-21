"""Offline explicit release/schema comparison. Never migration or qualification.

Client213 owns the reviewed V2 MQTT schema. Engine137 is a reviewed V2 successor,
not the schema owner or a verified end-to-end pair. Unknown versions stay unknown.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from ..referee_profiles import V2_PROFILE, supported_profiles
from .validation import validate_client_config

REVIEWED_CLIENT = "12.0.0.213"
REVIEWED_ENGINE = "12.0.0.137"
SAFE_PRESET_NAME = "official_213_v2_safe"


@dataclass(frozen=True)
class OfficialProfileDiagnostic:
    status: str
    selected_profile: str | None
    client_version: str
    expected_profile: str | None
    engine_version: str | None
    engine_status: str
    detail: str
    pairing_verified: bool = False
    hardware_qualified: bool = False

    @property
    def profile_matches(self) -> bool:
        return self.status == "PROFILE_MATCH_ONLY"


def diagnose_official_profile(data: dict[str, Any], *, client_version: str,
                              engine_version: str | None = None) -> OfficialProfileDiagnostic:
    """Read operator-supplied versions; do not connect, edit or guess defaults."""
    validate_client_config(data)
    profile = data.get("modules", {}).get("MQTTLink", {}).get("settings", {}).get("Referee Profile")
    expected = V2_PROFILE if client_version == REVIEWED_CLIENT else None
    engine_status = ("NOT_SUPPLIED" if engine_version is None else
                     "REVIEWED_V2_SUCCESSOR_NOT_PAIR_VALIDATED" if engine_version == REVIEWED_ENGINE else
                     "UNVERIFIED_VERSION")
    if profile is None:
        status = "PROFILE_UNRESOLVED"
        detail = "Configuration omits Referee Profile; inherited defaults are not guessed. Select an explicit profile."
    elif profile not in supported_profiles():
        status = "UNSUPPORTED_PROFILE"
        detail = "Unknown referee profile; no alias conversion or fallback is allowed."
    elif expected is None:
        status = "UNVERIFIED_VERSION"
        detail = "This client release has not been reviewed; do not infer V1/V2 from its version number."
    elif profile != expected:
        status = "PROFILE_MISMATCH"
        detail = f"Client {REVIEWED_CLIENT} has a reviewed V2 MQTT schema; explicitly select {V2_PROFILE}. Existing settings are unchanged."
    else:
        status = "PROFILE_MATCH_ONLY"
        detail = "Selected profile matches the reviewed client MQTT schema only. This is not a live connection, engine pairing, complete feature or hardware qualification result."
    return OfficialProfileDiagnostic(status, profile, client_version, expected,
                                     engine_version, engine_status, detail)
