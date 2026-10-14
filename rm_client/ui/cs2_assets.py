"""Optional, machine-local CS2 UI pack. Never reads a Steam installation.

Only the explicit offline importer handles compiled game resources. Runtime
verifies and preloads a small allowlisted pack once, before presentation; paint
and event feedback never extract files, spawn processes or perform network I/O.
Valve resources are not part of the public source/release distribution.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QImage, QImageReader, QPainter

from ..runtime_paths import RuntimePaths

_LOG = logging.getLogger(__name__)
IMAGE_IDS = frozenset({
    "dots", "skull", "skull_teammate", "alive_skull", "alive_blue", "alive_gold",
    "money", "buy_icon", "kill_mask", "kill_extra", "kill_default", "kill_headshot", "kill_blast",
    "kill_flag", "elimination", "person",
    "buy_ammo", "buy_recovery", "buy_revive",
    *(f"kill_{i}" for i in range(1, 6)),
})
SOUND_IDS = frozenset({"kill", "purchase", "cant_buy", "buy_select", "buy_hover"})
# Event gains resolved from this installed build's game_sounds_ui table.
CUE_GAINS = {"kill": .6, "purchase": .3, "cant_buy": .4, "buy_select": .5, "buy_hover": .3}
FONT_IDS = frozenset({"font_regular", "font_bold", "font_condensed", "font_mono", "font_timer"})


class Cs2Assets:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.images: dict[str, QImage] = {}
        self.paths: dict[str, Path] = {}
        self.families: dict[str, str] = {}
        self.error = ""
        self._audio = None
        self._tinted = {}
        if root is not None:
            self._load(Path(root))

    @property
    def available(self) -> bool:
        return bool(self.images)

    def _load(self, root: Path) -> None:
        try:
            manifest_path = root / "manifest.json"
            if not manifest_path.is_file():
                return
            if manifest_path.stat().st_size > 128 * 1024:
                raise ValueError("oversized CS2 manifest")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema") != 1 or manifest.get("scope") != "local-personal-use":
                raise ValueError("unsupported CS2 personal pack")
            entries = manifest["assets"]
            if not isinstance(entries, dict) or len(entries) > len(IMAGE_IDS | SOUND_IDS | FONT_IDS):
                raise ValueError("invalid CS2 asset table")
            images, paths, fonts, total = {}, {}, {}, 0
            for key, entry in entries.items():
                if key not in IMAGE_IDS | SOUND_IDS | FONT_IDS:
                    raise ValueError("unknown CS2 asset id")
                relative = Path(entry["file"])
                # Flat exported names only; reject absolute paths, traversal and
                # symlinks/junctions that escape the personal pack.
                if relative.name != str(relative) or relative.is_absolute():
                    raise ValueError("unsafe CS2 asset path")
                path = (root / relative).resolve()
                if not path.is_relative_to(root.resolve()):
                    raise ValueError("CS2 asset escapes personal pack")
                if path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("oversized CS2 asset")
                data = path.read_bytes()
                total += len(data)
                if len(data) > 8 * 1024 * 1024 or total > 32 * 1024 * 1024:
                    raise ValueError("oversized CS2 personal pack")
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError(f"CS2 asset hash mismatch: {key}")
                if key in IMAGE_IDS:
                    if path.suffix != ".png":
                        raise ValueError("runtime images must be exported PNGs")
                    reader = QImageReader(str(path))
                    size = reader.size()
                    if not size.isValid() or size.width() * size.height() > 4_194_304:
                        raise ValueError("oversized or invalid CS2 image")
                    image = reader.read()
                    if image.isNull():
                        raise ValueError(f"CS2 image decode failed: {key}")
                    images[key] = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                elif key in FONT_IDS:
                    if path.suffix not in {".otf", ".ttf"}:
                        raise ValueError("runtime fonts must be exported OTF/TTF")
                    fonts[key] = data
                elif path.suffix != ".wav":
                    raise ValueError("runtime sounds must be exported PCM WAVs")
                paths[key] = path
            self.images, self.paths = images, paths  # All-or-nothing activation.
            if isinstance(QGuiApplication.instance(), QGuiApplication):
                for key, data in fonts.items():
                    font_id = QFontDatabase.addApplicationFontFromData(data)
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        self.families[key] = families[0]
        except (OSError, KeyError, TypeError, ValueError) as exc:
            self.error = str(exc)
            _LOG.warning("Ignoring local CS2 UI pack: %s", exc)

    def image(self, key: str) -> QImage:
        return self.images.get(key, QImage())

    def tinted(self, key: str, color: QColor) -> QImage:
        image = self.image(key)
        if image.isNull():
            return image
        token = (key, color.rgba())
        if token not in self._tinted:
            tinted = image.copy()
            p = QPainter(tinted)
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(tinted.rect(), color)
            p.end()
            if len(self._tinted) >= 64:
                self._tinted.pop(next(iter(self._tinted)))
            self._tinted[token] = tinted
        return self._tinted[token]

    def preload_audio(self) -> None:
        if self._audio is not None or self.root is None or QCoreApplication.instance() is None:
            return
        if not any(key in self.paths for key in SOUND_IDS):
            return
        from ..ui_audio import ReliableAudioPool
        self._audio = ReliableAudioPool(self.root, voices_per_sound=2, fallback_voices=4)
        self._audio.preload(self.paths[key].name for key in SOUND_IDS if key in self.paths)

    def play(self, key: str, volume: float) -> bool:
        # Preload must have occurred at application startup, not on a kill.
        if self._audio is None or key not in self.paths:
            return False
        return self._audio.play(self.paths[key].name, max(0.0, min(1.0, volume)) * CUE_GAINS.get(key,1) * 100.0)


@lru_cache(maxsize=1)
def local_cs2_assets() -> Cs2Assets:
    return Cs2Assets(RuntimePaths.discover().user_data_root / "cs2_ui_pack")
