"""Native transcription of CS2's competitive Tab scoreboard.

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
from .cs2_scoreboard_motion import css_ease_in_out, stat_brightness
from .fonts import draw_ui_text, elide_ui_text, ui_text_advance
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
# Competitive XML has a 100px timeline plus 2px margins, not the empty 20px
# spacer used by the casual/no-timeline fallback. The 80+24+24 rail sets a
# 132px minimum team extent even when a 1v1/3v3 table has fewer than five rows.
META_HEIGHT, LABEL_HEIGHT, TEAM_GAP, FOOTER_HEIGHT = 75., 26., 104., 48.
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


def scoreboard_font(assets, kind, size):
    # All Stratum2 exports share family names. Merely registering the bold/
    # condensed file and constructing QFont(family) selects REGULAR again.
    font = QFont(assets.families.get('font_' + kind, 'DejaVu Sans'))
    font.setPixelSize(round(size))
    font.setStyleName({'bold': 'Bold', 'mono': 'Bold', 'medium': 'Medium',
                       'condensed': 'Bold Condensed', 'condensed_regular': 'Regular Condensed',
                       'mono_regular': 'Regular'}.get(kind, 'Regular'))
    return font


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
    heights = tuple(max(132., n * (ROW_HEIGHT + ROW_GAP)) for n in counts)
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
        self.sort_key = 'damage'
        self._row_positions = {}
        self._sort_transition = None
        self._order = None
        self.last_layout = None
        self._stats, self._stat_changes = {}, {}
        self._stat_images = OrderedDict()
        self._team_visuals = {}

    def _text(self, p, rect, text, size, tint, *, kind='regular', align=Qt.AlignCenter,
              fit=False, shadow=False):
        font = scoreboard_font(self.assets, kind, size)
        # draw_ui_text applies Regular CJK only to CJK FormatRanges. Replacing
        # the complete mixed line would discard Stratum2 for RMUC/IDs/digits.
        if fit:
            advance = ui_text_advance(font, text, p.device())
            if advance > rect.width():
                font.setPixelSize(max(7, math.floor(size * rect.width() / advance)))
        flags = align | Qt.AlignVCenter | Qt.TextSingleLine
        display = elide_ui_text(font, text, rect.width(), p.device())
        if shadow:
            p.setPen(QColor(0, 0, 0, 128))
            draw_ui_text(p, rect.translated(2, 2), display, font, flags)
        p.setPen(tint)
        draw_ui_text(p, rect, display, font, flags)

    def _icon(self, p, key, rect, color):
        image = self.assets.washed(key, color)
        if not image.isNull():
            p.drawImage(rect, image)

    def _build(self, layout, frame, chinese, season, mode, density, dpi, history, duration, identities):
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
                visual = identities.get(team.alliance)
                if visual is not None and not visual.image.isNull():
                    # Source .sb-team-logo-bg: 80px rail, contain, opacity .2.
                    # No new official-client header or extra crest slot.
                    size = visual.image.size().scaled(80,80,Qt.KeepAspectRatio)
                    p.save();p.setOpacity(.2)
                    p.drawImage(QRectF(PAD, y, size.width(), size.height()), visual.image)
                    p.restore()
                # CS rail is 80px, score 70px, name/count 20px. No extra heading.
                self._text(p, QRectF(PAD, y, RAIL, 80),
                           '—' if team.score is None else str(team.score), 70, tint, kind='mono',
                           fit=True, shadow=True)
                identity = visual.identity if visual is not None else None
                named = identity is not None and bool(identity.school or identity.team)
                label = (identity.school or identity.team) if named else (
                    ('蓝方' if team.alliance == 'Blue' else '红方') if chinese else team.alliance.upper())
                self._text(p, QRectF(PAD, y + 82, RAIL, 24), label, 14 if named else 20,
                           tint, kind='condensed_regular')
                count_color = QColor(tint)
                count_color.setAlphaF(.2)
                total = sum(c.health_applicable for c in team.cards)
                count = f'{team.alive_text}/{total} ' + ('存活' if chinese else 'Alive')
                caption = identity.team if named and identity.school and identity.team else count
                self._text(p, QRectF(PAD, y + 108, RAIL, 24), caption, 13 if caption != count else 20,
                           tint if caption != count else count_color, kind='condensed_regular')
            self._timeline(p, layout, frame, history, duration, chinese)
            self._footer(p, area, chinese, season)
        finally:
            p.end()
        self.build_count += 1
        return image

    def _meta(self, p, frame, chinese, season, mode):
        gray = QColor('#808080')
        self._icon(p, 'sb_competitive', QRectF(PAD + 6, PAD + 4, 24, 24), gray)
        title = ('竞技模式' if chinese else 'Competitive') + f' | {mode}'
        self._text(p, QRectF(PAD + 40, PAD + 1, 550, 30), title,
                   22, gray, kind='condensed', align=Qt.AlignLeft)
        self._text(p, QRectF(PAD + 760, PAD + 4, 100, 24),
                   frame.clock_text, 18, gray, kind='mono_regular')
        p.fillRect(QRectF(PAD, PAD + 32, 860, 1), QColor(128, 128, 128, 48))
        subtitle = ('2027 规则预览 · 裁判协议未验证' if season == 2027 else 'POLAR-RM · 裁判数据') if chinese else (
            '2027 RULE PREVIEW · WIRE UNVERIFIED' if season == 2027 else 'POLAR-RM · REFEREE DATA')
        # Source server/viewer label is 14px, aligned RIGHT on the second row.
        # It is not a second large custom title across the left of the board.
        self._text(p, QRectF(PAD + 100, PAD + 39, 760, 24), subtitle, 14, gray,
                   kind='regular', align=Qt.AlignRight)

    def _labels(self, p, chinese):
        names = {'name': '名称' if chinese else 'Name',
                 'money': '经济' if chinese else '$', 'kills': '击杀' if chinese else 'K',
                 'deaths': '阵亡' if chinese else 'D', 'assists': '助攻' if chinese else 'A',
                 'health': '血量' if chinese else 'HP', 'damage': '伤害' if chinese else 'DMG'}
        x = TABLE_X
        for key, width in COLUMNS:
            if key == 'ping':
                self._icon(p, 'sb_ping_4', QRectF(x + (width-16)/2, PAD + META_HEIGHT + 9, 16, 16),
                           QColor('#b0b0b0'))
                x += width
                continue
            if key == self.sort_key:
                p.fillRect(QRectF(x, PAD + META_HEIGHT + 1, width, ROW_HEIGHT), QColor(255,255,255,16))
            self._text(p, QRectF(x + 2, PAD + META_HEIGHT + 5, width - 4, ROW_HEIGHT),
                       names.get(key, ''), 18, QColor('#ffffff' if key == self.sort_key else '#b0b0b0'),
                       kind='condensed_regular')
            x += width

    def _row(self, p, card, tint, chinese, y):
        dead = card.life == LifeState.DEAD
        row_tint = QColor('#999999') if dead else tint
        if card.local:
            local = QColor(0, 166, 255, 18) if tint == BLUE else QColor(255, 238, 0, 18)
            p.fillRect(QRectF(TABLE_X, y, INNER, ROW_HEIGHT), local)
        # Missing observations remain unknown. Zero is never a substitute.
        values = {'ping': '—', 'flair': '', 'name': match_role_text(card, chinese) + f'  #{card.robot_id}',
                  'money': '—', 'kills': '—' if card.kills is None else str(card.kills),
                  'deaths': '—', 'assists': '—', 'damage': '—',
                  'health': ('N/A' if not card.health_applicable else
                             '—' if card.health is None else str(card.health))}
        x = TABLE_X
        for key, width in COLUMNS:
            cell = QRectF(x, y, width, ROW_HEIGHT)
            if not dead:
                alpha = 5 if key in ('status', 'ping', 'flair', 'avatar', 'name') else 8
                if key == self.sort_key:
                    alpha = 16
                p.fillRect(cell, QColor(255, 255, 255, alpha))
            if key == 'status':
                if dead:
                    self._icon(p, 'sb_elimination', cell.adjusted(2, 2, -2, -2), row_tint)
                elif card.life == LifeState.UNKNOWN:
                    self._text(p, cell, '—', 18, QColor('#888888'))
            elif key == 'avatar':
                p.drawImage(cell, self.portraits._portrait(card, None, chinese=chinese)[dead])
            elif key == 'flair':
                pass  # Original flair is an optional badge, not a numeric ID.
            else:
                inset = 6 if key != 'flair' else 1
                color = QColor('#888888') if key == 'ping' else QColor('#ffffff') if key == self.sort_key else row_tint
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
        label = ('点击列标题排序 | 松开 TAB 返回' if chinese else 'CLICK A COLUMN TO SORT | RELEASE TAB TO RETURN')
        self._text(p, QRectF(PAD + 140, y + 10, 760, 24), label, 12,
                   QColor(255, 255, 255, 32), kind='bold', align=Qt.AlignRight)

    def _timeline(self, p, layout, frame, history, duration, chinese):
        """Original no-half-times 650px/100px competitive strip; RM time ticks.

        Symbols mean observed robot losses, NOT CS round results. A missing
        history stays empty. No inferred winners/MVPs/loss-bonus/economy.
        """
        y = layout.team_y(0) + layout.team_heights[0] + 2
        self._text(p, QRectF(PAD, y + 37, RAIL, 24), '战况' if chinese else 'History',
                   18, QColor(170,170,170,150), kind='condensed_regular')
        interval = max(15, math.ceil(duration / 24 / 5) * 5)
        count = min(24, math.ceil(duration / interval))
        start = TABLE_X + (650 - count * 20) / 2 + 10
        elapsed = duration-frame.countdown if frame.countdown is not None else None
        buckets = {}
        for event in history:
            bucket = min(count-1, max(0, int((duration-event.remaining)/interval)))
            buckets.setdefault((bucket, event.alliance), []).append(event)
        for index in range(count):
            x = start + index*20
            passed = elapsed is not None and index*interval <= elapsed
            p.fillRect(QRectF(x+1, y+49, 18, 2), QColor(255,255,255,22 if passed else 7))
            if index % 4 == 0:
                seconds = index*interval
                self._text(p, QRectF(x-12, y+66, 44, 18), f'{seconds//60}:{seconds%60:02}',
                           14, QColor(170,170,170,150 if passed else 50), kind='condensed_regular')
            for alliance, tint, dy in (('Blue', BLUE, 23), ('Red', GOLD, 53)):
                events = buckets.get((index, alliance), ())
                if events:
                    # Two bands use the source 20px result glyph and .4 wash.
                    color = QColor(tint)
                    color.setAlphaF(.4)
                    self._icon(p, 'kill_flag', QRectF(x+3, y+dy, 14, 20), color)
        label = ('装甲血量归零观测' if chinese else 'OBSERVED HP LOSSES') if history else (
            '暂无已确认战况' if chinese else 'NO OBSERVED LOSSES')
        self._text(p, QRectF(TABLE_X+655, y+35, 115, 32), label, 12, QColor(170,170,170,100),
                   kind='condensed_regular', fit=True)

    def sorted_cards(self, team):
        cards = team_cards(team)
        if self.sort_key == 'name':
            return tuple(sorted(cards, key=lambda c: (c.label, c.robot_id)))
        if self.sort_key in ('kills', 'health'):
            return tuple(sorted(cards, key=lambda c: (getattr(c, self.sort_key) is None,
                                                      -(getattr(c, self.sort_key) or 0), c.robot_id)))
        return cards  # Do not rank unknown/unimplemented values as zero.

    def click(self, point, now):
        if self.last_layout is None:
            return
        layout = self.last_layout
        local = (point-layout.bounds.topLeft()) / layout.scale
        if not PAD+META_HEIGHT <= local.y() <= PAD+META_HEIGHT+LABEL_HEIGHT:
            return
        x = TABLE_X
        for key, width in COLUMNS:
            if x <= local.x() < x+width and key in ('name','kills','deaths','assists','health','damage','money'):
                if self.sort_key != key:
                    self.sort_key = key
                    self._sort_transition = (now, dict(self._row_positions))
                return
            x += width

    def paint(self, p, width, height, map_rect, frame: MatchBarFrame, progress, *, chinese, season, mode, now,
              pointer=None, history=(), duration=420, identities=None):
        progress = max(0., min(1., progress))
        counts = tuple(len(team_cards(t)) for t in ordered_teams(frame))
        layout = scoreboard_layout(width, height, map_rect, sum(counts), team_counts=counts)
        if progress <= 0 or layout is None:
            self.last_layout = None
            return None
        self.last_layout = layout
        self._team_visuals = identities or {}
        duration = max(1, min(3600, int(duration)))
        density = float(p.device().devicePixelRatioF())
        dpi = (p.device().dotsPerMeterX(), p.device().dotsPerMeterY())
        # Telemetry changes invalidate only their small row textures, not the
        # entire static panel. The clock/score header is a separate cache key.
        header = (frame.clock_text, tuple((t.alliance, t.score) for t in ordered_teams(frame)))
        key = (layout.bounds.width(), layout.bounds.height(), layout.scale, counts,
               header, tuple(t.alive_text for t in ordered_teams(frame)), tuple(history), duration,
               self.sort_key, chinese, season, mode, density, dpi)
        key += (tuple((side,visual.cache_key) for side,visual in sorted(self._team_visuals.items())),)
        if key not in self._layers:
            self._layers[key] = self._build(layout, frame, chinese, season, mode, density, dpi, history, duration,
                                           self._team_visuals)
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
                    for row, card in enumerate(self.sorted_cards(team)):
                        box = QRectF(layout.bounds.x() + TABLE_X * layout.scale,
                                     layout.bounds.y() + self._row_positions[card.robot_id] * layout.scale,
                                     INNER * layout.scale, ROW_HEIGHT * layout.scale)
                        if box.contains(pointer):
                            p.fillRect(box, QColor(200, 200, 200, 13))
        finally:
            p.restore()
        return QRectF(layout.bounds)

    def team_tooltip(self, point):
        layout = self.last_layout
        if layout is None:
            return ''
        local = (point-layout.bounds.topLeft())/layout.scale
        for index,side in enumerate(('Blue','Red')):
            if QRectF(PAD,layout.team_y(index),RAIL,132).contains(local):
                visual = self._team_visuals.get(side)
                return visual.tooltip if visual is not None else ''
        return ''

    def _row_image(self, card, tint, chinese, scale, density, dpi):
        key = (card, tint.rgba(), chinese, scale, density, dpi, self.sort_key)
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
            self._row_positions.clear()
            self._sort_transition = None
            self._order = None
            self._stats.clear()
            self._stat_changes.clear()
        p.save()
        p.translate(layout.bounds.topLeft())
        order = tuple(tuple(c.robot_id for c in self.sorted_cards(t)) for t in ordered_teams(frame))
        if self._order is not None and self._order != order:
            self._sort_transition = (now, dict(self._row_positions))
        self._order = order
        for index, team in enumerate(ordered_teams(frame)):
            tint = BLUE if team.alliance == 'Blue' else GOLD
            for row, card in enumerate(self.sorted_cards(team)):
                y = layout.team_y(index) + row*26+1
                if self._sort_transition is not None:
                    started, positions = self._sort_transition
                    y = positions.get(card.robot_id, y)+(y-positions.get(card.robot_id, y))*css_ease_in_out(
                        (now-started)/CELL_TRANSITION_SECONDS)
                self._row_positions[card.robot_id] = y
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
                p.drawImage(QPointF(TABLE_X * layout.scale, y * layout.scale), image)
                self._paint_stat_pulses(p, card, y, layout.scale, density, dpi, now)
        if self._sort_transition is not None and now-self._sort_transition[0] >= CELL_TRANSITION_SECONDS:
            self._sort_transition = None
        p.restore()

    def _paint_stat_pulses(self, p, card, y, scale, density, dpi, now):
        x = TABLE_X
        for key, width in COLUMNS:
            if key not in ('health', 'kills'):
                x += width
                continue
            token = (card.robot_id, key)
            value = getattr(card, key) if card.life != LifeState.UNKNOWN else None
            previous = self._stats.get(token)
            self._stats[token] = value
            if value is None:
                self._stat_changes.pop(token, None)
            elif previous is not None and previous != value:
                self._stat_changes[token] = now
            start = self._stat_changes.get(token)
            if start is not None and now-start >= 1:
                self._stat_changes.pop(token, None)
                start = None
            if start is not None:
                cache_key = (str(value), width, scale, density, dpi)
                if cache_key not in self._stat_images:
                    image = QImage(math.ceil(width*scale*density), math.ceil(24*scale*density),
                                   QImage.Format_ARGB32_Premultiplied)
                    image.setDevicePixelRatio(density)
                    image.setDotsPerMeterX(dpi[0])
                    image.setDotsPerMeterY(dpi[1])
                    image.fill(Qt.transparent)
                    ink = QPainter(image)
                    try:
                        ink.scale(scale, scale)
                        self._text(ink, QRectF(6, 0, width-12, 24), str(value), 18, QColor('white'), kind='mono_regular')
                    finally:
                        ink.end()
                    self._stat_images[cache_key] = image
                    while len(self._stat_images) > 64:
                        self._stat_images.popitem(last=False)
                p.save()
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                p.setOpacity(p.opacity()*min(1., (stat_brightness(now-start)-1)/2))
                p.drawImage(QPointF(x*scale, y*scale), self._stat_images[cache_key])
                p.restore()
            x += width


def tab_scoreboard_active(host):
    module = host.registry.get('TacticalMap')
    return bool(module is not None and module.enabled and not host.home_visible
                and not host.menu_overlay_active() and not host.student_ui.visible
                and not getattr(getattr(host, "hero_deploy_ui", None), "active", False) and host.tactical_map_hold_amount() > 0)


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
        mode=host.state.match_mode, now=now, pointer=getattr(host, 'hover_point', None),
        history=host.top_match_bar._scoreboard_history.snapshot(),
        duration=getattr(host.state, 'match_duration_sec', 420),
        identities=host.top_match_bar.team_profiles.visuals)
    pointer = getattr(host,'hover_point',None)
    if pointer is not None:
        tooltip = renderer.team_tooltip(pointer)
        if tooltip:
            host.draw_tooltip(p,pointer,tooltip)


def scoreboard_click(host, point):
    """Presentation-only action. Caller has already acquired pointer ownership."""
    renderer = getattr(host, '_tab_scoreboard_renderer', None)
    if renderer is not None:
        renderer.click(point, float(host.gui_motion.now))
        host.frame_scheduler.force()


def scoreboard_owns_pointer(host, point):
    bounds = getattr(host, '_tab_scoreboard_bounds', None)
    return bool(bounds is not None and tab_scoreboard_active(host) and bounds.contains(point))
