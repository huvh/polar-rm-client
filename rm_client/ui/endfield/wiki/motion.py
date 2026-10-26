"""离线导出的 Unity 曲线采样；运行时不依赖 Unity 或解包工具。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from bisect import bisect_right


def sample_keys(keys, at: float, default: float = 0.0, axis: str | None = None) -> float:
    """采样原始切线/加权 Bézier；无穷切线保留 Unity 的阶跃语义。"""
    if not keys:
        return default

    def scalar(value):
        return float(value[axis]) if axis is not None else float(value)

    if at <= keys[0]["time"]:
        return scalar(keys[0]["value"])
    for left, right in zip(keys, keys[1:]):
        if at > right["time"]:
            continue
        dt = right["time"] - left["time"]
        a, b = scalar(left["value"]), scalar(right["value"])
        if at == right["time"]:
            return b
        if dt <= 0:
            return b
        slope_out, slope_in = scalar(left["outSlope"]), scalar(right["inSlope"])
        if not math.isfinite(slope_out) or not math.isfinite(slope_in):
            return b if at >= right["time"] else a
        u = max(0.0, min(1.0, (at - left["time"]) / dt))
        wo = scalar(left.get("outWeight", 1 / 3)) if left.get("weightedMode", 0) & 2 else 1 / 3
        wi = scalar(right.get("inWeight", 1 / 3)) if right.get("weightedMode", 0) & 1 else 1 / 3
        # x 控制点也受权重影响，先由时间求曲线参数，不能只改 y 控制点。
        lo, hi, t = 0.0, 1.0, u
        if abs(wo - 1 / 3) > 1e-6 or abs(wi - 1 / 3) > 1e-6:
            for _ in range(18):
                t = (lo + hi) / 2
                x = 3 * (1-t)**2 * t * wo + 3 * (1-t) * t*t * (1-wi) + t**3
                if x < u:
                    lo = t
                else:
                    hi = t
        return ((1-t)**3 * a + 3*(1-t)**2*t*(a + slope_out*dt*wo)
                + 3*(1-t)*t*t*(b - slope_in*dt*wi) + t**3*b)
    return scalar(keys[-1]["value"])


class WikiMotion:
    def __init__(self, clips) -> None:
        self.tracks = {}
        self.durations = {}
        self.rotations = {}
        for name, clip in clips.items():
            duration = 0.0
            for group in ("m_FloatCurves", "m_PositionCurves", "m_ScaleCurves"):
                for track in clip.get(group, ()):
                    keys = track["curve"]["m_Curve"]
                    self.tracks[name, track.get("path", ""), track.get("attribute", group)] = keys
                    if keys:
                        duration = max(duration, keys[-1]["time"])
            for path, samples in clip.get("rotation_samples", {}).items():
                self.rotations[name, path] = (tuple(v[0] for v in samples), tuple(v[1] for v in samples))
                if samples:
                    duration = max(duration, samples[-1][0])
            self.durations[name] = duration

    def sample(self, clip, path, attribute, at, default=0.0, axis=None):
        return sample_keys(self.tracks.get((clip, path, attribute)), at, default, axis)

    def rotation(self, clip, path, at, default=0.0):
        """在原60 Hz四元数转换样本间插值；角度已展开，跨越360°不会反转。"""
        samples = self.rotations.get((clip, path))
        if not samples or not samples[0]:
            return default
        times, angles = samples
        index = bisect_right(times, at)
        if index == 0:
            return angles[0]
        if index == len(times):
            return angles[-1]
        ratio = (at - times[index - 1]) / (times[index] - times[index - 1])
        return angles[index - 1] + (angles[index] - angles[index - 1]) * ratio


@dataclass
class WikiHomeHover:
    """独立采样原悬停轨道，移入移出反向时从当前姿态接续。"""
    hovered: bool = False
    changed_at: float = 0.0
    starts: tuple[float, float, float] = (0.0, 0.0, 0.0)
    played: bool = False
    offsets: dict[tuple, float] = field(default_factory=dict)
    held: dict[tuple, float] = field(default_factory=dict)

    def track(self, motion, path, attribute, now, default=0.0, axis=None):
        """按原片段的绝对时间采样，保留闪烁关键帧与悬停反向时的当前姿态。"""
        if not self.played:
            return 0.0
        clip = "wiki_btnoption_select" if self.hovered else "wiki_btnoption_select_out"
        elapsed = max(0.0, now - self.changed_at)
        keys = motion.tracks.get((clip, path, attribute), ())
        key = path, attribute, axis
        if not keys and key in self.held:
            return self.held[key]
        duration = keys[-1]["time"] if keys else motion.durations[clip]
        value = motion.sample(clip, path, attribute, elapsed, default, axis)
        return value + self.offsets.get(key, 0) * max(0, 1 - elapsed / max(.001, duration))

    def values(self, now: float) -> tuple[float, float, float]:
        durations = (.833, 1 / 12, 11 / 60) if self.hovered else (1 / 6, 1 / 12, .1)
        elapsed = max(0.0, now - self.changed_at)
        direction = 1 if self.hovered else -1
        return tuple(max(0.0, min(1.0, start + direction * elapsed / duration))
                     for start, duration in zip(self.starts, durations))

    def sample(self, hovered: bool, now: float, motion=None) -> tuple[float, float, float]:
        if hovered != self.hovered:
            offsets, held = {}, {}
            # 完整退场后的再次移入是新一次播放，不能把上次终点叠加到原片段起点。
            fresh = (hovered and motion is not None and not self.hovered and
                     now - self.changed_at >= motion.durations["wiki_btnoption_select_out"])
            if motion is not None and self.played and not fresh:
                target = "wiki_btnoption_select" if hovered else "wiki_btnoption_select_out"
                for (clip, path, attribute), keys in motion.tracks.items():
                    if clip != "wiki_btnoption_select" or not keys:
                        continue
                    for axis in (tuple(keys[-1]["value"]) if isinstance(keys[-1]["value"], dict) else (None,)):
                        default = keys[-1]["value"][axis] if axis else keys[-1]["value"]
                        value = self.track(motion, path, attribute, now, default, axis)
                        if (target, path, attribute) not in motion.tracks:
                            # Unity 只写当前片段绑定的属性；out 没有几何轨道，应保持当下姿态。
                            held[path, attribute, axis] = value
                        else:
                            offsets[path, attribute, axis] = value - motion.sample(target, path, attribute, 0, default, axis)
            self.starts = self.values(now)
            self.hovered = hovered
            self.changed_at = now
            self.played = True
            self.offsets = offsets
            self.held = held
        return self.values(now)
