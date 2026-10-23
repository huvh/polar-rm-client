"""Real Qt settings-factory failure ownership; no devices or native display."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog, QWidget
from shiboken6 import isValid
import test_cs2_settings_center as fixture
from rm_client.ui import cs2_settings_center as settings


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    fixture.APP.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class SettingsFactoryFailureCleanupTests(unittest.TestCase):
    def setUp(self):
        self.host = fixture.Host()
        self.sibling = QWidget(self.host)
        self.addCleanup(self.cleanup_host)

    def cleanup_host(self):
        self.host.deleteLater()
        flush()

    def test_repeated_late_failure_retires_dialog_and_cancels_builders(self):
        for failure_site in ('apply_endfield_widgets', 'install_estop_shortcut'):
            for attempt in range(2):
                with self.subTest(site=failure_site, attempt=attempt):
                    error = RuntimeError('late settings construction failed')
                    captured = []
                    def fail(dialog, *args, **kwargs):
                        # Endfield styling passes the keyword-only scale; the
                        # shortcut site instead receives the host positionally.
                        self.assertIsInstance(dialog, settings.SettingsDialog)
                        self.assertIs(dialog.parent(), self.host)
                        queues = dialog.findChildren(settings.SettingsBuildQueue)
                        self.assertTrue(queues)
                        for queue in queues:
                            queue.set_active(True)
                            self.assertTrue(queue.timer.isActive())
                        captured.append((dialog, queues, dialog.findChildren(QWidget)))
                        raise error
                    with patch.object(settings, failure_site, autospec=True, side_effect=fail) as injection:
                        with self.assertRaises(RuntimeError) as raised:
                            settings.open_settings_center(self.host)
                    self.assertIs(raised.exception, error)
                    injection.assert_called_once()
                    self.assertEqual(len(captured), 1)
                    dialog, queues, children = captured[0]
                    if failure_site == 'apply_endfield_widgets':
                        injection.assert_called_once_with(dialog, scale=dialog.theme_scale)
                    else:
                        injection.assert_called_once_with(dialog, self.host)
                    # Timers must be revoked before returning control to Qt.
                    self.assertTrue(all(q.cancelled and not q.timer.isActive() for q in queues))
                    flush()
                    self.assertFalse(isValid(dialog))
                    self.assertTrue(all(not isValid(child) for child in children))
                    self.assertTrue(isValid(self.host))
                    self.assertTrue(isValid(self.sibling))
                    self.assertFalse(self.host.findChildren(QDialog))
        self.host.backend.arm_match.assert_not_called()

    def test_one_cancel_failure_preserves_primary_and_retires_other_owners(self):
        error = ValueError('original construction error')
        captured = []
        def fail(dialog, *, scale=None, stylesheet=True):
            self.assertIsInstance(dialog, settings.SettingsDialog)
            self.assertIs(dialog.parent(), self.host)
            queues = dialog.findChildren(settings.SettingsBuildQueue)
            self.assertGreater(len(queues), 1)
            for queue in queues:
                queue.set_active(True)
                self.assertTrue(queue.timer.isActive())
            queues[0].cancel = lambda: (_ for _ in ()).throw(OSError('cancel failed'))
            captured.append((dialog, queues))
            raise error
        with patch.object(settings, 'apply_endfield_widgets', autospec=True, side_effect=fail) as injection:
            with self.assertRaises(ValueError) as raised:
                settings.build_settings_center(self.host)
        self.assertIs(raised.exception, error)
        injection.assert_called_once()
        self.assertEqual(len(captured), 1)
        dialog, queues = captured[0]
        self.assertTrue(all(q.cancelled for q in queues[1:]))
        self.assertTrue(all(not q.timer.isActive() for q in queues[1:]))
        flush()
        self.assertFalse(isValid(dialog))
        self.assertTrue(all(not isValid(q) for q in queues))
        self.assertTrue(isValid(self.host))
        self.assertTrue(isValid(self.sibling))

    def test_successful_factory_keeps_dialog_and_drafts_live(self):
        dialog = settings.build_settings_center(self.host)
        self.assertTrue(isValid(dialog))
        self.assertTrue(dialog.pages)
        queues = dialog.findChildren(settings.SettingsBuildQueue)
        self.assertTrue(queues)
        self.assertFalse(any(q.cancelled for q in queues))
        dialog.reject()
        self.assertTrue(all(q.cancelled for q in queues))
        dialog.deleteLater()
        flush()
        self.assertFalse(isValid(dialog))
        self.assertTrue(isValid(self.host))


if __name__ == '__main__':
    unittest.main()
