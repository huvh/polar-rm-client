from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import shutil
from typing import Iterable

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect


class ReliableAudioPool(QObject):
    """预加载短音效，并在 Qt 短音效后端失败时回退到媒体播放器。"""

    def __init__(self, root: Path, voices_per_sound: int = 2, fallback_voices: int = 6) -> None:
        super().__init__()
        self.root = Path(root)
        self.voices_per_sound = max(1, voices_per_sound)
        self._effects: dict[str, list[QSoundEffect]] = {}
        self._pending: dict[str, list[float]] = defaultdict(list)
        self._fallback: list[tuple[QMediaPlayer, QAudioOutput]] = []
        self._fallback_index = 0
        self._fallback_voices = max(1, fallback_voices)
        self.last_sound = ""
        self.last_error = ""
        self.backend = "QSoundEffect"

    def preload(self, names: Iterable[str]) -> None:
        for name in dict.fromkeys(str(item) for item in names):
            path = self.root / name
            # Windows 的 QSoundEffect 后端对 OGG/Vorbis 支持不稳定；压缩音频统一交给 Qt FFmpeg 媒体后端。
            if not path.is_file() or path.suffix.lower() != ".wav" or name in self._effects:
                continue
            voices: list[QSoundEffect] = []
            for _ in range(self.voices_per_sound):
                effect = QSoundEffect(self)
                effect.statusChanged.connect(
                    lambda sound=name, voice=effect: self._on_status(sound, voice, voice.status())
                )
                effect.setSource(QUrl.fromLocalFile(str(path.resolve())))
                voices.append(effect)
            self._effects[name] = voices

    def play(self, name: str, volume: float) -> bool:
        path = self.root / name
        self.last_sound = name
        if not path.is_file():
            self.last_error = f"音效文件不存在: {path}"
            return False
        if path.suffix.lower() != ".wav":
            # OGG/MP3 等压缩音频不再先创建 QSoundEffect，避免启动时刷解码错误。
            return self._play_fallback(path, volume, "")
        self.preload((name,))
        voices = self._effects.get(name, [])
        ready = [voice for voice in voices if voice.status() == QSoundEffect.Status.Ready]
        if ready:
            voice = next((item for item in ready if not item.isPlaying()), ready[0])
            voice.stop()
            voice.setVolume(max(0.0, min(1.0, volume / 100.0)))
            voice.play()
            self.backend = "QSoundEffect"
            self.last_error = ""
            return True
        if any(voice.status() == QSoundEffect.Status.Loading for voice in voices):
            self._pending[name].append(volume)
            return True
        return self._play_fallback(path, volume, "QSoundEffect 无法解码该音效")

    def _on_status(self, name: str, voice: QSoundEffect, status: QSoundEffect.Status) -> None:
        if status == QSoundEffect.Status.Ready and self._pending.get(name):
            volume = self._pending[name].pop(0)
            voice.setVolume(max(0.0, min(1.0, volume / 100.0)))
            voice.play()
            self.backend = "QSoundEffect"
            self.last_error = ""
        elif status == QSoundEffect.Status.Error:
            pending = self._pending.pop(name, [])
            for volume in pending:
                self._play_fallback(self.root / name, volume, "QSoundEffect 加载失败")

    def _play_fallback(self, path: Path, volume: float, reason: str) -> bool:
        if len(self._fallback) < self._fallback_voices:
            output = QAudioOutput(self)
            player = QMediaPlayer(self)
            player.setAudioOutput(output)
            self._fallback.append((player, output))
        player, output = self._fallback[self._fallback_index % len(self._fallback)]
        self._fallback_index = (self._fallback_index + 1) % len(self._fallback)
        player.stop()
        output.setVolume(max(0.0, min(1.0, volume / 100.0)))
        player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        player.play()
        self.backend = "QMediaPlayer"
        self.last_error = reason
        return True


