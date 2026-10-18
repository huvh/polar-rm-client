"""Reported identity belongs to one robot epoch, selected identity does not.

Real manager gates/configuration, real safety/bridge/verifiers and model overlay,
recording-only transport, deterministic time. No devices, sockets, app or workers.
"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.backend.manager import BackendManager
from rm_client.backend.polar_bridge import PolarControlArbiter, PolarMotionVerifier, PolarStateBridge
from rm_client.backend.polar_link import PolarSegment, SEG_IMU, SEG_ROBOT_STATUS
from rm_client.backend.robot_link_settings import RobotLinkSettings
from rm_client.backend.safety import OfficialSafety
from rm_client.model import RobotState
from test_backend_policy_characterization import DEFAULT_SETTINGS, Module, RecordingPolar


class PolarRoleEpochTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = lambda: self.now
        self.events = []
        self.backend = object.__new__(BackendManager)
        backend = self.backend
        self.state = backend.state = RobotState(robot_id=3)
        backend.polar = RecordingPolar(self.events)
        backend.polar._thread = None
        backend.polar.connected = True
        backend.polar.request_start = lambda: self.events.append(["start"])
        backend.polar_bridge = PolarStateBridge(clock=self.clock)
        backend.polar_motion = PolarMotionVerifier(clock=self.clock)
        backend.polar_arbiter = PolarControlArbiter(clock=self.clock)
        backend.safety = OfficialSafety("LabDebug")
        backend.field_log = SimpleNamespace(emit=lambda *args, **kwargs: None)
        backend._last_spin_note = ""
        backend._spin_ever_on = False
        backend._spin_off_since = 0.0
        backend._spin_assert = 0
        backend.polar_chassis_state_seen = False
        backend._native_restart_generation = 0
        backend._native_recovery = SimpleNamespace(reset=lambda: None)
        backend._polar_last_connect_attempt = 0.0
        self.registry = {"RobotLink": Module(**DEFAULT_SETTINGS), "SpinMode": Module(enabled=False)}

    def deliver(self, segment_id, **fields):
        self.backend.polar.segments.append(PolarSegment(segment_id, 1, fields))
        self.backend._apply_polar_telemetry(self.state)

    def establish_identity(self, robot_id):
        self.deliver(SEG_ROBOT_STATUS, robot_id=robot_id)
        self.assertEqual(self.state.polar_reported_robot_id, robot_id)
        self.assertEqual(self.state.polar_overlay["polar_reported_robot_id"], robot_id)

    def invalidate(self, boundary):
        if boundary == "endpoint":
            self.backend._invalidate_polar_epoch("different robot")
        elif boundary == "scenario":
            self.backend._reset_state_for_scenario(self.state)
        elif boundary == "shutdown":
            self.backend._invalidate_shutdown_runtime()
        elif boundary == "reconfigure":
            # Exercise actual endpoint-setting caller, not merely its reset seam.
            registry = {"RobotLink": Module(**dict(DEFAULT_SETTINGS, Port="COM_NEW"))}
            settings = RobotLinkSettings.capture(registry)
            self.assertTrue(self.backend._apply_polar_configuration(settings))
            self.assertEqual(self.backend.polar.port, "COM_NEW")
        elif boundary == "reconnect":
            self.backend.polar.port = "COM_NEW"
            self.backend.polar.connected = False
            with patch("rm_client.backend.manager.time.perf_counter", self.clock):
                self.backend._retry_polar_connect()
            self.assertIn(["start"], self.events)
            self.backend.polar.connected = True
        else:
            self.fail(boundary)

    def tick(self):
        # This is new input supplied after invalidation, not replayed old keys.
        control = SimpleNamespace(last_command=SimpleNamespace(vx=1.0, vy=0.0, wz=0.0, keyboard_value=1))
        with patch("rm_client.backend.manager.time.perf_counter", self.clock):
            return self.backend._tick_polar_link_ready(self.state, self.registry, control)

    def assert_selected_fallback_after_old_hero(self, boundary):
        self.establish_identity(1)
        self.invalidate(boundary)
        self.now = 110.0
        self.deliver(SEG_IMU, yaw_rad=0.0)
        result = self.tick()
        self.assertEqual(result["role_id"], 3)
        self.assertEqual(result["role_reported_id"], 0)
        self.assertEqual(result["role_selected_id"], 3)
        self.assertEqual(result["role_mismatch"], "")
        self.assertEqual(result["role_max_linear_mps"], 1.5)
        self.assertTrue(result["drive_armed"])
        self.assertEqual(self.backend.polar.intent.vx, 1.5)

    def test_endpoint_does_not_reuse_old_hero_speed_limit(self):
        self.assert_selected_fallback_after_old_hero("endpoint")

    def test_scenario_does_not_reuse_old_hero_speed_limit(self):
        self.assert_selected_fallback_after_old_hero("scenario")

    def test_shutdown_does_not_reuse_old_hero_speed_limit(self):
        self.assert_selected_fallback_after_old_hero("shutdown")

    def test_actual_reconfigure_does_not_reuse_old_role(self):
        self.assert_selected_fallback_after_old_hero("reconfigure")

    def test_actual_reconnect_does_not_reuse_old_role(self):
        self.assert_selected_fallback_after_old_hero("reconnect")

    def test_all_boundaries_clear_scalar_and_replayable_overlay_immediately(self):
        for boundary in ("endpoint", "scenario", "shutdown"):
            with self.subTest(boundary=boundary):
                self.setUp()
                self.establish_identity(1)
                self.invalidate(boundary)
                self.assertEqual(self.state.robot_id, 3)
                self.assertEqual(self.state.polar_reported_robot_id, 0)
                self.assertNotIn("polar_reported_robot_id", self.state.polar_overlay)
                self.assertNotIn("polar_reported_robot_id", self.backend.polar_bridge.overlay)
                self.state.apply_polar_overlay()
                self.assertEqual(self.state.polar_reported_robot_id, 0)
                self.invalidate(boundary)
                self.assertEqual(self.state.polar_reported_robot_id, 0)

    def test_old_unsupported_roles_do_not_block_new_selected_infantry(self):
        for old_id in (5, 6, 7, 8, 9):
            with self.subTest(old_id=old_id):
                self.setUp()
                self.establish_identity(old_id)
                self.invalidate("endpoint")
                self.now = 110.0
                self.deliver(SEG_IMU, yaw_rad=0.0)
                result = self.tick()
                self.assertTrue(result["drive_armed"])
                self.assertEqual(result["role_id"], 3)
                self.assertEqual(self.backend.polar.intent.vx, 1.5)

    def test_old_unknown_identity_does_not_leak_into_new_role_diagnostics(self):
        self.establish_identity(255)
        self.invalidate("endpoint")
        self.now = 110.0
        self.deliver(SEG_IMU, yaw_rad=0.0)
        result = self.tick()
        self.assertEqual(result["role_reported_id"], 0)
        self.assertTrue(result["role_known"])
        self.assertEqual(result["role_mismatch"], "")

    def test_new_fresh_report_overrides_selected_role(self):
        for fresh_id, cap, allowed in ((1, 2.0, True), (9, 0.0, False)):
            with self.subTest(fresh_id=fresh_id):
                self.setUp()
                self.establish_identity(3)
                self.invalidate("endpoint")
                self.now = 110.0
                self.deliver(SEG_ROBOT_STATUS, robot_id=fresh_id)
                result = self.tick()
                self.assertEqual(result["role_id"], fresh_id)
                self.assertEqual(result["role_reported_id"], fresh_id)
                self.assertEqual(result["role_max_linear_mps"], cap)
                self.assertEqual(result["drive_armed"], allowed)
                self.assertEqual(self.state.robot_id, 3)

    def test_same_epoch_partial_telemetry_keeps_valid_reported_identity(self):
        self.establish_identity(1)
        self.now += 0.1
        self.deliver(SEG_IMU, yaw_rad=0.0)
        result = self.tick()
        self.assertEqual(result["role_id"], 1)
        self.assertEqual(result["role_max_linear_mps"], 2.0)
        self.assertEqual(self.backend.polar.intent.vx, 2.0)

    def test_selected_unsupported_role_stays_blocked_without_fresh_report(self):
        self.state.robot_id = 9
        self.establish_identity(1)
        self.invalidate("endpoint")
        self.now = 110.0
        self.deliver(SEG_IMU, yaw_rad=0.0)
        result = self.tick()
        self.assertEqual(result["role_id"], 9)
        self.assertFalse(result["drive_armed"])
        self.assertEqual(self.backend.polar.intent.vx, 0.0)

    def test_unknown_selected_role_retains_existing_conservative_fallback(self):
        self.state.robot_id = 255
        self.establish_identity(1)
        self.invalidate("endpoint")
        self.now = 110.0
        self.deliver(SEG_IMU, yaw_rad=0.0)
        result = self.tick()
        self.assertEqual(result["role_id"], 255)
        self.assertFalse(result["role_known"])
        self.assertEqual(result["role_max_linear_mps"], 1.5)
        self.assertEqual(self.backend.polar.intent.vx, 1.5)

    def test_latched_estop_is_not_released(self):
        for boundary in ("endpoint", "scenario", "shutdown"):
            with self.subTest(boundary=boundary):
                self.setUp()
                self.establish_identity(1)
                self.backend.safety.trigger_estop()
                estop_at = self.backend.safety.estop_at
                self.invalidate(boundary)
                self.now = 110.0
                self.deliver(SEG_IMU, yaw_rad=0.0)
                result = self.tick()
                self.assertTrue(self.backend.safety.estop_active)
                self.assertEqual(self.backend.safety.estop_at, estop_at)
                self.assertFalse(result["drive_armed"])
                self.assertEqual(self.backend.polar.intent.vx, 0.0)

    def test_unattached_runtime_boundaries_still_work(self):
        self.backend.state = None
        self.invalidate("endpoint")
        self.invalidate("shutdown")
        self.assertFalse(self.backend.polar_bridge.active)


if __name__ == "__main__":
    unittest.main()
