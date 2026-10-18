"""Synchronous UI callback reentry through real codecs and endpoint generations."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_official_feed_receive_freshness import ReceiveHarness
from test_official_feed_projection_authority import packed
from rm_client.model import build_default_registry
from rm_client.ui.polar.mixins.video_backend_mixin import VideoBackendMixin
from rm_client.ui.polar_app import PolarRMWindow
from rm_client.ui.polar.mixins.persistence_mixin import PersistenceMixin


class CallbackHost(ReceiveHarness, VideoBackendMixin):
    setting_bool = PolarRMWindow.setting_bool
    setting_mode = PolarRMWindow.setting_mode
    get_setting_number = PersistenceMixin.get_setting_number

    def __init__(self):
        super().__init__()
        del self.accept_combat_event  # Exercise the actual acceptance/callback path.
        self.registry = build_default_registry()
        self.registry.get('EliminationFX').enabled = False
        self.registry.get('MatchChat').enabled = True
        self.delivered = []
        self.on_event = lambda event: None
        self.chat_event_adapter = SimpleNamespace(combat=self.record)
        self.student_notice_adapter = SimpleNamespace(combat=lambda *args: None)

    def record(self, event):
        self.delivered.append(event.victim_id)
        self.on_event(event)

    def roster(self, hp, now):
        self.receive('GlobalUnitStatus', packed(11, [100]*5 + hp + [100]*(5-len(hp))), now)

    def switch(self):
        self.mqtt.set_address('new.invalid', 4444)


class OfficialFeedCallbackEpochTests(unittest.TestCase):
    def host(self):
        host = CallbackHost()
        host.roster([100, 100], 100.)
        host.consume(100.)
        return host

    def test_reentry_stops_same_payload_and_later_packet_and_future_batch_recovers(self):
        host = self.host()
        host.on_event = lambda event: host.switch()
        host.roster([0, 0], 100.1)
        host.receive('Event', b'\x08\x01', 100.2)
        host.consume(100.3)
        self.assertEqual(host.delivered, [101])
        self.assertEqual(host.state.referee_kill_count, 1)
        self.assertEqual(host.state.official_feed_at, 0.)
        self.assertFalse(host.state.official_events_online)
        self.assertEqual(host.official_feed._robot_health, [])
        host.on_event = lambda event: None
        host.roster([100, 100], 100.4)
        host.consume(100.4)
        host.roster([100, 0], 100.5)
        host.consume(100.5)
        self.assertEqual(host.delivered, [101, 102])

    def test_last_event_change_clears_pending_receipt_without_another_poll(self):
        host = self.host()
        host.on_event = lambda event: host.switch()
        host.roster([0, 100], 100.1)
        host.consume(100.2)
        self.assertEqual(host.delivered, [101])
        self.assertEqual(host.official_feed.last_message_at, 0.)
        self.assertEqual(host.state.official_feed_at, 0.)
        self.assertFalse(host.state.official_events_online)

    def test_nested_new_generation_consumer_history_is_not_reset_by_outer_batch(self):
        host = self.host()
        def nested(event):
            host.on_event = lambda event: None
            host.switch()
            host.roster([100, 100], 100.3)
            host.consume(100.3)
        host.on_event = nested
        host.roster([0, 0], 100.1)
        host.receive('Event', b'\x08\x01', 100.2)
        host.consume(100.4)
        self.assertEqual(host.delivered, [101])
        self.assertEqual(host.official_feed.last_message_at, 100.3)
        self.assertEqual(host.state.official_feed_at, 100.3)
        self.assertTrue(host.state.official_events_online)
        host.roster([100, 0], 100.5)
        host.consume(100.5)
        self.assertEqual(host.delivered, [101, 102])

    def test_stable_generation_delivers_entire_batch(self):
        host = self.host()
        host.roster([0, 0], 100.1)
        host.receive('Event', b'\x08\x01', 100.2)
        host.consume(100.3)
        self.assertEqual(host.delivered, [101, 102, 0])
        self.assertEqual(host.state.official_feed_at, 100.2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
