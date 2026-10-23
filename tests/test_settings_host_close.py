"""Settings retain client input, not the native host's close button."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox
from test_cs2_settings_center import Host, APP
from rm_client.ui.cs2_settings_center import build_settings_center, open_settings_center


class SettingsHostCloseTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.show()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.host.deleteLater()
        APP.sendPostedEvents()
        APP.processEvents()

    def run_dialog(self, dialog, callback):
        errors = []
        def inspect():
            try:
                callback()
            except BaseException as error:
                errors.append(error)
            finally:
                dialog.reject()
        QTimer.singleShot(0, inspect)
        dialog.exec()
        if errors:
            raise errors[0]

    def test_search_does_not_system_modally_disable_host(self):
        dialog = build_settings_center(self.host)
        self.addCleanup(dialog.deleteLater)
        def inspect():
            dialog.search.setFocus()
            dialog.search.setText('鼠标')
            self.assertIsNone(APP.activeModalWidget())
            self.assertFalse(dialog.isModal())
            self.assertIs(self.host._settings_session, dialog)
        self.run_dialog(dialog, inspect)
        self.assertIsNone(self.host._settings_session)

    def test_search_return_does_not_trigger_reset_or_apply(self):
        dialog = build_settings_center(self.host)
        self.addCleanup(dialog.deleteLater)
        def inspect():
            dialog.search.setFocus()
            dialog.search.setText('不存在的项目')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
                QTest.keyClick(dialog.search, Qt.Key_Return)
                QTest.keyClick(dialog.search, Qt.Key_Enter)
            question.assert_not_called()
            self.assertEqual(dialog.timeline.target, 1)
            self.host.auto_save_config.assert_not_called()
        self.run_dialog(dialog, inspect)

    def test_reopening_raises_existing_settings_not_a_second_input_owner(self):
        dialog = build_settings_center(self.host)
        self.addCleanup(dialog.deleteLater)
        def inspect():
            dialog.search.setText('HUD')
            with patch('rm_client.ui.cs2_settings_center.build_settings_center') as factory:
                open_settings_center(self.host)
            factory.assert_not_called()
            self.assertIs(self.host._settings_session, dialog)
            self.assertEqual(dialog.search.text(), 'HUD')
        self.run_dialog(dialog, inspect)

    def test_shutdown_retires_dialog_builders_and_local_loop_without_animation(self):
        dialog = build_settings_center(self.host)
        self.addCleanup(dialog.deleteLater)
        def inspect():
            dialog.search.setText('键位')
            dialog.close_for_shutdown()
            self.assertFalse(dialog.isVisible())
            self.assertFalse(dialog._transition_timer.isActive())
            self.assertTrue(all(page.builder.cancelled for page in (*dialog.pages.values(), dialog.crosshair)))
        self.run_dialog(dialog, inspect)
        self.assertIsNone(self.host._settings_session)
        self.host.backend.arm_match.assert_not_called()

    def test_shutdown_during_show_does_not_enter_an_already_finished_loop(self):
        dialog = build_settings_center(self.host)
        self.addCleanup(dialog.deleteLater)
        show = dialog.show
        rescue = QTimer(dialog)
        rescue.setSingleShot(True)
        rescued = []
        rescue.timeout.connect(lambda: (rescued.append(True), dialog.close_for_shutdown()))
        def show_and_close():
            show()
            dialog.close_for_shutdown()
        rescue.start(100)
        with patch.object(dialog, 'show', side_effect=show_and_close):
            dialog.exec()
        rescue.stop()
        self.assertFalse(rescued)
        self.assertIsNone(self.host._settings_session)

    def test_shutdown_between_build_and_exec_never_shows_new_settings(self):
        dialog = build_settings_center(self.host)
        self.addCleanup(dialog.deleteLater)
        self.host._window_lifecycle = SimpleNamespace(closing=True)
        with patch.object(dialog, 'show') as show:
            self.assertEqual(dialog.exec(), QDialog.DialogCode.Rejected)
        show.assert_not_called()
        self.assertIsNone(getattr(self.host, '_settings_session', None))


class ProductionSettingsCloseTests(unittest.TestCase):
    def enter(self, callback):
        from test_modal_input_epoch import window_fixture
        from window_lifecycle_helpers import close_window_safely
        with window_fixture() as (case, window, sink):
            errors = []
            def inspect():
                dialog = window._settings_session
                try:
                    callback(case, window, dialog, sink)
                except BaseException as error:
                    errors.append(error)
                finally:
                    if dialog.isVisible(): dialog.reject()
            QTimer.singleShot(0, inspect)
            open_settings_center(window)
            self.assertIsNone(window._settings_session)
            if errors:
                raise errors[0]
            if window._window_lifecycle.closing:
                close_window_safely(window, APP)
                self.assertTrue(window._window_close_finalized)
            self.assertFalse(any(window.control.key_state.values()))

    def test_host_close_during_search_uses_production_shutdown(self):
        def inspect(case, window, dialog, sink):
            dialog.search.setText('云台')
            with patch.object(window, '_admit_window_close', return_value=True):
                window.close()
            self.assertTrue(window._window_lifecycle.closing)
            self.assertFalse(dialog.isVisible())
            self.assertFalse(dialog._transition_timer.isActive())
        self.enter(inspect)

    def test_refused_host_close_keeps_settings_and_search_draft(self):
        def inspect(case, window, dialog, sink):
            dialog.search.setText('未保存草稿')
            with patch.object(window, '_admit_window_close', return_value=False):
                window.close()
            self.assertFalse(window._window_lifecycle.closing)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.search.text(), '未保存草稿')
            self.assertIs(window._settings_session, dialog)
        self.enter(inspect)

    def test_client_input_blocked_but_estop_remains_live(self):
        def inspect(case, window, dialog, sink):
            self.assertFalse(window.combat_control_input_allowed())
            before = window.registry.get('TacticalMap').enabled
            for key in (Qt.Key_W, Qt.Key_Tab, Qt.Key_H):
                case.key(key)
            self.assertFalse(window.control.key_state['W'])
            self.assertFalse(window.tactical_map_hold)
            self.assertEqual(window.registry.get('TacticalMap').enabled, before)
            with patch.object(window.backend, 'trigger_estop', return_value=(True, 'test-only')) as stop:
                QTest.keyClick(dialog.search, Qt.Key_F12)
            stop.assert_called_once()
        self.enter(inspect)


if __name__ == '__main__':
    unittest.main()
