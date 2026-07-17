from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class Easings:
    @staticmethod
    def linear(t: float) -> float:
        return clamp01(t)

    @staticmethod
    def ease_out_quad(t: float) -> float:
        t = clamp01(t)
        return 1.0 - (1.0 - t) * (1.0 - t)

    @staticmethod
    def ease_out_cubic(t: float) -> float:
        t = clamp01(t)
        return 1.0 - pow(1.0 - t, 3.0)

    @staticmethod
    def ease_out_pow3(t: float) -> float:
        return Easings.ease_out_cubic(t)

    @staticmethod
    def ease_in_pow3(t: float) -> float:
        t = clamp01(t)
        return t * t * t

    @staticmethod
    def ease_out_pow4(t: float) -> float:
        t = clamp01(t)
        return 1.0 - pow(1.0 - t, 4.0)

    @staticmethod
    def ease_out_pow5(t: float) -> float:
        t = clamp01(t)
        return 1.0 - pow(1.0 - t, 5.0)

    @staticmethod
    def ease_out_expo(t: float) -> float:
        t = clamp01(t)
        if t >= 1.0:
            return 1.0
        return 1.0 - pow(2.0, -10.0 * t)

    @staticmethod
    def ease_out_sine(t: float) -> float:
        return math.sin(clamp01(t) * math.pi / 2.0)

    @staticmethod
    def back_out(t: float) -> float:
        t = clamp01(t) - 1.0
        c1 = 1.70158
        c3 = c1 + 1.0
        return 1.0 + c3 * t * t * t + c1 * t * t


@dataclass
class SmoothAnimation:
    value: float = 0.0
    from_value: float = 0.0
    to_value: float = 0.0
    duration: float = 0.2
    start_time: float = 0.0
    easing: Callable[[float], float] = Easings.ease_out_quad

    def animate(
        self,
        target: float,
        duration: float = 0.2,
        easing: Callable[[float], float] = Easings.ease_out_quad,
        *,
        now: float | None = None,
    ) -> None:
        now = time.perf_counter() if now is None else now
        if abs(target - self.to_value) < 0.0001:
            if self.is_done(now):
                self.value = target
                self.from_value = target
            return
        if abs(target - self.value) < 0.0001 and self.is_done(now):
            self.to_value = target
            self.value = target
            return
        self.from_value = self.value
        self.to_value = target
        self.duration = max(0.001, duration)
        self.start_time = now
        self.easing = easing

    @property
    def done(self) -> bool:
        return self.is_done()

    def is_done(self, now: float | None = None) -> bool:
        now = time.perf_counter() if now is None else now
        return now - self.start_time >= self.duration

    def tick(self, now: float | None = None) -> float:
        now = time.perf_counter() if now is None else now
        t = (now - self.start_time) / self.duration
        if t >= 1.0:
            self.value = self.to_value
            return self.value
        eased = self.easing(t)
        self.value = self.from_value + (self.to_value - self.from_value) * eased
        return self.value

    def reset(self, value: float) -> None:
        self.value = value
        self.from_value = value
        self.to_value = value
        self.start_time = time.perf_counter() - self.duration


@dataclass
class SpringAnimation:
    stiffness: float
    mass: float
    damping: float
    value: float
    target: float | None = None
    velocity: float = 0.0

    def __post_init__(self) -> None:
        if self.target is None:
            self.target = self.value

    def set_target(self, target: float) -> None:
        self.target = target

    def reset(self, value: float) -> None:
        self.value = value
        self.target = value
        self.velocity = 0.0

    def update(self, dt: float) -> float:
        dt = max(0.0, min(0.033, dt))
        force = -self.stiffness * (self.value - float(self.target)) - self.damping * self.velocity
        acceleration = force / self.mass
        self.velocity += acceleration * dt
        self.value += self.velocity * dt
        return self.value


