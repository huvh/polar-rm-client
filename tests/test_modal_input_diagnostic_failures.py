"""Modal ownership keeps neutral attempts and its failed-cleanup latch (inert)."""
from pathlib import Path
import ast
import io
import logging
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
# External candidate runner already supplies repository import paths.
sys.path.insert(0, str(ROOT))
from rm_client.backend.manager import BackendManager
from rm_client.backend.safety import OfficialSafety, ControlState
from rm_client.ui.overlay_coordinator import OverlayCoordinator, OverlayKind
from rm_client.ui.polar.mixins.input_dispatch_mixin import InputDispatchMixin

MODULE = 'rm_client.ui.polar.mixins.input_dispatch_mixin'


class ModalInputDiagnosticFailureTests(unittest.TestCase):
    def host(self, failed=()):
        host = InputDispatchMixin()
        trace = []
        errors = {name: RuntimeError(name + ' failed') for name in failed}
        for error in errors.values():
            def note(value, error=error):
                error.__notes__ = [*getattr(error, '__notes__', ()), value]
            error.add_note = note  # Capability control also works under Python 3.10.
        def action(name):
            def call(*args, **kwargs):
                trace.append(name)
                if name in errors:
                    raise errors[name]
            return call
        class Mqtt:
            @property
            def mock_output(self):
                action('mode')()
                return True
        host.control = NS(mock_output=False, reset_inputs=action('reset'),
            send_from_state=action('publish'), release_direct_dt7=action('dt7'),
            release_custom_controller=action('custom'), clear_pending=action('clear'),
            last_command='old command')
        safety = OfficialSafety()
        safety.arm_match({'core_kmc'})
        manager = object.__new__(BackendManager)
        manager.safety = safety
        manager.field_log = NS(emit=lambda *args, **kwargs: None)
        def lock(reason):
            action('lock')()
            BackendManager.lock_control(manager, reason)
        host.backend = NS(mqtt=Mqtt(), lock_control=lock, lifecycle_pending=False)
        host.state, host.registry = object(), object()
        host._modal_input_clear_pending = False
        host._control_mouse_point = 'old mouse'
        host._combat_input_was_allowed = True
        host._escape_menu_visible = False
        host.escape_menu_visible = False
        host.student_ui = NS(visible=False)
        host.home_visible = host.gui_visible = host.economy_visible = False
        host.hero_deploy_ui = NS(visible=False)
        host.match_chat = NS(input_open=False)
        host.quick_action_wheel = NS(active=False)
        host.overlay_coordinator = OverlayCoordinator(on_input_claimed=host._neutralize_modal_inputs)
        return host, trace, errors, safety

    def call(self, action):
        try:
            return action(), None
        except Exception as error:
            return None, error

    def expected(self, first):
        values = ['mode', 'reset']
        if first not in ('mode', 'reset'):
            values.append('publish')
        return values + ['dt7', 'custom', 'clear', 'lock']

    def test_success_keeps_existing_order_without_new_backend_lock_or_failure_latch(self):
        host, trace, _, safety = self.host()
        with patch(MODULE + '.logging.getLogger') as lookup:
            self.assertIsNone(host._neutralize_modal_inputs())
        lookup.assert_not_called()
        self.assertEqual(trace, ['mode', 'reset', 'publish', 'dt7', 'custom'])
        self.assertFalse(host._modal_input_blocked())
        self.assertEqual(safety.control_state, ControlState.MATCH_ARMED)
        self.assertIsNone(host._control_mouse_point)
        self.assertFalse(host._combat_input_was_allowed)

    def test_healthy_logging_preserves_original_exception_identity_and_absorbed_return(self):
        host, trace, errors, safety = self.host(('publish', 'dt7', 'custom'))
        seen = []
        def report(*args, **kwargs):
            seen.append((args, kwargs, sys.exc_info()[1]))
        with patch(MODULE + '.logging.getLogger') as lookup:
            lookup.return_value.exception.side_effect = report
            result = host._neutralize_modal_inputs()
        self.assertIsNone(result)  # The established API does not rethrow ordinary cleanup errors.
        self.assertEqual([value[2] for value in seen], [errors[name] for name in ('publish', 'dt7', 'custom')])
        self.assertTrue(all(args == ('Modal input neutralization failed',) and kwargs == {} for args, kwargs, _ in seen))
        self.assertEqual(trace, self.expected('publish'))
        self.assertTrue(host._modal_input_clear_pending)
        self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_logger_emit_failure_at_each_operation_cannot_skip_remaining_cleanup(self):
        for step in ('mode', 'reset', 'publish', 'dt7', 'custom', 'clear', 'lock'):
            with self.subTest(step=step):
                host, trace, errors, safety = self.host((step,) if step not in ('clear', 'lock') else ('publish', step))
                with patch(MODULE + '.logging.getLogger') as lookup:
                    lookup.return_value.exception.side_effect = OSError('sink failed')
                    result, error = self.call(host._neutralize_modal_inputs)
                self.assertIsNone(error)
                self.assertIsNone(result)
                self.assertEqual(trace, self.expected(step))
                self.assertTrue(host._modal_input_clear_pending)
                self.assertFalse(host._modal_input_clearing)
                for primary in errors.values():
                    self.assertIn('OSError: sink failed', ' '.join(getattr(primary, '__notes__', ())))
                if step != 'lock':
                    self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_logger_lookup_failure_cannot_skip_neutral_or_failure_latch(self):
        host, trace, errors, safety = self.host(('reset',))
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            _, error = self.call(host._neutralize_modal_inputs)
        self.assertIsNone(error)
        self.assertEqual(trace, self.expected('reset'))
        self.assertTrue(host._modal_input_clear_pending)
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertIn('lookup failed', errors['reset'].__notes__[0])

    def test_standard_closed_stderr_cannot_skip_cleanup_or_lock(self):
        host, trace, _, safety = self.host(('reset',))
        stream = io.StringIO(); stream.close()
        logger = logging.Logger('closed in-memory stderr')
        logger.addHandler(logging.StreamHandler(stream))
        with (patch(MODULE + '.logging.getLogger', return_value=logger),
              patch.object(sys, 'stderr', stream), patch.object(logging, 'raiseExceptions', True)):
            _, error = self.call(host._neutralize_modal_inputs)
        self.assertIsNone(error)
        self.assertEqual(trace, self.expected('reset'))
        self.assertTrue(host._modal_input_clear_pending)
        self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_overlay_closure_does_not_remove_failed_cleanup_input_gate(self):
        for begin, finish in ((lambda c: c.request_modal(OverlayKind.CLICKGUI), lambda c: c.close_modal()),
                              (lambda c: c.begin_chat(), lambda c: c.end_chat()),
                              (lambda c: c.begin_radial(), lambda c: c.end_radial())):
            with self.subTest(begin=begin):
                host, trace, _, safety = self.host(('reset',))
                self.assertTrue(host.combat_control_input_allowed())
                with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
                    _, error = self.call(lambda: begin(host.overlay_coordinator))
                self.assertIsNone(error)
                self.assertTrue(host.overlay_coordinator.blocks_combat_input)
                finish(host.overlay_coordinator)
                self.assertFalse(host.overlay_coordinator.blocks_combat_input)
                self.assertFalse(host.combat_control_input_allowed())
                self.assertTrue(host._modal_input_clear_pending)
                self.assertEqual(trace, self.expected('reset'))
                self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_existing_pending_latch_prevents_implicit_retry(self):
        host, trace, _, _ = self.host()
        host._modal_input_clear_pending = True
        with patch(MODULE + '.logging.getLogger') as log:
            self.assertIsNone(host._neutralize_modal_inputs())
        self.assertEqual(trace, [])
        self.assertTrue(host._modal_input_clear_pending)
        log.assert_not_called()

    def test_lock_callback_clearing_pending_cannot_erase_modal_failure_latch(self):
        host, trace, _, safety = self.host(('publish',))
        lock = host.backend.lock_control
        def callback(reason):
            lock(reason)
            host._modal_input_clear_pending = False
        host.backend.lock_control = callback
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            _, error = self.call(host._neutralize_modal_inputs)
        self.assertIsNone(error)
        self.assertEqual(trace, self.expected('publish'))
        self.assertTrue(host._modal_input_clear_pending)
        self.assertEqual(safety.control_state, ControlState.LOCKED)

    def test_reentrant_diagnostic_callback_does_not_repeat_independent_actions(self):
        host, trace, _, _ = self.host(('reset',))
        def report(*args, **kwargs):
            host._neutralize_modal_inputs()
            raise OSError('sink failed')
        with patch(MODULE + '.logging.getLogger') as lookup:
            lookup.return_value.exception.side_effect = report
            _, error = self.call(host._neutralize_modal_inputs)
        self.assertIsNone(error)
        self.assertEqual(trace, self.expected('reset'))
        self.assertTrue(host._modal_input_clear_pending)

    def test_missing_or_raising_note_capability_cannot_cancel_cleanup(self):
        class NoNotes(RuntimeError):
            add_note = None
        class BrokenNotes(RuntimeError):
            def add_note(self, value):
                raise ValueError('notes failed')
        class BrokenLookup(RuntimeError):
            @property
            def add_note(self):
                raise ValueError('note lookup failed')
        for exception_type in (NoNotes, BrokenNotes, BrokenLookup):
            with self.subTest(exception_type=exception_type):
                host, trace, errors, _ = self.host(('reset',))
                primary = errors['reset'] = exception_type('reset failed')
                with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
                    _, error = self.call(host._neutralize_modal_inputs)
                self.assertIsNone(error)
                self.assertIs(errors['reset'], primary)
                self.assertEqual(trace, self.expected('reset'))
                self.assertTrue(host._modal_input_clear_pending)

    def test_unprintable_diagnostic_cannot_cancel_cleanup(self):
        class Failure(RuntimeError):
            def __str__(self):
                raise ValueError('format failed')
        host, trace, _, _ = self.host(('reset',))
        with patch(MODULE + '.logging.getLogger', side_effect=Failure()):
            _, error = self.call(host._neutralize_modal_inputs)
        self.assertIsNone(error)
        self.assertEqual(trace, self.expected('reset'))
        self.assertTrue(host._modal_input_clear_pending)

    def test_operation_baseexception_keeps_immediate_propagation_and_finally_flag(self):
        host, trace, errors, safety = self.host(('reset',))
        failure = errors['reset'] = KeyboardInterrupt('stop reset')
        with patch(MODULE + '.logging.getLogger') as lookup:
            with self.assertRaises(BaseException) as caught:
                host._neutralize_modal_inputs()
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['mode', 'reset'])
        self.assertFalse(host._modal_input_clearing)
        self.assertFalse(host._modal_input_clear_pending)
        self.assertEqual(safety.control_state, ControlState.MATCH_ARMED)
        lookup.assert_not_called()

    def test_logger_baseexception_keeps_immediate_propagation_and_finally_flag(self):
        host, trace, _, _ = self.host(('reset',))
        failure = SystemExit('stop logging')
        with patch(MODULE + '.logging.getLogger', side_effect=failure):
            with self.assertRaises(BaseException) as caught:
                host._neutralize_modal_inputs()
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['mode', 'reset'])
        self.assertFalse(host._modal_input_clearing)
        self.assertFalse(host._modal_input_clear_pending)

    def test_note_baseexception_is_not_swallowed(self):
        host, trace, errors, _ = self.host(('reset',))
        failure = KeyboardInterrupt('stop notes')
        def note(value):
            raise failure
        errors['reset'].add_note = note
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            with self.assertRaises(BaseException) as caught:
                host._neutralize_modal_inputs()
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, ['mode', 'reset'])
        self.assertFalse(host._modal_input_clearing)

    def test_real_radial_admission_has_no_prior_backend_revocation(self):
        # Compile only this existing production method; never construct a window.
        # The candidate file can live outside the repository; resolve the import root.
        import rm_client
        window_path = Path(rm_client.__file__).resolve().parent / 'ui/polar_app.py'
        tree = ast.parse(window_path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PolarRMWindow')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'begin_quick_action_wheel')
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), str(window_path), 'exec'), namespace)
        host, trace, _, safety = self.host(('reset',))
        host.registry = NS(get=lambda name: NS(enabled=True))
        host.sync_quick_action_wheel_settings = lambda: None
        host.quick_action_wheel = NS(active=False, open=Mock(), update_pointer=Mock())
        host.frame_scheduler = NS(force=Mock())
        host.width, host.height, host.update = lambda: 100, lambda: 100, Mock()
        seen = []
        callback = host._neutralize_modal_inputs
        def claimed():
            seen.append(safety.control_state)
            callback()
        host.overlay_coordinator.on_input_claimed = claimed
        point = NS(x=lambda: 10, y=lambda: 20)
        with patch(MODULE + '.logging.getLogger', side_effect=OSError('lookup failed')):
            result, error = self.call(lambda: namespace['begin_quick_action_wheel'](host, point))
        self.assertIsNone(error)
        self.assertTrue(result)
        self.assertEqual(seen, [ControlState.MATCH_ARMED])
        self.assertEqual(trace, self.expected('reset'))
        self.assertEqual(safety.control_state, ControlState.LOCKED)
        self.assertTrue(host._modal_input_clear_pending)
        host.quick_action_wheel.open.assert_called_once_with(10, 20, 100, 100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
