"""Locked input cleanup preserves primary failures across broken diagnostics."""
from pathlib import Path
import io
import logging
from queue import Queue
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager
from rm_client.backend.safety import OfficialSafety, ControlState
from rm_client.ui.polar.mixins.input_dispatch_mixin import InputDispatchMixin

MODULE = 'rm_client.ui.polar.mixins.input_dispatch_mixin'
STEPS = ['reset', 'cache', 'pointer', 'dt7', 'custom', 'clear']


class LockInputDiagnosticFailureTests(unittest.TestCase):
    def host(self, failed=()):
        host, trace = InputDispatchMixin(), []
        failures = {name: RuntimeError(name + ' failed') for name in failed}
        for error in failures.values():
            def note(value, error=error):
                error.__notes__ = [*getattr(error, '__notes__', ()), value]
            error.add_note = note  # Optional capability controlled on Python 3.10 too.
        def action(name, result=None):
            def call(*args, **kwargs):
                trace.append(name)
                if name in failures:
                    raise failures[name]
                return result
            return call
        class Control(NS):
            def __setattr__(self, name, value):
                if name == 'last_command':
                    action('cache')()
                super().__setattr__(name, value)
        host.control = Control(reset_inputs=action('reset'), last_command='old command',
            release_direct_dt7=action('dt7'), release_custom_controller=action('custom'),
            clear_pending=action('clear'))
        host.pointer_interaction.cancel_epoch = action('pointer')
        host._modal_input_clear_pending = False
        host._economy_qualification_token = 'old token'
        host._control_mouse_point = 'old mouse'
        host._combat_input_was_allowed = True
        return host, trace, failures, action

    def observed(self, call):
        try:
            return call(), None
        except Exception as error:
            return None, error

    def manager(self, host, action):
        manager = object.__new__(BackendManager)
        manager.safety = OfficialSafety()
        manager.safety.arm_match({'core_kmc'})
        manager._input_owner_thread = threading.get_ident()
        manager._input_clear_requests = Queue(maxsize=32)
        manager._input_clear_generation, manager._input_clear_error = 0, ''
        manager._dt7_control_ref = host.control
        manager.controller_angles = NS(disarm=action('disarm'))
        manager._dt7_link = NS(wire_neutral=False, asynchronous=True,
                              request_release=action('backend dt7', (True, '')))
        manager._cc_link = NS(wire_neutral=False, asynchronous=True,
                             release_all=action('backend custom', (True, '')))
        manager.field_log = NS(emit=lambda *args, **kwargs: None)
        manager.input_clear_hook = host._clear_control_inputs_for_lock
        manager.safety.input_clear_hook = manager._request_input_clear
        return manager

    def test_success_preserves_order_and_clears_existing_latch_without_logging(self):
        host, trace, _, _ = self.host()
        host._modal_input_clear_pending = True
        with patch(MODULE + '.logging.getLogger') as lookup:
            self.assertIsNone(host._clear_control_inputs_for_lock())
        lookup.assert_not_called()
        self.assertEqual(trace, STEPS)
        self.assertFalse(host._modal_input_clear_pending)
        self.assertFalse(host._lock_input_clearing)
        self.assertIsNone(host.control.last_command)
        self.assertIsNone(host._economy_qualification_token)
        self.assertIsNone(host._control_mouse_point)
        self.assertFalse(host._combat_input_was_allowed)

    def test_logger_emission_failure_at_every_action_keeps_primary_and_remaining_attempts(self):
        for step in STEPS:
            with self.subTest(step=step):
                host, trace, failures, _ = self.host((step,))
                with patch(MODULE + '.logging.getLogger') as logger:
                    logger.return_value.exception.side_effect = OSError('sink failed')
                    _, error = self.observed(host._clear_control_inputs_for_lock)
                self.assertIs(error, failures[step])
                self.assertEqual(trace, STEPS)
                self.assertTrue(host._modal_input_clear_pending)
                self.assertFalse(host._lock_input_clearing)
                self.assertIn('OSError: sink failed', ' '.join(getattr(error, '__notes__', ())))
                self.assertFalse(host.combat_control_input_allowed())
                self.assertIsNone(host._economy_qualification_token)
                self.assertIsNone(host._control_mouse_point)
                self.assertFalse(host._combat_input_was_allowed)

    def test_logger_lookup_failure_keeps_original_error(self):
        host, trace, failures, _ = self.host(('reset',))
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['reset'])
        self.assertEqual(trace, STEPS)
        self.assertIn('lookup failed', error.__notes__[0])

    def test_standard_closed_stderr_keeps_primary_and_later_calls(self):
        host, trace, failures, _ = self.host(('pointer',))
        stream = io.StringIO(); stream.close()
        logger = logging.Logger('closed in-memory stderr')
        logger.addHandler(logging.StreamHandler(stream))
        with (patch(MODULE + '.logging.getLogger', return_value=logger),
              patch.object(sys, 'stderr', stream), patch.object(logging, 'raiseExceptions', True)):
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['pointer'])
        self.assertEqual(trace, STEPS)
        self.assertTrue(host._modal_input_clear_pending)

    def test_healthy_logging_receives_each_exact_active_exception_and_first_wins(self):
        host, trace, failures, _ = self.host(('reset', 'dt7', 'clear'))
        seen = []
        def report(*args, **kwargs):
            seen.append((args, kwargs, sys.exc_info()[1]))
        with patch(MODULE + '.logging.getLogger') as lookup:
            lookup.return_value.exception.side_effect = report
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['reset'])
        self.assertEqual([item[2] for item in seen], [failures[n] for n in ('reset', 'dt7', 'clear')])
        self.assertTrue(all(args == ('Locked input cleanup failed',) and kwargs == {} for args, kwargs, _ in seen))
        self.assertEqual(trace, STEPS)

    def test_multiple_operation_and_diagnostic_failures_keep_first_identity(self):
        host, trace, failures, _ = self.host(tuple(STEPS))
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['reset'])
        self.assertEqual(trace, STEPS)
        self.assertTrue(all('lookup failed' in failure.__notes__[0] for failure in failures.values()))
        self.assertTrue(host._modal_input_clear_pending)

    def test_reentrant_diagnostic_cannot_repeat_actions_or_surrender_latch(self):
        host, trace, failures, _ = self.host(('reset',))
        seen = []
        def report(*args, **kwargs):
            host._clear_control_inputs_for_lock('nested')
            seen.append(host._modal_input_clear_pending)
            raise OSError('sink failed')
        with patch(MODULE + '.logging.getLogger') as lookup:
            lookup.return_value.exception.side_effect = report
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['reset'])
        self.assertEqual(trace, STEPS)
        self.assertEqual(seen, [True])
        self.assertTrue(host._modal_input_clear_pending)

    def test_later_successful_explicit_cleanup_clears_failed_epoch(self):
        host, trace, failures, _ = self.host(('dt7',))
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['dt7'])
        self.assertTrue(host._modal_input_clear_pending)
        failures.clear()
        self.assertIsNone(host._clear_control_inputs_for_lock('operator recovery'))
        self.assertEqual(trace, STEPS * 2)
        self.assertFalse(host._modal_input_clear_pending)

    def test_note_capability_absence_lookup_or_call_failure_keeps_primary(self):
        class NoNotes(RuntimeError):
            add_note = None
        class BrokenLookup(RuntimeError):
            @property
            def add_note(self):
                raise ValueError('lookup failed')
        class BrokenNotes(RuntimeError):
            def add_note(self, value):
                raise ValueError('notes failed')
        for error_type in (NoNotes, BrokenLookup, BrokenNotes):
            with self.subTest(error_type=error_type):
                host, trace, failures, _ = self.host(('reset',))
                primary = failures['reset'] = error_type('reset failed')
                with patch(MODULE + '.logging.getLogger', side_effect=OSError('sink failed')):
                    _, error = self.observed(host._clear_control_inputs_for_lock)
                self.assertIs(error, primary)
                self.assertEqual(trace, STEPS)
                self.assertTrue(host._modal_input_clear_pending)

    def test_unprintable_diagnostic_cannot_replace_primary(self):
        class Failure(RuntimeError):
            def __str__(self):
                raise ValueError('render failed')
        host, trace, failures, _ = self.host(('reset',))
        with patch(MODULE + '.logging.getLogger', side_effect=Failure()):
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, failures['reset'])
        self.assertEqual(trace, STEPS)

    def test_unprintable_primary_keeps_identity_with_raising_logger(self):
        class Failure(RuntimeError):
            def __str__(self):
                raise ValueError('render failed')
        host, trace, failures, _ = self.host(('reset',))
        primary = failures['reset'] = Failure()
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('sink failed')):
            _, error = self.observed(host._clear_control_inputs_for_lock)
        self.assertIs(error, primary)
        self.assertEqual(trace, STEPS)

    def test_operation_baseexception_at_every_step_keeps_identity_and_prefix(self):
        for step in STEPS:
            with self.subTest(step=step):
                host, trace, failures, _ = self.host((step,))
                stop = failures[step] = KeyboardInterrupt('stop action')
                with patch(MODULE + '.logging.getLogger') as lookup:
                    with self.assertRaises(BaseException) as caught:
                        host._clear_control_inputs_for_lock()
                self.assertIs(caught.exception, stop)
                self.assertEqual(trace, STEPS[:STEPS.index(step) + 1])
                self.assertTrue(host._modal_input_clear_pending)
                self.assertFalse(host._lock_input_clearing)
                lookup.assert_not_called()

    def test_logger_baseexception_keeps_identity_and_immediate_prefix(self):
        host, trace, _, _ = self.host(('reset',))
        stop = SystemExit('stop logging')
        with patch(MODULE + '.logging.getLogger', side_effect=stop):
            with self.assertRaises(BaseException) as caught:
                host._clear_control_inputs_for_lock()
        self.assertIs(caught.exception, stop)
        self.assertEqual(trace, ['reset'])
        self.assertTrue(host._modal_input_clear_pending)
        self.assertFalse(host._lock_input_clearing)

    def test_note_baseexception_is_not_swallowed(self):
        host, trace, failures, _ = self.host(('reset',))
        stop = KeyboardInterrupt('stop note')
        def note(value):
            raise stop
        failures['reset'].add_note = note
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('sink failed')):
            try:
                host._clear_control_inputs_for_lock()
            except BaseException as caught:
                observed = caught
            else:
                observed = None
        self.assertIs(observed, stop)
        self.assertEqual(trace, ['reset'])
        self.assertTrue(host._modal_input_clear_pending)
        self.assertFalse(host._lock_input_clearing)

    def test_actual_manager_keeps_upstream_revocation_requeue_and_primary_diagnostic(self):
        host, trace, _, action = self.host(('pointer',))
        manager = self.manager(host, action)
        observed = []
        hook = manager.input_clear_hook
        def report(reason):
            observed.append(manager.safety.control_state)
            hook(reason)
        manager.input_clear_hook = report
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('sink failed')):
            self.assertIsNone(manager.lock_control('operator lock'))
        self.assertEqual(observed, [ControlState.LOCKED])
        self.assertEqual(trace, ['disarm', 'backend dt7', 'backend custom', 'reset', 'cache', 'clear'] + STEPS)
        self.assertEqual(manager._input_clear_error, 'RuntimeError: pointer failed')
        self.assertEqual(manager.safety.input_clear_failures[0].exception_type, 'builtins.RuntimeError')
        self.assertTrue(manager._input_clear_incomplete())
        self.assertEqual(manager._input_clear_requests.qsize(), 1)
        self.assertTrue(host._modal_input_clear_pending)
        self.assertEqual(manager.safety.control_state, ControlState.LOCKED)

    def test_actual_manager_later_drain_completes_without_rearming_or_erasing_history(self):
        host, trace, failures, action = self.host(('pointer',))
        manager = self.manager(host, action)
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('sink failed')):
            manager.lock_control('operator lock')
        failures.clear()
        manager._drain_input_clear()
        self.assertFalse(manager._input_clear_incomplete())
        self.assertFalse(host._modal_input_clear_pending)
        self.assertEqual(manager.safety.control_state, ControlState.LOCKED)
        self.assertEqual(manager.safety.input_clear_failure_count, 1)
        self.assertEqual(manager.safety.input_clear_failures[0].exception_type, 'builtins.RuntimeError')


if __name__ == '__main__':
    unittest.main(verbosity=2)
