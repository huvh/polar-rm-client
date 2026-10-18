"""Stop failure records cannot interrupt independent cleanup on ordinary formatting errors."""
import ast
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rm_client
REPO = Path(rm_client.__file__).resolve().parent.parent
from rm_client import emergency_actions as actions

class BrokenTextError(Exception):
    def __init__(self, formatter=None):
        super().__init__('original operation failed')
        self.formatter = formatter if formatter is not None else ValueError('formatting failed')
    def __str__(self):
        raise self.formatter

def focus_type():
    source = REPO / 'rm_client/ui/polar_app.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PolarRMWindow')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'focusOutEvent')
    class Base:
        def focusOutEvent(self, event):
            self.trace.append('qt-focus')
    node = ast.ClassDef(name='Host', bases=[ast.Name(id='Base', ctx=ast.Load())], keywords=[], body=[method], decorator_list=[])
    scope = dict(vars(actions), Base=Base)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), 'exec'), scope)
    return scope['Host']

def fixture(failures=None):
    failures = failures or {}
    host = focus_type()()
    host.trace, host.warnings = [], []
    host.state, host.registry = object(), object()
    host.student_ui = NS(dragging='held')
    host.toast = lambda message, **kw: host.warnings.append((message, kw))
    def action(name, result=None):
        def call(*args, **kw):
            host.trace.append(name)
            if name in failures:
                raise failures[name]
            return result
        return call
    host.cancel_quick_action_wheel = action('radial')
    host.control = NS(reset_inputs=action('reset'), clear_pending=action('clear'),
        release_all=action('release'), release_direct_dt7=action('dt7'),
        release_custom_controller=action('cc'), mock_output=False)
    host.backend = NS(trigger_estop=action('estop', (True, '')), lock_control=action('lock'),
        mqtt=NS(mock_output=True, publish_estop_zero=action('zero', (True, ''))))
    return host

def invoke(host, mode):
    if mode == 'focus':
        return host.focusOutEvent(object())
    if mode == 'estop':
        return actions.request_emergency_stop(host.backend, host.control)
    return actions.request_control_lock(host.backend, host.control, host.backend.mqtt.publish_estop_zero)


def actual_manager(host, *, errors=None):
    from rm_client.backend.safety import OfficialSafety
    errors = errors or {}
    source = REPO / 'rm_client/backend/manager.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BackendManager')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {'trigger_estop', 'lock_control'}]
    scope = {'time': time}
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), str(source), 'exec'), scope)
    safety = OfficialSafety()
    safety.begin_qualification({'kmc_heartbeat'})
    safety.input_clear_hook = lambda reason: host.trace.append('safety:' + reason)
    def action(name, result=None):
        def call(*args, **kw):
            host.trace.append(name)
            if name in errors:
                raise errors[name]
            return result
        return call
    manager = NS(safety=safety, controller_angles=NS(disarm=action('angle-disarm')),
        mqtt=NS(publish_estop_zero=action('backend-zero', (True, ''))), _km_seq=0,
        serial=NS(request_estop=action('serial-estop')), polar=NS(request_estop=action('polar-estop')))
    def emit(event, **kwargs):
        return action('log:' + event)()
    manager.field_log = NS(emit=emit)
    manager.trigger_estop = MethodType(scope['trigger_estop'], manager)
    manager.lock_control = MethodType(scope['lock_control'], manager)
    host.backend = manager
    return manager


