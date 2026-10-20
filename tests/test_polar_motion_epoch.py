"""Motion evidence belongs to one robot transport epoch.

Real manager reset/ingestion methods and the existing verifier run against an
inert transport. No sockets, devices, workers, GUI, or application startup.
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
from rm_client.backend.polar_link import (
    PolarSegment, SEG_IMU, SEG_ROBOT_MOTION, SEG_ROBOT_STATUS,
)
from rm_client.model import RobotState


class PolarMotionEpochTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = lambda: self.now
        self.events = []
        self.segments = []
        self.state = RobotState()
        self.backend = object.__new__(BackendManager)
        backend = self.backend
        backend.state = self.state
        backend.polar_bridge = PolarStateBridge(clock=self.clock)
        backend.polar_motion = PolarMotionVerifier(clock=self.clock)
        backend.polar_arbiter = PolarControlArbiter(clock=self.clock)
        backend.safety = SimpleNamespace(
            lock_control=lambda reason: self.events.append("lock"))
        backend.polar = SimpleNamespace(
            drain_segments=self.drain_segments,
            request_estop=lambda: self.events.append("estop"),
            request_stop=lambda: self.events.append("stop"),
            request_start=self.start_transport,
            _thread=None, _stopping=False, _connecting=False, _running=False,
            _serial=None, connected=False, port="Stub", transport="tcp",
            host="configured", resolved_port="tcp://configured:50570",
            send_hz=50, last_error="",
        )
        backend.field_log = SimpleNamespace(emit=lambda *a, **k: None)
        backend._polar_last_connect_attempt = 0.0
        backend._polar_gimbal_last = (1.0, 2.0)
        backend.polar_chassis_state_seen = True
        backend._native_restart_generation = 0
        backend._native_recovery = SimpleNamespace(
            reset=lambda: self.events.append("native-reset"))

    def drain_segments(self):
        result = self.segments[:]
        self.segments.clear()
        return result

    def start_transport(self):
        self.assertEqual(self.backend.polar_motion.displacement_m, 0.0)
        self.assertFalse(self.backend.polar_motion._ever_had_feedback)
        self.events.append("start")
        self.backend.polar.connected = True

    def deliver(self, segment_id, **fields):
        self.segments.append(PolarSegment(segment_id, 1, fields))
        self.backend._apply_polar_telemetry(self.state)

    def observe(self, velocity=(1.0, 0.0, 0.0)):
        result, stats = self.backend._update_polar_motion(self.state, velocity)
        self.assertEqual(result, self.state.polar_motion_state)
        return result, stats

    def establish_position_motion(self):
        self.deliver(SEG_ROBOT_STATUS, x=0.0, y=0.0)
        self.assertEqual(self.observe()[0], "NO_FEEDBACK")
        self.deliver(SEG_ROBOT_STATUS, x=0.2, y=0.0)
        self.assertEqual(self.observe()[0], "OK")
        self.assertAlmostEqual(self.backend.polar_motion.displacement_m, 0.2)

    def assert_new_link_has_no_old_motion(self):
        # Valid IMU traffic makes the new link live without providing either
        # position or speed evidence. The previous robot's motion is irrelevant.
        self.deliver(SEG_IMU, yaw=0.0, pitch=0.0, roll=0.0)
        self.assertTrue(self.backend.polar_bridge.active)
        result, stats = self.observe()
        self.assertEqual(result, "NO_FEEDBACK")
        self.assertEqual(stats["displacement_m"], 0.0)

    def test_scenario_reset_discards_old_displacement(self):
        self.establish_position_motion()
        self.backend._reset_state_for_scenario(self.state)
        self.assert_new_link_has_no_old_motion()

    def test_endpoint_invalidation_discards_old_displacement(self):
        self.establish_position_motion()
        self.backend._invalidate_polar_epoch("endpoint changed")
        self.assertEqual(self.events, ["lock", "estop"])
        self.assert_new_link_has_no_old_motion()

    def test_shutdown_invalidation_discards_old_displacement(self):
        self.establish_position_motion()
        self.backend._invalidate_shutdown_runtime()
        self.assertEqual(self.events, ["native-reset"])
        self.assert_new_link_has_no_old_motion()

    def test_reconnect_discards_old_displacement_before_start(self):
        self.establish_position_motion()
        with patch("rm_client.backend.manager.time.perf_counter", self.clock):
            self.backend._retry_polar_connect()
        self.assertEqual(self.events, ["lock", "estop", "start"])
        self.assert_new_link_has_no_old_motion()

    def test_reconfigure_discards_old_displacement(self):
        self.establish_position_motion()
        self.assertTrue(self.backend._prepare_polar_reconfigure("port changed"))
        self.assertEqual(self.events, ["lock", "estop"])
        self.assert_new_link_has_no_old_motion()

    def test_first_new_position_is_a_baseline_even_after_old_drive(self):
        self.establish_position_motion()
        self.backend._reset_state_for_scenario(self.state)
        self.deliver(SEG_ROBOT_STATUS, x=30.0, y=40.0)
        result, stats = self.observe()
        self.assertEqual(result, "NO_FEEDBACK")
        self.assertEqual(stats["displacement_m"], 0.0)
        self.deliver(SEG_ROBOT_STATUS, x=30.2, y=40.0)
        self.assertEqual(self.observe()[0], "OK")

    def test_new_epoch_can_fall_back_to_position_after_old_speed_stream(self):
        self.deliver(SEG_ROBOT_MOTION, vx_mps=1.0, vy_mps=0.0, wz_rps=0.0)
        self.assertEqual(self.observe()[0], "OK")
        self.backend._invalidate_polar_epoch("different robot")
        self.now += 3.0
        self.deliver(SEG_ROBOT_STATUS, x=30.0, y=40.0)
        self.assertEqual(self.observe()[0], "NO_FEEDBACK")
        self.deliver(SEG_ROBOT_STATUS, x=30.2, y=40.0)
        self.assertEqual(self.observe()[0], "OK")

    def test_same_epoch_position_and_speed_observations_remain_valid(self):
        self.establish_position_motion()
        for x in (0.3, 0.4, 0.5):
            self.deliver(SEG_ROBOT_STATUS, x=x, y=0.0)
            result, stats = self.observe()
            self.assertEqual(result, "OK")
            self.assertAlmostEqual(stats["displacement_m"], x)
        self.deliver(SEG_ROBOT_MOTION, vx_mps=1.0, vy_mps=0.0, wz_rps=0.0)
        self.assertEqual(self.observe()[0], "OK")
        self.assertEqual(self.observe((0.0, 0.0, 0.0))[0], "IDLE")

    def test_reset_is_complete_idempotent_and_preserves_clock(self):
        self.establish_position_motion()
        self.deliver(SEG_ROBOT_MOTION, vx_mps=1.0, vy_mps=0.0, wz_rps=0.0)
        self.observe()
        motion = self.backend.polar_motion
        motion.reset()
        fresh = PolarMotionVerifier(clock=self.clock)
        self.assertEqual(vars(motion), vars(fresh))
        motion.reset()
        self.assertEqual(vars(motion), vars(fresh))
        self.assertIs(motion.clock, self.clock)
        self.now += 10.0
        self.deliver(SEG_ROBOT_MOTION, vx_mps=1.0, vy_mps=0.0, wz_rps=0.0)
        self.assertEqual(motion._last_feedback_segment_at, self.now)
        self.assertEqual(self.observe()[0], "OK")


if __name__ == "__main__":
    unittest.main()
