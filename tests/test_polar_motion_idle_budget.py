"""Only attempted motion can consume the missing-feedback STUCK budget.

Inert verifier and real manager tick paths; no device, network, worker, GUI, or
application startup. The missing-0x1E NO_FEEDBACK label remains intentional.
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.backend.manager import BackendManager
from rm_client.backend.polar_bridge import (
    PolarControlArbiter, PolarMotionVerifier, PolarStateBridge,
)
from rm_client.backend.polar_link import PolarSegment, SEG_IMU
from rm_client.model import RobotState
from test_backend_policy_characterization import DEFAULT_SETTINGS, Module, RecordingPolar


class PolarMotionIdleBudgetTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = lambda: self.now
        self.motion = PolarMotionVerifier(clock=self.clock)

    def observe(self, *, vx=0.0, vy=0.0, wz=0.0, active=True):
        return self.motion.update(
            link_active=active, commanded_vx=vx, commanded_vy=vy,
            commanded_wz=wz, measured_vx=None, measured_vy=None,
            measured_wz=None,
        )

    def test_idle_remains_no_feedback_after_a_long_wait(self):
        self.assertEqual(self.observe(), "NO_FEEDBACK")
        self.now += 60.0
        self.assertEqual(self.observe(), "NO_FEEDBACK")
        self.assertIsNone(self.motion._moving_since)

    def test_new_command_after_idle_gets_a_fresh_budget(self):
        self.assertEqual(self.observe(), "NO_FEEDBACK")
        self.now += 60.0
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        self.assertEqual(self.motion._moving_since, self.now)
        self.now += 1.19
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        self.now += 0.02
        self.assertEqual(self.observe(vx=1.0), "STUCK")

    def test_release_clears_stuck_and_repress_gets_a_fresh_budget(self):
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        self.now += 1.21
        self.assertEqual(self.observe(vx=1.0), "STUCK")
        self.assertEqual(self.observe(), "NO_FEEDBACK")
        self.assertIsNone(self.motion._moving_since)
        self.now += 5.0
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        self.assertEqual(self.motion._moving_since, self.now)
        self.now += 1.19
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        self.now += 0.02
        self.assertEqual(self.observe(vx=1.0), "STUCK")

    def test_release_before_timeout_does_not_charge_next_attempt(self):
        self.observe(vx=1.0)
        self.now += 1.0
        self.assertEqual(self.observe(), "NO_FEEDBACK")
        self.now += 0.1
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        self.now += 0.2
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")

    def test_subthreshold_linear_and_angular_commands_do_not_start_timer(self):
        for command in ({"vx": 0.299}, {"vy": -0.299},
                        {"wz": 0.299}, {"wz": -0.299}):
            with self.subTest(command=command):
                self.motion.reset()
                self.assertEqual(self.observe(**command), "NO_FEEDBACK")
                self.now += 10.0
                self.assertEqual(self.observe(**command), "NO_FEEDBACK")
                self.assertIsNone(self.motion._moving_since)

    def test_linear_and_rotation_thresholds_still_admit_attempts(self):
        for command in ({"vx": 0.3}, {"vy": -0.3}, {"vx": 0.24, "vy": 0.18},
                        {"wz": 0.3}, {"wz": -0.3}):
            with self.subTest(command=command):
                self.motion.reset()
                self.assertEqual(self.observe(**command), "NO_FEEDBACK")
                self.assertEqual(self.motion._moving_since, self.now)
                self.now += 1.21
                self.assertEqual(self.observe(**command), "STUCK")

    def test_same_epoch_position_accumulation_still_confirms_motion(self):
        self.motion.note_position(0.0, 0.0)
        self.assertEqual(self.observe(vx=1.0), "NO_FEEDBACK")
        for x in (0.06, 0.10, 0.20):
            self.motion.note_position(x, 0.0)
            self.assertEqual(self.observe(vx=1.0), "OK")
            self.assertAlmostEqual(self.motion.displacement_m, x)

    def test_missing_link_and_existing_speed_feedback_keep_their_precedence(self):
        self.assertEqual(self.observe(active=False), "NO_LINK")
        self.motion.note_motion_segment()
        self.assertEqual(self.observe(), "IDLE")
        self.now += 3.0
        self.assertEqual(self.observe(), "STALE_FEEDBACK")

    def test_real_manager_disabled_drive_does_not_report_stuck(self):
        events = []
        backend = object.__new__(BackendManager)
        state = backend.state = RobotState()
        backend.polar = RecordingPolar(events)
        backend.polar_bridge = PolarStateBridge(clock=self.clock)
        backend.polar_motion = self.motion
        backend.polar_arbiter = PolarControlArbiter(clock=self.clock)
        backend.safety = SimpleNamespace(estop_active=False)
        backend.field_log = SimpleNamespace(emit=lambda *a, **k: None)
        backend._spin_ever_on = False
        backend._spin_off_since = 0.0
        backend._spin_assert = 0
        backend._last_spin_note = ""
        backend._polar_gimbal_last = None
        backend.polar_chassis_state_seen = False
        settings = dict(DEFAULT_SETTINGS, **{"Allow Drive": False})
        registry = {"RobotLink": Module(enabled=True, **settings)}
        control = SimpleNamespace(
            last_command=SimpleNamespace(vx=1.0, vy=0.0, wz=0.0, keyboard_value=1),
            dt7_enabled=False,
        )
        for delay in (0.0, 10.0):
            self.now += delay
            backend.polar.segments.append(PolarSegment(SEG_IMU, 1, {}))
            with patch("rm_client.backend.manager.time.perf_counter", self.clock), \
                    patch("rm_client.backend.manager._LOG.warning"):
                result = backend._tick_polar_link_ready(state, registry, control)
            self.assertFalse(result["drive_armed"])
            self.assertEqual((backend.polar.intent.vx, backend.polar.intent.vy,
                              backend.polar.intent.wz), (0.0, 0.0, 0.0))
            self.assertEqual(result["motion_state"], "NO_FEEDBACK")
            self.assertEqual(state.polar_motion_state, "NO_FEEDBACK")


if __name__ == "__main__":
    unittest.main()
