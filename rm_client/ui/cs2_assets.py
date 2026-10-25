"""Validated bundled/local CS2 UI packs. Never reads a Steam installation.

Only the explicit offline importer handles compiled game resources. Runtime
verifies and preloads a small allowlisted pack once, before presentation; paint
and event feedback never extract files, spawn processes or perform network I/O.
The repository owner authorized redistribution of the reviewed bundled pack.
Local imports stay in user_data and are never automatically committed.
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
    "sb_casual", "sb_camera", "sb_unmuted", "sb_ct_silhouette", "sb_menu",
    "sb_competitive", "sb_ping_4", "sb_stats", "sb_elimination",
    *(f"kill_{i}" for i in range(1, 6)),
})
SOUND_IDS = frozenset({"kill", "purchase", "cant_buy", "buy_select", "buy_hover"})
# Event gains resolved from this installed build's game_sounds_ui table.
CUE_GAINS = {"kill": .6, "purchase": .3, "cant_buy": .4, "buy_select": .5, "buy_hover": .3}
FONT_IDS = frozenset({"font_regular", "font_bold", "font_condensed", "font_mono", "font_timer",
                      "font_medium", "font_condensed_regular", "font_mono_regular"})
SCOREBOARD_ADDON_IDS = frozenset({"sb_casual", "sb_camera", "sb_unmuted", "sb_ct_silhouette", "sb_menu",
                                 "sb_competitive", "sb_ping_4", "sb_stats", "sb_elimination",
                                 "font_medium", "font_condensed_regular", "font_mono_regular"})


class Cs2Assets:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.images: dict[str, QImage] = {}
        self.paths: dict[str, Path] = {}
        self.families: dict[str, str] = {}
        self.error = ""
        self._audio = None
        self._tinted = {}
        self._washed = {}
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
            if manifest.get("schema") != 1 or manifest.get("scope") not in {
                "local-personal-use", "authorized-distribution",
            }:
                raise ValueError("unsupported CS2 asset pack")
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

    def washed(self, key: str, color: QColor) -> QImage:
        """Panorama wash multiplies RGB; SourceIn erases multicolour details.

        In particular competitive.svg is an opaque team emblem: treating its
        alpha as a monochrome glyph turns the entire emblem into a square.
        """
        image = self.image(key)
        if image.isNull():
            return image
        token = (key, color.rgba())
        if token not in self._washed:
            washed = image.copy()
            p = QPainter(washed)
            try:
                wash = QColor(color); wash.setAlpha(255)
                p.setCompositionMode(QPainter.CompositionMode_Multiply)
                p.fillRect(washed.rect(), wash)
                p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                p.drawImage(0, 0, image)
                if color.alpha() < 255:
                    p.fillRect(washed.rect(), QColor(0, 0, 0, color.alpha()))
            finally:
                p.end()
            if len(self._washed) >= 64:
                self._washed.pop(next(iter(self._washed)))
            self._washed[token] = washed
        return self._washed[token]

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
    paths = RuntimePaths.discover()
    # A validated personal override remains optional. Clean clones and portable
    # builds load immutable versioned assets without copying runtime user data.
    local = paths.user_data_root / "cs2_ui_pack"
    if (local / "manifest.json").is_file():
        pack = Cs2Assets(local)
        if pack.available:
            # An older valid personal pack must not erase newly bundled Tab
            # icons/faces. Fill ONLY missing new presentation resources; keep
            # personal image/font choices, files and audio routing untouched.
            missing = SCOREBOARD_ADDON_IDS - pack.paths.keys()
            if missing:
                bundled = Cs2Assets(paths.asset("cs2_ui_pack"))
                for key in missing:
                    if key in bundled.paths:
                        pack.paths[key] = bundled.paths[key]
                    if key in bundled.images:
                        pack.images[key] = bundled.images[key]
                    if key in bundled.families:
                        pack.families[key] = bundled.families[key]
            return pack
    return Cs2Assets(paths.asset("cs2_ui_pack"))
