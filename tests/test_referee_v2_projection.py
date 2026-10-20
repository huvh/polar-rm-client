"""Pure V2 wire→state projection; no registered profile or native endpoint."""
from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
import unittest

from rm_client import model
from rm_client.model import RobotState
from rm_client.backend.referee.rm2026 import codec as v1_codec
from rm_client.backend.referee.rm2026.state_adapter import Rm2026StateAdapter
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.rm2026_v2.state_adapter import Rm2026V2StateAdapter
from rm_client.backend.referee.registry import get_profile
from rm_client.referee_profiles import supported_profiles, UnsupportedRefereeProfile
from rm_client.backend.safety import OfficialSafety


def integer(number, value):
    def varint(n):
        out = bytearray()
        while n >= 128:
            out.append((n & 127) | 128)
            n >>= 7
        return bytes(out + bytes([n]))
    return varint(number << 3) + varint(value)


def method(path, owner, name):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {'RobotState': RobotState, 'time': SimpleNamespace(perf_counter=lambda: 1234.)}
    source = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), fn], type_ignores=[])
    exec(compile(ast.fix_missing_locations(source), str(path), 'exec'), ns)
    return ns[name]


class Host:
    def __init__(self):
        self.safety = OfficialSafety()
        self._last_logged_stage = 'NOT_STARTED'
        self.events = []
        self.field_log = SimpleNamespace(emit=lambda *a, **kw: self.events.append((a, kw)))


