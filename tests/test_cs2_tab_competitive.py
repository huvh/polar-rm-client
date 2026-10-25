"""Independent source/behavior checks for the normal competitive Tab shell."""
from dataclasses import replace
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontInfo, QPainter
from PySide6.QtWidgets import QApplication
import test_cs2_tab_scoreboard as scoreboard_fixture
from rm_client.top_match_bar import LifeState
from rm_client.ui.cs2_scoreboard import Cs2ScoreboardRenderer, TEAM_GAP, COLUMNS, TABLE_X, scoreboard_font
from rm_client.ui.cs2_scoreboard_history import ScoreboardHistory
from rm_client.ui.cs2_scoreboard_motion import css_ease_in_out, stat_brightness


frame = scoreboard_fixture.frame


class CompetitiveTests(unittest.TestCase):
    image = scoreboard_fixture.ScoreboardTests.image
    draw = scoreboard_fixture.ScoreboardTests.draw

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_normal_competitive_middle_is_not_the_casual_empty_spacer(self):
        css = (Path(__file__).resolve().parents[1]/'assets/cs2_scoreboard_source/scoreboard.css').read_text(encoding='utf-8')
        body = re.search(r'\.sb-timeline__segments\s*\{([^}]+)', css).group(1)
        minimum = float(re.search(r'min-height:\s*(\d+)px', body).group(1))
        body = re.search(r'\.sb-timeline\s*\{([^}]+)', css).group(1)
        margins = sum(float(x) for x in re.findall(r'margin-(?:top|bottom):\s*(\d+)px', body))
        self.assertEqual(TEAM_GAP, minimum+margins)
        xml = (Path(__file__).resolve().parents[1]/'assets/cs2_scoreboard_source/scoreboard.xml').read_text(encoding='utf-8')
        self.assertIn('snippet_scoreboard-classic--with-timeline--no-half-times', xml)

    def test_shared_family_selects_real_medium_bold_and_condensed_faces(self):
        renderer = Cs2ScoreboardRenderer()
        for kind, style in (('medium','Medium'), ('condensed','Bold Condensed'),
                            ('condensed_regular','Regular Condensed'), ('mono','Bold'), ('mono_regular','Regular')):
            self.assertEqual(QFontInfo(scoreboard_font(renderer.assets, kind, 18)).styleName(), style)

    def test_wash_preserves_competitive_emblem_details_not_solid_alpha_square(self):
        assets = Cs2ScoreboardRenderer().assets
        washed = assets.washed('sb_competitive', QColor('#808080'))
        self.assertFalse(washed.isNull())
        rgb = {washed.pixelColor(x,y).rgb() for x in range(8,88,4) for y in range(8,88,4)}
        self.assertGreater(len(rgb), 12)
        self.assertIs(assets.washed('sb_competitive', QColor('#808080')), washed)
        image = assets.washed('sb_ping_4', QColor(255,255,255,100))
        self.assertEqual(image.pixelColor(0,0).alpha(), 0)
        self.assertLessEqual(max(image.pixelColor(x,y).alpha() for x in range(96) for y in range(96)), 100)

    def test_chinese_line_keeps_original_latin_face_and_uses_existing_cjk_runs(self):
        import rm_client.ui.cs2_scoreboard as module
        renderer=Cs2ScoreboardRenderer(); image=self.image(); p=QPainter(image)
        try:
            with patch.object(module, 'draw_ui_text', wraps=module.draw_ui_text) as draw:
                renderer._text(p,QRectF(0,0,550,32),'竞技模式 | RMUC7v7',22,QColor('white'),kind='condensed')
            font=draw.call_args.args[3]
            self.assertEqual(font.family(),renderer.assets.families['font_condensed'])
            self.assertEqual(font.styleName(),'Bold Condensed')
        finally:
            p.end()

    def test_stat_pulse_is_source_one_second_curve_not_a_white_rectangle(self):
        self.assertEqual(stat_brightness(0), 1)
        self.assertEqual(stat_brightness(.05), 3)
        self.assertEqual(stat_brightness(1), 1)
        self.assertGreater(stat_brightness(.5), 1)
        self.assertAlmostEqual(css_ease_in_out(.5), .5)
        renderer = Cs2ScoreboardRenderer(); data = frame()
        self.draw(renderer, data=data, now=10)
        c = replace(data.left.cards[0], health=110)
        data = replace(data, left=replace(data.left,cards=(c,*data.left.cards[1:])))
        first, bounds = self.draw(renderer,data=data,now=11)
        pulse, _ = self.draw(renderer,data=data,now=11.05)
        builds = renderer.build_count; cache = len(renderer._stat_images)
        self.assertNotEqual(first, pulse)
        # Pulse changes only glyph pixels in one cell; it cannot tint a panel.
        point = bounds.topLeft()+QPointF(15,15)
        self.assertEqual(first.pixelColor(point.toPoint()),pulse.pixelColor(point.toPoint()))
        for i in range(1,20): self.draw(renderer,data=data,now=11.05+i*.04)
        self.assertEqual(cache, len(renderer._stat_images))
        self.assertEqual(builds, renderer.build_count)
        self.draw(renderer,data=data,now=12.1)
        self.assertFalse(renderer._stat_changes)

    def test_click_sort_and_data_resort_ease_rows_without_affecting_telemetry(self):
        renderer = Cs2ScoreboardRenderer(); data = frame()
        a,b,*rest = data.left.cards
        data = replace(data,left=replace(data.left,cards=(replace(a,kills=1),replace(b,kills=4),*rest)))
        _, bounds = self.draw(renderer,data=data,now=10)
        layout=renderer.last_layout
        x = TABLE_X + sum(w for k,w in COLUMNS[:6]) + dict(COLUMNS)['kills']/2
        point = bounds.topLeft()+QPointF(x*layout.scale, (20+75+12)*layout.scale)
        renderer.click(point,11)
        self.assertEqual(renderer.sort_key, 'kills')
        self.draw(renderer,data=data,now=11)
        initial = renderer._row_positions[a.robot_id]
        self.draw(renderer,data=data,now=11.125)
        middle = renderer._row_positions[a.robot_id]
        self.draw(renderer,data=data,now=11.26)
        target = renderer._row_positions[a.robot_id]
        self.assertLess(initial,middle); self.assertLess(middle,target)
        self.assertEqual(renderer.sorted_cards(data.left)[0].robot_id,b.robot_id)
        self.assertIsNone(renderer._sort_transition)
        self.assertEqual(a.kills, None)  # Original frozen frame is not mutated.


