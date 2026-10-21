"""A retained MQTT snapshot has no verified age and cannot become live evidence."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.registry import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE
from rm_client.referee_profiles import V2_PROFILE


class RetainedEvidenceTests(unittest.TestCase):
    def test_retained_match_stage_is_not_fresh_official_evidence(self):
        for profile in (DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, V2_PROFILE):
            with self.subTest(profile=profile):
                backend = RmMqttBackend(referee_profile=profile)
                backend.client = object()
                backend.connected = True
                backend._on_message(backend.client, None,
                    SimpleNamespace(topic='GameStatus', payload=b'\x28\x04', retain=True))
                self.assertFalse(backend.safety.is_fighting())
                self.assertEqual(backend.drain_decoded(), [])
                self.assertEqual(backend.drain_received_messages(), [])
                self.assertIsNone(backend.v2_wire_snapshot())
                self.assertEqual(backend.stats()['retained_messages_ignored'], 1)

    def test_retained_packet_cannot_replace_current_live_phase(self):
        backend = RmMqttBackend()
        backend.client = object()
        backend.connected = True
        backend._subscriptions_ready = True  # Accepted current-session fixture.
        backend._on_message(backend.client, None,
            SimpleNamespace(topic='GameStatus', payload=b'\x28\x01', retain=False))
        backend.drain_decoded()
        backend.drain_received_messages()
        backend._on_message(backend.client, None,
            SimpleNamespace(topic='GameStatus', payload=b'\x28\x04', retain=True))
        self.assertEqual(backend.safety.current_stage, '1')
        self.assertFalse(backend.safety.is_fighting())
        self.assertEqual(backend.drain_decoded(), [])
        self.assertEqual(backend.drain_received_messages(), [])

    def test_following_live_delivery_still_updates_stage_and_queues(self):
        backend = RmMqttBackend()
        backend.client = object()
        backend.connected = True
        backend._subscriptions_ready = True  # Accepted current-session fixture.
        for retained in (True, False):
            backend._on_message(backend.client, None,
                SimpleNamespace(topic='GameStatus', payload=b'\x28\x04', retain=retained))
        self.assertTrue(backend.safety.is_fighting())
        self.assertEqual(len(backend.drain_decoded()), 1)
        self.assertEqual(len(backend.drain_received_messages()), 1)
        self.assertEqual(backend.stats()['retained_messages_ignored'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
