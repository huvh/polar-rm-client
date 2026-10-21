"""Inert actual MQTT admission: domains, source roles and final safety."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.wire import encode_uint


class Client:
    def __init__(self): self.sent = []
    def publish(self, topic, payload, qos):
        self.sent.append((topic, payload, qos)); return SimpleNamespace(rc=0)
    def subscribe(self, topics): return 0, 77


class UplinkAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.]
        p = patch('rm_client.backend.mqtt_backend.time.perf_counter', side_effect=lambda: self.clock[0])
        p.start(); self.addCleanup(p.stop)

    def backend(self, robot=3, stage=4):
        b = RmMqttBackend(referee_profile='rm2026-v2.0.0', client_id=str(robot), mock_output=False)
        b.client = Client()
        b._on_connect(b.client, None, {}, 0)
        b._on_subscribe(b.client, None, 77, [1] * len(codec.DOWNLINK_MESSAGES))
        b.safety.configure(mock_writes=False, allow_mqtt_publish=True, enforce_official_limits=True)
        b.safety.arm_match({'core_kmc', 'hero', 'economy'})
        self.receive(b, 'GameStatus', [(1, 1)])
        self.receive(b, 'RobotStaticStatus', [(4, robot), (5, 1)])
        self.receive(b, 'GameStatus', [(5, stage)])
        return b

    def receive(self, b, topic, values):
        b._on_message(b.client, None, SimpleNamespace(topic=topic, retain=False,
            payload=b''.join(encode_uint(n, v) for n, v in values)))

    def test_all_eight_non_economic_topics_have_real_guarded_routes(self):
        cases = [('KeyboardMouseControl', codec.encode_keyboard_mouse_control(mouse_x=-3), 3, 'control'),
                 ('CustomControl', codec.encode_custom_control(b'abc'), 3, 'control'),
                 ('MapClickCmd', codec.encode_map_click_cmd(), 3, 'control'),
                 ('AssemblyCommand', codec.encode_assembly_command(0, 4), 2, 'control'),
                 ('RobotPerformanceSelectionCommand', codec.encode_robot_performance_selection_command(1, 1, 0), 3, 'control'),
                 ('HeroDeployModeEventCommand', codec.encode_hero_deploy_mode_event_command(1), 1, 'hero'),
                 ('RuneActivateCommand', codec.encode_rune_activate_command(1), 3, 'control'),
                 ('DartCommand', codec.encode_dart_command(1, True, False), 6, 'control')]
        for topic, payload, robot, intent in cases:
            with self.subTest(topic=topic):
                b = self.backend(robot)
                self.assertEqual(b.publish_topic(topic, payload, intent=intent), (True, 'ok'))
                self.assertEqual(b.client.sent, [(topic, payload, 1)])

    def test_suback_gate_blocks_early_stage_but_not_fixed_neutral(self):
        b = self.backend()
        b._on_connect(b.client, None, {}, 0)
        b.safety.clear_stage_evidence()
        self.receive(b, 'GameStatus', [(5, 4)])
        self.assertFalse(b.safety.is_fighting(now=100.))
        b.safety.update_stage(4, now=100.)
        self.assertIn('SUBACK', b.publish_topic('KeyboardMouseControl', b'')[1])
        self.assertEqual(b.publish_estop_zero(), (True, 'ok'))
        b._on_subscribe(b.client, None, 77, [0]*25)
        self.assertTrue(b.subscriptions_ready)

    def test_wrong_and_stale_identity_and_direct_raw_domain_cannot_bypass(self):
        for robot, raw in [(8, codec.encode_dart_command(1, False, False)),
                           (6, encode_uint(1, 6)), (6, encode_uint(1, 1)+encode_uint(2, 2))]:
            b = self.backend(robot)
            self.assertFalse(b.publish_binary('DartCommand', raw))
            self.assertEqual(b.client.sent, [])
        b = self.backend(6); self.clock[0] = 102.1
        b.safety.update_stage(4, now=102.1)
        self.assertFalse(b.publish_binary('DartCommand', codec.encode_dart_command(1, False, False)))

    def test_final_record_observer_cannot_change_bytes_identity_or_stage(self):
        for change in ['identity', 'stage', 'authority', 'suback']:
            b = self.backend(6)
            original = b._publish_record
            def record(*a, **kw):
                result = original(*a, **kw)
                if change == 'identity': self.receive(b, 'RobotStaticStatus', [(4, 8)])
                elif change == 'stage': self.receive(b, 'GameStatus', [(5, 1)])
                elif change == 'authority': b.safety.lock_control('test')
                else: b._subscriptions_ready = False
                return result
            b._publish_record = record
            self.assertFalse(b.publish_binary('DartCommand', codec.encode_dart_command(1, False, False)))
            self.assertEqual(b.client.sent, [])

    def test_payload_is_frozen_before_record_callbacks(self):
        b = self.backend(); raw = bytearray(codec.encode_keyboard_mouse_control(mouse_x=2))
        before = bytes(raw); original = b._publish_record
        def record(*a, **kw):
            raw[:] = encode_uint(6, 65536)
            return original(*a, **kw)
        b._publish_record = record
        self.assertTrue(b.publish_keyboard_mouse(raw))
        self.assertEqual(b.client.sent[0][1], before)

    def test_aerial_sentry_mode_prepare_requires_explicit_qualification(self):
        b = self.backend(6, 1)
        payload = codec.encode_robot_performance_selection_command(0, 0, 1)
        self.assertFalse(b.publish_named('RobotPerformanceSelectionCommand', payload)[0])
        token = b.safety.begin_qualification({'core_kmc'}, now=100.)
        self.assertTrue(b.publish_named('RobotPerformanceSelectionCommand', payload,
            intent='core_kmc', qualification_token=token.value)[0])

    def test_custom_map_conflict_and_paid_core_are_explicitly_rejected(self):
        b = self.backend()
        self.assertIn('conflict', b.publish_named('MapClickCmd', codec.encode_map_click_cmd(mark_type=4))[1])
        self.assertFalse(b.publish_binary('MapClickCmd', codec.encode_map_click_cmd(is_send_all=2)))
        self.assertEqual(b.client.sent, [])

    def test_rates_cover_all_eleven_topics(self):
        b = self.backend()
        self.assertEqual(set(b.referee.uplink_hz), set(codec.UPLINK_MESSAGES))
        self.assertEqual(b.referee.uplink_hz['KeyboardMouseControl'], 75)
        self.assertEqual(b.referee.uplink_hz['MapClickCmd'], 1/3)

if __name__ == '__main__': unittest.main()
