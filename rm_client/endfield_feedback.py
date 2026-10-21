"""Presentation-only startup milestones and debounced power announcements.

No control publisher, protocol changes, fabricated readiness or text-to-speech.
Local game voices are optional; missing cues remain silent with diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path


@dataclass
class BootProgress:
    completed: set[str] = field(default_factory=set)
    finished_at: float | None = None
    announced: bool = False
    PHASES = ("configuration", "graphics", "atlases")

    def mark(self, phase: str, now: float) -> None:
        if phase not in self.PHASES:
            raise ValueError("Unknown boot milestone")
        self.completed.add(phase)
        if len(self.completed) == len(self.PHASES) and self.finished_at is None:
            self.finished_at = now

    @property
    def progress(self) -> float:
        return len(self.completed) / len(self.PHASES)

    def visible(self, now: float) -> bool:
        return self.finished_at is None or now - self.finished_at < 2.0

    def take_announcement(self) -> bool:
        if self.finished_at is None or self.announced:
            return False
        self.announced = True
        return True


@dataclass
class PowerAnnouncement:
    """Energy reserve warning; hysteresis and a 30s refractory interval.

    The official dynamic status owns energy reserve. Generic MQTT connectivity
    or the mock state's nonzero defaults are never a freshness witness.
    """
    low_since: float | None = None
    healthy_since: float | None = None
    latched: bool = False
    last_played: float = -math.inf

    def observe(self, *, now: float, reserve: float, maximum: float,
                threshold: float, fresh: bool, enabled: bool) -> bool:
        if (not enabled or not fresh or not all(math.isfinite(x) for x in (now, reserve, maximum, threshold))
                or maximum <= 0 or reserve < 0 or reserve > maximum):
            self.low_since = self.healthy_since = None
            return False
        percent = 100 * reserve / maximum
        if percent <= threshold:
            self.healthy_since = None
            if self.low_since is None:
                self.low_since = now
            if not self.latched and now - self.low_since >= .65 and now - self.last_played >= 30:
                self.latched = True
                self.last_played = now
                return True
        elif percent >= min(100, threshold + 6):
            self.low_since = None
            if self.healthy_since is None:
                self.healthy_since = now
            if now - self.healthy_since >= 2:
                self.latched = False
        else:
            self.low_since = self.healthy_since = None
        return False


class EndfieldVoice:
    CUES = {"startup": "entering_aic.wav", "power": "insufficient_power.wav"}

    def __init__(self, root: Path):
        self.root = root
        self.pool = None
        self.last_error = ""
        # Only preload verified local cue filenames. Never discover/scan the
        # game install or instantiate a media decoder inside the render loop.
        available = [name for name in self.CUES.values() if (root / name).is_file()]
        if available:
            from .ui_audio import ReliableAudioPool
            self.pool = ReliableAudioPool(root, voices_per_sound=1, fallback_voices=1)
            self.pool.preload(available)

    def play(self, cue: str, *, volume: float = 80) -> bool:
        name = self.CUES[cue]
        if self.pool is None or not (self.root / name).is_file():
            self.last_error = f"Original Endfield voice not installed: {name}"
            return False
        result = self.pool.play(name, volume)
        self.last_error = self.pool.last_error
        return result

    def stop(self) -> None:
        if self.pool is not None:
            self.pool.stop()


class EndfieldFeedback:
    """Read-only observer of already-decoded official energy observations."""
    def __init__(self, root: Path):
        self.boot = BootProgress()
        self.voice = EndfieldVoice(root / "audio")
        self.power = PowerAnnouncement()
        self.identity = None
        self.reserve = self.maximum = None
        self.received_at = -math.inf

    def sync_identity(self, identity) -> None:
        if identity != self.identity:
            self.identity = identity
            self.reserve = self.maximum = None
            self.received_at = -math.inf
            self.power = PowerAnnouncement()

    def observe_referee(self, name: str, data: dict, received_at: float, *, identity) -> None:
        self.sync_identity(identity)
        present = data.get("**present**")
        if name == "RobotStaticStatus" and "max_buffer_energy" in data and (present is None or 13 in present):
            self.maximum = float(data["max_buffer_energy"])
        elif name == "RobotDynamicStatus" and "current_buffer_energy" in data and (present is None or 5 in present):
            self.reserve = float(data["current_buffer_energy"])
            self.received_at = received_at

    def tick(self, *, now: float, identity, connected: bool, enabled: bool, threshold: float,
             launcher: bool = False, audio_enabled: bool = True, volume: float = 80) -> None:
        self.sync_identity(identity)
        if self.boot.take_announcement() and audio_enabled:
            self.voice.play("startup", volume=volume)
        if self.reserve is not None and self.maximum is not None and self.power.observe(
            now=now, reserve=self.reserve, maximum=self.maximum, threshold=threshold,
            fresh=connected and 0 <= now - self.received_at <= 2.0,
            enabled=enabled and audio_enabled and not launcher,
        ):
            self.voice.play("power", volume=volume)