class V2ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.state = RobotState()
        self.host = Host()
        self.adapter = Rm2026V2StateAdapter(self.host)

    def deliver(self, name='GameStatus', **values):
        numbers = {'current_round': 1, 'current_stage': 5, 'game_result': 9, 'end_reason': 10}
        if name == 'SentryStatusSync':
            numbers = {'posture_id': 1, 'is_weakened': 2, 'is_powered': 3}
        payload = b''.join(integer(numbers[key], int(value)) for key, value in values.items())
        data = codec.decode_message(name, payload)
        self.assertTrue(data)
        self.adapter._apply_one(self.state, name, data)
        return data

    def values(self):
        return self.state.game_result, self.state.end_reason, self.state.settlement_round

    def settle(self, result=1, reason=2):
        self.deliver(current_stage=5, game_result=result, end_reason=reason)

    def test_defaults_are_unobserved_and_not_constructor_arguments(self):
        self.assertEqual(self.values(), (None, None, None))
        self.assertNotIn('is_powered', self.state.sentry_status)
        definitions = {item.name: item for item in fields(RobotState)}
        for name in ('game_result', 'end_reason', 'settlement_round'):
            self.assertFalse(definitions[name].init)

    def test_explicit_zero_is_draw_and_all_documented_values_survive(self):
        for result in (0, 1, 2):
            for reason in range(1, 10):
                with self.subTest(result=result, reason=reason):
                    self.settle(result, reason)
                    self.assertEqual(self.values(), (result, reason, 1))

    def test_missing_decoder_zeros_are_not_observations(self):
        data = self.deliver(current_stage=5)
        self.assertEqual((data['game_result'], data['end_reason']), (0, 0))
        self.assertEqual(data['__present__'], frozenset({5}))
        self.assertEqual(self.values(), (None, None, 1))

    def test_result_before_first_stage_is_not_borrowed_later(self):
        self.deliver(game_result=0, end_reason=7)
        self.assertEqual(self.values(), (None, None, None))
        self.deliver(current_stage=5)
        self.assertEqual(self.values(), (None, None, 1))

    def test_same_settlement_partial_updates_preserve_missing_fields(self):
        self.settle()
        self.deliver(game_result=0)
        self.assertEqual(self.values(), (0, 2, 1))
        self.deliver(end_reason=7)
        self.assertEqual(self.values(), (0, 7, 1))
        self.deliver(current_stage=5)
        self.assertEqual(self.values(), (0, 7, 1))

    def test_explicit_255_remains_unavailable_and_not_synthesized(self):
        self.settle()
        self.deliver(game_result=255, end_reason=255)
        self.assertEqual(self.values(), (255, 255, 1))
        self.deliver(current_stage=4, game_result=255, end_reason=255)
        self.assertEqual(self.values(), (None, None, None))

    def test_nonsettlement_stages_ignore_even_present_result_fields(self):
        for stage in range(5):
            with self.subTest(stage=stage):
                self.settle()
                self.deliver(current_stage=stage, game_result=0, end_reason=7)
                self.assertEqual(self.values(), (None, None, None))
                self.assertEqual(self.host.safety.current_stage, str(stage))

    def test_stage_exit_and_reentry_need_new_observations(self):
        self.settle()
        self.deliver(current_stage=4)
        self.assertEqual(self.values(), (None, None, None))
        self.deliver(current_stage=5)
        self.assertEqual(self.values(), (None, None, 1))

    def test_round_only_change_retires_witness_despite_retained_stage(self):
        self.settle()
        self.deliver(current_round=2)
        self.assertEqual(self.state.current_stage, 'SETTLEMENT')
        self.assertEqual(self.values(), (None, None, None))
        self.deliver(game_result=0, end_reason=7)
        self.assertEqual(self.values(), (None, None, None))
        self.deliver(current_stage=5)
        self.deliver(game_result=2)
        self.assertEqual(self.values(), (2, None, 2))

    def test_new_round_and_settlement_in_one_packet_admit_present_values(self):
        self.settle()
        self.deliver(current_round=2, current_stage=5, game_result=0)
        self.assertEqual(self.values(), (0, None, 2))

    def test_same_round_update_does_not_clear_current_observations(self):
        self.settle()
        self.deliver(current_round=1)
        self.assertEqual(self.values(), (1, 2, 1))

    def test_round_rewind_is_also_a_new_local_context(self):
        self.deliver(current_round=3, current_stage=5, game_result=2, end_reason=9)
        self.deliver(current_round=1)
        self.assertEqual(self.values(), (None, None, None))

    def test_witness_cannot_be_inferred_from_directly_seeded_stage(self):
        self.state.current_stage = 'SETTLEMENT'
        self.deliver(game_result=0, end_reason=7)
        self.assertEqual(self.values(), (None, None, None))

    def test_unrecognized_enums_are_retained_without_interpretation(self):
        self.settle(99, 0)
        self.assertEqual(self.values(), (99, 0, 1))

    def test_sentry_boost_omission_false_and_other_fields(self):
        self.deliver('SentryStatusSync', is_powered=True, posture_id=2)
        self.assertEqual(self.state.sentry_status, {'posture_id': 2, 'is_powered': True})
        self.deliver('SentryStatusSync', is_weakened=False)
        self.assertEqual(self.state.sentry_status, {'posture_id': 2, 'is_powered': True, 'is_weakened': False})
        self.deliver('SentryStatusSync', is_powered=False)
        self.assertIs(self.state.sentry_status['is_powered'], False)
        self.assertEqual(self.state.sentry_status['posture_id'], 2)

    def test_sentry_absent_boost_does_not_publish_decoded_false(self):
        self.deliver('SentryStatusSync', posture_id=1)
        self.assertNotIn('is_powered', self.state.sentry_status)

    def test_common_presence_dependent_identity_and_performance_are_preserved(self):
        payload = integer(4, 107) + integer(6, 0) + integer(8, 3) + integer(9, 400)
        self.adapter._apply_one(self.state, 'RobotStaticStatus', codec.decode_message('RobotStaticStatus', payload))
        self.assertEqual((self.state.robot_id, self.state.level, self.state.max_health), (107, 3, 400))
        self.assertEqual(self.state.performance_sync, {'shooter': 0})
        self.assertEqual(self.state.robot_statics[107]['robot_id'], 107)

    def test_v1_never_adopts_v2_fields_or_changes_new_observations(self):
        v1 = Rm2026StateAdapter(self.host)
        data = codec.decode_message('GameStatus', integer(5, 5) + integer(9, 0) + integer(10, 7))
        v1._apply_one(self.state, 'GameStatus', data)
        self.assertEqual(self.values(), (None, None, None))
        v1._apply_one(self.state, 'SentryStatusSync', codec.decode_message('SentryStatusSync', integer(3, 1)))
        self.assertEqual(self.state.sentry_status, {})
        self.assertEqual(v1_codec.decode_message('SentryStatusSync', integer(3, 1)), {})

    def test_no_metadata_compatibility_mapping_is_retained(self):
        self.adapter._apply_one(self.state, 'GameStatus', {'current_stage': 5, 'game_result': 0})
        self.assertEqual(self.values(), (0, None, 1))
        self.adapter._apply_one(self.state, 'SentryStatusSync', {'is_powered': False, 'extension': 'keep'})
        self.assertEqual(self.state.sentry_status, {'is_powered': False, 'extension': 'keep'})

    def test_failed_direct_mapping_cannot_seed_later_stage_only_result(self):
        for incoming in ({'game_result': 'bad', 'end_reason': 7},
                         {'game_result': 0, 'end_reason': 'bad'}):
            with self.subTest(incoming=incoming):
                self.setUp()
                with self.assertRaises(ValueError):
                    self.adapter._apply_one(self.state, 'GameStatus',
                                            {'current_stage': 5, **incoming})
                self.assertEqual(self.values(), (None, None, None))
                self.assertEqual(self.state.current_stage, 'NOT_STARTED')
                self.assertFalse(self.host.events)
                self.deliver(current_stage=5)
                self.assertEqual(self.values(), (None, None, 1))

    def test_failed_new_round_conversion_keeps_required_retirement_and_common_prefix(self):
        self.settle()
        self.host.events.clear()
        with self.assertRaises(ValueError):
            self.adapter._apply_one(self.state, 'GameStatus', {
                'current_round': 2, 'current_stage': 5, 'red_score': 8,
                'game_result': 0, 'end_reason': 'bad'})
        self.assertEqual(self.values(), (None, None, None))
        self.assertEqual((self.state.current_round, self.state.red_score,
                          self.state.current_stage), (2, 8, 'SETTLEMENT'))
        self.assertFalse(self.host.events)
        self.deliver(current_stage=5)
        self.assertEqual(self.values(), (None, None, 2))

    def test_failed_same_round_conversion_retains_prior_accepted_observations(self):
        self.settle()
        for incoming in ({'game_result': 'bad', 'end_reason': 7},
                         {'game_result': 0, 'end_reason': 'bad'}):
            with self.subTest(incoming=incoming), self.assertRaises(ValueError):
                self.adapter._apply_one(self.state, 'GameStatus', incoming)
            self.assertEqual(self.values(), (1, 2, 1))
        self.deliver(current_stage=5)
        self.assertEqual(self.values(), (1, 2, 1))

    def test_inapplicable_bad_values_are_not_converted_and_exit_still_retires(self):
        self.adapter._apply_one(self.state, 'GameStatus',
                                {'game_result': 'bad', 'end_reason': 'bad'})
        self.assertEqual(self.values(), (None, None, None))
        self.settle()
        self.adapter._apply_one(self.state, 'GameStatus',
                                {'current_stage': 4, 'game_result': 'bad', 'end_reason': 'bad'})
        self.assertEqual(self.values(), (None, None, None))
        self.assertEqual(self.state.current_stage, 'MATCH')

    def test_outcome_conversion_errors_keep_identity_without_new_publication(self):
        for error in (RuntimeError('int'), KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                class InvalidOutcome:
                    def __int__(self):
                        raise error
                with self.assertRaises(type(error)) as caught:
                    self.adapter._apply_one(self.state, 'GameStatus', {
                        'current_stage': 5, 'game_result': 0, 'end_reason': InvalidOutcome()})
                self.assertIs(caught.exception, error)
                self.assertEqual(self.values(), (None, None, None))
                self.assertEqual(self.state.current_stage, 'NOT_STARTED')

    def test_unknown_and_malformed_presence_boundaries(self):
        self.settle()
        self.adapter._apply_one(self.state, 'GameStatus', {'__present__': (999,), 'game_result': 0})
        self.assertEqual(self.values(), (1, 2, 1))
        for bad in (None, [[]]):
            with self.subTest(presence=bad), self.assertRaises(TypeError):
                self.adapter._apply_one(self.state, 'GameStatus', {'__present__': bad, 'current_stage': 4})
            self.assertEqual(self.values(), (1, 2, 1))

    def test_owner_reset_is_idempotent_and_only_changes_three_fields(self):
        self.settle()
        before = dict(vars(self.state))
        self.state.clear_match_settlement()
        self.state.clear_match_settlement()
        expected = before | dict(game_result=None, end_reason=None, settlement_round=None)
        self.assertEqual(vars(self.state), expected)

    def test_actual_manager_reset_retires_settlement_and_sentry_only_at_existing_epoch(self):
        self.settle()
        self.deliver('SentryStatusSync', is_powered=True)
        self.state.red_score, self.state.stage_countdown_sec = 8, 12
        self.state.referee_kill_count = 3
        before = (self.state.current_round, self.state.red_score, self.state.stage_countdown_sec,
                  self.state.robot_profile, self.state.referee_profile, self.state.referee_kill_count)
        reset = method(Path(model.__file__).parent/'backend/manager.py', 'BackendManager', '_reset_state_for_scenario')
        host = SimpleNamespace(_clear_mock_frontend_state=lambda state: None,
            polar_bridge=SimpleNamespace(reset=lambda: None),
            polar_arbiter=SimpleNamespace(invalidate_pending_divergence=lambda: None, clear_lockout=lambda: None),
            polar_motion=SimpleNamespace(reset=lambda: None))
        reset(host, self.state)
        self.assertEqual(self.values(), (None, None, None))
        self.assertEqual(self.state.sentry_status, {})
        self.assertEqual(self.state.current_stage, 'NOT_STARTED')
        self.assertEqual(before, (self.state.current_round, self.state.red_score, self.state.stage_countdown_sec,
                  self.state.robot_profile, self.state.referee_profile, self.state.referee_kill_count))

    def test_actual_match_mode_seed_retires_live_settlement_only(self):
        self.settle()
        self.state.sentry_status['is_powered'] = True
        snapshot = (('unchanged', 'frozen student snapshot'),)
        host = SimpleNamespace(state=self.state, alliance_side=lambda: 'Blue',
                               student_ui=SimpleNamespace(settlement=snapshot))
        seed = method(Path(model.__file__).parent/'ui/polar/mixins/persistence_mixin.py',
                      'PersistenceMixin', 'seed_match_state')
        seed(host, SimpleNamespace(key='RMUC7v7', title='Match', duration_sec=420))
        self.assertEqual(self.values(), (None, None, None))
        self.assertEqual(self.state.current_stage, 'NOT_STARTED')
        self.assertEqual(self.state.sentry_status, {'is_powered': True})
        self.assertIs(host.student_ui.settlement, snapshot)
        self.assertEqual((self.state.current_round, self.state.alliance_color), (1, 'Blue'))

    def test_callbacks_observe_projection_before_their_effects(self):
        seen = []
        original = self.host.safety.update_stage
        def update(stage):
            seen.append((self.state.current_stage, self.values()))
            original(stage)
        self.host.safety.update_stage = update
        self.settle(0, 7)
        self.assertEqual(seen, [('SETTLEMENT', (0, 7, 1))])

    def test_actual_base_safety_and_log_resets_are_not_undone(self):
        for port in ('safety', 'log'):
            with self.subTest(port=port):
                self.setUp()
                if port == 'safety':
                    original = self.host.safety.update_stage
                    def update(stage):
                        original(stage)
                        self.state.clear_match_settlement()
                    self.host.safety.update_stage = update
                else:
                    self.host.field_log.emit = lambda *a, **kw: self.state.clear_match_settlement()
                self.settle()
                self.assertEqual(self.values(), (None, None, None))

    def test_callback_failure_retains_primary_identity_and_existing_common_prefix(self):
        for error in (RuntimeError('log'), KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                def fail(*a, **kw):
                    self.state.clear_match_settlement()
                    raise error
                self.host.field_log.emit = fail
                with self.assertRaises(type(error)) as caught:
                    self.settle()
                self.assertIs(caught.exception, error)
                self.assertEqual(self.state.current_stage, 'SETTLEMENT')
                self.assertEqual(self.host.safety.current_stage, '5')
                self.assertEqual(self.values(), (None, None, None))

    def test_profile_is_explicitly_registered_without_alias_fallback(self):
        self.assertIn('rm2026-v2.0.0', supported_profiles())
        self.assertIs(get_profile('rm2026-v2.0.0').codec, codec)
        with self.assertRaises(UnsupportedRefereeProfile):
            get_profile('rm2026-v2')


if __name__ == '__main__':
    unittest.main()
