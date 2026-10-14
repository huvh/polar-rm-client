"""Personal CS2 kill-card fan, fed by the existing CombatEvent dispatcher.

No new kill detector. Explicit preview events retain the application's existing
preview path; real feedback requires the same evidence as every GD656 preset.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen

from .cs2_assets import Cs2Assets
from .cs2_feedback import CARD_REFLOW_SECONDS, _css_ease_in_out, card_targets, kill_brightness, kill_spotlight


class Cs2KillFeedback:
    def __init__(self, assets: Cs2Assets) -> None:
        self.assets = assets
        self.cards = []
        self._from = []
        self._to = []
        self._reflow_at = -1e9
        self._background = self._make_background()

    def _make_background(self) -> QImage:
        mask = self.assets.image("kill_mask")
        if mask.isNull():
            return QImage()
        image = QImage(mask.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(4, 9, 13, 160))
        p = QPainter(image)
        try:
            dots = self.assets.image("dots")
            if not dots.isNull():
                p.setOpacity(.2)
                p.drawImage(QRectF(image.rect()), dots)
                p.setOpacity(1)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, mask)
        finally:
            p.end()
        return image

    def clear(self) -> None:
        self.cards.clear()
        self._from.clear()
        self._to.clear()

    def poses(self, now: float):
        t = _css_ease_in_out(max(0, min(1, (now - self._reflow_at) / CARD_REFLOW_SECONDS)))
        return [tuple(a + (b-a) * t for a, b in zip(start, end)) for start, end in zip(self._from, self._to)]

    def trigger(self, context, now: float) -> None:
        # Do not invent missing earlier kills when attaching mid-match.
        if context.combo <= 1:
            self.clear()
        current = self.poses(now)
        if len(self.cards) == 5:
            self.cards.pop(0)
            current.pop(0)
        self.cards.append(context)
        self._from = [*current, (0, 42, 0)]
        self._to = list(card_targets(len(self.cards)))
        self._reflow_at = now

    def draw(self, p: QPainter, point: QPointF, now: float, scale: float) -> None:
        if not self.cards:
            return
        age = max(0, now - self.cards[-1].timestamp)
        # RM's existing combo window is not a CS round. Keep feedback short
        # rather than claiming these cards are an official round kill count.
        opacity = max(0, min(1, (5.0 - age) / .3))
        if opacity <= 0:
            return
        p.save()
        try:
            p.translate(point)
            p.scale(scale, scale)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.setRenderHint(QPainter.Antialiasing)
            width = 48 * 152 / 126
            rect = QRectF(-width/2, -76, width, 152)
            for i, (context, pose) in enumerate(zip(self.cards, self.poses(now))):
                p.save()
                try:
                    p.translate(pose[0], pose[1])
                    p.rotate(pose[2])
                    p.setOpacity(opacity)
                    if not self._background.isNull():
                        p.drawImage(rect, self._background)
                    else:
                        p.setBrush(QColor(4, 9, 13, 150))
                        p.setPen(QPen(QColor("#dddddd"), 1))
                        p.drawRoundedRect(QRectF(-16, -65, 32, 45), 3, 3)
                    frame = self.assets.image(f"kill_{i+1}")
                    pip = self.assets.image({"HEADSHOT": "kill_headshot", "EXPLOSION": "kill_blast",
                                             "DESTROY_VEHICLE": "kill_blast"}.get(context.kill_type, "kill_default"))
                    for image in (frame, pip):
                        if not image.isNull():
                            p.drawImage(rect, image)
                    if frame.isNull() and pip.isNull():
                        # A public/released client has no Valve textures. Keep
                        # a legible original pictogram instead of an empty card.
                        p.setPen(Qt.NoPen)
                        p.setBrush(QColor("#f4f5f6"))
                        p.drawEllipse(QRectF(-6, -52, 12, 11))
                        p.drawRect(QRectF(-3, -43, 6, 6))
                        p.setBrush(QColor("#151b22"))
                        p.drawEllipse(QRectF(-4, -48, 3, 3))
                        p.drawEllipse(QRectF(1, -48, 3, 3))
                    brightness = kill_brightness(max(0, now-context.timestamp))
                    if brightness > 1:
                        p.setCompositionMode(QPainter.CompositionMode_Plus)
                        # Native additive HUD flash, no full-screen wash or
                        # camera kick. Bounded draws; no per-frame image work.
                        remaining = brightness-1
                        while remaining > 0:
                            p.setOpacity(opacity * min(1, remaining))
                            for image in (frame, pip):
                                if not image.isNull():
                                    p.drawImage(rect, image)
                            remaining -= 1
                        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                    spotlight = kill_spotlight(max(0, now-context.timestamp))
                    if spotlight > 0:
                        p.setOpacity(opacity)
                        beam = QLinearGradient(0, -115, 0, -15)
                        beam.setColorAt(0, QColor(255, 255, 255, 0))
                        beam.setColorAt(1, QColor(255, 255, 255, round(255*spotlight)))
                        p.fillRect(QRectF(-18, -115, 36, 100), beam)
                finally:
                    p.restore()
        finally:
            p.restore()
