"""Unregistered RMUC7v7 V2 rule estimates and documented command membership.

Pure arithmetic, not an offer, eligibility check, server quote or permission to
publish. Callers must establish explicit V2/RMUC identity and authoritative,
current target observations before using these values. No defaults or clamps.
V1 behavior, transport rates, role/stage admission and UI remain unchanged.
"""
from .contract import AIR_SUPPORT_COMMAND_IDS, SENTRY_COMMAND_IDS

RULES_URL = "https://bbs.robomaster.com/wiki/20204847/809871"
RULES_VERSION = "2.2.0 (2026-08-07)"
RULES_SHA256 = "88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5"


def _integer_in_range(value: int, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def estimate_remote_heal_cost(remaining_seconds: int) -> int:
    """Base 60%-HP heal cost; excludes any Sentry intervention surcharge.

    Table 5-6 p.77: 50 + ceil((420-T)/60 * 20). Multiplication is
    inside the ceiling. This is a rule estimate, not a received server quote.
    """
    remaining = _integer_in_range(remaining_seconds, 0, 420, "remaining_seconds")
    return 50 + (420 - remaining + 2) // 3


def estimate_leveled_revive_cost(remaining_seconds: int, level: int) -> int:
    """Base same-level ground revival comparator, not a target quote.

    Table 5-6 p.77: ceil((420-T)/60)*80 + L*20. Level1..10 is
    the Hero/Infantry/Aerial system (§5.4.1), not an inferred Sentry level.
    """
    remaining = _integer_in_range(remaining_seconds, 0, 420, "remaining_seconds")
    observed_level = _integer_in_range(level, 1, 10, "level")
    return ((420 - remaining + 59) // 60) * 80 + observed_level * 20


def estimate_air_countermeasure_cost(remaining_seconds: int, level: int) -> int:
    """Rule estimate for release-and-call: twice the same-level comparator.

    Requires the actual aerial level. Does not infer shooter_status, eligibility,
    counter count, operator permission, or unique execution acknowledgement.
    """
    return 2 * estimate_leveled_revive_cost(remaining_seconds, level)


def is_documented_command(topic: str, command_id: int) -> bool:
    """Only membership in the V2 Sentry/Air enums; never send permission."""
    if type(topic) is not str or type(command_id) is not int:
        return False
    if topic == "SentryCtrlCommand":
        return command_id in SENTRY_COMMAND_IDS
    if topic == "AirSupportCommand":
        return command_id in AIR_SUPPORT_COMMAND_IDS
    return False
