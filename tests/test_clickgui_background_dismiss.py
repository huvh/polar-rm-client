"""Real Qt events and production Jello hit geometry; inert output adapters."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from types import SimpleNamespace as NS, MethodType
from unittest.mock import Mock
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtTest import QTest
from rm_client.model import build_default_registry
from rm_client.ui.jello_clickgui import JelloClickGuiRenderer, JelloClickGuiState
from rm_client.ui.polar.mixins.clickgui_builders_mixin import ClickGuiBuildersMixin, EconomyScenePhase
from test_escape_menu import Host as EscapeHost, APP

class Host(EscapeHost):
    def __init__(self):
        super().__init__()
        self.registry = build_default_registry()
        self.jello_state = JelloClickGuiState()
        self.renderer = JelloClickGuiRenderer(Path('/nonexistent-assets'))
        self.gui_visible = True
        self.gui_scroll_viewports = []
        self.hover_point = QPointF(-1, -1)
        self.drag = None
        self.economy_hold_key = None
        self.handle_student_mouse = lambda *args: False
        self.handle_student_action = lambda *args: False
        self.invalidate_gui_cache = Mock()
        self.publish_map_click_from_screen = Mock(return_value=False)
        self.auto_save_config = Mock()
        self.after_setting_changed = Mock()
        self.prewarm_jello_module_resources = Mock()
        self.close_student_panel = Mock()
        self.hero_deploy_video_cut_active = lambda: False
        self.economy_phase = EconomyScenePhase.CLOSED
        self.cancel_quick_action_wheel = Mock()
        self.overlay_coordinator.request_modal = Mock()
        self.overlay_coordinator.close_modal = Mock()
        self.mode_manager = Mock()
        self.gui_timeline = NS(progress=1.0, target=1.0, visual_factor=lambda: 1.0, set_target=Mock())
        self.active_clickgui_mode = lambda: 'JelloSigma'
        self.set_clickgui_visible = MethodType(ClickGuiBuildersMixin.set_clickgui_visible, self)
    def paintEvent(self, event): pass
    def font(self, key, size):
        font = QFont('Sans Serif'); font.setPointSizeF(size); return font
    def add_hotspot(self, rect, action, payload=None, button=None, tooltip=''):
        self.hotspots.append(NS(rect=rect, action=action, payload=payload, button=button))
    def build(self):
        self.hotspots = []; self.gui_scroll_viewports = []
        self.renderer.build(self, self.jello_state, self.width(), self.height(), 1.0)
    def click(self, point, button=Qt.MouseButton.LeftButton):
        QTest.mouseClick(self, button, pos=point)

class BackgroundDismissTests(unittest.TestCase):
    def setUp(self): self.w = Host(); self.w.build()
    def tearDown(self): self.w.hide(); self.w.deleteLater(); APP.processEvents()
    def key(self, key):
        if key == Qt.Key.Key_Shift:
            # Windows right Shift retains either VK_RSHIFT or its native scan.
            for typ in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
                APP.sendEvent(self.w, QKeyEvent(typ, key, Qt.KeyboardModifier.NoModifier, 0x36, 161, 0))
        else:
            QTest.keyClick(self.w, key)
    def test_blank_left_click_closes_without_control_or_map_output(self):
        self.w.click(QPoint(2,2))
        self.assertFalse(self.w.gui_visible)
        self.w.control.set_mouse_button.assert_not_called()
        self.w.publish_map_click_from_screen.assert_not_called()
    def test_open_before_first_frame_does_not_publish_map_click(self):
        self.w.gui_visible = False
        self.w.hotspots = []
        self.key(Qt.Key.Key_F8)
        self.w.click(QPoint(2,2))
        self.assertTrue(self.w.gui_visible)
        self.w.publish_map_click_from_screen.assert_not_called()
        self.w.control.set_mouse_button.assert_not_called()
    def test_closing_animation_cannot_republish_stale_hotspots(self):
        row = next(h for h in self.w.hotspots if h.action == 'jello_module_press')
        module = self.w.registry.get(row.payload); before = module.enabled
        self.w.click(QPoint(2,2))
        self.w.build()  # fade-out rendering must not republish hit targets
        self.assertEqual(self.w.hotspots, [])
        self.assertEqual(self.w.gui_scroll_viewports, [])
        self.w.click(row.rect.center().toPoint())
        self.assertEqual(module.enabled, before)
        self.assertFalse(self.w.combat_control_input_allowed())
        self.w.control.set_mouse_button.assert_not_called()
        self.w.publish_map_click_from_screen.assert_not_called()
        self.w.gui_timeline.progress = 0.0  # timer tick before the next paint
        self.w.click(row.rect.center().toPoint())
        self.assertEqual(module.enabled, before)
    def test_close_clears_stale_gui_hotspots(self):
        self.assertTrue(self.w.hotspots)
        self.w.click(QPoint(2,2))
        self.assertFalse(self.w.gui_visible)
        self.assertEqual(self.w.hotspots, [])
    def test_blank_right_click_does_not_close(self):
        self.w.click(QPoint(2,2), Qt.MouseButton.RightButton)
        self.assertTrue(self.w.gui_visible)
    def test_panel_header_and_padding_do_not_close_at_multiple_sizes(self):
        for size in ((640,400),(1000,620),(2560,1440)):
            self.w.resize(*size); self.w.build()
            panels = [h.rect for h in self.w.hotspots if h.action == 'jello_noop']
            self.assertEqual(len(panels), 6)
            for rect in panels:
                self.w.click(QPointF(rect.left()+3, rect.top()+3).toPoint())
                self.assertTrue(self.w.gui_visible)
    def test_controls_still_toggle_and_open_settings(self):
        row = next(h for h in self.w.hotspots if h.action == 'jello_module_press' and h.payload != 'HeroLob')
        module = self.w.registry.get(row.payload); before = module.enabled
        self.w.click(row.rect.center().toPoint())
        self.assertNotEqual(module.enabled, before)
        self.assertTrue(self.w.gui_visible)
        self.w.click(row.rect.center().toPoint(), Qt.MouseButton.RightButton)
        self.assertEqual(self.w.jello_state.settings_module, module.name)
    def test_drag_and_cross_boundary_release_do_not_dismiss(self):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=QPoint(30,2))
        self.assertTrue(self.w.gui_visible)
        panel = next(h.rect for h in self.w.hotspots if h.action == 'jello_noop')
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=panel.center().toPoint())
        self.assertTrue(self.w.gui_visible)
        # A release outside from a panel press cannot close it either.
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=QPointF(panel.left()+3,panel.top()+3).toPoint())
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.assertTrue(self.w.gui_visible)
    def test_background_drag_returning_to_origin_does_not_close(self):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        QTest.mouseMove(self.w, QPoint(30,2))
        QTest.mouseMove(self.w, QPoint(2,2))
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.assertTrue(self.w.gui_visible)
    def test_nested_settings_padding_title_and_outside(self):
        self.w.jello_state.open_settings('ClickGui')
        self.w.jello_state.settings_panel_animation.reset(1)
        self.w.jello_state.settings_background_animation.reset(1)
        self.w.build()
        blockers = [h for h in self.w.hotspots if h.action == 'jello_noop']
        for target in blockers[-2:]:
            self.w.click(QPointF(target.rect.left()+2,target.rect.top()+2).toPoint())
            self.assertTrue(self.w.gui_visible)
        self.w.click(QPoint(2,2)); self.assertFalse(self.w.gui_visible)
    def test_slider_press_and_release_outside_do_not_close(self):
        self.w.jello_state.open_settings('ClickGui')
        self.w.jello_state.settings_panel_animation.reset(1)
        self.w.jello_state.settings_background_animation.reset(1)
        self.w.build()
        slider = next(h for h in self.w.hotspots if h.action == 'setting_slider')
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=slider.rect.center().toPoint())
        self.assertEqual(self.w.drag['type'], 'slider')
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.assertTrue(self.w.gui_visible)
        self.assertIsNone(self.w.drag)
        self.w.after_setting_changed.assert_called()
    def test_keyboard_close_while_pressed_still_consumes_release(self):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.key(Qt.Key.Key_F8)
        self.assertFalse(self.w.gui_visible)
        QTest.mouseMove(self.w, QPoint(20,20))
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.w.control.set_mouse_button.assert_not_called()
        self.w.control.add_mouse_motion.assert_not_called()
    def test_keyboard_close_reopen_cancels_older_background_press(self):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.assertIsNotNone(self.w._jello_background_press)
        self.key(Qt.Key.Key_F8); self.key(Qt.Key.Key_F8)
        self.assertIsNone(self.w._jello_background_press)
        self.w.build()
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=QPoint(2,2))
        self.assertTrue(self.w.gui_visible)
    def test_hotkeys_repeat_and_reopen(self):
        for key in (Qt.Key.Key_F8, Qt.Key.Key_Shift):
            for _ in range(3):
                self.w.gui_visible = False
                self.key(key); self.assertTrue(self.w.gui_visible)
                self.w.build(); self.w.click(QPoint(2,2)); self.assertFalse(self.w.gui_visible)
                self.key(key); self.assertTrue(self.w.gui_visible)
                self.key(key); self.assertFalse(self.w.gui_visible)

if __name__ == '__main__': unittest.main()
