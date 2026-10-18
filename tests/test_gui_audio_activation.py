"""GUI feedback activation policy through real methods, without audio devices."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.model import build_default_registry
from rm_client.ui.polar.mixins.config_actions_mixin import ConfigActionsMixin
from rm_client.ui.polar.mixins.persistence_mixin import PersistenceMixin
from rm_client.ui.polar_app import PolarRMWindow


class Host(ConfigActionsMixin):
    setting_bool = PolarRMWindow.setting_bool
    setting_mode = PolarRMWindow.setting_mode
    get_setting_number = PersistenceMixin.get_setting_number
    custom_ui_sound_selection = PersistenceMixin.custom_ui_sound_selection

    def __init__(self):
        self.registry = build_default_registry()
        self.ui_audio = SimpleNamespace(gui_feedback=Mock(), preview=Mock(),
                                        module_toggled=Mock(), jello_module_toggled=Mock())
        self.gui_visible = False
        self.reject_pending_configuration_edit = lambda: False
        self.invalidate_gui_cache = Mock()


class GuiAudioActivationTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.audio = self.host.registry.get("AudioFeedback")
        self.audio.get_setting("UI Volume").value = 27
        self.audio.get_setting("Sound Theme").value = "Custom"

    def test_disabled_module_suppresses_normal_gui_feedback(self):
        self.audio.enabled = False
        self.audio.get_setting("Enabled").value = True
        self.host.play_gui_transition_sound("expand")
        self.host.ui_audio.gui_feedback.assert_not_called()

    def test_master_setting_suppresses_normal_gui_feedback(self):
        for enabled in (True, False):
            with self.subTest(module_enabled=enabled):
                self.audio.enabled = enabled
                self.audio.get_setting("Enabled").value = False
                self.host.play_gui_transition_sound("collapse")
                self.host.ui_audio.gui_feedback.assert_not_called()

    def test_absent_module_suppresses_normal_gui_feedback(self):
        with patch.object(self.host.registry, "get", return_value=None):
            self.host.play_gui_transition_sound("success")
        self.host.ui_audio.gui_feedback.assert_not_called()

    def test_enabled_feedback_forwards_exact_kind_volume_and_theme(self):
        self.audio.enabled = True
        self.audio.get_setting("Enabled").value = True
        for kind in ("expand", "collapse", "success", "unknown"):
            with self.subTest(kind=kind):
                self.host.ui_audio.gui_feedback.reset_mock()
                self.host.play_gui_transition_sound(kind)
                self.host.ui_audio.gui_feedback.assert_called_once_with(kind, 27., "Custom")

    def test_explicit_preview_remains_available_when_disabled(self):
        self.audio.enabled = False
        self.audio.get_setting("Enabled").value = False
        self.host._preview_ui_sound("disable")
        self.host.ui_audio.preview.assert_called_once_with(
            "disable", 27., "Custom", self.host.custom_ui_sound_selection(self.audio))

    def test_self_disable_acknowledgement_retains_its_existing_exception(self):
        self.audio.enabled = False
        self.audio.get_setting("Enabled").value = True
        self.audio.get_setting("Module Toggle Sounds").value = True
        self.host.on_module_toggled(self.audio, False, "keyboard")
        self.host.ui_audio.module_toggled.assert_called_once_with(
            False, "keyboard", active=True, volume=27., theme="Custom",
            custom_sounds=self.host.custom_ui_sound_selection(self.audio))
        self.host.ui_audio.module_toggled.reset_mock()
        self.host.on_module_toggled(self.host.registry.get("HUD"), True, "keyboard")
        self.assertFalse(self.host.ui_audio.module_toggled.call_args.kwargs["active"])
        self.host.ui_audio.jello_module_toggled.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
