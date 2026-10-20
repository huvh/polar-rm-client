"""Pure aerial observations; status never grants publication permission."""
from __future__ import annotations

import ast
import copy
from dataclasses import fields
import itertools
from pathlib import Path
from types import SimpleNamespace
import unittest

from rm_client import model
from rm_client.model import RobotState
from rm_client.backend.referee.rm2026.state_adapter import Rm2026StateAdapter
from rm_client.backend.referee.rm2026_v2.state_adapter import Rm2026V2StateAdapter
from rm_client.backend.referee.student_legacy.state_adapter import StudentLegacyStateAdapter
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.registry import get_profile
from rm_client.referee_profiles import UnsupportedRefereeProfile
from rm_client.backend.safety import OfficialSafety, ControlState


NAMES = ('air_support_is_being_targeted', 'air_support_shooter_status')
NUMBERS = {'airsupport_status': 1, 'left_time': 2, 'cost_coins': 3,
           'is_being_targeted': 4, 'shooter_status': 5}


def integer(number, value):
    def varint(value):
        result = bytearray()
        while value >= 128:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
        return bytes(result)
    return varint(number << 3) + varint(value)


def actual_method(path, owner, name):
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    fn = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(body=[ast.ImportFrom(module='__future__',
        names=[ast.alias(name='annotations')], level=0), fn], type_ignores=[])
    ns = {'RobotState': RobotState, 'time': SimpleNamespace(perf_counter=lambda: 1234.)}
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), ns)
    return ns[name]


