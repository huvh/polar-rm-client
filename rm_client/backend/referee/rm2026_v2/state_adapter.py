"""Unregistered V2 projection; common V1 authority and host effects are reused.

The settlement witness is local stale-result prevention, not a protocol ACK or
atomic-snapshot claim. V2 is still unavailable through the profile registry.
"""
from __future__ import annotations

from typing import Any

from ....model import RobotState
from ..rm2026.projection_policy import _select_present_fields
from ..rm2026.state_adapter import Rm2026StateAdapter
from .contract import ALIASES, FIELDS


class Rm2026V2StateAdapter(Rm2026StateAdapter):
    @staticmethod
    def _select_present_fields(name: str, data: dict[str, Any]) -> tuple[dict[str, Any], frozenset[int]]:
        return _select_present_fields(name, data, FIELDS, ALIASES)

    def _apply_settlement(self, state: RobotState, data: dict[str, Any],
                          previous_round: int, stage: int | None) -> None:
        # Common round conversion has already succeeded. Retire an old round
        # even if its stage-5 value is retained by the common optional fields.
        if state.current_round != previous_round or (stage is not None and stage != 5):
            state.clear_match_settlement()
        if stage != 5 and (state.settlement_round != state.current_round
                           or state.current_stage != "SETTLEMENT"):
            return
        # Convert all present outcomes before publishing new observations. A
        # malformed direct mapping must not seed a later stage-only record.
        result = int(data["game_result"]) if "game_result" in data else None
        reason = int(data["end_reason"]) if "end_reason" in data else None
        if stage == 5:
            state.settlement_round = state.current_round
        # Omission preserves current-round observations. Raw 255/unknown enums
        # are retained but must never be interpreted as a winner/reason.
        if "game_result" in data:
            state.game_result = result
        if "end_reason" in data:
            state.end_reason = reason
        # SentryStatusSync uses the common presence-filtered dict update.
        # Its is_powered key means strengthened/boosted, not electrical power.
