"""Window cleanup must continue when its diagnostic sink fails; inert owners."""
from pathlib import Path
import io
import logging
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.ui.polar import window_lifecycle as lifecycle


class WindowOwnerDiagnosticFailureTests(unittest.TestCase):
    def actions(self, names=('first', 'second', 'third'), failed=('first',)):
        trace = []
        errors = {name: RuntimeError(name + ' failed') for name in failed}
        def action(name):
            def run():
                trace.append(name)
                if name in errors:
                    raise errors[name]
            return lifecycle.OwnerAction(name, run)
        return tuple(action(name) for name in names), trace, errors

    def call(self, action):
        try:
            return action(), None
        except Exception as error:
            return None, error

    def controller(self, trace):
        backend = SimpleNamespace(request_shutdown=lambda **kwargs: trace.append('shutdown'))
        return lifecycle.WindowLifecycleController(backend)

    def context(self, trace, releases=None):
        return lifecycle.FinalContextPorts(available=lambda: True,
            enter=lambda: trace.append('enter'),
            releases=lambda: releases if releases is not None else (
                lifecycle.OwnerAction('gpu', lambda: trace.append('gpu')),),
            leave=lambda: lifecycle.OwnerAction('leave', lambda: trace.append('leave')))

    def test_success_does_not_report_or_create_failure_records(self):
        actions, trace, _ = self.actions(failed=())
        with patch.object(lifecycle._LOG, 'error') as log:
            self.assertEqual(lifecycle.run_owner_actions(actions), ())
        log.assert_not_called()
        self.assertEqual(trace, ['first', 'second', 'third'])

    def test_healthy_logging_preserves_failure_fields_order_and_active_exception(self):
        actions, trace, errors = self.actions(failed=('first', 'second', 'third'))
        contexts = []
        def log(*args, **kwargs):
            contexts.append((args, kwargs, sys.exc_info()[1]))
        with patch.object(lifecycle._LOG, 'error', side_effect=log):
            failures = lifecycle.run_owner_actions(actions)
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual(failures, tuple(lifecycle.OwnerActionFailure(name, 'RuntimeError', name + ' failed') for name in trace))
        self.assertEqual([ctx[2] for ctx in contexts], [errors[name] for name in trace])
        for name, (args, kwargs, _) in zip(trace, contexts):
            self.assertEqual(args, ('Window owner action %s failed', name))
            self.assertEqual(kwargs, {'exc_info': True})

    def test_logger_failure_at_each_action_records_primary_then_diagnostic_and_continues(self):
        for name in ('first', 'second', 'third'):
            with self.subTest(action=name):
                actions, trace, _ = self.actions(failed=(name,))
                with patch.object(lifecycle._LOG, 'error', side_effect=OSError('sink failed')) as log:
                    failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
                self.assertIsNone(error)
                self.assertEqual(trace, ['first', 'second', 'third'])
                self.assertEqual(failures, (
                    lifecycle.OwnerActionFailure(name, 'RuntimeError', name + ' failed'),
                    lifecycle.OwnerActionFailure(name + ' diagnostic', 'OSError', 'sink failed')))
                log.assert_called_once()

    def test_logger_attribute_lookup_failure_is_recorded_without_skipping_actions(self):
        class Logger:
            @property
            def error(self):
                raise OSError('logger lookup failed')
        actions, trace, _ = self.actions()
        with patch.object(lifecycle, '_LOG', Logger()):
            failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual([f.name for f in failures], ['first', 'first diagnostic'])
        self.assertEqual(failures[1].message, 'logger lookup failed')

    def test_multiple_failed_diagnostics_remain_distinct_without_recursive_logging(self):
        actions, trace, _ = self.actions(failed=('first', 'second', 'third'))
        with patch.object(lifecycle._LOG, 'error', side_effect=OSError('sink failed')) as log:
            failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual([f.name for f in failures], ['first', 'first diagnostic', 'second', 'second diagnostic', 'third', 'third diagnostic'])
        self.assertEqual(log.call_count, 3)

    def test_single_failed_diagnostic_does_not_hide_later_healthy_reports(self):
        actions, trace, _ = self.actions(failed=('first', 'second', 'third'))
        with patch.object(lifecycle._LOG, 'error', side_effect=[OSError('sink failed'), None, None]) as log:
            failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
        self.assertIsNone(error)
        self.assertEqual([f.name for f in failures], ['first', 'first diagnostic', 'second', 'third'])
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual(log.call_count, 3)

    def test_standard_closed_stderr_keeps_original_record_and_later_actions(self):
        actions, trace, _ = self.actions()
        stream = io.StringIO(); stream.close()
        logger = logging.Logger('closed in-memory stderr')
        logger.addHandler(logging.StreamHandler(stream))
        with (patch.object(lifecycle, '_LOG', logger), patch.object(sys, 'stderr', stream),
              patch.object(logging, 'raiseExceptions', True)):
            failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual(failures[0], lifecycle.OwnerActionFailure('first', 'RuntimeError', 'first failed'))
        self.assertEqual(failures[1], lifecycle.OwnerActionFailure('first diagnostic', 'ValueError', 'I/O operation on closed file'))

    def test_unprintable_primary_keeps_original_type_and_continues(self):
        class Failure(RuntimeError):
            def __str__(self):
                raise ValueError('cannot render primary')
        actions, trace, errors = self.actions()
        errors['first'] = Failure()
        with patch.object(lifecycle._LOG, 'error'):
            failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual(failures, (lifecycle.OwnerActionFailure('first', 'Failure', '<unprintable exception>'),))

    def test_unprintable_diagnostic_keeps_primary_and_diagnostic_types(self):
        class Diagnostic(RuntimeError):
            def __str__(self):
                raise ValueError('cannot render diagnostic')
        actions, trace, _ = self.actions()
        with patch.object(lifecycle._LOG, 'error', side_effect=Diagnostic()):
            failures, error = self.call(lambda: lifecycle.run_owner_actions(actions))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third'])
        self.assertEqual(failures[0].message, 'first failed')
        self.assertEqual(failures[1], lifecycle.OwnerActionFailure('first diagnostic', 'Diagnostic', '<unprintable exception>'))

    def test_process_control_operation_retains_immediate_identity_and_prefix(self):
        for name in ('first', 'second', 'third'):
            with self.subTest(action=name):
                actions, trace, errors = self.actions(failed=(name,))
                failure = errors[name] = KeyboardInterrupt(name)
                with patch.object(lifecycle._LOG, 'error') as log:
                    with self.assertRaises(BaseException) as caught:
                        lifecycle.run_owner_actions(actions)
                self.assertIs(caught.exception, failure)
                self.assertEqual(trace, ['first', 'second', 'third'][:['first', 'second', 'third'].index(name)+1])
                log.assert_not_called()

    def test_process_control_logger_is_not_swallowed(self):
        actions, trace, _ = self.actions()
        failure = SystemExit('stop logging')
        with patch.object(lifecycle._LOG, 'error', side_effect=failure):
            with self.assertRaises(BaseException) as caught:
                lifecycle.run_owner_actions(actions)
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['first'])

    def test_process_control_formatter_is_not_swallowed(self):
        failure = KeyboardInterrupt('stop formatting')
        class Failure(RuntimeError):
            def __str__(self):
                raise failure
        actions, trace, errors = self.actions()
        errors['first'] = Failure()
        with patch.object(lifecycle._LOG, 'error'):
            with self.assertRaises(BaseException) as caught:
                lifecycle.run_owner_actions(actions)
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['first'])

    def test_close_seal_retains_records_and_admits_shutdown_once_after_diagnostic_failure(self):
        actions, trace, _ = self.actions()
        owner = self.controller(trace)
        with patch.object(lifecycle._LOG, 'error', side_effect=OSError('sink failed')):
            _, error = self.call(lambda: owner.request_close(prepare=actions, tasks=()))
            owner.request_close(prepare=actions, tasks=())
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third', 'shutdown'])
        self.assertTrue(owner.closing)
        self.assertEqual([f.name for f in owner.owner_failures], ['first', 'first diagnostic'])
        self.assertFalse(owner.ready_to_close)

    def test_reentrant_logging_does_not_replay_close_or_drop_original_record(self):
        actions, trace, _ = self.actions()
        owner = self.controller(trace)
        def log(*args, **kwargs):
            owner.request_close(prepare=actions, tasks=())
            raise OSError('reentrant sink failed')
        with patch.object(lifecycle._LOG, 'error', side_effect=log):
            _, error = self.call(lambda: owner.request_close(prepare=actions, tasks=()))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third', 'shutdown'])
        self.assertEqual(owner.owner_failures[0].message, 'first failed')

    def test_finalization_seal_records_diagnostics_and_finishes_all_resources_once(self):
        actions, trace, _ = self.actions()
        owner = self.controller(trace)
        context = self.context(trace)
        with patch.object(lifecycle._LOG, 'error', side_effect=OSError('sink failed')):
            failures, error = self.call(lambda: owner.finalize(prepare=lambda: actions, context=context))
            again = owner.finalize(prepare=lambda: actions, context=context)
        self.assertIsNone(error)
        self.assertIsNone(again)
        self.assertEqual(trace, ['first', 'second', 'third', 'enter', 'gpu', 'leave'])
        self.assertTrue(owner.finalized)
        self.assertEqual(failures, owner.finalization_failures)
        self.assertEqual([f.name for f in failures], ['first', 'first diagnostic'])

    def test_gpu_action_error_and_logger_failure_cannot_skip_later_gpu_or_leave(self):
        gpu, trace, _ = self.actions(names=('gpu1', 'gpu2'), failed=('gpu1',))
        owner = self.controller(trace)
        with patch.object(lifecycle._LOG, 'error', side_effect=OSError('sink failed')):
            failures, error = self.call(lambda: owner.finalize(prepare=lambda: (), context=self.context(trace, gpu)))
        self.assertIsNone(error)
        self.assertEqual(trace, ['enter', 'gpu1', 'gpu2', 'leave'])
        self.assertEqual([f.name for f in failures], ['gpu1', 'gpu1 diagnostic'])
        self.assertEqual(owner.finalization_failures, failures)

    def test_leave_failure_and_logger_failure_are_retained_after_all_resources(self):
        actions, trace, _ = self.actions(failed=())
        owner = self.controller(trace)
        def leave():
            trace.append('leave')
            raise OSError('leave failed')
        context = lifecycle.FinalContextPorts(available=lambda: True,
            enter=lambda: trace.append('enter'), releases=lambda: actions,
            leave=lambda: lifecycle.OwnerAction('GL done', leave))
        with patch.object(lifecycle._LOG, 'error', side_effect=ValueError('sink failed')):
            failures, error = self.call(lambda: owner.finalize(prepare=lambda: (), context=context))
        self.assertIsNone(error)
        self.assertEqual(trace, ['enter', 'first', 'second', 'third', 'leave'])
        self.assertEqual(failures, (
            lifecycle.OwnerActionFailure('GL done', 'OSError', 'leave failed'),
            lifecycle.OwnerActionFailure('GL done diagnostic', 'ValueError', 'sink failed')))
        self.assertEqual(owner.finalization_failures, failures)

    def test_reentrant_logging_does_not_replay_finalization(self):
        actions, trace, _ = self.actions()
        owner = self.controller(trace)
        context = self.context(trace)
        def log(*args, **kwargs):
            self.assertIsNone(owner.finalize(prepare=lambda: actions, context=context))
            raise OSError('reentrant sink failed')
        with patch.object(lifecycle._LOG, 'error', side_effect=log):
            failures, error = self.call(lambda: owner.finalize(prepare=lambda: actions, context=context))
        self.assertIsNone(error)
        self.assertEqual(trace, ['first', 'second', 'third', 'enter', 'gpu', 'leave'])
        self.assertEqual([f.name for f in failures], ['first', 'first diagnostic'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
