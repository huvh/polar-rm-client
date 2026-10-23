"""Endfield presentation contract; safe input behavior stays in existing suites."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtTest import QTest

from test_cs2_settings_center import APP, Host, ready_page
from test_clickgui_background_dismiss import Host as ClickHost
from rm_client.ui.cs2_settings_center import build_settings_center
from rm_client.ui.endfield_clickgui import EndfieldClickGuiRenderer
from rm_client.ui.jello_clickgui import JelloClickGuiRenderer
from rm_client.ui.endfield_settings_theme import (
    EndfieldTabBar, EndfieldCheckBox, EndfieldSettingRow, sample_curve, resources,
    endfield_font, MIN_TEXT_PX,
)

ROOT = Path(__file__).resolve().parents[1]


class ThemeTests(unittest.TestCase):
    def test_windowed_text_keeps_cjk_readability_floor_without_clipping(self):
        from PySide6.QtWidgets import QLabel
        self.assertEqual(endfield_font(9).pixelSize(),MIN_TEXT_PX)
        host=Host();host.resize(1280,720);dialog=build_settings_center(host)
        try:
            dialog.show();QTest.qWait(460)
            page=ready_page(dialog,'音频');QTest.qWait(380)
            for row in dialog.findChildren(EndfieldSettingRow):
                if not row.isVisible():continue
                self.assertGreaterEqual(row.label.font().pixelSize(),MIN_TEXT_PX)
                self.assertGreaterEqual(row.label.height(),row.label.fontMetrics().height())
                self.assertLessEqual(row.label.geometry().right(),row.control.geometry().left())
            self.assertGreaterEqual(dialog.apply_button.font().pixelSize(),MIN_TEXT_PX)
            number=page.audio_controls['master_volume']
            self.assertGreaterEqual(number.spin.height(),number.spin.fontMetrics().height())
            self.assertLessEqual(number.slider.geometry().bottom(),number.height())
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_video_source_list_is_one_column_without_old_scroll_owners(self):
        host=Host();host.resize(1920,1080);dialog=build_settings_center(host)
        try:
            dialog.show();QTest.qWait(460)
            video=dialog.tabs.widget(0)
            mode=video.controls['window_mode'].parentWidget()
            detail=video.controls['video_detail'].parentWidget()
            mode_y=mode.mapTo(video,mode.rect().topLeft()).y()
            detail_y=detail.mapTo(video,detail.rect().topLeft()).y()
            self.assertGreater(detail_y,mode_y+mode.height())
            self.assertGreater(mode.width(),1500)
            # The two source list containers must not share the same origin.
            self.assertIsNot(mode.parentWidget(),detail.parentWidget())
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_host_resize_follows_without_reopening_or_discarding_drafts(self):
        host=Host();host.show();dialog=build_settings_center(host)
        try:
            dialog.show();QTest.qWait(460)
            page=ready_page(dialog,'音频')
            value=page.audio_controls['mute_unfocused'];value.setChecked(not value.isChecked())
            before=value.isChecked();captures=dialog.capture_count
            host.resize(1600,900);QTest.qWait(80)
            self.assertEqual(dialog.size(),host.size())
            self.assertEqual(value.isChecked(),before)
            self.assertEqual(dialog.capture_count,captures)
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_save_failure_remains_visible_in_source_footer(self):
        host=Host();dialog=build_settings_center(host)
        try:
            dialog.show();QTest.qWait(460)
            page=ready_page(dialog,'音频')
            with patch.object(page,'apply_draft',side_effect=OSError('test disk full')):
                dialog.apply_button.click()
            self.assertFalse(dialog.status.isHidden())
            self.assertIn('test disk full',dialog.status.text())
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_resource_failure_precedes_acquiring_dialog_owner(self):
        from PySide6.QtWidgets import QDialog
        host=Host()
        try:
            with patch('rm_client.ui.endfield_settings_theme.resources',side_effect=ValueError('missing source')):
                with self.assertRaisesRegex(ValueError,'missing source'):build_settings_center(host)
            self.assertFalse(host.findChildren(QDialog))
        finally:host.deleteLater();APP.processEvents()

    def test_tab_fade_reversal_retires_old_effect_and_keeps_geometry(self):
        host=Host();dialog=build_settings_center(host)
        try:
            dialog.show();QTest.qWait(460)
            audio=dialog.pages['音频'];other=dialog.pages['游戏']
            dialog.tabs.setCurrentWidget(audio);QTest.qWait(40)
            self.assertIsNotNone(audio.graphicsEffect())
            dialog.tabs.setCurrentWidget(other)
            self.assertIsNone(audio.graphicsEffect())
            QTest.qWait(390)
            self.assertIsNone(other.graphicsEffect())
            self.assertFalse(dialog.page_transition.motion.state().value)
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_esc_backdrop_is_transferred_before_invalidation_and_consumed_once(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from rm_client.ui.endfield_settings_theme import capture_settings_backdrop
        host=Host();source=QImage(12,8,QImage.Format.Format_ARGB32);source.fill(QColor('#485145'))
        host.makeCurrent=Mock();host.doneCurrent=Mock()
        host.gpu_compositor=SimpleNamespace(_treated_blur_valid=True,
            _backdrop_treatment=SimpleNamespace(blur_kernel='endfield_gaussian'),
            treated_blur_fbo=SimpleNamespace(toImage=Mock(return_value=source)))
        try:
            capture_settings_backdrop(host)
            host.gpu_compositor._treated_blur_valid=False
            dialog=build_settings_center(host)
            self.assertEqual(dialog._world_backdrop,source)
            self.assertIsNone(host._endfield_settings_backdrop)
            host.gpu_compositor.treated_blur_fbo.toImage.assert_called_once()
            host.doneCurrent.assert_called_once()
            dialog.close_for_shutdown();dialog.deleteLater();APP.processEvents()
        finally:host.deleteLater();APP.processEvents()

    def test_original_resource_hashes_match(self):
        root = ROOT / "assets/endfield_settings"
        manifest = json.loads((root/"PROVENANCE.json").read_text())
        for name, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected,name)
        self.assertEqual(resources()[1]["icon_settings_audio"].size().width(),80)

    def test_authored_curves_are_not_jello_zoom(self):
        self.assertEqual(sample_curve("gamesetting_in","Main/TopNode","m_AnchoredPosition.y",0),80)
        self.assertAlmostEqual(sample_curve("gamesetting_in","Main/TopNode","m_AnchoredPosition.y",25/60),0,places=4)
        self.assertEqual(sample_curve("gamesetting_out","Main/ContentNode","m_Alpha",.04),1)
        self.assertAlmostEqual(sample_curve("gamesetting_out","Main/ContentNode","m_Alpha",10/60),0,places=4)

    def test_settings_sizes_and_tabs_fit_without_changing_host_mode(self):
        for w,h in ((1280,720),(1600,900),(1920,1080),(2560,1440)):
            host = Host();host.resize(w,h);dialog=build_settings_center(host)
            try:
                dialog.show();QTest.qWait(460)
                self.assertEqual(dialog.size(),host.size())
                self.assertIsInstance(dialog.tabs.tabBar(),EndfieldTabBar)
                bar=dialog.tabs.tabBar()
                self.assertLessEqual(bar.tabRect(5).right(),dialog.width())
                self.assertLessEqual(dialog.tabs.geometry().bottom(),dialog.height())
                self.assertFalse(host.isFullScreen())
                self.assertEqual(dialog.visual_factor(),1)
            finally:
                dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_toggle_is_real_staged_checkbox_and_controls_remain_readable(self):
        host=Host();dialog=build_settings_center(host)
        try:
            page=ready_page(dialog,"音频")
            toggle=page.audio_controls["mute_unfocused"]
            self.assertIsInstance(toggle,EndfieldCheckBox)
            before=toggle.isChecked()
            toggle.setFocus();QTest.keyClick(toggle,Qt.Key_Space)
            self.assertNotEqual(toggle.isChecked(),before)
            self.assertLessEqual(toggle.width(),round(515*dialog.theme_scale)+1)
            self.assertGreater(toggle.fontMetrics().height(),12)
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()

    def test_hybrid_clickgui_keeps_all_hotspots_and_geometry(self):
        host=ClickHost();host.resize(1920,1080)
        try:
            plain=JelloClickGuiRenderer(ROOT/'assets/jello')
            hybrid=EndfieldClickGuiRenderer(ROOT/'assets/jello')
            for module in (None,"HUD","ClickGui"):
                if module:
                    host.jello_state.open_settings(module);host.jello_state.update(.5)
                host.hotspots=[];plain.build(host,host.jello_state,1920,1080,1)
                old=[(x.rect,x.action,x.payload,x.button) for x in host.hotspots]
                host.hotspots=[];commands=hybrid.build(host,host.jello_state,1920,1080,1)
                self.assertEqual(old,[(x.rect,x.action,x.payload,x.button) for x in host.hotspots])
                self.assertTrue(any(r.fill.red()>230 and r.fill.green()>230 and r.fill.blue()<30 for r in commands.rects))
                self.assertFalse(any(r.fill.blue()>240 and r.fill.red()<100 for r in commands.rects))
        finally:host.deleteLater();APP.processEvents()

    def test_resize_does_not_restart_entrance_or_resample_text_at_rest(self):
        host=Host();dialog=build_settings_center(host)
        try:
            dialog.show();QTest.qWait(460)
            self.assertIsNone(dialog._surface)
            count=dialog.capture_count
            dialog.resize(1600,900);APP.processEvents()
            self.assertEqual(dialog.capture_count,count)
            self.assertFalse(dialog._transition_timer.isActive())
        finally:
            dialog.close_for_shutdown();dialog.deleteLater();host.deleteLater();APP.processEvents()


if __name__ == '__main__':unittest.main()