class V2AirProjectionTests(unittest.TestCase):
    def setUp(self):
        self.state = RobotState(start_time=1.)
        self.events = []
        self.host = SimpleNamespace(safety=OfficialSafety(), _last_logged_stage='NOT_STARTED',
            field_log=SimpleNamespace(emit=lambda *a, **kw: self.events.append((a, kw))))
        self.adapter = Rm2026V2StateAdapter(self.host)

    def values(self):
        return tuple(getattr(self.state, name) for name in NAMES)

    def deliver(self, **values):
        payload = b''.join(integer(NUMBERS[name], value) for name, value in values.items())
        data = codec.decode_message('AirSupportStatusSync', payload)
        self.assertTrue(data)
        self.adapter._apply_one(self.state, 'AirSupportStatusSync', data)
        return data

    def test_defaults_are_unknown_and_constructor_unchanged(self):
        self.assertEqual(self.values(), (None, None))
        declarations = {item.name: item for item in fields(RobotState)}
        for name in NAMES:
            self.assertFalse(declarations[name].init)
            with self.assertRaises(TypeError):
                RobotState(**{name: 0})

    def test_full_packet_projects_common_and_new_fields(self):
        self.deliver(airsupport_status=1, left_time=30, cost_coins=12,
                     is_being_targeted=1, shooter_status=2)
        self.assertEqual(self.values(), (1, 2))
        self.assertEqual((self.state.air_support_active, self.state.air_support_can_free,
                          self.state.air_support_free_time_sec, self.state.air_support_cost_coins),
                         (True, True, 30, 12))

    def test_decoder_defaults_do_not_become_observations(self):
        data = self.deliver(left_time=0)
        self.assertEqual((data['is_being_targeted'], data['shooter_status']), (0, 0))
        self.assertEqual(data['__present__'], frozenset({2}))
        self.assertEqual(self.values(), (None, None))

    def test_partial_omission_retains_previous_observations(self):
        self.deliver(is_being_targeted=1, shooter_status=2)
        self.deliver(left_time=8)
        self.assertEqual(self.values(), (1, 2))
        self.deliver(shooter_status=1)
        self.assertEqual(self.values(), (1, 1))
        self.deliver(is_being_targeted=0)
        self.assertEqual(self.values(), (0, 1))

    def test_explicit_zero_and_all_documented_values_are_preserved(self):
        for targeted, shooter in itertools.product(range(2), range(3)):
            with self.subTest(targeted=targeted, shooter=shooter):
                self.deliver(is_being_targeted=targeted, shooter_status=shooter)
                self.assertEqual(self.values(), (targeted, shooter))
                self.assertIs(type(self.state.air_support_is_being_targeted), int)
                self.assertIs(type(self.state.air_support_shooter_status), int)

    def test_unknown_enums_are_raw_and_never_clamped_or_booleanized(self):
        self.deliver(is_being_targeted=99, shooter_status=4294967295)
        self.assertEqual(self.values(), (99, 4294967295))

    def test_wire_order_and_input_ownership(self):
        chunks = [integer(1, 0), integer(4, 1), integer(5, 2)]
        for order in itertools.permutations(chunks):
            data = codec.decode_message('AirSupportStatusSync', b''.join(order))
            before = copy.deepcopy(data)
            self.adapter._apply_one(self.state, 'AirSupportStatusSync', data)
            self.assertEqual(self.values(), (1, 2))
            self.assertEqual(data, before)

    def test_direct_compatibility_mapping_uses_present_keys(self):
        data = {'is_being_targeted': '0', 'shooter_status': '2', 'extension': 'keep'}
        before = dict(data)
        self.adapter._apply_one(self.state, 'AirSupportStatusSync', data)
        self.assertEqual(self.values(), (0, 2))
        self.assertEqual(data, before)
        self.adapter._apply_one(self.state, 'AirSupportStatusSync', {})
        self.assertEqual(self.values(), (0, 2))

    def test_metadata_filters_unobserved_mapping_keys(self):
        self.adapter._apply_one(self.state, 'AirSupportStatusSync', {
            'is_being_targeted': 1, 'shooter_status': 2, '__present__': frozenset({4})})
        self.assertEqual(self.values(), (1, None))

    def test_v1_and_student_keep_their_existing_dropped_field_behavior(self):
        for owner in (Rm2026StateAdapter, StudentLegacyStateAdapter):
            with self.subTest(owner=owner.__name__):
                self.state.air_support_is_being_targeted = 77
                self.state.air_support_shooter_status = 88
                owner(self.host)._apply_one(self.state, 'AirSupportStatusSync', {
                    'airsupport_status': 1, 'is_being_targeted': 0, 'shooter_status': 2,
                    '__present__': frozenset({1, 4, 5})})
                self.assertEqual(self.values(), (77, 88))
                self.assertTrue(self.state.air_support_active)

    def test_failed_either_conversion_does_not_publish_either_new_field(self):
        self.deliver(is_being_targeted=1, shooter_status=2)
        for bad in ({'is_being_targeted': 'bad', 'shooter_status': 0},
                    {'is_being_targeted': 0, 'shooter_status': 'bad'}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.adapter._apply_one(self.state, 'AirSupportStatusSync', bad)
                self.assertEqual(self.values(), (1, 2))

    def test_new_conversion_failure_preserves_existing_common_partial_prefix(self):
        before_revision = self.state.economy_status_revision
        with self.assertRaises(ValueError):
            self.adapter._apply_one(self.state, 'AirSupportStatusSync', {
                'airsupport_status': 1, 'left_time': 8, 'cost_coins': 12,
                'is_being_targeted': 1, 'shooter_status': 'bad'})
        self.assertEqual((self.state.air_support_active, self.state.air_support_free_time_sec,
                          self.state.air_support_can_free, self.state.air_support_cost_coins),
                         (True, 8, True, 12))
        self.assertEqual(self.values(), (None, None))
        self.assertEqual(self.state.economy_status_revision, before_revision)

    def test_existing_common_failure_prevents_new_hook_publication(self):
        with self.assertRaises(ValueError):
            self.adapter._apply_one(self.state, 'AirSupportStatusSync', {
                'airsupport_status': 1, 'left_time': 'bad',
                'is_being_targeted': 1, 'shooter_status': 2})
        self.assertTrue(self.state.air_support_active)
        self.assertEqual(self.values(), (None, None))

    def test_conversion_process_control_identity_and_no_partial_publication(self):
        for error in (RuntimeError('conversion'), KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(error=type(error).__name__):
                class BadInt:
                    def __int__(self):
                        raise error
                with self.assertRaises(type(error)) as caught:
                    self.adapter._apply_one(self.state, 'AirSupportStatusSync', {
                        'is_being_targeted': 1, 'shooter_status': BadInt()})
                self.assertIs(caught.exception, error)
                self.assertEqual(self.values(), (None, None))

    def test_owner_reset_is_idempotent_and_changes_only_its_two_fields(self):
        self.deliver(is_being_targeted=1, shooter_status=2)
        before = copy.deepcopy(vars(self.state))
        self.state.clear_air_support_observations()
        self.state.clear_air_support_observations()
        self.assertEqual(vars(self.state), before | {name: None for name in NAMES})

    def test_actual_manager_epoch_reset_retires_new_fields_preserving_legacy_air(self):
        self.deliver(airsupport_status=1, left_time=30, cost_coins=14,
                     is_being_targeted=1, shooter_status=2)
        before = (self.state.air_support_active, self.state.air_support_can_free,
                  self.state.air_support_free_time_sec, self.state.air_support_cost_coins)
        reset = actual_method(Path(model.__file__).parent/'backend/manager.py',
                              'BackendManager', '_reset_state_for_scenario')
        host = SimpleNamespace(_clear_mock_frontend_state=lambda state: None,
            polar_bridge=SimpleNamespace(reset=lambda: None),
            polar_arbiter=SimpleNamespace(invalidate_pending_divergence=lambda: None,
                                         clear_lockout=lambda: None),
            polar_motion=SimpleNamespace(reset=lambda: None))
        reset(host, self.state)
        reset(host, self.state)
        self.assertEqual(self.values(), (None, None))
        self.assertEqual(before, (self.state.air_support_active, self.state.air_support_can_free,
                         self.state.air_support_free_time_sec, self.state.air_support_cost_coins))

    def test_normal_stage_updates_do_not_invent_aerial_retirement_policy(self):
        self.deliver(is_being_targeted=1, shooter_status=2)
        for stage in (4, 5, 0):
            self.adapter._apply_one(self.state, 'GameStatus', {'current_stage': stage})
            self.assertEqual(self.values(), (1, 2))

    def test_actual_match_mode_seed_preserves_existing_aerial_policy(self):
        self.deliver(is_being_targeted=1, shooter_status=2)
        seed = actual_method(Path(model.__file__).parent/'ui/polar/mixins/persistence_mixin.py',
                             'PersistenceMixin', 'seed_match_state')
        host = SimpleNamespace(state=self.state, alliance_side=lambda: 'Blue')
        seed(host, SimpleNamespace(key='RMUC7v7', title='Match', duration_sec=420))
        self.assertEqual(self.values(), (1, 2))
        self.assertEqual(self.state.current_stage, 'NOT_STARTED')

    def test_new_observations_do_not_synthesize_economy_revision_or_ack(self):
        self.state.economy_status_revision = 7
        self.state.economy_command_status = 'pending'
        self.deliver(is_being_targeted=1, shooter_status=2)
        self.deliver(is_being_targeted=0, shooter_status=1)
        self.assertEqual((self.state.economy_status_revision,
                          self.state.economy_command_status), (7, 'pending'))
        self.assertEqual(self.events, [])

    def test_existing_support_active_revision_behavior_is_preserved(self):
        self.state.economy_status_revision = 7
        self.state.economy_command_status = 'pending'
        self.deliver(airsupport_status=1, is_being_targeted=1, shooter_status=2)
        self.assertEqual((self.state.economy_status_revision,
                          self.state.economy_command_status), (8, ''))

    def test_observed_status_does_not_grant_permission_or_accept_v2_alias(self):
        before = copy.deepcopy(vars(self.host.safety))
        self.deliver(is_being_targeted=1, shooter_status=2)
        self.assertEqual(vars(self.host.safety), before)
        self.assertEqual(self.host.safety.control_state, ControlState.LOCKED)
        with self.assertRaises(UnsupportedRefereeProfile):
            get_profile('rm2026-v2')


if __name__ == '__main__':
    unittest.main()
