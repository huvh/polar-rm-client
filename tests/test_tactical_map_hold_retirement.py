"""Actual-window map-hold epochs with inert transport and dialog boundaries."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_modal_input_epoch import window_fixture
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFocusEvent
from rm_client.ui.cs2_settings_center import open_settings_center

KEYS = (Qt.Key.Key_Tab, Qt.Key.Key_J)


def prepare(case, window, key):
    window.registry.get('TacticalMap').keybind = 'J'
    window.registry.get('TacticalMap').enabled = True
    case.key(key)
    if not window.tactical_map_hold:
        raise AssertionError('fresh map gesture was not admitted')


class TacticalMapHoldRetirementTests(unittest.TestCase):
    def test_modal_claim_retires_hold_and_ignores_modal_presses(self):
        transitions = (
            ('clickgui', lambda w: w.set_clickgui_visible(True, announce=False, play_sound=False),
             lambda w: w.set_clickgui_visible(False, announce=False, play_sound=False)),
            ('chat', lambda w: w.open_match_chat(), lambda w: w.close_match_chat()),
            ('student', lambda w: w.open_student_panel('damage'),
             lambda w: w.close_student_panel(immediate=True)),
            ('escape', lambda w: w.set_escape_menu_visible(True),
             lambda w: w.set_escape_menu_visible(False)),
        )
        for name, enter, leave in transitions:
            for key in KEYS:
                with self.subTest(modal=name, key=key), window_fixture() as (case, w, sink):
                    prepare(case, w, key)
                    observed = []
                    original = w.control.reset_inputs
                    def reset():
                        observed.append(w.tactical_map_hold)
                        case.key(key)  # modal cleanup owns reentrant input
                        observed.append(w.tactical_map_hold)
                        original()
                    with patch.object(w.control, 'reset_inputs', side_effect=reset):
                        enter(w)
                    self.assertTrue(observed)
                    self.assertFalse(any(observed))
                    case.key(key, release=True)
                    case.key(key)
                    self.assertFalse(w.tactical_map_hold)
                    case.key(key, release=True)
                    leave(w)
                    self.assertFalse(w.tactical_map_hold)
                    with patch.object(w.backend, 'publish_map_click_cmd') as publish:
                        self.assertFalse(w.publish_map_click_from_screen(QPointF(20, 20)))
                        publish.assert_not_called()
                    case.key(key)
                    self.assertTrue(w.tactical_map_hold)
                    case.key(key, release=True)
                    self.assertFalse(w.tactical_map_hold)

    def test_focus_and_lock_retire_before_reentrant_callbacks(self):
        for boundary in ('focus', 'lock'):
            for key in KEYS:
                with self.subTest(boundary=boundary, key=key), window_fixture() as (case, w, sink):
                    prepare(case, w, key)
                    observed = []
                    original = w.control.reset_inputs
                    def reset():
                        observed.append(w.tactical_map_hold)
                        # Focus loss also calls release_all after this hook finishes;
                        # only the active lock hook owns the cleanup reentry here.
                        if getattr(w, '_lock_input_clearing', False):
                            case.key(key)
                        observed.append(w.tactical_map_hold)
                        original()
                    with patch.object(w.control, 'reset_inputs', side_effect=reset):
                        if boundary == 'focus':
                            w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
                        else:
                            w.backend.lock_control('test map epoch')
                    self.assertTrue(observed)
                    self.assertFalse(any(observed))
                    case.key(key, release=True)
                    self.assertFalse(w.tactical_map_hold)
                    case.key(key)
                    self.assertTrue(w.tactical_map_hold)
                    case.key(key, release=True)
                    self.assertFalse(w.tactical_map_hold)

    def test_settings_open_and_close_cannot_restore_previous_hold(self):
        for key in KEYS:
            with self.subTest(key=key), window_fixture() as (case, w, sink):
                prepare(case, w, key)
                dialog = Mock()
                observed = []
                dialog.exec.side_effect = lambda: observed.append(w.tactical_map_hold)
                with patch('rm_client.ui.cs2_settings_center.build_settings_center', return_value=dialog):
                    open_settings_center(w)
                self.assertEqual(observed, [False])
                self.assertFalse(w.tactical_map_hold)
                dialog.deleteLater.assert_called_once()
                case.key(key, release=True)
                case.key(key)
                self.assertTrue(w.tactical_map_hold)
                case.key(key, release=True)
                self.assertFalse(w.tactical_map_hold)


if __name__ == '__main__':
    unittest.main()
