"""CS2 source palette, read-only projection, DPI/cache and combined Tab regressions."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rm_client.top_match_bar import LifeState, MatchBarFrame, RobotCard, TeamStrip
from rm_client.model import build_default_registry
from rm_client.ui.cs2_scoreboard import (
    Cs2ScoreboardRenderer, scoreboard_layout, paint_tab_scoreboard,
    scoreboard_owns_pointer, tab_scoreboard_active, prepare_tab_layout,
    COLUMNS, TABLE_X, INNER, REFERENCE_WIDTH, ordered_teams,
)
from rm_client.ui.top_match_bar_controller import TopMatchBarController

ROOT=Path(__file__).resolve().parents[1]


def frame(count=7):
    def team(alliance):
        offset=100 if alliance=='Blue' else 0
        roles=[(1,'HEAVY'),(2,'ENG'),(3,'INF-1'),(4,'INF-2'),(6,'AIR SYSTEM'),(7,'SENTRY'),(8,'DART')][:count]
        cards=tuple(RobotCard(n+offset,label,LifeState.ALIVE,health=300,max_health=450,local=n+offset==3)
                    for n,label in roles)
        return TeamStrip(alliance,cards,42)
    return MatchBarFrame(team('Red'),team('Blue'),123,'RM SCORE')


class ScoreboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def image(self,width=1280,height=720,dpr=1.):
        image=QImage(round(width*dpr),round(height*dpr),QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr);image.fill(Qt.transparent)
        return image

    def draw(self,renderer,*,width=1280,height=720,dpr=1.,progress=1.,data=None,now=10):
        image=self.image(width,height,dpr)
        p=QPainter(image)
        try:
            rect=renderer.paint(p,width,height,QRectF(12,48,min(520,width*.48),380),
                                data or frame(),progress,chinese=True,season=2027,mode='RMUC7v7',now=now)
        finally:p.end()
        return image,rect

    def test_copied_cs2_materials_have_locked_hashes_and_source_rules(self):
        root=ROOT/'assets/cs2_scoreboard_source'
        manifest=json.loads((root/'provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['scope'],'authorized-distribution')
        for name,entry in manifest['assets'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),entry['sha256'])
        css=(root/'scoreboard.css').read_text(encoding='utf-8')
        for literal in ('rgba(0, 0, 0, 0.88)','background-img-opacity: 0.015',
                        'transition-duration: 0.25s','@define row-image-size: 24px'):
            self.assertIn(literal,css)

    def test_four_resolutions_keep_centered_source_geometry_and_docked_map(self):
        for width,height in ((1280,720),(1600,900),(1920,1080),(2560,1440)):
            map_rect=QRectF(12,48,520,380)
            layout=scoreboard_layout(width,height,map_rect,18)
            self.assertIsNotNone(layout)
            self.assertFalse(layout.bounds.intersects(layout.map_bounds))
            self.assertAlmostEqual(layout.bounds.center().x(),width/2)
            self.assertAlmostEqual(layout.bounds.width()/layout.scale,960)
            self.assertAlmostEqual(layout.row_height/layout.scale,26)
            self.assertTrue(QRectF(0,0,width,height).contains(layout.bounds))
            self.assertGreaterEqual(layout.row_height,12)
            self.assertTrue(QRectF(0,0,width,height).contains(layout.map_bounds))

    def test_exact_competitive_source_column_order_widths_not_percentage_table(self):
        self.assertEqual([c[0] for c in COLUMNS],['status','ping','flair','avatar','name',
                         'money','kills','deaths','assists','health','damage'])
        widths=dict(COLUMNS)
        self.assertEqual(widths['ping'],37)
        self.assertEqual(widths['money'],66)
        self.assertEqual(widths['health'],64)
        self.assertAlmostEqual(sum(widths.values()),770)
        self.assertEqual(TABLE_X,110)
        self.assertEqual(REFERENCE_WIDTH,960)
        self.assertEqual(ordered_teams(frame())[0].alliance,'Blue')

    def test_map_dock_and_table_use_same_snapshot_geometry(self):
        host=self.host()
        prepare_tab_layout(host,1920,1080,10)
        layout=host._tab_scoreboard_layout
        self.assertIsNotNone(layout)
        image=self.image(1920,1080);p=QPainter(image)
        try:paint_tab_scoreboard(host,p,1920,1080,10)
        finally:p.end()
        self.assertEqual(host._tab_scoreboard_bounds,layout.bounds)
        self.assertFalse(layout.map_bounds.intersects(layout.bounds))
        host.home_visible=True
        prepare_tab_layout(host,1920,1080,10)
        self.assertIsNone(host._tab_scoreboard_layout)

    def test_raster_at_four_dprs_has_transparent_outside_and_opaque_cs_surface(self):
        for dpr in (1.,1.25,1.5,2.):
            image,rect=self.draw(Cs2ScoreboardRenderer(),dpr=dpr)
            self.assertEqual(image.pixelColor(0,0).alpha(),0)
            point=rect.topLeft()+QPointF(8,8)
            self.assertGreaterEqual(image.pixelColor(round(point.x()*dpr),round(point.y()*dpr)).alpha(),220)

    def test_one_layer_for_100_open_close_cycles(self):
        renderer=Cs2ScoreboardRenderer()
        for index in range(100):
            self.draw(renderer,progress=(.15,.5,1.,.75,.25)[index%5])
        self.assertEqual(renderer.build_count,1)
        self.assertEqual(len(renderer._layers),1)
        rows=len(renderer._row_images)
        self.draw(renderer,progress=0)
        self.assertEqual(renderer.build_count,1)
        self.assertEqual(len(renderer._row_images),rows)
        self.assertLessEqual(rows,64)

    def test_real_qpainter_dpr_never_enters_logical_mouse_coordinates(self):
        from PySide6.QtGui import QPainterPath
        from rm_client.ui.tactical_map_interaction import MapHitGeometry, logical_map_transform
        for dpr in (1.,1.25,1.5,2.):
            image=self.image(dpr=dpr);p=QPainter(image)
            try:
                p.translate(23,17);p.scale(.8,.8)
                rect=QRectF(40,60,200,100)
                hit=MapHitGeometry.from_paint(rect,rect,logical_map_transform(p),None,rounded=False)
                # Independent manually-computed Qt logical point, not a copy
                # of the production combinedTransform/DPR calculation.
                point=QPointF(23+.8*(40+200*.3),17+.8*(60+100*.6))
                result=hit.normalized_point(point)
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result.x,.3)
                self.assertAlmostEqual(result.y,.4)
            finally:p.end()

    def test_state_cache_is_bounded_and_immediate_unknown_clears_cell_transition(self):
        renderer=Cs2ScoreboardRenderer()
        for n in range(30):self.draw(renderer,data=replace(frame(),countdown=n))
        self.assertLessEqual(len(renderer._layers),6)
        data=frame()
        dead=replace(data.left.cards[0],life=LifeState.DEAD,health=0)
        changed=replace(data,left=replace(data.left,cards=(dead,*data.left.cards[1:])))
        self.draw(renderer,data=changed,now=10.01)
        self.assertIn(dead.robot_id,renderer._changes)
        unknown=replace(dead,life=LifeState.UNKNOWN,health=None)
        changed=replace(changed,left=replace(changed.left,cards=(unknown,*changed.left.cards[1:])))
        self.draw(renderer,data=changed,now=10.02)
        self.assertNotIn(dead.robot_id,renderer._changes)

    def test_cell_wash_finishes_at_source_250ms_without_rebuilding_text(self):
        renderer=Cs2ScoreboardRenderer(); data=frame()
        self.draw(renderer,data=data)
        card=replace(data.left.cards[0],life=LifeState.DEAD,health=0)
        data=replace(data,left=replace(data.left,cards=(card,*data.left.cards[1:])))
        self.draw(renderer,data=data,now=11)
        builds=renderer.build_count
        rows=len(renderer._row_images)
        for tick in range(1,20):self.draw(renderer,data=data,now=11+tick*.01)
        self.assertEqual(len(renderer._row_images),rows)
        self.draw(renderer,data=data,now=11.26)
        self.assertFalse(renderer._changes)
        self.assertEqual(renderer.build_count,builds)

    def host(self):
        registry=build_default_registry()
        registry.get('TacticalMap').enabled=True
        registry.get('TopMatchBar').enabled=False
        state=NS(rules_season=2026,match_mode='RMUC7v7',alliance_color='Red',robot_id=3)
        backend=NS(scenario_key='OfficialEvent',referee=NS(profile_id='rm2026-v1.3.1',year=2026),
                   mqtt=NS(host='localhost',port=1883,receive_generation=1,disconnected_at=0.,connected=True))
        host=NS(registry=registry,state=state,backend=backend,home_visible=False,
                menu_overlay_active=lambda:False,student_ui=NS(visible=False),hero_deploy_ui=NS(active=False),
                tactical_map_hold_amount=lambda:1.,get_hud_scale=lambda w,h:1.,
                setting_mode=lambda module,name,default:default,hud_density=lambda:'Balanced',
                minecraft_hud_active=lambda:True)
        host.top_match_bar=TopMatchBarController(host)
        return host

    def test_disabled_mini_strip_does_not_reset_independent_tab_observations(self):
        host=self.host();controller=host.top_match_bar
        controller.observe_referee('GlobalUnitStatus',{'robot_health':[100,200,300,400,500,99,88,77,66,55]},10)
        controller.paint(None,1280,720,10)
        data=controller.scoreboard_snapshot(10)
        card=next(c for c in data.left.cards if c.robot_id==3)
        self.assertEqual(card.health,300)
        stale=controller.scoreboard_snapshot(13)
        self.assertTrue(all(c.health is None for t in (stale.left,stale.right) for c in t.cards))
        host.backend.mqtt.connected=False
        self.assertTrue(all(c.health is None for c in controller.scoreboard_snapshot(10).left.cards))

    def test_2027_cannot_reuse_2026_feed_and_real_roster_has_heavy_not_engineer(self):
        host=self.host();host.state.rules_season=2027
        controller=host.top_match_bar
        controller.observe_referee('GlobalUnitStatus',{'robot_health':[100]*10},10)
        data=controller.scoreboard_snapshot(10)
        self.assertTrue(all(c.health is None for c in data.left.cards))
        ids={c.robot_id for c in data.left.cards}
        self.assertIn(1,ids);self.assertNotIn(2,ids)
        self.assertEqual(next(c for c in data.left.cards if c.robot_id==1).label,'HEAVY')

    def test_group_reuses_map_progress_and_glyphs_without_reshaping_during_motion(self):
        host=self.host();image=self.image();p=QPainter(image)
        try:
            for progress in (.1,.3,.8,1.,.4,.1):
                host.tactical_map_hold_amount=lambda:progress
                paint_tab_scoreboard(host,p,1280,720,10)
                self.assertIsNotNone(host._tab_scoreboard_bounds)
            self.assertEqual(host._tab_scoreboard_renderer.build_count,1)
            point=host._tab_scoreboard_bounds.center()
            self.assertTrue(scoreboard_owns_pointer(host,point))
            host.tactical_map_hold_amount=lambda:0
            paint_tab_scoreboard(host,p,1280,720,10)
            self.assertIsNone(host._tab_scoreboard_bounds)
            self.assertFalse(scoreboard_owns_pointer(host,point))
        finally:p.end()

    def test_modal_home_module_off_and_include_map_false_clear_presentation(self):
        host=self.host();image=self.image();p=QPainter(image)
        try:
            for attr,value in (('home_visible',True),('student_ui',NS(visible=True)),
                               ('hero_deploy_ui',NS(active=True)),('menu_overlay_active',lambda:True)):
                with patch.object(host,attr,value):
                    self.assertFalse(tab_scoreboard_active(host))
                    paint_tab_scoreboard(host,p,1280,720,10)
                    self.assertIsNone(host._tab_scoreboard_bounds)
            paint_tab_scoreboard(host,p,1280,720,10,include_map=False)
            self.assertIsNone(host._tab_scoreboard_bounds)
            host.registry.get('TacticalMap').enabled=False
            self.assertFalse(tab_scoreboard_active(host))
        finally:p.end()


if __name__=='__main__':unittest.main()
