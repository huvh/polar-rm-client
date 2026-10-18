"""Diagnostic failures must not cancel independent neutral attempts (inert IO)."""
from pathlib import Path
import io
import logging
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.configuration.quiescence import quiesce_configuration_inputs
from rm_client.control import KeyboardControlBridge
from rm_client.emergency_actions import request_focus_loss
from rm_client.ui.polar.mixins.config_actions_mixin import ConfigActionsMixin


class ControlReleaseLoggingFailureTests(unittest.TestCase):
    def bridge(self, failures=()):
        bridge = KeyboardControlBridge()
        trace = []
        command = object()
        errors = {name: RuntimeError(name + ' failed') for name in failures}
        # Keep note assertions valid on the supported Python 3.10 runtime too.
        for error in errors.values():
            def add_note(note, error=error):
                error.__notes__ = [*getattr(error, '__notes__', ()), note]
            error.add_note = add_note
        def action(name, result=None):
            def run(*args):
                trace.append(name)
                if name in errors:
                    raise errors[name]
                return result
            return Mock(side_effect=run)
        bridge.reset_inputs = action('reset')
        bridge.send_from_state = action('publish', command)
        bridge.release_direct_dt7 = action('dt7')
        bridge.release_custom_controller = action('custom')
        return bridge, trace, command, errors

    def run_failure(self, bridge):
        try:
            bridge.release_all(object(), object())
        except Exception as error:
            return error
        self.fail('the operation failure must propagate')

    def expected_trace(self, first):
        return ['reset', 'dt7', 'custom'] if first == 'reset' else ['reset', 'publish', 'dt7', 'custom']

    def test_success_does_not_lookup_logger(self):
        bridge, trace, command, _ = self.bridge()
        with patch('rm_client.control.logging.getLogger') as lookup:
            self.assertIs(bridge.release_all(object(), object()), command)
        lookup.assert_not_called()
        self.assertEqual(trace, self.expected_trace('publish'))

    def test_healthy_logging_preserves_all_failure_messages_and_first_error(self):
        bridge, trace, _, errors = self.bridge(('publish', 'dt7', 'custom'))
        with patch('rm_client.control.logging.getLogger') as lookup:
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))
        self.assertEqual([call.args[0] for call in lookup.return_value.exception.call_args_list], [
            'Input reset/neutral publication failed',
            'Independent input neutral release failed',
            'Independent input neutral release failed'])
        self.assertFalse(hasattr(actual, '__notes__'))

    def test_logger_lookup_failure_keeps_each_operation_primary_and_routes(self):
        for step in ('reset', 'publish', 'dt7', 'custom'):
            with self.subTest(step=step):
                bridge, trace, _, errors = self.bridge((step,))
                with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
                    actual = self.run_failure(bridge)
                self.assertIs(actual, errors[step])
                self.assertEqual(trace, self.expected_trace(step))
                self.assertIn('OSError: lookup failed', ' '.join(getattr(actual, '__notes__', ())))

    def test_logger_emit_failure_keeps_each_operation_primary_and_routes(self):
        for step in ('reset', 'publish', 'dt7', 'custom'):
            with self.subTest(step=step):
                bridge, trace, _, errors = self.bridge((step,))
                with patch('rm_client.control.logging.getLogger') as lookup:
                    lookup.return_value.exception.side_effect = OSError('emit failed')
                    actual = self.run_failure(bridge)
                self.assertIs(actual, errors[step])
                self.assertEqual(trace, self.expected_trace(step))
                self.assertIn('OSError: emit failed', ' '.join(getattr(actual, '__notes__', ())))
                lookup.return_value.exception.assert_called_once()

    def test_standard_logging_closed_stderr_preserves_primary_and_routes(self):
        bridge, trace, _, errors = self.bridge(('publish',))
        stream = io.StringIO()
        stream.close()
        logger = logging.Logger('closed in-memory stderr')
        logger.addHandler(logging.StreamHandler(stream))
        with (patch('rm_client.control.logging.getLogger', return_value=logger),
              patch.object(sys, 'stderr', stream), patch.object(logging, 'raiseExceptions', True)):
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))
        self.assertIn('ValueError: I/O operation on closed file', ' '.join(getattr(actual, '__notes__', ())))

    def test_each_diagnostic_failure_is_noted_on_its_operation_without_recursive_logging(self):
        bridge, trace, _, errors = self.bridge(('publish', 'dt7', 'custom'))
        errors['publish'].add_note('existing note')
        with patch('rm_client.control.logging.getLogger') as lookup:
            lookup.return_value.exception.side_effect = OSError('sink failed')
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))
        self.assertEqual(lookup.return_value.exception.call_count, 3)
        self.assertEqual(errors['publish'].__notes__[0], 'existing note')
        for error in errors.values():
            self.assertIn('OSError: sink failed', ' '.join(getattr(error, '__notes__', ())))

    def test_one_failed_diagnostic_does_not_prevent_later_healthy_reports(self):
        bridge, trace, _, errors = self.bridge(('publish', 'dt7', 'custom'))
        with patch('rm_client.control.logging.getLogger') as lookup:
            lookup.return_value.exception.side_effect = [OSError('first log failed'), None, None]
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))
        self.assertEqual(lookup.return_value.exception.call_count, 3)
        self.assertFalse(hasattr(errors['dt7'], '__notes__'))
        self.assertFalse(hasattr(errors['custom'], '__notes__'))

    def test_broken_add_note_cannot_replace_operation_or_cancel_releases(self):
        class Failure(RuntimeError):
            def add_note(self, note):
                raise ValueError('notes unavailable')
        bridge, trace, _, errors = self.bridge(('publish',))
        errors['publish'] = Failure('publish failed')
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))

    def test_missing_add_note_capability_keeps_primary_and_all_releases(self):
        bridge, trace, _, errors = self.bridge(('publish',))
        errors['publish'].add_note = None
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))

    def test_raising_add_note_lookup_keeps_primary_and_all_releases(self):
        class Failure(RuntimeError):
            @property
            def add_note(self):
                raise OSError('notes lookup failed')
        bridge, trace, _, errors = self.bridge(('publish',))
        errors['publish'] = Failure('publish failed')
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))

    def test_broken_diagnostic_formatting_cannot_replace_operation_or_cancel_releases(self):
        class DiagnosticFailure(RuntimeError):
            def __str__(self):
                raise ValueError('format unavailable')
        bridge, trace, _, errors = self.bridge(('publish',))
        with patch('rm_client.control.logging.getLogger', side_effect=DiagnosticFailure()):
            actual = self.run_failure(bridge)
        self.assertIs(actual, errors['publish'])
        self.assertEqual(trace, self.expected_trace('publish'))

    def test_operation_baseexception_keeps_existing_immediate_propagation(self):
        for step in ('reset', 'publish', 'dt7', 'custom'):
            with self.subTest(step=step):
                bridge, trace, _, errors = self.bridge((step,))
                failure = errors[step] = KeyboardInterrupt('stop now')
                with patch('rm_client.control.logging.getLogger') as lookup:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        bridge.release_all(object(), object())
                self.assertIs(caught.exception, failure)
                order = ['reset', 'publish', 'dt7', 'custom']
                self.assertEqual(trace, order[:order.index(step) + 1])
                lookup.assert_not_called()

    def test_logger_baseexception_is_not_swallowed(self):
        for where in ('lookup', 'emit'):
            with self.subTest(where=where):
                bridge, trace, _, _ = self.bridge(('publish',))
                failure = SystemExit('stop diagnostics')
                with patch('rm_client.control.logging.getLogger') as lookup:
                    if where == 'lookup':
                        lookup.side_effect = failure
                    else:
                        lookup.return_value.exception.side_effect = failure
                    with self.assertRaises(SystemExit) as caught:
                        bridge.release_all(object(), object())
                self.assertIs(caught.exception, failure)
                self.assertEqual(trace, ['reset', 'publish'])

    def test_note_baseexception_is_not_swallowed(self):
        failure = KeyboardInterrupt('stop notes')
        class Failure(RuntimeError):
            def add_note(self, note):
                raise failure
        bridge, trace, _, errors = self.bridge(('publish',))
        errors['publish'] = Failure('publish failed')
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            with self.assertRaises(BaseException) as caught:
                bridge.release_all(object(), object())
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['reset', 'publish'])

    def test_custom_controller_error_and_pending_survive_ordinary_pending_clear(self):
        bridge = KeyboardControlBridge()
        bridge.cc_link = SimpleNamespace(release_all=Mock(side_effect=OSError('neutral failed')))
        bridge.release_custom_controller()
        bridge.clear_pending()
        self.assertTrue(bridge.cc_release_pending)
        self.assertEqual(bridge.cc_last_error, 'neutral failed')
        bridge.cc_link.release_all.side_effect = None
        bridge.cc_link.release_all.return_value = (True, '')
        bridge.release_custom_controller()
        self.assertFalse(bridge.cc_release_pending)
        self.assertEqual(bridge.cc_last_error, '')

    def test_disabled_output_gate_keeps_lock_order_primary_and_pending_clear(self):
        bridge, trace, _, errors = self.bridge(('publish',))
        bridge._dirty = True
        clear = bridge.clear_pending
        def clear_pending():
            trace.append('clear')
            clear()
        bridge.clear_pending = clear_pending
        host = SimpleNamespace(control=bridge, state=object(), registry=object(),
            backend=SimpleNamespace(lock_control=lambda reason: trace.append('lock')))
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            with self.assertRaises(Exception) as caught:
                ConfigActionsMixin._close_disabled_output_gate(host, object())
        self.assertIs(caught.exception, errors['publish'])
        self.assertEqual(trace, ['lock', 'reset', 'publish', 'dt7', 'custom', 'clear'])
        self.assertFalse(bridge._dirty)

    def test_focus_loss_fallback_retains_original_failure_and_both_neutral_attempts(self):
        bridge, trace, _, errors = self.bridge(('publish',))
        bridge.clear_pending = lambda: trace.append('clear')
        backend = SimpleNamespace(lock_control=lambda reason: trace.append('lock'))
        def zero():
            trace.append('zero')
            return True, ''
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            result = request_focus_loss(backend, bridge,
                lambda: bridge.release_all(object(), object()), zero)
        self.assertEqual(trace, ['lock', 'reset', 'publish', 'dt7', 'custom', 'reset', 'dt7', 'custom', 'zero', 'clear'])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual((result.failures[0].operation, result.failures[0].error_type, result.failures[0].message),
                         ('input release', 'RuntimeError', str(errors['publish'])))

    def test_configuration_quiescence_preserves_primary_and_clear_after_both_routes(self):
        bridge, trace, _, errors = self.bridge(('publish',))
        with patch('rm_client.control.logging.getLogger', side_effect=OSError('lookup failed')):
            with self.assertRaises(Exception) as caught:
                quiesce_configuration_inputs(revoke=lambda: trace.append('lock'),
                    release=lambda: bridge.release_all(object(), object()),
                    clear_pending=lambda: trace.append('clear'))
        self.assertIs(caught.exception, errors['publish'])
        self.assertEqual(trace, ['lock', 'reset', 'publish', 'dt7', 'custom', 'clear'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
