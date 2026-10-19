"""Actual calibration action route, temporary files and inert file-failure injection."""
from __future__ import annotations
import ast
from dataclasses import asdict
import errno
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.calibration import CameraCalibrationManager, CalibrationProfile
from rm_client.configuration.commands import ConfigCommandKind, resolve_config_command

def method(path, name, namespace):
    nodes = [n for n in ast.walk(ast.parse(path.read_text()))
             if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(nodes) == 1
    module = ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        nodes[0]], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace[name]

class CalibrationExportErrorTests(unittest.TestCase):

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / '同济自瞄' / 'sp_vision_25' / 'configs'
        self.directory.mkdir(parents=True)
        self.base = self.directory / 'demo.yaml'
        self.template = 'camera_matrix: [1]\ndistort_coeffs: [0]\ndevice: CPU\n'
        self.base.write_text(self.template)
        self.target = self.directory / 'polar_webcam.yaml'
        self.manager = CameraCalibrationManager(self.root)
        self.profile = CalibrationProfile(
            'original', 960, 540, 9, 6, 25,
            [800.0, 0.0, 480.0, 0.0, 800.0, 270.0, 0.0, 0.0, 1.0],
            [0.0] * 5, 0.42, 12)
        self.manager.profile = self.profile
        self.events = []
        self.host = SimpleNamespace(
            calibration=self.manager, registry=SimpleNamespace(get=lambda _: None),
            setting_mode=lambda m, n, default: default,
            get_setting_number=lambda m, n, default: default,
            toast=lambda message, **kwargs: self.events.append((message, kwargs)),
            handle_student_config_action=lambda _: False,
            handle_student_action=lambda *_: False,
            _lifecycle_owns_input=lambda: False, invalidate_gui_cache=lambda: None)

        def unexpected(*args, **kwargs):
            raise AssertionError('unrelated action')
        for name in ('handle_qualification_action', '_apply_safety_command',
                     '_run_link_diagnostic', '_apply_angle_command', '_apply_profile_command',
                     '_preview_elimination_command', '_open_deploy_command', '_apply_lob_command'):
            setattr(self.host, name, unexpected)
        namespace = dict(ConfigCommandKind=ConfigCommandKind, resolve_config_command=resolve_config_command)
        path = ROOT / 'rm_client/ui/polar/mixins/config_actions_mixin.py'
        for name in ('handle_calibration_action', '_execute_config_command', 'handle_config_action'):
            setattr(self.host, name, MethodType(method(path, name, namespace), self.host))
        path = ROOT / 'rm_client/ui/polar/mixins/input_dispatch_mixin.py'
        handler = method(path, '_on_action_config_action', {})
        namespace = dict(_DISPATCH_HANDLERS={'config_action': handler}, _GUI_CACHE_INVALIDATE_ACTIONS=set())
        self.host.dispatch = MethodType(method(path, 'dispatch', namespace), self.host)

    def observe(self):
        try:
            self.host.dispatch('config_action', 'Export Tongji YAML', None, 1, None)
            return None
        except Exception as error:
            return error

    def assert_warning(self, error):
        self.assertIsNone(error, repr(error))
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][1], {'kind': 'warning'})
        self.assertEqual(self.events[0][0], self.manager.last_error)
        self.assertTrue(self.manager.last_error)
        self.assertIs(self.manager.profile, self.profile)
        self.assertEqual(self.base.read_text(), self.template)

    def test_target_directory_failure_reaches_existing_ui_warning(self):
        self.target.mkdir()
        self.assert_warning(self.observe())

    def test_template_directory_failure_reaches_existing_ui_warning(self):
        self.base.unlink()
        self.base.mkdir()
        error = self.observe()
        self.assertIsNone(error, repr(error))
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][1], {'kind': 'warning'})
        self.assertFalse(self.target.exists())
        self.assertTrue(self.base.is_dir())
        self.assertIs(self.manager.profile, self.profile)

    def test_target_permission_failure_reaches_existing_ui_warning(self):
        real = Path.write_text
        failure = PermissionError(errno.EACCES, 'target denied', str(self.target))

        def write(path, *args, **kwargs):
            if path == self.target:
                raise failure
            return real(path, *args, **kwargs)
        with patch.object(Path, 'write_text', write):
            error = self.observe()
        self.assert_warning(error)
        self.assertFalse(self.target.exists())

    def test_template_stat_failure_reaches_existing_ui_warning(self):
        real = Path.exists
        failure = PermissionError(errno.EACCES, 'template stat denied', str(self.base))

        def exists(path):
            if path == self.base:
                raise failure
            return real(path)
        with patch.object(Path, 'exists', exists):
            error = self.observe()
        self.assert_warning(error)

    def test_fallback_profile_stat_failure_reaches_existing_ui_warning(self):
        self.manager.profile = None
        path = self.manager.profile_path('polar_webcam')
        real = Path.exists
        failure = PermissionError(errno.EACCES, 'profile stat denied', str(path))

        def exists(value):
            if value == path:
                raise failure
            return real(value)
        with patch.object(Path, 'exists', exists):
            error = self.observe()
        self.assertIsNone(error, repr(error))
        self.assertEqual(self.events, [(str(failure), {'kind': 'warning'})])
        self.assertIsNone(self.manager.profile)
        self.assertFalse(self.target.exists())

    def test_missing_template_already_warns_without_mutation(self):
        self.base.unlink()
        self.assertIsNone(self.observe())
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][1], {'kind': 'warning'})
        self.assertIs(self.manager.profile, self.profile)
        self.assertFalse(self.target.exists())

    def test_healthy_action_exports_existing_profile_without_changing_template(self):
        self.assertIsNone(self.observe())
        self.assertEqual(self.events, [('Tongji YAML exported: polar_webcam.yaml', {})])
        self.assertIn('camera_matrix: [800, 0, 480, 0, 800, 270, 0, 0, 1]', self.target.read_text())
        self.assertEqual(self.base.read_text(), self.template)
        self.assertIs(self.manager.profile, self.profile)
        self.assertEqual(self.manager.last_error, '')

    def test_template_read_permission_failure_keeps_existing_destination(self):
        self.target.write_text('previous destination')
        real = Path.read_text
        failure = PermissionError(errno.EACCES, 'read denied', str(self.base))

        def read(path, *args, **kwargs):
            if path == self.base:
                raise failure
            return real(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            error = self.observe()
        self.assert_warning(error)
        self.assertEqual(self.target.read_text(), 'previous destination')

    def test_partial_write_failure_is_reported_without_promising_atomic_preservation(self):
        self.target.write_text('previous destination')
        real = Path.write_text
        failure = OSError(errno.ENOSPC, 'disk full')

        def write(path, text, *args, **kwargs):
            if path == self.target:
                real(path, 'partial exported prefix', *args, **kwargs)
                raise failure
            return real(path, text, *args, **kwargs)
        with patch.object(Path, 'write_text', write):
            error = self.observe()
        self.assert_warning(error)
        self.assertEqual(self.manager.last_error, str(failure))
        self.assertEqual(self.target.read_text(), 'partial exported prefix')

    def test_successful_fallback_load_remains_published_after_failed_export(self):
        self.manager.profile = None
        profile_path = self.manager.profile_path('polar_webcam')
        saved = json.dumps(asdict(self.profile))
        profile_path.write_text(saved)
        self.target.mkdir()
        self.assertIsNone(self.observe())
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][1], {'kind': 'warning'})
        self.assertIsNot(self.manager.profile, self.profile)
        self.assertEqual(self.manager.profile, self.profile)
        self.assertEqual(profile_path.read_text(), saved)
        self.assertEqual(self.base.read_text(), self.template)

    def test_already_contained_load_read_error_keeps_existing_generic_export_diagnostic(self):
        self.manager.profile = None
        profile_path = self.manager.profile_path('polar_webcam')
        profile_path.write_text(json.dumps(asdict(self.profile)))
        real = Path.read_text
        failure = PermissionError('saved profile unavailable')

        def read(path, *args, **kwargs):
            if path == profile_path:
                raise failure
            return real(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            error = self.observe()
        self.assertIsNone(error)
        self.assertEqual(self.manager.last_error, '没有可导出的标定 profile')
        self.assertEqual(self.events, [('没有可导出的标定 profile', {'kind': 'warning'})])
        self.assertIsNone(self.manager.profile)
        self.assertFalse(self.target.exists())

    def test_healthy_existing_target_overwrite_and_rendering_remain_unchanged(self):
        template = ('camera_matrix: [1]\ncamera_matrix: [leave duplicate]\n'
                    'distort_coeffs: [9]\ndevice: CPU\ndevice: KEEP\ncustom: retained\n')
        self.base.write_text(template)
        self.target.write_text('old destination')
        self.manager.last_error = 'old diagnostic'
        self.assertEqual(self.manager.export_tongji_yaml('polar_webcam', 'GPU'), self.target)
        text = self.target.read_text()
        self.assertIn('camera_matrix: [800, 0, 480, 0, 800, 270, 0, 0, 1]\n'
                      'camera_matrix: [leave duplicate]', text)
        self.assertIn('distort_coeffs: [0, 0, 0, 0, 0]', text)
        self.assertIn('device: GPU\ndevice: KEEP', text)
        self.assertIn('custom: retained', text)
        self.assertIn('R_camera2gimbal: [1, 0, 0, 0, 1, 0, 0, 0, 1]', text)
        self.assertIn('t_camera2gimbal: [0, 0, 0]', text)
        self.assertTrue(text.endswith(
            '# POLAR desktop calibration profile: original\n'
            '# resolution: 960x540, rms_error_px: 0.4200\n'))
        self.assertEqual(self.base.read_text(), template)
        self.assertEqual(self.manager.last_error, '')

    def test_existing_profile_wins_without_reload_or_new_quality_gate(self):
        self.profile.sample_count = 1
        self.profile.rms_error_px = 9
        with patch.object(self.manager, 'load', side_effect=AssertionError('must not reload')):
            result = self.manager.export_tongji_yaml('different_export_name')
        self.assertEqual(result, self.directory / 'different_export_name.yaml')
        self.assertIn('profile: original', result.read_text())
        self.assertIs(self.manager.profile, self.profile)
        self.assertFalse(self.manager.is_valid_for(960, 540))

    def test_raw_export_names_and_existing_template_overwrite_policy_are_preserved(self):
        for name in ('', '相机', '../relative_export', 'demo'):
            with self.subTest(name=name):
                self.base.write_text(self.template)
                expected = self.directory / f'{name}.yaml'
                self.assertEqual(self.manager.export_tongji_yaml(name), expected)
                self.assertIn('profile: original', expected.read_text())
                if name != 'demo':
                    self.assertEqual(self.base.read_text(), self.template)
                else:
                    self.assertNotEqual(self.base.read_text(), self.template)

    def test_missing_destination_parent_is_reported_without_creating_directories(self):
        destination = self.directory / 'missing' / 'profile.yaml'
        try:
            result = self.manager.export_tongji_yaml('missing/profile')
        except OSError as failure:
            self.fail('Filesystem error escaped: ' + str(failure))
        self.assertIsNone(result)
        self.assertTrue(self.manager.last_error)
        self.assertFalse(destination.parent.exists())
        self.assertEqual(self.base.read_text(), self.template)

    def test_no_profile_keeps_existing_warning_and_no_output(self):
        self.manager.profile = None
        self.assertIsNone(self.observe())
        self.assertEqual(self.events, [('没有可导出的标定 profile', {'kind': 'warning'})])
        self.assertFalse(self.target.exists())

    def test_non_os_errors_and_process_control_keep_operation_exception_identity(self):
        for operation, path in (('exists', self.base), ('read_text', self.base), ('write_text', self.target)):
            for failure in (ValueError('invalid'), TypeError('wrong type'),
                            RuntimeError('programming'), KeyboardInterrupt('interrupt'), SystemExit(6)):
                with self.subTest(operation=operation, error=type(failure).__name__):
                    self.manager.last_error = 'previous diagnostic'
                    real = getattr(Path, operation)

                    def perform(value, *args, **kwargs):
                        if value == path:
                            raise failure
                        return real(value, *args, **kwargs)
                    with patch.object(Path, operation, perform), self.assertRaises(type(failure)) as caught:
                        self.manager.export_tongji_yaml('polar_webcam')
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(self.manager.last_error, 'previous diagnostic')
                    self.assertIs(self.manager.profile, self.profile)

    def test_rendering_exception_types_are_not_broadly_absorbed(self):
        for failure in (ValueError('render'), TypeError('render'),
                        KeyboardInterrupt('render'), SystemExit(8)):

            class BadFormat:

                def __format__(self, _):
                    raise failure
            with self.subTest(error=type(failure).__name__):
                self.profile.camera_matrix = [BadFormat()]
                with self.assertRaises(type(failure)) as caught:
                    self.manager.export_tongji_yaml('polar_webcam')
                self.assertIs(caught.exception, failure)
                self.assertFalse(self.target.exists())

    def test_custom_rendering_oserror_remains_outside_file_error_handlers(self):
        failure = OSError('custom formatting I/O failure')

        class BadFormat:

            def __format__(self, _):
                raise failure
        self.profile.camera_matrix = [BadFormat()]
        with self.assertRaises(OSError) as caught:
            self.manager.export_tongji_yaml('polar_webcam')
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.target.exists())

    def test_presentation_failure_is_outside_export_owner_handler(self):
        for succeeds in (False, True):
            with self.subTest(succeeds=succeeds):
                if not succeeds:
                    self.target.mkdir()
                else:
                    self.target.rmdir()
                failure = RuntimeError('toast failed')
                self.host.toast = lambda *args, **kwargs: (_ for _ in ()).throw(failure)
                self.assertIs(self.observe(), failure)
                if succeeds:
                    self.assertTrue(self.target.is_file())
                    self.assertEqual(self.manager.last_error, '')
                else:
                    self.assertTrue(self.manager.last_error)

    def test_template_decode_replacement_and_empty_coefficients_are_not_revalidated(self):
        self.base.write_bytes(b'custom: \xff\n')
        self.profile.camera_matrix = []
        self.profile.distort_coeffs = []
        result = self.manager.export_tongji_yaml('polar_webcam')
        self.assertEqual(result, self.target)
        self.assertIn('custom: �', result.read_text())
        self.assertIn('camera_matrix: []', result.read_text())
        self.assertIn('distort_coeffs: []', result.read_text())
if __name__ == '__main__':
    unittest.main()
