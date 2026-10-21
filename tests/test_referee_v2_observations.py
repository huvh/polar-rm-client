"""Inert V2 wire receipts; no network, profile registration or command enablement."""
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.rm2026_v2.observations import observe
from rm_client.backend.referee.wire import encode_uint as _encode_varint_field


class V2WireObservations(unittest.TestCase):
    def backend(self):
        backend = RmMqttBackend()
        backend.referee = replace(backend.referee, profile_id='test-unregistered-v2',
                                  protocol_version='2.0.0', codec=codec)
        backend.client = object()
        backend.connected = backend._subscriptions_ready = True
        return backend

    def receive(self, backend, topic, fields, at=100.0):
        payload = b''.join(_encode_varint_field(k, v) for k, v in fields)
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=at):
            backend._on_message(backend.client, None, SimpleNamespace(topic=topic, payload=payload))
        return backend.v2_wire_snapshot()

    def test_present_zero_false_and_partial_original_receipts(self):
        backend = self.backend()
        first = self.receive(backend, 'AirSupportStatusSync', [(1, 0), (5, 2)])
        second = self.receive(backend, 'AirSupportStatusSync', [(1, 1)], 101.0)
        self.assertEqual(first.get('AirSupportStatusSync', 'airsupport_status').value, 0)
        self.assertEqual(second.get('AirSupportStatusSync', 'shooter_status').received_at, 100.0)
        self.assertEqual(second.get('AirSupportStatusSync', 'airsupport_status').received_at, 101.0)
        self.assertIsNone(second.get('AirSupportStatusSync', 'left_time'))
        third = self.receive(backend, 'SentryStatusSync', [(3, 0)], 102.0)
        self.assertIs(third.get('SentryStatusSync', 'is_powered').value, False)

    def test_immutable_snapshot_and_detached_decoded_queue(self):
        backend = self.backend()
        snapshot = self.receive(backend, 'AirSupportStatusSync', [(5, 2)])
        queued = backend.drain_decoded()
        queued[0][2]['shooter_status'] = 99
        self.assertEqual(snapshot.get('AirSupportStatusSync', 'shooter_status').value, 2)
        with self.assertRaises(FrozenInstanceError):
            snapshot.client_id = '7'
        with self.assertRaises(FrozenInstanceError):
            snapshot.observations[0].value = 99
        self.assertIsInstance(snapshot.observations, tuple)

    def test_receipt_precedes_hook_delay_and_raw_queue_unchanged(self):
        backend = self.backend()
        clock = [100.0]
        backend.event_hook = lambda *a, **k: clock.__setitem__(0, 104.0)
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', side_effect=lambda: clock[0]):
            backend._on_message(backend.client, None, SimpleNamespace(topic='AirSupportStatusSync', payload=b'\x28\x02'))
        self.assertEqual(backend.v2_wire_snapshot().observations[0].received_at, 100.0)
        self.assertEqual(backend.drain_received_messages()[0][2], 100.0)
        self.assertEqual(backend.drain_decoded()[0][3], 100.0)

    def test_missing_invalid_unavailable_and_reply_do_not_seed_snapshot(self):
        for topic, payload in [('AirSupportStatusSync', b''), ('AirSupportStatusSync', b'\x28'),
                               ('RadarInfoToClient', b'\x08\x01'), ('SentryCtrlResult', b'\x08\x07\x10\x00')]:
            with self.subTest(topic=topic, payload=payload):
                backend = self.backend()
                backend._on_message(backend.client, None, SimpleNamespace(topic=topic, payload=payload))
                self.assertIsNone(backend.v2_wire_snapshot())

    def test_v1_and_mismatching_protocol_have_no_wire_snapshot(self):
        for v1 in (True, False):
            backend = RmMqttBackend() if v1 else self.backend()
            if not v1:
                backend.referee = replace(backend.referee, protocol_version='1.3.1')
            backend.client = object()
            backend.connected = backend._subscriptions_ready = True
            self.receive(backend, 'AirSupportStatusSync', [(1, 0)])
            self.assertIsNone(backend.v2_wire_snapshot())
            self.assertEqual(len(backend.drain_decoded()), 1)

    def test_v1_callback_does_not_add_client_id_conversion(self):
        class UnusedClientId:
            def __str__(self):
                raise AssertionError('legacy receipt must not convert ClientId')
        backend = RmMqttBackend()
        backend.client = object()
        backend.connected = backend._subscriptions_ready = True
        backend.client_id = UnusedClientId()
        backend._on_message(backend.client, None, SimpleNamespace(topic='AirSupportStatusSync', payload=b'\x08\x00'))
        self.assertEqual(len(backend.drain_decoded()), 1)
        self.assertIsNone(backend.v2_wire_snapshot())

    def test_epoch_clear_retires_and_new_receipt_starts_empty(self):
        backend = self.backend()
        old = self.receive(backend, 'AirSupportStatusSync', [(5, 2)])
        backend.clear_received_epoch()
        self.assertIsNone(backend.v2_wire_snapshot())
        new = self.receive(backend, 'GlobalLogisticsStatus', [(1, 42)], 101.0)
        self.assertEqual(new.receive_generation, old.receive_generation + 1)
        self.assertIsNone(new.get('AirSupportStatusSync', 'shooter_status'))
        self.assertEqual(old.get('AirSupportStatusSync', 'shooter_status').value, 2)

    def test_changed_context_reader_rejects_old_and_callback_restarts(self):
        for changed in ('client', 'profile', 'client_id'):
            with self.subTest(changed=changed):
                backend = self.backend()
                self.receive(backend, 'AirSupportStatusSync', [(5, 2)])
                if changed == 'client':
                    backend.client = object()
                elif changed == 'profile':
                    backend.referee = replace(backend.referee, profile_id='other-v2')
                else:
                    backend.client_id = '7'
                self.assertIsNone(backend.v2_wire_snapshot())
                new = self.receive(backend, 'GlobalLogisticsStatus', [(1, 5)], 101.0)
                self.assertIsNone(new.get('AirSupportStatusSync', 'shooter_status'))

    def test_hook_epoch_profile_client_and_config_identity_reentry_rejected(self):
        for changed in ('epoch', 'profile', 'client', 'client_id'):
            with self.subTest(changed=changed):
                backend = self.backend()
                def hook(*args, **kwargs):
                    if changed == 'epoch':
                        backend.clear_received_epoch()
                    elif changed == 'profile':
                        backend.referee = replace(backend.referee, profile_id='other')
                    elif changed == 'client':
                        backend.client = object()
                    else:
                        backend.client_id = '7'
                backend.event_hook = hook
                self.receive(backend, 'AirSupportStatusSync', [(5, 2)])
                self.assertIsNone(backend.v2_wire_snapshot())
                self.assertEqual(backend.drain_decoded(), [])

    def test_identity_round_binding_and_changed_scope_retire_measurements(self):
        backend = self.backend()
        self.receive(backend, 'GlobalLogisticsStatus', [(1, 42)])
        bound = self.receive(backend, 'RobotStaticStatus', [(4, 7)], 101.0)
        self.assertIsNone(bound.get('GlobalLogisticsStatus', 'remaining_economy'))
        self.receive(backend, 'GameStatus', [(1, 1)], 102.0)
        partial = self.receive(backend, 'RobotStaticStatus', [(5, 7)], 103.0)
        self.assertEqual(partial.get('RobotStaticStatus', 'robot_id').value, 7)
        self.assertEqual(partial.get('GameStatus', 'current_round').value, 1)
        self.receive(backend, 'AirSupportStatusSync', [(5, 2)], 104.0)
        changed = self.receive(backend, 'RobotStaticStatus', [(4, 107)], 105.0)
        self.assertIsNone(changed.get('AirSupportStatusSync', 'shooter_status'))
        self.assertIsNone(changed.get('RobotStaticStatus', 'robot_type'))
        self.assertEqual(changed.get('RobotStaticStatus', 'robot_id').value, 107)

    def test_late_disjoint_and_pre_retirement_receipts_cannot_repopulate(self):
        backend = self.backend()
        self.receive(backend, 'GameStatus', [(1, 1)], 100.0)
        self.receive(backend, 'AirSupportStatusSync', [(5, 2)], 101.0)
        current = self.receive(backend, 'GameStatus', [(1, 2)], 103.0)
        older = self.receive(backend, 'AirSupportStatusSync', [(5, 2)], 102.0)
        self.assertIs(older, current)
        self.assertIsNone(older.get('AirSupportStatusSync', 'shooter_status'))
        self.assertEqual(len(backend.drain_decoded()), 4)  # Storage policy doesn't rewrite the queue.

    def test_equal_receipts_follow_commit_order_and_unknown_enum_remains_raw(self):
        backend = self.backend()
        self.receive(backend, 'AirSupportStatusSync', [(5, 2)])
        snapshot = self.receive(backend, 'AirSupportStatusSync', [(5, 255)])
        self.assertEqual(snapshot.get('AirSupportStatusSync', 'shooter_status').value, 255)

    def test_callback_never_acquires_lifecycle_and_getter_lock_order(self):
        backend = self.backend()
        entered = []
        class CheckedLock:
            def __init__(self, name):
                self.name = name
                self.lock = threading.Lock()
            def __enter__(self):
                if self.name == 'lifecycle' and 'decoded' in entered:
                    raise AssertionError('inverted lock acquisition')
                self.lock.acquire()
                entered.append(self.name)
            def __exit__(self, *args):
                self_name = entered.pop()
                assert self_name == self.name
                self.lock.release()
        backend._decoded_lock = CheckedLock('decoded')
        class Forbidden:
            def __enter__(self):
                raise AssertionError('callback acquired lifecycle')
            def __exit__(self, *args):
                pass
        backend._lifecycle_lock = Forbidden()
        backend._on_message(backend.client, None, SimpleNamespace(topic='AirSupportStatusSync', payload=b'\x28\x02'))
        backend._lifecycle_lock = CheckedLock('lifecycle')
        self.assertIsNotNone(backend.v2_wire_snapshot())
        with backend._lifecycle_lock:
            backend.clear_received_epoch()
        self.assertIsNone(backend.v2_wire_snapshot())

    def test_partial_scope_binding_in_both_orders_then_new_round(self):
        for fields in (((4, 7), (5, 7)), ((5, 7), (4, 7))):
            with self.subTest(fields=fields):
                backend = self.backend()
                self.receive(backend, 'RobotStaticStatus', [fields[0]], 100.0)
                self.receive(backend, 'RobotStaticStatus', [fields[1]], 101.0)
                self.receive(backend, 'GameStatus', [(1, 1)], 102.0)
                bound = self.receive(backend, 'GameStatus', [(5, 4)], 103.0)
                self.assertEqual(bound.get('RobotStaticStatus', 'robot_id').value, 7)
                self.assertEqual(bound.get('RobotStaticStatus', 'robot_type').value, 7)
                self.assertEqual(bound.get('GameStatus', 'current_round').value, 1)
                self.receive(backend, 'GameStatus', [(1, 2)], 104.0)
                self.receive(backend, 'RobotStaticStatus', [fields[0]], 105.0)
                self.receive(backend, 'RobotStaticStatus', [fields[1]], 106.0)
                bound = self.receive(backend, 'GameStatus', [(5, 4)], 107.0)
                self.assertEqual(bound.get('GameStatus', 'current_round').value, 2)
                self.assertEqual(bound.get('GameStatus', 'current_stage').value, 4)
                self.assertEqual(bound.get('RobotStaticStatus', 'robot_id').value, 7)
                self.assertEqual(bound.get('RobotStaticStatus', 'robot_type').value, 7)

    def test_nested_newer_callback_identity_retirement_wins_over_old_completion(self):
        backend = self.backend()
        self.receive(backend, 'RobotStaticStatus', [(4, 7), (5, 7)], 99.0)
        def hook(*args, **kwargs):
            backend.event_hook = None
            self.receive(backend, 'RobotStaticStatus', [(4, 107)], 101.0)
        backend.event_hook = hook
        snapshot = self.receive(backend, 'AirSupportStatusSync', [(5, 2)], 100.0)
        self.assertEqual(snapshot.get('RobotStaticStatus', 'robot_id').value, 107)
        self.assertIsNone(snapshot.get('AirSupportStatusSync', 'shooter_status'))
        self.assertIsNone(snapshot.get('RobotStaticStatus', 'robot_type'))

    def test_snapshot_metadata_does_not_invent_observed_robot_identity(self):
        backend = self.backend()
        snapshot = self.receive(backend, 'GlobalLogisticsStatus', [(1, 0)])
        self.assertEqual(snapshot.client_id, '3')
        self.assertEqual(snapshot.profile_id, 'test-unregistered-v2')
        self.assertEqual(snapshot.receive_generation, backend.receive_generation)
        self.assertIsNone(snapshot.get('RobotStaticStatus', 'robot_id'))
        self.assertIsNone(snapshot.get('RobotStaticStatus', 'robot_type'))

    def test_performance_mode_presence_receipt_and_identity_retirement(self):
        backend = self.backend()
        self.receive(backend, 'RobotStaticStatus', [(4, 7)], 99.0)
        absent = self.receive(backend, 'RobotPerformanceSelectionSync', [(1, 1)], 100.0)
        self.assertIsNone(absent.get('RobotPerformanceSelectionSync', 'sentry_control'))
        zero = self.receive(backend, 'RobotPerformanceSelectionSync', [(3, 0)], 101.0)
        self.assertEqual(zero.get('RobotPerformanceSelectionSync', 'sentry_control').value, 0)
        partial = self.receive(backend, 'RobotPerformanceSelectionSync', [(2, 2)], 102.0)
        self.assertEqual(partial.get('RobotPerformanceSelectionSync', 'sentry_control').received_at, 101.0)
        self.assertEqual(partial.get('RobotPerformanceSelectionSync', 'shooter').value, 1)
        self.assertEqual(partial.get('RobotPerformanceSelectionSync', 'chassis').value, 2)
        changed = self.receive(backend, 'RobotStaticStatus', [(4, 107)], 103.0)
        self.assertIsNone(changed.get('RobotPerformanceSelectionSync', 'sentry_control'))
        explicit = self.receive(backend, 'RobotPerformanceSelectionSync', [(3, 1)], 104.0)
        self.assertEqual(explicit.get('RobotPerformanceSelectionSync', 'sentry_control').value, 1)

    def test_bad_direct_record_is_atomic_and_receipt_is_validated(self):
        data = codec.decode_message('AirSupportStatusSync', b'\x08\x01')
        first = observe(None, profile_id='v2', receive_generation=0, client_id='3',
                        message='AirSupportStatusSync', data=data, received_at=100.0)
        bad = dict(data, shooter_status='2', __present__=frozenset({1, 5}))
        with self.assertRaises(ValueError):
            observe(first, profile_id='v2', receive_generation=0, client_id='3',
                    message='AirSupportStatusSync', data=bad, received_at=101.0)
        for stamp in (None, True, -1, float('nan'), float('inf')):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                observe(first, profile_id='v2', receive_generation=0, client_id='3',
                        message='AirSupportStatusSync', data=data, received_at=stamp)
        self.assertEqual(first.get('AirSupportStatusSync', 'airsupport_status').value, 1)


if __name__ == '__main__':
    unittest.main()
