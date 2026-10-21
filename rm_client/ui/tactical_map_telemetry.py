"""Detached tactical-map observations from explicit telemetry values.

No settings, Qt objects, clock sampling, rendering or publication lives here.
Single radar rows are decoded on demand: a later malformed row cannot erase
already-painted markers or move their observable failure prefix.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
import math


RADAR_TTL_SECONDS = 6.0


def radar_coordinate_metres(value: float, span_m: float, *, source: str = "official") -> float:
    """Official coordinates are always cm, including small/zero values.

    span_m remains for caller compatibility, never as a unit-guessing threshold.
    Private producers must explicitly select their metre-based contract.
    """
    if type(value) is bool:
        raise ValueError("boolean radar coordinate")
    coordinate = float(value)
    if not math.isfinite(coordinate):
        raise ValueError("nonfinite radar coordinate")
    if source == "official":
        if coordinate < 0:
            raise ValueError("official radar coordinates are unsigned")
        return coordinate / 100.0
    if source in {"private-metres", "mock-metres"}:
        return coordinate
    raise ValueError("unknown radar coordinate source")


@dataclass(frozen=True)
class RadarLifetime:
    age_seconds: float
    ttl_seconds: float

    @classmethod
    def visible_at(cls, seen_at: float, now: float, ttl_seconds: float = RADAR_TTL_SECONDS) -> RadarLifetime | None:
        if seen_at <= 0.0:
            return None
        age = now - seen_at
        if age > ttl_seconds:
            return None
        return cls(age, ttl_seconds)

    @property
    def opacity(self) -> float:
        return max(0.0, min(1.0, (self.ttl_seconds - self.age_seconds) / 2.0))


@dataclass(frozen=True)
class RadarMarker:
    x_m: float
    y_m: float
    highlighted: bool
    position_offline: bool = False

    @classmethod
    def from_wire(cls, detection: Mapping[str, Any], width_m: float, height_m: float, *, source: str = "official") -> RadarMarker:
        x_m = radar_coordinate_metres(detection.get('target_pos_x', 0.0), width_m, source=source)
        y_m = radar_coordinate_metres(detection.get('target_pos_y', 0.0), height_m, source=source)
        highlight = int(detection.get('is_high_light', 0) or 0)
        if highlight not in {0, 1, 2}:
            raise ValueError('unknown radar highlight enum')
        return cls(x_m, y_m, highlight != 0, highlight == 2)


@dataclass(frozen=True)
class PenaltyNotice:
    penalty_type: int
    total_count: int
    effect_seconds: int


def penalty_notices(active: Mapping[str, Any], penalties: Sequence[Mapping[str, Any]]) -> tuple[PenaltyNotice, ...]:
    """Prioritize active/latest penalties, deduplicate types, then cap at three.

    Preserve the established conversion failures: invalid type/value is ignored
    or zeroed, while missing mapping behavior and numeric overflow stay visible.
    """
    entries: list[PenaltyNotice] = []

    def push(item: Mapping[str, Any]) -> None:
        try:
            penalty_type = int(item.get('penalty_type', 0))
        except (TypeError, ValueError):
            return
        if any(existing.penalty_type == penalty_type for existing in entries):
            return
        try:
            total = int(item.get('total_penalty_num', 0) or 0)
            effect = int(item.get('penalty_effect_sec', 0) or 0)
        except (TypeError, ValueError):
            total, effect = 0, 0
        entries.append(PenaltyNotice(penalty_type, total, effect))

    if active:
        push(active)
    for item in reversed(penalties):
        push(item)
        if len(entries) >= 3:
            break
    return tuple(entries)


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    name: str
    remaining_seconds: int

    def as_row(self) -> tuple[str, str, int]:
        return self.kind, self.name, self.remaining_seconds


def own_active_buffs(rows: Iterable[Mapping[str, Any]], own_robot_id: int) -> tuple[TimelineEntry, ...]:
    """Only genuine active telemetry for the own robot belongs on its timeline."""
    entries: list[TimelineEntry] = []
    for row in rows:
        if row.get('buff_type') is None:
            continue
        try:
            if int(row.get('robot_id', 0) or 0) != own_robot_id:
                continue
        except (TypeError, ValueError):
            continue
        if not row.get('active'):
            continue
        name = str(row.get('name') or f"Buff {row.get('buff_type')}")
        try:
            remaining = max(0, int(row.get('remaining', 0) or 0))
        except (TypeError, ValueError):
            remaining = 0
        entries.append(TimelineEntry('buff', name, remaining))
    return tuple(entries)


def special_mechanisms(items: Iterable[Mapping[str, Any]]) -> tuple[TimelineEntry, ...]:
    entries: list[TimelineEntry] = []
    for item in items:
        try:
            mechanism_id = int(item.get('mechanism_id', 0) or 0)
            seconds = max(0, int(item.get('time_sec', 0) or 0))
        except (AttributeError, TypeError, ValueError):
            continue
        if mechanism_id <= 0:
            continue
        entries.append(TimelineEntry('mechanism', f'MECH{mechanism_id}', seconds))
    return tuple(entries)
