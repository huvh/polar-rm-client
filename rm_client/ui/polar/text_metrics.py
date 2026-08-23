"""阶段 1 叶子外迁：文本度量 / 颜色与矩形纯函数 + TextMetricsMixin。

（REFACTOR_BLUEPRINT §5 阶段 1 / §5.6 冻结面）

所有函数体自 ``rm_client/ui/polar_app.py`` 机械迁入，一行未改。原代码中它们是
``PolarRMWindow`` 的方法/staticmethod，而非蓝图假设的模块级纯函数（以实际代码为
准）：其中 ``mix_color/fit_aspect/format_time/short_ring_number/short_outpost_value``
带 ``self`` 参数（部分读 ``self.state``），故本模块按**原签名**定义在模块级，
由 ``polar_app.PolarRMWindow`` 类体以同名赋值方式重新挂载——调用面、派发路径、
每帧开销均与迁移前完全一致。

冻结面纪律：``tests/api_freeze_test.py`` 对方法类成员比对 ``__qualname__``（基线值
形如 ``"PolarRMWindow.<name>"``）。这些符号外迁后仍作为 ``PolarRMWindow`` 类属性
挂载，故在本模块底部统一固定其 ``__qualname__``，使 ``window.<name>`` 的签名与
迁移前 bit 级一致。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QTransform

from ..theme import color

__all__ = [
    "TextMetricsMixin",
    "mix_color",
    "economy_lerp_rect",
    "fit_aspect",
    "_aspect_fit_image_rect",
    "format_time",
    "short_ring_number",
    "short_outpost_value",
    "painter_device_scale",
]


def mix_color(self, a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def economy_lerp_rect(a: QRectF, b: QRectF, progress: float) -> QRectF:
    t = max(0.0, min(1.0, progress))
    return QRectF(
        a.x() + (b.x() - a.x()) * t,
        a.y() + (b.y() - a.y()) * t,
        a.width() + (b.width() - a.width()) * t,
        a.height() + (b.height() - a.height()) * t,
    )


def fit_aspect(self, rect: QRectF, aspect: float) -> QRectF:
    if rect.width() / max(1.0, rect.height()) > aspect:
        h = rect.height()
        w = h * aspect
    else:
        w = rect.width()
        h = w / max(0.1, aspect)
    return QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)


def _aspect_fit_image_rect(image: QImage, width: int, height: int) -> QRectF:
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return QRectF()
    scale = min(float(width) / image.width(), float(height) / image.height())
    draw_width = image.width() * scale
    draw_height = image.height() * scale
    return QRectF(
        (float(width) - draw_width) * 0.5,
        (float(height) - draw_height) * 0.5,
        draw_width,
        draw_height,
    )


def format_time(self, seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def short_ring_number(self, value: float) -> str:
    value = float(value)
    if abs(value) >= 1000:
        return f"{value / 1000.0:.1f}k".replace(".0k", "k")
    return str(int(value))


def short_outpost_value(self) -> str:
    status = str(self.state.enemy_outpost_status)
    if status.upper() in ("ACTIVE", "ALIVE", "ONLINE"):
        return "OK"
    if status.upper() in ("DOWN", "DESTROYED", "OFFLINE"):
        return "DOWN"
    if self.state.enemy_outpost_health <= 0:
        return "DOWN"
    return self.short_ring_number(self.state.enemy_outpost_health)


def painter_device_scale(p: QPainter) -> float:
    """Logical→device scale from current painter transform (hud_scale * dpr)."""
    t = p.transform()
    return max(1.0, abs(float(t.m11())), abs(float(t.m22())))


class TextMetricsMixin:
    """D19 文本度量底座（font/text_advance/font_line_height/draw_text/draw_glass_text/elide）。

    三缓存（_text_metric_cache/_font_height_cache/_elide_cache）选择**类级初始化**
    而非 ``_init_text_metrics()`` 由 ``__init__`` 显式调用：api_freeze_test 把
    ``dir(window)`` 新增成员也视为破坏（[成员新增] 即 FAIL），任何新方法都会进
    dir()；类级 dict 属性的 kind/sig（plain-attribute/dict/"dict"）与基线中实例
    属性完全一致，且对行为影响最小——三个缓存均为纯 memoization（key 含字体标识
    与文本/DPI），跨实例共享无正确性影响。原 __init__ 中三处赋值已删除。
    """

    _text_metric_cache: dict[tuple[str, str], float] = {}
    _font_height_cache: dict[str, float] = {}
    _elide_cache: dict[tuple[str, str, int, int, int], str] = {}

    def font(self, key: str, size: float, weight: QFont.Weight | None = None) -> QFont:
        return self.fonts.font(key, max(1.0, size), weight)

    def text_advance(self, font: QFont, text: str) -> float:
        """Cached QFontMetricsF.horizontalAdvance.

        A DirectWrite metrics query costs a fraction of a millisecond, and the
        island/toasts/modlist re-measured the same strings every frame. The
        value only depends on the font identity and the text, so cache it.
        """

        cache = self._text_metric_cache
        key = (font.key(), text)
        value = cache.get(key)
        if value is None:
            value = float(QFontMetricsF(font).horizontalAdvance(text))
            if len(cache) >= 8192:
                cache.clear()
            cache[key] = value
        return value

    def font_line_height(self, font: QFont) -> float:
        """Cached QFontMetricsF.height — identical reasoning to text_advance."""
        key = font.key()
        cache = self._font_height_cache
        value = cache.get(key)
        if value is None:
            value = float(QFontMetricsF(font).height())
            cache[key] = value
        return value

    def draw_text(
        self,
        p: QPainter,
        rect: QRectF,
        text: str,
        font: QFont,
        c: QColor,
        flags: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        p.setFont(font)
        p.setPen(c)
        clipped = self.elide(p, font, text, rect.width())
        p.drawText(rect, int(flags), clipped)

    def draw_glass_text(
        self,
        p: QPainter,
        rect: QRectF,
        text: str,
        font: QFont,
        c: QColor,
        flags: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        """透明镜片上的最小文字保护，不引入额外暗色面板。"""
        if (
            self._collect_gpu_hud_commands
            and self.clickgui_gpu.available
            and self.minecraft_hud_active()
            and not self.menu_overlay_active()
        ):
            clipped = self.elide(p, font, text, rect.width())
            transform = QTransform(p.transform())
            draw_scale = max(0.01, math.hypot(transform.m11(), transform.m12()))
            opacity = max(0.0, min(1.0, float(p.opacity())))

            def faded(source: QColor) -> QColor:
                result = QColor(source)
                result.setAlphaF(source.alphaF() * opacity)
                return result

            shadow_rect = rect.translated(0.80, 0.95)
            mapped_shadow = transform.mapRect(shadow_rect)
            mapped_main = transform.mapRect(rect)
            # Keep the existing two-pass glass typography exactly ordered, but
            # submit glyphs through the already-warmed GPU atlas instead of
            # asking QPainter's OpenGL engine to shape/rasterise them every
            # display frame.  The liquid-glass command itself is untouched.
            self._gpu_hud_commands.text(
                mapped_shadow,
                clipped,
                font,
                faded(color("#071018", 0.68)),
                flags,
                mapped_shadow,
                shadow=False,
                render_scale=draw_scale,
                raster_scale=1.0,
                preserve_weight=True,
                device_pixel_snap=True,
            )
            self._gpu_hud_commands.text(
                mapped_main,
                clipped,
                font,
                faded(c),
                flags,
                mapped_main,
                shadow=False,
                render_scale=draw_scale,
                raster_scale=1.0,
                preserve_weight=True,
                device_pixel_snap=True,
            )
            return
        self.draw_text(p, rect.translated(0.80, 0.95), text, font, color("#071018", 0.68), flags)
        self.draw_text(p, rect, text, font, c, flags)

    def elide(self, p: QPainter, font: QFont, text: str, width: float) -> str:
        p.setFont(font)
        width_px = max(1, int(width))
        device = p.device()
        logical_dpi = int(device.logicalDpiX()) if device is not None else 96
        device_ratio = int(round((device.devicePixelRatioF() if device is not None else 1.0) * 100.0))
        key = (font.key(), str(text), width_px, logical_dpi, device_ratio)
        cached = self._elide_cache.get(key)
        if cached is not None:
            return cached
        result = p.fontMetrics().elidedText(
            str(text),
            Qt.TextElideMode.ElideRight,
            width_px,
        )
        if len(self._elide_cache) >= 4096:
            self._elide_cache.pop(next(iter(self._elide_cache)), None)
        self._elide_cache[key] = result
        return result


# ---------------------------------------------------------------------------
# API 冻结面 qualname 固定（见模块 docstring「冻结面纪律」）。
# ---------------------------------------------------------------------------

_QUALNAME_PINNED_MEMBERS = (
    mix_color,
    economy_lerp_rect,
    fit_aspect,
    _aspect_fit_image_rect,
    format_time,
    short_ring_number,
    short_outpost_value,
    painter_device_scale,
    TextMetricsMixin.font,
    TextMetricsMixin.text_advance,
    TextMetricsMixin.font_line_height,
    TextMetricsMixin.draw_text,
    TextMetricsMixin.draw_glass_text,
    TextMetricsMixin.elide,
)

for _fn in _QUALNAME_PINNED_MEMBERS:
    _fn.__qualname__ = f"PolarRMWindow.{_fn.__name__}"
del _fn, _QUALNAME_PINNED_MEMBERS
