"""Nonblocking, deterministic DT7 probe. Never owns a serial port."""
from __future__ import annotations

from collections import Counter
import math

PROBE_BITS = 1 << 12  # X, must be verified non-actuating on the actual firmware.


class Dt7Probe:
    def __init__(self, now: float, *, baseline_s=1.0, press_s=0.9, hold_s=1.6):
        self.phase = "baseline"
        self.phase_at = float(now)
        if not math.isfinite(self.phase_at):
            raise ValueError("finite probe start required")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or not 0.1 <= value <= 30
               for value in (baseline_s, press_s, hold_s)):
            raise ValueError("probe phases must be finite, bounded 0.1..30 seconds")
        self.durations = {"baseline": baseline_s, "press": press_s, "hold": hold_s}
        self.samples = {key: [] for key in self.durations}
        self.baseline = None
        self._last_sample = (0, 0.0)
        self.result = None
        self.frames_at_press = 0

    def observe(self, key, sampled_at, sequence, now):
        if self.result is not None:
            return
        if (not isinstance(key, int) or isinstance(key, bool) or not 0 <= key <= 0xffff
                or not isinstance(sampled_at, (int, float)) or isinstance(sampled_at, bool)
                or not isinstance(sequence, int) or isinstance(sequence, bool)
                or not math.isfinite(sampled_at) or not self.phase_at <= sampled_at <= now
                or now - sampled_at > 0.75 or sequence <= self._last_sample[0]
                or sampled_at <= self._last_sample[1]):
            return
        self._last_sample = (sequence, sampled_at)
        self.samples[self.phase].append((sampled_at, key))
        if len(self.samples[self.phase]) > 2048:
            del self.samples[self.phase][0]

    def advance(self, now, frames_sent):
        if self.result is not None or now - self.phase_at < self.durations[self.phase]:
            return self.phase
        if self.phase == "baseline":
            values = [key for _, key in self.samples["baseline"]]
            if len(values) < 2:
                self.abort("NO-READBACK", "发送前没有至少两个新鲜车端键位样本")
                return "done"
            self.baseline = Counter(values).most_common(1)[0][0]
            if any(value & PROBE_BITS for value in values):
                self.abort("BLOCKED", "发送前已含 X 探针位，不能证明是本次发送造成的")
                return "done"
            self.phase = "press"
            self.frames_at_press = frames_sent
        elif self.phase == "press":
            self.phase = "hold"
            self.press_frames = max(0, frames_sent - self.frames_at_press)
        else:
            from ..control import evaluate_dt7_selftest, evaluate_dt7_hold
            press = [key for _, key in self.samples["press"]]
            tail = [key for _, key in self.samples["hold"]]
            verdict, detail = evaluate_dt7_selftest(press, PROBE_BITS, self.baseline,
                                                  frames_sent=self.press_frames)
            hv, hd = evaluate_dt7_hold(tail, PROBE_BITS)
            # A single packet cannot establish a steady state or safe expiry.
            if len(press) < 2 and verdict == "PASS":
                verdict, detail = "NO-READBACK", "按住阶段回读不足，不能确认链路"
            if len(tail) < 2 or not self.samples["hold"] or self.samples["hold"][-1][0] < now - 0.75:
                hv, hd = "NO-READBACK", "停发阶段缺少持续新鲜回读，不能判安全"
            self.result = {"verdict": verdict, "detail": detail, "baseline": self.baseline,
                           "hold_verdict": hv, "hold_detail": hd, "frames_sent": self.press_frames,
                           "samples": self.samples}
            self.phase = "done"
            return self.phase
        self.phase_at = now
        return self.phase

    def abort(self, verdict="BLOCKED", detail="authorization epoch changed"):
        self.result = {"verdict": verdict, "detail": detail, "baseline": self.baseline,
                       "hold_verdict": "NO-READBACK", "hold_detail": "测试未完成",
                       "frames_sent": 0, "samples": self.samples}
        self.phase = "done"
