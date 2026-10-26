"""真实设置模态的三个关闭入口都只退回原生Esc父菜单。"""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT),str(ROOT/"tests"),str(ROOT/"tests/endfield")]
from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from test_startup_settings_fullscreen import APP, Host
from test_endfield_menu import NativeMenu
from rm_client.ui import cs2_settings_center as settings


class SettingsReturnTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.resize(1225,704)
        self.host.home_visible = False
        self.host.hotspots = []
        self.host.match_mode_manager = NS(current=NS(key="RMUC7v7"))
        self.menu = self.host._endfield_menu = NativeMenu()
        self.host.set_escape_menu_visible(True)

    def tearDown(self):
        self.host.hide()
        self.host.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_return_close_and_escape_preserve_menu_without_arming_or_saving(self):
        for outcome in ("back","close","escape"):
            with self.subTest(outcome=outcome):
                loop = QEventLoop()
                failures, observed = [], []
                original_build = settings.build_settings_center
                original_dispatch = self.host.dispatch_endfield_action

                def build(host):
                    dialog = original_build(host)
                    def dismiss():
                        try:
                            self.assertTrue(host.escape_menu_visible)
                            self.assertTrue(self.menu.requested)
                            self.assertIs(APP.activeModalWidget(),dialog)
                            with patch.object(self.menu,"tick",wraps=self.menu.tick) as tick:
                                host.advance_endfield_menu()
                                self.assertTrue(tick.call_args.kwargs["paused"])
                            observed.append(outcome)
                            if outcome == "back":
                                back = next(button for button in dialog.panel.findChildren(
                                    QPushButton,options=Qt.FindChildOption.FindDirectChildrenOnly)
                                            if button.text() == "返回")
                                QTest.mouseClick(back,Qt.MouseButton.LeftButton)
                            elif outcome == "close":
                                QTest.mouseClick(dialog.close_button,Qt.MouseButton.LeftButton)
                            else:
                                QTest.keyClick(dialog.search,Qt.Key.Key_Escape)
                        except BaseException as error:
                            failures.append(error)
                            dialog.reject()
                    QTimer.singleShot(600,dialog,dismiss)
                    def timeout():
                        failures.append(AssertionError("Settings did not close"))
                        dialog.reject()
                    QTimer.singleShot(5000,dialog,timeout)
                    return dialog

                def dispatch(action):
                    try:
                        original_dispatch(action)
                    except BaseException as error:
                        failures.append(error)
                    finally:
                        loop.quit()

                with patch.object(settings,"build_settings_center",side_effect=build), \
                     patch.object(self.host,"dispatch_endfield_action",side_effect=dispatch):
                    self.menu.action = 2
                    self.host.advance_endfield_menu()
                    loop.exec()
                if failures:
                    raise failures[0]
                self.assertEqual(observed,[outcome])
                self.assertTrue(self.menu.requested)
                self.assertTrue(self.host.escape_menu_visible)
                self.assertFalse(self.host._endfield_settings_pending)
                self.assertFalse(self.host.home_visible)
                self.host.backend.arm_match.assert_not_called()
                self.host.auto_save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
