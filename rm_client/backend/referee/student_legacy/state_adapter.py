"""Shared stable scalar projection for old Student preview; no guessed roster."""
from __future__ import annotations
from typing import Any
from ..rm2026.state_adapter import Rm2026StateAdapter
from ..rm2026.contract import FIELDS, ALIASES

TOPIC_ALIASES = {
    "RaderInfoToClient": "RadarInfoToClient",
    "SentinelStatusSync": "SentryStatusSync",
    "GuardCtrlResult": "SentryCtrlResult",
}


class StudentLegacyStateAdapter(Rm2026StateAdapter):
    def _apply_one(self, state: Any, name: str, data: dict) -> None:
        name = TOPIC_ALIASES.get(name, name)
        data = dict(data)
        raw = state.backend_stats.setdefault("student_legacy_fields", {})
        raw[name] = self._clean(data)
        if name == "GlobalUnitStatus":
            # Old PDF does not pin a role order or list length. Store raw data
            # for capture/audit instead of treating 14 values as a 5+5 roster.
            state.backend_stats["student_legacy_roster"] = {
                "robot_health": list(data.pop("robot_health", ())),
                "robot_bullets": list(data.pop("robot_bullets", ())),
                "mapping": "UNVERIFIED: old schema does not specify role order",
            }
        if name == "DartSelectTargetStatusSync":
            # Older bool open -> current enum (0 closed / 1 opening / 2 open).
            data["open"] = 2 if data.get("open", False) else 0
        # Convert by reviewed field names, not by incompatible raw field IDs.
        data["__present__"] = frozenset(
            number for number, (field_name, _kind, _repeat) in FIELDS[name].items()
            if ALIASES.get((name, field_name), field_name) in data
        )
        super()._apply_one(state, name, data)
