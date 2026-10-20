"""Persistent calibration values are checked before live-profile publication.

Only temporary files, the pure owner, and selected caller ASTs execute. The
solve producer uses an explicit inert cv2 result double; no native module loads.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'rm_client').is_dir():
    ROOT = Path('/workspace/scratch/8fc313400f06/client-clean-recovered')
sys.path.insert(0, str(ROOT))
from rm_client.calibration import CalibrationProfile, CameraCalibrationManager

SCALARS = ('width', 'height', 'board_columns', 'board_rows', 'square_size_mm',
           'rms_error_px', 'sample_count')
VECTORS = ('camera_matrix', 'distort_coeffs')


def valid_data():
    return dict(name='polar_webcam', width=960, height=540, board_columns=9,
                board_rows=6, square_size_mm=25.0,
                camera_matrix=[800.0, 0.0, 480.0, 0.0, 800.0, 270.0, 0.0, 0.0, 1.0],
                distort_coeffs=[0.0] * 5, rms_error_px=0.42, sample_count=12)


def actual_nodes(relative, names, namespace):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    nodes = {node.name: node for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names}
    assert set(nodes) == set(names)
    body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
    body.extend(nodes[name] for name in names)
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    exec(compile(module, str(ROOT / relative), 'exec'), namespace)
    return namespace


class CalibrationConfigValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manager = CameraCalibrationManager(self.root, profile_dir=self.root)
        self.path = self.manager.profile_path('polar_webcam')

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')

    def rejected(self, changes):
        previous = CalibrationProfile(**valid_data())
        self.manager.profile = previous
        self.write(valid_data() | changes)
        before = self.path.read_bytes()
        try:
            result = self.manager.load('polar_webcam')
        except Exception as error:
            self.fail(f'Rejected load escaped as {type(error).__name__}: {error}')
        self.assertIsNone(result)
        self.assertIs(self.manager.profile, previous)
        self.assertTrue(self.manager.last_error)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.manager.is_valid_for(960, 540))

    def test_actual_save_producer_roundtrip_types_and_values(self):
        class Flat:
            def __init__(self, values): self.values = values
            def reshape(self, count):
                if count != -1: raise AssertionError(count)
                return self.values
        raw = valid_data()
        self.manager._image_size = (960, 540)
        self.manager._object_points = [object()] * 12
        self.manager._image_points = [object()] * 12
        calls = []
        def calibrate(*args):
            calls.append(args)
            return (0.42, Flat(raw['camera_matrix']), Flat(raw['distort_coeffs']), None, None)
        with patch.dict(sys.modules, {'cv2': SimpleNamespace(calibrateCamera=calibrate)}):
            produced = self.manager.solve('polar_webcam', 9, 6, 25.0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2:], ((960, 540), None, None))
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved, raw)
        for key in ('width', 'height', 'board_columns', 'board_rows', 'sample_count'):
            self.assertIs(type(saved[key]), int)
        for key in ('square_size_mm', 'rms_error_px'):
            self.assertIs(type(saved[key]), float)
        for key in VECTORS:
            self.assertTrue(all(type(value) is float for value in saved[key]))
        self.manager.profile = None
        loaded = self.manager.load('polar_webcam')
        self.assertEqual(asdict(loaded), asdict(produced))
        self.assertTrue(self.manager.is_valid_for(960, 540))

    def test_finite_numeric_compatibility_is_not_narrowed_to_integral_values(self):
        raw = valid_data() | dict(width=960.0, height=540.0, board_columns=9.5,
                                 board_rows=6.5, sample_count=12.5,
                                 square_size_mm=25, rms_error_px=1,
                                 camera_matrix=[800, 0, 480, 0, 800, 270, 0, 0, 1],
                                 distort_coeffs=[0, 0, 0, 0, 0])
        self.write(raw)
        loaded = self.manager.load('polar_webcam')
        self.assertEqual(asdict(loaded), raw)
        self.assertTrue(self.manager.is_valid_for(960, 540))

    def test_scalar_null_containers_strings_and_booleans_are_rejected(self):
        for key in SCALARS:
            for value in (None, [], {}, '12', True, False):
                with self.subTest(key=key, value=value): self.rejected({key: value})

    def test_name_requires_string_without_new_content_restrictions(self):
        for value in (None, [], {}, 1, True):
            with self.subTest(value=value): self.rejected({'name': value})
        for value in ('', '相机 profile'):
            with self.subTest(value=value):
                self.write(valid_data() | {'name': value})
                self.assertEqual(self.manager.load('polar_webcam').name, value)

    def test_vector_container_types_are_rejected(self):
        for key in VECTORS:
            for value in (None, {}, '0,0', 1, True):
                with self.subTest(key=key, value=value): self.rejected({key: value})

    def test_vector_element_types_are_rejected_before_publication(self):
        for key in VECTORS:
            for value in (None, [], {}, '0', True, False):
                with self.subTest(key=key, value=value): self.rejected({key: [0.0, value]})

    def test_nonfinite_scalar_values_are_rejected(self):
        for key in SCALARS:
            for value in (float('nan'), float('inf'), -float('inf')):
                with self.subTest(key=key, value=value): self.rejected({key: value})

    def test_nonfinite_vector_values_are_rejected(self):
        for key in VECTORS:
            for value in (float('nan'), float('inf'), -float('inf')):
                with self.subTest(key=key, value=value): self.rejected({key: [0.0, value]})

    def test_numeric_overflow_is_a_rejected_load_with_previous_profile_retained(self):
        for key in SCALARS:
            with self.subTest(key=key): self.rejected({key: 10 ** 400})
        for key in VECTORS:
            with self.subTest(key=key): self.rejected({key: [10 ** 400]})

    def test_existing_quality_thresholds_and_vector_shape_policy_are_unchanged(self):
        for changes, accepted in (({}, True), ({'sample_count': 7}, False),
                                  ({'rms_error_px': 2.0}, True), ({'rms_error_px': 2.01}, False),
                                  ({'width': 959}, False), ({'height': 539}, False),
                                  ({'camera_matrix': [], 'distort_coeffs': []}, True),
                                  ({'camera_matrix': [1.0], 'distort_coeffs': [0.0] * 14}, True),
                                  ({'board_columns': -1, 'square_size_mm': 0, 'rms_error_px': -1}, True)):
            with self.subTest(changes=changes):
                self.write(valid_data() | changes)
                self.assertIsNotNone(self.manager.load('polar_webcam'))
                self.assertEqual(self.manager.is_valid_for(960, 540), accepted)

    def test_existing_missing_unknown_root_and_io_rejection_preserves_profile(self):
        prior = CalibrationProfile(**valid_data())
        self.manager.profile = prior
        self.manager.last_error = 'previous error'
        self.assertIsNone(self.manager.load('missing'))
        self.assertIs(self.manager.profile, prior)
        self.assertEqual(self.manager.last_error, 'previous error')
        for data in (None, [], {}, valid_data() | {'unknown': 1},
                     {key: value for key, value in valid_data().items() if key != 'sample_count'}):
            with self.subTest(data=data):
                self.write(data)
                self.assertIsNone(self.manager.load('polar_webcam'))
                self.assertIs(self.manager.profile, prior)
        self.path.write_text('{broken', encoding='utf-8')
        self.assertIsNone(self.manager.load('polar_webcam'))
        self.assertIs(self.manager.profile, prior)
        with patch.object(Path, 'read_text', side_effect=OSError('read unavailable')):
            self.assertIsNone(self.manager.load('polar_webcam'))
        self.assertEqual(self.manager.last_error, 'read unavailable')
        self.assertIs(self.manager.profile, prior)

    def test_success_preserves_existing_last_error_behavior(self):
        self.manager.last_error = 'historical diagnostic'
        self.write(valid_data())
        self.assertIsNotNone(self.manager.load('polar_webcam'))
        self.assertEqual(self.manager.last_error, 'historical diagnostic')

    def test_process_control_read_errors_keep_original_identity_and_prefix(self):
        prior = CalibrationProfile(**valid_data())
        self.manager.profile = prior
        self.manager.last_error = 'prior'
        self.write(valid_data())
        for failure in (KeyboardInterrupt('stop'), SystemExit(3)):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(Path, 'read_text', side_effect=failure):
                    with self.assertRaises(type(failure)) as caught:
                        self.manager.load('polar_webcam')
                self.assertIs(caught.exception, failure)
                self.assertIs(self.manager.profile, prior)
                self.assertEqual(self.manager.last_error, 'prior')

    def test_actual_presentation_predicate_after_bad_load_is_false_or_retained_valid(self):
        namespace = actual_nodes('rm_client/ui/polar/renderers/esp_wireframe.py',
                                 ['vision_result_calibrated'], {})
        result = SimpleNamespace(calibrated=True, source_width=960, source_height=540)
        for previous, expected in ((None, False), (CalibrationProfile(**valid_data()), True)):
            with self.subTest(previous=previous):
                self.manager.profile = previous
                self.write(valid_data() | {'sample_count': None})
                self.assertIsNone(self.manager.load('polar_webcam'))
                actual = namespace['vision_result_calibrated'](SimpleNamespace(calibration=self.manager), result)
                self.assertEqual(actual, expected)

    def test_actual_startup_factory_rejects_bad_profile_before_inert_services_are_built(self):
        self.write(valid_data() | {'rms_error_px': []})
        calls = []
        def service(name):
            def create(*args):
                calls.append((name, args))
                return SimpleNamespace(name=name)
            return create
        namespace = dict(dataclass=dataclass, CameraCalibrationManager=CameraCalibrationManager)
        for name in ('TongjiVisionReceiver', 'GimbalCommandBridge', 'CompositeVisionPipeline',
                     'LocalAlignedVision', 'TongjiVisionBridge'):
            namespace[name] = service(name)
        actual_nodes('rm_client/ui/polar/window_assembly.py', ['VisionServices', 'create_vision_services'], namespace)
        services = namespace['create_vision_services'](workspace=self.root,
                        calibration_profiles=self.root, model_path=self.root / 'inert.xml')
        self.assertIsNone(services.calibration.profile)
        self.assertTrue(services.calibration.last_error)
        self.assertEqual([name for name, args in calls], ['TongjiVisionReceiver', 'GimbalCommandBridge',
                         'CompositeVisionPipeline', 'LocalAlignedVision', 'TongjiVisionBridge'])
        self.assertEqual(calls[3][1], (self.root / 'inert.xml',))


if __name__ == '__main__':
    unittest.main()
