"""Real decoded projection with an inert manager shell; no transport owners.

Presentation callbacks receive detached containers, including callbacks that
retain data or mutate it before raising. This is not a security sandbox for
callbacks holding a separate reference to the manager/state.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rm_client.backend.manager import BackendManager
from rm_client.backend.referee.registry import get_profile
from rm_client.model import RobotState
from rm_client.referee_profiles import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE


class RefereeObserverOwnership(unittest.TestCase):
    def make_backend(self, observer, profile=DEFAULT_PROFILE):
        # Bypass construction explicitly: no MQTT/serial/video/logger workers.
        backend = BackendManager.__new__(BackendManager)
        backend.referee = get_profile(profile)
        backend.referee_adapter = backend.referee.create_state_adapter(backend)
        backend.referee_view_observer = observer
        backend._referee_view_error = ""
        backend._last_apply_error = ""
        backend._apply_error_count = backend._official_state_updates_count = 0
        backend._backend_transition_blocks_work = lambda: False
        backend.stats = lambda: {}
        backend.sync_frontend_state = lambda state: None
        backend.queue = []
        def drain():
            batch, backend.queue = backend.queue, []
            return batch
        backend.mqtt = SimpleNamespace(drain_decoded=drain)
        return backend, RobotState()

    def enqueue(self, backend, name, payload):
        data = backend.referee.codec.decode_message(name, payload)
        backend.queue.append((name, name, data, 10.0))
        return data

    def test_repeated_fields_cannot_mutate_authoritative_state_before_observer_error(self):
        for profile in (DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE):
            with self.subTest(profile=profile):
                def observe(name, incoming, stamp):
                    self.assertEqual(state.path_plan['offset_x'], [1, 2])
                    incoming['offset_x'].clear()
                    raise RuntimeError('presentation only')
                backend, state = self.make_backend(observe, profile)
                data = self.enqueue(backend, 'RobotPathPlanInfo', b'\x22\x02\x01\x02\x2a\x02\x03\x04')
                self.assertEqual(backend.apply_updates(state), 1)
                self.assertEqual(state.path_plan['offset_x'], [1, 2])
                self.assertEqual(data['offset_x'], [1, 2])
                self.assertEqual(backend._official_state_updates_count, 1)
                self.assertEqual(backend._apply_error_count, 0)
                self.assertEqual(backend._referee_view_error, 'RuntimeError: presentation only')

    def test_retained_observer_lists_are_detached_in_both_directions(self):
        seen = []
        backend, state = self.make_backend(lambda name, data, stamp: seen.append(data))
        data = self.enqueue(backend, 'RobotPathPlanInfo', b'\x22\x02\x01\x02\x2a\x02\x03\x04')
        self.assertEqual(backend.apply_updates(state), 1)
        seen[0]['offset_x'].append(99)
        self.assertEqual(state.path_plan['offset_x'], [1, 2])
        self.assertEqual(data['offset_x'], [1, 2])
        state.path_plan['offset_y'].append(88)
        self.assertEqual(seen[0]['offset_y'], [3, 4])

    def test_nested_decoded_dictionary_is_detached_from_observer(self):
        seen = []
        backend, state = self.make_backend(lambda name, data, stamp: seen.append(data))
        data = self.enqueue(backend, 'RadarInfoToClient', b'\x0a\x06\x08\x01\x10\x02\x18\x01')
        expected = deepcopy(data)
        self.assertEqual(backend.apply_updates(state), 1)
        seen[0]['robots'][0]['target_pos_x'] = 999
        self.assertEqual(data, expected)
        self.assertEqual(state.radar_detections[0]['target_pos_x'], 1)

    def test_copy_failure_is_presentation_error_and_next_message_still_applies(self):
        seen = []
        backend, state = self.make_backend(lambda *args: seen.append(args))
        self.enqueue(backend, 'RobotPathPlanInfo', b'\x22\x02\x01\x02')
        self.enqueue(backend, 'GlobalLogisticsStatus', b'\x08\x4d')
        with patch('rm_client.backend.manager.deepcopy', side_effect=ValueError('copy failed')):
            self.assertEqual(backend.apply_updates(state), 2)
        self.assertEqual(state.path_plan['offset_x'], [1, 2])
        self.assertEqual(state.remaining_economy, 77)
        self.assertEqual(backend._official_state_updates_count, 2)
        self.assertEqual(backend._apply_error_count, 0)
        self.assertEqual(backend._referee_view_error, 'ValueError: copy failed')
        self.assertEqual(seen, [])


if __name__ == '__main__':
    unittest.main()