class EmergencyFormattingTests(unittest.TestCase):
    def no_escape(self, callback):
        result = error = None
        try:
            result = callback()
        except Exception as caught:
            error = caught
        self.assertIsNone(error, 'ordinary diagnostic formatting escaped its cleanup owner')
        return result

    def assert_record(self, record, operation, kind='BrokenTextError', message='<unprintable exception>'):
        self.assertEqual((record.operation, record.error_type, record.message), (operation, kind, message))

    def test_estop_each_failure_keeps_original_type_and_remaining_input_attempts(self):
        cases = [('estop', {}, ['estop', 'lock', 'reset', 'clear'], 'backend E-stop'),
            ('lock', {'estop': OSError('early')}, ['estop', 'lock', 'reset', 'clear'], 'fallback control lock'),
            ('reset', {}, ['estop', 'reset', 'clear'], 'input reset'),
            ('clear', {}, ['estop', 'reset', 'clear'], 'pending input clear')]
        for stage, prior, expected, operation in cases:
            with self.subTest(stage=stage):
                host = fixture({**prior, stage: BrokenTextError()})
                result = self.no_escape(lambda: invoke(host, 'estop'))
                self.assertEqual(host.trace, expected)
                self.assert_record(result.failures[-1], operation)
                self.assertIn('<unprintable exception>', result.message)

    def test_control_lock_each_failure_keeps_zero_reset_and_clear_independent(self):
        for stage, operation in [('lock', 'control lock'), ('zero', 'neutral publication'),
                                 ('reset', 'input reset'), ('clear', 'pending input clear')]:
            with self.subTest(stage=stage):
                host = fixture({stage: BrokenTextError()})
                result = self.no_escape(lambda: invoke(host, 'lock'))
                self.assertEqual(host.trace, ['lock', 'zero', 'reset', 'clear'])
                self.assert_record(result.failures[0], operation)
                self.assertEqual(result.status, 'Control lock INCOMPLETE' if stage == 'lock' else 'Match control LOCKED')

    def test_focus_each_failure_preserves_fallback_order_and_qt_finally(self):
        for stage in ['lock', 'radial', 'release', 'reset', 'dt7', 'cc', 'zero', 'clear']:
            with self.subTest(stage=stage):
                prior = {'release': OSError('release failed')} if stage in {'reset', 'dt7', 'cc'} else {}
                host = fixture({**prior, stage: BrokenTextError()})
                self.no_escape(lambda: invoke(host, 'focus'))
                expected = ['lock', 'radial']
                if stage != 'radial':
                    expected += ['release']
                if stage in {'radial', 'release', 'reset', 'dt7', 'cc'}:
                    expected += ['reset', 'dt7', 'cc']
                self.assertEqual(host.trace, expected + ['zero', 'clear', 'qt-focus'])
                self.assertEqual(host.student_ui.dragging, '')
                self.assertIn('BrokenTextError: <unprintable exception>', host.warnings[0][0])

    def test_all_estop_failures_keep_every_record_in_order(self):
        host = fixture({name: BrokenTextError() for name in ['estop', 'lock', 'reset', 'clear']})
        result = self.no_escape(lambda: invoke(host, 'estop'))
        self.assertEqual(host.trace, ['estop', 'lock', 'reset', 'clear'])
        self.assertEqual([f.operation for f in result.failures], ['backend E-stop', 'fallback control lock', 'input reset', 'pending input clear'])
        self.assertTrue(all(f.error_type == 'BrokenTextError' for f in result.failures))
        self.assertEqual(result.status, 'E-STOP REQUEST INCOMPLETE')

    def test_all_focus_failures_keep_every_record_without_claiming_lock_success(self):
        host = fixture({name: BrokenTextError() for name in ['lock', 'release', 'reset', 'dt7', 'cc', 'zero', 'clear']})
        result = self.no_escape(lambda: actions.request_focus_loss(host.backend, host.control,
            lambda: host.control.release_all(host.state, host.registry), host.backend.mqtt.publish_estop_zero))
        self.assertEqual(host.trace, ['lock', 'release', 'reset', 'dt7', 'cc', 'zero', 'clear'])
        self.assertEqual([f.operation for f in result.failures], ['control lock', 'input release', 'fallback input reset',
            'DT7 neutral release', 'custom controller neutral release', 'neutral publication', 'pending input clear'])
        self.assertEqual(result.status, 'Focus-loss control lock INCOMPLETE')

    def test_healthy_paths_keep_exact_status_and_no_failure_records(self):
        for mode, expected, status in [('estop', ['estop', 'reset', 'clear'], 'E-STOP ACTIVE'),
                ('lock', ['lock', 'zero', 'reset', 'clear'], 'Match control LOCKED')]:
            with self.subTest(mode=mode):
                host = fixture()
                result = invoke(host, mode)
                self.assertEqual(host.trace, expected)
                self.assertEqual((result.status, result.failures, result.message), (status, (), status))
        host = fixture()
        invoke(host, 'focus')
        self.assertEqual(host.trace, ['lock', 'radial', 'release', 'zero', 'clear', 'qt-focus'])
        self.assertEqual(host.warnings, [])

    def test_printable_message_is_exact_and_formatted_once_in_active_operation_context(self):
        observations = []
        class PrintableError(Exception):
            def __str__(self):
                observations.append(sys.exc_info()[1] is self)
                return 'Unicode 错误\nsecond line'
        host = fixture({'reset': PrintableError()})
        result = invoke(host, 'estop')
        self.assert_record(result.failures[0], 'input reset', 'PrintableError', 'Unicode 错误\nsecond line')
        self.assertEqual(observations, [True])
        self.assertEqual(result.message, 'E-STOP ACTIVE; incomplete: input reset: PrintableError: Unicode 错误\nsecond line')
        self.assertEqual(observations, [True])

    def test_primary_type_is_captured_before_message_side_effect(self):
        class ChangedError(Exception):
            pass
        class OriginalError(Exception):
            def __str__(self):
                self.__class__ = ChangedError
                return 'kept'
        error = OriginalError()
        host = fixture({'reset': error})
        result = invoke(host, 'estop')
        self.assert_record(result.failures[0], 'input reset', 'OriginalError', 'kept')
        self.assertIs(type(error), ChangedError)

    def test_non_string_str_result_uses_same_bounded_fallback(self):
        class NonStringError(Exception):
            def __str__(self):
                return 17
        host = fixture({'reset': NonStringError()})
        result = self.no_escape(lambda: invoke(host, 'estop'))
        self.assert_record(result.failures[0], 'input reset', 'NonStringError')
        self.assertEqual(host.trace, ['estop', 'reset', 'clear'])

    def test_formatter_failure_is_not_recursively_rendered_or_retried(self):
        class PoisonFormatter(Exception):
            def __str__(self):
                raise AssertionError('secondary formatter must not run')
        error = BrokenTextError(PoisonFormatter())
        count = []
        class CountingError(BrokenTextError):
            def __str__(self):
                count.append('render')
                return super().__str__()
        host = fixture({'reset': CountingError(error.formatter)})
        result = self.no_escape(lambda: invoke(host, 'estop'))
        self.assert_record(result.failures[0], 'input reset', 'CountingError')
        self.assertEqual(count, ['render'])

    def test_rejected_zero_reason_and_estop_false_status_remain_unchanged(self):
        host = fixture()
        host.backend.mqtt.publish_estop_zero = lambda: (False, 'offline')
        result = invoke(host, 'lock')
        self.assert_record(result.failures[0], 'neutral publication', 'Rejected', 'offline')
        host = fixture()
        host.backend.trigger_estop = lambda: (False, 'offline')
        result = invoke(host, 'estop')
        self.assertEqual((result.status, result.failures), ('E-STOP ACTIVE (offline)', ()))

    def test_operation_baseexception_preserves_identity_and_prefix(self):
        for mode, stage, expected in [('estop', 'estop', ['estop']), ('lock', 'zero', ['lock', 'zero']),
                ('focus', 'release', ['lock', 'radial', 'release', 'qt-focus'])]:
            for error in [KeyboardInterrupt(), SystemExit(23)]:
                with self.subTest(mode=mode, kind=type(error).__name__):
                    host = fixture({stage: error})
                    with self.assertRaises(BaseException) as caught:
                        invoke(host, mode)
                    self.assertIs(caught.exception, error)
                    self.assertEqual(host.trace, expected)

    def test_formatter_baseexception_preserves_identity_and_prefix(self):
        for mode, stage, expected in [('estop', 'estop', ['estop']), ('lock', 'zero', ['lock', 'zero']),
                ('focus', 'release', ['lock', 'radial', 'release', 'qt-focus'])]:
            for error in [KeyboardInterrupt(), SystemExit(24)]:
                with self.subTest(mode=mode, kind=type(error).__name__):
                    host = fixture({stage: BrokenTextError(error)})
                    with self.assertRaises(BaseException) as caught:
                        invoke(host, mode)
                    self.assertIs(caught.exception, error)
                    self.assertEqual(host.trace, expected)

    def test_actual_focus_toast_failure_still_runs_qt_after_completed_cleanup(self):
        host = fixture({'release': BrokenTextError()})
        error = OSError('toast failed')
        def toast(*args, **kwargs):
            raise error
        host.toast = toast
        with self.assertRaises(Exception) as caught:
            invoke(host, 'focus')
        self.assertIs(caught.exception, error)
        self.assertEqual(host.trace, ['lock', 'radial', 'release', 'reset', 'dt7', 'cc', 'zero', 'clear', 'qt-focus'])
        self.assertEqual(host.student_ui.dragging, '')

    def test_actual_manager_early_stop_failure_reaches_fallback_real_safety_lock(self):
        from rm_client.backend.safety import ControlState
        host = fixture()
        manager = actual_manager(host, errors={'angle-disarm': BrokenTextError()})
        result = self.no_escape(lambda: invoke(host, 'estop'))
        self.assertEqual(host.trace, ['angle-disarm', 'safety:E-stop request failed', 'log:control_lock', 'reset', 'clear'])
        self.assertIs(manager.safety.control_state, ControlState.LOCKED)
        self.assertFalse(manager.safety.estop_active)
        self.assertIsNone(manager.safety._qualification)
        self.assertEqual(result.status, 'E-STOP REQUEST INCOMPLETE')

    def test_actual_manager_late_stop_error_keeps_existing_estop_and_transport_attempts(self):
        from rm_client.backend.safety import ControlState
        host = fixture()
        manager = actual_manager(host, errors={'log:estop': BrokenTextError()})
        result = self.no_escape(lambda: invoke(host, 'estop'))
        self.assertEqual(host.trace, ['angle-disarm', 'backend-zero', 'safety:E-stop triggered', 'serial-estop', 'polar-estop',
            'log:estop', 'safety:E-stop request failed', 'log:control_lock', 'reset', 'clear'])
        self.assertTrue(manager.safety.estop_active)
        self.assertIs(manager.safety.control_state, ControlState.LOCKED)
        self.assertIsNone(manager.safety._qualification)
        self.assertEqual(result.status, 'E-STOP REQUEST INCOMPLETE')

    def test_actual_manager_lock_already_revoked_before_bad_diagnostic_and_cleanup(self):
        from rm_client.backend.safety import ControlState
        host = fixture()
        manager = actual_manager(host, errors={'log:control_lock': BrokenTextError()})
        result = self.no_escape(lambda: invoke(host, 'lock'))
        self.assertEqual(host.trace, ['safety:operator lock', 'log:control_lock', 'backend-zero', 'reset', 'clear'])
        self.assertIs(manager.safety.control_state, ControlState.LOCKED)
        self.assertIsNone(manager.safety._qualification)
        self.assertEqual(result.status, 'Control lock INCOMPLETE')

if __name__ == '__main__':
    unittest.main(verbosity=2)
