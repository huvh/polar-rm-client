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
from rm_client.ui import endfield_settings_theme as theme


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

    def inject_video_build_failure(self, error, captured, *, delete_scheduling_fails=False):
        # Embedded video deliberately skips apply_endfield_widgets. This real
        # row factory runs after its scroll content is attached to the acquired
        # dialog; delegate first so the newly built row is owned and checked too.
        insert_row = theme.EndfieldRowsLayout.insertRow
        def fail(layout, index, label, control):
            insert_row(layout, index, label, control)
            self.assertEqual((index, label), (0, '画质预设'))
            dialog = layout.parentWidget()
            while dialog is not None and not isinstance(dialog, QDialog):
                dialog = dialog.parentWidget()
            self.assertIsNotNone(dialog)
            self.assertEqual(dialog.objectName(), 'JelloVideoSettings')
            self.assertIs(dialog.parent(), self.host)
            self.assertIsNot(dialog, self.sibling)
            self.assertTrue(dialog.isAncestorOf(control))
            children = dialog.findChildren(QWidget)
            self.assertTrue(children)
            captured.append((dialog, children))
            if delete_scheduling_fails:
                original = dialog.deleteLater
                def retire_then_fail():
                    original()
                    raise OSError('injected deletion adapter failure')
                dialog.deleteLater = retire_then_fail
            raise error
        return patch.object(theme.EndfieldRowsLayout, 'insertRow', autospec=True, side_effect=fail)

    def test_embedded_video_failure_does_not_outlive_failed_settings_center(self):
        for _ in range(2):
            captured = []
            error = RuntimeError('injected embedded video row construction failure')
            with self.inject_video_build_failure(error, captured) as injection:
                with self.assertRaises(RuntimeError) as raised:
                    settings.open_settings_center(self.host)
            self.assertIs(raised.exception, error)
            injection.assert_called_once()
            self.assertEqual(len(captured), 1)
            self.check_retired(*captured[0])

    def test_video_cleanup_preserves_original_error_when_delete_scheduling_fails(self):
        error = RuntimeError('injected video construction failure')
        captured = []
        with self.inject_video_build_failure(error, captured, delete_scheduling_fails=True) as injection:
            with self.assertRaises(RuntimeError) as raised:
                video.open_video_settings(self.host, embedded=True)
        self.assertIs(raised.exception, error)
        injection.assert_called_once()
        self.assertEqual(len(captured), 1)
        self.check_retired(*captured[0])

    def test_keyboard_factory_failure_retires_only_its_acquired_tree(self):
        for site in ('install_estop_shortcut', 'apply_endfield_widgets'):
            for _ in range(2):
                with self.subTest(site=site):
                    captured = []
                    error = RuntimeError('injected keyboard factory failure')
                    def fail(dialog, *args, **kwargs):
                        self.assertIsInstance(dialog, keyboard.EndfieldDialog)
                        self.assertEqual(dialog.objectName(), 'JelloKeyboardManager')
                        self.assertIs(dialog.parent(), self.host)
                        captured.append((dialog, dialog.findChildren(QWidget)))
                        raise error
                    with patch.object(keyboard, site, autospec=True, side_effect=fail) as injection:
                        with self.assertRaises(RuntimeError) as raised:
                            keyboard.open_keyboard_manager(self.host)
                    self.assertIs(raised.exception, error)
                    injection.assert_called_once()
                    self.assertEqual(len(captured), 1)
                    self.check_retired(*captured[0])

    def test_keyboard_cleanup_preserves_original_error_when_delete_scheduling_fails(self):
        error = RuntimeError('injected keyboard construction failure')
        captured = []
        def fail(dialog, *, scale=None, stylesheet=True):
            self.assertIsInstance(dialog, keyboard.EndfieldDialog)
            self.assertIs(dialog.parent(), self.host)
            captured.append((dialog, dialog.findChildren(QWidget)))
            original = dialog.deleteLater
            def retire_then_fail():
                original()
                raise OSError('injected deletion adapter failure')
            dialog.deleteLater = retire_then_fail
            raise error
        with patch.object(keyboard, 'apply_endfield_widgets', autospec=True, side_effect=fail) as injection:
            with self.assertRaises(RuntimeError) as raised:
                keyboard.build_keyboard_manager(self.host)
        self.assertIs(raised.exception, error)
        injection.assert_called_once()
        self.assertEqual(len(captured), 1)
        self.check_retired(*captured[0])

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
