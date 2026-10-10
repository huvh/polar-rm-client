from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase


class FontBook:
    def __init__(self) -> None:
        self.loaded: dict[str, str] = {}
        self._font_cache: dict[tuple[str, str, float, int | None], QFont] = {}

    def load_from_project_assets(self, workspace: Path) -> None:
        # A reloaded face may keep its family name. Invalidate configured
        # font values as well as letting Qt invalidate its raster font cache.
        self._font_cache.clear()
        candidates = {
            "axiforma_regular": "axiforma_regular.ttf",
            "axiforma_bold": "axiforma_bold.ttf",
            "axiforma_extrabold": "axiforma_extrabold.ttf",
            "poppins_regular": "Poppins-Regular.ttf",
            "poppins_medium": "Poppins-Medium.ttf",
            "poppins_bold": "Poppins-Bold.ttf",
            "museo": "MuseoSansCyrl-900.ttf",
            "material": "MaterialIcons-Regular.ttf",
            "polaricon": "*icon-Regular.ttf",
            "pingfang": "pingfang_sc_regular.ttf",
            # Debug.jar HUD ArrayList tahoma16 (MODLIST_WHITE.md).
            "tahoma": "tahoma.ttf",
            "jello_light": "Jello-Helvetica-Neue-Light.ttf",
            "jello_medium": "Jello-Helvetica-Neue-Medium.ttf",
        }
        for key, filename in candidates.items():
            path = self._find_font(Path(workspace), filename)
            if not path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                self.loaded[key] = families[0]

    def _find_font(self, workspace: Path, pattern: str) -> Path:
        direct = workspace / "assets" / "fonts" / pattern
        if direct.exists():
            return direct
        for path in workspace.rglob(pattern):
            if ".venv" in path.parts:
                continue
            return path
        return workspace / "__missing_font__"

    def font(self, key: str, size: float, weight: int | None = None) -> QFont:
        family = self.loaded.get(key)
        if family is None:
            family = {
                "material": "Segoe UI Symbol",
                "polaricon": "Segoe UI",
                "museo": "Segoe UI",
                "pingfang": "Microsoft YaHei UI",
                "tahoma": "Tahoma",
            }.get(key, "Segoe UI")
        # HUD builders request the same fonts every display frame. Cache the
        # configured value, but return an implicitly shared copy: callers may
        # change its size/style without poisoning later requests. Keep exact
        # sizes (no rounding) and the resolved family in the key, so loading or
        # replacing a font takes effect immediately without a stale fallback.
        # These are logical point-size descriptors, not metrics or pixels;
        # each painter/atlas still applies its own DPI/DPR and raster policy.
        cache_key = (key, family, size, weight)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return QFont(cached)
        font = QFont(family)
        font.setPointSizeF(size)
        if key == "jello_light":
            # The bundled TTF exposes Light as its only named style, but Qt
            # otherwise reports/request a Normal (400) face. Pin both style
            # name and weight so the GPU atlas cannot silently thicken it.
            font.setStyleName("Light")
            if weight is None:
                font.setWeight(QFont.Weight.Light)
        elif key == "jello_medium":
            font.setStyleName("Medium")
            if weight is None:
                font.setWeight(QFont.Weight.Medium)
        if weight is not None:
            font.setWeight(weight)
        if key == "tahoma":
            # jar createFont tahoma16: PLAIN, antiAlias off → pixel-sharp white list.
            font.setBold(False)
            font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        # Animated sizes and imported fonts must not grow this cache forever.
        if len(self._font_cache) >= 512:
            self._font_cache.pop(next(iter(self._font_cache)))
        self._font_cache[cache_key] = QFont(font)
        return font
