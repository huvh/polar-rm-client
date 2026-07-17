from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time

from ..vision import ArmorObservation, VisionResult


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _shortest_angle_delta(start: float, end: float, period: float) -> float:
    return (end - start + period * 0.5) % period - period * 0.5


def _armor_key(armor: ArmorObservation) -> tuple[int, int, bool]:
    target_id = armor.target_id if armor.target_id >= 0 else armor.armor_id
    plate_id = armor.plate_id if armor.plate_id >= 0 else armor.armor_id
    return target_id, plate_id, bool(armor.predicted)


def _lerp_points(
    start: tuple[tuple[float, float], ...],
    end: tuple[tuple[float, float], ...],
    amount: float,
) -> tuple[tuple[float, float], ...]:
    if len(start) != len(end):
        return end
    return tuple(
        (sx + (ex - sx) * amount, sy + (ey - sy) * amount)
        for (sx, sy), (ex, ey) in zip(start, end)
    )


def _interpolate_armor(
    start: ArmorObservation | None,
    end: ArmorObservation,
    amount: float,
) -> ArmorObservation:
    if start is None:
        return end
    yaw_delta = _shortest_angle_delta(start.yaw_rad, end.yaw_rad, math.tau)
    return replace(
        end,
        confidence=_clamp(
            start.confidence + (end.confidence - start.confidence) * amount,
            0.0,
            1.0,
        ),
        points=_lerp_points(start.points, end.points, amount),
        distance_m=max(
            0.0,
            start.distance_m + (end.distance_m - start.distance_m) * amount,
        ),
        depth_m=max(
            0.0,
            start.depth_m + (end.depth_m - start.depth_m) * amount,
        ),
        back_points=_lerp_points(start.back_points, end.back_points, amount),
        yaw_rad=start.yaw_rad + yaw_delta * amount,
        light_strength=_clamp(
            start.light_strength
            + (end.light_strength - start.light_strength) * amount,
            0.0,
            1.0,
        ),
    )


def _has_geometry(result: VisionResult) -> bool:
    if result.tracking_state.lower() in {
        "lost",
        "dead",
        "off",
        "extinguish",
        "extinguished",
        "disconnected",
    }:
        return False
    values = result.detections + result.predicted_armors
    if result.aim_armor is not None:
        values += (result.aim_armor,)
    return any(len(armor.points) == 4 for armor in values)


@dataclass(frozen=True)
class _TimedVisionFrame:
    result: VisionResult
    received_at: float


class VisionRenderInterpolator:
    """在低频视觉结果之间生成仅供显示使用的高刷新率快照。"""

    def __init__(self, *, max_extrapolation: float = 0.05) -> None:
        self.max_extrapolation = max(0.0, float(max_extrapolation))
        self._source = ""
        self._previous: _TimedVisionFrame | None = None
        self._current: _TimedVisionFrame | None = None
        self._interval = 1.0 / 30.0

    @property
    def sequence(self) -> int:
        return self._current.result.sequence if self._current else -1

    @property
    def source_interval(self) -> float:
        return self._interval

    def clear(self) -> None:
        self._previous = None
        self._current = None

    def push(
        self,
        result: VisionResult,
        *,
        source: str,
        received_at: float | None = None,
    ) -> bool:
        now = time.perf_counter() if received_at is None else float(received_at)
        if source != self._source:
            self._source = source
            self.clear()
        if self._current is not None and result.sequence == self._current.result.sequence:
            return False
        if self._current is not None and result.sequence < self._current.result.sequence:
            self.clear()
        frame = _TimedVisionFrame(result, now)
        if self._current is None:
            self._previous = frame
            self._current = frame
            return True
        interval = now - self._current.received_at
        if interval > 0.001:
            measured = _clamp(interval, 1.0 / 120.0, 1.0 / 8.0)
            self._interval = self._interval * 0.72 + measured * 0.28
        self._previous = self._current
        self._current = frame
        return True

    def sample(self, render_time: float | None = None) -> VisionResult | None:
        now = time.perf_counter() if render_time is None else float(render_time)
        current = self._current
        previous = self._previous
        if current is None:
            return None
        if not _has_geometry(current.result):
            return current.result
        if previous is None or previous is current or not _has_geometry(previous.result):
            return current.result
        interval = max(0.001, current.received_at - previous.received_at)
        render_at = now - _clamp(self._interval, 1.0 / 120.0, 0.08)
        amount = (render_at - previous.received_at) / interval
        if amount > 1.0:
            elapsed = max(0.0, now - current.received_at)
            amount = 1.0 + min(elapsed, self.max_extrapolation) / interval
        amount = max(0.0, amount)
        return self._interpolate_result(previous.result, current.result, amount)

    @staticmethod
    def _interpolate_result(
        start: VisionResult,
        end: VisionResult,
        amount: float,
    ) -> VisionResult:
        start_values = {
            _armor_key(armor): armor
            for armor in start.detections + start.predicted_armors
        }
        detections = tuple(
            _interpolate_armor(start_values.get(_armor_key(armor)), armor, amount)
            for armor in end.detections
        )
        predicted = tuple(
            _interpolate_armor(start_values.get(_armor_key(armor)), armor, amount)
            for armor in end.predicted_armors
        )
        aim_start = None
        if end.aim_armor is not None:
            if start.aim_armor is not None and _armor_key(start.aim_armor) == _armor_key(end.aim_armor):
                aim_start = start.aim_armor
            else:
                aim_start = start_values.get(_armor_key(end.aim_armor))
        aim = (
            _interpolate_armor(aim_start, end.aim_armor, amount)
            if end.aim_armor is not None
            else None
        )
        return replace(
            end,
            detections=detections,
            predicted_armors=predicted,
            aim_armor=aim,
            aim_yaw_deg=start.aim_yaw_deg
            + _shortest_angle_delta(start.aim_yaw_deg, end.aim_yaw_deg, 360.0)
            * amount,
            aim_pitch_deg=start.aim_pitch_deg
            + (end.aim_pitch_deg - start.aim_pitch_deg) * amount,
        )


