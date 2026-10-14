"""CS-style compact match strip rendered natively with PySide6/QPainter.

Original robot portraits, optionally dressed with a preloaded personal CS2 UI
pack. No Steam access, web view, input or actuator/control dependencies.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from functools import lru_cache
import math
from typing import Mapping

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPolygonF

from ..top_match_bar import LifeState, MatchBarFrame, MatchBarLayout, Rect, RobotCard, compute_layout
from ..top_match_bar_motion import DEAD_CONTRAST, DEAD_OPACITY, kill_pop_scale
from .match_strip_locale import match_alliance_text, match_role_text, match_strip_text
from .fonts import cjk_ui_font, draw_ui_text, elide_ui_text, has_cjk, ui_text_advance
from .cs2_assets import Cs2Assets


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
    show_health: bool = False  # Thin HP underline; no per-card telemetry paragraphs.
    font_family: str = "DejaVu Sans"
    chinese: bool = False  # Standalone callers retain the original English view.
    custom_roster_label: bool = False
    local_assets: bool = True


_ACCENTS = ("#eddb45", "#8ad8ee", "#ba81dd", "#54b494", "#e69548", "#bce074", "#df889f", "#7b94ce", "#d8bb90")
_BLUE = QColor("#B5D4EE")
_GOLD = QColor("#EAD18A")
_WHITE = QColor("#f9faf7")
_DEAD_WHITE = QColor("#dddddd")


def _qr(rect: Rect) -> QRectF:
    return QRectF(rect.x, rect.y, rect.width, rect.height)


@lru_cache(maxsize=128)
def _strip_layout(width: float, left_count: int, right_count: int, scale: float,
                  top: float, safe_left: float, safe_right: float) -> MatchBarLayout:
    # Only immutable geometry is cached. Telemetry and motion are painted live.
    return compute_layout(width, left_count, right_count, scale=scale, top=top,
                          safe_left=safe_left, safe_right=safe_right)


@lru_cache(maxsize=256)
def _cached_font(family: str, size: float, bold: bool, condensed: bool) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, round(size)))
    font.setWeight(QFont.Bold if bold else QFont.Normal)
    if condensed:
        if family == "Stratum2":
            font.setStyleName("Bold Condensed" if bold else "Regular")
        else:
            font.setStretch(82)
    return font


def _font(family: str, size: float, *, bold: bool = False, condensed: bool = False) -> QFont:
    return QFont(_cached_font(family, size, bold, condensed))


@lru_cache(maxsize=1024)
def _label_font(family: str, size: float, text: str) -> QFont:
    font = _font(family, size)
    return cjk_ui_font(font) if has_cjk(text) else font


def _text(p: QPainter, rect: QRectF, text: str, font: QFont, color: QColor, *, shadow: bool = True) -> None:
    p.setFont(font)
    flags = Qt.AlignCenter | Qt.TextSingleLine
    if has_cjk(text):
        text = elide_ui_text(font, text, rect.width(), p.device())
        if shadow:
            p.setPen(QColor(0, 0, 0, 210))
            draw_ui_text(p, rect.translated(0, 1), text, font, flags, ink_center=True)
        p.setPen(color)
        draw_ui_text(p, rect, text, font, flags, ink_center=True)
        return
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
    def __init__(self, assets: Cs2Assets | None = None) -> None:
        self.resources = assets or Cs2Assets()
        self._native = False
        self._portraits: OrderedDict[tuple[object, ...], tuple[QImage, QImage]] = OrderedDict()
        self._avatar_layers: OrderedDict[tuple[object, ...], QImage] = OrderedDict()
        self._text_layers: OrderedDict[tuple[object, ...], QImage] = OrderedDict()
        self._transitions: dict[int, LifeState] = {}
        self._kill_pops: dict[int, tuple[int, int, float]] = {}
        self._panels: dict[bool, QImage] = {}

    def _skull(self, p: QPainter, x: float, y: float, size: float, color: QColor, *, dead=False) -> None:
        asset = self.resources.tinted("elimination" if dead else "kill_flag", color) if self._native else QImage()
        if not asset.isNull():
            p.drawImage(QRectF(x, y, size, size), asset)
        else:
            _skull(p, x, y, size, color)

    def reset_motion(self) -> None:
        self._transitions.clear()
        self._kill_pops.clear()

    def _paint_cached_text(self, p: QPainter, rect: QRectF, text: str, font: QFont,
                           color: QColor, *, shadow: bool = True, fit: bool = False) -> None:
        """Cache glyph pixels, not model fields; every call uses the live value.

        Two logical pixels of padding preserve shadow/ink at small CJK sizes.
        Effective painter density includes both HUD transforms and device DPR.
        """
        transform = p.deviceTransform()
        density = max(1.0, math.hypot(transform.m11(), transform.m12()),
                      math.hypot(transform.m21(), transform.m22()))
        width, height = rect.width() + 4, rect.height() + 4
        pixels = (math.ceil(width * density), math.ceil(height * density))
        dpi = (p.device().logicalDpiX(), p.device().logicalDpiY())
        key = (text, font.toString(), color.rgba(), shadow, fit, width, height, pixels, dpi)
        layer = self._text_layers.get(key)
        if layer is None:
            layer = QImage(*pixels, QImage.Format_ARGB32_Premultiplied)
            layer.fill(Qt.transparent)
            layer.setDotsPerMeterX(round(dpi[0] / .0254))
            layer.setDotsPerMeterY(round(dpi[1] / .0254))
            ink = QPainter(layer)
            try:
                ink.setRenderHint(QPainter.Antialiasing)
                ink.scale(pixels[0] / width, pixels[1] / height)
                if fit:
                    # Numeric model values must stay complete, including the
                    # unknown clock's wide em dashes and a six-digit RM score.
                    advance = ui_text_advance(font, text, layer)
                    if advance > rect.width():
                        font = QFont(font)
                        font.setPixelSize(max(6, math.floor(font.pixelSize() * rect.width() / advance)))
                    display = text
                else:
                    display = elide_ui_text(font, text, rect.width(), layer)
                _text(ink, QRectF(2, 2, rect.width(), rect.height()), display,
                      font, color, shadow=shadow)
            finally:
                ink.end()
            self._text_layers[key] = layer
            while len(self._text_layers) > 128:
                self._text_layers.popitem(last=False)
        else:
            self._text_layers.move_to_end(key)
        p.drawImage(rect.adjusted(-2, -2, 2, 2), layer)

    def _portrait(self, card: RobotCard, supplied: QImage | None, *, chinese: bool = False) -> tuple[QImage, QImage]:
        key = (card.robot_id, card.label, supplied.cacheKey() if supplied is not None else 0, chinese)
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
            image = self._robot_portrait(card, chinese=chinese)
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
    def _robot_portrait(card: RobotCard, *, chinese: bool = False) -> QImage:
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
            role_text = match_role_text(card, chinese)[:3]
            _text(p, QRectF(24, 0, 43, 14), role_text,
                  _label_font("DejaVu Sans", 10, role_text), accent, shadow=False)
        finally:
            p.end()
        return image

    def _center_panel(self) -> QImage:
        if self._native not in self._panels:
            image = QImage(108, 120, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            p = QPainter(image)
            try:
                gradient = QLinearGradient(0, 0, 0, 120)
                gradient.setColorAt(0, QColor(4, 6, 7, 170))
                gradient.setColorAt(.62, QColor(4, 6, 7, 125))
                gradient.setColorAt(1, QColor(4, 6, 7, 0))
                p.fillRect(QRectF(0, 0, 108, 120), gradient)
                if self._native:
                    dots = self.resources.image("dots")
                    if not dots.isNull():
                        p.setOpacity(.05)
                        p.drawImage(QRectF(0, 0, 108, 120), dots)
            finally:
                p.end()
            self._panels[self._native] = image
        return self._panels[self._native]

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
        self._native = options.local_assets and self.resources.available
        if self._native and "font_regular" in self.resources.families:
            options = replace(options, font_family=self.resources.families["font_regular"])
        if not options.enabled:
            self.reset_motion()
            return None
        if not math.isfinite(now):
            raise ValueError("now must be finite")
        layout = _strip_layout(width, len(frame.left.cards), len(frame.right.cards),
                               options.scale, options.top, options.safe_left, options.safe_right)
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
            shade.setColorAt(0, QColor(5, 8, 10, 55))
            shade.setColorAt(.65, QColor(5, 8, 10, 65))
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

    def _avatar_layer(self, card: RobotCard, options: TopMatchBarOptions,
                      supplied: QImage | None, density: float) -> QImage:
        """Reusable square only; never bake HP, kills or a clock into this layer.

        Rasterize at the effective painter density, including HUD scale and DPR,
        so caching cannot turn high-DPI glyphs/borders into a low-res thumbnail.
        Generic robot art denotes a role, not an invented member photograph.
        """
        portrait, gray = self._portrait(card, supplied, chinese=options.chinese)
        pixels = max(70, math.ceil(70 * density))
        key = (self._native, portrait.cacheKey(), card.robot_id, card.life, options.font_family,
               options.chinese, pixels)
        if key in self._avatar_layers:
            self._avatar_layers.move_to_end(key)
            return self._avatar_layers[key]
        image = QImage(pixels, pixels, QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(pixels / 70)
        image.fill(Qt.transparent)
        p = QPainter(image)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            r = QRectF(0, 0, 70, 70)
            if card.life == LifeState.UNKNOWN:
                # Unknown is not desaturated/dead. An authorized portrait stays
                # in colour; otherwise use a clean, neutral question-mark well.
                if supplied is not None and not supplied.isNull():
                    p.drawImage(r, portrait)
                    p.fillRect(r, QColor(5, 8, 10, 65))
                else:
                    p.fillRect(r, QColor("#172126"))
                border = QColor("#70838e")
                _text(p, QRectF(0, 3, 70, 51), "?",
                      _font(options.font_family, 40, bold=True), _WHITE)
            elif card.life == LifeState.DEAD:
                p.setOpacity(DEAD_OPACITY)
                p.drawImage(r, gray)
                border = QColor(120, 120, 120, 115)
            else:
                p.drawImage(r, portrait)
                border = QColor(_ACCENTS[(card.robot_id % 100 - 1) % len(_ACCENTS)])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(border, 2))
            p.drawRect(r.adjusted(1, 1, -1, -1))
            p.setOpacity(1)
            # Identity fits inside the avatar, not another card-label row.
            p.fillRect(QRectF(2, 54, 27, 14), QColor(4, 6, 7, 175))
            _text(p, QRectF(2, 54, 27, 14), str(card.robot_id),
                  _font(options.font_family, 10, bold=True), QColor("#d4dee3"))
            if card.life == LifeState.DEAD:
                # Death is an explicit marker even with Show Kills disabled.
                p.fillRect(QRectF(45, 3, 22, 26), QColor(4, 6, 7, 170))
                self._skull(p, 48, 5, 16, _DEAD_WHITE, dead=True)
        finally:
            p.end()
        self._avatar_layers[key] = image
        while len(self._avatar_layers) > 64:
            self._avatar_layers.popitem(last=False)
        return image

    def _paint_card(self, p: QPainter, card: RobotCard, now: float,
                    options: TopMatchBarOptions, supplied: QImage | None) -> None:
        self._transitions[card.robot_id] = card.life
        dead = card.life == LifeState.DEAD
        self._kill_scale(card, 0, now, True)
        transform = p.deviceTransform()
        density = max(math.hypot(transform.m11(), transform.m12()),
                      math.hypot(transform.m21(), transform.m22()))
        p.drawImage(QRectF(0, 0, 70, 70), self._avatar_layer(card, options, supplied, density))
        # A real denominator is required for a proportional HP underline.
        # HP without max is still useful as a number, never a fabricated ratio.
        if options.show_health:
            ratio = card.health_ratio
            track = QRectF(0, 73, 70, 3)
            if card.life != LifeState.UNKNOWN and ratio is not None and 0 <= ratio <= 1:
                p.fillRect(track, QColor(255, 255, 255, 36))
                hp_color = QColor("#FF796B") if ratio <= .25 else QColor("#c7eab7")
                p.fillRect(QRectF(0, 73, 70 * ratio, 3), hp_color)
            elif card.health_applicable and card.health is not None and card.life != LifeState.UNKNOWN:
                # A number without a denominator is useful, but not a ratio.
                # This small in-avatar badge cannot masquerade as a full bar.
                p.fillRect(QRectF(31, 54, 37, 14), QColor(4, 6, 7, 175))
                value = str(card.health)
                self._paint_cached_text(p, QRectF(31, 54, 37, 14), value,
                                        _font(options.font_family, min(10, 54 / max(1, len(value))), bold=True), _WHITE)
        if options.show_kills and card.kills is not None and card.kills > 0:
            count = min(card.kills, 5)
            start = 35 - (count * 12 - 2) / 2
            for i in range(count):
                pop = self._kill_scale(card, i, now, options.reduced_motion)
                p.save()
                try:
                    p.translate(start + i * 12 + 4.5, 85.5)
                    p.scale(pop, pop)
                    self._skull(p, -4.5, -4.5, 9, _DEAD_WHITE if dead else _WHITE)
                finally:
                    p.restore()
            if card.kills > 5:
                self._paint_cached_text(p, QRectF(0, 94, 70, 12), f"×{card.kills}",
                                        _font(options.font_family, 9, bold=True), _WHITE)

    def _paint_center(self, p: QPainter, frame: MatchBarFrame,
                      options: TopMatchBarOptions, now: float) -> None:
        p.drawImage(QRectF(0, 0, 108, 120), self._center_panel())
        timer_color = QColor(_WHITE)
        timer_font = _font(options.font_family, min(36, 180 / max(5, len(frame.clock_text))), bold=True, condensed=True)
        if self._native and "font_timer" in self.resources.families:
            timer_font.setStyleName("Bold TF")
        self._paint_cached_text(p, QRectF(1, 0, 106, 39), frame.clock_text,
                                timer_font, timer_color, fit=True)
        # Only these exact metric/roster labels belong to the built-in feed.
        # Other caller-owned labels may themselves contain UI vocabulary.
        score_label = (match_strip_text(frame.score_label, options.chinese)
                       if frame.score_label == "RM SCORE" else frame.score_label)
        if options.show_health and options.show_scores:
            metric = score_label or match_strip_text("SCORE —", options.chinese)
            self._paint_cached_text(p, QRectF(0, 75, 108, 14), metric,
                                    _label_font(options.font_family, 12 if options.chinese else 9, metric), QColor("#aab0b4"))
        for team, x in ((frame.left, 6), (frame.right, 60)):
            tint = _BLUE if team.alliance == "Blue" else _GOLD
            value = str(team.score) if team.score is not None and options.show_scores and frame.score_label else "—"
            size = 30 if len(value) <= 2 else max(9, 58 / len(value))
            score_font = _font(options.font_family, size, bold=True, condensed=True)
            if self._native and "font_timer" in self.resources.families:
                score_font.setStyleName("Bold TF")
            self._paint_cached_text(p, QRectF(x, 39, 40, 36), value, score_font, tint, fit=True)
            person = self.resources.tinted("person", tint) if self._native else QImage()
            if person.isNull():
                _person(p, x + 15, 103, tint)
            else:
                p.drawImage(QRectF(x + 15, 103, 8, 14), person)
            self._paint_cached_text(p, QRectF(x + 23, 99, 25, 21), team.alive_text,
                                    _font(options.font_family, 14 if len(team.alive_text) < 3 else 10, bold=True, condensed=True), tint, fit=True)
            # RM team identities stay explicit even with the reference's blue/gold palette.
            alliance = match_alliance_text(team.alliance, options.chinese)
            if self._native:
                # Reserve separate space for the exact person SVG and count.
                # A one-character identity keeps RM's red/blue meaning without
                # the old two-character label colliding with the CS2 pictogram.
                alliance = alliance[:1]
            self._paint_cached_text(p, QRectF(x - 5, 101, 22, 17), alliance,
                                    _label_font(options.font_family, 10 if options.chinese else 7, alliance), tint, shadow=False, fit=True)
        roster_label = (match_strip_text(frame.roster_label, options.chinese)
                        if not options.custom_roster_label and frame.roster_label == "GROUND ALIVE"
                        else frame.roster_label)
        label = (match_strip_text("PAUSED", options.chinese) if frame.paused else
                 (roster_label if options.show_health else
                  (score_label if options.show_scores else "")))
        if not label:
            label = match_strip_text("NO DATA", options.chinese) if frame.countdown is None else roster_label
        self._paint_cached_text(p, QRectF(0, 89, 108, 14), label,
                                _label_font(options.font_family, 11 if options.chinese else 9, label), QColor("#aab0b4"))
