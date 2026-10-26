"""Official match-info adapter, portable logos and in-place CS rail replacement."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path[:0] = [str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
import test_cs2_tab_scoreboard as fixture
from rm_client.ui.match_teams import MatchTeamStore, TeamIdentity, SIDES
from rm_client.ui.cs2_scoreboard import Cs2ScoreboardRenderer, PAD, RAIL


APP = QApplication.instance() or QApplication([])


class TeamIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = MatchTeamStore(self.root/'profile')

    def logo(self, name='logo.png',width=100,height=80):
        image = QImage(width,height,QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p=QPainter(image);p.setBrush(QColor('#41a7c7'));p.drawEllipse(QRectF(2,2,width-4,height-4));p.end()
        path=self.root/name
        self.assertTrue(image.save(str(path)))
        return path

    def test_official_engine_fields_and_adjacent_logos_utf8_and_gb18030(self):
        for encoding in ('utf-8','gb18030'):
            for side in SIDES:self.logo(f'compress_{side.lower()}_team_logo.png')
            data={'red_team':{'college_name':'复旦大学','name':'星云FGA','college_logo':'https://invalid.example/logo.png'},
                  'blue_team':{'college_name':'西安电子科技大学','name':'IRobot','emblem':''},
                  'red_score':99999,'status':0}
            path=self.root/'match_info.json';path.write_bytes(json.dumps(data,ensure_ascii=False).encode(encoding))
            previous=dict(self.store.teams)
            teams=self.store.read_official(path)
            self.assertEqual(teams['Red'].school,'复旦大学')
            self.assertEqual(teams['Blue'].team,'IRobot')
            self.assertTrue(all(t.logo for t in teams.values()))
            self.assertEqual(self.store.teams,previous)  # Import remains a draft.
            self.store.save(teams)
            self.assertFalse(self.store.visuals['Red'].image.isNull())

    def test_no_remote_url_fetch_or_arbitrary_external_logo_path(self):
        external=self.logo()
        data={side.lower()+'_team':{'college_name':side,'name':'Team',
                                   'college_logo':str(external)} for side in SIDES}
        path=self.root/'match.json';path.write_text(json.dumps(data),encoding='utf-8')
        teams=self.store.read_official(path)
        self.assertTrue(all(not team.logo for team in teams.values()))

    def test_names_and_alpha_preserving_logos_move_with_portable_profile(self):
        name=self.store.import_logo(self.logo(width=1024,height=512))
        teams={s:TeamIdentity(s+'大学','战队',name) for s in SIDES}
        self.store.save(teams)
        path=self.root/'moved';shutil.copytree(self.store.root,path)
        moved=MatchTeamStore(path)
        self.assertFalse(moved.error)
        self.assertEqual(moved.teams,teams)
        image=moved.visuals['Blue'].image
        self.assertEqual((image.width(),image.height()),(512,256))
        self.assertEqual(image.pixelColor(0,0).alpha(),0)
        self.assertNotIn(str(self.root/'logo.png'),(path/'teams.json').read_text(encoding='utf-8'))

    def test_invalid_profile_and_logo_cannot_escape_or_replace_existing_pair(self):
        teams={s:TeamIdentity('学校',s) for s in SIDES};self.store.save(teams)
        original=(self.store.root/'teams.json').read_bytes()
        for bad in ('../logo.png','https://example.invalid/logo.png','C:/logo.png',None):
            with self.assertRaises((ValueError,TypeError)):
                self.store.save({**teams,'Red':TeamIdentity('bad','bad',bad)})
            self.assertEqual((self.store.root/'teams.json').read_bytes(),original)
            self.assertEqual(self.store.teams,teams)
        for name in ('x'*81,'学校\n覆盖','学校\u202e覆盖'):
            with self.assertRaises(ValueError):self.store.save({**teams,'Red':TeamIdentity(name)})
        corrupt=self.store.root/'teams.json';corrupt.write_text('{',encoding='utf-8')
        loaded=MatchTeamStore(self.store.root)
        self.assertTrue(loaded.error)
        self.assertFalse(any(t.school for t in loaded.teams.values()))

    def test_malformed_metadata_and_oversized_images_fail_without_partial_save(self):
        path=self.root/'bad.json';path.write_text('{"red_team":{}}',encoding='utf-8')
        with self.assertRaises(ValueError):self.store.read_official(path)
        path.write_bytes(b' '*262145)
        with self.assertRaises(ValueError):self.store.read_official(path)
        large=self.logo(width=2100,height=2100)
        with self.assertRaises(ValueError):self.store.import_logo(large)
        self.assertFalse((self.store.root/'teams.json').exists())

    def test_school_identity_changes_only_original_cs_team_rail_and_cache(self):
        renderer=Cs2ScoreboardRenderer();frame=fixture.frame()
        teams={side:TeamIdentity(side+'University','RM Team',self.store.import_logo(self.logo())) for side in SIDES}
        self.store.save(teams)
        def draw(identities=None):
            image=QImage(1280,720,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent)
            p=QPainter(image)
            try:
                bounds=renderer.paint(p,1280,720,QRectF(0,0,520,380),frame,1.,chinese=True,
                                      season=2026,mode='RMUC7v7',now=10,identities=identities)
            finally:p.end()
            return image,bounds
        before,bounds=draw();after,updated=draw(self.store.visuals)
        self.assertEqual(bounds,updated)
        layout=renderer.last_layout
        allowed=[QRectF(bounds.x()+PAD*layout.scale,bounds.y()+layout.team_y(i)*layout.scale,
                        RAIL*layout.scale,132*layout.scale).adjusted(-2,-2,2,2) for i in (0,1)]
        changed=0
        for y in range(round(bounds.top()),round(bounds.bottom())):
            for x in range(round(bounds.left()),round(bounds.right())):
                if before.pixel(x,y) != after.pixel(x,y):
                    changed+=1
                    self.assertTrue(any(r.contains(QPointF(x,y)) for r in allowed),(x,y))
        self.assertGreater(changed,100)
        self.assertEqual(renderer.team_tooltip(allowed[0].center()),'BlueUniversity · RM Team')
        builds=renderer.build_count
        with patch.object(Path,'read_bytes',side_effect=AssertionError('No file I/O during paint')):
            for _ in range(100):draw(self.store.visuals)
        self.assertEqual(builds,renderer.build_count)

    def test_four_resolutions_and_four_dprs_keep_all_identity_geometry_in_original_rail(self):
        logo=self.store.import_logo(self.logo())
        self.store.save({side:TeamIdentity('很长的大学全称用于省略号检查','Very Long Team Name',logo) for side in SIDES})
        renderer=Cs2ScoreboardRenderer()
        for width,height in ((1280,720),(1600,900),(1920,1080),(2560,1440)):
            for dpr in (1.,1.25,1.5,2.):
                image=QImage(round(width*dpr),round(height*dpr),QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr);image.fill(Qt.transparent);p=QPainter(image)
                try:
                    bounds=renderer.paint(p,width,height,QRectF(0,0,520,380),fixture.frame(),1.,
                                          chinese=True,season=2026,mode='RMUC7v7',now=10,
                                          identities=self.store.visuals)
                finally:p.end()
                layout=renderer.last_layout
                self.assertEqual(bounds.center().x(),width/2)
                for i in (0,1):
                    point=bounds.topLeft()+QPointF((PAD+RAIL/2)*layout.scale,
                                                  (layout.team_y(i)+90)*layout.scale)
                    self.assertEqual(renderer.team_tooltip(point),'很长的大学全称用于省略号检查 · Very Long Team Name')
        self.assertLessEqual(len(renderer._layers),6)


class TeamEditorTests(unittest.TestCase):
    def test_editor_route_does_not_consult_student_extension_or_transport(self):
        from rm_client.ui.polar.mixins.config_actions_mixin import ConfigActionsMixin
        class Host(ConfigActionsMixin):
            handle_student_config_action=Mock(return_value=True)
        host=Host()
        with patch('rm_client.ui.match_team_editor.open_match_team_editor') as editor:
            host.handle_config_action('Match Team Identities')
        editor.assert_called_once_with(host)
        host.handle_student_config_action.assert_not_called()

    def test_editor_cancel_and_logo_buttons_do_not_overwrite_typed_names_or_save(self):
        from rm_client.ui.match_team_editor import MatchTeamEditor
        from test_modal_input_epoch import window_fixture
        with window_fixture() as (_case,host,_sink):
            editor=MatchTeamEditor(host)
            try:
                editor.fields['Red'][0].setText('尚未保存学校')
                editor.clear_logo('Red')
                self.assertEqual(editor.fields['Red'][0].text(),'尚未保存学校')
                self.assertFalse(editor.isModal())
                editor.reject()
                self.assertFalse(host.top_match_bar.team_profiles.teams['Red'].school)
            finally:editor.deleteLater()

    def test_editor_owns_input_and_main_close_retires_it_without_an_extra_loop(self):
        from rm_client.ui.match_team_editor import open_match_team_editor
        from test_modal_input_epoch import window_fixture
        with window_fixture() as (_case,host,_sink):
            editor=open_match_team_editor(host)
            self.assertIs(editor,host._match_team_editor)
            self.assertTrue(host._lifecycle_owns_input())
            with patch('rm_client.ui.match_team_editor.MatchTeamEditor') as factory:
                self.assertIs(open_match_team_editor(host),editor)
                factory.assert_not_called()
            host._begin_window_shutdown()
            self.assertIsNone(host._match_team_editor)
            self.assertFalse(editor.isVisible())


if __name__=='__main__':unittest.main()
