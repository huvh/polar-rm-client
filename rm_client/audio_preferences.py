"""Local audio output preferences. No paths/configuration in the CS2 install."""
from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import tempfile
import weakref

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaDevices
from .runtime_paths import RuntimePaths

POOLS = weakref.WeakSet()


@dataclass(frozen=True)
class AudioPreferences:
    device_id: str = "default"
    master_volume: int = 100
    mute_unfocused: bool = False


def validate_audio(data):
    if not isinstance(data, dict) or set(data) - set(asdict(AudioPreferences())):
        raise ValueError("未知音频设置")
    values = {**asdict(AudioPreferences()), **data}
    device = values["device_id"]
    if not isinstance(device, str) or len(device) > 512 or (device != "default" and
            (len(device) % 2 or not device or any(c not in "0123456789abcdef" for c in device))):
        raise ValueError("无效音频设备ID")
    if type(values["master_volume"]) is not int or not 0 <= values["master_volume"] <= 100:
        raise ValueError("无效主音量")
    if type(values["mute_unfocused"]) is not bool:
        raise ValueError("无效后台静音选项")
    return AudioPreferences(**values)


def audio_path():
    return RuntimePaths.discover().user_data_root / "audio_preferences.json"


@lru_cache(maxsize=1)
def current_audio():
    try:
        path = audio_path()
        if path.is_file() and path.stat().st_size <= 4096:
            return validate_audio(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        pass
    return AudioPreferences()


@lru_cache(maxsize=1)
def selected_output():
    device_id = current_audio().device_id
    return next((d for d in QMediaDevices.audioOutputs() if bytes(d.id()).hex() == device_id),
                QMediaDevices.defaultAudioOutput())


def cue_volume(volume):
    prefs = current_audio()
    if prefs.mute_unfocused and QGuiApplication.instance() is not None and QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
        return 0.0
    return max(0.0, min(100.0, float(volume))) * prefs.master_volume / 100.0


def save_audio(prefs):
    prefs = validate_audio(asdict(prefs))
    path = audio_path(); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="audio-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(asdict(prefs), stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    current_audio.cache_clear(); selected_output.cache_clear()
    for pool in list(POOLS):
        pool.apply_audio_preferences()
