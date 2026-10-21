"""Menu action, localization and real scrollable Jello update dialog."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QScrollArea
from test_escape_menu import APP, Host
from rm_client.ui.endfield_dialogs import changelog_text, show_changelog


class ChangelogTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()

    def tearDown(self):
        self.host.hide()
        self.host.deleteLater()
        APP.processEvents()

    def test_menu_action_opens_changelog_instead_of_help(self):
        with patch("rm_client.ui.endfield_dialogs.show_changelog") as show:
            self.host.dispatch_endfield_action(7)
        show.assert_called_once_with(self.host)

    def test_english_and_chinese_describe_implemented_changes_not_a_release(self):
        for chinese, title, disclaimer in ((True, "本地更新", "不代表已发布新版本"),
                                           (False, "Local changes", "not a new release")):
            text = changelog_text(chinese)
            self.assertIn("2026.10.21", text)
            self.assertIn(title, text)
            self.assertIn(disclaimer, text)
            for feature in ("GPU", "HUD", "Jello", "7v7", "3v3", "1v1"):
                self.assertIn(feature, text)

    def test_small_window_has_scrollable_content_and_retains_modal_safety(self):
        for chinese in (True, False):
            with self.subTest(chinese=chinese):
                self.host.resize(640, 360)
                language = "简体中文" if chinese else "English"
                self.host.registry = NS(get=lambda _: NS(get_setting=lambda _: NS(value=language)))
                errors, observations = [], []

                def inspect():
                    dialog = QApplication.activeModalWidget()
                    try:
                        self.assertIsNotNone(dialog)
                        self.assertIn("更新日志" if chinese else "Changelog", dialog.windowTitle())
                        area = dialog.findChild(QScrollArea, "ChangelogBody")
                        self.assertIsNotNone(area)
                        self.assertGreater(area.verticalScrollBar().maximum(), 0)
                        self.assertLessEqual(dialog.width(), self.host.width())
                        self.assertLessEqual(dialog.height(), self.host.height())
                        self.assertIsNotNone(dialog.estop_shortcut)
                        observations.append(True)
                    except BaseException as error:
                        errors.append(error)
                    finally:
                        if dialog is not None:
                            dialog.reject()

                QTimer.singleShot(650, inspect)
                self.assertFalse(show_changelog(self.host))
                self.assertFalse(errors, errors)
                self.assertEqual(observations, [True])
                self.host.backend.lock_control.assert_called_with("menu dialog opened")
                self.host.backend.arm_match_control.assert_not_called()


if __name__ == "__main__":
    unittest.main()
