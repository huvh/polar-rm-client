"""Lifecycle fault bookkeeping and revocation are independent of diagnostic IO."""
from pathlib import Path
import io
import logging
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager
from rm_client.backend.safety import OfficialSafety, ControlState
from rm_client.lifecycle import LifecycleSnapshot, LifecyclePhase
from rm_client.ui.polar import window_lifecycle as life


class WindowLifecycleDiagnosticFailureTests(unittest.TestCase):
    def poll_fixture(self):
        trace = []
        safety = OfficialSafety()
        safety.arm_match({'core_kmc'})
        primary = TypeError('poll failed')
        manager = object.__new__(BackendManager)
        manager.safety = safety
        manager.field_log = NS(emit=lambda *args, **kwargs: trace.append('field-log'))
        def lock(reason):
            trace.append('lock')
            BackendManager.lock_control(manager, reason)
        backend = NS(poll_lifecycle=Mock(side_effect=primary), lock_control=lock,
            lifecycle_snapshot=LifecycleSnapshot(LifecyclePhase.IDLE, 1, (), (), 0, False),
            lifecycle_pending=False, shutdown_completion=None)
        owner = life.WindowLifecycleController(backend)
        owner.ready_to_close = True
        return owner, safety, trace, primary, manager

    def close_fixture(self, retry=False):
        primary = RuntimeError('shutdown failed')
        backend = NS(request_shutdown=Mock(side_effect=primary), retry_shutdown=Mock(side_effect=primary),
            lifecycle_pending=False, shutdown_completion=NS(may_exit=False) if retry else None)
        owner = life.WindowLifecycleController(backend)
        owner.closing = retry
        return owner, backend, primary

    def call(self, action):
        try:
            return action(), None
        except Exception as error:
            return None, error

    def test_healthy_poll_reporting_observes_revoked_safety_and_original_context(self):
        owner, safety, trace, primary, _ = self.poll_fixture()
        observations = []
        def log(*args, **kwargs):
            observations.append((safety.control_state, args, kwargs, sys.exc_info()[1]))
        with patch.object(life._LOG, 'error', side_effect=log):
            update = owner.poll(Mock())
        self.assertEqual(trace, ['lock', 'field-log'])
        self.assertEqual(observations, [(ControlState.LOCKED, ('Window lifecycle polling failed',), {'exc_info': True}, primary)])
        self.assertEqual(update, life.LifecycleUpdate(False, False, 'lifecycle poll: TypeError: poll failed', True))
        self.assertEqual(owner.last_poll_failure, life.OwnerActionFailure('lifecycle poll', 'TypeError', 'poll failed'))
        self.assertEqual(owner.poll_failures, 1)
        self.assertFalse(owner.ready_to_close)

    def test_poll_diagnostic_exception_cannot_skip_revocation_or_failed_update(self):
        owner, safety, trace, _, _ = self.poll_fixture()
        with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
            update, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(trace, ['lock', 'field-log'])
        self.assertEqual(update, life.LifecycleUpdate(False, False, 'lifecycle poll: TypeError: poll failed', True))
        self.assertEqual(owner.status_text, update.notification)
        self.assertEqual(owner.last_poll_failure.message, 'poll failed')

    def test_standard_closed_stderr_cannot_prevent_poll_lock_or_failed_result(self):
        owner, safety, trace, _, _ = self.poll_fixture()
        stream = io.StringIO(); stream.close()
        logger = logging.Logger('closed in-memory stderr')
        logger.addHandler(logging.StreamHandler(stream))
        with (patch.object(life, '_LOG', logger), patch.object(sys, 'stderr', stream),
              patch.object(logging, 'raiseExceptions', True)):
            update, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(trace, ['lock', 'field-log'])
        self.assertTrue(update.failed)

    def test_logger_attribute_lookup_exception_cannot_skip_poll_lock(self):
        class Logger:
            @property
            def error(self):
                raise OSError('logger unavailable')
        owner, safety, _, _, _ = self.poll_fixture()
        with patch.object(life, '_LOG', Logger()):
            update, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertTrue(update.failed)

    def test_repeated_fault_keeps_count_lock_attempts_and_deduplicated_notice(self):
        owner, safety, trace, _, _ = self.poll_fixture()
        with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')) as log:
            first, error1 = self.call(lambda: owner.poll(Mock()))
            second, error2 = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error1)
        self.assertIsNone(error2)
        self.assertEqual(owner.poll_failures, 2)
        self.assertEqual(trace, ['lock', 'field-log', 'lock', 'field-log'])
        self.assertTrue(first.notification)
        self.assertEqual(second.notification, '')
        log.assert_called_once()
        self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_next_healthy_poll_allows_runtime_without_restoring_armed_authority(self):
        owner, safety, _, _, _ = self.poll_fixture()
        with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
            _, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        owner.backend.poll_lifecycle.side_effect = None
        owner.backend.poll_lifecycle.return_value = None
        self.assertTrue(owner.poll(Mock()).runtime_allowed)
        self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_lock_side_failure_still_reports_both_original_tracebacks_and_failed_update(self):
        owner, safety, trace, primary, manager = self.poll_fixture()
        secondary = OSError('field logger failed after safety lock')
        manager.field_log.emit = Mock(side_effect=secondary)
        exception_contexts = []
        def capture(*args, **kwargs):
            info = kwargs['exc_info']
            exception_contexts.append(sys.exc_info() if info is True else info)
        with patch.object(life._LOG, 'error', side_effect=capture) as log:
            update, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(trace, ['lock'])
        self.assertTrue(update.failed)
        self.assertEqual(log.call_args_list[0].args, ('Window lifecycle polling failed',))
        self.assertEqual(log.call_args_list[1].args, ('Could not lock after lifecycle polling failure',))
        self.assertIs(exception_contexts[0][1], primary)
        exception_info = exception_contexts[1]
        self.assertIs(exception_info[0], OSError)
        self.assertIs(exception_info[1], secondary)
        self.assertIs(exception_info[2], secondary.__traceback__)
        self.assertEqual(owner.last_poll_failure.message, str(primary))

    def test_both_diagnostic_failures_do_not_escape_after_lock_side_failure(self):
        owner, safety, _, _, manager = self.poll_fixture()
        manager.field_log.emit = Mock(side_effect=OSError('field logger failed'))
        with patch.object(life._LOG, 'error', side_effect=ValueError('diagnostic failed')) as log:
            update, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        self.assertEqual(log.call_count, 2)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertTrue(update.failed)
        self.assertEqual(owner.last_poll_failure.message, 'poll failed')

    def test_unprintable_poll_error_is_formatted_only_after_revocation(self):
        owner, safety, trace, _, _ = self.poll_fixture()
        observed = []
        class Failure(RuntimeError):
            def __str__(self):
                observed.append(safety.control_state)
                raise ValueError('format failed')
        owner.backend.poll_lifecycle.side_effect = Failure()
        with patch.object(life._LOG, 'error'):
            update, error = self.call(lambda: owner.poll(Mock()))
        self.assertIsNone(error)
        self.assertEqual(observed, [ControlState.LOCKED])
        self.assertEqual(trace, ['lock', 'field-log'])
        self.assertEqual(owner.last_poll_failure, life.OwnerActionFailure('lifecycle poll', 'Failure', '<unprintable exception>'))
        self.assertEqual(update.notification, 'lifecycle poll: Failure: <unprintable exception>')

    def test_request_failure_marker_and_record_exist_before_diagnostic_callback(self):
        owner, backend, primary = self.close_fixture()
        observed = []
        def log(*args, **kwargs):
            observed.append((owner._request_failed, owner.owner_failures, sys.exc_info()[1]))
            raise OSError('sink failed')
        with patch.object(life._LOG, 'error', side_effect=log):
            _, error = self.call(lambda: owner.request_close(prepare=(), tasks=()))
            owner.request_close(prepare=(), tasks=())
        self.assertIsNone(error)
        expected = (life.OwnerActionFailure('shutdown request', 'RuntimeError', 'shutdown failed'),)
        self.assertEqual(observed, [(True, expected, primary)])
        self.assertEqual(owner.owner_failures, expected)
        backend.request_shutdown.assert_called_once_with(teardown_tasks=())
        self.assertTrue(owner.closing)

    def test_retry_failure_marker_and_record_exist_before_diagnostic_callback(self):
        owner, backend, primary = self.close_fixture(retry=True)
        observed = []
        def log(*args, **kwargs):
            observed.append((owner._request_failed, owner.owner_failures, sys.exc_info()[1]))
            raise OSError('sink failed')
        with patch.object(life._LOG, 'error', side_effect=log):
            result, error = self.call(owner.retry_close)
        self.assertIsNone(error)
        self.assertFalse(result)
        expected = (life.OwnerActionFailure('shutdown retry', 'RuntimeError', 'shutdown failed'),)
        self.assertEqual(observed, [(True, expected, primary)])
        backend.retry_shutdown.assert_called_once()

    def test_request_and_retry_unprintable_primary_keep_original_type(self):
        class Failure(RuntimeError):
            def __str__(self):
                raise ValueError('format failed')
        for retry in (False, True):
            with self.subTest(retry=retry):
                owner, backend, _ = self.close_fixture(retry=retry)
                backend.request_shutdown.side_effect = backend.retry_shutdown.side_effect = Failure()
                call = owner.retry_close if retry else lambda: owner.request_close(prepare=(), tasks=())
                with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
                    _, error = self.call(call)
                self.assertIsNone(error)
                self.assertTrue(owner._request_failed)
                self.assertEqual(owner.owner_failures[0].error_type, 'Failure')
                self.assertEqual(owner.owner_failures[0].message, '<unprintable exception>')

    def test_poll_operation_baseexception_is_not_swallowed_or_reclassified(self):
        owner, safety, trace, _, _ = self.poll_fixture()
        failure = KeyboardInterrupt('stop poll')
        owner.backend.poll_lifecycle.side_effect = failure
        with self.assertRaises(BaseException) as caught:
            owner.poll(Mock())
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, [])
        self.assertEqual(safety.control_state, ControlState.MATCH_ARMED)
        self.assertEqual(owner.poll_failures, 0)

    def test_poll_logger_baseexception_propagates_after_required_lock(self):
        owner, safety, trace, _, _ = self.poll_fixture()
        failure = SystemExit('stop logging')
        with patch.object(life._LOG, 'error', side_effect=failure):
            with self.assertRaises(BaseException) as caught:
                owner.poll(Mock())
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['lock', 'field-log'])
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(owner.last_poll_failure.message, 'poll failed')

    def test_poll_lock_baseexception_is_not_swallowed(self):
        owner, _, _, _, _ = self.poll_fixture()
        failure = KeyboardInterrupt('stop locking')
        owner.backend.lock_control = Mock(side_effect=failure)
        with patch.object(life._LOG, 'error') as log:
            with self.assertRaises(BaseException) as caught:
                owner.poll(Mock())
        self.assertIs(caught.exception, failure)
        log.assert_not_called()

    def test_process_control_formatter_propagates_after_required_state_prefix(self):
        failure = KeyboardInterrupt('stop formatting')
        class Failure(RuntimeError):
            def __str__(self):
                raise failure
        owner, safety, trace, _, _ = self.poll_fixture()
        owner.backend.poll_lifecycle.side_effect = Failure()
        with patch.object(life._LOG, 'error') as log:
            with self.assertRaises(BaseException) as caught:
                owner.poll(Mock())
        self.assertIs(caught.exception, failure)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertEqual(trace, ['lock', 'field-log'])
        log.assert_not_called()

    def test_request_and_retry_process_control_operation_or_logger_propagates(self):
        for retry in (False, True):
            for where in ('operation', 'logger'):
                with self.subTest(retry=retry, where=where):
                    owner, backend, _ = self.close_fixture(retry=retry)
                    failure = SystemExit('stop close')
                    if where == 'operation':
                        backend.request_shutdown.side_effect = backend.retry_shutdown.side_effect = failure
                    call = owner.retry_close if retry else lambda: owner.request_close(prepare=(), tasks=())
                    with patch.object(life._LOG, 'error', side_effect=failure) as log:
                        with self.assertRaises(BaseException) as caught:
                            call()
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(owner._request_failed, where == 'logger')
                    if where == 'operation':
                        log.assert_not_called()

    def test_healthy_retry_success_keeps_existing_state_reset_and_status(self):
        owner, backend, _ = self.close_fixture(retry=True)
        owner._request_failed = True
        owner._last_notice = ('old',)
        backend.retry_shutdown.side_effect = None
        with patch.object(life._LOG, 'error') as log:
            self.assertTrue(owner.retry_close())
        log.assert_not_called()
        self.assertFalse(owner._request_failed)
        self.assertIsNone(owner._last_notice)
        self.assertEqual(owner.status_text, 'Retrying failed resource cleanup…')


if __name__ == '__main__':
    unittest.main(verbosity=2)
