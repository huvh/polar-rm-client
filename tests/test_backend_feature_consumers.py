"""Offline consumer boundaries: no socket, device, or command publisher is started."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.control import describe_km_policy
from rm_client.economy import EconomyCommandBridge, available_actions
from rm_client.hero_lob import HeroLobPlanner
from rm_client.match_chat import ChatEventAdapter, MatchChatController
from rm_client.model import RobotState
from rm_client.vision import (ArmorObservation, VisionLossEvidence, VisionResult,
    TongjiVisionBridge, PACKET_HEADER, PROTOCOL_MAGIC, PROTOCOL_VERSION, PACKET_RESULT)


class FeatureConsumerTests(unittest.TestCase):
    def test_text_and_nonboolean_flags_never_create_positive_evidence(self):
        for value in ('false', 'true', '0', '1', '', None, [], {}, 2, -1, 1.0):
            with self.subTest(value=value):
                armor = ArmorObservation.from_payload(dict(predicted=value, aim=value, held=value))
                self.assertFalse(armor.predicted or armor.aim or armor.held)
                result = VisionResult.from_payload(1, 100, dict(calibrated=value))
                self.assertFalse(result.calibrated)
                evidence = VisionLossEvidence.from_payload(dict(probe_dark=value, moving_fast=value, near_edge=value))
                self.assertFalse(evidence.probe_dark or evidence.moving_fast or evidence.near_edge)
        for value in (True, 1):
            self.assertTrue(ArmorObservation.from_payload(dict(aim=value)).aim)
            self.assertTrue(VisionResult.from_payload(1, 100, dict(calibrated=value)).calibrated)

    def test_nonfinite_result_numbers_are_rejected(self):
        for key in ('inference_fps', 'latency_ms', 'aim_yaw_deg', 'aim_pitch_deg'):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    VisionResult.from_payload(1, 100, {key: value})

    def test_nonfinite_armor_numbers_and_geometry_are_rejected(self):
        for key in ('confidence', 'distance_m', 'depth_m', 'yaw_rad', 'light_strength'):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    ArmorObservation.from_payload({key: value})
        for key in ('points', 'back_points'):
            for value in (math.nan, math.inf, 'bad', None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    ArmorObservation.from_payload({key: [[1, value]]})

    def test_invalid_loss_evidence_is_not_retained(self):
        for key in ('light_strength', 'baseline_strength', 'target_id', 'sequence'):
            for value in (math.nan, math.inf, -math.inf, 'bad'):
                self.assertIsNone(VisionLossEvidence.from_payload({key: value}))

    def test_dimensions_and_timestamp_bounds(self):
        for key, value in (('source_width', 0), ('source_height', -1), ('source_width', 16385),
                           ('timestamp_ns', -1), ('timestamp_ns', 2**64)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                VisionResult.from_payload(1, 100, {key: value})
        self.assertEqual(VisionResult.from_payload(1, 100, {'source_width':16384}).source_width, 16384)

    def test_bad_packet_does_not_kill_reader_or_admit_result(self):
        bridge = TongjiVisionBridge()
        bridge.running = True
        callbacks = []
        bridge.on_result = callbacks.append
        for seq, data in ((1, {'aim_yaw_deg':math.nan}), (2, {'calibrated':True})):
            payload = json.dumps(data).encode()
            bridge._receive_buffer.extend(PACKET_HEADER.pack(PROTOCOL_MAGIC, PROTOCOL_VERSION,
                PACKET_RESULT, seq, 100, len(payload)) + payload)
        bridge._parse_packets()
        self.assertTrue(bridge.running)
        self.assertEqual(bridge.results_received, 1)
        self.assertEqual([result.sequence for result in callbacks], [2])
        self.assertEqual(bridge.last_result.sequence, 2)
        self.assertIn('字段无效', bridge.last_error)

    def test_future_and_stale_vision_results_not_fresh(self):
        bridge = TongjiVisionBridge()
        with patch('rm_client.vision.time.time_ns', return_value=1_000_000_000):
            for timestamp, admitted in ((1_000_000_001, False), (1_000_000_000, True),
                                         (600_000_000, True), (500_000_000, False)):
                bridge.last_result = VisionResult.from_payload(1, timestamp, {})
                self.assertEqual(bridge.latest_result() is not None, admitted)

    @staticmethod
    def ready_state():
        return RobotState(robot_profile='Hero', native_telemetry_at=100., native_gimbal_online=True,
            hero_lob_yaw_calibrated=True, hero_lob_pitch_calibrated=True,
            hero_lob_relocalization_valid=True, current_stage='MATCH', remaining_ammo=10,
            current_heat=20, max_heat=240)

    def test_valid_lob_readiness_retains_existing_gates(self):
        state = self.ready_state()
        self.assertTrue(HeroLobPlanner.readiness(state, now=100.1, hero_range_profile=True).ready)
        self.assertFalse(HeroLobPlanner.readiness(state, now=100.1).ready)
        state.robot_profile = 'Infantry1'
        self.assertFalse(HeroLobPlanner.readiness(state, now=100.1, hero_range_profile=True).ready)

    def test_lob_readiness_flags_require_actual_true_not_truthy_strings(self):
        for field, reason in (('native_gimbal_online', 'gimbal offline'),
                              ('hero_lob_yaw_calibrated', 'yaw not calibrated'),
                              ('hero_lob_pitch_calibrated', 'pitch not calibrated'),
                              ('hero_lob_relocalization_valid', 'relocalization invalid')):
            for value in ('false', 'true', 0, 1, None, False):
                state = self.ready_state()
                setattr(state, field, value)
                result = HeroLobPlanner.readiness(state, now=100.1, hero_range_profile=True)
                self.assertFalse(result.ready, (field,value))
                self.assertIn(reason,result.reasons)
            state = self.ready_state()
            setattr(state,field,True)
            self.assertTrue(HeroLobPlanner.readiness(state,now=100.1,hero_range_profile=True).ready)

    def test_unknown_and_nonfinite_quaternion_fails_closed(self):
        for quaternion in (None, (), (0,0,0,0), (math.nan,0,0,1), (math.inf,0,0,1), ('bad',0,0,1)):
            self.assertTrue(math.isinf(HeroLobPlanner.quaternion_roll_deg(quaternion)))
            state = self.ready_state()
            state.native_quaternion = quaternion
            self.assertIn('roll/yaw coupling guard', HeroLobPlanner.readiness(state, now=100.1,
                hero_range_profile=True).reasons)

    def test_scaled_quaternion_preserves_physical_angle(self):
        q = (math.sin(math.radians(5)/2), 0, 0, math.cos(math.radians(5)/2))
        self.assertAlmostEqual(HeroLobPlanner.quaternion_roll_deg(q), 5.)
        self.assertAlmostEqual(HeroLobPlanner.quaternion_roll_deg(tuple(v*5 for v in q)), 5.)

    def test_missing_future_nonfinite_lob_timestamp_is_stale(self):
        for timestamp in (None, 0, 101, math.nan, math.inf, -math.inf, 'bad'):
            state = self.ready_state()
            state.native_telemetry_at = timestamp
            result = HeroLobPlanner.readiness(state, now=100.1, hero_range_profile=True)
            self.assertIn('telemetry stale', result.reasons)
            self.assertFalse(result.ready)

    def test_missing_nonfinite_heat_or_capacity_blocks_lob(self):
        for key, values in (('current_heat', (None, math.nan, math.inf, -1)),
                            ('max_heat', (None, math.nan, math.inf, 0, -1))):
            for value in values:
                state = self.ready_state()
                setattr(state, key, value)
                self.assertIn('heat guard', HeroLobPlanner.readiness(state, now=100.1,
                    hero_range_profile=True).reasons)

    @staticmethod
    def pending(mock=True):
        state = RobotState(economy_mock_mode=True)
        offer = next(o for o in available_actions(state) if o.enabled and '_17_' in o.key)
        bridge = EconomyCommandBridge()
        if not mock:
            bridge.sender = lambda request: True
        transaction = bridge.submit(state, offer, mock=mock, now=10.)
        return state, bridge, transaction

    def test_mock_request_cannot_mutate_new_context(self):
        changes = dict(referee_profile='changed', match_mode='RMUL3v3', robot_profile='Hero',
            robot_id=1, alliance_color='changed', current_round=2,
            mock_simulation_enabled=False, economy_mock_mode=False)
        for key, value in changes.items():
            with self.subTest(key=key):
                state, bridge, transaction = self.pending()
                baseline = state.remaining_economy, state.remaining_ammo
                setattr(state, key, value)
                bridge.update(state, now=11.)
                self.assertEqual(transaction.status, 'rejected')
                self.assertIn('不代表服务器撤销', transaction.message)
                self.assertEqual((state.remaining_economy, state.remaining_ammo), baseline)

    def test_equal_replacement_owner_does_not_complete_old_request(self):
        state, bridge, transaction = self.pending()
        replacement = deepcopy(state)
        bridge.update(replacement, now=11.)
        self.assertEqual(transaction.status, 'rejected')

    def test_same_context_mock_request_still_completes(self):
        state, bridge, transaction = self.pending()
        ammo = state.remaining_ammo
        bridge.update(state, now=11.)
        self.assertEqual(transaction.status, 'succeeded')
        self.assertGreater(state.remaining_ammo, ammo)

    def test_changed_real_context_cannot_misattribute_telemetry_as_ack(self):
        state, bridge, transaction = self.pending(mock=False)
        state.current_round += 1
        state.remaining_ammo += 100
        state.economy_status_revision += 1
        state.economy_command_status = 'accepted'
        bridge.update(state, now=11.)
        self.assertEqual(transaction.status, 'rejected')

    def test_chat_prepare_countdown_is_not_match_end(self):
        state = RobotState(official_state_active=True, current_stage='PREPARE')
        chat = MatchChatController()
        adapter = ChatEventAdapter(chat)
        for remaining in (61, 59):
            state.stage_countdown_sec = remaining
            adapter.poll(state, now=100-remaining)
        self.assertFalse(any('Match ends' in m.text for m in chat.messages))
        state.current_stage = 'MATCH'
        for remaining in (61,59):
            state.stage_countdown_sec = remaining
            adapter.poll(state, now=200-remaining)
        self.assertEqual([m.text for m in chat.messages if 'Match ends' in m.text], ['Match ends in 60 seconds'])

    def test_chat_context_change_does_not_cross_previous_round_countdown(self):
        state = RobotState(official_state_active=True, current_stage='MATCH', stage_countdown_sec=61)
        chat = MatchChatController()
        adapter = ChatEventAdapter(chat)
        adapter.poll(state, now=1.)
        state.current_round += 1
        state.stage_countdown_sec=59
        adapter.poll(state, now=2.)
        self.assertFalse(any('Match ends' in m.text for m in chat.messages))

    def test_mock_chat_retains_legacy_countdown(self):
        state = RobotState(stage_countdown_sec=61)
        chat = MatchChatController()
        adapter = ChatEventAdapter(chat)
        adapter.poll(state, now=1.)
        state.stage_countdown_sec=59
        adapter.poll(state, now=2.)
        self.assertTrue(any('Match ends in 60' in m.text for m in chat.messages))

    def test_nonfinite_policy_description_is_unknown_not_authority(self):
        for value in (math.nan, math.inf, -math.inf, None, 'false', 'bad', [], {}):
            self.assertEqual(describe_km_policy(value)[:2], ('?', None))
        for value, name, active in ((0,'none',False),(1,'rc',False),(2,'vt',True),(3,'rc_vt',True),(4,'vt_rc',True)):
            self.assertEqual(describe_km_policy(value)[:2], (name, active))

    def test_observed_own_zero_capability_overrides_demo_percent(self):
        state = RobotState(robot_id=3, max_buffer_energy=0, current_buffer_energy=0, capacitor_percent=62)
        state.robot_statics[3] = {'max_buffer_energy':0}
        self.assertEqual(state.effective_capacitor_percent, 0)
        state.robot_statics[3] = {'max_buffer_energy':100}
        state.max_buffer_energy=100
        state.current_buffer_energy=41
        self.assertEqual(state.effective_capacitor_percent, 41)

    def test_unobserved_or_other_robot_zero_keeps_private_fallback(self):
        state = RobotState(robot_id=3, max_buffer_energy=0, current_buffer_energy=0, capacitor_percent=62)
        self.assertEqual(state.effective_capacitor_percent, 62)
        state.robot_statics[1]={'max_buffer_energy':0}
        self.assertEqual(state.effective_capacitor_percent, 62)
        state.robot_statics[3]={'max_buffer_energy':False}
        self.assertEqual(state.effective_capacitor_percent, 62)


if __name__ == '__main__':
    unittest.main()
