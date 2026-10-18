"""Actual close adapter AST, pure safety owner, and inert close events only."""
import ast
import io
import logging
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rm_client
REPO = Path(rm_client.__file__).resolve().parent.parent
from rm_client.emergency_actions import request_control_lock
from rm_client.backend.safety import OfficialSafety
WINDOW_SOURCE = REPO / 'rm_client/ui/polar_app.py'
MANAGER_SOURCE = REPO / 'rm_client/backend/manager.py'
PERSISTENCE_SOURCE = REPO / 'rm_client/ui/polar/mixins/persistence_mixin.py'

class Event:
    """An initially accepted inert event; no claim about native Qt exception routing."""
    def __init__(self): self.accepted = True; self.ignored = 0
    def ignore(self): self.accepted = False; self.ignored += 1

def method(source, class_name, name, **scope):
    cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node]
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(source), 'exec'), scope)
    return scope[name]

def fixture(*, primary=None, logger=None, requires_save=True, prepare_result=False):
    tree = ast.parse(WINDOW_SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PolarRMWindow')
    selected = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {'closeEvent', '_admit_window_close'}]
    class Base:
        def closeEvent(self, event): self.trace.append('super-close')
    node = ast.ClassDef(name='Host', bases=[ast.Name(id='Base', ctx=ast.Load())], keywords=[], body=selected, decorator_list=[])
    scope = dict(Base=Base, request_control_lock=request_control_lock, _LOG=logger or Mock(spec=logging.Logger))
    body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node]
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(WINDOW_SOURCE), 'exec'), scope)
    host = scope['Host']()
    host.trace, host.warnings = [], []
    host._unsaved_profile_name = 'retained-draft'
    host.configuration_close_requires_save = requires_save
    host._window_lifecycle = NS(ready_to_close=False, closing=False, retry_close=lambda: host.trace.append('retry'))
    def begin(): host.trace.append('begin'); host._window_lifecycle.closing = True
    host._begin_window_shutdown = begin
    host._finish_window_shutdown = lambda: host.trace.append('finish')
    def toast(message, **kw): host.trace.append('toast'); host.warnings.append((message, kw))
    host.toast = toast
    safety = OfficialSafety()
    safety.begin_qualification({'kmc_heartbeat'})
    safety.input_clear_hook = lambda reason: host.trace.append('safety-lock')
    host.backend = NS(safety=safety, lifecycle_pending=False,
        mqtt=NS(publish_estop_zero=lambda: (host.trace.append('zero') or (True, ''))),
        field_log=NS(emit=lambda *a, **k: host.trace.append('lock-log')))
    host.backend.lock_control = MethodType(method(MANAGER_SOURCE, 'BackendManager', 'lock_control'), host.backend)
    host.control = NS(reset_inputs=lambda: host.trace.append('reset'), clear_pending=lambda: host.trace.append('clear'))
    def prepare():
        host.trace.append('prepare')
        if primary is not None: raise primary
        return prepare_result
    host.prepare_configuration_for_close = prepare
    host.event, host.logger = Event(), scope['_LOG']
    return host

def closed_stderr_logger():
    stream = io.StringIO(); stream.close()
    logger = logging.Logger('close-admission-proof')
    logger.addHandler(logging.StreamHandler(stream))
    return logger, stream

