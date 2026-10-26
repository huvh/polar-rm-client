"""设置打开期间，F11和视频显示模式切换都必须同步父窗口内容区。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT),str(ROOT/"tests")]

from PySide6.QtCore import QPoint, QRect, Qt, QEvent
from PySide6.QtTest import QTest
from test_cs2_settings_center import APP, Host, ready_page
from rm_client.ui.cs2_settings_center import build_settings_center
from rm_client.ui.cs2_video_settings import apply_window_settings,VideoPreferences
from rm_client.ui.jello_keybinds import build_keyboard_manager
from rm_client.ui.window_shortcuts import WindowShortcuts,set_fullscreen
from rm_client.ui.endfield.settings.widgets import SettingsRow


class SettingsGeometryTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.setGeometry(70,90,1225,704)
        self.host._shortcuts = WindowShortcuts(self.host)
        self.host.show()
        self.dialogs = []
        APP.processEvents()

    def tearDown(self):
        for dialog in reversed(self.dialogs):
            dialog.hide()
            dialog.deleteLater()
        self.host.hide()
        self.host.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def open(self):
        dialog = build_settings_center(self.host)
        self.dialogs.append(dialog)
        dialog.show()
        QTest.qWait(550)
        return dialog

    def assert_fits(self, dialog, host=None):
        host = host or self.host
        QTest.qWait(60)
        target = QRect(host.mapToGlobal(QPoint()),host.size())
        self.assertEqual(dialog.geometry(),target)
        self.assertEqual(dialog.panel.size(),host.size())

    def test_open_windowed_then_f11_fullscreen_and_back(self):
        original = self.host.geometry()
        dialog = self.open()
        self.assert_fits(dialog)
        QTest.keyClick(dialog.search,Qt.Key.Key_F11)
        self.assertTrue(self.host.isFullScreen())
        self.assert_fits(dialog)
        QTest.keyClick(dialog.search,Qt.Key.Key_F11)
        self.assertFalse(self.host.isFullScreen())
        self.assertEqual(self.host.geometry(),original)
        self.assert_fits(dialog)

    def test_open_fullscreen_then_f11_windowed_and_back(self):
        set_fullscreen(self.host,True)
        dialog = self.open()
        self.assert_fits(dialog)
        QTest.keyClick(dialog.search,Qt.Key.Key_F11)
        self.assertFalse(self.host.isFullScreen())
        self.assert_fits(dialog)
        QTest.keyClick(dialog.search,Qt.Key.Key_F11)
        self.assertTrue(self.host.isFullScreen())
        self.assert_fits(dialog)

    def test_video_mode_and_resolution_changes_keep_same_dialog_and_draft(self):
        dialog = self.open()
        page = ready_page(dialog,"键盘 / 鼠标")
        field = page.controls[("RobotLink","Mouse Sensitivity")]
        field.spin.setValue(1.75)
        apply_window_settings(self.host,VideoPreferences(window_mode="Borderless"))
        self.assert_fits(dialog)
        apply_window_settings(self.host,VideoPreferences(window_mode="Windowed",resolution="1280×720"))
        self.assert_fits(dialog)
        self.assertIs(page.controls[("RobotLink","Mouse Sensitivity")],field)
        self.assertEqual(field.spin.value(),1.75)
        self.host.auto_save_config.assert_not_called()
        self.host.backend.arm_match.assert_not_called()

    def test_host_move_resize_and_nested_key_dialog_follow_client_area(self):
        dialog = self.open()
        page = ready_page(dialog,"键盘 / 鼠标")
        editor = build_keyboard_manager(self.host,page,parent=dialog)
        self.dialogs.append(editor)
        editor.show()
        QTest.qWait(500)
        self.host.setGeometry(130,150,1100,650)
        self.assert_fits(dialog)
        self.assert_fits(editor,dialog)
        self.host.resize(1500,900)
        self.assert_fits(dialog)
        self.assert_fits(editor,dialog)

    def test_hidden_dialog_does_not_get_resized_or_reopened_by_host(self):
        dialog = self.open()
        dialog.hide()
        before = dialog.geometry()
        self.host.resize(1400,800)
        QTest.qWait(60)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.geometry(),before)

    def test_large_client_resize_reflows_controls_and_restores_window_layout(self):
        dialog = self.open()
        page = ready_page(dialog,"键盘 / 鼠标")
        for width,height in ((2560,1600),(1000,620),(1920,1080),(1225,704)):
            self.host.resize(width,height)
            self.assert_fits(dialog)
            for row in page.findChildren(SettingsRow):
                self.assertTrue(row.rect().contains(row.control.geometry()),row.label.text())
            self.assertTrue(dialog.header.rect().contains(dialog.navigation.geometry()))

    def test_settings_cover_new_bounds_before_parent_resize_handler_can_paint(self):
        dialog = self.open()
        original = self.host.resizeEvent
        samples = []

        def resize(event):
            target = QRect(self.host.mapToGlobal(QPoint()),self.host.size())
            samples.append(dialog.geometry() == target)
            # 父窗口此刻可以同步paintGL；布局工作必须留到设置覆盖之后。
            scale.assert_not_called()
            original(event)

        self.host.resizeEvent = resize
        with patch.object(dialog,"apply_layout_scale",wraps=dialog.apply_layout_scale) as scale:
            self.host.resize(1920,1080)
            self.assertEqual(samples,[True])
        self.assert_fits(dialog)

    def test_resizing_does_not_restyle_hidden_pages_and_next_tab_gets_current_scale(self):
        dialog = self.open()
        keyboard = ready_page(dialog,"键盘 / 鼠标")
        dialog.tabs.setCurrentIndex(0)
        QTest.qWait(380)
        previous = keyboard.styleSheet()
        self.host.resize(1920,1080)
        self.assert_fits(dialog)
        self.assertEqual(keyboard.styleSheet(),previous)
        dialog.tabs.setCurrentWidget(keyboard)
        QTest.qWait(60)
        self.assertNotEqual(keyboard.styleSheet(),previous)
        for row in keyboard.findChildren(SettingsRow):
            self.assertTrue(row.rect().contains(row.control.geometry()),row.label.text())

    def test_rapid_fullscreen_roundtrips_before_deferred_reflow_keep_cover_and_draft(self):
        dialog = self.open()
        page = ready_page(dialog,"键盘 / 鼠标")
        field = page.controls[("RobotLink","Mouse Sensitivity")]
        field.spin.setValue(1.75)
        for _ in range(4):
            QTest.keyClick(dialog,Qt.Key.Key_F11)
            self.assertEqual(dialog.geometry(),QRect(self.host.mapToGlobal(QPoint()),self.host.size()))
        self.assertFalse(self.host.isFullScreen())
        self.assert_fits(dialog)
        self.assertEqual(field.spin.value(),1.75)
        self.assertIsNone(dialog._resize_surface)
        for row in page.findChildren(SettingsRow):
            self.assertTrue(row.rect().contains(row.control.geometry()),row.label.text())

    def test_hidden_during_pending_resize_cancels_reflow(self):
        dialog = self.open()
        self.host.resize(1920,1080)
        dialog.hide()
        with patch.object(dialog,"apply_layout_scale") as scale:
            QTest.qWait(80)
            scale.assert_not_called()
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(dialog._resize_surface)

    def test_resize_keeps_keyboard_focus_on_the_same_editor(self):
        dialog = self.open()
        dialog.activateWindow()
        dialog.search.setFocus()
        QTest.qWait(20)
        self.assertTrue(dialog.search.hasFocus())
        self.host.resize(1920,1080)
        self.assert_fits(dialog)
        self.assertTrue(dialog.search.hasFocus())


if __name__ == "__main__":
    unittest.main()
