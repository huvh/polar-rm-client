"""CS-style compact match strip rendered natively with PySide6/QPainter.

Original vector robot portraits and glyphs; no Valve images, Steam avatars,
web view, sockets, event handlers, focus, or actuator/control dependencies.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from typing import Mapping

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPolygonF

from ..top_match_bar import LifeState, MatchBarFrame, MatchBarLayout, Rect, RobotCard, compute_layout
from ..top_match_bar_motion import DEAD_CONTRAST, DEAD_OPACITY, kill_pop_scale


@dataclass(frozen=True)
class TopMatchBarOptions:
    enabled: bool = True
    scale: float = 0.72
    top: float = 5.0
    safe_left: float = 12.0
    safe_right: float = 12.0
    reduced_motion: bool = True  # Source motion requires an explicit preview opt-in.
    show_kills: bool = True
    show_scores: bool = True
    show_health: bool = False  # Controller opts in for the integrated RM vehicle HUD.
    font_family: str = "DejaVu Sans"


_ACCENTS = ("#eddb45", "#8ad8ee", "#ba81dd", "#54b494", "#e69548", "#bce074", "#df889f", "#7b94ce", "#d8bb90")
_BLUE = QColor("#B5D4EE")
_GOLD = QColor("#EAD18A")
_WHITE = QColor("#f9faf7")
_DEAD_WHITE = QColor("#dddddd")


def _qr(rect: Rect) -> QRectF:
    return QRectF(rect.x, rect.y, rect.width, rect.height)


def _font(family: str, size: float, *, bold: bool = False, condensed: bool = False) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, round(size)))
    font.setWeight(QFont.Bold if bold else QFont.Normal)
    if condensed:
        font.setStretch(82)
    return font


def _text(p: QPainter, rect: QRectF, text: str, font: QFont, color: QColor, *, shadow: bool = True) -> None:
    p.setFont(font)
    flags = Qt.AlignCenter | Qt.TextSingleLine
    if shadow:
        p.setPen(QColor(0, 0, 0, 210))
        p.drawText(rect.translated(0, 1), flags, text)
    p.setPen(color)
    p.drawText(rect, flags, text)


def _skull(p: QPainter, x: float, y: float, size: float, color: QColor) -> None:
    """Original 10x12 pictogram, not a game texture."""
    p.save()
    try:
        p.translate(x, y)
        p.scale(size / 10, size / 10)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(0.5, 0, 9, 8), 3, 3)
        p.drawRect(QRectF(2.5, 6, 5, 4))
        p.setBrush(QColor(12, 15, 18, 230))
        p.drawEllipse(QRectF(1.8, 3, 2.1, 2.2))
        p.drawEllipse(QRectF(6.1, 3, 2.1, 2.2))
        p.drawRect(QRectF(4.2, 6, 1.6, 1.4))
        p.setPen(QPen(QColor(12, 15, 18, 230), .6))
        p.drawLine(QPointF(4, 8), QPointF(4, 10))
        p.drawLine(QPointF(6, 8), QPointF(6, 10))
    finally:
        p.restore()


def _person(p: QPainter, x: float, y: float, color: QColor) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(x + 2, y, 4, 4))
    p.drawRoundedRect(QRectF(x + 1, y + 5, 6, 7), 1.5, 1.5)
    p.drawRect(QRectF(x + 2, y + 10, 2, 4))
    p.drawRect(QRectF(x + 5, y + 10, 2, 4))


class TopMatchBarRenderer:
    """Paint into the existing HUD painter. The owner controls visibility/repaint.

    Avatar images are supplied in memory by the caller; there is deliberately no
    file/URL loading here. Recreating the renderer/reset_motion() clears animation
    state on source, match or scene transitions. No QTimer runs in the background.
    """
    def __init__(self) -> None:
        self._portraits: OrderedDict[tuple[object, ...], tuple[QImage, QImage]] = OrderedDict()
        self._transitions: dict[int, LifeState] = {}
        self._kill_pops: dict[int, tuple[int, int, float]] = {}
        self._panel: QImage | None = None

    def reset_motion(self) -> None:
        self._transitions.clear()
        self._kill_pops.clear()

    def _portrait(self, card: RobotCard, supplied: QImage | None) -> tuple[QImage, QImage]:
        key = (card.robot_id, card.label, supplied.cacheKey() if supplied is not None else 0)
        if key in self._portraits:
            self._portraits.move_to_end(key)
            return self._portraits[key]
        if supplied is not None and not supplied.isNull():
            # Crop before resizing so extreme aspect ratios cannot allocate a
            # huge temporary image merely to produce a 140px square portrait.
            edge = min(supplied.width(), supplied.height())
            square = supplied.copy((supplied.width() - edge) // 2,
                                   (supplied.height() - edge) // 2, edge, edge)
            image = square.scaled(140, 140, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        else:
            image = self._robot_portrait(card)
        gray = image.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        effect = QPainter(gray)
        try:
            # Neutral gray mix implements 0.9 contrast; restore source alpha so
            # authorized transparent portraits don't acquire an opaque dead square.
            effect.fillRect(gray.rect(), QColor(128, 128, 128, round(255 * (1 - DEAD_CONTRAST))))
            effect.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            effect.drawImage(0, 0, image)
        finally:
            effect.end()
        pair = (image, gray)
        self._portraits[key] = pair
        while len(self._portraits) > 64:
            self._portraits.popitem(last=False)
        return pair

    @staticmethod
    def _robot_portrait(card: RobotCard) -> QImage:
        """Original role-coded robot head/bust, generated by vector primitives."""
        image = QImage(140, 140, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#172027"))
        p = QPainter(image)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(2, 2)
            accent = QColor(_ACCENTS[(card.robot_id % 100 - 1) % len(_ACCENTS)])
            gradient = QLinearGradient(0, 0, 70, 70)
            gradient.setColorAt(0, accent.darker(250))
            gradient.setColorAt(1, QColor("#10171e"))
            p.fillRect(QRectF(0, 0, 70, 70), gradient)
            # Slanted plate and concentric aperture distinguish roles without weapons.
            p.setPen(QPen(QColor(255, 255, 255, 17), .8))
            for k in range(-2, 6):
                p.drawLine(QPointF(k * 20, 0), QPointF(k * 20 - 35, 70))
            p.setPen(QPen(QColor("#090e13"), 2))
            p.setBrush(QColor("#73818b"))
            body = QPolygonF([QPointF(9, 70), QPointF(16, 51), QPointF(29, 45), QPointF(43, 45), QPointF(57, 53), QPointF(64, 70)])
            p.drawPolygon(body)
            p.setBrush(QColor("#27333e"))
            p.drawRoundedRect(QRectF(21, 16, 32, 34), 7, 7)
            p.setBrush(QColor("#a4b2b8"))
            p.drawPolygon(QPolygonF([QPointF(21, 21), QPointF(28, 12), QPointF(46, 13), QPointF(54, 23), QPointF(50, 31), QPointF(24, 30)]))
            p.setBrush(QColor("#131c22"))
            p.drawRoundedRect(QRectF(24, 24, 28, 13), 3, 3)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            role = card.robot_id % 100
            if role in (6, 9):
                p.drawEllipse(QRectF(30, 25, 10, 10))
                p.setPen(QPen(accent.lighter(140), 1.2))
                p.drawLine(QPointF(37, 12), QPointF(41, 4))
            elif role in (2, 7):
                p.drawRoundedRect(QRectF(27, 28, 7, 5), 1, 1)
                p.drawRoundedRect(QRectF(41, 28, 7, 5), 1, 1)
            else:
                p.drawRoundedRect(QRectF(27, 28, 22, 4), 1, 1)
            p.setPen(QPen(QColor("#c1cbd0"), 1))
            p.drawLine(QPointF(30, 41), QPointF(44, 41))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#17222b"))
            p.drawRoundedRect(QRectF(25, 53, 24, 19), 4, 4)
            _text(p, QRectF(25, 52, 24, 19), card.label[:3], _font("DejaVu Sans", 13, bold=True), accent, shadow=False)
            _text(p, QRectF(3, 2, 19, 10), str(card.robot_id), _font("DejaVu Sans", 8, bold=True), QColor(255, 255, 255, 170), shadow=False)
        finally:
            p.end()
        return image

    def _center_panel(self) -> QImage:
        if self._panel is None:
            image = QImage(108, 120, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            p = QPainter(image)
            try:
                gradient = QLinearGradient(0, 0, 0, 120)
                gradient.setColorAt(0, QColor(4, 6, 7, 218))
                gradient.setColorAt(.78, QColor(4, 6, 7, 204))
                gradient.setColorAt(1, QColor(4, 6, 7, 0))
                p.fillRect(QRectF(0, 0, 108, 120), gradient)
                p.setPen(QPen(QColor(255, 255, 255, 12), 1))
                for y in range(2, 105, 3):
                    for x in range(2, 108, 3):
                        p.drawPoint(x, y)
            finally:
                p.end()
            self._panel = image
        return self._panel

    def _kill_scale(self, card: RobotCard, icon_index: int, now: float, reduced: bool) -> float:
        count = max(0, card.kills or 0)
        previous = self._kill_pops.get(card.robot_id)
        if previous is None:
            # A first snapshot is not a newly observed kill event.
            self._kill_pops[card.robot_id] = (count, count, now - 1.0)
            return 1.0
        prior_count, initial_count, started = previous
        if count != prior_count:
            initial_count = min(prior_count, count)
            started = now
            self._kill_pops[card.robot_id] = (count, initial_count, started)
        if reduced or icon_index < initial_count:
            return 1.0
        return kill_pop_scale(now - started)

    def paint(self, p: QPainter, frame: MatchBarFrame, width: float, *, now: float,
              options: TopMatchBarOptions | None = None,
              avatars: Mapping[str, QImage] | None = None) -> MatchBarLayout | None:
        options = options or TopMatchBarOptions()
        if not options.enabled:
            self.reset_motion()
            return None
        if not math.isfinite(now):
            raise ValueError("now must be finite")
        layout = compute_layout(width, len(frame.left.cards), len(frame.right.cards),
                                scale=options.scale, top=options.top,
                                safe_left=options.safe_left, safe_right=options.safe_right)
        ids = {c.robot_id for team in (frame.left, frame.right) for c in team.cards}
        self._transitions = {key: value for key, value in self._transitions.items() if key in ids}
        self._kill_pops = {key: value for key, value in self._kill_pops.items() if key in ids}
        p.save()
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.setClipRect(_qr(layout.bounds), Qt.IntersectClip)
            # A low-opacity fade gives the original floating strip its contrast.
            shade = QLinearGradient(0, layout.bounds.y, 0, layout.bounds.bottom)
            shade.setColorAt(0, QColor(5, 8, 10, 70))
            shade.setColorAt(.65, QColor(5, 8, 10, 90))
            shade.setColorAt(1, QColor(5, 8, 10, 0))
            visible_left = layout.left_cards[0].x if layout.left_cards else layout.center.x
            visible_right = layout.right_cards[-1].right if layout.right_cards else layout.center.right
            p.fillRect(QRectF(visible_left, layout.bounds.y, visible_right - visible_left, layout.bounds.height), shade)
            for team, rects in ((frame.left, layout.left_cards), (frame.right, layout.right_cards)):
                for card, rect in zip(team.cards, rects):
                    p.save()
                    try:
                        p.translate(rect.x, rect.y)
                        p.scale(layout.scale, layout.scale)
                        self._paint_card(p, card, now, options, (avatars or {}).get(card.avatar_key))
                    finally:
                        p.restore()
            p.translate(layout.center.x, layout.center.y)
            p.scale(layout.scale, layout.scale)
            self._paint_center(p, frame, options, now)
        finally:
            p.restore()
        return layout

    def _paint_card(self, p: QPainter, card: RobotCard, now: float,
                    options: TopMatchBarOptions, supplied: QImage | None) -> None:
        portrait, gray = self._portrait(card, supplied)
        inherited_opacity = p.opacity()
        self._transitions[card.robot_id] = card.life
        blend = 1.0 if card.life == LifeState.DEAD else 0.0
        self._kill_scale(card, 0, now, True)
        r = QRectF(0, 0, 70, 70)
        if card.life == LifeState.UNKNOWN:
            p.fillRect(r, QColor(14, 24, 30, 210))
            p.setOpacity(inherited_opacity * .15)
            p.drawImage(r, gray)
            p.setOpacity(inherited_opacity)
            pen = QPen(QColor("#9ba8ae"), 1.4, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(1, 1, -1, -1))
            _text(p, QRectF(0, 4, 70, 53), "?", _font(options.font_family, 46, bold=True), _WHITE)
            _text(p, QRectF(0, 56, 70, 11), str(card.robot_id), _font(options.font_family, 8), QColor("#aebdc5"))
        else:
            p.setOpacity(inherited_opacity * (1 - blend))
            p.drawImage(r, portrait)
            p.setOpacity(inherited_opacity * blend * DEAD_OPACITY)
            p.drawImage(r, gray)
            p.setOpacity(inherited_opacity * (DEAD_OPACITY if blend else 1.0))
            border = QColor("#000000") if blend else QColor(_ACCENTS[(card.robot_id % 100 - 1) % len(_ACCENTS)])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(border, 2 if blend else 3))
            p.drawRect(r.adjusted(1.5, 1.5, -1.5, -1.5))
            p.setOpacity(inherited_opacity)
        # A real denominator is required for a proportional HP underline.
        # HP without max is still useful as a number, never a fabricated ratio.
        if options.show_health:
            ratio = card.health_ratio
            track = QRectF(0, 73, 70, 3)
            if card.health_applicable:
                p.fillRect(track, QColor(255, 255, 255, 36))
                if ratio is not None:
                    hp_color = QColor("#FF796B") if ratio <= .25 else QColor("#c7eab7")
                    p.fillRect(QRectF(0, 73, 70 * ratio, 3), hp_color)
            _text(p, QRectF(-3, 78, 76, 14), card.health_text,
                  _font(options.font_family, 10, bold=True), _WHITE)
            role_text = f"{card.label} {card.robot_id}"
            _text(p, QRectF(-3, 93, 76, 13), role_text,
                  _font(options.font_family, 9, bold=True), QColor("#bdc9ce"))
        if options.show_kills and card.kills is not None and card.kills > 0:
            count = min(card.kills, 5)
            start = 35 - (count * 12 - 2) / 2
            for i in range(count):
                pop = self._kill_scale(card, i, now, options.reduced_motion)
                p.save()
                try:
                    p.translate(start + i * 12 + 4.5, 112.5 if options.show_health else 85.5)
                    p.scale(pop, pop)
                    _skull(p, -4.5, -4.5, 9, _DEAD_WHITE if blend else _WHITE)
                finally:
                    p.restore()
            if card.kills > 5 and not options.show_health:
                _text(p, QRectF(0, 94, 70, 12), f"×{card.kills}", _font(options.font_family, 9, bold=True), _WHITE)

    def _paint_center(self, p: QPainter, frame: MatchBarFrame,
                      options: TopMatchBarOptions, now: float) -> None:
        p.drawImage(QRectF(0, 0, 108, 120), self._center_panel())
        timer_color = QColor(_WHITE)
        _text(p, QRectF(1, 0, 106, 36 if options.show_health else 43), frame.clock_text,
              _font(options.font_family, min(32, 160 / max(5, len(frame.clock_text))), bold=True, condensed=True), timer_color)
        if options.show_health and options.show_scores:
            _text(p, QRectF(0, 37, 108, 10), frame.score_label or "SCORE —",
                  _font(options.font_family, 8), QColor("#aab0b4"))
        for team, x in ((frame.left, 7), (frame.right, 61)):
            tint = _BLUE if team.alliance == "Blue" else _GOLD
            value = str(team.score) if team.score is not None and options.show_scores and frame.score_label else "—"
            size = 30 if len(value) <= 2 else max(13, 58 / len(value))
            _text(p, QRectF(x, 47, 40, 38), value,
                  _font(options.font_family, size, bold=True, condensed=True), tint)
            _person(p, x + 3, 98, tint)
            _text(p, QRectF(x + 12, 94, 32, 24), team.alive_text,
                  _font(options.font_family, 16 if len(team.alive_text) < 3 else 12, bold=True, condensed=True), tint)
            # RM team identities stay explicit even with the reference's blue/gold palette.
            _text(p, QRectF(x, 114, 40, 6), team.alliance.upper(), _font(options.font_family, 6, bold=True), tint, shadow=False)
        label = "PAUSED" if frame.paused else (frame.roster_label if options.show_health else (frame.score_label if options.show_scores else ""))
        if not label:
            label = "NO DATA" if frame.countdown is None else frame.roster_label
        _text(p, QRectF(0, 82, 108, 12), label[:20], _font(options.font_family, 8), QColor("#aab0b4"))