class AnimationBank:
    def __init__(self) -> None:
        self._smooth: dict[str, SmoothAnimation] = {}
        self._frame_time = time.perf_counter()

    def begin_frame(self, now: float | None = None) -> None:
        """所有 UI 动画共享同一时间戳，避免同一帧内出现不同步的微跳。"""
        self._frame_time = time.perf_counter() if now is None else now

    def value(
        self,
        key: str,
        target: float,
        duration: float = 0.2,
        easing: Callable[[float], float] = Easings.ease_out_quad,
        initial: float | None = None,
    ) -> float:
        anim = self._smooth.get(key)
        if anim is None:
            start = target if initial is None else initial
            anim = SmoothAnimation(value=start, from_value=start, to_value=start, duration=duration)
            self._smooth[key] = anim
        anim.animate(target, duration, easing, now=self._frame_time)
        return anim.tick(self._frame_time)

    def reset(self, key: str, value: float = 0.0) -> None:
        anim = self._smooth.get(key)
        if anim is not None:
            anim.reset(value)

    def reset_prefix(self, prefix: str, value: float = 0.0) -> None:
        for key, anim in self._smooth.items():
            if key.startswith(prefix):
                anim.reset(value)

    def active(self, prefix: str = "") -> bool:
        return any(
            (not prefix or key.startswith(prefix)) and not animation.is_done(self._frame_time)
            for key, animation in self._smooth.items()
        )


class GuiMotionController:
    """灵动岛式 GUI 动画协调器：统一时间、连续反转与瀑布裁剪节奏。"""

    def __init__(self, bank: AnimationBank) -> None:
        self.bank = bank
        self.now = time.perf_counter()

    def begin_frame(self, now: float | None = None) -> None:
        self.now = time.perf_counter() if now is None else now
        self.bank.begin_frame(self.now)

    def value(
        self,
        key: str,
        target: float,
        duration: float,
        easing: Callable[[float], float] = Easings.ease_out_expo,
        *,
        initial: float | None = None,
    ) -> float:
        return self.bank.value(f"gui.{key}", target, duration, easing, initial=initial)

    def waterfall(self, reveal: float, index: int, total: int, stagger: float = 0.065) -> float:
        if reveal >= 0.999 or total <= 1:
            return clamp01(reveal)
        delay = min(0.42, index * stagger)
        span = max(0.24, 1.0 - delay)
        return Easings.ease_out_pow5((reveal - delay) / span)

    def active(self) -> bool:
        return self.bank.active("gui.")


@dataclass
class GuiTransitionTimeline:
    """可逆的全局 GUI 时间线，避免打开和关闭各自重置动画起点。"""

    progress: float = 0.0
    target: float = 0.0
    velocity: float = 0.0

    def set_target(self, target: float) -> None:
        self.target = clamp01(target)

    def reverse_from_current(self) -> None:
        self.target = 0.0 if self.target > 0.5 else 1.0
        # 反向时保留当前位置，但清掉旧方向惯性，避免关窗第一帧继续向前冲。
        self.velocity = 0.0

    def update(self, dt: float) -> float:
        dt = max(0.0, min(0.033, float(dt)))
        # 临界阻尼弹簧：有柔性，但不会像 overshoot 动画一样来回抖动。
        stiffness = 82.0
        damping = 18.0
        acceleration = (self.target - self.progress) * stiffness - self.velocity * damping
        self.velocity += acceleration * dt
        self.progress = clamp01(self.progress + self.velocity * dt)
        if abs(self.target - self.progress) < 0.0015 and abs(self.velocity) < 0.01:
            self.progress = self.target
            self.velocity = 0.0
        return self.progress

    def active(self) -> bool:
        return abs(self.target - self.progress) > 0.001 or abs(self.velocity) > 0.01


@dataclass
class MorphState:
    """可逆的单进度形变状态，尺寸、圆角和裁剪必须共同消费它。"""

    progress: float = 0.0
    target: float = 0.0
    velocity: float = 0.0
    duration: float = 0.24
    _from: float = 0.0
    _started_at: float = 0.0

    def reset(self, value: float, *, now: float | None = None) -> None:
        value = clamp01(value)
        self.progress = value
        self.target = value
        self.velocity = 0.0
        self._from = value
        self._started_at = 0.0 if now is None else float(now)

    def set_target(
        self,
        target: float,
        duration: float | None = None,
        *,
        now: float | None = None,
    ) -> None:
        target = clamp01(target)
        now = time.perf_counter() if now is None else now
        if abs(target - self.target) < 0.0001:
            return
        self.update(now=now)
        self._from = self.progress
        self.target = target
        self.duration = max(0.001, self.duration if duration is None else float(duration))
        self._started_at = now

    def reverse_from_current(
        self,
        duration: float | None = None,
        *,
        now: float | None = None,
    ) -> None:
        self.set_target(0.0 if self.target > 0.5 else 1.0, duration, now=now)

    def update(self, dt: float | None = None, *, now: float | None = None) -> float:
        del dt
        now = time.perf_counter() if now is None else now
        if abs(self.progress - self.target) < 0.0001 and self._started_at <= 0.0:
            self.progress = self.target
            self.velocity = 0.0
            return self.progress
        elapsed = max(0.0, now - self._started_at)
        linear = clamp01(elapsed / max(0.001, self.duration))
        eased = Easings.ease_out_expo(linear)
        previous = self.progress
        self.progress = self._from + (self.target - self._from) * eased
        self.velocity = (self.progress - previous) / max(0.0001, elapsed if elapsed > 0.0 else self.duration)
        if linear >= 1.0 or abs(self.progress - self.target) < 0.0005:
            self.progress = self.target
            self.velocity = 0.0
            self._started_at = 0.0
            self._from = self.target
        return self.progress

    def active(self) -> bool:
        return abs(self.target - self.progress) > 0.0005


