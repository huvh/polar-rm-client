"""New-tree offline preset/diagnostic tests, plus stopped offscreen UI reload.

Serial discovery/open and MQTT/UDP starts are patched. No hardware qualification.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.config_store import ClientConfigStore, apply_registry_config, validate_client_config
from rm_client.configuration.official_profile import (
    REVIEWED_CLIENT, REVIEWED_ENGINE, SAFE_PRESET_NAME, diagnose_official_profile,
)
from rm_client.module_catalog import CatalogChoices, assemble_registry, default_modules
from rm_client.referee_profiles import DEFAULT_PROFILE, V2_PROFILE, supported_profiles
from rm_client.scenarios import ScenarioManager
PRESET = ROOT / "configs" / f"{SAFE_PRESET_NAME}.json"


def registry():
    return assemble_registry(default_modules(CatalogChoices(
        ("OfficialEvent", "CampusSimulation", "LabDebug"), ("RMUC7v7", "RMUL3v3"),
        ("Hero", "Engineer", "Infantry"), DEFAULT_PROFILE, supported_profiles(),
        ("Stub",), ("Stub",), ("Auto", "Stub"), ("Auto",), ("Auto",),
    )))


def configured(profile):
    return {"version": 1, "modules": {"MQTTLink": {"settings": {"Referee Profile": profile}}}}


class OfficialProfilePresetTests(unittest.TestCase):
    def setUp(self):
        self.preset = json.loads(PRESET.read_text(encoding="utf-8"))
        self.registry = registry()

    def test_preset_uses_real_setting_ids_and_accepted_values(self):
        validate_client_config(self.preset, self.registry)
        for name, payload in self.preset["modules"].items():
            module = self.registry.get(name)
            self.assertIsNotNone(module, name)
            for key, value in payload.get("settings", {}).items():
                setting = module.get_setting(key)
                self.assertIsNotNone(setting, (name, key))
                if setting.kind == "mode":
                    self.assertIn(value, setting.options, (name, key))

    def test_actual_import_and_loader_leave_old_and_startup_files_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ClientConfigStore(Path(directory))
            store.save("default", configured(DEFAULT_PROFILE))
            store.save_startup_preferences("default", True)
            paths = (store.profile_path("default"), Path(directory) / ".startup.json")
            before = [p.read_bytes() for p in paths]
            name = store.import_file(PRESET, registry=self.registry)
            self.assertEqual(name, SAFE_PRESET_NAME)
            apply_registry_config(self.registry, store.load(name))
            self.assertEqual([p.read_bytes() for p in paths], before)
        self.assertEqual(self.registry.get("MQTTLink").get_setting("Referee Profile").value, V2_PROFILE)
        self.assertEqual(self.registry.get("Scenario").get_setting("Mode").value, "LabDebug")

    def test_import_over_previous_live_intent_closes_outputs_without_enabling(self):
        events = []
        for name, payload in self.preset["modules"].items():
            module = self.registry.get(name)
            module.enabled = True
            for key, value in payload.get("settings", {}).items():
                if type(value) is bool:
                    module.get_setting(key).value = not value
        for module in self.registry.modules:
            module.on_enable = lambda name=module.name: events.append((name, True))
            module.on_disable = lambda name=module.name: events.append((name, False))
        apply_registry_config(self.registry, self.preset)
        for name, payload in self.preset["modules"].items():
            module = self.registry.get(name)
            if "enabled" in payload:
                self.assertFalse(module.enabled)
            for key, value in payload.get("settings", {}).items():
                self.assertEqual(module.get_setting(key).value, value, (name, key))
        self.assertTrue(events)
        self.assertTrue(all(event[-1] is False for event in events))

    def test_staging_has_no_auto_port_camera_or_remote_network_target(self):
        apply_registry_config(self.registry, self.preset)
        for name, key in (("RobotLink", "Port"), ("SerialBridge", "Port"),
                          ("ControllerAngles", "Angle RX Port"), ("ControllerAngles", "Angle TX Port")):
            self.assertEqual(self.registry.get(name).get_setting(key).value, "Stub")
        self.assertEqual(self.registry.get("CameraFeed").get_setting("Source").value, "Synthetic")
        self.assertEqual(self.registry.get("MQTTLink").get_setting("Host").value, "127.0.0.1")
        for name, key in (("MQTTLink", "Auto Connect"), ("ConfigManager", "Load On Start"), ("ConfigManager", "Auto Save")):
            self.assertFalse(self.registry.get(name).get_setting(key).value)

    def test_explicit_later_official_scenario_preserves_v2_without_robot_drive(self):
        apply_registry_config(self.registry, self.preset)
        ScenarioManager("OfficialEvent").apply_to_registry(self.registry)
        self.assertEqual(self.registry.get("MQTTLink").get_setting("Referee Profile").value, V2_PROFILE)
        self.assertEqual(self.registry.get("MQTTLink").get_setting("Host").value, "192.168.12.1")
        self.assertFalse(self.registry.get("RobotLink").enabled)
        self.assertFalse(self.registry.get("RobotLink").get_setting("Allow Drive").value)
        self.assertFalse(self.registry.get("EconomyPanel").get_setting("Mock Requests").value)

    def test_v1_identity_and_existing_config_are_not_silently_migrated(self):
        self.assertEqual(DEFAULT_PROFILE, "rm2026-v1.3.1")
        data = configured(DEFAULT_PROFILE); before = deepcopy(data)
        self.assertEqual(diagnose_official_profile(data, client_version=REVIEWED_CLIENT).status, "PROFILE_MISMATCH")
        self.assertEqual(data, before)
        apply_registry_config(self.registry, data)
        self.assertEqual(self.registry.get("MQTTLink").get_setting("Referee Profile").value, DEFAULT_PROFILE)

    def test_reviewed_schema_match_is_never_pairing_or_hardware_qualification(self):
        result = diagnose_official_profile(self.preset, client_version=REVIEWED_CLIENT, engine_version=REVIEWED_ENGINE)
        self.assertTrue(result.profile_matches)
        self.assertEqual(result.expected_profile, V2_PROFILE)
        self.assertEqual(result.engine_status, "REVIEWED_V2_SUCCESSOR_NOT_PAIR_VALIDATED")
        self.assertFalse(result.pairing_verified)
        self.assertFalse(result.hardware_qualified)

    def test_unknown_versions_and_profile_aliases_are_not_guessed(self):
        for version in ("12.0.0.214", "12.0.0.212", "213", " 12.0.0.213", ""):
            result = diagnose_official_profile(self.preset, client_version=version)
            self.assertEqual(result.status, "UNVERIFIED_VERSION")
            self.assertIsNone(result.expected_profile)
        result = diagnose_official_profile(self.preset, client_version=REVIEWED_CLIENT, engine_version="unknown")
        self.assertEqual(result.engine_status, "UNVERIFIED_VERSION")
        for profile in ("rm2026-v2", "future-profile"):
            self.assertEqual(diagnose_official_profile(configured(profile), client_version=REVIEWED_CLIENT).status, "UNSUPPORTED_PROFILE")

    def test_omitted_profile_does_not_guess_registry_default(self):
        result = diagnose_official_profile({"version": 1}, client_version=REVIEWED_CLIENT)
        self.assertEqual(result.status, "PROFILE_UNRESOLVED")
        self.assertIsNone(result.selected_profile)

    def test_malformed_input_cannot_report_matching(self):
        for data in ({"modules": []}, {"modules": {"MQTTLink": {"enabled": "false"}}},
                     {"version": 1, "unused": float("nan")}):
            with self.assertRaises(ValueError):
                diagnose_official_profile(data, client_version=REVIEWED_CLIENT)

    def test_cli_exit_codes_and_read_only_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "client.json"
            for profile, client, engine, code in (
                (V2_PROFILE, REVIEWED_CLIENT, REVIEWED_ENGINE, 0),
                (DEFAULT_PROFILE, REVIEWED_CLIENT, REVIEWED_ENGINE, 2),
                (V2_PROFILE, "unknown", REVIEWED_ENGINE, 3),
                (V2_PROFILE, REVIEWED_CLIENT, "unknown", 3),
            ):
                path.write_text(json.dumps(configured(profile))); before = path.read_bytes()
                result = subprocess.run([sys.executable, str(ROOT / "tools/check_official_profile.py"),
                    "--config", str(path), "--client-version", client, "--engine-version", engine],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertFalse(json.loads(result.stdout)["hardware_qualified"])
                self.assertFalse(json.loads(result.stdout)["pairing_verified"])
                self.assertEqual(path.read_bytes(), before)

    def test_missing_config_is_explicit_error(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/check_official_profile.py"),
            "--config", str(ROOT / "configs/nonexistent-offline-fixture.json"), "--client-version", REVIEWED_CLIENT],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "INVALID_CONFIG")

    def test_portable_script_ships_manifested_template_not_user_config(self):
        script = (ROOT / "tools/build_release.ps1").read_text(encoding="utf-8")
        copy = 'Copy-Item -LiteralPath (Join-Path $sourceRoot "configs\\official_213_v2_safe.json") -Destination (Join-Path $portable "defaults\\official_213_v2_safe.json") -Force'
        manifest = '"defaults/official_213_v2_safe.json" = (Get-FileHash (Join-Path $portable "defaults\\official_213_v2_safe.json") -Algorithm SHA256).Hash'
        self.assertEqual(script.count(copy), 1)
        self.assertEqual(script.count(manifest), 1)
        self.assertNotIn('user_data\\configs\\official_213_v2_safe.json', script)
        self.assertNotIn(SAFE_PRESET_NAME, (ROOT / "rm_client/runtime_paths.py").read_text())

    def test_actual_window_reload_commits_v2_but_never_starts_transports(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("POLAR_DISABLE_LOCAL_CAPTURE", "1")
        os.environ.setdefault("POLAR_DISABLE_MEDIA_PRELOAD", "1")
        from PySide6.QtCore import QEvent, QTimer
        from PySide6.QtWidgets import QApplication
        from rm_client.ui.polar_app import PolarRMWindow
        from tests.window_lifecycle_helpers import close_window_safely, settle_window_lifecycle
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"POLAR_USER_DATA_ROOT": folder}), \
             patch("serial.tools.list_ports.comports", return_value=[]), \
             patch("serial.Serial", side_effect=AssertionError("No serial open allowed")) as serial_open, \
             patch("rm_client.backend.mqtt_backend.RmMqttBackend.start") as mqtt_start, \
             patch("rm_client.backend.video_backend.RmVideoBackend.start") as video_start:
            window = PolarRMWindow()
            try:
                settle_window_lifecycle(window, app)
                for timer in window.findChildren(QTimer):
                    timer.stop()
                window._auto_save_pending = False
                name = window.config_store.import_file(PRESET, registry=window.registry)
                window.registry.get("ConfigManager").get_setting("Profile").value = name
                window.reload_current_config()
                settle_window_lifecycle(window, app)
                self.assertFalse(window.configuration_change_pending)
                self.assertEqual(window.backend.referee.profile_id, V2_PROFILE)
                self.assertEqual(window.backend.mqtt.referee.profile_id, V2_PROFILE)
                self.assertEqual(window.current_profile(), SAFE_PRESET_NAME)
                self.assertEqual(window.scenario_manager.current.key, "LabDebug")
                self.assertEqual(window.backend.safety.control_state.value, "LOCKED")
                self.assertTrue(window.backend.mqtt.mock_output)
                self.assertFalse(window.registry.get("RobotLink").enabled)
                self.assertEqual(window.registry.get("CameraFeed").get_setting("Source").value, "Synthetic")
                serial_open.assert_not_called(); mqtt_start.assert_not_called(); video_start.assert_not_called()
            finally:
                close_window_safely(window, app)
                window.deleteLater()
                app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
