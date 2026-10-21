"""Pure V2 peer request decisions; no transport, Safety, UI or native imports."""
import copy
import unittest

from rm_client.backend.referee.rm2026_v2 import codec, economy_rules as rules
from rm_client.backend.referee.rm2026_v2.observations import WireObservation, WireSnapshot, observe

G = 'GameStatus'
R = 'RobotStaticStatus'
A = 'AirSupportStatusSync'
E = 'GlobalLogisticsStatus'
P = 'PenaltyInfo'
NOW = 100.0
BASE = {
    (G, 'current_round'): 1, (G, 'current_stage'): 4, (G, 'stage_countdown_sec'): 360,
    (R, 'robot_id'): 6, (R, 'robot_type'): 91, (R, 'connection_state'): 1,
    (R, 'field_state'): 0, (R, 'alive_state'): 0, (R, 'level'): 3,
    (A, 'airsupport_status'): 0, (A, 'shooter_status'): 1, (A, 'left_time'): 30,
    (E, 'remaining_economy'): 280,
}


def snapshot(changes=None, *, omit=(), receipts=None, client_id='6', profile='rm2026-v2.0.0'):
    values = BASE | (changes or {})
    for key in omit:
        values.pop(key, None)
    receipts = receipts or {}
    observations = tuple(WireObservation(message, field, value, receipts.get((message, field), NOW))
                         for (message, field), value in sorted(values.items()))
    return WireSnapshot(profile, 3, client_id, NOW, observations)


def decide(command, state=None, *, now=NOW):
    return rules.request_decision('AirSupportCommand', command,
                                  snapshot() if state is None else state, now=now)


def wire(message, data):
    def varint(value):
        output = bytearray()
        while value >= 128:
            output.append((value & 127) | 128)
            value >>= 7
        output.append(value)
        return bytes(output)
    numbers = {field: number for number, (field, _kind, _repeated) in codec.FIELDS[message].items()}
    return b''.join(varint(numbers[field] << 3) + varint(value) for field, value in data.items())