@dataclass
class ReversibleExpoTimeline:
    """A reversible ease-out-expo timeline that never restarts on reversal."""

    progress: float = 0.0
    target: float = 0.0
    duration: float = 0.22
    def set_target(self, target: float) -> None:
        self.target = clamp01(target)

    def update(self, dt: float) -> float:
        dt = max(0.0, min(0.05, float(dt)))
        difference = self.target - self.progress
        if abs(difference) <= 0.0005:
            self.progress = self.target
            return self.progress
        # easeOutExpo 的连续形式。反向只改变目标，当前位置不会跳变。
        alpha = 1.0 - pow(2.0, -10.0 * dt / max(0.001, self.duration))
        self.progress = clamp01(self.progress + difference * alpha)
        if abs(self.target - self.progress) <= 0.0005:
            self.progress = self.target
        return self.progress

    def active(self) -> bool:
        return abs(self.target - self.progress) > 0.0005


@dataclass
class IslandContainerState:
    """Frame-rate independent continuous target tracking for island containers."""

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    radius: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    target_width: float = 0.0
    target_height: float = 0.0
    target_radius: float = 0.0
    response_per_60hz_frame: float = 0.20
    initialized: bool = False
    content: ReversibleExpoTimeline = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = ReversibleExpoTimeline()

    def set_target_geometry(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float | None = None,
    ) -> None:
        self.target_x = float(x)
        self.target_y = float(y)
        self.target_width = max(0.0, float(width))
        self.target_height = max(0.0, float(height))
        self.target_radius = max(0.0, float(self.target_height * 0.5 if radius is None else radius))
        if not self.initialized:
            self.x = self.target_x
            self.y = self.target_y
            self.width = self.target_width
            self.height = self.target_height
            self.radius = self.target_radius
            self.initialized = True

    def set_content_target(self, target: float, duration: float | None = None) -> None:
        if duration is not None:
            self.content.duration = max(0.001, float(duration))
        self.content.set_target(target)

    def update(self, dt: float) -> None:
        dt = max(0.0, min(0.05, float(dt)))
        response = max(0.001, min(0.999, self.response_per_60hz_frame))
        alpha = 1.0 - pow(1.0 - response, dt * 60.0)
        for name in ("x", "y", "width", "height", "radius"):
            current = float(getattr(self, name))
            target = float(getattr(self, f"target_{name}"))
            value = current + (target - current) * alpha
            if abs(target - value) < 0.025:
                value = target
            setattr(self, name, value)
        self.content.update(dt)

    def active(self) -> bool:
        geometry_active = any(
            abs(float(getattr(self, name)) - float(getattr(self, f"target_{name}"))) > 0.025
            for name in ("x", "y", "width", "height", "radius")
        )
        return geometry_active or self.content.active()


@dataclass
class MapIslandState:
    """Tactical map container and its child reveal share one continuous state."""

    container: IslandContainerState = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.container is None:
            self.container = IslandContainerState(response_per_60hz_frame=0.20)

    def set_target(self, x: float, y: float, width: float, height: float, expanded: bool) -> None:
        radius = 6.0 + (4.0 if expanded else 0.0)
        self.container.set_target_geometry(x, y, width, height, radius)
        self.container.set_content_target(1.0 if expanded else 0.0, 0.22)

    def update(self, dt: float) -> None:
        self.container.update(dt)

    @property
    def progress(self) -> float:
        return self.container.content.progress

    def active(self) -> bool:
        return self.container.active()
