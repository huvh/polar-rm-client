"""Read-only mini-scoreboard data and geometry; no Qt, transport or control imports.

The protocol's health-vector order is distinct from the *display roster*.  Only
explicit observations can mark a robot alive/dead. Missing and stale data are
unknown, never zero HP. Call reset() on match/source/alliance changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping, Sequence


class LifeState(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RobotCard:
    robot_id: int
    label: str
    life: LifeState = LifeState.UNKNOWN
    kills: int | None = None
    avatar_key: str = ""  # Key into caller-owned, already-authorized QImages.
    local: bool = False
    health: int | None = None
    max_health: int | None = None
    health_applicable: bool = True

    @property
    def health_ratio(self) -> float | None:
        if (not self.health_applicable or self.health is None or self.max_health is None
                or self.max_health <= 0 or self.health > self.max_health):
            return None
        return self.health / self.max_health

    @property
    def health_text(self) -> str:
        if not self.health_applicable:
            return "NO HP"
        if self.health is None:
            return "HP —"
        return f"{self.health}/{self.max_health}" if self.max_health else f"HP {self.health} / ?"


@dataclass(frozen=True)
class TeamStrip:
    alliance: str
    cards: tuple[RobotCard, ...] = ()
    score: int | None = None
    systems: tuple[RobotCard, ...] = ()

    @property
    def alive_count(self) -> int:
        return sum(card.life == LifeState.ALIVE for card in self.cards if card.health_applicable)

    @property
    def unknown_count(self) -> int:
        return sum(card.life == LifeState.UNKNOWN for card in self.cards if card.health_applicable)

    @property
    def alive_text(self) -> str:
        if not self.cards:
            return "—"
        if self.unknown_count:
            return f"{self.alive_count}+?" if self.alive_count else "?"
        return str(self.alive_count)


@dataclass(frozen=True)
class MatchBarFrame:
    left: TeamStrip
    right: TeamStrip
    countdown: int | None = None
    score_label: str = ""  # Caller must state the real metric; never assume CS rounds.
    phase: str = ""
    paused: bool = False
    roster_label: str = ""
    own_base_health: int | None = None
    enemy_base_health: int | None = None

    @property
    def clock_text(self) -> str:
        if self.countdown is None:
            return "—:——"
        return f"{self.countdown // 60}:{self.countdown % 60:02d}"


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True)
class MatchBarLayout:
    bounds: Rect
    center: Rect
    left_cards: tuple[Rect, ...]
    right_cards: tuple[Rect, ...]
    scale: float
    compact: bool = False


def compute_layout(width: float, left_count: int, right_count: int, *,
                   top: float = 5.0, scale: float = 1.0,
                   safe_left: float = 12.0, safe_right: float = 12.0) -> MatchBarLayout:
    """Fit symmetric strips around a fixed viewport center, including uneven rosters.

    Logical reference: 70px square, 8px gaps, 108px center, 6px gutters,
    120px total height. Below 0.36 scale use the legible timer/count-only mode.
    Safe insets reserve existing watermark/map/module-list regions.
    """
    values = (width, top, scale, safe_left, safe_right)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("layout values must be finite numbers")
    if width <= 0 or scale <= 0 or top < 0 or min(safe_left, safe_right) < 0:
        raise ValueError("invalid layout dimensions")
    if any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 16 for n in (left_count, right_count)):
        raise ValueError("each roster must contain 0..16 entries")
    available = width - safe_left - safe_right
    if available <= 0:
        raise ValueError("safe insets leave no drawable space")
    midpoint = safe_left + available / 2
    slots = max(left_count, right_count)
    wing = max(0, slots * 78 - 8)
    natural_width = 108 + (12 + 2 * wing if slots else 0)
    fitted = min(scale, available / natural_width)
    compact = fitted < 0.36
    if compact:
        fitted = min(scale, available / 108)
        wing = 0
    total_width = (108 if compact else natural_width) * fitted
    center = Rect(midpoint - 54 * fitted, top, 108 * fitted, 120 * fitted)
    left, right = [], []
    if not compact:
        for index in range(left_count):
            # Left order remains roster order from outermost to innermost.
            x = center.x - (6 + left_count * 78 - 8) * fitted + index * 78 * fitted
            left.append(Rect(x, top, 70 * fitted, 70 * fitted))
        for index in range(right_count):
            x = center.right + (6 + index * 78) * fitted
            right.append(Rect(x, top, 70 * fitted, 70 * fitted))
    return MatchBarLayout(Rect(midpoint - total_width / 2, top, total_width, 120 * fitted),
                          center, tuple(left), tuple(right), fitted, compact)


def _uint(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 999999 else None


def _robot_id(value: object) -> int | None:
    value = _uint(value)
    return value if value is not None and (1 <= value <= 9 or 101 <= value <= 109) else None


def _stamp(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("time must be a finite nonnegative monotonic timestamp")
    return float(value)


_HEALTH_ROLES = (1, 2, 3, 4, 7)  # RM2026 wire contract, NOT display roster size.
_ROLE_LABELS = {1: "HERO", 2: "ENG", 3: "INF-1", 4: "INF-2", 5: "INF-3", 6: "UAV", 7: "SENTRY", 8: "DART", 9: "RADAR"}
_FIELDS = {
    "GameStatus": {1: "current_round", 3: "red_score", 4: "blue_score", 5: "current_stage", 6: "stage_countdown_sec", 8: "is_paused"},
    "GlobalUnitStatus": {1: "base_health", 6: "enemy_base_health", 11: "robot_health"},
    "RobotDynamicStatus": {1: "current_health"},
    "RobotStaticStatus": {3: "alive_state", 4: "robot_id", 9: "max_health"},
}
_PHASES = {0: "NOT STARTED", 1: "PREPARE", 2: "SELF CHECK", 3: "COUNTDOWN", 4: "MATCH", 5: "SETTLEMENT"}


class TopMatchBarFeed:
    """Projection of decoded referee observations with per-field expiry.

    All inputs are read-only. It does not subscribe to sockets, mutate RobotState,
    send commands, infer eliminations, or inspect vision. Missing __present__ is
    accepted for already presence-filtered dictionaries; use the existing decoder
    dictionaries including __present__ whenever available.
    """
    def __init__(self, red_roster: Sequence[int], blue_roster: Sequence[int], *,
                 left_alliance: str = "Blue", freshness_s: float = 2.5,
                 score_label: str = "") -> None:
        if left_alliance not in ("Red", "Blue"):
            raise ValueError("left_alliance must be Red or Blue")
        if isinstance(freshness_s, bool) or not isinstance(freshness_s, (int, float)) or not math.isfinite(freshness_s) or freshness_s <= 0:
            raise ValueError("freshness_s must be positive")
        self.rosters = {"Red": self._roster(red_roster, False), "Blue": self._roster(blue_roster, True)}
        self.left_alliance = left_alliance
        self.freshness_s = freshness_s
        self.score_label = str(score_label)[:20]
        self.reset()

    @staticmethod
    def _roster(ids: Sequence[int], blue: bool) -> tuple[int, ...]:
        result = tuple(ids)
        if len(result) > 16 or len(set(result)) != len(result):
            raise ValueError("roster must have at most 16 unique robot IDs")
        if any(_uint(i) is None or not 1 <= i - (100 if blue else 0) <= 9 for i in result):
            raise ValueError("roster IDs must use red 1..9 or blue 101..109")
        return result

    def reset(self) -> None:
        self._health: dict[int, tuple[LifeState, float]] = {}
        self._global_at = -1.0
        self._hp: dict[int, tuple[int | None, float]] = {}
        self._max_hp: dict[int, tuple[int | None, float]] = {}
        self._local_dynamic_at = -1.0
        self._values: dict[str, tuple[object, float]] = {}
        self._kills: dict[int, int] = {}
        self._event_ids: set[str] = set()
        self._round: int | None = None
        self._round_started_at = -1.0
        self._context: tuple[str, int] | None = None

    def _set_health(self, robot_id: int, life: LifeState, now: float) -> None:
        if _robot_id(robot_id) is None:
            return
        previous = self._health.get(robot_id)
        if previous is None or now >= previous[1]:
            self._health[robot_id] = (life, now)

    def _set_hp(self, robot_id: int, hp: int | None, now: float) -> None:
        previous = self._hp.get(robot_id)
        if _robot_id(robot_id) is None or (previous is not None and now < previous[1]):
            return
        self._hp[robot_id] = (hp, now)
        self._set_health(robot_id, LifeState.UNKNOWN if hp is None else
                         (LifeState.ALIVE if hp > 0 else LifeState.DEAD), now)

    def _set_value(self, key: str, value: object, now: float) -> None:
        previous = self._values.get(key)
        if previous is None or now >= previous[1]:
            self._values[key] = (value, now)

    def consume_referee(self, name: str, data: Mapping[str, object], *,
                        received_at: float, own_alliance: str, local_robot_id: int) -> None:
        now = _stamp(received_at)
        if own_alliance not in ("Red", "Blue"):
            raise ValueError("own_alliance must be Red or Blue")
        if _robot_id(local_robot_id) is None:
            raise ValueError("invalid local robot ID")
        context = (own_alliance, local_robot_id)
        if self._context is not None and self._context != context:
            self.reset()
        self._context = context
        if now < self._round_started_at:
            return  # A late packet from a cleared round cannot restore old state.
        fields = _FIELDS.get(name)
        if not fields:
            return
        if "__present__" in data:
            present = data["__present__"]
            if not isinstance(present, (tuple, list, set, frozenset)):
                return
            permitted = {key for number, key in fields.items() if number in present}
            data = {key: value for key, value in data.items() if key in permitted}
        if name == "GameStatus":
            new_round = _uint(data.get("current_round"))
            old_round = self._values.get("current_round")
            if new_round is not None and (old_round is None or now >= old_round[1]):
                if self._round is not None and new_round != self._round:
                    self._round_started_at = now
                    self._kills.clear()
                    self._event_ids.clear()
                    self._health.clear()
                    self._hp.clear()
                    self._max_hp.clear()
                    self._local_dynamic_at = -1.0
                    self._global_at = -1.0
                    for key in ("stage_countdown_sec", "current_stage", "is_paused", "base_health", "enemy_base_health"):
                        self._values.pop(key, None)
                self._round = new_round
                self._set_value("current_round", new_round, now)
            for key in ("red_score", "blue_score", "stage_countdown_sec", "current_stage"):
                value = _uint(data.get(key))
                if key in data:
                    self._set_value(key, value, now)
            if "is_paused" in data and isinstance(data["is_paused"], bool):
                self._set_value("is_paused", data["is_paused"], now)
        elif name == "GlobalUnitStatus":
            for key in ("base_health", "enemy_base_health"):
                if key in data:
                    self._set_value(key, _uint(data[key]), now)
            if "robot_health" not in data or now < self._global_at:
                return
            values = data["robot_health"]
            if not isinstance(values, (tuple, list)):
                return
            offset = 100 if own_alliance == "Blue" else 0
            ids = tuple(role + offset for role in _HEALTH_ROLES) + tuple(role + (100 - offset) for role in _HEALTH_ROLES)
            # Short vectors leave trailing entries UNKNOWN, without shifting indices.
            for index, robot_id in enumerate(ids):
                # Local 10 Hz HP owns this robot while fresh; a delayed 1 Hz
                # team snapshot cannot resurrect it immediately after death.
                if robot_id == local_robot_id and 0 <= now - self._local_dynamic_at <= self.freshness_s:
                    continue
                hp = _uint(values[index]) if index < len(values) else None
                self._set_hp(robot_id, hp, now)
            self._global_at = now
        elif name == "RobotDynamicStatus" and "current_health" in data:
            hp = _uint(data["current_health"])
            self._set_hp(local_robot_id, hp, now)
            self._local_dynamic_at = max(self._local_dynamic_at, now)
        elif name == "RobotStaticStatus":
            robot_id = _robot_id(data["robot_id"]) if "robot_id" in data else local_robot_id
            # This message describes the locally connected robot. An explicit
            # mismatched ID must not become invented remote max-HP authority.
            if robot_id is None or robot_id != local_robot_id:
                return
            if "max_health" in data:
                maximum = _uint(data["max_health"])
                previous = self._max_hp.get(robot_id)
                if previous is None or now >= previous[1]:
                    self._max_hp[robot_id] = (maximum if maximum and maximum > 0 else None, now)
            if "alive_state" in data:
                alive = _uint(data["alive_state"])
                life = {1: LifeState.ALIVE, 2: LifeState.DEAD}.get(alive, LifeState.UNKNOWN)
                self._set_health(robot_id, life, now)
                # A static life transition cannot retain contradictory old HP.
                hp, at = self._hp.get(robot_id, (None, -1.0))
                if now >= at and (life == LifeState.UNKNOWN or
                        (life == LifeState.DEAD and hp != 0) or
                        (life == LifeState.ALIVE and hp == 0)):
                    self._hp.pop(robot_id, None)

    def record_confirmed_elimination(self, *, event_id: str, killer_id: int,
                                      victim_id: int, confirmed: bool,
                                      source: str) -> bool:
        """Optional skull marks; stable unique IDs and trusted attribution required.

        Do not pass visual guesses, cumulative counters, or health-zero events:
        those do not establish a killer. The host must reset at a new match.
        """
        roster_ids = set(self.rosters["Red"] + self.rosters["Blue"])
        if (confirmed is not True or source != "referee" or not isinstance(event_id, str)
                or not 0 < len(event_id) <= 160 or event_id in self._event_ids
                or _uint(killer_id) is None or _uint(victim_id) is None
                or killer_id not in roster_ids or victim_id not in roster_ids
                or (killer_id >= 100) == (victim_id >= 100) or len(self._event_ids) >= 4096):
            return False
        self._event_ids.add(event_id)
        self._kills[killer_id] = min(999, self._kills.get(killer_id, 0) + 1)
        return True

    def snapshot(self, now: float, *, local_robot_id: int = 0) -> MatchBarFrame:
        now = _stamp(now)
        def fresh(key: str) -> object | None:
            value, at = self._values.get(key, (None, -1.0))
            return value if 0 <= now - at <= self.freshness_s else None
        def fresh_hp(values: dict, robot_id: int) -> int | None:
            value, at = values.get(robot_id, (None, -1.0))
            return value if 0 <= now - at <= self.freshness_s else None
        def team(alliance: str) -> TeamStrip:
            cards, systems = [], []
            for robot_id in self.rosters[alliance]:
                life, at = self._health.get(robot_id, (LifeState.UNKNOWN, -1.0))
                if not 0 <= now - at <= self.freshness_s:
                    life = LifeState.UNKNOWN
                role = robot_id % 100
                card = RobotCard(robot_id, _ROLE_LABELS.get(role, "ROBOT"), life,
                                 self._kills.get(robot_id), str(robot_id), robot_id == local_robot_id,
                                 fresh_hp(self._hp, robot_id), fresh_hp(self._max_hp, robot_id),
                                 role not in (6, 8, 9))
                (systems if role in (8, 9) else cards).append(card)
            score = fresh(alliance.lower() + "_score") if self.score_label else None
            return TeamStrip(alliance, tuple(cards), score, tuple(systems))
        other = "Red" if self.left_alliance == "Blue" else "Blue"
        stage = fresh("current_stage")
        return MatchBarFrame(team(self.left_alliance), team(other), fresh("stage_countdown_sec"),
                             self.score_label, _PHASES.get(stage, ""), fresh("is_paused") is True,
                             own_base_health=fresh("base_health"), enemy_base_health=fresh("enemy_base_health"))
