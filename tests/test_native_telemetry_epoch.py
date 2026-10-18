"""Native sample retirement at existing scenario/profile epochs; inert I/O only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import os
import tempfile
import struct
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend.manager import BackendManager
from rm_client.backend.polar_bridge import PolarStateBridge, PolarMotionVerifier, PolarControlArbiter
from rm_client.backend.referee.rm2026 import codec
from rm_client.backend.referee.rm2026.state_adapter import Rm2026StateAdapter
from rm_client.backend.safety import OfficialSafety
from rm_client.hero_lob import HeroLobPlanner
from rm_client.model import RobotState

FIXED = struct.Struct('<4sHHIQIHHHHIBBH9f')
NATIVE = ('native_telemetry_at', 'native_telemetry_unix_ms', 'native_telemetry_frame_seq',
    'native_camera_online', 'native_gimbal_online', 'native_gimbal_mode',
    'native_bullet_count', 'native_bullet_speed', 'native_yaw_deg', 'native_yaw_velocity',
    'native_pitch_deg', 'native_pitch_velocity', 'native_quaternion', 'native_status_text')

def packet(count=42, seq=37):
    text = b'READY'
    return FIXED.pack(b'PDL1', 1, FIXED.size + len(text), 3, 123456789, seq,
        1280, 720, 3000, 100, 1200, 1, 0, count, 1.25, 2.5, -3.25, -4.5,
        15., 0., 0., 0.6, 0.8) + text

class NativeTelemetryEpochTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.clock = lambda: self.now
        self.backend = object.__new__(BackendManager)
        b = self.backend
        self.state = b.state = RobotState(robot_id=1, robot_profile='Hero',
            remaining_ammo=0, current_heat=20., max_heat=240.,
            hero_lob_yaw_calibrated=True, hero_lob_pitch_calibrated=True,
            hero_lob_relocalization_valid=True, current_stage='MATCH',
            mock_simulation_enabled=False, official_state_active=True)
        b.polar_bridge = PolarStateBridge(clock=self.clock)
        b.polar_motion = PolarMotionVerifier(clock=self.clock)
        b.polar_arbiter = PolarControlArbiter(clock=self.clock)
        b.safety = OfficialSafety()
        b.field_log = NS(emit=lambda *a, **k: None)
        b._last_logged_stage = 'MATCH'
        b.referee_adapter = Rm2026StateAdapter(b)
        self.timepatch = patch('rm_client.backend.manager.time.perf_counter', self.clock)
        self.timepatch.start()
        self.addCleanup(self.timepatch.stop)

    def deliver_native(self, raw):
        self.backend._apply_custom_byte_block(self.state, {'data': raw})

    def official(self, name, raw):
        data = codec.decode_message(name, raw)
        self.assertTrue(data)
        self.backend._begin_official_state(self.state, self.now)
        self.backend._apply_one(self.state, name, data)

    def ready(self):
        return HeroLobPlanner.readiness(self.state, hero_range_profile=True, now=self.now)

    def snapshot(self):
        return {name: getattr(self.state, name) for name in NATIVE}

    def assert_native_retired(self):
        defaults = RobotState()
        self.assertEqual(self.snapshot(), {name: getattr(defaults, name) for name in NATIVE})
        self.assertNotIn('native_telemetry', self.state.backend_stats)

    def test_reset_retires_native_group_and_mirror(self):
        self.deliver_native(packet())
        self.assertEqual(self.state.native_bullet_count, 42)
        self.now = 100.1
        self.backend._reset_state_for_scenario(self.state)
        self.assert_native_retired()

    def test_new_official_zero_ammo_cannot_reuse_previous_native_observation(self):
        self.deliver_native(packet())
        self.assertTrue(self.ready().ready)
        self.now = 100.1
        self.backend._reset_state_for_scenario(self.state)
        self.now = 100.2
        self.official('GameStatus', codec.encode_uint(5, 4))
        self.official('RobotDynamicStatus', codec.encode_uint(9, 0))
        result = self.ready()
        self.assertEqual(self.state.remaining_ammo, 0)
        self.assertFalse(result.ready)
        self.assertIn('telemetry stale', result.reasons)
        self.assertIn('no projectile', result.reasons)
        self.assert_native_retired()

    def test_first_new_native_sample_restores_current_epoch_readiness(self):
        self.deliver_native(packet())
        self.backend._reset_state_for_scenario(self.state)
        self.now = 100.2
        self.official('GameStatus', codec.encode_uint(5, 4))
        self.assertFalse(self.ready().ready)
        self.deliver_native(packet(count=3, seq=1))
        self.assertTrue(self.ready().ready)
        self.assertEqual((self.state.native_bullet_count, self.state.native_telemetry_frame_seq), (3, 1))
        self.assertEqual(self.state.native_telemetry_at, self.now)
        self.assertEqual(self.state.backend_stats['native_telemetry']['frame_seq'], 1)

    def test_repeated_reset_remains_retired_without_fresh_sample(self):
        self.deliver_native(packet())
        for _ in range(2):
            self.backend._reset_state_for_scenario(self.state)
            self.assert_native_retired()

    def test_malformed_packet_after_reset_cannot_restore_freshness(self):
        self.deliver_native(packet())
        self.backend._reset_state_for_scenario(self.state)
        self.now = 100.2
        self.official('GameStatus', codec.encode_uint(5, 4))
        self.deliver_native(b'PDL1' + bytes(70))
        self.assert_native_retired()
        self.assertFalse(self.ready().ready)
        self.assertIn('telemetry stale', self.ready().reasons)

    def test_existing_same_epoch_sequence_restart_still_revokes_trust(self):
        self.deliver_native(packet())
        self.now = 100.2
        self.deliver_native(packet(seq=1))
        self.assertFalse(self.state.hero_lob_relocalization_valid)
        self.assertFalse(self.ready().ready)

    def test_same_epoch_partial_official_zero_keeps_native_alternative(self):
        self.deliver_native(packet())
        self.now = 100.2
        self.official('RobotDynamicStatus', codec.encode_uint(9, 0))
        self.assertTrue(self.ready().ready)
        self.assertEqual(self.state.native_bullet_count, 42)

    def test_elapsed_native_timeout_blocks_even_with_retained_ammo(self):
        self.deliver_native(packet())
        self.backend._reset_state_for_scenario(self.state)
        self.now = 100.6
        self.official('GameStatus', codec.encode_uint(5, 4))
        self.assertIn('telemetry stale', self.ready().reasons)
        self.assertFalse(self.ready().ready)

    def test_fresh_zero_native_report_does_not_retain_old_ammo(self):
        self.deliver_native(packet())
        self.backend._reset_state_for_scenario(self.state)
        self.now = 100.2
        self.official('GameStatus', codec.encode_uint(5, 4))
        self.deliver_native(packet(count=0, seq=38))
        self.assertEqual(self.state.native_bullet_count, 0)
        self.assertEqual(self.state.native_telemetry_at, 100.2)
        self.assertIn('no projectile', self.ready().reasons)
        self.assertFalse(self.ready().ready)

    def test_malformed_native_block_never_refreshes_old_sample(self):
        self.deliver_native(packet())
        before = self.snapshot()
        self.now = 100.2
        self.deliver_native(b'PDL1' + bytes(70))
        self.assertEqual(self.snapshot(), before)

class NativeTelemetryOwnerTests(unittest.TestCase):
    def test_owner_reset_changes_only_sample_group_and_owned_mirror(self):
        state = RobotState(robot_id=101, robot_profile='Hero', current_heat=17.,
            power_limit=123, remaining_ammo=9, hero_lob_armed=True,
            hero_lob_relocalization_valid=True, hero_lob_yaw_calibrated=True,
            hero_lob_pitch_calibrated=True)
        backend = object.__new__(BackendManager)
        backend._apply_custom_byte_block(state, {'data': packet()})
        state.backend_stats.update({'video_frames': 123, 'unrelated': {'retained': 7}})
        unrelated = state.backend_stats['unrelated']
        expected = deepcopy(vars(state))
        defaults = RobotState()
        expected.update({name: getattr(defaults, name) for name in NATIVE})
        expected['backend_stats'].pop('native_telemetry')
        state.clear_native_telemetry()
        self.assertEqual(vars(state), expected)
        self.assertIs(state.backend_stats['unrelated'], unrelated)

    def test_owner_reset_is_idempotent_with_absent_diagnostic(self):
        state = RobotState()
        before = deepcopy(vars(state))
        state.clear_native_telemetry()
        state.clear_native_telemetry()
        self.assertEqual(vars(state), before)

    def test_new_sample_after_reset_never_restores_revoked_operator_flags(self):
        state = RobotState(hero_lob_armed=False, hero_lob_relocalization_valid=False)
        backend = object.__new__(BackendManager)
        backend._apply_custom_byte_block(state, {'data': packet()})
        state.clear_native_telemetry()
        backend._apply_custom_byte_block(state, {'data': packet(seq=1)})
        self.assertFalse(state.hero_lob_armed)
        self.assertFalse(state.hero_lob_relocalization_valid)
        self.assertEqual(state.native_telemetry_frame_seq, 1)
        self.assertEqual(state.native_bullet_count, 42)


class NativeTelemetryCallerTests(unittest.TestCase):
    """Actual manager scenario/profile callers, unstarted resources and I/O guards."""
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        for target in ('serial.Serial', 'socket.socket', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('native acquisition forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        self.state = RobotState(robot_id=1, robot_profile='Hero')
        with patch.dict(os.environ, {'POLAR_USER_DATA_ROOT': self.root.name}), patch.object(
                BackendManager, '_build_commit', return_value='TEST'):
            self.backend = BackendManager(workspace=self.root.name, state=self.state, client_id='1')
        self.addCleanup(self.backend.shutdown)
        self.assertTrue(self.backend.native_decoder.wait_closed())
        self.assertTrue(self.backend.udp.wait_closed())
        self.backend._apply_custom_byte_block(self.state, {'data': packet()})

    def assert_native_retired(self):
        defaults = RobotState()
        self.assertEqual({name: getattr(self.state, name) for name in NATIVE},
                         {name: getattr(defaults, name) for name in NATIVE})
        self.assertNotIn('native_telemetry', self.state.backend_stats)

    def test_actual_scenario_activation_retires_sample_and_preserves_estop_role(self):
        self.backend.safety.trigger_estop()
        estop_at = self.backend.safety.estop_at
        self.backend._native_0310_dropped_chunks = 13
        self.backend._native_0310_out_of_order_chunks = 14
        self.backend._native_0310_recovery_dropped_chunks = 15
        self.backend._native_0310_decoder_restarts = 16
        self.backend.apply_scenario('OfficialEvent', start=False, robot_id=1)
        self.assert_native_retired()
        self.assertTrue(self.backend.safety.estop_active)
        # The existing scenario transition may refresh the E-stop timestamp;
        # it must not release the operator's latched stop.
        self.assertGreaterEqual(self.backend.safety.estop_at, estop_at)
        self.assertEqual((self.state.robot_id, self.state.robot_profile), (1, 'Hero'))
        self.assertEqual((self.backend._native_0310_dropped_chunks,
                          self.backend._native_0310_out_of_order_chunks,
                          self.backend._native_0310_recovery_dropped_chunks,
                          self.backend._native_0310_decoder_restarts), (13, 14, 15, 16))

    def test_actual_referee_profile_switch_retires_native_sample(self):
        from rm_client.referee_profiles import STUDENT_PREVIEW_PROFILE
        self.backend.set_referee_profile(STUDENT_PREVIEW_PROFILE, start_video=False)
        self.assertEqual(self.state.referee_profile, STUDENT_PREVIEW_PROFILE)
        self.assert_native_retired()
        self.assertEqual((self.state.robot_id, self.state.robot_profile), (1, 'Hero'))

    def test_same_profile_noop_preserves_valid_current_sample(self):
        before = {name: getattr(self.state, name) for name in NATIVE}
        self.backend.set_referee_profile(self.state.referee_profile, start_video=False)
        self.assertEqual({name: getattr(self.state, name) for name in NATIVE}, before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
