"""Inert DT7 recovery characterization; event barriers, never a timing benchmark."""
from dataclasses import replace
from pathlib import Path
from queue import Queue
from types import SimpleNamespace as NS
from unittest.mock import patch
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend.dt7_link import Dt7KeyMouseLink, DEFAULT_PROFILE, decode_dt7_frame
from rm_client.backend.dt7_worker import AsyncDt7KeyMouseLink
from rm_client.backend.manager import BackendManager
from rm_client.backend.safety import OfficialSafety, ControlState

class ParkedFacade(AsyncDt7KeyMouseLink):
    """Park the real worker outside its condition until explicitly released."""
    def __init__(self, **kwargs):
        self.worker_parked = threading.Event()
        self.unpark_worker = threading.Event()
        super().__init__(**kwargs)
    def _run(self):
        self.worker_parked.set()
        self.unpark_worker.wait(5)
        super()._run()

class DT7RecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.links, self.gates, self.threads = [], [], []
        self.native = patch('serial.Serial', side_effect=AssertionError('native serial forbidden'))
        self.native.start()

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for thread in self.threads:
            thread.join(3)
            self.assertFalse(thread.is_alive(), thread.name)
        for link in self.links:
            link.close()
            link.unpark_worker.set()
            self.assertTrue(link.wait_closed(3))
        self.native.stop()

    def event(self):
        gate = threading.Event()
        self.gates.append(gate)
        return gate

    def launch(self, name, action):
        started, done = threading.Event(), threading.Event()
        results, errors = [], []
        def invoke():
            started.set()
            try:
                results.append(action())
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()
        thread = threading.Thread(target=invoke, name=name)
        self.threads.append(thread)
        thread.start()
        self.assertTrue(started.wait(2), name)
        return done, results, errors

    def finish(self, call):
        done, results, errors = call
        self.assertTrue(done.wait(2), 'operation must finish before held policy is released')
        if errors:
            raise errors[0]
        return results[0]

    def make(self):
        writes = []
        safety = OfficialSafety()
        inner = Dt7KeyMouseLink(profile=dict(DEFAULT_PROFILE), mock_output=False,
            write_bytes=lambda frame: (writes.append(frame) or len(frame)))
        link = ParkedFacade(link=inner, profile=dict(DEFAULT_PROFILE), mock_output=False,
            safety=safety, max_intent_age_s=30, release_attempts=1)
        self.links.append(link)
        self.assertTrue(link.worker_parked.wait(2))
        link._latch_fault('prior fault')
        link.poll()
        token = safety.begin_qualification(['dt7_selftest'])
        return link, safety, token, writes

    def hold_policy(self, link, safety):
        entered, gate = self.event(), self.event()
        calls = []
        original = safety.can_transmit_dt7
        def policy(**kwargs):
            calls.append((threading.current_thread().name, link._cv._is_owned()))
            result = original(**kwargs)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(gate.wait(4), 'policy barrier abandoned')
            return result
        safety.can_transmit_dt7 = policy
        return entered, gate, calls

    def start_held(self):
        link, safety, token, writes = self.make()
        entered, gate, calls = self.hold_policy(link, safety)
        sender = self.launch('older-recovery', lambda: link.send(
            pressed_bits=1 << 12, qualification_token=token.value))
        self.assertTrue(entered.wait(2))
        return link, safety, token, writes, gate, calls, sender

    def rejected_unchanged(self, link, sender, gate, calls, *, fault='prior fault'):
        gate.set()
        self.assertFalse(self.finish(sender)[0])
        self.assertEqual(link._fault, fault)
        self.assertIsNone(link._latest)
        self.assertEqual(link.queued, 0)
        self.assertEqual(calls, [('older-recovery', False)])

    def test_actual_manager_expiry_observer_outside_condition_and_neutral_admitted(self):
        link, safety, token, writes = self.make()
        safety._qualification = replace(token, expires_at=time.perf_counter() - 1)
        manager = object.__new__(BackendManager)
        manager.safety, manager._dt7_link = safety, link
        manager._input_clear_requests = Queue(maxsize=1)
        manager._input_clear_generation, manager._input_clear_error = 0, ''
        manager.field_log = NS(emit=lambda *args, **kwargs: None)
        entered, gate = self.event(), self.event()
        observed = []
        def observer(reason):
            observed.append((reason, link._cv._is_owned(), safety.control_state.value,
                             threading.current_thread().name))
            entered.set()
            self.assertTrue(gate.wait(4))
        manager.input_clear_hook = observer
        safety.input_clear_hook = manager._request_input_clear
        def owner_send():
            manager._input_owner_thread = threading.get_ident()
            return link.send(pressed_bits=1 << 12, qualification_token=token.value)
        sender = self.launch('control-owner', owner_send)
        self.assertTrue(entered.wait(2))
        acquired = link._cv.acquire(blocking=False)
        if acquired:
            link._cv.release()
        self.assertTrue(acquired)
        self.assertEqual(observed, [('qualification token invalid or expired', False,
                                    'LOCKED', 'control-owner')])
        self.assertTrue(self.finish(self.launch('neutral', link.request_release))[0])
        self.assertFalse(gate.is_set())
        gate.set()
        self.assertFalse(self.finish(sender)[0])
        self.assertEqual(manager._input_clear_generation, 1)
        self.assertEqual(writes, [])
        self.assertIsNone(link._latest)
        self.assertEqual(link._fault, 'prior fault')

    def test_positive_recovery_clears_and_enqueues_once(self):
        link, safety, token, writes = self.make()
        original, calls = safety.can_transmit_dt7, []
        def policy(**kwargs):
            calls.append((kwargs, link._cv._is_owned()))
            return original(**kwargs)
        safety.can_transmit_dt7 = policy
        self.assertEqual(link.send(pressed_bits=1 << 12, qualification_token=token.value), (True, 'queued'))
        self.assertEqual(calls, [({'qualification_token': token.value}, False)])
        self.assertEqual(link._fault, '')
        self.assertFalse(link._fault_reported)
        self.assertEqual(link._latest[0]['pressed_bits'], 1 << 12)
        self.assertEqual(link.queued, 1)
        self.assertEqual(writes, [])

    def test_healthy_send_does_not_call_owner_policy(self):
        link, safety, token, _ = self.make()
        self.assertTrue(link.send(qualification_token=token.value)[0])
        with patch.object(safety, 'can_transmit_dt7', side_effect=AssertionError('not a recovery')):
            self.assertTrue(link.send(pressed_bits=1 << 12, qualification_token=token.value)[0])
        self.assertEqual(link.queued, 2)

    def test_same_epoch_fault_cannot_recover(self):
        link, safety, token, _ = self.make()
        with link._cv:
            link._fault_epoch = link._epoch()
        with patch.object(safety, 'can_transmit_dt7', side_effect=AssertionError('epoch unchanged')):
            self.assertFalse(link.send(qualification_token=token.value)[0])
        self.assertEqual(link._fault, 'prior fault')
        self.assertEqual(link.queued, 0)

    def test_already_neutral_release_invalidates_even_without_pending_barrier(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        generation = link._generation
        self.assertTrue(self.finish(self.launch('neutral', link.request_release))[0])
        self.assertEqual(link._generation, generation + 1)
        self.assertFalse(link.release_pending)
        self.rejected_unchanged(link, sender, gate, calls)

    def test_finished_neutral_barrier_still_invalidates_old_generation(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        with link._cv:
            link._link.wire_neutral = False
        self.assertFalse(self.finish(self.launch('neutral', link.request_release))[0])
        generation = link._generation
        link.unpark_worker.set()
        with link._cv:
            self.assertTrue(link._cv.wait_for(lambda: not link._release_pending, 2))
        self.assertTrue(link.wire_neutral)
        self.assertEqual(link._generation, generation)
        self.assertEqual(len(writes), 1)
        self.assertEqual(int.from_bytes(decode_dt7_frame(writes[0])['payload'][8:10], 'little'), 0)
        self.rejected_unchanged(link, sender, gate, calls)

    def test_same_text_latched_fault_invalidates_generation(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        generation = link._generation
        self.finish(self.launch('successor-fault', lambda: link._latch_fault('prior fault')))
        self.assertEqual(link._generation, generation + 1)
        self.rejected_unchanged(link, sender, gate, calls)

    def test_fault_aba_same_text_new_epoch_rejects_old_proposal(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        old_epoch = link._fault_epoch
        newer = self.launch('newer-recovery', lambda: link.send(pressed_bits=2, qualification_token=token.value))
        self.assertTrue(self.finish(newer)[0])
        self.finish(self.launch('successor-fault', lambda: link._latch_fault('prior fault')))
        self.assertNotEqual(link._fault_epoch, old_epoch)
        safety.begin_qualification(['dt7_selftest'])
        gate.set()
        self.assertFalse(self.finish(sender)[0])
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)
        self.assertEqual(link.queued, 1)
        self.assertEqual(calls, [('older-recovery', False), ('newer-recovery', False)])

    def test_safety_replacement_even_with_equal_epoch_rejects(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        replacement = OfficialSafety()
        replacement.begin_qualification(['dt7_selftest'])
        replacement.last_transition_at = safety.last_transition_at
        def change():
            with link._cv:
                link.safety = replacement
        self.finish(self.launch('replace-safety', change))
        self.rejected_unchanged(link, sender, gate, calls)

    def test_new_qualification_epoch_rejects_old_proposal(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        self.finish(self.launch('requalify', lambda: safety.begin_qualification(['dt7_selftest'])))
        self.rejected_unchanged(link, sender, gate, calls)

    def test_estop_rejects_old_proposal(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        self.finish(self.launch('estop', safety.trigger_estop))
        self.rejected_unchanged(link, sender, gate, calls)
        self.assertTrue(safety.estop_active)

    def test_closing_rejects_old_proposal(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        self.finish(self.launch('close', link.close))
        gate.set()
        self.assertEqual(self.finish(sender), (False, 'DT7 writer closed'))
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)
        self.assertEqual(link.queued, 0)
        self.assertEqual(calls, [('older-recovery', False)])

    def test_two_overlapping_recoveries_cannot_overwrite_newer_intent(self):
        link, safety, token, writes, gate, calls, sender = self.start_held()
        self.assertTrue(self.finish(self.launch('newer-recovery', lambda: link.send(
            pressed_bits=2, qualification_token=token.value)))[0])
        newer = link._latest
        self.assertEqual(link._fault, '')
        gate.set()
        self.assertFalse(self.finish(sender)[0])
        self.assertIs(link._latest, newer)
        self.assertEqual(link._latest[0]['pressed_bits'], 2)
        self.assertEqual(link.queued, 1)
        self.assertEqual(calls, [('older-recovery', False), ('newer-recovery', False)])

    def test_reentrant_release_then_policy_exception_keeps_fault_and_propagates(self):
        link, safety, token, _ = self.make()
        error = ValueError('inert policy failure')
        calls = []
        def policy(**kwargs):
            calls.append(link._cv._is_owned())
            link.request_release()
            raise error
        safety.can_transmit_dt7 = policy
        try:
            link.send(qualification_token=token.value)
        except ValueError as actual:
            self.assertIs(actual, error)
        else:
            self.fail('policy exception must retain original propagation')
        self.assertEqual(calls, [False])
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)
        self.assertEqual(link.queued, 0)

    def test_policy_false_and_observer_order_remain_synchronous(self):
        link, safety, token, _ = self.make()
        safety._qualification = replace(token, expires_at=time.perf_counter() - 1)
        original, order = safety.can_transmit_dt7, []
        safety.mark_published = lambda *args, **kwargs: order.append(('published', link._cv._is_owned()))
        safety.input_clear_hook = lambda reason: order.append(('input_clear', link._cv._is_owned()))
        link._published = (('DT7KeyboardMouseControl',), {})
        def policy(**kwargs):
            order.append(('policy_enter', link._cv._is_owned()))
            result = original(**kwargs)
            order.append(('policy_return', link._cv._is_owned()))
            return result
        safety.can_transmit_dt7 = policy
        self.assertFalse(link.send(qualification_token=token.value)[0])
        self.assertEqual(order, [('published', False), ('policy_enter', False),
                                 ('input_clear', False), ('policy_return', False)])
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)

    def test_policy_true_reentrant_release_cannot_be_undone(self):
        link, safety, token, _ = self.make()
        original, order = safety.can_transmit_dt7, []
        def policy(**kwargs):
            order.append(('policy', link._cv._is_owned()))
            result = original(**kwargs)
            order.append(('callback', link._cv._is_owned()))
            link.request_release()
            return result
        safety.can_transmit_dt7 = policy
        self.assertFalse(link.send(qualification_token=token.value)[0])
        self.assertEqual(order, [('policy', False), ('callback', False)])
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)
        self.assertEqual(link.queued, 0)

    def test_neutral_pending_exhausted_and_non_neutral_each_preserve_fault(self):
        for mode in ('pending', 'exhausted', 'nonneutral'):
            with self.subTest(mode=mode):
                link, safety, token, _ = self.make()
                with link._cv:
                    if mode == 'pending':
                        link._release_pending = True
                    elif mode == 'exhausted':
                        link._release_exhausted = True
                    else:
                        link._link.wire_neutral = False
                self.assertFalse(link.send(qualification_token=token.value)[0])
                self.assertEqual(link._fault, 'prior fault')
                self.assertIsNone(link._latest)
                self.assertEqual(link.queued, 0)

    def test_state_must_still_be_armed_even_if_policy_says_true(self):
        link, safety, token, _ = self.make()
        def policy(**kwargs):
            safety.control_state = ControlState.LOCKED
            return True, 'inert obsolete allow'
        safety.can_transmit_dt7 = policy
        self.assertFalse(link.send(qualification_token=token.value)[0])
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)

    def test_expiry_after_admission_is_rejected_by_unchanged_wire_guard(self):
        link, safety, token, writes = self.make()
        self.assertTrue(link.send(pressed_bits=1 << 12, qualification_token=token.value)[0])
        safety._qualification = replace(token, expires_at=time.perf_counter() - 1)
        link.unpark_worker.set()
        with link._cv:
            self.assertTrue(link._cv.wait_for(lambda: bool(link._fault), 2))
        self.assertEqual(link.stale_dropped, 1)
        self.assertEqual(writes, [])
        link.poll()
        self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_match_rearm_recovers_and_current_intent_reaches_inert_writer(self):
        link, safety, token, writes = self.make()
        safety.update_stage(4)
        safety.arm_match(['core_kmc', 'dt7_control'])
        self.assertTrue(link.send(pressed_bits=2)[0])
        self.assertEqual(safety.control_state, ControlState.MATCH_ARMED)
        self.assertEqual(link._fault, '')
        written = self.event()
        original_write = link._link.write_bytes
        def write(frame):
            result = original_write(frame)
            written.set()
            return result
        link._link.write_bytes = write
        link.unpark_worker.set()
        self.assertTrue(written.wait(2))
        self.assertEqual(int.from_bytes(decode_dt7_frame(writes[0])['payload'][8:10], 'little'), 2)

    def test_missing_policy_preserves_fault_and_no_admission(self):
        link, safety, token, writes = self.make()
        link.safety = None
        self.assertFalse(link.send(pressed_bits=2)[0])
        self.assertEqual(link._fault, 'prior fault')
        self.assertEqual(link.queued, 0)
        self.assertEqual(writes, [])

    def test_locked_current_policy_preserves_fault(self):
        link, safety, token, writes = self.make()
        safety.lock_control('operator lock')
        self.assertFalse(link.send(pressed_bits=2)[0])
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)

    def test_wrong_qualification_token_still_locks_and_notifies_once(self):
        link, safety, token, writes = self.make()
        callbacks = []
        safety.input_clear_hook = callbacks.append
        self.assertFalse(link.send(pressed_bits=2, qualification_token='wrong')[0])
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(callbacks, ['qualification token invalid or expired'])
        self.assertEqual(link._fault, 'prior fault')
        self.assertEqual(link.queued, 0)

    def test_true_policy_callback_finishes_before_clear_and_enqueue(self):
        link, safety, token, writes = self.make()
        original, observed = safety.can_transmit_dt7, []
        def policy(**kwargs):
            result = original(**kwargs)
            observed.append((link._fault, link._latest, link.queued))
            return result
        safety.can_transmit_dt7 = policy
        self.assertTrue(link.send(pressed_bits=2, qualification_token=token.value)[0])
        self.assertEqual(observed, [('prior fault', None, 0)])
        self.assertEqual(link._fault, '')
        self.assertEqual(link.queued, 1)

    def test_plain_policy_exception_leaves_original_state_and_error_identity(self):
        link, safety, token, writes = self.make()
        error = RuntimeError('inert policy exception')
        generation, fault_epoch = link._generation, link._fault_epoch
        with patch.object(safety, 'can_transmit_dt7', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                link.send(qualification_token=token.value)
        self.assertIs(caught.exception, error)
        self.assertEqual((link._generation, link._fault_epoch), (generation, fault_epoch))
        self.assertEqual(link._fault, 'prior fault')
        self.assertIsNone(link._latest)
        self.assertEqual(link.queued, 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
