"""Repeated real Qt filter ownership and unchanged F12 safety routing."""
import contextlib
import gc
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import weakref

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from PySide6 import QtMultimedia
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget
from shiboken6 import isValid
from rm_client.ui.emergency_shortcut import install_estop_shortcut
from test_cs2_settings_center import Host as SettingsHost
from rm_client.ui import cs2_settings_center as settings
from rm_client import audio_preferences

APP = QApplication.instance() or QApplication([])


def drain():
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
    gc.collect()


class EmergencyShortcutLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.resources = contextlib.ExitStack()
        self.addCleanup(self.resources.close)
        directory = self.resources.enter_context(tempfile.TemporaryDirectory())
        self.resources.enter_context(patch.dict(os.environ, POLAR_USER_DATA_ROOT=directory))
        self.forbidden = []
        for name in ('QMediaDevices', 'QSoundEffect', 'QMediaPlayer', 'QAudioOutput', 'QAudioSink', 'QAudioSource'):
            if not hasattr(QtMultimedia, name):
                continue
            guard = Mock(side_effect=AssertionError('unexpected native audio: ' + name))
            guard.audioOutputs.side_effect = AssertionError('unexpected device enumeration')
            guard.defaultAudioOutput.side_effect = AssertionError('unexpected default device')
            self.forbidden.append(guard)
            self.resources.enter_context(patch.object(QtMultimedia, name, guard))
            if name == 'QMediaDevices':
                self.resources.enter_context(patch.object(audio_preferences, name, guard))
        for target, name in ((subprocess, 'Popen'), (socket, 'getaddrinfo'),
                             (socket.socket, 'connect'), (socket.socket, 'bind'),
                             (socket.socket, 'sendto')):
            guard = Mock(side_effect=AssertionError('unexpected external boundary: ' + name))
            self.forbidden.append(guard)
            self.resources.enter_context(patch.object(target, name, guard))
        self.host = QWidget()
        self.host.backend = Mock()
        self.host.backend.trigger_estop.return_value = (True, '')
        self.host.control = Mock()
        self.host.toast = Mock()
        self.addCleanup(self.retire_host)

    def retire_host(self):
        self.host.deleteLater()
        drain()
        for guard in self.forbidden:
            self.assertFalse(guard.called)
            self.assertFalse(guard.audioOutputs.called)
            self.assertFalse(guard.defaultAudioOutput.called)

    def dialog(self):
        dialog = QDialog(self.host)
        dialog.estop_shortcut = install_estop_shortcut(dialog, self.host)
        dialog.show()
        APP.processEvents()
        return dialog

    def test_repeated_plain_dialogs_collect_wrappers_after_native_delete(self):
        refs = []
        def cycle():
            dialog = self.dialog()
            refs.append(weakref.ref(dialog))
            refs.append(weakref.ref(dialog.estop_shortcut))
            QTimer.singleShot(0, dialog.reject)
            dialog.exec()
            dialog.deleteLater()
        for _ in range(8):
            cycle(); drain()
            self.assertFalse(self.host.findChildren(QDialog))
            self.assertFalse(any(ref() is not None and isValid(ref()) for ref in refs))
            self.assertTrue(all(ref() is None for ref in refs), 'deleted dialog/filter wrappers were retained')

    def test_repeated_real_settings_entry_collects_wrappers(self):
        host = SettingsHost()
        original = settings.build_settings_center
        refs = []
        def build(parent):
            dialog = original(parent)
            refs.append(weakref.ref(dialog))
            QTimer.singleShot(0, dialog.reject)
            return dialog
        try:
            for _ in range(6):
                # A plain function avoids Mock retaining returned owners/arguments.
                with patch.object(settings, 'build_settings_center', new=build):
                    settings.open_settings_center(host)
                drain()
                self.assertFalse(host.children())
                self.assertTrue(all(ref() is None for ref in refs), 'settings wrapper survived its production finally')
            host.auto_save_config.assert_not_called()
            host.backend.arm_match.assert_not_called()
        finally:
            host.deleteLater(); drain()

    def test_live_child_and_nested_modal_f12_keep_stop_order(self):
        dialog = self.dialog()
        child = QLineEdit(dialog)
        nested = QDialog(dialog)
        nested_child = QLineEdit(nested)
        nested.show()
        order = []
        self.host.backend.trigger_estop.side_effect = lambda: (order.append('stop') or (True, ''))
        self.host.control.reset_inputs.side_effect = lambda: order.append('reset')
        self.host.control.clear_pending.side_effect = lambda: order.append('clear')
        for target in (child, nested_child):
            QTest.keyClick(target, Qt.Key.Key_F12)
        self.assertEqual(order, ['stop', 'reset', 'clear'] * 2)
        self.assertEqual(self.host.toast.call_count, 2)
        self.assertIs(dialog.estop_shortcut.parent(), dialog)

    def test_override_release_and_autorepeat_are_consumed_without_retrigger(self):
        dialog = self.dialog()
        for kind, repeat in ((QEvent.Type.ShortcutOverride, False),
                             (QEvent.Type.KeyRelease, False),
                             (QEvent.Type.KeyPress, True)):
            event = QKeyEvent(kind, Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier, '', repeat)
            event.setAccepted(False)
            self.assertTrue(dialog.estop_shortcut.eventFilter(dialog, event))
            self.assertTrue(event.isAccepted())
        self.host.backend.trigger_estop.assert_not_called()
        self.host.control.reset_inputs.assert_not_called()

    def test_non_f12_non_key_and_hidden_dialog_do_not_consume(self):
        dialog = self.dialog()
        for event in (QEvent(QEvent.Type.User),
                      QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)):
            self.assertFalse(dialog.estop_shortcut.eventFilter(dialog, event))
        dialog.hide()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier)
        self.assertFalse(dialog.estop_shortcut.eventFilter(dialog, event))
        self.host.backend.trigger_estop.assert_not_called()

    def test_finished_removes_application_filter_even_if_dialog_is_reshown(self):
        dialog = self.dialog()
        QTest.keyClick(dialog, Qt.Key.Key_F12)
        self.host.backend.trigger_estop.assert_called_once()
        dialog.reject()
        self.assertTrue(isValid(dialog.estop_shortcut))
        dialog.show(); APP.processEvents()
        QTest.keyClick(dialog, Qt.Key.Key_F12)
        self.host.backend.trigger_estop.assert_called_once()

    def test_backend_failure_still_locks_and_clears_before_warning(self):
        dialog = self.dialog()
        order = []
        def fail_stop():
            order.append('stop')
            raise OSError('inert E-stop failure')
        self.host.backend.trigger_estop.side_effect = fail_stop
        self.host.backend.lock_control.side_effect = lambda reason: order.append('lock')
        self.host.control.reset_inputs.side_effect = lambda: order.append('reset')
        self.host.control.clear_pending.side_effect = lambda: order.append('clear')
        self.host.toast.side_effect = lambda *args, **kwargs: order.append('warning')
        QTest.keyClick(dialog, Qt.Key.Key_F12)
        self.assertEqual(order, ['stop', 'lock', 'reset', 'clear', 'warning'])
        self.assertEqual(self.host.toast.call_args.kwargs, {'kind': 'warning'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
