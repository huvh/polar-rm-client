"""Inert V2 economic routes require a confirmed snapshot and actual RMUC owners."""
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.wire import encode_uint
from tests.test_referee_v2_uplink_admission import Client


class EconomyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.]
        p = patch('rm_client.backend.mqtt_backend.time.perf_counter', side_effect=lambda: self.clock[0])
        p.start(); self.addCleanup(p.stop)

    def backend(self, robot=3, dead=False, mode=0, coins=1000):
        b = RmMqttBackend(referee_profile='rm2026-v2.0.0', client_id=str(robot), mock_output=False)
        b.client = Client()
        b.bind_economy_context(NS(match_mode='RMUC7v7'), NS(session=NS(
            match_mode='RMUC7v7', referee_profile='rm2026-v2.0.0', robot_id=str(robot))))
        b._on_connect(b.client, None, {}, 0)
        b._on_subscribe(b.client, None, 77, [0] * 25)
        b.safety.configure(mock_writes=False, allow_mqtt_publish=True, enforce_official_limits=True)
        b.safety.arm_match({'core_kmc', 'economy'})
        for topic, values in [
            ('GameStatus', [(1, 1)]), ('RobotStaticStatus', [(4, robot), (5, 5 if robot % 100 == 6 else 1)]),
            ('GameStatus', [(5, 4), (6, 360)]),
            ('RobotStaticStatus', [(1, 1), (2, 0), (3, 2 if dead else 1), (8, 3), (9, 600)]),
            ('RobotDynamicStatus', [(1, 0 if dead else 300), (10, 1), (12, 1), (13, 1)]),
            ('RobotRespawnStatus', [(1, int(dead)), (4, 1), (5, 180), (6, 1)]),
            ('GlobalLogisticsStatus', [(1, coins)]),
            ('RobotPerformanceSelectionSync', [(3, mode)]),
            ('SentryStatusSync', [(1, 1), (2, 0), (3, 0)]),
            ('AirSupportStatusSync', [(1, 0), (2, 30), (5, 1)])]:
            self.receive(b, topic, values)
        return b

    def receive(self, b, topic, values):
        b._on_message(b.client, None, NS(topic=topic, retain=False,
            payload=b''.join(encode_uint(n, v) for n, v in values)))

    def publish(self, b, topic, raw, **kw):
        return b.publish_topic(topic, raw, intent='economy',
            expected_economy_snapshot=kw.pop('snapshot', b.v2_wire_snapshot()), **kw)

    def test_common_six_commands_both_alliances(self):
        for blue in (0, 100):
            for command in range(1, 7):
                b = self.backend(robot=(1 if command == 2 else 3)+blue, dead=command in {3, 4})
                raw = codec.encode_common_command(command, 10 if command == 1 else 2 if command == 2 else 0)
                self.assertEqual(self.publish(b, 'CommonCommand', raw), (True, 'ok'))
                self.assertEqual(b.client.sent, [('CommonCommand', raw, 1)])

    def test_sentry_reviewed_subset_both_alliances_and_paid_revive_unknown(self):
        for robot in (6, 106):
            for command in (1, 3, 4, 5, 7, 8, 9, 10, 11, 12):
                b = self.backend(robot)
                self.assertTrue(self.publish(b, 'SentryCtrlCommand', codec.encode_sentry_ctrl_command(command))[0])
            b = self.backend(robot)
            ok, reason = self.publish(b, 'SentryCtrlCommand', codec.encode_sentry_ctrl_command(6))
            self.assertFalse(ok); self.assertIn('target can_pay', reason); self.assertEqual(b.client.sent, [])
        b = self.backend(7)
        self.assertFalse(self.publish(b, 'SentryCtrlCommand', b'\x08\x01')[0])

    def test_every_bytes_entrypoint_requires_confirmation_identity(self):
        for entry in ('topic', 'named', 'binary', 'match', 'common'):
            b = self.backend(); raw = codec.encode_common_command(1, 10)
            if entry == 'topic': result = b.publish_topic('CommonCommand', raw)[0]
            elif entry == 'named': result = b.publish_named('CommonCommand', raw)[0]
            elif entry == 'binary': result = b.publish_binary('CommonCommand', raw)
            elif entry == 'match': result = b.publish_match_command('CommonCommand', raw)
            else: result = b.publish_common_command(raw)
            self.assertFalse(result); self.assertEqual(b.client.sent, [])
        for entry in ('named', 'common'):
            b = self.backend(); kw = {'expected_economy_snapshot': b.v2_wire_snapshot()}
            if entry == 'named': ok = b.publish_named('CommonCommand', raw, **kw)[0]
            else: ok = b.publish_common_command(raw, **kw)
            self.assertTrue(ok)

    def test_same_value_copy_or_new_receipt_is_not_confirmed_object(self):
        b = self.backend(); original = b.v2_wire_snapshot(); raw = codec.encode_common_command(1, 10)
        self.assertFalse(self.publish(b, 'CommonCommand', raw, snapshot=replace(original))[0])
        self.receive(b, 'GlobalLogisticsStatus', [(1, 1000)])
        self.assertEqual(b.v2_wire_snapshot(), original)
        self.assertIsNot(b.v2_wire_snapshot(), original)
        self.assertFalse(self.publish(b, 'CommonCommand', raw, snapshot=original)[0])
        self.assertEqual(b.client.sent, [])

    def test_actual_mode_and_session_owner_fail_closed(self):
        for change in ('unbound', 'state_mode', 'session_mode', 'missing', 'profile', 'robot'):
            b = self.backend()
            if change == 'unbound': b._economy_state_owner = None
            elif change == 'state_mode': b._economy_state_owner.match_mode = 'RMUL3v3'
            elif change == 'session_mode': b._economy_qualification_owner.session.match_mode = 'RMUL3v3'
            elif change == 'missing': b._economy_qualification_owner.session = None
            elif change == 'profile': b._economy_qualification_owner.session.referee_profile = 'rm2026-v1.3.1'
            else: b._economy_qualification_owner.session.robot_id = '103'
            self.assertFalse(self.publish(b, 'CommonCommand', codec.encode_common_command(1, 10))[0])
            self.assertEqual(b.client.sent, [])

    def test_final_rechecks_confirmation_scope_session_and_authority(self):
        for change in ('receipt', 'mode', 'session', 'owner', 'capability', 'suback', 'time'):
            b = self.backend(); original = b._publish_record
            def record(*a, **kw):
                out = original(*a, **kw)
                if change == 'receipt': self.receive(b, 'GlobalLogisticsStatus', [(1, 1000)])
                elif change == 'mode': b._economy_state_owner.match_mode = 'RMUL3v3'
                elif change == 'session': b._economy_qualification_owner.session = NS(**vars(b._economy_qualification_owner.session))
                elif change == 'owner': b._economy_state_owner = NS(match_mode='RMUC7v7')
                elif change == 'capability': b.safety._authorized_capabilities = frozenset({'core_kmc'})
                elif change == 'suback': b._subscriptions_ready = False
                else: self.clock[0] += 2.1
                return out
            b._publish_record = record
            self.assertFalse(self.publish(b, 'CommonCommand', codec.encode_common_command(1, 10))[0], change)
            self.assertEqual(b.client.sent, [])
            self.clock[0] = 100.

    def test_paid_map_intent_scope_cost_and_ordinary_route(self):
        raw = codec.encode_map_click_cmd(is_send_all=2)
        b = self.backend(coins=49)
        self.assertFalse(b.publish_topic('MapClickCmd', raw, expected_economy_snapshot=b.v2_wire_snapshot())[0])
        self.assertFalse(self.publish(b, 'MapClickCmd', raw)[0])
        b = self.backend(coins=50)
        self.assertTrue(self.publish(b, 'MapClickCmd', raw)[0])
        b = self.backend(coins=0, mode=1)
        self.assertTrue(self.publish(b, 'MapClickCmd', raw)[0])
        for blue in (0, 100):
            b = self.backend(3+blue)
            wrong = codec.encode_map_click_cmd(robot_id=bytes([107-blue]))
            self.assertFalse(self.publish(b, 'MapClickCmd', wrong)[0])
        b = self.backend(); b.safety.arm_match({'core_kmc'})
        ordinary = codec.encode_map_click_cmd(robot_id=bytes([3, 4]))
        self.assertTrue(b.publish_binary('MapClickCmd', ordinary))

    def test_frozen_common_bytes_and_bound_paid_classifier(self):
        b = self.backend(); raw = bytearray(codec.encode_common_command(1, 10)); expected = bytes(raw)
        original = b._publish_record
        def record(*a, **kw):
            raw[:] = codec.encode_common_command(1, 1000)
            return original(*a, **kw)
        b._publish_record = record
        self.assertTrue(self.publish(b, 'CommonCommand', raw)[0])
        self.assertEqual(b.client.sent[0][1], expected)
        b = self.backend()
        with patch('rm_client.backend.referee.rm2026_v2.uplink_validation.decode_fields', side_effect=AssertionError('unbounded decode')):
            self.assertFalse(b.publish_binary('MapClickCmd', b'\x08\x00' * (1024*1024)) )

    def test_air_optional_api_witness_but_provided_stale_witness_rejected(self):
        b = self.backend(6); original = b.v2_wire_snapshot()
        self.receive(b, 'GlobalLogisticsStatus', [(1, 1000)])
        self.assertFalse(b.publish_air_support_command(b'\x08\x01', expected_economy_snapshot=original))
        self.assertTrue(b.publish_air_support_command(b'\x08\x01', expected_economy_snapshot=b.v2_wire_snapshot()))

    def test_pre_suback_receipt_cannot_reenter_through_adapter_after_ack(self):
        b = self.backend()
        b.drain_decoded(); b.drain_received_messages(); b.clear_received_epoch()
        b._on_connect(b.client, None, {}, 0); b.safety.clear_stage_evidence()
        self.receive(b, 'GameStatus', [(1, 1), (5, 4)])
        b._on_subscribe(b.client, None, 77, [0] * 25)
        self.assertEqual(b.drain_decoded(), []); self.assertEqual(b.drain_received_messages(), [])
        self.assertIsNone(b.v2_wire_snapshot()); self.assertFalse(b.safety.is_fighting(now=100.))

if __name__ == '__main__': unittest.main()
