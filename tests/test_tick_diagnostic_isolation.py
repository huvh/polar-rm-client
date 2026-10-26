"""Tick diagnostics preserve independent runtime stages when logging fails."""
from pathlib import Path
import ast
import io
import logging
import sys
from types import MethodType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rm_client
ROOT = Path(rm_client.__file__).resolve().parent.parent
from rm_client.ui.polar.tick_controller import RuntimeTickPlan, TickDiagnostics, TickStageRunner

LATER = ['backend.apply', 'backend.readiness', 'hero.lob', 'guard placeholder',
         'official.consume', 'official.apply', 'fx.hit_info', 'vision.sync', 'vision.events',
         'registry', 'mqtt.link', 'polar.link']


def actual_methods(logger):
    path = ROOT / 'rm_client/ui/polar_app.py'
    tree = ast.parse(path.read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PolarRMWindow')
    names = {'_advance_runtime_tick', '_run_tick_stage'}
    methods = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(RuntimeTickPlan=RuntimeTickPlan, TickStageRunner=TickStageRunner,
                     time=NS(perf_counter=lambda: 10.), _LOG=logger)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *methods], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace


class RuntimeFixture:
    def host(self, *, logger=None, emitter=None, primary=None):
        calls = []
        logger = logger if logger is not None else Mock(spec=logging.Logger)
        emitter = emitter if emitter is not None else Mock()
        primary = primary if primary is not None else ValueError('broken packet')
        def record(name):
            return lambda *a, **k: calls.append(name)
        def fail():
            calls.append('backend.tick')
            raise primary
        host = NS(_tick_diagnostics=TickDiagnostics(), _last_control_tick_time=10., _last_logic_time=9.,
                  _modal_input_blocked=lambda: False, home_visible=True,
                  startup_wallpaper=NS(set_active=record('wallpaper')), consume_capture_frame=record('capture'),
                  state=NS(backend_stats={}, tick=record('state.tick')),
                  camera_worker=NS(connected=False), mqtt=NS(connected=False), serial=NS(connected=False),
                  udp=NS(decoded_frame_fresh=lambda _: False), NORMAL_BACKEND_VIDEO_STALE_S=1.,
                  registry=NS(tick=record('registry'), get=lambda _: None), control=object())
        host.backend = NS(tick=fail, apply_updates=record('backend.apply'),
            field_log=NS(emit=emitter), sync_mqtt_link=record('mqtt.link'), tick_polar_link=record('polar.link'))
        for attr, name in (('update_backend_readiness', 'backend.readiness'),
            ('update_hero_lob_guard', 'hero.lob'), ('update_auto_spin_guard', 'guard placeholder'),
            ('consume_official_messages', 'official.consume'), ('apply_official_state', 'official.apply'),
            ('update_elimination_hit_info', 'fx.hit_info'), ('sync_tongji_vision_state', 'vision.sync'),
            ('process_vision_kill_events', 'vision.events')):
            setattr(host, attr, record(name))
        # The guard placeholder is a recorder only. No spin implementation is imported or executed.
        methods = actual_methods(logger)
        host._run_tick_stage = MethodType(methods['_run_tick_stage'], host)
        host.run = lambda: methods['_advance_runtime_tick'](host, 10.)
        return host, calls, logger, emitter, primary

    def observed(self, host):
        try:
            host.run()
        except Exception as error:
            return error
        return None

    def assert_recorded(self, host):
        self.assertEqual(host._tick_diagnostics.count, 1)
        self.assertEqual(host._tick_diagnostics.last_error, 'backend.tick: ValueError: broken packet')
        self.assertEqual(host.state.backend_stats['ui_tick']['errors'], 1)
        self.assertEqual(host._tick_diagnostics.stages['backend.tick']['count'], 1)



