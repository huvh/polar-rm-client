"""Actual endpoint epoch changes through inert MQTT queues and UI consumers."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_official_feed_receive_freshness import ReceiveHarness
from test_official_feed_projection_authority import packed
from rm_client.ui.polar.mixins.video_backend_mixin import VideoBackendMixin


class OfficialFeedReceiveEpoch(unittest.TestCase):
    def roster(self, host, enemy_hp, now):
        host.receive('GlobalUnitStatus', packed(11, [100] * 5 + [enemy_hp] + [100] * 4), now)
        host.consume(now)

    def change_endpoint(self, host, now):
        with patch('time.perf_counter', return_value=now):
            self.assertTrue(host.mqtt.set_address('new.invalid', 4444))

    def test_new_endpoint_first_dead_roster_is_not_a_cross_endpoint_kill(self):
        host = ReceiveHarness()
        self.roster(host, 100, 100.0)
        previous = host.mqtt.receive_generation
        self.change_endpoint(host, 100.5)
        self.assertGreater(host.mqtt.receive_generation, previous)
        self.assertEqual(host.mqtt.drain_received_messages(), [])
        self.roster(host, 0, 101.0)
        self.assertEqual(host.accepted, [])
        self.roster(host, 100, 101.5)
        self.roster(host, 0, 102.0)
        self.assertEqual([(e.kind, e.victim_id) for e in host.accepted], [('elimination', 101)])

    def test_empty_epoch_change_clears_feed_freshness_roster_dedupe_and_pending_receipt(self):
        host = ReceiveHarness()
        self.roster(host, 100, 100.0)
        host.receive('Event', b'\x08\x01', 100.1)
        host.consume(100.1)
        self.assertTrue(host.official_feed._seen)
        self.assertTrue(host.official_feed._robot_health)
        # Pending old receipt must not be republished after clearing the feed;
        # unrelated explicit compatibility updates are not owned by this reset.
        host._official_state_updates = {'official_feed_at': 100.1, 'remaining_economy': 77}
        self.change_endpoint(host, 100.5)
        host.consume(100.5)
        self.assertFalse(host.state.official_events_online)
        self.assertEqual(host.state.official_feed_at, 0.0)
        self.assertEqual(host.state.remaining_economy, 77)
        self.assertEqual(host.official_feed.last_message_at, 0.0)
        self.assertEqual(host.official_feed.last_kill_data_at, 0.0)
        self.assertEqual(host.official_feed.last_official_event_at, 0.0)
        self.assertEqual(host.official_feed._seen, {})
        self.assertEqual(host.official_feed._robot_health, [])
        host.receive('Event', b'\x08\x01', 100.6)
        host.consume(100.6)
        self.assertEqual(len(host.accepted), 2)  # Same event in the new epoch is independent.

    def test_stable_generation_empty_poll_keeps_history_and_deduplication(self):
        host = ReceiveHarness()
        self.roster(host, 100, 100.0)
        host.consume(100.1)
        self.roster(host, 0, 100.2)
        host.receive('Event', b'\x08\x01', 100.3)
        host.consume(100.3)
        count = len(host.accepted)
        host.consume(100.4)
        host.receive('Event', b'\x08\x01', 100.5)
        host.consume(100.5)
        self.assertEqual(len(host.accepted), count)
        self.assertTrue(any(e.detail == 'health_zero' for e in host.accepted))

    def test_host_without_generation_and_initial_unset_keep_direct_feed_history(self):
        for has_generation in (False, True):
            with self.subTest(has_generation=has_generation):
                host = ReceiveHarness()
                with patch('time.perf_counter', return_value=100.0):
                    host.official_feed.consume('GlobalUnitStatus', packed(11, [100] * 10),
                                               alliance='Red', local_robot_id=3)
                host.mqtt = SimpleNamespace(drain_received_messages=lambda: [
                    ('GlobalUnitStatus', packed(11, [100]*5+[0]+[100]*4), 100.5)])
                if has_generation:
                    host.mqtt.receive_generation = 7
                with patch('time.perf_counter', return_value=100.5):
                    VideoBackendMixin.consume_official_messages(host)
                self.assertEqual(len(host.accepted), 1)
                self.assertEqual(host.accepted[0].victim_id, 101)


if __name__ == '__main__':
    unittest.main()
