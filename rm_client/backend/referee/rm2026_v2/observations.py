"""Immutable decoded-wire receipts, not UI publication or action permission.

Only present, verified scalar fields are retained. Consumers must validate raw
values and each original receipt; a fresh sibling never refreshes old evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .contract import FIELDS

OBSERVED_MESSAGES = frozenset({
    "GameStatus", "GlobalLogisticsStatus", "RobotStaticStatus",
    "RobotDynamicStatus", "RobotRespawnStatus", "PenaltyInfo",
    "SentryStatusSync", "AirSupportStatusSync", "RobotPerformanceSelectionSync",
})
_SCOPE_FIELDS = frozenset({
    ("GameStatus", "current_round"),
    ("RobotStaticStatus", "robot_id"),
    ("RobotStaticStatus", "robot_type"),
})


@dataclass(frozen=True, slots=True)
class WireObservation:
    message: str
    field: str
    value: int | float | bool
    received_at: float


@dataclass(frozen=True, slots=True)
class WireSnapshot:
    profile_id: str
    receive_generation: int
    client_id: str
    received_at: float
    observations: tuple[WireObservation, ...]
    # Local retirement witness, not a peer sequence or authentication token.
    # Appended with a default to retain the existing five-argument constructor.
    scope_revision: int = 0

    def get(self, message: str, field: str) -> WireObservation | None:
        return next((item for item in self.observations
                     if item.message == message and item.field == field), None)


def observe(previous: WireSnapshot | None, *, profile_id: str,
            receive_generation: int, client_id: str, message: str,
            data: dict[str, Any], received_at: float) -> WireSnapshot | None:
    """Reduce one decoded V2 record without callbacks, locks or state defaults.

    Identity/round changes (including first binding) retire previous fields.
    The retained receipt high-watermark rejects older completions even for
    fields erased by retirement. Equal receipts use commit order, not a claim
    of atomic peer state. Disjoint older records are conservatively discarded.
    """
    if message not in OBSERVED_MESSAGES:
        return previous
    if (type(received_at) not in (int, float) or not math.isfinite(received_at)
            or received_at < 0):
        raise ValueError("wire receipt must be finite and nonnegative")
    same_context = previous is not None and (
        previous.profile_id, previous.receive_generation, previous.client_id
    ) == (profile_id, receive_generation, client_id)
    if same_context and received_at < previous.received_at:
        return previous
    pending = []
    present = data.get("__present__", ())
    for number, (field, kind, repeated) in FIELDS[message].items():
        if number not in present:
            continue
        value = data[field]
        expected = bool if kind == "bool" else float if kind == "float" else int
        if repeated or type(value) is not expected:
            raise ValueError("wire observation requires decoded scalar values")
        pending.append(WireObservation(message, field, value, received_at))
    if not pending:
        return previous
    retained = {(item.message, item.field): item for item in previous.observations} if same_context else {}
    scope_revision = previous.scope_revision if same_context else 0
    scope = [item for item in pending if (item.message, item.field) in _SCOPE_FIELDS]
    if any((item.message, item.field) in retained
           and retained[item.message, item.field].value != item.value for item in scope):
        retained.clear()
        scope_revision += 1
    elif any((item.message, item.field) not in retained for item in scope):
        # A first identity/round binding cannot relabel unbound peer samples.
        # Keep already observed scope keys so partial bindings can accumulate.
        retained = {key: value for key, value in retained.items() if key in _SCOPE_FIELDS}
        scope_revision += 1
    retained.update(((item.message, item.field), item) for item in pending)
    return WireSnapshot(profile_id, receive_generation, client_id, received_at,
                        tuple(retained[key] for key in sorted(retained)), scope_revision)
