"""Callback-entry age through real codecs/queues; no network or native owners."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.registry import get_profile
from rm_client.combat_events import OfficialMatchFeed
from rm_client.referee_profiles import STUDENT_PREVIEW_PROFILE
from rm_client.transports import OfficialMqttBridge


class MqttCallbackReceiptTime(unittest.TestCase):
    def make_backend(self):
        backend = RmMqttBackend()
        backend.client = object()  # Callback identity only; never connect/start.
        return backend

    def test_hook_and_decode_delays_remain_part_of_both_queue_ages(self):
        for delayed_step in ('hook', 'decode'):
            with self.subTest(delayed_step=delayed_step):
                backend = self.make_backend()
                clock = [100.0]
                original_decode = backend.referee.codec.decode_message
                def decode(*args):
                    if delayed_step == 'decode':
                        clock[0] = 104.0
                    return original_decode(*args)
                def hook(*args, **kwargs):
                    if delayed_step == 'hook':
                        clock[0] = 104.0
                backend.event_hook = hook
                with patch('time.perf_counter', side_effect=lambda: clock[0]), \
                     patch.object(backend.referee.codec, 'decode_message', side_effect=decode):
                    backend._on_message(backend.client, None, SimpleNamespace(topic='Event', payload=b'\x08\x01'))
                    raw = backend.drain_received_messages()
                    decoded = backend.drain_decoded()
                    self.assertEqual(backend.invalid_messages, 0)
                    self.assertEqual(len(raw), 1)
                    self.assertEqual(len(decoded), 1)
                    self.assertEqual((raw[0][2], decoded[0][3]), (100.0, 100.0))
                    feed = OfficialMatchFeed()
                    events, updates = feed.consume(raw[0][0], raw[0][1], alliance='Red',
                                                   local_robot_id=3, received_at=raw[0][2])
                    self.assertEqual((events, updates), ([], {}))
                    self.assertEqual(feed.last_message_at, 0.0)

    def test_fresh_event_uses_callback_time_even_after_short_hook_delay(self):
        backend = self.make_backend()
        clock = [100.0]
        backend.event_hook = lambda *args, **kwargs: clock.__setitem__(0, 100.5)
        with patch('time.perf_counter', side_effect=lambda: clock[0]):
            backend._on_message(backend.client, None, SimpleNamespace(topic='Event', payload=b'\x08\x01'))
            topic, payload, stamp = backend.drain_received_messages()[0]
            events, updates = OfficialMatchFeed().consume(topic, payload, alliance='Red',
                                                          local_robot_id=3, received_at=stamp)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].timestamp, 100.0)
        self.assertEqual(updates['official_feed_at'], 100.0)
        self.assertEqual(backend.drain_decoded()[0][3], 100.0)

    def test_generation_profile_and_client_changes_during_hook_discard_old_callback(self):
        for changed in ('generation', 'profile', 'client'):
            with self.subTest(changed=changed):
                backend = self.make_backend()
                def hook(*args, **kwargs):
                    if changed == 'generation':
                        backend.clear_received_epoch()
                    elif changed == 'profile':
                        backend.referee = get_profile(STUDENT_PREVIEW_PROFILE)
                    else:
                        backend.client = object()
                backend.event_hook = hook
                with patch('time.perf_counter', return_value=100.0):
                    backend._on_message(backend.client, None, SimpleNamespace(topic='Event', payload=b'\x08\x01'))
                self.assertEqual(backend.drain_received_messages(), [])
                self.assertEqual(backend.drain_decoded(), [])

    def test_invalid_and_unknown_packets_never_publish_receipt(self):
        backend = self.make_backend()
        for topic, payload in (('Event', b'\x08'), ('unknown', b'\x08\x01')):
            backend._on_message(backend.client, None, SimpleNamespace(topic=topic, payload=payload))
        self.assertEqual(backend.invalid_messages, 1)
        self.assertEqual(backend.ignored_topics, 1)
        self.assertEqual(backend.drain_received_messages(), [])
        self.assertEqual(backend.drain_decoded(), [])

    def test_explicit_bridge_timestamp_is_preserved_without_clock_resampling(self):
        bridge = OfficialMqttBridge()
        with patch('time.perf_counter', side_effect=AssertionError('must not resample')):
            bridge._on_message(None, None, SimpleNamespace(topic='example', payload=b'payload'),
                               received_at=100.0)
        self.assertEqual(bridge.drain_received_messages(), [('example', b'payload', 100.0)])

    def test_direct_bridge_three_argument_callback_keeps_entry_time(self):
        bridge = OfficialMqttBridge()
        clock = [100.0]
        class Payload:
            def __bytes__(self):
                clock[0] = 104.0
                return b'payload'
        with patch('time.perf_counter', side_effect=lambda: clock[0]):
            bridge._on_message(None, None, SimpleNamespace(topic='example', payload=Payload()))
        self.assertEqual(bridge.drain_received_messages(), [('example', b'payload', 100.0)])
        self.assertEqual(bridge.messages_received, 1)


if __name__ == '__main__':
    unittest.main()