class V2AirDecisionTests(unittest.TestCase):
    def test_all_four_air_commands_have_positive_peer_decisions(self):
        cases = [(0, {(A, 'airsupport_status'): 1}, 0), (1, {}, 0), (2, {}, None),
                 (3, {(A, 'shooter_status'): 2}, 280)]
        for command, changes, cost in cases:
            with self.subTest(command=command):
                allowed, reason, estimate = decide(command, snapshot(changes))
                self.assertTrue(allowed, reason)
                self.assertEqual(estimate, cost)

    def test_paid_free_first_does_not_require_known_or_positive_coins(self):
        for state in (snapshot({(E, 'remaining_economy'): 0}),
                      snapshot(omit=[(E, 'remaining_economy')]),
                      snapshot(receipts={(E, 'remaining_economy'): 1.0})):
            allowed, reason, estimate = decide(2, state)
            self.assertTrue(allowed, reason)
            self.assertIsNone(estimate)
            self.assertIn('1金币/秒', reason)

    def test_paid_without_free_time_needs_fresh_first_second_balance(self):
        for coins, expected in ((0, False), (1, True), (99, True)):
            self.assertEqual(decide(2, snapshot({(A, 'left_time'): 0,
                                               (E, 'remaining_economy'): coins}))[0], expected)
        self.assertFalse(decide(2, snapshot({(A, 'left_time'): 0},
                                          omit=[(E, 'remaining_economy')]))[0])
        self.assertFalse(decide(2, snapshot({(A, 'left_time'): 0},
                                          receipts={(E, 'remaining_economy'): 97.0}))[0])

    def test_cancel_ignores_start_money_shooter_level_and_alive_gates(self):
        omitted = [(R, 'connection_state'), (R, 'field_state'), (R, 'level'), (R, 'alive_state'),
                   (G, 'stage_countdown_sec'), (A, 'shooter_status'), (A, 'left_time'),
                   (E, 'remaining_economy')]
        result = decide(0, snapshot({(A, 'airsupport_status'): 1, (P, 'penalty_type'): 3},
                                    omit=omitted, receipts={(P, 'penalty_type'): 0.0}))
        self.assertTrue(result[0], result[1])
        self.assertEqual(result[2], 0)

    def test_cancel_still_requires_observed_active_support(self):
        for value in (0, 2, 99):
            self.assertFalse(decide(0, snapshot({(A, 'airsupport_status'): value}))[0])
        self.assertFalse(decide(0, snapshot(omit=[(A, 'airsupport_status')]))[0])

    def test_start_requires_connected_on_field_and_never_ground_alive(self):
        for command in (1, 2, 3):
            changes = {(A, 'shooter_status'): 2 if command == 3 else 1}
            for key, bad_values in (((R, 'connection_state'), (0, 2)),
                                    ((R, 'field_state'), (1, 2))):
                for bad in bad_values:
                    with self.subTest(command=command, key=key, bad=bad):
                        self.assertFalse(decide(command, snapshot(changes | {key: bad}))[0])
                self.assertFalse(decide(command, snapshot(changes, omit=[key]))[0])
            for alive in (0, 1, 2, 99):
                self.assertTrue(decide(command, snapshot(changes | {(R, 'alive_state'): alive}))[0])
            self.assertTrue(decide(command, snapshot(changes, omit=[(R, 'alive_state')]))[0])

    def test_ordinary_start_local_inactive_and_normal_shooter_restriction(self):
        for command in (1, 2):
            for shooter in (0, 2, 3, 99):
                self.assertFalse(decide(command, snapshot({(A, 'shooter_status'): shooter}))[0])
            result = decide(command, snapshot({(A, 'airsupport_status'): 1}))
            self.assertFalse(result[0])
            self.assertIn('local policy', result[1])

    def test_release_allows_active_or_inactive_and_does_not_need_illumination_or_free_time(self):
        for active in (0, 1):
            for illuminated in (0, 1, 99):
                state = snapshot({(A, 'airsupport_status'): active, (A, 'shooter_status'): 2,
                                  (A, 'is_being_targeted'): illuminated}, omit=[(A, 'left_time')])
                self.assertTrue(decide(3, state)[0])
        for shooter in (0, 1, 3):
            self.assertFalse(decide(3, snapshot({(A, 'shooter_status'): shooter}))[0])

    def test_release_estimate_and_insufficient_balance_boundaries(self):
        for remaining, level, cost in ((420, 1, 40), (360, 3, 280), (359, 3, 440), (0, 10, 1520)):
            changes = {(A, 'shooter_status'): 2, (G, 'stage_countdown_sec'): remaining,
                       (R, 'level'): level, (E, 'remaining_economy'): cost}
            result = decide(3, snapshot(changes))
            self.assertTrue(result[0], result[1])
            self.assertEqual(result[2], cost)
            result = decide(3, snapshot(changes | {(E, 'remaining_economy'): cost - 1}))
            self.assertFalse(result[0])
            self.assertEqual(result[2], cost)

    def test_release_missing_invalid_time_or_level_never_defaults_or_clamps(self):
        for key, bads in (((G, 'stage_countdown_sec'), (-1, 421, True, 360.0, '360')),
                          ((R, 'level'), (0, 11, True, 3.0, '3'))):
            self.assertFalse(decide(3, snapshot({(A, 'shooter_status'): 2}, omit=[key]))[0])
            for bad in bads:
                with self.subTest(key=key, bad=bad):
                    self.assertFalse(decide(3, snapshot({(A, 'shooter_status'): 2, key: bad}))[0])

    def test_every_free_call_required_observation_is_presence_bearing(self):
        required = [(G, 'current_round'), (G, 'current_stage'), (R, 'robot_id'), (R, 'robot_type'),
                    (R, 'connection_state'), (R, 'field_state'), (A, 'airsupport_status'),
                    (A, 'shooter_status'), (A, 'left_time')]
        for key in required:
            with self.subTest(key=key):
                result = decide(1, snapshot(omit=[key]))
                self.assertFalse(result[0])
                self.assertIn('missing', result[1])

    def test_required_integer_types_are_not_coerced(self):
        for key in ((G, 'current_round'), (R, 'robot_type'), (A, 'left_time')):
            for bad in (True, False, 1.0, '1', None, float('nan')):
                with self.subTest(key=key, bad=bad):
                    self.assertFalse(decide(1, snapshot({key: bad}))[0])

    def test_each_required_receipt_has_inclusive_two_second_local_boundary(self):
        for key in ((G, 'current_round'), (G, 'current_stage'), (R, 'robot_id'), (R, 'robot_type'),
                    (R, 'connection_state'), (R, 'field_state'), (A, 'airsupport_status'),
                    (A, 'shooter_status'), (A, 'left_time')):
            for receipt, expected in ((100.0, True), (98.0, True), (97.999, False), (100.001, False)):
                with self.subTest(key=key, receipt=receipt):
                    self.assertEqual(decide(1, snapshot(receipts={key: receipt}))[0], expected)

    def test_bad_receipts_and_fresh_siblings_cannot_requalify_old_fields(self):
        key = (A, 'left_time')
        for receipt in (None, True, '100', -1, float('nan'), float('inf'), 10**1000, 97.0):
            state = snapshot(receipts={key: receipt})
            self.assertEqual(state.received_at, NOW)
            self.assertFalse(decide(1, state)[0])
        self.assertTrue(decide(1, snapshot(receipts={(R, 'level'): 1.0,
                                                   (E, 'remaining_economy'): 1.0}))[0])

    def test_current_red_card_veto_never_expires_into_permission(self):
        for receipt in (0.0, 97.0, 100.0):
            for command in (1, 2, 3):
                state = snapshot({(P, 'penalty_type'): 3,
                                  (A, 'shooter_status'): 2 if command == 3 else 1},
                                 receipts={(P, 'penalty_type'): receipt})
                self.assertFalse(decide(command, state)[0])
        for penalty in (None, 0, 1, 2, 4, 5, 6, 99):
            state = snapshot() if penalty is None else snapshot({(P, 'penalty_type'): penalty})
            allowed, reason, _ = decide(1, state)
            self.assertTrue(allowed)
            self.assertIn('判罚状态未核实', reason)
            self.assertNotIn('已解除', reason)

    def test_only_match_stage_can_produce_a_positive_air_decision(self):
        for command in range(4):
            for stage in (0, 1, 2, 3, 5, 99):
                changes = {(G, 'current_stage'): stage, (A, 'airsupport_status'): command == 0,
                           (A, 'shooter_status'): 2 if command == 3 else 1}
                changes[(A, 'airsupport_status')] = int(changes[(A, 'airsupport_status')])
                result = decide(command, snapshot(changes))
                self.assertFalse(result[0])
                self.assertIn('MATCH', result[1])

    def test_observed_robot_id_defines_role_without_guessing_type_enum(self):
        for robot_id in (6, 106):
            for raw_type in (0, 6, 91, 4294967295):
                self.assertTrue(decide(1, snapshot({(R, 'robot_id'): robot_id,
                    (R, 'robot_type'): raw_type}, client_id=str(robot_id)))[0])
        for robot_id in (0, 3, 7, 103, 107):
            self.assertFalse(decide(1, snapshot({(R, 'robot_id'): robot_id,
                (R, 'robot_type'): 6}, client_id=str(robot_id)))[0])
        self.assertFalse(decide(1, snapshot({(R, 'robot_id'): 106}, client_id='6'))[0])

    def test_snapshot_profile_and_owner_shape_are_required(self):
        for state in (None, object(), {}, snapshot(profile='rm2026-v1.3.1'), snapshot(profile='unknown')):
            self.assertFalse(rules.request_decision('AirSupportCommand', 1, state, now=NOW)[0])

    def test_sentry_requires_own_team_mode_and_target_quote(self):
        for command in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
            result = rules.request_decision('SentryCtrlCommand', command, snapshot(), now=NOW)
            self.assertFalse(result[0])
            self.assertIsNone(result[2])
            self.assertIn('target can_pay' if command == 6 else 'sentry_control', result[1])
        for command in (0, 2, 13):
            self.assertIn('unsupported', rules.request_decision('SentryCtrlCommand', command,
                                                               snapshot(), now=NOW)[1])

    def test_unknown_command_topics_and_types_fail_closed(self):
        for topic in ('Unknown', 'CommonCommand', '', None, [], 1):
            self.assertFalse(rules.request_decision(topic, 1, snapshot(), now=NOW)[0])
        for command in (-1, 4, True, False, 1.0, '1', None, [], {}):
            self.assertFalse(decide(command)[0])

    def test_decision_does_not_mutate_or_refresh_snapshot(self):
        state = snapshot()
        before = copy.deepcopy(state)
        for command in range(4):
            decide(command, state)
        self.assertEqual(state, before)
        self.assertTrue(decide(1, state, now=102.0)[0])
        self.assertFalse(decide(1, state, now=102.001)[0])
        self.assertEqual(state, before)

    def test_invalid_clock_fails_closed_without_converting_custom_values(self):
        for now in (None, True, '100', -1, float('nan'), float('inf'), 10**1000):
            self.assertFalse(decide(1, now=now)[0])

    def test_free_time_zero_and_missing_are_not_synthesized_from_other_fields(self):
        zero = decide(1, snapshot({(A, 'left_time'): 0}))
        missing = decide(1, snapshot(omit=[(A, 'left_time')]))
        self.assertFalse(zero[0]); self.assertFalse(missing[0])
        self.assertIn('no observed free', zero[1])
        self.assertIn('missing', missing[1])
        self.assertFalse(decide(2, snapshot({(A, 'left_time'): -1}))[0])

    def test_actual_codec_and_snapshot_owner_supply_positive_request_evidence(self):
        records = [(G, {'current_round': 1}), (R, {'robot_id': 6, 'robot_type': 91}),
                   (G, {'current_stage': 4, 'stage_countdown_sec': 360}),
                   (R, {'connection_state': 1, 'field_state': 0, 'level': 3}),
                   (A, {'airsupport_status': 0, 'shooter_status': 2}),
                   (E, {'remaining_economy': 280})]
        state = None
        for message, values in records:
            decoded = codec.decode_message(message, wire(message, values))
            self.assertTrue(decoded)
            state = observe(state, profile_id='rm2026-v2.0.0', receive_generation=3,
                            client_id='6', message=message, data=decoded, received_at=NOW)
        result = decide(3, state)
        self.assertTrue(result[0], result[1])
        self.assertEqual(result[2], 280)
        decoded = codec.decode_message(G, wire(G, {'current_round': 2}))
        retired = observe(state, profile_id='rm2026-v2.0.0', receive_generation=3,
                          client_id='6', message=G, data=decoded, received_at=NOW)
        self.assertFalse(decide(3, retired)[0])

    def test_positive_cues_are_requests_not_execution_acknowledgements(self):
        for command in range(4):
            state = snapshot({(A, 'airsupport_status'): int(command == 0),
                              (A, 'shooter_status'): 2 if command == 3 else 1})
            allowed, reason, _ = decide(command, state)
            self.assertTrue(allowed, reason)
            self.assertIn('请求', reason)
            self.assertIn('待服务器确认', reason)
            self.assertNotIn('已执行', reason)
            if command == 3:
                self.assertIn('解除反制费用估价', reason)
                self.assertIn('后续支援模式/总价未确认', reason)


if __name__ == '__main__':
    unittest.main()
