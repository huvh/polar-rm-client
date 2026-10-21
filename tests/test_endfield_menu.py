"""Modal/semantic contract; inert renderer, no robot, game or GPU required."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from test_escape_menu import APP, Host


class NativeMenu:
    def __init__(self):
        self.requested = False
        self.phase = 0
        self.attempted = self.ready = True
        self.error = ""
        self.action = 0
        self.pointer = Mock()

    def request(self, value, **_kwargs):
        self.requested = value
        self.phase = 1 if value else 2

    def tick(self, **_kwargs):
        action, self.action = self.action, 0
        return action


class EndfieldMenuTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.menu = self.host._endfield_menu = NativeMenu()
        self.host.match_mode_manager = NS(current=NS(key="RMUL3v3"))
        self.host.open_student_panel = Mock()

    def tearDown(self):
        self.host.hide()
        self.host.deleteLater()
        APP.processEvents()

    def test_close_holds_input_until_actual_conceal_ack(self):
        self.host.set_escape_menu_visible(True)
        self.host.set_escape_menu_visible(False)
        self.assertTrue(self.host.escape_menu_visible)
        self.host.advance_endfield_menu()
        self.assertTrue(self.host.escape_menu_visible)
        self.menu.phase = 0
        self.host.advance_endfield_menu()
        self.assertFalse(self.host.escape_menu_visible)
        self.host.handle_control_key_event.assert_not_called()

    def test_action_waits_for_exit_and_is_dispatched_once(self):
        self.host.set_escape_menu_visible(True)
        self.menu.action = 10
        self.host.advance_endfield_menu()
        self.host.open_student_panel.assert_not_called()
        self.menu.phase = 0
        self.host.advance_endfield_menu()
        self.host.advance_endfield_menu()
        self.host.open_student_panel.assert_called_once_with("inventory")

    def test_reopen_cancels_a_retired_route(self):
        self.host.set_escape_menu_visible(True)
        self.menu.action = 10
        self.host.advance_endfield_menu()
        self.host.set_escape_menu_visible(True)
        self.host.advance_endfield_menu()
        self.assertTrue(self.host.escape_menu_visible)
        self.host.open_student_panel.assert_not_called()

    def test_pending_visibility_is_modal_and_failure_can_escape(self):
        self.host.set_escape_menu_visible(True)
        self.menu.phase = 3  # Native request not yet acknowledged.
        self.host.set_escape_menu_visible(False)
        self.assertTrue(self.host.escape_menu_visible)
        self.menu.error = "No device"
        self.host.advance_endfield_menu()
        self.assertFalse(self.host.escape_menu_visible)

    def test_startup_never_opens_menu(self):
        self.host.home_visible = True
        self.host.set_escape_menu_visible(True)
        self.assertFalse(self.menu.requested)

    def test_pointer_uses_the_same_physical_dpi_transform(self):
        self.host.set_escape_menu_visible(True)
        self.host.devicePixelRatioF = lambda: 1.5
        event = NS(position=lambda: QPointF(30, 60), button=lambda: Qt.MouseButton.LeftButton, accept=Mock())
        self.host.handle_escape_menu_mouse(event, "release")
        self.menu.pointer.assert_called_once_with(3, 45.0, 90.0)
        event.accept.assert_called_once()

    def test_menu_keys_never_become_combat_input(self):
        self.host.set_escape_menu_visible(True)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.host.handle_escape_menu_key(event))
        self.menu.pointer.assert_called_once_with(5, 0, 0, 1)
        self.host.handle_control_key_event.assert_not_called()

    def test_hero_action_only_opens_the_existing_interface(self):
        self.host.open_hero_deploy_interface = Mock()
        self.host.dispatch_endfield_action(14)
        self.host.open_hero_deploy_interface.assert_called_once_with()
        self.host.backend.publish_hero_deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
