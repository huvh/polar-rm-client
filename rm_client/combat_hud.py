"""Combat TargetHUD ring math — parity with Debug visual-demo RM semantics.

Reference (branch / handoff):
  `Downloads/Debug/visual-demo/RM_VISUAL_README.md`
  `Downloads/Debug/visual-demo/index.html` (tickRm / approachJar / ghostFollow)
  `Downloads/Debug/visual-demo/targethud-core.js`

Rules that must stay 1:1 with the demo:
  - Red ring = self HP %, blue ring = heat % (same 0..100 scale)
  - Both rings use approachJar (never a different heat curve)
  - Enhanced: selfGhost / heatGhost — snap up, lag down
  - Staged heat cool is a *logic* heat jump (demo heat field), not a second
    animation curve; heatAnim only ever does approachJar toward that target
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_COMBAT_HUD_VISUALS = ("Classic", "Clear", "Enhanced")

# visual-demo RM_VISUAL_README §3.5 / index.html
SELF_HIT_HP = 2.0
HEAT_PER_SHOT = 12.0
HEAT_COOL_DELAY = 0.35
HEAT_STAGE_GAP = 0.06
METER_SETTLE_EPS = 0.45


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def percent(value: float, maximum: float) -> float:
    if maximum <= 0.0:
        return 0.0
    return clamp_percent(float(value) / float(maximum) * 100.0)


def ring_end(value: float) -> float:
    """jar / demo: endAngle = 180 + 3.6 * value (value ∈ [0,100])."""
    return 180.0 + 3.6 * clamp_percent(value)


def jar_speed(current: float, target: float) -> float:
    """visual-demo jarSpeed — shared by HP and heat rings."""
    return max(10.0, abs(float(current) - float(target)) * 30.0) * 0.3


def approach_jar(current: float, target: float, dt: float) -> float:
    """visual-demo approachJar / getAnimationState(cur, tgt, jarSpeed, dt)."""
    current = float(current)
    target = float(target)
    step = jar_speed(current, target) * max(0.0, float(dt))
    if abs(target - current) <= step:
        return target
    return current + (step if target > current else -step)


def approach_bar(current: float, target: float, dt: float) -> float:
    """visual-demo approachBar — AIM / AMMO only (not rings)."""
    current = float(current)
    target = float(target)
    factor = max(0.04, min(1.0, abs(target - current) * 12.0 * max(0.0, float(dt))))
    return current + (target - current) * factor


def ghost_follow(current: float, target: float, dt: float, multiplier: float = 12.0) -> float:
    """visual-demo ghostFollow — rise snaps, fall lags (Enhanced trails)."""
    current = float(current)
    target = float(target)
    if current < target:
        return target
    speed = max(4.0, abs(current - target) * float(multiplier)) * 0.3
    step = speed * max(0.0, float(dt))
    if abs(target - current) <= step:
        return target
    return current - step


def meter_settled(anim: float, target: float, eps: float = METER_SETTLE_EPS) -> bool:
    """visual-demo meterSettled — heat stage cool must wait for this."""
    return abs(float(anim) - float(target)) <= float(eps)


def stage_drop_pct(self_max: float, hit_hp: float = SELF_HIT_HP) -> float:
    """visual-demo stageDropPct — same % as one self-hit on the red ring."""
    maximum = max(1.0, float(self_max))
    return clamp_percent((float(hit_hp) / maximum) * 100.0)


def aim_target(state: Any) -> float:
    if bool(getattr(state, "target_locked", False)):
        return 100.0
    tracking = str(getattr(state, "vision_tracking_state", "")).strip().lower()
    if tracking in {"track", "tracking", "detect", "detected", "acquire", "acquired", "locked"}:
        return 60.0
    if int(getattr(state, "vision_detection_count", 0)) > 0:
        return 60.0
    return 0.0


@dataclass
class CombatHudFrameState:
    self_anim: float = 0.0
    heat_anim: float = 0.0
    self_ghost: float = 0.0
    heat_ghost: float = 0.0
    aim_anim: float = 0.0
    ammo_anim: float = 0.0
    ammo_ghost: float = 0.0


class CombatHudAnimator:
    """Display-layer animator: approachJar for rings, approachBar for meters."""

    def __init__(self) -> None:
        self.frame = CombatHudFrameState()
        self.initialized = False

    def reset(self, state: Any, *, aim_override: float | None = None) -> CombatHudFrameState:
        health = percent(getattr(state, "current_health", 0), getattr(state, "max_health", 0))
        heat = percent(getattr(state, "current_heat", 0.0), getattr(state, "max_heat", 0.0))
        capacity = max(0, int(getattr(state, "ammo_capacity", 0)))
        remaining = max(0, int(getattr(state, "remaining_ammo", 0)))
        ammo = percent(remaining, max(capacity, remaining, 1))
        aim = aim_target(state) if aim_override is None else clamp_percent(aim_override)
        self.frame = CombatHudFrameState(health, heat, health, heat, aim, ammo, ammo)
        self.initialized = True
        return self.frame

    def update(
        self,
        state: Any,
        dt: float,
        visual: str,
        *,
        aim_override: float | None = None,
    ) -> CombatHudFrameState:
        if not self.initialized:
            return self.reset(state, aim_override=aim_override)

        # Clamp dt like a single display frame (demo rAF ≈ 0..0.05).
        dt = max(0.0, min(0.05, float(dt)))

        health_target = percent(getattr(state, "current_health", 0), getattr(state, "max_health", 0))
        heat_target = percent(getattr(state, "current_heat", 0.0), getattr(state, "max_heat", 0.0))
        capacity = max(0, int(getattr(state, "ammo_capacity", 0)))
        remaining = max(0, int(getattr(state, "remaining_ammo", 0)))
        ammo_target = percent(remaining, max(capacity, remaining, 1))

        frame = self.frame
        # ★ Both rings share approachJar — never a separate heat curve.
        frame.self_anim = approach_jar(frame.self_anim, health_target, dt)
        frame.heat_anim = approach_jar(frame.heat_anim, heat_target, dt)
        aim_value = aim_target(state) if aim_override is None else clamp_percent(aim_override)
        frame.aim_anim = approach_bar(frame.aim_anim, aim_value, dt)
        frame.ammo_anim = approach_bar(frame.ammo_anim, ammo_target, dt)

        if visual == "Enhanced":
            frame.self_ghost = ghost_follow(frame.self_ghost, frame.self_anim, dt, 12.0)
            frame.heat_ghost = ghost_follow(frame.heat_ghost, frame.heat_anim, dt, 12.0)
            frame.ammo_ghost = ghost_follow(frame.ammo_ghost, frame.ammo_anim, dt, 10.0)
        else:
            frame.self_ghost = frame.self_anim
            frame.heat_ghost = frame.heat_anim
            frame.ammo_ghost = frame.ammo_anim
        return frame


class MockHeatStageSimulator:
    """Desktop mock: fire bursts + staged cool matching visual-demo tickHeatStages.

    Real referee/robot heat should feed ``RobotState.current_heat`` directly;
    this simulator only drives mock tick so the blue ring shows jar settle +
    stage drops instead of a continuous sine wave.

    Internally mirrors demo order:
      heatAnim = approachJar(heatAnim, heat)
      then if settled and cool delay → heat -= stageDrop
    """

    def __init__(self) -> None:
        self.heat_pct = 48.0  # start mid so outer blue ring is visible immediately
        self.heat_anim = 48.0
        self.last_fire_at = 0.0
        self.heat_gap_wait = 0.0
        self._phase_t = 0.0
        self._burst_shots_left = 0
        self._burst_cooldown = 0.0
        self._next_burst_at = 0.8
        self._started_at = 0.0

    def reset(self, heat_pct: float = 48.0) -> None:
        # Keep a readable floor so the outer blue arc is not empty for long.
        self.heat_pct = clamp_percent(max(float(heat_pct), 36.0))
        self.heat_anim = self.heat_pct
        self.last_fire_at = 0.0  # set on first tick to "now" so we do not cool from t=-∞
        self.heat_gap_wait = 0.0
        self._phase_t = 0.0
        self._burst_shots_left = 0
        self._burst_cooldown = 0.0
        self._next_burst_at = 0.8
        self._started_at = 0.0

    def tick(
        self,
        dt: float,
        *,
        now: float,
        self_max_hp: float,
        ammo: int,
    ) -> float:
        """Advance mock heat logic; return heat percent 0..100."""
        dt = max(0.0, min(0.1, float(dt)))
        if self._started_at <= 0.0:
            self._started_at = now
            self.last_fire_at = now  # suppress instant staged cool on boot
        self._phase_t += dt
        self._burst_cooldown = max(0.0, self._burst_cooldown - dt)

        # 1) Display catch-up first (demo frame order before stage cool).
        self.heat_anim = approach_jar(self.heat_anim, self.heat_pct, dt)

        # 2) Periodic fire bursts → instant +HEAT_PER_SHOT jumps.
        if self._burst_shots_left <= 0 and self._phase_t >= self._next_burst_at and self.heat_pct < 90.0:
            self._burst_shots_left = 4 + int(self._phase_t * 7) % 2
            self._next_burst_at = self._phase_t + 2.4 + (int(self._phase_t) % 4) * 0.12
        if self._burst_shots_left > 0 and ammo > 0 and self.heat_pct < 100.0 - 0.5:
            if self._burst_cooldown <= 0.0:
                self.heat_pct = min(100.0, self.heat_pct + HEAT_PER_SHOT)
                self.last_fire_at = now
                self.heat_gap_wait = 0.0
                self._burst_shots_left -= 1
                self._burst_cooldown = 0.10
        elif self._burst_shots_left > 0 and (ammo <= 0 or self.heat_pct >= 99.5):
            self._burst_shots_left = 0
            self._burst_cooldown = 0.8

        # 3) Staged cool — demo uses stageDropPct(selfMax); for RM robots max HP
        #    is huge (~600) so 2/600 ≈ 0.3% stages look continuous and can
        #    empty the blue ring between bursts. Mock uses a 10% step (demo
        #    selfMax=20 feel) so settle + trail stay readable.
        if self.heat_pct > 0.0 and (now - self.last_fire_at) >= HEAT_COOL_DELAY:
            if meter_settled(self.heat_anim, self.heat_pct):
                self.heat_gap_wait += dt
                if self.heat_gap_wait >= HEAT_STAGE_GAP:
                    self.heat_gap_wait = 0.0
                    drop = max(10.0, stage_drop_pct(self_max_hp))
                    # Floor so the outer ring is not empty most of the time.
                    self.heat_pct = max(12.0, self.heat_pct - drop)
            else:
                self.heat_gap_wait = 0.0
        else:
            self.heat_gap_wait = 0.0

        return self.heat_pct
