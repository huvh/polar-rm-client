"""Native transcription of CS2's classic/no-timeline Tab scoreboard.

Geometry and materials come from the copied 2026-10-25 Panorama resources,
not a replacement table theme. Only the data labels/avatars are RM adapters.
No Steam/process access at runtime. The existing map owns reveal/reversal.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath

from ..top_match_bar import LifeState, MatchBarFrame
from ..top_match_bar_motion import css_ease_out
from .cs2_assets import local_cs2_assets
from .fonts import cjk_ui_font, draw_ui_text, elide_ui_text, has_cjk
from .jello_locale import chinese_enabled
from .match_strip_locale import match_role_text
from .top_match_bar import TopMatchBarRenderer


# Original selectors are recorded in assets/cs2_scoreboard_source/README.md.
SURFACE_ALPHA = .88
DOTS_ALPHA = .015
ROW_HEIGHT = 24
ROW_GAP = 2
CELL_TRANSITION_SECONDS = .25
BLUE = QColor('#B5D4EE')
GOLD = QColor('#EAD18A')
PAD, RAIL, RAIL_GAP, TABLE, INNER = 20., 80., 10., 830., 770.
REFERENCE_WIDTH = PAD * 2 + RAIL + RAIL_GAP + TABLE
META_HEIGHT, LABEL_HEIGHT, TEAM_GAP, FOOTER_HEIGHT = 75., 26., 24., 48.
TABLE_X = PAD + RAIL + RAIL_GAP

# Exact competitive set-0 order/widths. NAME consumes remaining flow width.
# RM HEALTH replaces HSP; no invented packet ping, assists, or damage.
_FIXED_COLUMNS = (
    ('status', 24.), ('ping', 37.), ('flair', 32.4), ('avatar', 24.),
    ('name', 0.), ('money', 66.), ('kills', 50.), ('deaths', 50.),
    ('assists', 50.), ('health', 64.), ('damage', 50.),
)
COLUMNS = tuple((key, INNER - sum(w for _, w in _FIXED_COLUMNS) if key == 'name' else w)
                for key, w in _FIXED_COLUMNS)


def ordered_teams(frame):
    """CS CT/blue first, T/gold second; not dependent on local alliance."""
    return tuple(sorted((frame.left, frame.right), key=lambda t: t.alliance != 'Blue'))


def team_cards(team):
    return (*team.cards, *team.systems)


@dataclass(frozen=True)
class ScoreboardLayout:
    bounds: QRectF
    map_bounds: QRectF
    scale: float
    team_heights: tuple[float, float]

    @property
    def row_height(self):
        return (ROW_HEIGHT + ROW_GAP) * self.scale

    @property
    def compact(self):
        return False  # Never remove/reflow columns at different resolutions.

    def team_y(self, index):
        return PAD + META_HEIGHT + LABEL_HEIGHT + (self.team_heights[0] + TEAM_GAP if index else 0)


def scoreboard_layout(width, height, map_rect, rows, *, team_counts=None):
    """1080p CSS canvas, centered +30px Y. Map is a separate RM sidecar.

    No animation-frame geometry in this function. This makes glyph/cache size
    stable during reveal. Small windows scale the entire original layout.
    """
    if width < 640 or height < 360:
        return None
    counts = team_counts or ((rows + 1) // 2, rows // 2)
    heights = tuple(max(120., n * (ROW_HEIGHT + ROW_GAP)) for n in counts)
    ref_height = PAD + META_HEIGHT + LABEL_HEIGHT + sum(heights) + TEAM_GAP + FOOTER_HEIGHT
    scale = min(height / 1080., (width - 40.) / REFERENCE_WIDTH,
                (height - 60.) / ref_height)
    panel_w, panel_h = REFERENCE_WIDTH * scale, ref_height * scale
    x = (width - panel_w) * .5
    y = min(height - panel_h - 16., (height - panel_h) * .5 + 30. * scale)
    # The CS panel stays centered. The RM map fits LEFT, never atop the rows.
    map_w = min(520. * scale, x - 24.)
    aspect = map_rect.height() / max(1., map_rect.width())
    map_h = min(height * .5, map_w * max(.65, min(1., aspect)))
    dock = QRectF(12., y, max(0., map_w), max(0., map_h))
    return ScoreboardLayout(QRectF(x, y, panel_w, panel_h), dock, scale, heights)


class Cs2ScoreboardRenderer:
    """Bounded text/image cache; no extraction or font upload during motion."""
    def __init__(self):
        self.assets = local_cs2_assets()
        self.portraits = TopMatchBarRenderer(self.assets)
        self._layers: OrderedDict[tuple, QImage] = OrderedDict()
        self._row_images: OrderedDict[tuple, QImage] = OrderedDict()
        self.build_count = 0
        self._context = None
        self._lives, self._changes = {}, {}

    def _text(self, p, rect, text, size, tint, *, kind='regular', align=Qt.AlignCenter):
        font = QFont(self.assets.families.get('font_' + kind, 'DejaVu Sans'))
        font.setPixelSize(round(size))
        if kind in ('bold', 'mono'):
            font.setWeight(QFont.Bold)
        elif kind == 'medium':
            font.setWeight(QFont.Medium)
        if kind == 'condensed_regular':
            font.setStyleName('Regular Condensed')
        if has_cjk(text):
            font = cjk_ui_font(font)
        p.setPen(tint)
        draw_ui_text(p, rect, elide_ui_text(font, text, rect.width(), p.device()), font,
                     align | Qt.AlignVCenter | Qt.TextSingleLine)

    def _icon(self, p, key, rect, color):
        image = self.assets.tinted(key, color)
        if not image.isNull():
            p.drawImage(rect, image)

    def _build(self, layout, frame, chinese, season, mode, density, dpi):
        area = QRectF(0, 0, REFERENCE_WIDTH, layout.bounds.height() / layout.scale)
        image = QImage(math.ceil(layout.bounds.width() * density),
                       math.ceil(layout.bounds.height() * density), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(density)
        image.setDotsPerMeterX(dpi[0])
        image.setDotsPerMeterY(dpi[1])
        image.fill(Qt.transparent)
        p = QPainter(image)
        try:
            p.scale(layout.scale, layout.scale)
            p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            clip = QPainterPath()
            clip.addRoundedRect(area, 5, 5)
            p.setClipPath(clip)
            p.fillRect(area, QColor(0, 0, 0, round(255 * SURFACE_ALPHA)))
            dots = self.assets.image('dots')
            if not dots.isNull():
                p.save()
                p.setOpacity(DOTS_ALPHA)
                for y in range(0, math.ceil(area.height()), 360):
                    for x in range(0, math.ceil(area.width()), 360):
                        p.drawImage(QRectF(x, y, 360, 360), dots)
                p.restore()
            self._meta(p, frame, chinese, season, mode)
            self._labels(p, chinese)
            for index, team in enumerate(ordered_teams(frame)):
                y = layout.team_y(index)
                tint = BLUE if team.alliance == 'Blue' else GOLD
                # CS rail is 80px, score 70px, name/count 20px. No extra heading.
                self._text(p, QRectF(PAD, y, RAIL, 80),
                           '—' if team.score is None else str(team.score), 70, tint, kind='mono')
                label = ('蓝方' if team.alliance == 'Blue' else '红方') if chinese else team.alliance.upper()
                self._text(p, QRectF(PAD, y + 82, RAIL, 24), label, 20, tint, kind='condensed_regular')
                count_color = QColor(tint)
                count_color.setAlphaF(.2)
                count = f'{len(team_cards(team))} ' + ('单位' if chinese else 'Units')
                self._text(p, QRectF(PAD, y + 108, RAIL, 24), count, 20, count_color, kind='condensed_regular')
            self._footer(p, area, chinese, season)
        finally:
            p.end()
        self.build_count += 1
        return image

    def _meta(self, p, frame, chinese, season, mode):
        gray = QColor('#808080')
        self._icon(p, 'sb_casual', QRectF(PAD + 6, PAD + 4, 24, 24), gray)
        self._text(p, QRectF(PAD + 40, PAD + 1, 550, 30), f'{mode}  ·  {season}',
                   22, gray, kind='condensed_regular', align=Qt.AlignLeft)
        self._text(p, QRectF(REFERENCE_WIDTH - PAD - 100, PAD + 4, 100, 24),
                   frame.clock_text, 18, gray, kind='mono_regular')
        p.fillRect(QRectF(PAD, PAD + 32, 860, 1), QColor(128, 128, 128, 48))
        subtitle = ('2027 规则预览 · 裁判协议未验证' if season == 2027 else 'POLAR-RM · 裁判数据') if chinese else (
            '2027 RULE PREVIEW · WIRE UNVERIFIED' if season == 2027 else 'POLAR-RM · REFEREE DATA')
        self._text(p, QRectF(PAD, PAD + 39, 750, 24), subtitle, 18, gray,
                   kind='condensed_regular', align=Qt.AlignLeft)

    def _labels(self, p, chinese):
        names = {'ping': 'ms' if chinese else 'Ping', 'name': '机器人' if chinese else 'Robot',
                 'money': '经济' if chinese else '$', 'kills': '击杀' if chinese else 'K',
                 'deaths': '阵亡' if chinese else 'D', 'assists': '助攻' if chinese else 'A',
                 'health': '血量' if chinese else 'HP', 'damage': '伤害' if chinese else 'DMG'}
        x = TABLE_X
        for key, width in COLUMNS:
            self._text(p, QRectF(x + 2, PAD + META_HEIGHT + 5, width - 4, ROW_HEIGHT),
                       names.get(key, ''), 18, QColor('#b0b0b0'), kind='condensed_regular')
            x += width

    def _row(self, p, card, tint, chinese, y):
        dead = card.life == LifeState.DEAD
        row_tint = QColor('#999999') if dead else tint
        if card.local:
            local = QColor(0, 166, 255, 18) if tint == BLUE else QColor(255, 238, 0, 18)
            p.fillRect(QRectF(TABLE_X, y, INNER, ROW_HEIGHT), local)
        # Missing observations remain unknown. Zero is never a substitute.
        values = {'ping': '—', 'flair': str(card.robot_id), 'name': match_role_text(card, chinese),
                  'money': '—', 'kills': '—' if card.kills is None else str(card.kills),
                  'deaths': '—', 'assists': '—', 'damage': '—',
                  'health': ('N/A' if not card.health_applicable else
                             '—' if card.health is None else str(card.health))}
        x = TABLE_X
        for key, width in COLUMNS:
            cell = QRectF(x, y, width, ROW_HEIGHT)
            if not dead:
                alpha = 5 if key in ('status', 'ping', 'flair', 'avatar', 'name') else 8
                p.fillRect(cell, QColor(255, 255, 255, alpha))
            if key == 'status':
                if dead:
                    self._icon(p, 'skull', cell.adjusted(3, 3, -3, -3), row_tint)
                elif card.life == LifeState.UNKNOWN:
                    self._text(p, cell, '—', 18, QColor('#888888'))
            elif key == 'avatar':
                p.drawImage(cell, self.portraits._portrait(card, None, chinese=chinese)[dead])
            else:
                inset = 6 if key != 'flair' else 1
                color = QColor('#888888') if key == 'ping' else row_tint
                self._text(p, cell.adjusted(inset, 0, -inset, 0), values[key], 18, color,
                           kind='medium' if key == 'name' else 'mono_regular',
                           align=Qt.AlignLeft if key == 'name' else Qt.AlignRight if key == 'money' else Qt.AlignCenter)
            x += width

    def _footer(self, p, area, chinese, season):
        y = area.height() - FOOTER_HEIGHT
        # Original caster controls retained as disabled material references:
        # RM does not implement Steam voice, caster/X-ray, report or commend.
        for index, key in enumerate(('sb_camera', 'sb_unmuted', 'sb_ct_silhouette', 'sb_menu')):
            self._icon(p, key, QRectF(PAD + index * 26 + 3, y + 17, 16, 16), QColor(170, 170, 170, 75))
        label = ('松开 Tab 返回 · — 未知/过期 · 观战按钮未接入' if chinese else
                 'RELEASE TAB TO RETURN · — UNKNOWN/STALE · CASTER CONTROLS UNAVAILABLE')
        self._text(p, QRectF(PAD + 140, y + 10, 760, 24), label, 12,
                   QColor(255, 255, 255, 65), kind='bold', align=Qt.AlignRight)

    def paint(self, p, width, height, map_rect, frame: MatchBarFrame, progress, *, chinese, season, mode, now,
              pointer=None):
        progress = max(0., min(1., progress))
        counts = tuple(len(team_cards(t)) for t in ordered_teams(frame))
        layout = scoreboard_layout(width, height, map_rect, sum(counts), team_counts=counts)
        if progress <= 0 or layout is None:
            return None
        density = float(p.device().devicePixelRatioF())
        dpi = (p.device().dotsPerMeterX(), p.device().dotsPerMeterY())
        # Telemetry changes invalidate only their small row textures, not the
        # entire static panel. The clock/score header is a separate cache key.
        header = (frame.clock_text, tuple((t.alliance, t.score) for t in ordered_teams(frame)))
        key = (layout.bounds.width(), layout.bounds.height(), layout.scale, counts,
               header, chinese, season, mode, density, dpi)
        if key not in self._layers:
            self._layers[key] = self._build(layout, frame, chinese, season, mode, density, dpi)
            while len(self._layers) > 6:
                self._layers.popitem(last=False)
        self._layers.move_to_end(key)
        p.save()
        try:
            p.setOpacity(p.opacity() * progress)
            p.drawImage(layout.bounds.topLeft(), self._layers[key])
            self._paint_cell_changes(p, layout, frame, season, mode, now, chinese, density, dpi)
            if pointer is not None:
                for index, team in enumerate(ordered_teams(frame)):
                    for row, card in enumerate(team_cards(team)):
                        box = QRectF(layout.bounds.x() + TABLE_X * layout.scale,
                                     layout.bounds.y() + (layout.team_y(index) + row * 26 + 1) * layout.scale,
                                     INNER * layout.scale, ROW_HEIGHT * layout.scale)
                        if box.contains(pointer):
                            p.fillRect(box, QColor(200, 200, 200, 13))
        finally:
            p.restore()
        return QRectF(layout.bounds)

    def _row_image(self, card, tint, chinese, scale, density, dpi):
        key = (card, tint.rgba(), chinese, scale, density, dpi)
        if key not in self._row_images:
            image = QImage(math.ceil(INNER * scale * density), math.ceil(ROW_HEIGHT * scale * density),
                           QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(density)
            image.setDotsPerMeterX(dpi[0])
            image.setDotsPerMeterY(dpi[1])
            image.fill(Qt.transparent)
            painter = QPainter(image)
            try:
                painter.setRenderHints(QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
                painter.scale(scale, scale)
                painter.translate(-TABLE_X, 0)
                self._row(painter, card, tint, chinese, 0)
            finally:
                painter.end()
            self._row_images[key] = image
            while len(self._row_images) > 64:
                self._row_images.popitem(last=False)
        self._row_images.move_to_end(key)
        return self._row_images[key]

    def _paint_cell_changes(self, p, layout, frame, season, mode, now, chinese, density, dpi):
        context = (season, mode, tuple((t.alliance, tuple(c.robot_id for c in team_cards(t)))
                                      for t in ordered_teams(frame)))
        if context != self._context:
            self._context = context
            self._lives.clear()
            self._changes.clear()
        p.save()
        p.translate(layout.bounds.topLeft())
        for index, team in enumerate(ordered_teams(frame)):
            tint = BLUE if team.alliance == 'Blue' else GOLD
            for row, card in enumerate(team_cards(team)):
                old = self._lives.get(card.robot_id, LifeState.UNKNOWN)
                if old != card.life:
                    self._lives[card.robot_id] = card.life
                    if old != LifeState.UNKNOWN and card.life != LifeState.UNKNOWN:
                        self._changes[card.robot_id] = (now, old)
                    else:
                        self._changes.pop(card.robot_id, None)
                image = self._row_image(card, tint, chinese, layout.scale, density, dpi)
                change = self._changes.get(card.robot_id)
                if change is not None:
                    started, previous_life = change
                    elapsed = max(0., now - started)
                    if elapsed >= CELL_TRANSITION_SECONDS:
                        self._changes.pop(card.robot_id, None)
                    else:
                        # Animate the SOURCE wash/color, not a white flash over
                        # the whole table. Both textures use CURRENT values;
                        # health/kill/unknown data never lags the observation.
                        before = self._row_image(replace(card, life=previous_life), tint, chinese,
                                                 layout.scale, density, dpi)
                        blend = QImage(image.size(), image.format())
                        blend.setDevicePixelRatio(density)
                        blend.fill(Qt.transparent)
                        painter = QPainter(blend)
                        amount = css_ease_out(elapsed / CELL_TRANSITION_SECONDS)
                        painter.setOpacity(1 - amount)
                        painter.drawImage(QPointF(), before)
                        painter.setCompositionMode(QPainter.CompositionMode_Plus)
                        painter.setOpacity(amount)
                        painter.drawImage(QPointF(), image)
                        painter.end()
                        image = blend
                p.drawImage(QPointF(TABLE_X * layout.scale,
                                   (layout.team_y(index) + row * 26 + 1) * layout.scale), image)
        p.restore()


def tab_scoreboard_active(host):
    module = host.registry.get('TacticalMap')
    return bool(module is not None and module.enabled and not host.home_visible
                and not host.menu_overlay_active() and not host.student_ui.visible
                and not host.hero_deploy_ui.active and host.tactical_map_hold_amount() > 0)


def prepare_tab_layout(host, width, height, now, *, include_map=True):
    """Resolve one physical layout BEFORE the map's existing spring/hit capture."""
    host._tab_scoreboard_layout = None
    if not include_map or not tab_scoreboard_active(host):
        return
    frame = host.top_match_bar.scoreboard_snapshot(now)
    counts = tuple(len(team_cards(t)) for t in ordered_teams(frame))
    host._tab_scoreboard_layout = scoreboard_layout(width, height, QRectF(0, 0, 520, 380),
                                                    sum(counts), team_counts=counts)


def paint_tab_scoreboard(host, p, width, height, now, *, include_map=True):
    """Full-resolution final layer. No new video/control/data polling path."""
    host._tab_scoreboard_bounds = None
    if not include_map or not tab_scoreboard_active(host):
        return
    renderer = getattr(host, '_tab_scoreboard_renderer', None)
    if renderer is None:
        renderer = host._tab_scoreboard_renderer = Cs2ScoreboardRenderer()
    frame = host.top_match_bar.scoreboard_snapshot(now)
    host._tab_scoreboard_bounds = renderer.paint(
        p, width, height, QRectF(0, 0, 520, 380), frame, host.tactical_map_hold_amount(),
        chinese=chinese_enabled(host.registry), season=host.state.rules_season,
        mode=host.state.match_mode, now=now, pointer=getattr(host, 'hover_point', None))


def scoreboard_owns_pointer(host, point):
    bounds = getattr(host, '_tab_scoreboard_bounds', None)
    return bool(bounds is not None and tab_scoreboard_active(host) and bounds.contains(point))
