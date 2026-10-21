"""Retire detached decoded batches without losing current state or HUD projection.

Real validation/adapter and inert owners only; no transport is started.
"""
from pathlib import Path
from queue import Queue
from types import SimpleNamespace as NS
from unittest.mock import patch
import struct
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend.manager import BackendManager
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.model import RobotState


class DecodedBatchEpochTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket', 'serial.Serial', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('native acquisition forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        b = self.backend = object.__new__(BackendManager)
        b.mqtt = RmMqttBackend()
        b.mqtt.client = object()  # Callback identity only; no transport owner.
        b.mqtt.connected = True
        b.mqtt._subscriptions_ready = True
        b.safety = b.mqtt.safety
        b.referee = b.mqtt.referee
        b.referee_adapter = b.referee.create_state_adapter(b)
        b._referee_view_error = b._last_apply_error = ''
        b._apply_error_count = b._official_state_updates_count = 0
        b._referee_change_error = b._input_clear_error = ''
        b._input_clear_requests = Queue()
        b._lifecycle = NS(blocks_work=False)
        b.field_log = NS(emit=lambda *a, **kw: None)
        self.state = b.state = RobotState(current_heat=42., remaining_ammo=180,
            official_state_active=True, official_state_at=90., mock_simulation_enabled=False)
        self.stats_calls = []
        self.sync_calls = []
        def stats():
            self.stats_calls.append(b.mqtt.receive_generation)
            return {'probe_generation': b.mqtt.receive_generation, 'updates': b._official_state_updates_count}
        def sync(state):
            self.sync_calls.append(b.mqtt.receive_generation)
            return BackendManager.sync_frontend_state(b, state)
        b.stats = stats
        b.sync_frontend_state = sync

    def receive(self, payload, stamp):
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=stamp):
            self.backend.mqtt._on_message(self.backend.mqtt.client, None,
                NS(topic='RobotDynamicStatus', payload=payload))
        self.assertEqual(self.backend.mqtt.invalid_messages, 0)

    def heat(self, value=15., stamp=100.1):
        self.receive(b'\x15' + struct.pack('<f', value), stamp)

    def pair(self):
        self.receive(b'\x48\x0c', 100.)
        self.heat()

    def apply(self):
        return self.backend.apply_updates(self.state)

    def disconnect(self):
        mqtt = self.backend.mqtt
        mqtt._on_disconnect(mqtt.client, None, _reason_code='inert proof')

    def reconnect(self):
        # A post-disconnect batch needs a new admitted connection, not a late
        # callback from the retired socket. No real transport is acquired.
        mqtt = self.backend.mqtt
        mqtt.client = NS(subscribe=lambda topics: (0, 1))
        mqtt._on_connect(mqtt.client, None, {}, 0)
        mqtt._on_subscribe(mqtt.client, None, 1, [0] * len(mqtt.referee.codec.DOWNLINK_MESSAGES))

    def assert_first_only(self):
        self.assertEqual((self.state.remaining_ammo, self.state.current_heat), (12, 42.))
        self.assertEqual(self.state.official_state_at, 100.)
        self.assertEqual(self.backend._official_state_updates_count, 1)
        self.assertEqual(self.backend._apply_error_count, 0)
        self.assertEqual((self.stats_calls, self.sync_calls), ([1], [1]))

    def test_stable_generation_applies_all_with_original_receipt_times(self):
        self.pair()
        seen = []
        self.backend.referee_view_observer = lambda name, data, stamp: seen.append(stamp)
        self.assertEqual(self.apply(), 2)
        self.assertEqual((self.state.remaining_ammo, self.state.current_heat), (12, 15.))
        self.assertEqual((self.state.official_state_at, seen), (100.1, [100., 100.1]))
        self.assertEqual((self.stats_calls, self.sync_calls), ([0], [0]))

    def test_empty_batch_does_not_refresh(self):
        self.assertEqual(self.apply(), 0)
        self.assertEqual((self.stats_calls, self.sync_calls), ([], []))
        self.assertEqual(self.state.official_state_at, 90.)

    def test_transition_block_leaves_batch_queued(self):
        self.pair()
        self.backend._lifecycle.blocks_work = True
        self.assertEqual(self.apply(), 0)
        self.assertEqual(len(self.backend.mqtt.drain_decoded()), 2)
        self.assertEqual((self.state.remaining_ammo, self.state.current_heat), (180, 42.))

    def test_actual_background_disconnect_stops_remaining_batch(self):
        self.pair()
        entered, retired = threading.Event(), threading.Event()
        errors = []
        def observer(name, data, stamp):
            if stamp == 100.:
                entered.set()
                self.assertTrue(retired.wait(2), 'disconnect callback stalled')
        def worker():
            try:
                if not entered.wait(2):
                    raise AssertionError('observer barrier not reached')
                self.disconnect()
            except BaseException as exc:
                errors.append(exc)
            finally:
                retired.set()
        self.backend.referee_view_observer = observer
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            count = self.apply()
        finally:
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(count, 1)
        self.assertEqual(self.backend.mqtt.receive_generation, 1)
        self.assertFalse(self.backend.mqtt.connected)
        self.assert_first_only()

    def test_actual_endpoint_change_stops_remaining_batch(self):
        self.pair()
        self.backend.referee_view_observer = lambda *args: self.backend.mqtt.set_address('new.invalid', 4444)
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.backend.mqtt.receive_generation, 1)
        self.assert_first_only()

    def test_same_endpoint_noop_does_not_discard_current_batch(self):
        self.pair()
        mqtt = self.backend.mqtt
        self.backend.referee_view_observer = lambda *args: mqtt.set_address(mqtt.host, mqtt.port)
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state.current_heat, 15.)
        self.assertEqual(mqtt.receive_generation, 0)

    def test_retirement_on_last_record_preserves_current_runtime_refresh(self):
        self.heat()
        self.backend.referee_view_observer = lambda *args: self.disconnect()
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.state.current_heat, 15.)  # No rollback of completed apply.
        self.assertEqual((self.stats_calls, self.sync_calls), ([1], [1]))

    def test_raising_observer_after_retirement_does_not_resume_old_batch(self):
        self.pair()
        def observer(*args):
            self.disconnect()
            raise RuntimeError('presentation failed after retirement')
        self.backend.referee_view_observer = observer
        self.assertEqual(self.apply(), 1)
        self.assert_first_only()
        self.assertEqual(self.backend._referee_view_error, 'RuntimeError: presentation failed after retirement')

    def test_raising_observer_without_retirement_preserves_existing_continuation(self):
        self.pair()
        def observer(*args):
            raise RuntimeError('presentation only')
        self.backend.referee_view_observer = observer
        self.assertEqual(self.apply(), 2)
        self.assertEqual(self.state.current_heat, 15.)
        self.assertEqual(self.backend._apply_error_count, 0)

    def test_non_exception_callback_failure_preserves_original_propagation(self):
        class StopObserver(BaseException):
            pass
        failure = StopObserver('do not swallow')
        self.pair()
        def observer(*args):
            self.disconnect()
            self.reconnect()
            self.heat(7., 102.)
            raise failure
        self.backend.referee_view_observer = observer
        with self.assertRaises(StopObserver) as caught:
            self.apply()
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.state.current_heat, 42.)
        self.assertEqual(len(self.backend.mqtt._decoded), 1)
        self.assertEqual((self.stats_calls, self.sync_calls), ([], []))
        self.backend.referee_view_observer = None
        self.assertEqual(self.apply(), 1)
        self.assertEqual((self.state.current_heat, self.state.official_state_at), (7., 102.))

    def test_new_generation_queue_is_not_cleared_by_outer_retirement(self):
        self.pair()
        def observer(*args):
            self.backend.referee_view_observer = None
            self.disconnect()
            self.reconnect()
            self.heat(7., 102.)
        self.backend.referee_view_observer = observer
        self.assertEqual(self.apply(), 1)
        self.assert_first_only()
        self.assertEqual(len(self.backend.mqtt._decoded), 1)
        self.assertEqual(len(self.backend.mqtt._received_messages), 1)
        self.assertEqual(self.apply(), 1)
        self.assertEqual((self.state.current_heat, self.state.official_state_at), (7., 102.))
        self.assertEqual((self.stats_calls, self.sync_calls), ([1, 1], [1, 1]))

    def test_nested_new_generation_apply_preserves_new_state_and_current_refresh(self):
        self.check_nested(False)

    def test_nested_new_generation_apply_survives_outer_observer_exception(self):
        self.check_nested(True)

    def check_nested(self, fail):
        self.pair()
        nested = []
        def observer(*args):
            self.backend.referee_view_observer = None
            self.disconnect()
            self.reconnect()
            self.heat(7., 102.)
            nested.append(self.apply())
            if fail:
                raise RuntimeError('outer observer failed')
        self.backend.referee_view_observer = observer
        self.assertEqual(self.apply(), 1)
        self.assertEqual(nested, [1])
        self.assertEqual((self.state.current_heat, self.state.official_state_at), (7., 102.))
        self.assertEqual(self.backend._official_state_updates_count, 2)
        self.assertEqual((self.stats_calls, self.sync_calls), ([1, 1], [1, 1]))
        self.assertEqual(self.state.backend_stats['probe_generation'], 1)
        self.assertEqual(self.state.backend_stats['updates'], 2)
        self.assertEqual(self.backend._apply_error_count, 0)

    def test_epoch_retired_inside_drain_is_checked_before_first_apply(self):
        self.pair()
        drain = self.backend.mqtt.drain_decoded
        def retiring_drain():
            batch = drain()
            self.disconnect()
            return batch
        self.backend.mqtt.drain_decoded = retiring_drain
        self.assertEqual(self.apply(), 0)
        self.assertEqual((self.state.remaining_ammo, self.state.current_heat), (180, 42.))
        self.assertEqual(self.state.official_state_at, 90.)
        self.assertEqual((self.stats_calls, self.sync_calls), ([1], [1]))

    def test_snapshot_precedes_drain_even_when_returned_batch_is_newer(self):
        self.pair()
        drain = self.backend.mqtt.drain_decoded
        def crossed_drain():
            self.disconnect()
            self.reconnect()
            self.heat(7., 102.)
            return drain()
        self.backend.mqtt.drain_decoded = crossed_drain
        self.assertEqual(self.apply(), 0)  # Conservatively reject an unattributable batch.
        self.assertEqual((self.state.current_heat, self.state.official_state_at), (42., 90.))
        self.assertEqual((self.stats_calls, self.sync_calls), ([1], [1]))

    def test_malformed_apply_without_retirement_keeps_next_valid_record(self):
        self.pair()
        apply_one = self.backend._apply_one
        def apply_one_with_failure(state, name, data):
            if 'remaining_ammo' in data and 9 in data.get('__present__', ()):
                raise ValueError('inert apply error')
            return apply_one(state, name, data)
        self.backend._apply_one = apply_one_with_failure
        self.assertEqual(self.apply(), 1)
        self.assertEqual((self.state.remaining_ammo, self.state.current_heat), (180, 15.))
        self.assertEqual(self.backend._apply_error_count, 1)

    def test_failing_apply_that_retires_epoch_cannot_apply_next_record(self):
        self.pair()
        def retiring_apply(*args):
            self.disconnect()
            raise ValueError('retired during failed apply')
        self.backend._apply_one = retiring_apply
        self.assertEqual(self.apply(), 0)
        self.assertEqual((self.state.remaining_ammo, self.state.current_heat), (180, 42.))
        self.assertEqual(self.backend._apply_error_count, 1)
        self.assertEqual((self.stats_calls, self.sync_calls), ([1], [1]))

    def test_completed_first_record_still_projects_hud_after_disconnect(self):
        self.receive(b'\x08\x7b\x48\x0c', 100.)  # health 123, ammo 12
        self.heat()
        self.backend.referee_view_observer = lambda *args: self.disconnect()
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.state.current_health, 123)
        local = next(row for row in self.state.robot_rows if row['id'] == self.state.robot_id)
        self.assertEqual(local['hp'], 123)
        self.assertTrue(self.state.backend_frontend_synced)
        self.assertEqual(self.state.current_heat, 42.)
        self.assertEqual(self.state.backend_stats['updates'], 1)

    def test_same_generation_nested_apply_keeps_existing_outer_order(self):
        self.pair()
        def observer(*args):
            self.backend.referee_view_observer = None
            self.heat(7., 102.)
            self.assertEqual(self.apply(), 1)
        self.backend.referee_view_observer = observer
        self.assertEqual(self.apply(), 2)
        self.assertEqual((self.state.current_heat, self.state.official_state_at), (15., 102.))
        self.assertEqual(self.backend._official_state_updates_count, 3)
        self.assertEqual((self.stats_calls, self.sync_calls), ([0, 0], [0, 0]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
