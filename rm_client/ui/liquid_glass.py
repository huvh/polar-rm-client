from __future__ import annotations

from dataclasses import dataclass, field
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QRadialGradient


@dataclass
class LiquidGlassSnapshot:
    image: QImage = field(default_factory=QImage)
    soft: QImage = field(default_factory=QImage)
    lens: QImage = field(default_factory=QImage)
    luminance: QImage = field(default_factory=QImage)
    draw_rect: QRectF = field(default_factory=QRectF)
    key: int = 0


class LiquidGlassRenderer:
    """基于 liquid-glass-react 参数语义的稳定镜片渲染器。"""

    def __init__(self) -> None:
        self.snapshots: dict[str, LiquidGlassSnapshot] = {}
        self.light_state: dict[tuple[str, int, int, int, int], float] = {}
        self.light_time: dict[tuple[str, int, int, int, int], float] = {}

    def update(
        self,
        source: str,
        image: QImage,
        draw_rect: QRectF,
        *,
        soft: QImage | None = None,
        lens: QImage | None = None,
    ) -> None:
        if image.isNull() or draw_rect.isEmpty():
            return
        key = hash((
            int(image.cacheKey()),
            int(soft.cacheKey()) if soft and not soft.isNull() else 0,
            int(lens.cacheKey()) if lens and not lens.isNull() else 0,
        ))
        previous = self.snapshots.get(source)
        if previous is not None and previous.key == key and previous.draw_rect == draw_rect:
            return
        base_w = min(420, max(180, image.width() // 3))
        soft_image = soft if soft is not None and not soft.isNull() else image.scaledToWidth(
            base_w, Qt.TransformationMode.SmoothTransformation
        )
        lens_image = lens if lens is not None and not lens.isNull() else soft_image.scaledToWidth(
            max(112, soft_image.width() // 2), Qt.TransformationMode.SmoothTransformation
        )
        luminance = image.scaled(48, 27, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        self.snapshots[source] = LiquidGlassSnapshot(
            QImage(), soft_image.copy(), lens_image.copy(), luminance.copy(), QRectF(draw_rect), key
        )

    def draw(
        self,
        painter: QPainter,
        rect: QRectF,
        radius: float,
        *,
        source: str,
        mode: str = "standard",
        surface: str = "main",
        hover: float = 0.0,
        press: float = 0.0,
        pointer: QPointF | None = None,
        lite: bool = False,
    ) -> None:
        snapshot = self.snapshots.get(source)
        hover = max(0.0, min(1.0, hover))
        press = max(0.0, min(1.0, press))
        profile = {
            "standard": (0.055, 1.8, 0.18, 0.54),
            "polar": (0.080, 2.8, 0.25, 0.58),
            "prominent": (0.105, 3.6, 0.32, 0.60),
        }.get(mode, (0.055, 1.8, 0.18, 0.54))
        edge_ratio, displacement, aberration, core_alpha = profile
        if surface == "sub":
            core_alpha *= 0.70
            displacement *= 0.52
            aberration *= 0.42

        outer = QPainterPath()
        outer.addRoundedRect(rect, radius, radius)
        edge = max(2.0, min(min(rect.width(), rect.height()) * edge_ratio, 11.0))
        inner_rect = rect.adjusted(edge, edge, -edge, -edge)
        inner = QPainterPath()
        inner.addRoundedRect(inner_rect, max(1.0, radius - edge), max(1.0, radius - edge))
        edge_path = outer.subtracted(inner)
        light = self._light_amount(source, snapshot, rect)
        pointer = pointer or rect.center()
        nx = max(-1.0, min(1.0, (pointer.x() - rect.center().x()) / max(1.0, rect.width() * 0.5)))
        ny = max(-1.0, min(1.0, (pointer.y() - rect.center().y()) / max(1.0, rect.height() * 0.5)))

        # 玻璃只允许极轻的位移，文字和布局始终保持稳定。
        visual_rect = QRectF(rect)
        if hover > 0.0:
            visual_rect.adjust(-0.5 * hover, -0.5 * hover, 0.5 * hover, 0.5 * hover)
            visual_rect.translate(nx * 0.8 * hover, ny * 0.6 * hover)
        if press > 0.0:
            visual_rect.setWidth(visual_rect.width() * (1.0 - 0.010 * press))
            visual_rect.setHeight(visual_rect.height() * (1.0 - 0.010 * press))
            visual_rect.moveCenter(rect.center())

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if snapshot is not None and not snapshot.soft.isNull():
            source_rect = self._source_rect(snapshot, visual_rect, snapshot.soft)
            painter.setClipPath(outer)
            painter.setOpacity(painter.opacity() * core_alpha)
            painter.drawImage(visual_rect, snapshot.soft, source_rect)
            if not lite and not snapshot.lens.isNull() and not source_rect.isEmpty():
                lens_source = self._source_rect(snapshot, visual_rect, snapshot.lens)
                warped = lens_source.adjusted(-displacement, -displacement, displacement, displacement)
                painter.setClipPath(edge_path)
                painter.setOpacity(painter.opacity() * (0.30 + 0.08 * hover + 0.08 * light))
                painter.drawImage(visual_rect, snapshot.lens, warped)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                painter.setBrush(QColor(228, 242, 255, int(8 + aberration * 22 + light * 12)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(edge_path)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        else:
            painter.setClipPath(outer)
            painter.fillRect(rect, QColor(223, 238, 250, 26 if surface == "main" else 15))
        painter.restore()

        # 亮背景仅获得局部雾化，避免把整张卡片洗成白色。
        if light > 0.01:
            fog_size = max(14.0, min(rect.width(), rect.height()) * 0.28)
            fog_center = self._edge_glint_center(rect, nx, ny, edge)
            fog = QRadialGradient(fog_center, fog_size)
            fog.setColorAt(0.0, QColor(246, 252, 255, int(8 + light * 20)))
            fog.setColorAt(1.0, QColor(246, 252, 255, 0))
            painter.save()
            painter.setClipPath(outer)
            painter.setBrush(fog)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(fog_center.x() - fog_size, fog_center.y() - fog_size, fog_size * 2.0, fog_size * 2.0))
            painter.restore()

        # 高光只停留在鼠标朝向的短边缘带，禁止整块面板出现扫过的白条。
        if not lite and surface != "sub" and (hover > 0.015 or light > 0.08):
            glint_center = self._edge_glint_center(rect, nx, ny, edge)
            glint_radius = max(10.0, min(26.0, edge * (3.2 + hover * 1.6)))
            glint = QRadialGradient(glint_center, glint_radius)
            glint.setColorAt(0.0, QColor(255, 255, 255, int(20 + light * 24 + hover * 22)))
            glint.setColorAt(0.42, QColor(231, 246, 255, int(8 + light * 12 + hover * 10)))
            glint.setColorAt(1.0, QColor(231, 246, 255, 0))
            painter.save()
            painter.setClipPath(edge_path)
            painter.setBrush(glint)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(glint_center.x() - glint_radius, glint_center.y() - glint_radius, glint_radius * 2.0, glint_radius * 2.0))
            painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(242, 249, 255, int(54 + light * 38 + hover * 20)), 0.8))
        painter.drawRoundedRect(rect, radius, radius)
        if surface == "main" and not lite:
            painter.setPen(QPen(QColor(15, 27, 40, int(18 + light * 14)), 0.6))
            painter.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), max(1.0, radius - 1.0), max(1.0, radius - 1.0))

    @staticmethod
    def _edge_glint_center(rect: QRectF, nx: float, ny: float, edge: float) -> QPointF:
        """把反光锚定在最接近鼠标方向的边缘，而不是横穿整个镜片。"""
        if abs(nx) >= abs(ny):
            x = rect.right() - edge * 0.45 if nx >= 0.0 else rect.left() + edge * 0.45
            y = rect.center().y() + ny * rect.height() * 0.27
        else:
            x = rect.center().x() + nx * rect.width() * 0.27
            y = rect.bottom() - edge * 0.45 if ny >= 0.0 else rect.top() + edge * 0.45
        return QPointF(x, y)

    def _source_rect(self, snapshot: LiquidGlassSnapshot, rect: QRectF, image: QImage) -> QRectF:
        draw = snapshot.draw_rect
        return QRectF(
            (rect.left() - draw.left()) / max(1.0, draw.width()) * image.width(),
            (rect.top() - draw.top()) / max(1.0, draw.height()) * image.height(),
            rect.width() / max(1.0, draw.width()) * image.width(),
            rect.height() / max(1.0, draw.height()) * image.height(),
        ).intersected(QRectF(0, 0, image.width(), image.height()))

    def _light_amount(self, source: str, snapshot: LiquidGlassSnapshot | None, rect: QRectF) -> float:
        if snapshot is None or snapshot.luminance.isNull() or snapshot.draw_rect.isEmpty():
            return 0.0
        draw = snapshot.draw_rect
        px = int(max(0, min(snapshot.luminance.width() - 1, (rect.center().x() - draw.left()) / max(1.0, draw.width()) * snapshot.luminance.width())))
        py = int(max(0, min(snapshot.luminance.height() - 1, (rect.center().y() - draw.top()) / max(1.0, draw.height()) * snapshot.luminance.height())))
        total = 0.0
        count = 0
        for y in range(max(0, py - 1), min(snapshot.luminance.height(), py + 2)):
            for x in range(max(0, px - 1), min(snapshot.luminance.width(), px + 2)):
                c = snapshot.luminance.pixelColor(x, y)
                total += (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) / 255.0
                count += 1
        luminance = total / max(1, count)
        key = (source, int(rect.x() // 24), int(rect.y() // 24), int(rect.width() // 24), int(rect.height() // 24))
        previous = self.light_state.get(key, 0.0)
        threshold = 0.63 if previous < 0.5 else 0.56
        target = max(0.0, min(1.0, (luminance - threshold) / max(0.01, 1.0 - threshold)))
        now = time.perf_counter()
        dt = min(0.15, max(0.0, now - self.light_time.get(key, now)))
        amount = previous + (target - previous) * (1.0 - math.exp(-dt / 0.15))
        self.light_state[key] = amount
        self.light_time[key] = now
        return amount
