"""ClickGUI closure retires pending gestures before callbacks or hidden input.

Production routing and Jello geometry run on the existing offscreen QWidget
fixture with inert output adapters. No native display or device is exercised.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from test_clickgui_background_dismiss import Host, APP

class CaptureHost(Host):
    def setting_mode(self, module, name, fallback):
        return fallback

    def get_setting_number(self, module, name, fallback):
        return fallback

    def add_hotspot(self, rect, action, payload=None, button=None, tooltip=''):
        super().add_hotspot(rect, action, payload, button, tooltip)
        # The reused fixture omits this production Hotspot field.
        self.hotspots[-1].tooltip = tooltip

class CaptureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.w = CaptureHost()
        self.w.hover_tooltip = ''
        self.w._startup_last_hover_action = ''
        self.w._control_mouse_point = None
        self.w.build()

    def tearDown(self):
        self.w.hide(); self.w.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def press(self, point):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=point)

    def release(self, point):
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=point)

    def move(self, point, held=True):
        p = QPointF(point)
        APP.sendEvent(self.w, QMouseEvent(QEvent.Type.MouseMove, p, p,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))

    def close_gui(self, route, settings=False):
        if route == 'programmatic':
            self.w.set_clickgui_visible(False)
        elif route == 'right_shift':
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                APP.sendEvent(self.w, QKeyEvent(kind, Qt.Key.Key_Shift,
                    Qt.KeyboardModifier.NoModifier, 0x36, 161, 0, '', False))
        else:
            key = Qt.Key.Key_F8 if route == 'f8' else Qt.Key.Key_Escape
            if settings and route == 'escape':
                QTest.keyClick(self.w, key) # close settings, retain ClickGUI
                self.w.jello_state.update(1.0) # deterministic completed close
                self.assertIsNone(self.w.jello_state.settings_module)
            QTest.keyClick(self.w, key)
        self.assertFalse(self.w.gui_visible)

    def module_row(self):
        return next(h for h in self.w.hotspots
                    if h.action == 'jello_module_press' and h.payload != 'HeroLob')

    def slider(self):
        self.w.jello_state.open_settings('ClickGui')
        self.w.jello_state.settings_panel_animation.reset(1)
        self.w.jello_state.settings_background_animation.reset(1)
        self.w.build()
        return next(h for h in self.w.hotspots if h.action == 'setting_slider')

    def check_module_close(self, route):
        row = self.module_row(); module = self.w.registry.get(row.payload)
        before = module.enabled; point = row.rect.center().toPoint()
        self.press(point)
        self.assertEqual(self.w.drag['type'], 'jello_module')
        self.close_gui(route)
        retained = self.w.drag is not None
        self.w.gui_timeline.progress = 0.0  # release after the exit animation
        self.release(point)
        self.assertEqual(module.enabled, before,
            f'{route}: stale capture={retained}; closed GUI release toggled {module.name}; '
            f'autosaves={self.w.auto_save_config.call_count}')
        self.assertIsNone(self.w.drag)
        self.w.auto_save_config.assert_not_called()
        self.w.control.set_mouse_button.assert_not_called()

    def check_slider_close(self, route):
        row = self.slider(); self.press(row.rect.center().toPoint())
        before = row.payload.value; changes = self.w.after_setting_changed.call_count
        self.close_gui(route, settings=True)
        retained = self.w.drag is not None
        self.w.gui_timeline.progress = 0.0
        self.move(QPoint(2,2)); self.release(QPoint(2,2))
        self.assertEqual(row.payload.value, before,
            f'{route}: stale capture={retained}; hidden slider changed '
            f'{before!r}->{row.payload.value!r}; setting callbacks='
            f'{self.w.after_setting_changed.call_count - changes}')
        self.assertIsNone(self.w.drag)
        self.assertEqual(self.w.after_setting_changed.call_count, changes)
        self.w.control.set_mouse_button.assert_not_called()

    def test_normal_module_click_toggles_once(self):
        row = self.module_row(); module = self.w.registry.get(row.payload)
        before = module.enabled; point = row.rect.center().toPoint()
        self.press(point); self.release(point); self.release(point)
        self.assertNotEqual(module.enabled, before)
        self.w.auto_save_config.assert_called_once()
        self.assertIsNone(self.w.drag)

    def test_open_module_drag_commits_once(self):
        row = self.module_row(); point = row.rect.center().toPoint()
        self.w.minecraft_hud = NS(layout=Mock(return_value=NS(slot_at=lambda p: 3)))
        self.w.assign_minecraft_function_slot = Mock()
        self.press(point); self.move(point + QPoint(20, 20))
        self.assertTrue(self.w.drag['moved'])
        self.release(point + QPoint(20, 20)); self.release(point + QPoint(20,20))
        self.w.assign_minecraft_function_slot.assert_called_once_with(3, str(row.payload))
        self.w.auto_save_config.assert_not_called()
        self.assertIsNone(self.w.drag)

    def test_open_slider_drag_finishes(self):
        row = self.slider(); self.press(row.rect.center().toPoint())
        before = row.payload.value; self.move(QPoint(2,2))
        self.assertNotEqual(row.payload.value, before)
        self.release(QPoint(2,2)); finished = row.payload.value
        self.move(row.rect.bottomRight().toPoint(), held=False)
        self.assertEqual(row.payload.value, finished)
        self.assertIsNone(self.w.drag)

    def test_blank_close_consumes_its_release(self):
        self.press(QPoint(2,2)); self.release(QPoint(2,2))
        self.assertFalse(self.w.gui_visible)
        self.assertFalse(self.w.pointer_interaction.background_release_owned)
        self.w.control.set_mouse_button.assert_not_called()
        self.w.auto_save_config.assert_not_called()

    def test_redundant_open_preserves_active_module_gesture(self):
        row = self.module_row(); point = row.rect.center().toPoint()
        module = self.w.registry.get(row.payload); before = module.enabled
        self.press(point); self.w.set_clickgui_visible(True); self.release(point)
        self.assertNotEqual(module.enabled, before)
        self.w.auto_save_config.assert_called_once()

    def test_close_reopen_does_not_revive_old_module_capture(self):
        row = self.module_row(); point = row.rect.center().toPoint()
        module = self.w.registry.get(row.payload); before = module.enabled
        self.press(point); self.close_gui('f8')
        QTest.keyClick(self.w, Qt.Key.Key_F8); self.w.build()
        self.assertTrue(self.w.gui_visible)
        self.release(point)
        self.assertEqual(module.enabled, before)
        self.w.auto_save_config.assert_not_called()
        # The cancellation owns only the stale release, not a new click.
        self.press(point); self.release(point)
        self.assertNotEqual(module.enabled, before)
        self.w.auto_save_config.assert_called_once()

    def test_close_retires_capture_before_reentrant_modal_callback(self):
        row = self.module_row(); point = row.rect.center().toPoint()
        module = self.w.registry.get(row.payload); before = module.enabled
        self.press(point)
        self.w.overlay_coordinator.close_modal.side_effect = lambda *args: self.release(point)
        self.close_gui('programmatic')
        self.assertEqual(module.enabled, before)
        self.w.auto_save_config.assert_not_called()
        self.assertIsNone(self.w.drag)
        self.w.control.set_mouse_button.assert_not_called()

    def test_already_hidden_close_preserves_other_owner_capture(self):
        self.w.gui_visible = False
        capture = {'type': 'slider', 'setting': object(), 'rect': object()}
        binding = object()
        self.w.pointer_interaction.drag = capture
        self.w.pointer_interaction.binding_module = binding
        self.w.set_clickgui_visible(False)
        self.assertIs(self.w.pointer_interaction.drag, capture)
        self.assertIs(self.w.pointer_interaction.binding_module, binding)
        self.w.auto_save_config.assert_not_called()

    def test_closed_module_drag_cannot_assign_slot(self):
        row = self.module_row(); point = row.rect.center().toPoint()
        self.w.minecraft_hud = NS(layout=Mock(return_value=NS(slot_at=lambda p: 3)))
        self.w.assign_minecraft_function_slot = Mock()
        self.press(point); self.move(point + QPoint(20,20))
        self.assertTrue(self.w.drag['moved'])
        self.close_gui('f8'); self.release(point + QPoint(20,20))
        self.w.assign_minecraft_function_slot.assert_not_called()
        self.w.auto_save_config.assert_not_called()
        self.assertIsNone(self.w.drag)

for route in ('f8', 'right_shift', 'escape', 'programmatic'):
    setattr(CaptureBoundaryTests, f'test_module_close_{route}',
            lambda self, route=route: self.check_module_close(route))
    setattr(CaptureBoundaryTests, f'test_slider_close_{route}',
            lambda self, route=route: self.check_slider_close(route))

if __name__ == '__main__':
    unittest.main(verbosity=2)
