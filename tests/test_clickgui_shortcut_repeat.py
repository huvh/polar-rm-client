"""Real Qt shortcut repeats must not reopen or dismiss a physical toggle.

The production input/ClickGUI mixins run on a QWidget with inert outputs.
No native display, GPU, audio device or robot is qualified by these checks.
"""
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from test_clickgui_background_dismiss import APP, Host


class ClickGuiShortcutRepeatTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.gui_visible = False

    def tearDown(self):
        self.host.hide()
        self.host.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def key(self, key, *, repeat=False, release=False):
        kind = QEvent.Type.KeyRelease if release else QEvent.Type.KeyPress
        if key == Qt.Key.Key_Shift:
            event = QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier,
                              0x36, 161, 0, '', repeat)
        else:
            event = QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier, '', repeat)
        APP.sendEvent(self.host, event)

    def check_toggle(self, key):
        for expected in (True, False, True, False):
            self.key(key)
            self.assertEqual(self.host.gui_visible, expected)
            for _ in range(4):
                # Some platforms deliver synthetic releases during repeat.
                self.key(key, repeat=True, release=True)
                self.key(key, repeat=True)
                self.assertEqual(self.host.gui_visible, expected)
            self.key(key, release=True)
            self.assertEqual(self.host.gui_visible, expected)
        self.host.control.set_mouse_button.assert_not_called()
        self.host.publish_map_click_from_screen.assert_not_called()

    def test_f8_repeats_do_not_reverse_the_physical_toggle(self):
        self.check_toggle(Qt.Key.Key_F8)

    def test_right_shift_repeats_do_not_reverse_the_physical_toggle(self):
        self.check_toggle(Qt.Key.Key_Shift)


    def test_repeat_keeps_pending_background_release_owned_without_dismissal(self):
        self.key(Qt.Key.Key_F8)
        self.host.build()
        QTest.mousePress(self.host, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        self.assertIsNotNone(self.host._jello_background_press)
        self.key(Qt.Key.Key_F8, repeat=True)
        self.assertTrue(self.host.gui_visible)
        self.assertIsNone(self.host._jello_background_press)
        self.assertTrue(self.host._jello_background_release_owned)
        QTest.mouseRelease(self.host, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        self.assertTrue(self.host.gui_visible)
        self.assertFalse(self.host._jello_background_release_owned)
        self.host.control.set_mouse_button.assert_not_called()
        self.host.publish_map_click_from_screen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