class HistoryTests(unittest.TestCase):
    def test_only_known_alive_to_dead_with_confirmed_match_clock_is_recorded(self):
        history = ScoreboardHistory(); data = replace(frame(),phase='MATCH')
        history.observe(data,('source',1))
        dead = replace(data.left.cards[0],life=LifeState.DEAD,health=0)
        changed = replace(data,left=replace(data.left,cards=(dead,*data.left.cards[1:])))
        history.observe(changed,('source',1)); history.observe(changed,('source',1))
        self.assertEqual(len(history.snapshot()),1)
        self.assertEqual(history.snapshot()[0].remaining,123)
        history.observe(data,('source',2))
        self.assertFalse(history.snapshot())
        unknown = replace(dead,life=LifeState.UNKNOWN,health=None)
        history.observe(replace(changed,left=replace(changed.left,cards=(unknown,*changed.left.cards[1:]))),('source',2))
        history.observe(changed,('source',2))
        self.assertFalse(history.snapshot())

    def test_history_is_bounded_and_unclocked_or_unstaged_edges_are_not_invented(self):
        history = ScoreboardHistory(); data = replace(frame(),phase='MATCH')
        dead = replace(data.left.cards[0],life=LifeState.DEAD,health=0)
        changed = replace(data,left=replace(data.left,cards=(dead,*data.left.cards[1:])))
        for i in range(100):
            history.observe(data,1); history.observe(changed,1)
        self.assertEqual(len(history.snapshot()),64)
        history.reset()
        history.observe(replace(data,countdown=None),1);history.observe(replace(changed,countdown=None),1)
        self.assertFalse(history.snapshot())
        history.observe(replace(data,phase='PREPARE'),1);history.observe(replace(changed,phase='PREPARE'),1)
        self.assertFalse(history.snapshot())


if __name__ == '__main__':
    unittest.main()
