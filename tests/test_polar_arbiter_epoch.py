"""Gimbal conflict timing must describe one continuous transport epoch.

Real manager boundaries and planning, real bridge/arbiter, deterministic clock,
inert transport. Existing lockout latching and slew trajectory are invariants.
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
from rm_client.backend.polar_link import PolarSegment, SEG_IMU, SEG_JOINT_STATE
from rm_client.model import RobotState


class PolarArbiterEpochTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = lambda: self.now
        self.events = []
        self.state = RobotState()
        self.state.robot_id = 3
        self.state.target_locked = True
        self.state.vision_calibrated = True
        self.state.vision_aim_yaw_deg = 90.0
        self.state.vision_aim_pitch_deg = 30.0
        self.backend = object.__new__(BackendManager)
        backend = self.backend
        backend.state = self.state
        backend.polar_bridge = PolarStateBridge(clock=self.clock)
        backend.polar_motion = PolarMotionVerifier(clock=self.clock)
        backend.polar_arbiter = PolarControlArbiter(clock=self.clock)
        backend.safety = SimpleNamespace(lock_control=lambda reason: self.events.append("lock"))
        backend.polar = SimpleNamespace(
            request_estop=lambda: self.events.append("estop"),
            request_stop=lambda: self.events.append("stop"),
            request_start=lambda: self.events.append("start"),
            _thread=None, _stopping=False, _connecting=False, _running=False,
            _serial=None, connected=False, port="Stub", transport="tcp",
            host="configured", resolved_port="tcp://configured:50570", send_hz=50,
            last_error="",
        )
        backend.field_log = SimpleNamespace(emit=lambda *args, **kwargs: None)
        backend._polar_last_connect_attempt = 0.0
        backend._polar_gimbal_last = None
        backend.polar_chassis_state_seen = False
        backend._native_restart_generation = 0
        backend._native_recovery = SimpleNamespace(reset=lambda: self.events.append("native-reset"))

    @property
    def arbiter(self):
        return self.backend.polar_arbiter

    def takeover(self):
        self.arbiter.request_takeover(client_gimbal_enabled=True, vision_nuc_occupied=False)

    def feedback(self, *, joint=True):
        segment_id = SEG_JOINT_STATE if joint else SEG_IMU
        self.backend.polar_bridge.apply(PolarSegment(segment_id, 1, {"yaw_rad": 0.0, "pitch_rad": 0.0}))

    def plan(self):
        self.feedback()
        return self.backend._plan_polar_gimbal(self.state, estopped=False)

    def establish_pending_divergence(self):
        self.takeover()
        self.assertEqual(self.plan(), (8.0, 8.0))
        self.assertFalse(self.arbiter.diverging)
        self.now = 100.10
        self.assertEqual(self.plan(), (16.0, 16.0))
        self.assertTrue(self.arbiter.diverging)
        self.assertEqual(self.arbiter.state, "CLIENT")

    def establish_lockout(self):
        self.establish_pending_divergence()
        self.now = 100.80
        self.plan()
        self.assertEqual(self.arbiter.state, "LOCKOUT")
        self.assertFalse(self.arbiter.diverging)

    def invalidate(self, boundary):
        if boundary == "scenario":
            self.backend._reset_state_for_scenario(self.state)
        elif boundary == "endpoint":
            self.backend._invalidate_polar_epoch("endpoint changed")
        elif boundary == "shutdown":
            self.backend._invalidate_shutdown_runtime()
        elif boundary == "reconnect":
            with patch("rm_client.backend.manager.time.perf_counter", self.clock):
                self.backend._retry_polar_connect()
        elif boundary == "reconfigure":
            self.assertTrue(self.backend._prepare_polar_reconfigure("port changed"))
        else:
            self.fail(boundary)

    def assert_new_epoch_gets_fresh_budget(self, boundary):
        self.establish_pending_divergence()
        self.invalidate(boundary)
        self.now = 110.0
        self.takeover()
        # Existing last-command slew references remain 16/16, not reset to zero.
        self.assertEqual(self.plan(), (24.0, 24.0))
        self.assertEqual(self.arbiter.state, "CLIENT")
        self.assertTrue(self.arbiter.diverging)
        self.assertEqual(self.arbiter.divergent_seconds, 0.0)
        self.now = 110.50
        self.plan()
        self.assertEqual(self.arbiter.state, "CLIENT")
        self.now = 110.61
        self.plan()
        self.assertEqual(self.arbiter.state, "LOCKOUT")

    def test_scenario_starts_new_divergence_budget(self):
        self.assert_new_epoch_gets_fresh_budget("scenario")

    def test_endpoint_starts_new_divergence_budget(self):
        self.assert_new_epoch_gets_fresh_budget("endpoint")

    def test_shutdown_starts_new_divergence_budget(self):
        self.assert_new_epoch_gets_fresh_budget("shutdown")

    def test_reconnect_starts_new_divergence_budget(self):
        self.assert_new_epoch_gets_fresh_budget("reconnect")

    def test_reconfigure_starts_new_divergence_budget(self):
        self.assert_new_epoch_gets_fresh_budget("reconfigure")

    def test_same_epoch_pending_divergence_still_times_out(self):
        self.establish_pending_divergence()
        self.now = 100.50
        self.plan()
        self.assertEqual(self.arbiter.state, "CLIENT")
        self.now = 100.80
        self.plan()
        self.assertEqual(self.arbiter.state, "LOCKOUT")
        self.assertIsNone(self.plan())

    def test_same_epoch_convergence_restarts_budget(self):
        self.establish_pending_divergence()
        self.now = 100.50
        self.state.vision_aim_yaw_deg = 0.0
        self.state.vision_aim_pitch_deg = 0.0
        self.assertEqual(self.plan(), (8.0, 8.0))
        self.assertFalse(self.arbiter.diverging)
        self.now = 110.0
        self.state.vision_aim_yaw_deg = 90.0
        self.state.vision_aim_pitch_deg = 30.0
        self.assertEqual(self.plan(), (16.0, 16.0))
        self.assertEqual(self.arbiter.state, "CLIENT")
        self.assertEqual(self.arbiter.divergent_seconds, 0.0)

    def test_invalidation_changes_only_pending_timer(self):
        for boundary in ("scenario", "endpoint", "shutdown"):
            with self.subTest(boundary=boundary):
                self.setUp()
                self.establish_pending_divergence()
                expected = vars(self.arbiter).copy()
                expected["_divergent_since"] = None
                self.invalidate(boundary)
                self.assertEqual(vars(self.arbiter), expected)
                self.invalidate(boundary)
                self.assertEqual(vars(self.arbiter), expected)
                self.assertEqual(self.arbiter._last_command_time(), 100.10)

    def test_endpoint_and_shutdown_preserve_established_lockout_exactly(self):
        for boundary in ("endpoint", "shutdown", "reconnect", "reconfigure"):
            with self.subTest(boundary=boundary):
                self.setUp()
                self.establish_lockout()
                expected = vars(self.arbiter).copy()
                self.invalidate(boundary)
                self.assertEqual(vars(self.arbiter), expected)
                self.now = 110.0
                self.takeover()
                self.assertEqual(vars(self.arbiter), expected)
                self.assertIsNone(self.plan())
                self.arbiter.clear_lockout()
                self.assertEqual(self.arbiter.state, "PASSIVE")
                self.takeover()
                self.assertEqual(self.arbiter.state, "CLIENT")

    def test_scenario_retains_existing_explicit_clear_behavior(self):
        self.establish_lockout()
        reference = (self.arbiter._commanded_at, self.arbiter._commanded_yaw, self.arbiter._commanded_pitch)
        self.invalidate("scenario")
        self.assertEqual(self.arbiter.state, "PASSIVE")
        self.assertEqual(self.arbiter.reason, "已清除抢环锁出，等待重新交权")
        self.assertEqual(self.arbiter._lockout_reason, "")
        self.assertTrue(self.arbiter._converged)
        self.assertFalse(self.arbiter.diverging)
        self.assertEqual((self.arbiter._commanded_at, self.arbiter._commanded_yaw, self.arbiter._commanded_pitch), reference)
        self.assertIsNone(self.plan())

    def test_new_epoch_without_joint_feedback_does_not_spend_budget(self):
        self.establish_pending_divergence()
        self.invalidate("endpoint")
        self.now = 110.0
        self.feedback(joint=False)
        self.assertEqual(self.backend._plan_polar_gimbal(self.state, estopped=False), (24.0, 24.0))
        self.assertFalse(self.arbiter.diverging)
        self.now = 120.0
        self.assertEqual(self.plan(), (32.0, 30.0))
        self.assertEqual(self.arbiter.state, "CLIENT")
        self.assertEqual(self.arbiter.divergent_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
