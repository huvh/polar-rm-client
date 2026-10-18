"""Acquired video/keyboard dialogs retire on injected construction failures.

These are explicit fault-path tests, not reproduced spontaneous field failures.
Actual Qt ownership is exercised with inert backend and control adapters.
"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QDialog, QWidget
from shiboken6 import isValid
import test_cs2_settings_center as fixture
from rm_client.ui import cs2_settings_center as settings
from rm_client.ui import cs2_video_settings as video
from rm_client.ui import jello_keybinds as keyboard
from rm_client.ui import jello_widgets as widgets


def flush():
    fixture.APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    fixture.APP.processEvents()
    fixture.APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class NestedSettingsFactoryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.host = fixture.Host()
        self.host.control = Mock()
        self.sibling = QDialog(self.host)

    def tearDown(self):
        self.host.deleteLater()
        flush()

    def check_retired(self, dialog, children):
        flush()
        self.assertFalse(isValid(dialog))
        self.assertTrue(all(not isValid(child) for child in children))
        self.assertTrue(isValid(self.host))
        self.assertTrue(isValid(self.sibling))
        self.assertEqual(self.host.findChildren(QDialog), [self.sibling])
        self.host.backend.arm_match.assert_not_called()

    def test_embedded_video_failure_does_not_outlive_failed_settings_center(self):
        for _ in range(2):
            captured = []
            error = RuntimeError('injected embedded video styling failure')
            def fail(dialog):
                self.assertEqual(dialog.objectName(), 'JelloVideoSettings')
                captured.append((dialog, dialog.findChildren(QWidget)))
                raise error
            with patch.object(widgets, 'apply_jello_widgets', side_effect=fail):
                with self.assertRaises(RuntimeError) as raised:
                    settings.open_settings_center(self.host)
            self.assertIs(raised.exception, error)
            self.check_retired(*captured[0])

    def test_video_cleanup_preserves_original_error_when_delete_scheduling_fails(self):
        error = RuntimeError('injected video construction failure')
        captured = []
        def fail(dialog):
            captured.append(dialog)
            original = dialog.deleteLater
            def retire_then_fail():
                original()
                raise OSError('injected deletion adapter failure')
            dialog.deleteLater = retire_then_fail
            raise error
        with patch.object(widgets, 'apply_jello_widgets', side_effect=fail):
            with self.assertRaises(RuntimeError) as raised:
                video.open_video_settings(self.host, embedded=True)
        self.assertIs(raised.exception, error)
        self.check_retired(captured[0], [])

    def test_keyboard_factory_failure_retires_only_its_acquired_tree(self):
        for site in ('install_estop_shortcut', 'apply_jello_widgets'):
            for _ in range(2):
                with self.subTest(site=site):
                    captured = []
                    error = RuntimeError('injected keyboard factory failure')
                    def fail(dialog, *args):
                        captured.append((dialog, dialog.findChildren(QWidget)))
                        raise error
                    with patch.object(keyboard, site, side_effect=fail):
                        with self.assertRaises(RuntimeError) as raised:
                            keyboard.open_keyboard_manager(self.host)
                    self.assertIs(raised.exception, error)
                    self.check_retired(*captured[0])

    def test_keyboard_cleanup_preserves_original_error_when_delete_scheduling_fails(self):
        error = RuntimeError('injected keyboard construction failure')
        captured = []
        def fail(dialog):
            captured.append(dialog)
            original = dialog.deleteLater
            def retire_then_fail():
                original()
                raise OSError('injected deletion adapter failure')
            dialog.deleteLater = retire_then_fail
            raise error
        with patch.object(keyboard, 'apply_jello_widgets', side_effect=fail):
            with self.assertRaises(RuntimeError) as raised:
                keyboard.build_keyboard_manager(self.host)
        self.assertIs(raised.exception, error)
        self.check_retired(captured[0], [])

    def test_successful_factories_return_live_owned_dialogs(self):
        dialog = video.open_video_settings(self.host, embedded=True)
        self.assertTrue(isValid(dialog))
        self.assertIs(dialog.parent(), self.host)
        self.assertIn('window_mode', dialog.controls)
        dialog.deleteLater()
        flush()
        dialog = keyboard.build_keyboard_manager(self.host, parent=self.sibling)
        self.assertTrue(isValid(dialog))
        self.assertIs(dialog.parent(), self.sibling)
        self.assertTrue(dialog.session.entries)
        self.assertTrue(isValid(dialog.canvas))
        dialog.deleteLater()
        flush()
        self.assertEqual(self.host.findChildren(QDialog), [self.sibling])


if __name__ == '__main__':
    unittest.main()
