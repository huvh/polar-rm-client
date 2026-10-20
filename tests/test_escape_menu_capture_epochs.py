"""Real Qt event routing across Escape-menu page/capture transitions.

The QWidget host uses production mixins; settings and close are inert recorders.
"""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_escape_menu import Host, APP
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


class EscapeMenuCaptureEpochTests(unittest.TestCase):
    def setUp(self):
        self.w = Host()
        self.w.set_escape_menu_visible(True)
        self.settings = Mock()
        replacement = patch.dict(sys.modules, {
            'rm_client.ui.cs2_settings_center': NS(open_settings_center=self.settings),
        })
        replacement.start()
        self.addCleanup(replacement.stop)

    def tearDown(self):
        self.w.hide()
        self.w.deleteLater()
        APP.processEvents()

    def point(self, index):
        return self.w.escape_menu_layout(self.w.width(), self.w.height())[1][index].center().toPoint()

    def press(self, index):
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=self.point(index))

    def release(self, index):
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=self.point(index))

    def key(self, key):
        QTest.keyClick(self.w, key)

    def test_keyboard_confirmation_page_cannot_reuse_settings_mouse_press(self):
        self.press(1)
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return)
        self.assertTrue(self.w._escape_menu_confirm_exit)
        self.release(1)
        self.w.close.assert_not_called()
        self.settings.assert_not_called()

    def test_keyboard_navigation_supersedes_same_page_mouse_capture(self):
        self.press(1)
        self.key(Qt.Key.Key_Down)
        self.release(1)
        self.settings.assert_not_called()

    def test_escape_back_cannot_reuse_confirmation_press_as_settings_click(self):
        self.w.activate_escape_menu_choice(3)
        self.press(1)
        self.key(Qt.Key.Key_Escape)
        self.release(1)
        self.settings.assert_not_called()
        self.w.close.assert_not_called()

    def test_direct_confirmation_and_cancel_transitions_retire_capture(self):
        self.press(1)
        self.w.activate_escape_menu_choice(3)
        self.release(1)
        self.w.close.assert_not_called()
        self.press(1)
        self.w.activate_escape_menu_choice(0)
        self.release(1)
        self.settings.assert_not_called()

    def test_settings_callback_observes_retired_capture(self):
        self.press(1)
        observed = []
        self.settings.side_effect = lambda host: observed.append(host._escape_menu_pressed)
        self.w.activate_escape_menu_choice(1)
        self.assertEqual(observed, [None])
        self.release(1)
        self.settings.assert_called_once_with(self.w)

    def test_fresh_same_page_mouse_and_keyboard_confirmation_still_work(self):
        for _ in range(2):
            self.press(3)
            self.release(3)
            self.assertTrue(self.w._escape_menu_confirm_exit)
            self.press(0)
            self.release(0)
            self.assertFalse(self.w._escape_menu_confirm_exit)
        self.press(1)
        self.release(1)
        self.settings.assert_called_once_with(self.w)
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return)
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return)
        self.w.close.assert_called_once()

    def test_close_reopen_does_not_restore_capture(self):
        self.press(1)
        self.w.set_escape_menu_visible(False)
        self.w.set_escape_menu_visible(True)
        self.release(1)
        self.settings.assert_not_called()


if __name__ == '__main__':
    unittest.main()