class TickDiagnosticIsolationTests(unittest.TestCase, RuntimeFixture):
    def runner(self, *, logger=None, emitter=None, primary=None):
        owner, stats = TickDiagnostics(), {}
        logger = logger if logger is not None else Mock(spec=logging.Logger)
        emitter = emitter if emitter is not None else Mock()
        primary = primary if primary is not None else ValueError('packet rejected')
        clock = Mock(side_effect=[10., 10.005])
        runner = TickStageRunner(stats, emitter, logger, clock)
        def failed():
            raise primary
        return owner, stats, logger, emitter, primary, runner, failed

    def run_observed(self, owner, runner, action, now=10.):
        try:
            return owner.run_stage(runner, 'backend', action, now=now), None
        except Exception as error:
            return None, error

    def assert_fields(self, owner, stats):
        self.assertEqual(owner.count, 1)
        self.assertEqual(owner.last_error, 'backend: ValueError: packet rejected')
        self.assertEqual(stats, {'ui_tick': {'errors': 1, 'last_error': owner.last_error}})
        self.assertEqual(owner.last_logged_at, {'backend': 10.})
        self.assertEqual(owner.stages.get('backend', {}).get('count'), 1)
        self.assertAlmostEqual(owner.stages.get('backend', {}).get('total_ms', -1), 5.)

    def test_healthy_message_active_exception_emitter_order_and_fields_are_unchanged(self):
        owner, stats, logger, emit, primary, runner, failed = self.runner()
        seen = []
        logger.exception.side_effect = lambda *a, **k: seen.append(('log', a, k, sys.exc_info()[1]))
        emit.side_effect = lambda *a, **k: seen.append(('emit', a, k, sys.exc_info()[1]))
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        self.assertEqual(seen, [
            ('log', ('UI tick stage failed: %s', 'backend'), {}, primary),
            ('emit', ('thread_exception',), {'stage': 'backend', 'error_type': 'ValueError', 'error': 'packet rejected', 'count': 1}, primary)])
        logger.warning.assert_not_called()
        self.assert_fields(owner, stats)

    def test_primary_logger_emission_failure_preserves_false_result_and_field_log_attempt(self):
        owner, stats, logger, emit, primary, runner, failed = self.runner()
        logger.exception.side_effect = OSError('logger failed')
        seen = []
        emit.side_effect = lambda *a, **k: seen.append(sys.exc_info()[1])
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        self.assertEqual(seen, [primary])
        emit.assert_called_once_with('thread_exception', stage='backend', error_type='ValueError', error='packet rejected', count=1)
        logger.warning.assert_not_called()
        self.assert_fields(owner, stats)

    def test_primary_logger_attribute_lookup_failure_does_not_skip_field_log(self):
        class Logger:
            @property
            def exception(self):
                raise OSError('logger lookup failed')
        owner, stats, _, emit, _, runner, failed = self.runner(logger=Logger())
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        emit.assert_called_once()
        self.assert_fields(owner, stats)

    def test_warning_logger_emission_failure_preserves_original_record_and_false_result(self):
        owner, stats, logger, emit, _, runner, failed = self.runner()
        emit.side_effect = OSError('field log failed')
        logger.warning.side_effect = OSError('warning logger failed')
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        logger.exception.assert_called_once_with('UI tick stage failed: %s', 'backend')
        logger.warning.assert_called_once_with('UI tick failure diagnostic could not be written', exc_info=True)
        self.assert_fields(owner, stats)

    def test_warning_logger_attribute_lookup_failure_keeps_original_fields(self):
        class Logger:
            exception = Mock()
            @property
            def warning(self):
                raise OSError('warning lookup failed')
        owner, stats, _, emit, _, runner, failed = self.runner(logger=Logger())
        emit.side_effect = OSError('field log failed')
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        self.assert_fields(owner, stats)

    def test_both_logger_failures_keep_field_emitter_then_warning_active_context(self):
        owner, stats, logger, emit, primary, runner, failed = self.runner()
        trace = []
        field_error = OSError('field log failed')
        def report(*args, **kwargs):
            trace.append(('log', sys.exc_info()[1]))
            raise OSError('logger failed')
        def field(*args, **kwargs):
            trace.append(('emit', sys.exc_info()[1]))
            raise field_error
        def warn(*args, **kwargs):
            trace.append(('warning', sys.exc_info()[1]))
            raise OSError('warning failed')
        logger.exception.side_effect, emit.side_effect, logger.warning.side_effect = report, field, warn
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        self.assertEqual(trace, [('log', primary), ('emit', primary), ('warning', field_error)])
        self.assert_fields(owner, stats)

    def test_standard_closed_stderr_isolated_for_primary_and_fallback_logging(self):
        for failed_emitter in (False, True):
            with self.subTest(failed_emitter=failed_emitter):
                stream = io.StringIO(); stream.close()
                logger = logging.Logger('closed in-memory stderr')
                logger.addHandler(logging.StreamHandler(stream))
                owner, stats, _, emit, _, runner, failed = self.runner(logger=logger)
                if failed_emitter:
                    emit.side_effect = OSError('field log failed')
                with patch.object(sys, 'stderr', stream), patch.object(logging, 'raiseExceptions', True):
                    result, error = self.run_observed(owner, runner, failed)
                self.assertIsNone(error)
                self.assertFalse(result)
                emit.assert_called_once()
                self.assert_fields(owner, stats)

    def test_fault_throttle_is_per_stage_and_counters_still_advance(self):
        owner, stats, logger, emit, _, _, failed = self.runner()
        logger.exception.side_effect = OSError('logger failed')
        runner = TickStageRunner(stats, emit, logger, lambda: 10.)
        for now in (10., 10.2, 10.999, 11.):
            result, error = self.run_observed(owner, runner, failed, now)
            self.assertIsNone(error)
            self.assertFalse(result)
        self.assertEqual(owner.count, 4)
        self.assertEqual(owner.last_logged_at, {'backend': 11.})
        self.assertEqual(logger.exception.call_count, 2)
        self.assertEqual(emit.call_count, 2)
        self.assertEqual(owner.stages.get('backend', {}).get('count'), 4)
        # A different stage retains its independent first-report eligibility.
        self.assertFalse(owner.run_stage(runner, 'vision', failed, now=10.2))
        self.assertEqual(logger.exception.call_count, 3)
        self.assertEqual(owner.last_logged_at['vision'], 10.2)

    def test_success_does_not_touch_existing_fault_history_or_diagnostics(self):
        owner, stats, logger, emit, _, runner, _ = self.runner()
        owner.count, owner.last_error = 7, 'old error'
        owner.last_logged_at['previous'] = 9.
        logger.exception.side_effect = OSError('should not be called')
        result, error = self.run_observed(owner, runner, lambda: None)
        self.assertIsNone(error)
        self.assertTrue(result)
        self.assertEqual((owner.count, owner.last_error, owner.last_logged_at), (7, 'old error', {'previous': 9.}))
        self.assertEqual(stats, {})
        logger.exception.assert_not_called()
        logger.warning.assert_not_called()
        emit.assert_not_called()
        self.assertEqual(owner.stages.get('backend', {}).get('count'), 1)

    def test_actual_runtime_adapter_continues_all_later_inert_callbacks(self):
        for failure in ('primary', 'warning', 'both'):
            with self.subTest(failure=failure):
                host, calls, logger, emit, _ = self.host()
                if failure in ('primary', 'both'):
                    logger.exception.side_effect = OSError('logger failed')
                if failure in ('warning', 'both'):
                    emit.side_effect = OSError('field log failed')
                    logger.warning.side_effect = OSError('warning failed')
                self.assertIsNone(self.observed(host))
                self.assertEqual(calls, ['wallpaper', 'capture', 'state.tick', 'backend.tick', *LATER])
                self.assert_recorded(host)

    def test_reentrant_successful_stage_does_not_replace_original_fault(self):
        owner, stats, logger, emit, _, _, failed = self.runner()
        runner = TickStageRunner(stats, emit, logger, lambda: 10.)
        nested = []
        def report(*args, **kwargs):
            nested.append(owner.run_stage(runner, 'nested', lambda: None, now=10.))
            raise OSError('logger failed')
        logger.exception.side_effect = report
        result, error = self.run_observed(owner, runner, failed)
        self.assertIsNone(error)
        self.assertFalse(result)
        self.assertEqual(nested, [True])
        self.assertEqual(owner.count, 1)
        self.assertEqual(owner.last_error, 'backend: ValueError: packet rejected')
        self.assertEqual(set(owner.stages), {'nested', 'backend'})
        emit.assert_called_once()

    def test_primary_logger_baseexception_retains_identity_prefix_and_timing(self):
        owner, stats, logger, emit, _, runner, failed = self.runner()
        stop = SystemExit('stop logger')
        logger.exception.side_effect = stop
        with self.assertRaises(BaseException) as caught:
            owner.run_stage(runner, 'backend', failed, now=10.)
        self.assertIs(caught.exception, stop)
        emit.assert_not_called()
        logger.warning.assert_not_called()
        self.assert_fields(owner, stats)

    def test_fallback_logger_baseexception_retains_identity_and_timing(self):
        owner, stats, logger, emit, _, runner, failed = self.runner()
        emit.side_effect = OSError('field log failed')
        stop = KeyboardInterrupt('stop warning')
        logger.warning.side_effect = stop
        with self.assertRaises(BaseException) as caught:
            owner.run_stage(runner, 'backend', failed, now=10.)
        self.assertIs(caught.exception, stop)
        emit.assert_called_once()
        logger.exception.assert_called_once()
        self.assert_fields(owner, stats)

    def test_field_emitter_baseexception_remains_outside_fallback_handler(self):
        owner, stats, logger, emit, _, runner, failed = self.runner()
        stop = KeyboardInterrupt('stop field log')
        emit.side_effect = stop
        with self.assertRaises(BaseException) as caught:
            owner.run_stage(runner, 'backend', failed, now=10.)
        self.assertIs(caught.exception, stop)
        logger.warning.assert_not_called()
        self.assert_fields(owner, stats)

    def test_operation_baseexception_does_not_become_an_ordinary_stage_fault(self):
        stop = KeyboardInterrupt('stop operation')
        owner, stats, logger, emit, _, runner, failed = self.runner(primary=stop)
        with self.assertRaises(BaseException) as caught:
            owner.run_stage(runner, 'backend', failed, now=10.)
        self.assertIs(caught.exception, stop)
        self.assertEqual((owner.count, owner.last_error, stats), (0, '', {}))
        logger.exception.assert_not_called()
        emit.assert_not_called()
        self.assertEqual(owner.stages.get('backend', {}).get('count'), 1)

    def test_failed_primary_formatting_retains_existing_partial_bookkeeping_boundary(self):
        stop = ValueError('format failed')
        class Primary(RuntimeError):
            def __str__(self):
                raise stop
        owner, stats, logger, emit, _, runner, failed = self.runner(primary=Primary())
        _, error = self.run_observed(owner, runner, failed)
        self.assertIs(error, stop)
        self.assertEqual((owner.count, owner.last_error, owner.last_logged_at, stats), (1, '', {}, {}))
        self.assertEqual(owner.stages.get('backend', {}).get('count'), 1)
        logger.exception.assert_not_called()
        emit.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
