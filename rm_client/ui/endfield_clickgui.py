"""Endfield industrial chrome over Jello's unchanged cards/input/timelines.

Only ClickGUI opts into this draw list. Esc's source-authored settings theme,
HUD materials and the independently usable Jello renderer are not involved.
Sprites have fixed absolute keys, exposed to the existing GPU image prewarm.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage

from ..model import CATEGORIES
from .clickgui_gpu import ClickGuiDrawList
from .jello_clickgui import JelloClickGuiRenderer, JELLO_PANEL_HEADER, JELLO_MODULE_ROW


def _tint(color, rgb):
    result = QColor(rgb)
    result.setAlpha(color.alpha())
    return result


def _surface(color):
    r, g, b, _ = color.getRgb()
    if b > r + 50 and b > g + 15:
        return _tint(color, "#6a6845")  # Warm active row, not an opaque neon slab.
    if r > 180 and g > 180 and b > 180:
        return _tint(color, "#393b3e")
    return color


class IndustrialDrawList(ClickGuiDrawList):
    _before_panel_title = None

    @contextmanager
    def panel_chrome(self, decorate):
        """One-shot insertion after Jello's backplates, before its first label.

        Scope this to _build_panel, never to build(): modal/dropdown labels must
        not consume the hook. No command reordering or copy of Jello's layout.
        """
        previous = self._before_panel_title
        self._before_panel_title = decorate
        try:
            yield
        finally:
            self._before_panel_title = previous

    def rect(self, rect, radius, fill, outline=None, outline_width=0.0,
             gradient=None, clip=None, clip_radius=0.0):
        is_blue = fill.blue() > fill.red() + 50 and fill.blue() > fill.green() + 15
        knob = radius >= 10 and rect.width() < 32 and rect.height() < 32
        mapped = _tint(fill, "#fff100") if is_blue and rect.height() < 10 else _surface(fill)
        if knob and fill.red() > 240:
            mapped = _tint(fill, "#eeeeee")
        # Geometry, including rounded panel masks and dropdown seam clips,
        # belongs to Jello. Industrial edges are additional inset rules only.
        super().rect(rect, radius, mapped, outline, outline_width,
                     _surface(gradient) if gradient is not None else None, clip, clip_radius)

    def text(self, rect, text, font, color, *args, **kwargs):
        decorate = self._before_panel_title
        self._before_panel_title = None  # Decoration may itself submit text.
        on_yellow = decorate() if decorate is not None else False
        if max(color.red(), color.green(), color.blue()) < 80:
            color = _tint(color, "#212121" if on_yellow else "#eeeeee")
            if color.alpha() < 160:
                color.setAlpha(min(255, round(color.alpha() * 1.5)))
        # Preserve shaped text, weight, density, snapping and line transforms.
        super().text(rect, text, font, color, *args, **kwargs)


class EndfieldClickGuiRenderer(JelloClickGuiRenderer):
    draw_list_type = IndustrialDrawList

    def __init__(self, asset_root: Path) -> None:
        # Initialise before super: Jello validates the virtual image_assets
        # property in its constructor. resolve/stat/decode happen only here.
        asset_root = Path(asset_root).expanduser().resolve()
        theme_root = asset_root.parent / "endfield_settings"
        self.terrain_image = theme_root / "tab_selected.png"
        self.contour_image = theme_root / "deco_settings_bg_contour.png"
        self.texture_image = theme_root / "deco_settings_texture.png"
        super().__init__(asset_root)
        # Also preload the diagnostic raster path. GPU textures belong to the
        # existing image_assets/prewarm_images pipeline, not a captured UI.
        self._compat_images.update(
            (str(path), QImage(str(path))) for path in self.image_assets
            if self._image_available(path)
        )
        self._available_images = frozenset(
            path for path in self._available_images
            if not self._compat_images[str(path)].isNull()
        )
        self._theme_aspects = {
            path: self._compat_images[str(path)].width() / self._compat_images[str(path)].height()
            for path in (self.terrain_image, self.contour_image, self.texture_image)
            if self._image_available(path)
        }

    @property
    def image_assets(self) -> tuple[Path, ...]:
        return (*super().image_assets, self.terrain_image, self.contour_image, self.texture_image)

    def _build_panel_chrome(self, host, commands, category, panel, scale, alpha):
        alpha = min(1.0, max(0.0, alpha))
        header_h = JELLO_PANEL_HEADER * scale
        header = QRectF(panel.left() + 3 * scale, panel.top() + 3 * scale,
                        panel.width() - 6 * scale, header_h - 6 * scale)
        on_yellow = self._image_available(self.terrain_image)
        if on_yellow:
            # Crop, don't stretch, the original yellow/topographic tab. The
            # inset clip stays within the parent's rounded silhouette. Exclude
            # the sprite's transparent side notches so every title glyph has a
            # yellow backing. Texture keys never depend on scale or opacity.
            image_w = header.width() / 0.75
            image_h = image_w / self._theme_aspects[self.terrain_image]
            image_rect = QRectF(header.center().x() - image_w / 2,
                                header.center().y() - image_h / 2, image_w, image_h)
            commands.image(image_rect, self.terrain_image,
                           QColor(255, 255, 255, round(255 * alpha)), header)

        body = QRectF(panel.left() + 3 * scale, panel.top() + header_h,
                      panel.width() - 6 * scale, panel.height() - header_h - 3 * scale)
        if self._image_available(self.contour_image):
            commands.image(
                QRectF(body.left(), body.top() + 5 * scale, body.width(),
                       body.width() / self._theme_aspects[self.contour_image]),
                self.contour_image, QColor(190, 193, 187, round(36 * alpha)), body,
            )
        if self._image_available(self.texture_image):
            texture_w = 100 * scale
            texture_h = texture_w / self._theme_aspects[self.texture_image]
            commands.image(
                QRectF(body.right() - texture_w, body.bottom() - texture_h,
                       texture_w, texture_h),
                self.texture_image, QColor(190, 193, 187, round(22 * alpha)), body,
            )

        # The registration serial occupies title padding, not the label band.
        # Explicit ink bypasses the normal dark-to-light map.
        ClickGuiDrawList.text(
            commands,
            QRectF(panel.right() - 60 * scale, panel.top() + 4 * scale, 47 * scale, 10 * scale),
            f"/{CATEGORIES.index(category) + 1:02}", self._font(host, "jello_medium", 10),
            QColor(33, 33, 33, round(180 * alpha)) if on_yellow
            else QColor(190, 193, 187, round(180 * alpha)),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, render_scale=scale,
        )
        return on_yellow

    def _build_panel(self, host, state, commands, category, panel, scale, alpha):
        # Insert before the title: rows/scrollbars cover body decoration, and
        # build() still appends modal/dropdown commands above all panel chrome.
        with commands.panel_chrome(
            lambda: self._build_panel_chrome(host, commands, category, panel, scale, alpha)
        ):
            super()._build_panel(host, state, commands, category, panel, scale, alpha)

        alpha = min(1.0, max(0.0, alpha))
        yellow = QColor(255, 241, 0, round(220 * alpha))
        commands.rect(panel, 10 * scale, QColor(0, 0, 0, 0),
                      QColor(139, 145, 140, round(95 * alpha)), 0.75 * scale)
        header = JELLO_PANEL_HEADER * scale
        commands.rect(QRectF(panel.left() + 20 * scale, panel.top() + header - 2 * scale,
                             34 * scale, 2 * scale), 0, yellow)
        viewport = QRectF(panel.left(), panel.top() + header,
                          panel.width(), panel.height() - header)
        scroll = state.panel_scroll.get(category, 0)
        for i, module in enumerate(self._modules_for(host, category)):
            if module.enabled:
                accent = QRectF(panel.left() + 3 * scale,
                                viewport.top() + i * JELLO_MODULE_ROW * scale - scroll + 7 * scale,
                                2 * scale, 16 * scale).intersected(viewport)
                if not accent.isEmpty():
                    commands.rect(accent, 0, QColor(255, 241, 0, round(220 * alpha * alpha)),
                                  clip=panel, clip_radius=10 * scale)
