"""独立快捷键的改绑、取消、事务、原版曲线及输入安全。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT),str(ROOT/"tests")]
from PySide6.QtCore import QEvent, Qt, QTimer, QRect, QPoint
from PySide6.QtTest import QTest
from test_cs2_settings_center import APP, Host as BaseHost
from rm_client.ui.polar.mixins.input_dispatch_mixin import InputDispatchMixin
from rm_client.ui.jello_keybinds import build_keyboard_manager, open_keyboard_manager, ALL_KEYS
from rm_client.ui.endfield.keybinds.capture import KeyCapturePopup
from rm_client.ui.endfield.keybinds.resources import ASSETS, highlight_alpha, motion, key_texture
from rm_client.ui.endfield.settings.widgets import SettingsRow
from rm_client.ui.window_shortcuts import WindowShortcuts
from tools.endfield.keybinds.check_assets import validate


class Host(BaseHost):
    key_name = InputDispatchMixin.key_name
    is_right_shift_event = InputDispatchMixin.is_right_shift_event


class KeybindTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host._shortcuts = WindowShortcuts(self.host)
        self.host.show()
        self.dialog = build_keyboard_manager(self.host)
        self.dialog.show()
        QTest.qWait(500)
        self.entry = next(entry for entry in self.dialog.session.entries if entry.identity == ("module","TacticalMap"))

    def tearDown(self):
        self.dialog.hide()
        self.dialog.deleteLater()
        self.host.hide()
        self.host.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_standalone_has_physical_keyboard_without_settings_tabs_or_vertical_rows(self):
        self.assertEqual(self.dialog.objectName(),"EndfieldKeybindManager")
        self.assertFalse(hasattr(self.dialog,"tabs"))
        self.assertFalse(hasattr(self.dialog,"canvas"))
        self.assertFalse(self.dialog.findChildren(SettingsRow))
        self.assertEqual(len(self.dialog.keyboard.keys),84)
        self.assertEqual(self.dialog.function_combo.count(),len(self.dialog.session.entries))
        self.dialog.select_key("RightShift")
        self.assertFalse(self.dialog.bound_buttons[("module","ClickGui")].isEnabled())
        for key in ALL_KEYS:
            self.assertFalse(key_texture(key.name).isNull(),key.name)

    def test_conflict_stays_open_then_valid_capture_changes_only_local_draft(self):
        def input_keys():
            popup = APP.activeModalWidget()
            self.assertIsInstance(popup,KeyCapturePopup)
            QTest.keyClick(popup,Qt.Key.Key_H)
            self.assertFalse(popup._closing)
            self.assertTrue(popup.status.text())
            QTest.keyClick(popup,Qt.Key.Key_F10)
        QTimer.singleShot(350,input_keys)
        self.dialog.capture(self.entry)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"F10")
        self.assertEqual(self.host.registry.get("TacticalMap").keybind,"Tab")
        self.host.auto_save_config.assert_not_called()
        self.host.backend.arm_match.assert_not_called()

    def test_popup_escape_does_not_clear_or_change_binding(self):
        QTimer.singleShot(50,lambda: QTest.keyClick(APP.activeModalWidget(),Qt.Key.Key_Escape))
        self.dialog.capture(self.entry)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"Tab")
        self.assertTrue(self.dialog.isVisible())

    def test_tab_is_captured_for_the_canonical_map_instead_of_moving_focus(self):
        QTimer.singleShot(50,lambda: QTest.keyClick(APP.activeModalWidget(),Qt.Key.Key_Tab))
        self.dialog.capture(self.entry)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"Tab")
        self.assertTrue(self.dialog.isVisible())

    def test_confirm_applies_independent_session_and_return_discards_it(self):
        self.dialog.hide()
        for accept in (False,True):
            def build(host,manager=None,target=None,parent=None):
                dialog = build_keyboard_manager(host,manager,target,parent)
                entry = next(entry for entry in dialog.session.entries if entry.identity == self.entry.identity)
                dialog.session.assign(entry,"F10")
                QTimer.singleShot(50,dialog,dialog.accept if accept else dialog.reject)
                return dialog
            with patch("rm_client.ui.jello_keybinds.build_keyboard_manager",side_effect=build):
                open_keyboard_manager(self.host)
            self.assertEqual(self.host.registry.get("TacticalMap").keybind,"F10" if accept else "Tab")
        self.host.backend.arm_match.assert_not_called()

    def test_search_matches_key_and_clearing_remains_a_draft(self):
        self.dialog.clear(self.entry)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"None")
        self.assertEqual(self.host.registry.get("TacticalMap").keybind,"Tab")
        self.dialog.search.setText("驾驶协议槽 W")
        self.assertEqual(self.dialog.function_combo.count(),1)
        self.assertEqual(self.dialog.current_entry().identity,("RobotLink","Bind W"))
        self.assertEqual(self.dialog.keyboard.matches,{"W"})

    def test_nested_f11_reflows_both_windows_and_f12_dispatches_once(self):
        popup = KeyCapturePopup(self.dialog,self.entry)
        try:
            popup.show()
            QTest.qWait(350)
            QTest.keyClick(popup,Qt.Key.Key_F11)
            QTest.qWait(80)
            self.assertEqual(self.dialog.geometry(),QRect(self.host.mapToGlobal(QPoint()),self.host.size()))
            self.assertEqual(popup.geometry(),QRect(self.dialog.mapToGlobal(QPoint()),self.dialog.size()))
            QTest.keyClick(popup,Qt.Key.Key_F12)
            self.host.backend.trigger_estop.assert_called_once()
            self.assertFalse(popup._closing)
            for name in self.dialog.keyboard.keys:
                self.assertTrue(QRect(self.dialog.keyboard.rect()).contains(self.dialog.keyboard.key_rect(name).toAlignedRect()),name)
        finally:
            popup.hide()
            popup.deleteLater()

    def test_installed_game_assets_and_exact_key_controller_curve(self):
        self.assertGreater(validate(ASSETS),80)
        self.assertEqual(highlight_alpha(0),0)
        self.assertAlmostEqual(highlight_alpha(1/12),64/255,places=5)
        self.assertAlmostEqual(highlight_alpha(1/24),32/255,places=5)
        self.assertAlmostEqual(motion().durations["gamesettingkeycodepopup_in"],17/60,places=5)
        self.assertAlmostEqual(motion().durations["gamesettingkeycodepopup_out"],1/6,places=5)

    def test_physical_keyboard_geometry_and_mouse_hits_survive_all_supported_sizes(self):
        view = self.dialog.keyboard
        for size in ((720,540),(1000,620),(1280,720),(1920,1080),(2560,1440)):
            self.host.resize(*size)
            QTest.qWait(90)
            self.assertEqual(self.dialog.size(),self.host.size())
            for name in view.keys:
                rect = view.key_rect(name)
                self.assertTrue(view.rect().contains(rect.toAlignedRect()),(size,name))
                self.assertEqual(view.key_at(rect.center()),name)
            self.assertGreater(view.key_rect("Space").width(),view.key_rect("A").width()*5)
            self.assertGreater(view.key_rect("Delete").left(),view.key_rect("Enter").right())
            self.assertLess(view.key_rect("Up").top(),view.key_rect("Down").top())
            QTest.mouseClick(view,Qt.MouseButton.LeftButton,pos=view.key_rect("F10").center().toPoint())
            self.assertEqual(view.selected_key,"F10")

    def test_click_bind_clear_and_conflict_use_only_the_current_draft(self):
        view = self.dialog.keyboard
        self.dialog.select_entry(self.entry)
        QTest.mouseClick(view,Qt.MouseButton.LeftButton,pos=view.key_rect("H").center().toPoint())
        QTest.mouseClick(self.dialog.bind_button,Qt.MouseButton.LeftButton)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"Tab")
        QTest.mouseClick(view,Qt.MouseButton.LeftButton,pos=view.key_rect("F10").center().toPoint())
        QTest.mouseClick(self.dialog.bind_button,Qt.MouseButton.LeftButton)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"F10")
        self.assertIn(self.entry.identity,self.dialog.bound_buttons)
        QTest.mouseClick(self.dialog.bound_buttons[self.entry.identity],Qt.MouseButton.LeftButton)
        self.assertEqual(self.dialog.session.values[self.entry.identity],"None")
        self.assertEqual(self.host.registry.get("TacticalMap").keybind,"Tab")
        self.host.auto_save_config.assert_not_called()

    def test_dragging_between_caps_does_not_select_and_physical_q_e_are_visible(self):
        view = self.dialog.keyboard
        first = view.selected_key
        QTest.mousePress(view,Qt.MouseButton.LeftButton,pos=view.key_rect("F10").center().toPoint())
        QTest.mouseRelease(view,Qt.MouseButton.LeftButton,pos=view.key_rect("F9").center().toPoint())
        self.assertEqual(view.selected_key,first)
        view.setFocus()
        for key,name in ((Qt.Key.Key_Q,"Q"),(Qt.Key.Key_E,"E"),(Qt.Key.Key_Tab,"Tab")):
            QTest.keyPress(view,key)
            self.assertIn(name,view.held)
            QTest.keyRelease(view,key)
            self.assertNotIn(name,view.held)


if __name__ == "__main__":
    unittest.main()
