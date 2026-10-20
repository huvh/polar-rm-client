"""A radial hold gesture cannot survive focus loss or confirm a stale selection.

The real-window fixture makes device startup and audio output inert. Selected
actions and cursor position are doubles; no native focus/display is qualified.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_LOCAL_CAPTURE', '1')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
os.environ.setdefault('CI', 'true')
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFocusEvent
from test_modal_input_epoch import window_fixture
from rm_client.ui.polar.mixins import input_dispatch_mixin
from rm_client.ui import window_shortcuts

@contextmanager
def fixture():
    with window_fixture() as (case, window, sink):
        window.registry.get('QuickActionWheel').keybind = 'Q'
        with patch.object(input_dispatch_mixin, 'QCursor', NS(pos=lambda: QPoint(400, 300))), \
             patch.object(window, 'execute_quick_action') as execute:
            yield case, window, sink, execute


def open_selected(case, window):
    case.key(Qt.Key.Key_Q)
    wheel = window.quick_action_wheel
    assert wheel.active and window.overlay_coordinator.radial_active
    wheel.update_pointer(wheel.center_x - 75, wheel.center_y - 75)
    assert wheel.sectors()[wheel.selected_index].action == 'clickgui'


def focus_out(window):
    window.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))


class RadialFocusTests(unittest.TestCase):
    def assert_retired(self, window):
        self.assertFalse(window.quick_action_wheel.active)
        self.assertFalse(window.overlay_coordinator.radial_active)
        self.assertEqual(window.quick_action_wheel.selected_index, -1)

    def test_focus_loss_retires_only_pending_radial_selection(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            focus_out(window)
            self.assert_retired(window)
            execute.assert_not_called()
            self.assertEqual(window.backend.safety.control_state.value, 'LOCKED')
            self.assertFalse(window.control._dirty)
            self.assertFalse(any(window.control.key_state.values()))
            self.assertTrue(all(frame[1]['keyboard_value'] == 0 for frame in sink.frames))

    def test_late_old_release_never_executes_selection(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            focus_out(window)
            case.key(Qt.Key.Key_Q, release=True)
            execute.assert_not_called()
            self.assert_retired(window)
            self.assertFalse(any(window.control.key_state.values()))

    def test_fresh_press_after_missing_release_starts_new_selection(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            focus_out(window)
            case.key(Qt.Key.Key_Q)
            wheel = window.quick_action_wheel
            self.assertTrue(wheel.active)
            self.assertEqual(wheel.selected_index, -1)
            wheel.update_pointer(wheel.center_x, wheel.center_y - 80)
            case.key(Qt.Key.Key_Q, release=True)
            execute.assert_called_once_with('economy')
            self.assert_retired(window)

    def test_repeat_after_focus_loss_does_not_reopen_or_confirm(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            focus_out(window)
            for _ in range(3):
                case.key(Qt.Key.Key_Q, repeat=True)
                case.key(Qt.Key.Key_Q, release=True, repeat=True)
            self.assert_retired(window)
            execute.assert_not_called()
            case.key(Qt.Key.Key_Q, release=True)
            execute.assert_not_called()

    def test_normal_confirmation_ignores_repeat_release_and_commits_once(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            case.key(Qt.Key.Key_Q, repeat=True, release=True)
            self.assertTrue(window.quick_action_wheel.active)
            execute.assert_not_called()
            case.key(Qt.Key.Key_Q, release=True)
            case.key(Qt.Key.Key_Q, release=True)
            execute.assert_called_once_with('clickgui')
            self.assert_retired(window)

    def test_neutral_publication_reentry_cannot_confirm_old_selection(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            ordinary = window.control.send_from_state
            reentries = []
            def publish(*args, **kwargs):
                reentries.append(True)
                case.key(Qt.Key.Key_Q, release=True)
                return ordinary(*args, **kwargs)
            with patch.object(window.control, 'send_from_state', side_effect=publish):
                focus_out(window)
            self.assertTrue(reentries)
            execute.assert_not_called()
            self.assert_retired(window)
            self.assertEqual(window.backend.safety.control_state.value, 'LOCKED')

    def test_cancel_refresh_reentry_cannot_confirm_old_selection(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            calls = []
            def refresh():
                calls.append(True)
                case.key(Qt.Key.Key_Q, release=True)
            with patch.object(window.frame_scheduler, 'force', side_effect=refresh):
                focus_out(window)
            self.assertTrue(calls)
            execute.assert_not_called()
            self.assert_retired(window)
            self.assertEqual(window.backend.safety.control_state.value, 'LOCKED')

    def test_cancel_refresh_failure_cannot_skip_lock_or_neutral_fallback(self):
        with fixture() as (case, window, sink, execute):
            window.backend.begin_qualification({'kmc_heartbeat'})
            open_selected(case, window)
            with patch.object(window.frame_scheduler, 'force', side_effect=RuntimeError('refresh failed')), \
                 patch.object(window.control, 'release_direct_dt7') as dt7, \
                 patch.object(window.control, 'release_custom_controller') as custom, \
                 patch.object(window.backend.mqtt, 'publish_estop_zero', return_value=(True, '')) as zero, \
                 patch.object(window, 'toast') as toast:
                focus_out(window)
            self.assert_retired(window)
            self.assertEqual(window.backend.safety.control_state.value, 'LOCKED')
            self.assertIsNone(window.backend.safety._qualification)
            self.assertGreaterEqual(dt7.call_count, 1)
            self.assertGreaterEqual(custom.call_count, 1)
            zero.assert_called_once_with()
            self.assertFalse(window.control._dirty)
            self.assertIn('refresh failed', toast.call_args.args[0])
            execute.assert_not_called()

    def test_control_lock_alone_preserves_radial_confirmation(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            window.backend.lock_control('operator lock')
            self.assertTrue(window.quick_action_wheel.active)
            self.assertTrue(window.overlay_coordinator.radial_active)
            self.assertEqual(window.quick_action_wheel.selected_index, 7)
            case.key(Qt.Key.Key_Q, release=True)
            execute.assert_called_once_with('clickgui')

    def test_fullscreen_action_preserves_radial_without_focus_event(self):
        with fixture() as (case, window, sink, execute):
            open_selected(case, window)
            with patch.object(window_shortcuts, 'set_fullscreen') as fullscreen:
                window_shortcuts.toggle_fullscreen(window)
            fullscreen.assert_called_once()
            self.assertTrue(window.quick_action_wheel.active)
            self.assertTrue(window.overlay_coordinator.radial_active)
            self.assertEqual(window.quick_action_wheel.selected_index, 7)
            execute.assert_not_called()

    def test_chat_draft_and_clickgui_remain_open_on_focus_loss(self):
        for owner in ('chat', 'clickgui'):
            with self.subTest(owner=owner), fixture() as (case, window, sink, execute):
                if owner == 'chat':
                    window.open_match_chat()
                    window.match_chat.insert('unsent draft')
                else:
                    window.set_clickgui_visible(True, announce=False, play_sound=False)
                modal = window.overlay_coordinator.modal
                focus_out(window)
                self.assertEqual(window.overlay_coordinator.modal, modal)
                if owner == 'chat':
                    self.assertTrue(window.match_chat.input_open)
                    self.assertEqual(window.match_chat.input_text, 'unsent draft')
                    self.assertTrue(window.overlay_coordinator.chat_input)
                else:
                    self.assertTrue(window.gui_visible)
                self.assertTrue(window.overlay_coordinator.blocks_combat_input)
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
