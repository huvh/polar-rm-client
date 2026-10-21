"""Presence/units regression for the restored V2 descriptor projection."""
import unittest
from types import SimpleNamespace
from rm_client.model import RobotState
from rm_client.backend.referee.rm2026 import codec as v1
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.rm2026_v2.state_adapter import Rm2026V2StateAdapter
from rm_client.backend.referee.wire import encode_uint, encode_float, encode_int, encode_packed_ints
from rm_client.backend.safety import OfficialSafety


class CompleteProjectionTests(unittest.TestCase):
    def setUp(self):
        self.state = RobotState()
        self.adapter = Rm2026V2StateAdapter(SimpleNamespace(
            safety=OfficialSafety(), _last_logged_stage="NOT_STARTED",
            field_log=SimpleNamespace(emit=lambda *a, **kw: None)))

    def apply(self, name, payload):
        self.adapter._apply_one(self.state, name, codec.decode_message(name, payload))

    def test_explicit_zero_static_capabilities_are_not_omission(self):
        for field, attribute in ((9, 'max_health'), (10, 'max_heat'),
                                 (12, 'power_limit'), (13, 'max_buffer_energy'),
                                 (14, 'max_chassis_energy')):
            with self.subTest(field=field):
                self.apply('RobotStaticStatus', encode_uint(field, 123))
                self.apply('RobotStaticStatus', encode_uint(8, 1))
                self.assertEqual(getattr(self.state, attribute), 123)
                self.apply('RobotStaticStatus', encode_uint(field, 0))
                self.assertEqual(getattr(self.state, attribute), 0)
        self.apply('RobotStaticStatus', encode_float(11, 0))
        self.assertEqual(self.state.heat_cooldown_rate, 0)

    def test_rune_score_preserves_units_and_mock_progress(self):
        progress = self.state.energy_rune_progress
        self.apply('RuneStatusSync', encode_uint(1, 2) + encode_float(3, 8.5))
        self.assertEqual(self.state.rune_status['average_rings'], 8.5)
        self.assertEqual(self.state.energy_rune_progress, progress)
        self.apply('RuneStatusSync', encode_uint(2, 4))
        self.assertEqual(self.state.rune_status['average_rings'], 8.5)
        self.apply('RuneStatusSync', encode_uint(1, 3))
        self.assertNotIn('average_rings', self.state.rune_status)

    def test_damage_partial_presence_zero_and_round_retirement(self):
        self.apply('GlobalUnitStatus', encode_uint(13, 23) + encode_uint(14, 42))
        self.apply('GlobalUnitStatus', encode_uint(13, 0))
        self.assertEqual((self.state.total_damage_ally, self.state.total_damage_enemy), (0, 42))
        self.apply('GameStatus', encode_uint(1, self.state.current_round + 1))
        self.assertEqual((self.state.total_damage_ally, self.state.total_damage_enemy), (None, None))

    def test_shared_v1_signed_repeated_mixed_forms(self):
        raw = encode_int(12, -1) + encode_packed_ints(12, [-2, 3])
        self.assertEqual(v1.decode_message('GlobalUnitStatus', raw)['robot_bullets'], [-1, -2, 3])

    def test_radar_alias_reaches_consumer(self):
        self.apply('RadarInfoToClient', bytes.fromhex('0a07086410c8011802'))
        self.assertEqual(self.state.radar_detections[0]['target_pos_x'], 100)
        self.assertEqual(self.state.radar_detections[0]['is_high_light'], 2)

if __name__ == '__main__': unittest.main()
