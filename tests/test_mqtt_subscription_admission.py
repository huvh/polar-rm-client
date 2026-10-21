"""MQTT subscribe admission and SUBACK evidence, without an external broker."""
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.mqtt_backend import RmMqttBackend


class Client:
    def __init__(self, result=(0, 17), error=None):
        self.result = result
        self.error = error
        self.subscriptions = []
        self.publications = []
        self._thread = None

    def subscribe(self, topics):
        self.subscriptions.append(topics)
        if self.error is not None:
            raise self.error
        return self.result

    def publish(self, topic, payload, **kwargs):
        self.publications.append((topic, bytes(payload)))
        return SimpleNamespace(rc=0)

    def disconnect(self):
        pass

    def loop_stop(self):
        return 0


class SubscriptionAdmissionTests(unittest.TestCase):
    def backend(self, *, result=(0, 17), error=None):
        backend = RmMqttBackend(mock_output=False)
        backend.client = Client(result, error)
        backend._started = True
        backend._zero_after_reconnect = True
        backend.safety.update_stage(4)
        backend.safety.arm_match({'core_kmc'})
        self.addCleanup(backend.stop)
        return backend

    def test_local_subscribe_error_revokes_session_and_does_not_call_ready_hook(self):
        for result in ((4, None), (1, 17), None, (0, None), (0, 0)):
            with self.subTest(result=result):
                backend = self.backend(result=result)
                calls = []
                backend._on_connect_hook = lambda: calls.append('ready')
                client = backend.client
                backend._on_connect(client, None, {}, 0)
                self.assertFalse(backend.connected)
                self.assertTrue(backend._reconnect_required)
                self.assertEqual(calls, [])
                self.assertEqual(client.publications, [])
                self.assertFalse(backend.safety.is_fighting())
                self.assertEqual(backend.safety.control_state.value, 'LOCKED')
                self.assertIn('subscrib', backend.last_error.lower())

    def test_subscribe_exception_is_contained_and_recoverable(self):
        backend = self.backend(error=OSError('subscription send failed'))
        backend._on_connect(backend.client, None, {}, 0)
        self.assertFalse(backend.connected)
        self.assertTrue(backend._reconnect_required)
        self.assertIn('subscription send failed', backend.last_error)

    def test_suback_failure_for_current_request_revokes_all_received_evidence(self):
        for v2 in (False, True):
            with self.subTest(v2=v2):
                backend = self.backend()
                client = backend.client
                backend._on_connect(client, None, {}, 0)
                self.assertTrue(backend.connected)
                generation = backend.receive_generation
                count = len(client.subscriptions[0])
                codes = [0] * count
                codes[-1] = 128
                if v2:
                    codes = [SimpleNamespace(value=code) for code in codes]
                backend._on_subscribe(client, None, 17, codes, None)
                self.assertFalse(backend.connected)
                self.assertTrue(backend._reconnect_required)
                self.assertGreater(backend.receive_generation, generation)
                self.assertFalse(backend.safety.is_fighting())
                self.assertFalse(backend.stats()['subscriptions_ready'])
                self.assertIn('SUBACK', backend.last_error)

    def test_suback_success_requires_exact_request_and_legal_grants(self):
        backend = self.backend()
        client = backend.client
        backend._on_connect(client, None, {}, 0)
        count = len(client.subscriptions[0])
        self.assertFalse(backend.stats()['subscriptions_ready'])
        backend._on_subscribe(client, None, 18, [0] * count, None)
        self.assertFalse(backend.stats()['subscriptions_ready'])
        backend._on_subscribe(client, None, 17, [0, 1] * (count // 2) + [0] * (count % 2), None)
        self.assertTrue(backend.connected)
        self.assertTrue(backend.stats()['subscriptions_ready'])
        self.assertFalse(backend._reconnect_required)
        backend.stop()
        self.assertFalse(backend.stats()['subscriptions_ready'])

    def test_bad_suback_vector_is_not_readiness(self):
        for codes in ([], [0], [2], [255]):
            with self.subTest(codes=codes):
                backend = self.backend()
                backend._on_connect(backend.client, None, {}, 0)
                backend._on_subscribe(backend.client, None, 17, codes, None)
                self.assertFalse(backend.connected)
                self.assertFalse(backend.stats()['subscriptions_ready'])
                self.assertTrue(backend._reconnect_required)

    def test_delayed_subscribe_failure_cannot_revoke_replacement(self):
        backend = self.backend()
        old = backend.client
        replacement = Client()
        def replace(topics):
            backend.client = replacement
            backend._lifecycle_generation += 1
            backend.connected = True
            return (4, None)
        old.subscribe = replace
        backend._on_connect(old, None, {}, 0)
        self.assertIs(backend.client, replacement)
        self.assertTrue(backend.connected)
        self.assertFalse(backend._reconnect_required)

    def test_old_or_duplicate_suback_cannot_revoke_current_session(self):
        backend = self.backend()
        old = Client()
        backend._on_connect(backend.client, None, {}, 0)
        count = len(backend.client.subscriptions[0])
        backend._on_subscribe(old, None, 17, [128] * count, None)
        self.assertTrue(backend.connected)
        backend._on_subscribe(backend.client, None, 17, [1] * count, None)
        backend._on_subscribe(backend.client, None, 17, [128] * count, None)
        self.assertTrue(backend.connected)
        self.assertTrue(backend.stats()['subscriptions_ready'])


    def test_pending_suback_times_out_without_blocking_or_starting_another_owner(self):
        backend = self.backend()
        client = backend.client
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=100.):
            backend._on_connect(client, None, {}, 0)
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=104.99):
            backend.poll_connection()
        self.assertTrue(backend.connected)
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=105.):
            backend.poll_connection()
        self.assertIs(backend.client, client)
        self.assertFalse(backend.connected)
        self.assertTrue(backend._reconnect_required)
        self.assertIn('SUBACK timeout', backend.last_error)
        backend._on_subscribe(client, None, 17, [1] * len(client.subscriptions[0]), None)
        self.assertFalse(backend.stats()['subscriptions_ready'])

    def test_completed_request_cannot_be_revoked_by_a_stale_timeout_observation(self):
        backend = self.backend()
        backend._on_connect(backend.client, None, {}, 0)
        request = backend._subscription_request
        backend._on_subscribe(backend.client, None, 17, [1] * request[3], None)
        backend._subscription_failed(request[0], request[1], 'stale timeout', expected_request=request)
        self.assertTrue(backend.connected)
        self.assertTrue(backend.stats()['subscriptions_ready'])

    def test_disconnect_revokes_ingress_before_fallible_safety_observers(self):
        backend = self.backend()
        client = backend.client
        backend._on_connect(client, None, {}, 0)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = backend._lock_safety_locked
        def blocked(reason):
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test did not release safety observer')
            original(reason)
        backend._lock_safety_locked = blocked
        worker = threading.Thread(target=lambda: backend._schedule_reconnect('lost', client=client))
        worker.start()
        self.assertTrue(entered.wait(1))
        backend._on_message(client, None, SimpleNamespace(topic='GameStatus', payload=b'\x28\x04'))
        self.assertEqual(backend.drain_decoded(), [])
        self.assertEqual(backend.drain_received_messages(), [])
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(backend.safety.is_fighting())
        backend._lock_safety_locked = original

    def test_downlink_readiness_requires_ack_not_just_connack(self):
        from rm_client.backend.readiness import audit_backend
        backend = self.backend()
        manager = SimpleNamespace(stats=lambda: {'mqtt': backend.stats()})
        state = SimpleNamespace(backend_stats={})
        def gate():
            return next(g for g in audit_backend(manager, state).gates if g.key == 'mqtt_link')
        backend._on_connect(backend.client, None, {}, 0)
        self.assertFalse(gate().passed)
        count = len(backend.client.subscriptions[0])
        backend._on_subscribe(backend.client, None, 17, [1] * count, None)
        self.assertTrue(gate().passed)

    def test_legacy_raw_video_cannot_inherit_official_udp_qualification(self):
        from rm_client.backend.readiness import audit_backend
        udp = dict(connected=True, decoded_connected=True, decoded_frames=10)
        manager = SimpleNamespace(stats=lambda: {'udp': udp})
        state = SimpleNamespace(backend_stats={})
        def gate():
            return next(g for g in audit_backend(manager, state,
                live_evidence={'video_source': 'udp'}).gates if g.key == 'video_link')
        udp['ingress_mode'] = 'shark-framed'
        self.assertTrue(gate().passed)
        udp['ingress_mode'] = 'legacy-vt02-h264'
        self.assertFalse(gate().passed)


    def test_real_paho_rejected_suback_and_retained_delivery(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from referee_integration_test import LoopbackBroker
        class Broker(LoopbackBroker):
            def __init__(self, *, deny):
                self.deny = deny
                super().__init__()
            def send(self, header, payload):
                if header == 0x90 and self.deny:
                    payload = payload[:-1] + b'\x80'
                elif header == 0x32 and not self.deny:
                    # Replay only GameStatus as retained; RobotDynamicStatus
                    # remains a real non-retained downstream delivery.
                    length = int.from_bytes(payload[:2], 'big')
                    if payload[2:2 + length] == b'GameStatus':
                        header |= 1
                super().send(header, payload)
        for deny in (True, False):
            with self.subTest(deny=deny):
                broker = Broker(deny=deny)
                backend = RmMqttBackend(host='127.0.0.1', port=broker.port, mock_output=False)
                try:
                    backend.start()
                    deadline = time.monotonic() + 3.
                    while time.monotonic() < deadline:
                        done = (backend._subscription_error if deny else backend.messages_received >= 2)
                        if broker.ready.is_set() and done:
                            break
                        time.sleep(.01)
                    self.assertTrue(broker.ready.is_set())
                    self.assertEqual(broker.error, '')
                    self.assertFalse(backend.safety.is_fighting())
                    if deny:
                        self.assertFalse(backend.connected)
                        self.assertTrue(backend._reconnect_required)
                        self.assertIn('SUBACK', backend.last_error)
                        self.assertEqual(backend.drain_decoded(), [])
                        self.assertEqual(backend.drain_received_messages(), [])
                    else:
                        self.assertTrue(backend.connected)
                        self.assertTrue(backend.stats()['subscriptions_ready'])
                        self.assertEqual(backend.retained_messages_ignored, 1)
                        self.assertEqual([row[1] for row in backend.drain_decoded()], ['RobotDynamicStatus'])
                        self.assertEqual(len(backend.drain_received_messages()), 1)
                finally:
                    backend.stop()
                    broker.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
