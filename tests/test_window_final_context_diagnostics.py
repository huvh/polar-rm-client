"""Final-context failures reach stored records and the actual window warning adapter."""
from pathlib import Path
import io
import logging
import sys
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from rm_client.ui.polar import window_lifecycle as life
from test_window_finalization_contract import FinalizationFixture, RESOURCE_NAMES, production_finish


class WindowFinalContextDiagnosticTests(unittest.TestCase):
    finish = staticmethod(production_finish())

    def host(self, fault='context', primary=None):
        host = FinalizationFixture()
        original = host.call
        primary = primary if primary is not None else OSError(fault + ' rejected')
        def call(name, *args):
            if name == fault:
                host.calls.append((name, *args))
                raise primary
            return original(name, *args)
        host.call = call
        if fault == 'resources':
            class Resource:
                @property
                def release(self):
                    host.calls.append(('resources',))
                    raise primary
            host.clickgui_gpu = Resource()
        return host, primary

    def prefix(self, fault):
        names = ['timer', 'warmup', 'save', 'context']
        if fault != 'context':
            names.append('make')
            if fault == 'resources':
                names.append('resources')
            names.append('done')
        return names

    def observed(self, host):
        try:
            self.finish(host)
        except Exception as error:
            return error
        return None

    def assert_recorded(self, host, primary, fault, message=None):
        self.assertEqual(host._window_lifecycle.finalization_failures,
                         (life.OwnerActionFailure('GL context', type(primary).__name__, str(primary) if message is None else message),))
        self.assertTrue(host._window_close_finalized)
        self.assertEqual([item[0] for item in host.calls], self.prefix(fault) + ['event', 'warning'])
        self.assertEqual(host.calls[-1][1], host.calls[-2][1])

    def test_healthy_logging_preserves_message_arguments_active_exception_and_warning(self):
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                host, primary = self.host(fault)
                seen = []
                def report(*args, **kwargs):
                    seen.append((args, kwargs, sys.exc_info()[1]))
                with patch.object(life._LOG, 'error', side_effect=report):
                    self.assertIsNone(self.observed(host))
                message = 'Window GL context inspection failed' if fault == 'context' else 'Window GL context cleanup failed'
                self.assertEqual(seen, [((message,), {'exc_info': True}, primary)])
                self.assert_recorded(host, primary, fault)

    def test_raising_logger_preserves_original_record_and_actual_adapter_warnings(self):
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                host, primary = self.host(fault)
                with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
                    error = self.observed(host)
                self.assertIsNone(error)
                self.assert_recorded(host, primary, fault)

    def test_logger_attribute_lookup_failure_cannot_hide_original_context_failure(self):
        class Logger:
            @property
            def error(self):
                raise OSError('logger lookup failed')
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                host, primary = self.host(fault)
                with patch.object(life, '_LOG', Logger()):
                    error = self.observed(host)
                self.assertIsNone(error)
                self.assert_recorded(host, primary, fault)

    def test_standard_closed_stderr_preserves_record_and_warning_delivery(self):
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                host, primary = self.host(fault)
                stream = io.StringIO(); stream.close()
                logger = logging.Logger('closed in-memory stderr')
                logger.addHandler(logging.StreamHandler(stream))
                with (patch.object(life, '_LOG', logger), patch.object(sys, 'stderr', stream),
                      patch.object(logging, 'raiseExceptions', True)):
                    error = self.observed(host)
                self.assertIsNone(error)
                self.assert_recorded(host, primary, fault)

    def test_unprintable_primary_uses_existing_owner_fallback(self):
        class Failure(RuntimeError):
            def __str__(self):
                raise ValueError('render failed')
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                host, primary = self.host(fault, Failure())
                with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
                    error = self.observed(host)
                self.assertIsNone(error)
                self.assert_recorded(host, primary, fault, '<unprintable exception>')

    def test_diagnostic_rendering_is_not_required_to_store_original_failure(self):
        class Diagnostic(RuntimeError):
            def __str__(self):
                raise AssertionError('diagnostic rendering must not be required')
        host, primary = self.host()
        with patch.object(life._LOG, 'error', side_effect=Diagnostic()):
            error = self.observed(host)
        self.assertIsNone(error)
        self.assert_recorded(host, primary, 'context')

    def test_reentrant_logger_keeps_seal_and_does_not_repeat_cleanup_or_warnings(self):
        host, primary = self.host('make')
        nested = []
        def report(*args, **kwargs):
            nested.append(self.finish(host))
            raise OSError('sink failed')
        with patch.object(life._LOG, 'error', side_effect=report):
            error = self.observed(host)
        self.assertIsNone(error)
        self.assertEqual(nested, [None])
        self.assert_recorded(host, primary, 'make')
        before = list(host.calls)
        self.finish(host)
        self.assertEqual(host.calls, before)

    def test_prior_owner_failures_remain_before_context_failure(self):
        host, primary = self.host('make')
        prior = life.OwnerActionFailure('earlier', 'ValueError', 'prepare failed')
        host._window_lifecycle.owner_failures = (prior,)
        with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
            error = self.observed(host)
        self.assertIsNone(error)
        self.assertEqual(host._window_lifecycle.finalization_failures,
                         (prior, life.OwnerActionFailure('GL context', 'OSError', 'make rejected')))
        self.assertIn('earlier: ValueError: prepare failed; GL context: OSError: make rejected', host.calls[-1][1])

    def test_done_action_failure_is_still_aggregated_after_context_failure(self):
        host, _ = self.host('make')
        host.faults.add('done')
        with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
            error = self.observed(host)
        self.assertIsNone(error)
        self.assertEqual([f.name for f in host._window_lifecycle.finalization_failures],
                         ['GL context', 'GL done', 'GL done diagnostic'])
        self.assertEqual([item[0] for item in host.calls], self.prefix('make') + ['event', 'warning'])

    def test_warning_callback_failure_keeps_stored_record_and_does_not_replay(self):
        for fault in ('event', 'warning'):
            with self.subTest(fault=fault):
                host, primary = self.host('make')
                host.faults.add(fault)
                with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
                    error = self.observed(host)
                self.assertIsInstance(error, OSError)
                self.assertEqual(str(error), fault + ' rejected')
                self.assertEqual(host._window_lifecycle.finalization_failures,
                                 (life.OwnerActionFailure('GL context', 'OSError', 'make rejected'),))
                before = list(host.calls)
                self.finish(host)
                self.assertEqual(host.calls, before)

    def test_absent_context_and_successful_context_keep_no_diagnostic_path(self):
        for available in (False, True):
            with self.subTest(available=available):
                host = FinalizationFixture(context=available)
                with patch.object(life._LOG, 'error') as log:
                    self.finish(host)
                log.assert_not_called()
                self.assertEqual(host._window_lifecycle.finalization_failures, ())
                expected = ['timer', 'warmup', 'save', 'context']
                if available:
                    expected += ['make', *RESOURCE_NAMES, 'done']
                self.assertEqual([item[0] for item in host.calls], expected)

    def test_leave_factory_failure_retains_identity_and_existing_propagation(self):
        stop = AttributeError('doneCurrent lookup failed')
        class MissingLeave(FinalizationFixture):
            def __getattribute__(self, name):
                if name == 'doneCurrent':
                    raise stop
                return super().__getattribute__(name)
        for fault in (None, 'make'):
            with self.subTest(fault=fault):
                host = MissingLeave(faults=(fault,) if fault else ())
                with patch.object(life._LOG, 'error', side_effect=OSError('sink failed')):
                    error = self.observed(host)
                self.assertIs(error, stop)
                self.assertTrue(host._window_close_finalized)
                self.assertEqual(host._window_lifecycle.finalization_failures, ())
                expected = ['timer', 'warmup', 'save', 'context', 'make']
                if fault is None:
                    expected += list(RESOURCE_NAMES)
                self.assertEqual([item[0] for item in host.calls], expected)

    def test_operation_baseexception_keeps_identity_and_finally_leave(self):
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                stop = KeyboardInterrupt('stop operation')
                host, _ = self.host(fault, stop)
                with patch.object(life._LOG, 'error') as log:
                    with self.assertRaises(BaseException) as caught:
                        self.finish(host)
                self.assertIs(caught.exception, stop)
                log.assert_not_called()
                self.assertEqual([item[0] for item in host.calls], self.prefix(fault))
                self.assertTrue(host._window_close_finalized)
                self.assertEqual(host._window_lifecycle.finalization_failures, ())

    def test_logger_baseexception_keeps_identity_and_does_not_start_formatting(self):
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                formatted = []
                class Primary(RuntimeError):
                    def __str__(self):
                        formatted.append(True)
                        return 'primary failed'
                host, _ = self.host(fault, Primary())
                stop = SystemExit('stop logging')
                with patch.object(life._LOG, 'error', side_effect=stop):
                    with self.assertRaises(BaseException) as caught:
                        self.finish(host)
                self.assertIs(caught.exception, stop)
                self.assertEqual(formatted, [])
                self.assertEqual([item[0] for item in host.calls], self.prefix(fault))
                self.assertEqual(host._window_lifecycle.finalization_failures, ())

    def test_formatter_baseexception_remains_after_logging_and_keeps_finally_leave(self):
        for fault in ('context', 'make', 'resources'):
            with self.subTest(fault=fault):
                order = []
                stop = KeyboardInterrupt('stop formatter')
                class Primary(RuntimeError):
                    def __str__(self):
                        order.append('format')
                        raise stop
                host, _ = self.host(fault, Primary())
                with patch.object(life._LOG, 'error', side_effect=lambda *a, **k: order.append('log')):
                    with self.assertRaises(BaseException) as caught:
                        self.finish(host)
                self.assertIs(caught.exception, stop)
                self.assertEqual(order, ['log', 'format'])
                self.assertEqual([item[0] for item in host.calls], self.prefix(fault))
                self.assertEqual(host._window_lifecycle.finalization_failures, ())


if __name__ == '__main__':
    unittest.main(verbosity=2)
