"""Inert final V2 admission: real owners, no broker/client network loop."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ast
import copy
import threading
import unittest
from unittest.mock import patch
import rm_client

from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.registry import get_profile
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.wire import encode_uint
from rm_client.backend.safety import ControlState, OfficialSafety


class InertClient:
    def __init__(self):
        self.sent = []
        self.rc = 0
        self.at_publish = None

    def publish(self, topic, payload, qos):
        self.sent.append((topic, payload, qos))
        if self.at_publish:
            self.at_publish()
        return SimpleNamespace(rc=self.rc)


class V2PublishGuardTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.addCleanup(patch.stopall)
        patch('rm_client.backend.mqtt_backend.time.perf_counter', side_effect=lambda: self.clock[0]).start()

    def backend(self, *, active=0, shooter=1, free=30, coins=280, mock=False):
        backend = RmMqttBackend(client_id='6', mock_output=mock)
        backend.referee = replace(backend.referee, profile_id='rm2026-v2.0.0',
                                  protocol_version=codec.PROTOCOL_VERSION, codec=codec)
        backend.client = InertClient()
        backend.connected = True
        backend.safety.configure(mock_writes=mock, allow_mqtt_publish=True, enforce_official_limits=True)
        backend.safety.arm_match({'core_kmc', 'economy'})
        for topic, values in [
            ('GameStatus', [(1, 1)]),
            ('RobotStaticStatus', [(4, 6), (5, 91)]),
            ('GameStatus', [(5, 4), (6, 360)]),
            ('RobotStaticStatus', [(1, 1), (2, 0), (8, 3)]),
            ('AirSupportStatusSync', [(1, active), (2, free), (5, shooter)]),
            ('GlobalLogisticsStatus', [(1, coins)]),
        ]:
            self.receive(backend, topic, values)
        return backend

    def receive(self, backend, topic, values):
        backend._on_message(backend.client, None, SimpleNamespace(
            topic=topic, payload=b''.join(encode_uint(number, value) for number, value in values)))

    def publish(self, backend, command=1, **kwargs):
        return backend.publish_topic('AirSupportCommand', encode_uint(1, command), **kwargs)

    def held(self, backend, change, *, command=1, **kwargs):
        entered, release = threading.Event(), threading.Event()
        original = backend._publish_current
        result = []
        def pause(*args, **options):
            entered.set()
            if not release.wait(3):
                raise AssertionError('test release missing')
            return original(*args, **options)
        with patch.object(backend, '_publish_current', side_effect=pause):
            thread = threading.Thread(target=lambda: result.append(self.publish(backend, command, **kwargs)), daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                change()
            finally:
                release.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        return result[0]

    def test_all_air_positive_paths_enqueue_exact_bytes(self):
        for command in range(4):
            with self.subTest(command=command):
                backend = self.backend(active=int(command == 0), shooter=2 if command == 3 else 1)
                self.assertEqual(self.publish(backend, command), (True, 'ok'))
                self.assertEqual(backend.client.sent, [('AirSupportCommand', encode_uint(1, command), 1)])
                self.assertEqual(backend.messages_sent, 1)
                self.assertEqual(backend.safety._publish_at['AirSupportCommand'], 100.0)

    def test_all_public_entrypoints_force_economy_capability(self):
        for entry in ('topic', 'named', 'binary', 'match', 'air'):
            for economy, expected in ((False, False), (True, True)):
                with self.subTest(entry=entry, economy=economy):
                    backend = self.backend()
                    backend.safety.arm_match({'core_kmc', *(['economy'] if economy else [])})
                    payload = encode_uint(1, 1)
                    if entry == 'topic': result = backend.publish_topic('AirSupportCommand', payload, intent='core_kmc')[0]
                    elif entry == 'named': result = backend.publish_named('AirSupportCommand', payload, intent='hero')[0]
                    elif entry == 'binary': result = backend.publish_binary('AirSupportCommand', payload)
                    elif entry == 'match': result = backend.publish_match_command('AirSupportCommand', payload)
                    else: result = backend.publish_air_support_command(payload)
                    self.assertEqual(result, expected)
                    self.assertEqual(len(backend.client.sent), int(expected))

    def test_initial_policy_once_and_events_outside_decoded_lock(self):
        backend = self.backend()
        calls, events = [], []
        original = backend.safety.can_publish
        def policy(*args, **kwargs):
            self.assertTrue(backend._decoded_lock.acquire(blocking=False))
            backend._decoded_lock.release()
            calls.append(kwargs)
            return original(*args, **kwargs)
        def event(*args, **kwargs):
            self.assertTrue(backend._decoded_lock.acquire(blocking=False))
            backend._decoded_lock.release()
            events.append(kwargs)
        backend.event_hook = event
        with patch.object(backend.safety, 'can_publish', side_effect=policy):
            self.assertTrue(self.publish(backend, now=-999, intent='core_kmc')[0])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['intent'], 'economy')
        self.assertEqual(calls[0]['now'], 100.0)
        self.assertEqual(events[-1]['intent'], 'economy')

    def test_actual_manager_adapters_inherit_the_same_economy_gate(self):
        path = Path(rm_client.__file__).resolve().parent/'backend/manager.py'
        tree = ast.parse(path.read_text())
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                     and node.name == 'BackendManager')
        names = {'_publish', 'publish_air_support', 'publish_sentry_command'}
        owner.body = [node for node in owner.body if isinstance(node, ast.FunctionDef)
                      and node.name in names]
        namespace = {}
        exec(compile(ast.Module(body=[owner], type_ignores=[]), str(path), 'exec'), namespace)
        for economy in (False, True):
            backend = self.backend()
            backend.safety.arm_match({'core_kmc', *(['economy'] if economy else [])})
            manager = namespace['BackendManager']()
            manager.mqtt, manager.referee = backend, backend.referee
            self.assertEqual(manager.publish_air_support(1)[0], economy)
            self.assertFalse(manager.publish_sentry_command(1)[0])
            self.assertEqual(len(backend.client.sent), int(economy))

    def test_stage_callback_before_ui_drain_retires_held_admission(self):
        backend = self.backend()
        generation = backend.safety.control_generation
        result = self.held(backend, lambda: self.receive(backend, 'GameStatus', [(5, 5)]))
        self.assertFalse(result[0])
        self.assertEqual(backend.safety.control_generation, generation)
        self.assertEqual(backend.safety.current_stage, '5')
        self.assertEqual(backend.client.sent, [])

    def test_same_value_snapshot_replacement_does_not_requalify_old_intent(self):
        backend = self.backend()
        self.assertFalse(self.held(backend, lambda: self.receive(backend, 'AirSupportStatusSync', [(2, 30)]))[0])
        self.assertEqual(backend.client.sent, [])
        self.assertTrue(self.publish(backend)[0])

    def test_field_expiry_uses_final_internal_clock_not_caller_now(self):
        backend = self.backend()
        self.assertFalse(self.held(backend, lambda: self.clock.__setitem__(0, 102.001), now=100.0)[0])
        self.assertEqual(backend.client.sent, [])
        self.assertEqual(backend.messages_sent, 0)

    def test_token_expiry_is_read_only_and_cannot_use_old_caller_clock(self):
        backend = self.backend()
        token = backend.safety.begin_qualification({'economy'}, ttl_s=1.0, now=100.0)
        notifications = []
        backend.safety.input_clear_hook = notifications.append
        generation = backend.safety.control_generation
        result = self.held(backend, lambda: self.clock.__setitem__(0, 101.001),
                           qualification_token=token.value, now=100.0, intent="economy")
        self.assertFalse(result[0])
        self.assertEqual(backend.safety.control_generation, generation)
        self.assertIs(backend.safety.control_state, ControlState.QUALIFICATION)
        self.assertEqual(notifications, [])
        self.assertEqual(backend.client.sent, [])

    def test_valid_economy_qualification_still_needs_match_and_business_rules(self):
        for intents, stage, free, expected in [({'economy'}, 4, 30, True),
                ({'core_kmc'}, 4, 30, False), ({'economy'}, 5, 30, False), ({'economy'}, 4, 0, False)]:
            backend = self.backend(free=free)
            token = backend.safety.begin_qualification(intents, now=100.0)
            self.receive(backend, 'GameStatus', [(5, stage)])
            self.assertEqual(self.publish(backend, qualification_token=token.value)[0], expected)
            self.assertEqual(len(backend.client.sent), int(expected))

    def test_initial_expired_token_observer_runs_without_decoded_lock(self):
        backend = self.backend()
        token = backend.safety.begin_qualification({'economy'}, ttl_s=1.0, now=98.0)
        called = []
        def observer(reason):
            self.assertTrue(backend._decoded_lock.acquire(blocking=False))
            backend._decoded_lock.release()
            called.append(reason)
        backend.safety.input_clear_hook = observer
        self.assertFalse(self.publish(backend, qualification_token=token.value)[0])
        self.assertEqual(len(called), 1)
        self.assertIs(backend.safety.control_state, ControlState.LOCKED)

    def test_revoke_and_rearm_cannot_reuse_held_approval(self):
        for estop in (False, True):
            backend = self.backend()
            def change():
                if estop:
                    backend.safety.trigger_estop(); backend.safety.release_estop()
                else:
                    backend.safety.lock_control()
                backend.safety.arm_match({'core_kmc', 'economy'})
            self.assertFalse(self.held(backend, change)[0])
            self.assertEqual(backend.client.sent, [])

    def test_final_configuration_and_capability_changes_without_generation_reject(self):
        for field, value in [('allow_mqtt_publish', False), ('current_stage', '5'),
                             ('_authorized_capabilities', frozenset({'core_kmc'}))]:
            backend = self.backend()
            generation = backend.safety.control_generation
            self.assertFalse(self.held(backend, lambda: setattr(backend.safety, field, value))[0])
            self.assertEqual(backend.safety.control_generation, generation)
            self.assertEqual(backend.client.sent, [])

    def test_context_and_safety_replacements_reject_held_approval(self):
        for changed in ('client', 'profile', 'client_id', 'epoch', 'lifecycle', 'safety', 'connected', 'mock'):
            with self.subTest(changed=changed):
                backend = self.backend()
                client = backend.client
                def change():
                    if changed == 'client': backend.client = InertClient()
                    elif changed == 'profile': backend.referee = replace(backend.referee)
                    elif changed == 'client_id': backend.client_id = '106'
                    elif changed == 'epoch': backend.clear_received_epoch()
                    elif changed == 'lifecycle': backend._lifecycle_generation += 1
                    elif changed == 'safety': backend.safety = copy.copy(backend.safety)
                    elif changed == 'connected': backend.connected = False
                    else: backend.mock_output = True
                self.assertFalse(self.held(backend, change)[0])
                self.assertEqual(client.sent, [])

    def test_actual_disconnect_then_rearm_cannot_restore_old_admission(self):
        backend = self.backend()
        client = backend.client
        def disconnect_rearm():
            backend._on_disconnect(client, None, _reason_code=7)
            backend.connected = True
            backend.safety.update_stage(4)
            backend.safety.arm_match({'core_kmc', 'economy'})
        self.assertFalse(self.held(backend, disconnect_rearm)[0])
        self.assertEqual(client.sent, [])

    def test_payload_conversion_cannot_rebind_a_new_receipt_epoch(self):
        backend = self.backend()
        calls = []
        class ChangesEpoch:
            def __bytes__(self):
                calls.append('converted')
                backend.clear_received_epoch()
                return encode_uint(1, 1)
        self.assertFalse(backend.publish_topic('AirSupportCommand', ChangesEpoch())[0])
        self.assertEqual(calls, ['converted'])
        self.assertEqual(backend.client.sent, [])

    def test_bytearray_is_frozen_once_for_validation_record_and_enqueue(self):
        backend = self.backend(coins=0)
        payload = bytearray(encode_uint(1, 1))
        original = backend._publish_current
        def change(*args, **kwargs):
            payload[:] = encode_uint(1, 3)
            return original(*args, **kwargs)
        with patch.object(backend, '_publish_current', side_effect=change):
            self.assertTrue(backend.publish_topic('AirSupportCommand', payload)[0])
        sent = backend.client.sent[0][1]
        self.assertIs(type(sent), bytes)
        self.assertEqual(sent, encode_uint(1, 1))
        self.assertIs(backend.publish_records[-1].payload, sent)

    def test_duplicates_default_unknown_fields_and_malformed_payload(self):
        cases = [(encode_uint(1, 3)+encode_uint(1, 1), False, True),
                 (encode_uint(1, 1)+encode_uint(1, 3), False, False),
                 (b'', True, True), (encode_uint(77, 99), True, True),
                 (b'\x08', False, False), (b'\x0a\x01\x01', False, False),
                 (encode_uint(1, 1 << 32), False, False)]
        for payload, active, expected in cases:
            backend = self.backend(active=int(active), coins=0)
            self.assertEqual(backend.publish_topic('AirSupportCommand', payload)[0], expected)
            self.assertEqual(len(backend.client.sent), int(expected))

    def test_missing_context_cannot_call_final_private_path(self):
        backend = self.backend()
        with self.assertRaisesRegex(RuntimeError, 'context required'):
            backend._publish_current(backend.client, backend._lifecycle_generation,
                                     'AirSupportCommand', encode_uint(1, 1), 1,
                                     authority_generation=backend.safety.control_generation)
        self.assertEqual(backend.client.sent, [])

    def test_final_decodes_actual_payload_not_a_cached_command(self):
        backend = self.backend(coins=0)
        context = (backend.referee, backend.safety, backend.v2_wire_snapshot(), None, False)
        for payload in (encode_uint(1, 3), bytearray(encode_uint(1, 1))):
            with self.assertRaises((RuntimeError, ValueError)):
                backend._publish_current(backend.client, backend._lifecycle_generation,
                    'AirSupportCommand', payload, 1, authority_generation=backend.safety.control_generation,
                    v2_context=context)
        self.assertEqual(backend.client.sent, [])

    def test_unimplemented_sentry_and_unknown_air_never_enqueue(self):
        for topic, commands in [('SentryCtrlCommand', range(14)), ('AirSupportCommand', (4, 99))]:
            for command in commands:
                backend = self.backend()
                self.assertFalse(backend.publish_topic(topic, encode_uint(1, command))[0])
                self.assertEqual(backend.client.sent, [])

    def test_mock_requires_same_checks_and_is_diagnostic_without_rate_debit(self):
        backend = self.backend(mock=True)
        self.assertEqual(self.publish(backend), (True, 'mock'))
        self.assertEqual(backend.client.sent, [])
        self.assertEqual(backend.messages_sent, 0)
        self.assertNotIn('AirSupportCommand', backend.safety._publish_at)
        backend.safety.lock_control()
        self.assertFalse(self.publish(backend)[0])

    def test_final_rate_recheck_sees_publish_after_initial_admission(self):
        backend = self.backend()
        self.assertFalse(self.held(backend, lambda: backend.safety.mark_published('AirSupportCommand', now=100.0))[0])
        self.assertEqual(backend.client.sent, [])
        self.clock[0] = 100.11
        self.assertTrue(self.publish(backend)[0])

    def test_callback_cannot_change_phase_inside_final_enqueue_section(self):
        backend = self.backend()
        publishing, release, attempted, delivered = [threading.Event() for _ in range(4)]
        original_lock = backend._decoded_lock
        class ObservedLock:
            def __enter__(self):
                if threading.current_thread().name == 'late-receipt': attempted.set()
                original_lock.acquire()
            def __exit__(self, *args): original_lock.release()
        backend._decoded_lock = ObservedLock()
        def enqueue():
            publishing.set()
            if not release.wait(3): raise AssertionError('enqueue release missing')
        backend.client.at_publish = enqueue
        results = []
        sender = threading.Thread(target=lambda: results.append(self.publish(backend)), daemon=True)
        sender.start()
        self.assertTrue(publishing.wait(3))
        def callback():
            self.receive(backend, 'GameStatus', [(5, 5)])
            delivered.set()
        receiver = threading.Thread(target=callback, name='late-receipt', daemon=True)
        receiver.start()
        try:
            self.assertTrue(attempted.wait(3))
            self.assertFalse(delivered.is_set())
            self.assertEqual(backend.safety.current_stage, '4')
        finally:
            release.set()
        sender.join(3); receiver.join(3)
        self.assertFalse(sender.is_alive()); self.assertFalse(receiver.is_alive())
        self.assertEqual(results, [(True, 'ok')])
        self.assertEqual(len(backend.client.sent), 1)
        self.assertEqual(backend.safety.current_stage, '5')

    def test_current_safety_predicate_has_no_denial_or_observer_side_effects(self):
        backend = self.backend()
        safety = backend.safety
        token = safety.begin_qualification({'economy'}, ttl_s=1.0, now=100.0)
        safety.input_clear_hook = lambda reason: self.fail('pure final check notified')
        before = safety.__dict__.copy()
        self.assertFalse(safety.can_publish_v2_economy_current('AirSupportCommand', now=101.001,
                                                            qualification_token=token.value)[0])
        self.assertEqual(safety.__dict__, before)
        for now in (None, True, '100', -1, float('nan'), float('inf'), 10**1000):
            self.assertFalse(safety.can_publish_v2_economy_current('AirSupportCommand', now=now)[0])
        self.assertEqual(safety.__dict__, before)

    def test_publish_failure_and_process_control_boundaries(self):
        backend = self.backend()
        backend.client.rc = 7
        self.assertFalse(self.publish(backend)[0])
        self.assertEqual(backend.messages_sent, 0)
        self.assertNotIn('AirSupportCommand', backend.safety._publish_at)
        for error in (RuntimeError('ordinary'), KeyboardInterrupt('interrupt'), SystemExit('exit')):
            backend = self.backend()
            with patch.object(backend.client, 'publish', side_effect=error):
                if isinstance(error, Exception): self.assertFalse(self.publish(backend)[0])
                else:
                    with self.assertRaises(type(error)) as caught: self.publish(backend)
                    self.assertIs(caught.exception, error)
            self.assertEqual(backend.messages_sent, 0)
            self.assertTrue(backend._decoded_lock.acquire(blocking=False))
            backend._decoded_lock.release()

    def test_v1_mock_and_caller_time_semantics_remain_legacy(self):
        backend = RmMqttBackend(mock_output=True)
        payload = bytearray(encode_uint(1, 1))
        self.assertEqual(backend.publish_topic('AirSupportCommand', payload, now=12.0), (True, 'mock'))
        self.assertIs(backend.publish_records[-1].payload, payload)
        self.assertEqual(backend.messages_sent, 0)
        with self.assertRaises(ValueError): get_profile('rm2026-v2.0.0')


if __name__ == '__main__':
    unittest.main()
