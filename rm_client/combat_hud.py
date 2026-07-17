from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_COMBAT_HUD_VISUALS = ("Classic", "Clear", "Enhanced")


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def percent(value: float, maximum: float) -> float:
    if maximum <= 0.0:
        return 0.0
    return clamp_percent(float(value) / float(maximum) * 100.0)


def ring_end(value: float) -> float:
    return 180.0 + 3.6 * clamp_percent(value)


def approach_jar(current: float, target: float, dt: float) -> float:
    current = float(current)
    target = float(target)
    speed = max(10.0, abs(current - target) * 30.0) * 0.3
    step = speed * max(0.0, float(dt))
    if abs(target - current) <= step:
        return target
    return current + (step if target > current else -step)


def approach_bar(current: float, target: float, dt: float) -> float:
    current = float(current)
    target = float(target)
    factor = max(0.04, min(1.0, abs(target - current) * 12.0 * max(0.0, float(dt))))
    return current + (target - current) * factor


def ghost_follow(current: float, target: float, dt: float, multiplier: float = 12.0) -> float:
    current = float(current)
    target = float(target)
    if current < target:
        return target
    speed = max(4.0, abs(current - target) * float(multiplier)) * 0.3
    step = speed * max(0.0, float(dt))
    if abs(target - current) <= step:
        return target
    return current - step


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

        health_target = percent(getattr(state, "current_health", 0), getattr(state, "max_health", 0))
        heat_target = percent(getattr(state, "current_heat", 0.0), getattr(state, "max_heat", 0.0))
        capacity = max(0, int(getattr(state, "ammo_capacity", 0)))
        remaining = max(0, int(getattr(state, "remaining_ammo", 0)))
        ammo_target = percent(remaining, max(capacity, remaining, 1))

        frame = self.frame
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