class CloseAdmissionDiagnosticTests(unittest.TestCase):
    def no_escape(self, call):
        error = None
        try: call()
        except Exception as caught: error = caught
        self.assertIsNone(error, 'ordinary diagnostic must not prevent close refusal')

    def assert_refused(self, host):
        self.assertFalse(host.event.accepted)
        self.assertEqual(host.event.ignored, 1)
        self.assertFalse(host._window_lifecycle.closing)
        self.assertEqual(host._unsaved_profile_name, 'retained-draft')
        self.assertEqual(host.backend.safety.control_state.value, 'LOCKED')
        self.assertIsNone(host.backend.safety._qualification)
        self.assertNotIn('begin', host.trace)

    def test_raising_error_logger_still_refuses_close(self):
        host = fixture(primary=ValueError('admission failed'), logger=Mock(error=Mock(side_effect=OSError('logger failed'))))
        self.no_escape(lambda: host.closeEvent(host.event))
        self.assert_refused(host)

    def test_standard_closed_stderr_still_refuses_close(self):
        logger, stream = closed_stderr_logger()
        host = fixture(primary=ValueError('admission failed'), logger=logger)
        with patch.object(sys, 'stderr', stream), patch.object(logging, 'raiseExceptions', True):
            self.no_escape(lambda: host.closeEvent(host.event))
        self.assert_refused(host)

    def test_healthy_error_logger_keeps_refusal_and_message_order(self):
        host = fixture(primary=ValueError('admission failed'))
        host.closeEvent(host.event)
        self.assert_refused(host)
        self.assertEqual(host.trace, ['safety-lock', 'lock-log', 'zero', 'reset', 'clear', 'prepare', 'toast', 'toast'])
        self.assertIn('ValueError: admission failed', host.warnings[0][0])
        self.assertIn('关闭已取消', host.warnings[1][0])
        host.logger.error.assert_called_once_with('Close configuration admission failed', exc_info=True)

    def test_accepted_close_starts_once_and_defers_event(self):
        host = fixture(prepare_result=True)
        host.closeEvent(host.event)
        self.assertFalse(host.event.accepted)
        self.assertTrue(host._window_lifecycle.closing)
        self.assertEqual(host.trace[-2:], ['prepare', 'begin'])
        self.assertEqual(host.warnings, [])
        host.logger.error.assert_not_called()

    def test_logger_process_control_keeps_exact_identity_and_prior_lock(self):
        failure = SystemExit('logger stop')
        host = fixture(primary=ValueError('admission failed'), logger=Mock(error=Mock(side_effect=failure)))
        with self.assertRaises(SystemExit) as caught: host.closeEvent(host.event)
        self.assertIs(caught.exception, failure)
        self.assertTrue(host.event.accepted)
        self.assertEqual(host.event.ignored, 0)
        self.assertEqual(host.backend.safety.control_state.value, 'LOCKED')
        self.assertIsNone(host.backend.safety._qualification)
        self.assertEqual(host.warnings, [])
        self.assertFalse(host._window_lifecycle.closing)

    def test_ready_and_closing_paths_do_not_repeat_admission(self):
        host = fixture(primary=ValueError('should not run'))
        host._window_lifecycle.closing = True
        host.closeEvent(host.event)
        self.assertEqual(host.trace, ['retry'])
        self.assertFalse(host.event.accepted)
        host = fixture(primary=ValueError('should not run'))
        host._window_lifecycle.ready_to_close = True
        host.closeEvent(host.event)
        self.assertEqual(host.trace, ['finish', 'super-close'])
        self.assertTrue(host.event.accepted)


    def test_direct_admission_returns_false_despite_logger_lookup_failure(self):
        class LookupLogger:
            @property
            def error(self): raise ValueError('logger lookup failed')
        host = fixture(primary=TypeError('admission failed'), logger=LookupLogger())
        result = []
        self.no_escape(lambda: result.append(host._admit_window_close()))
        self.assertEqual(result, [False])
        self.assertEqual(host.event.ignored, 0, 'only closeEvent owns event refusal')
        self.assertFalse(host._window_lifecycle.closing)
        self.assertEqual(len(host.warnings), 2)

    def test_actual_persistence_admission_and_save_adapter_reaches_refusal(self):
        primary = TypeError('config serialization failed')
        host = fixture(logger=Mock(error=Mock(side_effect=OSError('logger failed'))))
        host.configuration_change_pending = False
        identity = NS(name='accepted')
        host._accepted_profile_identity = lambda: identity
        host._profile_saves = NS(close_intent=lambda draft, accepted: NS(profile=draft, explicit=True))
        host.registry = NS(get=lambda name: None)
        host.config_store = NS(save_with_startup=Mock())
        def serialize(): host.trace.append('serialize'); raise primary
        host.current_config_data = serialize
        host._save_profile = MethodType(method(PERSISTENCE_SOURCE, 'PersistenceMixin', '_save_profile'), host)
        host.prepare_configuration_for_close = MethodType(method(PERSISTENCE_SOURCE, 'PersistenceMixin', 'prepare_configuration_for_close'), host)
        self.no_escape(lambda: host.closeEvent(host.event))
        self.assert_refused(host)
        self.assertEqual(host.trace, ['safety-lock', 'lock-log', 'zero', 'reset', 'clear', 'serialize', 'toast', 'toast'])
        host.config_store.save_with_startup.assert_not_called()
        self.assertIn('TypeError: config serialization failed', host.warnings[0][0])

    def test_original_exception_context_and_healthy_warning_text_remain_exact(self):
        primary = ValueError('Unicode 错误\nsecond line')
        seen = []
        def error(*args, **kwargs):
            seen.append((sys.exc_info()[1], args, kwargs))
            raise OSError('logger unavailable')
        host = fixture(primary=primary, logger=NS(error=error))
        self.no_escape(lambda: host.closeEvent(host.event))
        self.assertEqual(seen, [(primary, ('Close configuration admission failed',), {'exc_info': True})])
        self.assertEqual(host.warnings, [
            ('关闭保存检查失败：ValueError: Unicode 错误\nsecond line', {'kind': 'warning'}),
            ('关闭已取消，未保存草稿仍保留。恢复控制需要显式重新授权。比赛控制保持锁定。', {'kind': 'warning'})])
        self.assert_refused(host)

    def test_failed_lock_record_and_remaining_neutral_attempts_are_preserved(self):
        host = fixture(primary=ValueError('admission failed'), logger=Mock(error=Mock(side_effect=OSError('logger failed'))))
        def late_lock_log(*args, **kw): host.trace.append('lock-log'); raise RuntimeError('lock log failed')
        host.backend.field_log.emit = late_lock_log
        self.no_escape(lambda: host.closeEvent(host.event))
        self.assert_refused(host)
        self.assertEqual(host.trace[:7], ['safety-lock', 'lock-log', 'zero', 'reset', 'clear', 'toast', 'prepare'])
        self.assertIn('Control lock INCOMPLETE', host.warnings[0][0])
        self.assertIn('RuntimeError: lock log failed', host.warnings[0][0])
        self.assertIn('Control lock INCOMPLETE', host.warnings[-1][0])
        self.assertNotIn('比赛控制保持锁定。', host.warnings[-1][0])

    def test_refused_then_accepted_retry_does_not_start_shutdown_early(self):
        host = fixture(primary=ValueError('admission failed'), logger=Mock(error=Mock(side_effect=OSError('logger failed'))))
        self.no_escape(lambda: host.closeEvent(host.event))
        self.assert_refused(host)
        host.prepare_configuration_for_close = lambda: True
        host.event = Event()
        host.closeEvent(host.event)
        self.assertFalse(host.event.accepted)
        self.assertEqual(host.trace.count('begin'), 1)
        self.assertTrue(host._window_lifecycle.closing)
        self.assertEqual(host.backend.safety.control_state.value, 'LOCKED')

    def test_false_admission_without_exception_uses_only_cancellation_warning(self):
        host = fixture(prepare_result=False)
        host.closeEvent(host.event)
        self.assert_refused(host)
        host.logger.error.assert_not_called()
        self.assertEqual(len(host.warnings), 1)
        self.assertIn('关闭已取消', host.warnings[0][0])

    def test_no_save_required_admission_adds_no_new_revocation(self):
        for primary in (None, ValueError('injected unexpected admission failure')):
            with self.subTest(failed=primary is not None):
                host = fixture(primary=primary, requires_save=False, prepare_result=True,
                               logger=Mock(error=Mock(side_effect=OSError('logger failed'))))
                token = host.backend.safety._qualification
                results = []
                self.no_escape(lambda: results.append(host._admit_window_close()))
                self.assertEqual(results, [primary is None])
                self.assertIs(host.backend.safety._qualification, token)
                self.assertEqual(host.backend.safety.control_state.value, 'QUALIFICATION')
                self.assertNotIn('safety-lock', host.trace)
                self.assertNotIn('zero', host.trace)
                self.assertFalse(host._window_lifecycle.closing)

    def test_primary_process_control_retains_identity_prefix_and_no_logging(self):
        for failure in (KeyboardInterrupt('stop'), SystemExit('stop')):
            with self.subTest(kind=type(failure).__name__):
                host = fixture(primary=failure)
                with self.assertRaises(type(failure)) as caught: host.closeEvent(host.event)
                self.assertIs(caught.exception, failure)
                self.assertEqual(host.trace, ['safety-lock', 'lock-log', 'zero', 'reset', 'clear', 'prepare'])
                self.assertTrue(host.event.accepted)
                self.assertFalse(host._window_lifecycle.closing)
                self.assertEqual(host.backend.safety.control_state.value, 'LOCKED')
                host.logger.error.assert_not_called()

    def test_logger_keyboard_interrupt_retains_identity_without_warning_or_ignore(self):
        failure = KeyboardInterrupt('logger stop')
        host = fixture(primary=ValueError('admission failed'), logger=Mock(error=Mock(side_effect=failure)))
        with self.assertRaises(KeyboardInterrupt) as caught: host.closeEvent(host.event)
        self.assertIs(caught.exception, failure)
        self.assertEqual(host.warnings, [])
        self.assertTrue(host.event.accepted)
        self.assertFalse(host._window_lifecycle.closing)
        self.assertEqual(host.backend.safety.control_state.value, 'LOCKED')

    def test_formatter_and_toast_failures_keep_existing_propagation_boundary(self):
        for failure in (ValueError('format stop'), SystemExit('format stop')):
            with self.subTest(formatter=type(failure).__name__):
                class BrokenTextError(Exception):
                    def __str__(self): raise failure
                host = fixture(primary=BrokenTextError())
                with self.assertRaises(type(failure)) as caught: host.closeEvent(host.event)
                self.assertIs(caught.exception, failure)
                self.assertTrue(host.event.accepted)
                self.assertEqual(host.warnings, [])
                self.assertFalse(host._window_lifecycle.closing)
        for failure in (OSError('toast stop'), KeyboardInterrupt('toast stop')):
            with self.subTest(toast=type(failure).__name__):
                host = fixture(primary=ValueError('admission failed'))
                host.toast = Mock(side_effect=failure)
                with self.assertRaises(type(failure)) as caught: host.closeEvent(host.event)
                self.assertIs(caught.exception, failure)
                self.assertTrue(host.event.accepted)
                self.assertEqual(host.toast.call_count, 1)
                self.assertFalse(host._window_lifecycle.closing)

    def test_save_requirement_lookup_and_preparation_warning_remain_outside_guard(self):
        failure = OSError('lookup failed')
        host = fixture(primary=ValueError('admission failed'))
        type(host).configuration_close_requires_save = property(lambda self: (_ for _ in ()).throw(failure))
        with self.assertRaises(OSError) as caught: host.closeEvent(host.event)
        self.assertIs(caught.exception, failure)
        self.assertEqual(host.trace, [])
        self.assertEqual(host.backend.safety.control_state.value, 'QUALIFICATION')
        host = fixture(primary=ValueError('admission failed'))
        host.control.reset_inputs = Mock(side_effect=ValueError('reset failed'))
        host.toast = Mock(side_effect=failure)
        with self.assertRaises(OSError) as caught: host.closeEvent(host.event)
        self.assertIs(caught.exception, failure)
        self.assertNotIn('prepare', host.trace)
        self.assertEqual(host.backend.safety.control_state.value, 'LOCKED')
        self.assertTrue(host.event.accepted)
        host.logger.error.assert_not_called()

if __name__ == '__main__': unittest.main(verbosity=2)