@dataclass(frozen=True)
class TargetHudPresenceFrame:
    opacity: float
    scale: float
    phase: str

    @property
    def visible(self) -> bool:
        return self.opacity > 0.001


class TargetHudPresenceState:
    """中心 TargetHUD 的出现、十秒保留和可逆退出状态机。"""

    def __init__(
        self,
        *,
        hold_seconds: float = 10.0,
        appear_seconds: float = 0.18,
        fade_seconds: float = 0.26,
    ) -> None:
        self.hold_seconds = float(hold_seconds)
        self.appear_seconds = float(appear_seconds)
        self.fade_seconds = float(fade_seconds)
        self.phase = "Hidden"
        self.opacity = 0.0
        self.scale = 0.94
        self._transition_started = 0.0
        self._transition_opacity = 0.0
        self._transition_scale = 0.94
        self._lost_at: float | None = None
        self._last_now: float | None = None

    @staticmethod
    def _ease_out_cubic(value: float) -> float:
        value = _clamp(value, 0.0, 1.0)
        return 1.0 - (1.0 - value) ** 3

    def _begin_appearing(self, now: float) -> None:
        self.phase = "Appearing"
        self._transition_started = now
        self._transition_opacity = self.opacity
        self._transition_scale = self.scale
        self._lost_at = None

    def _begin_fading(self, now: float) -> None:
        self.phase = "Fading"
        self._transition_started = now
        self._transition_opacity = self.opacity
        self._transition_scale = self.scale

    def update(self, now: float, valid_target: bool) -> TargetHudPresenceFrame:
        now = float(now)
        dt = 0.0 if self._last_now is None else _clamp(now - self._last_now, 0.0, 0.1)
        self._last_now = now

        if valid_target:
            if self.phase in {"Hidden", "Grace10s", "Fading"}:
                if self.opacity >= 0.999:
                    self.phase = "Visible"
                    self.opacity = 1.0
                    self.scale = 1.0
                    self._lost_at = None
                else:
                    self._begin_appearing(now)
            if self.phase == "Appearing":
                progress = (now - self._transition_started) / max(0.001, self.appear_seconds)
                eased = self._ease_out_cubic(progress)
                self.opacity = self._transition_opacity + (1.0 - self._transition_opacity) * eased
                self.scale = self._transition_scale + (1.0 - self._transition_scale) * eased
                if progress >= 1.0:
                    self.phase = "Visible"
                    self.opacity = 1.0
                    self.scale = 1.0
            return TargetHudPresenceFrame(self.opacity, self.scale, self.phase)

        if self.phase in {"Appearing", "Visible"}:
            self.phase = "Grace10s"
            self._lost_at = now
        if self.phase == "Grace10s":
            # 目标在出现途中丢失时仍平滑完成出现，然后完整保留十秒。
            settle = 1.0 - math.exp(-18.0 * dt) if dt > 0.0 else 0.0
            self.opacity += (1.0 - self.opacity) * settle
            self.scale += (1.0 - self.scale) * settle
            if self._lost_at is not None and now - self._lost_at >= self.hold_seconds:
                self._begin_fading(now)
        if self.phase == "Fading":
            progress = (now - self._transition_started) / max(0.001, self.fade_seconds)
            eased = self._ease_out_cubic(progress)
            self.opacity = self._transition_opacity * (1.0 - eased)
            self.scale = self._transition_scale + (0.96 - self._transition_scale) * eased
            if progress >= 1.0:
                self.phase = "Hidden"
                self.opacity = 0.0
                self.scale = 0.94
                self._lost_at = None
        return TargetHudPresenceFrame(self.opacity, self.scale, self.phase)


class AngleRenderTrack:
    """按显示帧沿最短角路径连续追踪低频角度。"""

    def __init__(self) -> None:
        self.value = 0.0
        self._initialized = False
        self._last_time: float | None = None

    def reset(self, value: float = 0.0) -> None:
        self.value = (float(value) + 180.0) % 360.0 - 180.0
        self._initialized = True
        self._last_time = None

    def sample(self, now: float, target: float, *, response: float = 16.0) -> float:
        target = (float(target) + 180.0) % 360.0 - 180.0
        if not self._initialized:
            self.reset(target)
            self._last_time = float(now)
            return self.value
        dt = 0.0 if self._last_time is None else _clamp(float(now) - self._last_time, 0.0, 0.05)
        self._last_time = float(now)
        amount = 1.0 - math.exp(-max(0.1, float(response)) * dt)
        delta = _shortest_angle_delta(self.value, target, 360.0)
        self.value = (self.value + delta * amount + 180.0) % 360.0 - 180.0
        return self.value


class ScalarRenderTrack:
    """按显示帧平滑遥测数值，不修改原始状态。"""

    def __init__(self) -> None:
        self.value = 0.0
        self._initialized = False
        self._last_time: float | None = None

    def sample(self, now: float, target: float, *, response: float = 18.0) -> float:
        target = float(target)
        if not self._initialized:
            self.value = target
            self._initialized = True
            self._last_time = float(now)
            return self.value
        dt = 0.0 if self._last_time is None else _clamp(float(now) - self._last_time, 0.0, 0.05)
        self._last_time = float(now)
        amount = 1.0 - math.exp(-max(0.1, float(response)) * dt)
        self.value += (target - self.value) * amount
        return self.value