class UiAudioManager:
    USER_SOURCES = frozenset({"clickgui", "keybind"})
    CUSTOM_THEME = "Custom"
    NO_SOUND = "No Sound"
    AUDIO_EXTENSIONS = frozenset({".wav", ".ogg", ".mp3", ".flac", ".m4a", ".aac"})
    CUSTOM_KINDS = frozenset({"enable", "disable", "invalid"})
    THEMES = {
        "Custom": {},
        "Polar Classic": {
            "enable": "polar_classic/module_on.wav",
            "disable": "polar_classic/module_off.wav",
            "invalid": "polar_classic/module_off.wav",
        },
        "LiquidBounce": {
            "enable": "liquidbounce/click-2.ogg",
            "disable": "liquidbounce/click-1.ogg",
            "invalid": "liquidbounce/click-3.ogg",
        },
        "Polar UI": {
            "enable": "polar_ui/module_toggle.wav",
            "disable": "polar_ui/module_toggle.wav",
            "invalid": "polar_ui/action_success.wav",
        },
    }

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.custom_dir = self.root / "custom"
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        self.pool = ReliableAudioPool(self.root, voices_per_sound=2, fallback_voices=4)
        self.pool.preload(name for theme in self.THEMES.values() for name in theme.values())

    def custom_sound_names(self) -> list[str]:
        sounds = [
            path.relative_to(self.root).as_posix()
            for path in self.custom_dir.iterdir()
            if path.is_file() and path.suffix.lower() in self.AUDIO_EXTENSIONS
        ]
        return sorted(sounds, key=str.casefold)

    def import_custom_sound(self, source: Path, kind: str) -> str:
        source = Path(source)
        if kind not in self.CUSTOM_KINDS:
            raise ValueError("Unsupported sound slot")
        if not source.is_file() or source.suffix.lower() not in self.AUDIO_EXTENSIONS:
            raise ValueError("Unsupported audio file")
        safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in source.stem).strip("_") or kind
        target = self.custom_dir / f"{kind}-{safe_stem}{source.suffix.lower()}"
        index = 2
        while target.exists() and target.resolve() != source.resolve():
            target = self.custom_dir / f"{kind}-{safe_stem}-{index}{source.suffix.lower()}"
            index += 1
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        relative = target.relative_to(self.root).as_posix()
        self.pool.preload((relative,))
        return relative

    @classmethod
    def sound_name(cls, theme: str, kind: str, custom_sounds: dict[str, str] | None = None) -> str | None:
        if theme == cls.CUSTOM_THEME:
            selected = str((custom_sounds or {}).get(kind, cls.NO_SOUND))
            return None if selected == cls.NO_SOUND or not selected.startswith("custom/") else selected
        selected = cls.THEMES.get(theme, cls.THEMES["Polar UI"])
        return selected.get(kind, selected["invalid"])

    def module_toggled(
        self,
        enabled: bool,
        source: str,
        *,
        active: bool,
        volume: float,
        theme: str = "Custom",
        custom_sounds: dict[str, str] | None = None,
    ) -> None:
        if active and source in self.USER_SOURCES:
            sound = self.sound_name(theme, "enable" if enabled else "disable", custom_sounds)
            if sound is not None:
                self.pool.play(sound, volume)

    def preview(
        self,
        kind: str,
        volume: float,
        theme: str = "Custom",
        custom_sounds: dict[str, str] | None = None,
    ) -> None:
        adjusted = volume * 0.60 if kind == "invalid" and theme == "Polar Classic" else volume
        sound = self.sound_name(theme, kind, custom_sounds)
        if sound is not None:
            self.pool.play(sound, adjusted)

    def gui_feedback(self, kind: str, volume: float, theme: str) -> None:
        """Play a transition cue without making config hydration noisy."""
        if theme != "Polar UI":
            return
        sound = {
            "expand": "polar_ui/panel_transition.wav",
            "collapse": "polar_ui/panel_transition.wav",
            "success": "polar_ui/action_success.wav",
        }.get(kind)
        if sound:
            self.pool.play(sound, volume)
