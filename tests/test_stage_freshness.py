"""Local fail-closed stage deadline, receipt ownership, and final wire guard."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.safety import OfficialSafety, ControlState
from rm_client.backend.manager import BackendManager
from rm_client.model import RobotState


class StageFreshnessTests(unittest.TestCase):
    def backend(self):
        safety = OfficialSafety(stage_timeout_s=1.)
        safety.configure(mock_writes=False, allow_mqtt_publish=True, enforce_official_limits=True)
        backend = RmMqttBackend(safety=safety, mock_output=False)
        backend.client = NS(sent=[], publish=lambda *a, **kw: backend.client.sent.append(a) or NS(rc=0))
        backend.connected = True
        # These receipt/deadline cases begin in an admitted MQTT session;
        # early-SUBACK rejection has its own subscription admission tests.
        backend._subscriptions_ready = True
        return backend

    def receipt(self, backend, stamp=100., payload=b'\x28\x04', retained=False):
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=stamp):
            backend._on_message(backend.client, None, NS(topic='GameStatus', payload=payload, retain=retained))

    def test_deadline_is_local_configurable_and_validated(self):
        for timeout in (0., -1., float('inf'), float('nan'), True, '1', 1 << 10000):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                OfficialSafety(stage_timeout_s=timeout)
        safety = OfficialSafety(stage_timeout_s=.4)
        safety.update_stage(4, now=100.)
        self.assertTrue(safety.is_fighting(now=100.399))
        for now in (100.4, 99.9, float('nan'), float('inf'), -1.):
            self.assertFalse(safety.is_fighting(now=now))

    def test_invalid_receipt_clock_cannot_preserve_authority(self):
        for stamp in (None, '100', float('nan'), float('inf'), -1., True, 1 << 10000):
            with self.subTest(stamp=stamp):
                b = self.backend()
                self.receipt(b)
                b.safety.arm_match({'core_kmc'})
                self.assertTrue(b.safety.observe_stage_receipt(4, received_at=stamp))
                self.assertFalse(b.safety.is_fighting(now=100.1))
                self.assertEqual(b.safety.control_state, ControlState.LOCKED)

    def test_live_messages_without_phase_and_retained_cannot_refresh(self):
        b = self.backend()
        self.receipt(b)
        self.receipt(b, 100.8, b'\x08\x01')
        self.receipt(b, 100.9, retained=True)
        self.assertTrue(b.safety.is_fighting(now=100.99))
        self.assertFalse(b.safety.is_fighting(now=101.))
        b.safety.update_stage('MATCH', now=100.99)
        self.assertFalse(b.safety.is_fighting(now=101.))

    def test_reordered_old_fighting_receipt_cannot_replace_new_phase(self):
        b = self.backend()
        self.receipt(b, 100.5, b'\x28\x01')
        self.receipt(b, 100.2, b'\x28\x04')
        self.assertEqual(b.safety.current_stage, '1')
        self.assertFalse(b.safety.is_fighting(now=100.6))
        self.assertTrue(b.safety.stage_is_fresh(now=100.6))

    def test_poll_locks_once_and_new_receipt_requires_rearm(self):
        b = self.backend()
        self.receipt(b)
        b.safety.arm_match({'core_kmc'})
        events = []
        b.safety.input_clear_hook = events.append
        generation = b.safety.control_generation
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=101.1):
            b.poll_connection()
            b.poll_connection()
        self.assertEqual(b.safety.control_state, ControlState.LOCKED)
        self.assertEqual(b.safety.control_generation, generation + 1)
        self.assertEqual(len(events), 1)
        self.receipt(b, 101.2)
        self.assertTrue(b.safety.is_fighting(now=101.2))
        self.assertFalse(b.safety.can_publish('KeyboardMouseControl', now=101.2)[0])
        b.safety.arm_match({'core_kmc'})
        self.assertTrue(b.safety.can_publish('KeyboardMouseControl', now=101.2)[0])

    def test_gap_receipt_revokes_even_without_poll_and_callback_defers_observer(self):
        b = self.backend()
        self.receipt(b)
        b.safety.arm_match({'core_kmc'})
        threads = []
        b.safety.input_clear_hook = lambda reason: threads.append(threading.get_ident())
        worker = threading.Thread(target=lambda: self.receipt(b, 101.2))
        worker.start(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(b.safety.control_state, ControlState.LOCKED)
        self.assertEqual(threads, [])
        self.assertTrue(b.safety.is_fighting(now=101.2))
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=101.3):
            b.poll_connection()
        self.assertEqual(threads, [threading.get_ident()])

    def test_queued_ui_projection_cannot_regrant_or_refresh_phase(self):
        b = self.backend()
        self.receipt(b)
        manager = object.__new__(BackendManager)
        manager.safety = b.safety
        manager._last_logged_stage = ''
        manager.field_log = NS(emit=lambda *a, **kw: None)
        adapter = b.referee.create_state_adapter(manager)
        state = RobotState()
        b.safety.clear_stage_evidence()
        adapter._apply_one(state, 'GameStatus', {'current_stage': 4, '__present__': (5,)})
        self.assertEqual(state.current_stage, 'MATCH')
        self.assertFalse(b.safety.is_fighting(now=100.1))

    def test_final_physical_publish_rechecks_elapsed_time_and_phase(self):
        for replacement in (None, b'\x28\x01'):
            with self.subTest(replacement=replacement):
                b = self.backend()
                self.receipt(b)
                b.safety.arm_match({'core_kmc'})
                generation = b.safety.control_generation
                self.assertTrue(b.safety.can_publish('KeyboardMouseControl', now=100.1)[0])
                if replacement:
                    self.receipt(b, 100.2, replacement)
                with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=101.1 if replacement is None else 100.3):
                    with self.assertRaisesRegex(RuntimeError, 'stage'):
                        b._publish_current(b.client, b._lifecycle_generation, 'KeyboardMouseControl', b'', 1,
                                           authority_generation=generation)
                self.assertEqual(b.client.sent, [])

    def test_receipt_expiry_between_final_locks_cannot_restore_old_command(self):
        b = self.backend()
        self.receipt(b)
        b.safety.arm_match({'core_kmc'})
        generation = b.safety.control_generation
        class ReceiptBeforeDecodedLock:
            def __enter__(self):
                b.safety.expire_stage(now=101.1, notify=False)
                b.safety.update_stage(4, now=101.1)
            def __exit__(self, *args):
                pass
        b._decoded_lock = ReceiptBeforeDecodedLock()
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=101.1):
            with self.assertRaisesRegex(RuntimeError, 'authority'):
                b._publish_current(b.client, b._lifecycle_generation, 'KeyboardMouseControl', b'', 1,
                                   authority_generation=generation)
        self.assertEqual(b.client.sent, [])

    def test_real_callback_can_revoke_between_publish_locks(self):
        b = self.backend()
        self.receipt(b)
        b.safety.arm_match({'core_kmc'})
        generation = b.safety.control_generation
        blocked, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        class InterleavedLock:
            def __enter__(self):
                if threading.current_thread().name == 'held-publish':
                    blocked.set()
                    if not release.wait(2):
                        raise RuntimeError('test barrier timed out')
                lock.acquire()
            def __exit__(self, *args):
                lock.release()
        b._decoded_lock = InterleavedLock()
        errors = []
        def publish():
            try:
                b._publish_current(b.client, b._lifecycle_generation, 'KeyboardMouseControl', b'', 1,
                                   authority_generation=generation)
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=publish, name='held-publish')
        thread.start()
        try:
            self.assertTrue(blocked.wait(2))
            self.receipt(b, 101.2)
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any('authority' in error for error in errors), errors)
        self.assertEqual(b.client.sent, [])

    def test_expiry_preserves_estop_and_supervised_neutral_qualification(self):
        b = self.backend()
        self.receipt(b)
        token = b.safety.begin_qualification({'core_kmc'}, now=100.)
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=102.):
            b.poll_connection()
        self.assertTrue(b.safety.can_publish('KeyboardMouseControl', now=102., intent='core_kmc',
                                            qualification_token=token.value)[0])
        self.receipt(b, 103.)
        b.safety.trigger_estop()
        generation = b.safety.control_generation
        with patch('rm_client.backend.mqtt_backend.time.perf_counter', return_value=104.):
            b.poll_connection()
        self.assertEqual(b.safety.control_state, ControlState.ESTOP)
        self.assertEqual(b.safety.control_generation, generation)


if __name__ == '__main__':
    unittest.main()
