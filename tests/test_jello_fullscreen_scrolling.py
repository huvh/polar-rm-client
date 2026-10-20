"""Real Qt settings/ClickGUI input, no robot or transport output.

Defaults to raster/offscreen. QT_QPA_PLATFORM=windows exercises the same tests
with native windows; GPU compositor acceptance remains a separate suite.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("POLAR_DISABLE_MEDIA_PRELOAD", "1")

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QLabel
from rm_client.ui.jello_scroll import JelloScrollArea
from rm_client.ui.jello_widgets import JelloDialog
from rm_client.ui.window_shortcuts import set_fullscreen
from test_startup_settings_fullscreen import APP, Host
from test_clickgui_background_dismiss import Host as ClickGuiHost


class FullscreenModalTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.resize(900, 650)
        set_fullscreen(self.host, True)
        APP.processEvents()
        self.saved = self.host._fullscreen_restore_geometry
        self.dialog = JelloDialog(self.host)
        self.dialog.resize(800, 580)
        self.dialog.show()
        APP.processEvents()

    def tearDown(self):
        self.dialog.hide()
        self.host.hide()
        self.host.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_opening_and_return_keep_fullscreen_and_restore_geometry(self):
        self.assertTrue(self.host.isFullScreen())
        self.dialog.hide()
        APP.processEvents()
        self.assertTrue(self.host.isFullScreen())
        self.assertEqual(self.host._fullscreen_restore_geometry, self.saved)

    def test_native_demotion_repaired_without_recapturing_normal_geometry(self):
        # Model the native WindowStateChange notification, not an F11 intent.
        self.host.showNormal()
        APP.processEvents()
        APP.processEvents()
        self.assertTrue(self.host.isFullScreen())
        self.assertEqual(self.host._fullscreen_restore_geometry, self.saved)

    def test_explicit_windowed_request_is_not_undone(self):
        set_fullscreen(self.host, False)
        APP.processEvents()
        APP.processEvents()
        self.assertFalse(self.host.isFullScreen())
        self.assertIsNone(self.host._fullscreen_restore_geometry)

    def test_hidden_dialog_cannot_reenter_fullscreen(self):
        self.dialog.hide()
        self.host.showNormal()
        APP.processEvents()
        self.assertFalse(self.host.isFullScreen())

    def test_reentering_fullscreen_while_dialog_open_acquires_new_intent(self):
        set_fullscreen(self.host, False)
        APP.processEvents()
        set_fullscreen(self.host, True)
        APP.processEvents()
        saved = self.host._fullscreen_restore_geometry
        self.host.showNormal()
        APP.processEvents()
        APP.processEvents()
        self.assertTrue(self.host.isFullScreen())
        self.assertEqual(self.host._fullscreen_restore_geometry, saved)

    def test_opening_windowed_dialog_does_not_enable_fullscreen(self):
        self.dialog.hide()
        set_fullscreen(self.host, False)
        self.dialog.show()
        APP.processEvents()
        self.assertFalse(self.host.isFullScreen())

    def test_parent_shutdown_cannot_recreate_fullscreen_window(self):
        from types import SimpleNamespace
        self.host._window_lifecycle = SimpleNamespace(closing=True)
        self.host.showNormal()
        APP.processEvents()
        APP.processEvents()
        self.assertFalse(self.host.isFullScreen())

    def test_minimizing_is_not_reversed_by_dialog_guard(self):
        self.host.showMinimized()
        APP.processEvents()
        APP.processEvents()
        self.assertTrue(self.host.isMinimized())


class SmoothSettingsTests(unittest.TestCase):
    def setUp(self):
        self.area = JelloScrollArea()
        self.area.resize(400, 300)
        self.content = QLabel("Long settings")
        self.content.setMinimumSize(380, 3000)
        self.area.setWidget(self.content)
        self.area.show()
        APP.processEvents()

    def tearDown(self):
        self.area.hide()
        self.area.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def step(self, dt):
        # Advance the real analytical integrator without wall-clock flakiness.
        from unittest.mock import patch
        clock = self.area._last_time + dt
        with patch("rm_client.ui.jello_scroll.time.perf_counter", return_value=clock):
            self.area._tick_scroll()

    def test_wheel_target_moves_continuously_and_accumulates(self):
        self.area.scroll_by(70)
        self.assertEqual(self.area.verticalScrollBar().value(), 0)
        self.step(1 / 144)
        self.assertGreater(self.area._position, 0)
        self.assertLess(self.area._position, 70)
        self.area.scroll_by(70)
        self.assertEqual(self.area._target, 140)
        for _ in range(200):
            self.step(1 / 144)
            if not self.area._scroll_timer.isActive():
                break
        self.assertEqual(self.area.verticalScrollBar().value(), 140)
        self.assertFalse(self.area._scroll_timer.isActive())

    def test_direction_change_does_not_jump(self):
        self.area.verticalScrollBar().setValue(300)
        self.area.scroll_by(200)
        self.step(.06)
        before = self.area._position
        self.area.scroll_by(-400)
        self.assertEqual(self.area._position, before)
        for _ in range(180):
            self.step(1 / 144)
            if not self.area._scroll_timer.isActive():
                break
        self.assertEqual(self.area.verticalScrollBar().value(), 100)

    def test_direct_trackpad_and_scrollbar_drag_cancel_old_motion(self):
        self.area.scroll_by(200)
        self.step(.03)
        before = self.area.verticalScrollBar().value()
        self.area.scroll_by(13, direct=True)
        self.assertEqual(self.area.verticalScrollBar().value(), before + 13)
        self.assertFalse(self.area._scroll_timer.isActive())
        self.area.scroll_by(100)
        self.area.verticalScrollBar().setValue(450)
        self.assertFalse(self.area._scroll_timer.isActive())
        self.assertEqual(self.area._target, 450)

    def test_bounds_hide_and_child_identity(self):
        self.area.scroll_by(100000)
        self.assertEqual(self.area._target, self.area.verticalScrollBar().maximum())
        self.area.hide()
        self.assertFalse(self.area._scroll_timer.isActive())
        self.assertIs(self.area.widget(), self.content)

    def test_viewport_wheel_uses_continuous_scroll_and_accepts_input(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QWheelEvent
        point = QPointF(100, 100)
        event = QWheelEvent(point, point, QPoint(), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        APP.sendEvent(self.area.viewport(), event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.area._target, 70)
        self.assertEqual(self.area.verticalScrollBar().value(), 0)
        self.step(1 / 144)
        self.assertGreater(self.area._position, 0)


class ClickGuiArrowTests(unittest.TestCase):
    def test_visible_arrow_edge_remains_clickable_across_sizes_and_scales(self):
        host = ClickGuiHost()
        self.addCleanup(host.deleteLater)
        for width, height in ((1280,720), (1600,900), (1920,1080), (2560,1440)):
            host.resize(width, height)
            for scale in (.75, 1.0, 1.25, 1.5):
                with self.subTest(size=(width,height),scale=scale):
                    host.gui_visible = True
                    host.registry.get("ClickGui").get_setting("Scale").value = scale
                    host.jello_state.open_settings("ChassisAssist")
                    host.jello_state.settings_panel_animation.reset(1)
                    host.jello_state.settings_background_animation.reset(1)
                    host.build()
                    hit = next(h for h in host.hotspots if h.action == "jello_mode_dropdown")
                    # Exercise the arrow edge, not only a generous central hit.
                    point = QPointF(hit.rect.right() - 1, hit.rect.center().y()).toPoint()
                    host.click(point)
                    self.assertTrue(host.gui_visible)
                    self.assertEqual(host.jello_state.dropdown_key, "ChassisAssist:Follow")
                    self.assertEqual(host.jello_state.dropdown_animation.target, 1)
                    host.control.set_mouse_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
