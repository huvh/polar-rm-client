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
from PySide6.QtWidgets import QWidget
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
        for failure_site in ('apply_jello_widgets', 'install_estop_shortcut'):
            for attempt in range(2):
                with self.subTest(site=failure_site, attempt=attempt):
                    error = RuntimeError('late settings construction failed')
                    captured = []
                    def fail(dialog, *args):
                        queues = dialog.findChildren(settings.SettingsBuildQueue)
                        self.assertTrue(queues)
                        for queue in queues:
                            queue.set_active(True)
                        captured.append((dialog, queues, dialog.findChildren(QWidget)))
                        raise error
                    with patch.object(settings, failure_site, side_effect=fail):
                        with self.assertRaises(RuntimeError) as raised:
                            settings.open_settings_center(self.host)
                    self.assertIs(raised.exception, error)
                    dialog, queues, children = captured[0]
                    # Timers must be revoked before returning control to Qt.
                    self.assertTrue(all(q.cancelled and not q.timer.isActive() for q in queues))
                    flush()
                    self.assertFalse(isValid(dialog))
                    self.assertTrue(all(not isValid(child) for child in children))
                    self.assertTrue(isValid(self.host))
                    self.assertTrue(isValid(self.sibling))
                    self.assertFalse(self.host.findChildren(settings.JelloDialog))
        self.host.backend.arm_match.assert_not_called()

    def test_one_cancel_failure_preserves_primary_and_retires_other_owners(self):
        error = ValueError('original construction error')
        captured = []
        def fail(dialog):
            queues = dialog.findChildren(settings.SettingsBuildQueue)
            for queue in queues:
                queue.set_active(True)
            queues[0].cancel = lambda: (_ for _ in ()).throw(OSError('cancel failed'))
            captured.append((dialog, queues))
            raise error
        with patch.object(settings, 'apply_jello_widgets', side_effect=fail):
            with self.assertRaises(ValueError) as raised:
                settings.build_settings_center(self.host)
        self.assertIs(raised.exception, error)
        dialog, queues = captured[0]
        self.assertTrue(all(q.cancelled for q in queues[1:]))
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
