"""Original login loading prefab: authored anchors, sprites, font and curve.

Only status content and actual work completion are adapted to POLAR. Assets
are prepared offline; no scanning, file loading, font installation or texture
creation occurs in the animation path. No liquid-glass material is modified.
"""
from __future__ import annotations

import bisect
import json
import math
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter


def rotation_degrees(keys, elapsed):
    """Unity's unweighted quaternion Hermite keys, mirrored to Qt's Y-down."""
    t = elapsed % keys[-1]["time"]
    i = min(len(keys)-2, max(0, bisect.bisect_right([k["time"] for k in keys], t)-1))
    a, b = keys[i], keys[i+1]
    dt = b["time"]-a["time"]
    u = (t-a["time"])/dt
    h00, h10, h01, h11 = 2*u**3-3*u*u+1, u**3-2*u*u+u, -2*u**3+3*u*u, u**3-u*u
    def value(axis):
        return (h00*a["value"][axis] + h10*dt*a["outSlope"][axis] +
                h01*b["value"][axis] + h11*dt*b["inSlope"][axis])
    return -math.degrees(2*math.atan2(value("z"), value("w")))


def child_rect(node, parent, scale):
    t = node["transform"]
    amin, amax, pivot = t["m_AnchorMin"], t["m_AnchorMax"], t["m_Pivot"]
    pos, delta = t["m_AnchoredPosition"], t["m_SizeDelta"]
    width = (amax["x"]-amin["x"])*parent.width()+delta["x"]*scale
    height = (amax["y"]-amin["y"])*parent.height()+delta["y"]*scale
    x = parent.x()+(amin["x"]+(amax["x"]-amin["x"])*pivot["x"])*parent.width()+pos["x"]*scale-pivot["x"]*width
    y = parent.bottom()-(amin["y"]+(amax["y"]-amin["y"])*pivot["y"])*parent.height()-pos["y"]*scale-(1-pivot["y"])*height
    return QRectF(x, y, width, height)


class EndfieldBootPresentation:
    def __init__(self, root: Path):
        self.error = ""
        self.layout = None
        self.images = {}
        self.family = "Microsoft YaHei UI"
        self.started_at = None
        try:
            self.layout = json.loads((root / "layout.json").read_text(encoding="utf-8"))
            font = QFontDatabase.addApplicationFont(str(root / "defaultfont_cn.ttf"))
            families = QFontDatabase.applicationFontFamilies(font)
            if families:
                self.family = families[0]
            for key, name in self.layout["sprites"].items():
                image = QImage(str(root / name))
                if image.isNull():
                    raise ValueError("Original loading sprite missing: " + name)
                self.images[key] = image
        except (OSError, ValueError, KeyError) as error:
            self.error = str(error)
            self.layout = None
            self.images.clear()

    def draw(self, painter, width, height, boot, now, *, chinese=True, error=""):
        if not self.layout or not boot.visible(now):
            return
        if self.started_at is None:
            self.started_at = now
        scale = height / self.layout["canvas"][1]
        # ResourcePanel is bottom-anchored +540, then Loading -482. Keep
        # these authored anchors rather than centering a guessed progress card.
        parent = QRectF(0, height-540*scale, width, 0)
        root = self.layout["root"]
        rect = child_rect(root, parent, scale)
        phases = ("配置", "图形资源", "字形与纹理") if chinese else ("Configuration", "Graphics", "Atlases")
        phase = next((phases[i] for i, key in enumerate(boot.PHASES) if key not in boot.completed), "READY")
        text = ("资源初始化失败 · " + error) if error else f"{phase}    {boot.progress:.0%}"
        painter.save()
        painter.setClipRect(QRectF(0, 0, width, height))
        self._draw_node(painter, root, rect, scale, boot.progress, now-self.started_at, text)
        painter.restore()
        return rect.intersected(QRectF(0, 0, width, height))

    def _draw_node(self, painter, node, rect, scale, progress, now, text):
        if node["name"] == "Progress":
            painter.fillRect(QRectF(rect.x(), rect.y(), rect.width()*progress, rect.height()), QColor("white"))
            return
        if node["name"] == "LayoutText":
            font = QFont(self.family)
            font.setPixelSize(max(12, round(26*scale)))
            painter.setFont(font)
            painter.setPen(QColor("white"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            return
        image = node.get("image")
        if image:
            rgba = image["m_Color"]
            color = QColor.fromRgbF(*[rgba[k] for k in "rgba"])
            source = self.images.get(str(image["m_Sprite"]["m_PathID"]))
            if source is None:
                painter.fillRect(rect, color)
            else:
                painter.save()
                painter.setOpacity(color.alphaF())
                if node["name"] == "loading_icon":
                    painter.translate(rect.center())
                    painter.rotate(rotation_degrees(self.layout["rotation"], now))
                    rect = QRectF(-rect.width()/2, -rect.height()/2, rect.width(), rect.height())
                # Source bg/deco are white masks tinted 0.2 in the prefab;
                # composition multiply is a small retained sprite operation.
                painter.drawImage(rect, source)
                if color.redF() < .99:
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                    painter.fillRect(rect, color)
                painter.restore()
        for child in node["children"]:
            self._draw_node(painter, child, child_rect(child, rect, scale), scale, progress, now, text)
