"""Actual UI method AST and pure inference owner, with inert frame/native edges."""
from __future__ import annotations
import ast
import os
from pathlib import Path
import sys
import threading
import time
from types import MethodType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'rm_client').is_dir():
    ROOT = Path('/workspace/scratch/8fc313400f06/client-clean-recovered')
sys.path.insert(0, str(ROOT))
from rm_client.vision import CameraCaptureWorker, CapturedFrame
from rm_client.tongji_yolo import LocalAlignedVision
from rm_client.ui.polar.camera_activation import CameraActivation
from rm_client.ui.polar.normal_video_timeline import NormalVideoTimeline
from rm_client.ui.polar.vision_selection import VisionSelection
from rm_client.backend.video_source import (
    VideoSourceRequest, VideoSourceSnapshot, VideoStopStatus, VideoSourceFailure,
    VideoSourceAdmission, VideoSourceAdmissionError,
)
EconomyScenePhase = NS(CLOSED="closed", OPEN="open", CLOSING="closing")

SOURCE = ROOT / 'rm_client/ui/polar/mixins/video_backend_mixin.py'
NAMES = ('ensure_camera_started', '_bind_camera_frame_sink', '_sync_local_vision_input',
         'on_captured_camera_frame', 'consume_capture_frame', 'consume_backend_video_frame',
         'update_hero_deploy_state', 'refresh_vision_runtime')

class Frame:
    shape = (120, 160, 3)
    ndim = 3
    strides = (480, 3, 1)
    data = b'inert'
    def __init__(self, label, copy_hook=None): self.label, self.copy_hook = label, copy_hook
    def copy(self):
        if self.copy_hook: self.copy_hook()
        return Frame(self.label)
    def __getitem__(self, key): return self
    def mean(self): return 128.0

class Image:
    Format = NS(Format_BGR888='inert-bgr', Format_RGB888='inert-rgb')
    def __init__(self, *args): pass
    def copy(self): return self
    def mirrored(self, *args): return self

class InertCamera:
    def __init__(self):
        self.running, self.camera_id, self.size = True, 0, (160, 120)
        self.frame, self.last_error = None, ''
        self.on_frame = None
    def stop(self, *, wait):
        assert wait is False
        self.running, self.frame = False, None
    def configure(self, camera_id, size): self.camera_id, self.size = camera_id, size
    def start(self): self.running = True; return True
    def latest_frame(self): return self.frame

def bind_methods(host):
    cls = next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'VideoBackendMixin')
    selected = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    scope = {'os': os, 'time': time, 'QImage': Image, 'QPixmap': NS(fromImage=lambda image: image),
             'EconomyScenePhase': EconomyScenePhase, 'OverlayKind': NS(HERO_DEPLOY='hero')}
    tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), str(SOURCE), 'exec'), scope)
    for name in NAMES:
        if name in scope: setattr(host, name, MethodType(scope[name], host))
    return host

def make_host():
    source = NS(value='Webcam')
    module = NS(get_setting=lambda name: source if name == 'Source' else None)
    camera = InertCamera()
    local = LocalAlignedVision(Path('INERT_NO_MODEL'))
    local.running = True
    h = NS(camera_worker=camera, local_vision=local, _vision_source='Local', state=NS(),
        registry=NS(get=lambda name: module), _window_lifecycle=NS(closing=False),
        _normal_video_timeline=NormalVideoTimeline(), NORMAL_BACKEND_VIDEO_STALE_S=.65,
        hero_deploy_video_cut_active=lambda: False,
        hero_deploy_ui=NS(render_visible=False, pending_mode=None),
        consume_hero_native_video_frame=lambda: False,
        update_hud_liquid_source=lambda image: None,
        clear_normal_backend_video_frame=lambda: None,
        setting_bool=lambda module, key, default: False,
        setting_mode=lambda module, key, default: source.value,
        get_setting_number=lambda module, key, default: {'Camera ID': 0, 'Capture Width': 160, 'Capture Height': 120}.get(key, default),
        backend=NS(video_source_snapshot=NS(generation=1), latest_video_frame=lambda *args: (Frame('BACKEND'), 200., 'udp'),
                   udp=NS(clear_stale_decoded_frame=lambda *args: None)))
    h._camera_activation = CameraActivation(camera, True, (0, 160, 120))
    bind_methods(h)
    if hasattr(h, '_sync_local_vision_input'): h._sync_local_vision_input('webcam')
    return h, source

def pending_label(local):
    return None if local._pending is None else local._pending[3].label

def captured(camera, label='WEBCAM', copy_hook=None, sequence=1):
    frame = Frame(label, copy_hook)
    result = CapturedFrame(sequence, 1, 160, 120, frame, frame)
    camera.frame = result
    return result

def inert_backend():
    """Actual source-admission and scenario-activation AST, inert resource ports."""
    source = ROOT / 'rm_client/backend/manager.py'
    cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'BackendManager')
    names = {'_activate_scenario', 'set_active_video_source', 'video_source_snapshot'}
    nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    scope = dict(VideoSourceRequest=VideoSourceRequest, VideoSourceSnapshot=VideoSourceSnapshot,
        VideoSourceFailure=VideoSourceFailure, VideoSourceAdmission=VideoSourceAdmission,
        VideoSourceAdmissionError=VideoSourceAdmissionError)
    exec(compile(ast.fix_missing_locations(tree), str(source), 'exec'), scope)
    kind = type('InertBackend', (), {name: scope[name] for name in names})
    b = kind()
    b._lifecycle = NS(applying=True)
    b._video_source_request = VideoSourceRequest('udp hevc', True)
    b._video_source_generation = 3; b._video_source_failures = ()
    b._active_video_source = b._normal_video_source = 'udp hevc'
    b._hero_native_override = False; b._native_restart_thread = None
    b._native_restart_generation = 0; b.state = None
    b.udp = NS(running=True, ingress_mode='shark-framed', stop_pending=False, stop_status=VideoStopStatus(),
        request_stop=lambda: None, request_decode_enabled=lambda value: None,
        start=lambda: None, clear_stale_decoded_frame=lambda *args: None)
    b.native_decoder = NS(stop_pending=False, stop_status=VideoStopStatus(), request_stop=lambda: None)
    b._native_recovery = NS(reset=lambda: None)
    b._apply_config = lambda config: None
    b.set_referee_profile = lambda profile, **kwargs: None
    b.set_client_id = lambda identity: None
    b.polar = NS()
    b._input_clear_incomplete = lambda: False
    b.latest_video_frame = lambda *args: (Frame('BACKEND'), 200., 'udp')
    return b

def wire_refresh(h, source):
    def idle_worker(): return NS(stop=lambda **kwargs: None, running=False)
    h._vision_selection = VisionSelection(h.local_vision, idle_worker(), idle_worker())
    h._stop_vision_workers = lambda owners: [worker.stop(wait=False) for _, worker in owners] and None
    model = NS(exists=lambda: True)
    h.local_vision.model_path = model
    h._client_asset_path = lambda *args: model
    h.local_vision.start = lambda: setattr(h.local_vision, 'running', True)
    camera = NS(enabled=True, get_setting=lambda key: source if key == 'Source' else None)
    h.registry = NS(get=lambda name: camera)
    h.setting_mode = lambda module, key, default: {'Source': source.value, 'Vision Source': 'Local', 'Local Device': 'AUTO'}.get(key, default)


class CameraInputHandoffTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'POLAR_DISABLE_LOCAL_CAPTURE': ''})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_current_camera_callback_still_submits_without_restarting_local(self):
        h, _ = make_host(); frame = captured(h.camera_worker)
        before = h.local_vision._epoch
        h.on_captured_camera_frame(frame)
        self.assertEqual(pending_label(h.local_vision), 'WEBCAM')
        self.assertEqual(h.local_vision._pending[:3], (1, 160, 120))
        self.assertEqual(h.local_vision._epoch, before)

    def test_source_away_suspend_then_backend_rejects_old_callback(self):
        for mode in ('UDP HEVC', 'Native 0x0310'):
            with self.subTest(mode=mode):
                h, source = make_host(); old = captured(h.camera_worker, 'OLD')
                source.value = mode; h.ensure_camera_started(); h.consume_backend_video_frame()
                self.assertEqual(pending_label(h.local_vision), 'BACKEND')
                h.on_captured_camera_frame(old)
                self.assertEqual(pending_label(h.local_vision), 'BACKEND')

    def test_source_away_suspension_alone_rejects_already_copying_callback(self):
        for mode in ('UDP HEVC', 'Native 0x0310', 'Synthetic'):
            with self.subTest(mode=mode):
                h, source = make_host()
                def change(): source.value = mode; h.ensure_camera_started()
                old = captured(h.camera_worker, 'OLD', change)
                h.on_captured_camera_frame(old)
                self.assertIsNone(h.local_vision._pending)
                self.assertFalse(h.camera_worker.running)

    def test_held_copy_cannot_overwrite_new_backend_submission(self):
        h, source = make_host(); entered, release = threading.Event(), threading.Event(); errors = []
        def hold():
            entered.set()
            if not release.wait(2): raise AssertionError('held inert frame was not released')
        frame = captured(h.camera_worker, 'OLD', hold)
        def callback():
            try: h.on_captured_camera_frame(frame)
            except BaseException as error: errors.append(error)
        thread = threading.Thread(target=callback); thread.start()
        try:
            self.assertTrue(entered.wait(1))
            source.value = 'UDP HEVC'; h.ensure_camera_started(); h.consume_backend_video_frame()
            self.assertEqual(pending_label(h.local_vision), 'BACKEND')
        finally: release.set(); thread.join(2)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
        self.assertEqual(pending_label(h.local_vision), 'BACKEND')

    def test_camera_backend_camera_aba_does_not_bless_old_frame(self):
        h, source = make_host(); old = captured(h.camera_worker, 'OLD')
        source.value = 'UDP HEVC'; h.ensure_camera_started()
        source.value = 'Webcam'; h.ensure_camera_started()
        fresh = captured(h.camera_worker, 'FRESH', sequence=2)
        h.on_captured_camera_frame(fresh); h.on_captured_camera_frame(old)
        self.assertEqual(pending_label(h.local_vision), 'FRESH')

    def test_disabled_capture_revokes_copy_without_consume(self):
        h, _ = make_host()
        def disable():
            with patch.dict(os.environ, {'POLAR_DISABLE_LOCAL_CAPTURE': '1'}): h.ensure_camera_started()
        frame = captured(h.camera_worker, 'OLD', disable)
        h.on_captured_camera_frame(frame)
        self.assertIsNone(h.local_vision._pending)
        self.assertEqual(h.camera_worker.last_error, 'local capture disabled')

    def test_reconfigure_retires_before_fallible_frame_clear(self):
        h, _ = make_host()
        original = h.get_setting_number
        h.get_setting_number = lambda m, k, d: 1 if k == 'Camera ID' else original(m, k, d)
        failure = ValueError('clear failed')
        def change():
            h.clear_normal_backend_video_frame = lambda: (_ for _ in ()).throw(failure)
            with self.assertRaises(ValueError) as caught: h.ensure_camera_started()
            self.assertIs(caught.exception, failure)
        frame = captured(h.camera_worker, 'OLD', change)
        h.on_captured_camera_frame(frame)
        self.assertIsNone(h.local_vision._pending)
        self.assertFalse(h._camera_activation.started)
        self.assertEqual(h._camera_activation.configuration, (0, 160, 120))

    def test_mode_retirement_precedes_fallible_clear_for_both_consumers(self):
        for method in ('consume_capture_frame', 'consume_backend_video_frame'):
            with self.subTest(method=method):
                h, source = make_host(); failure = ValueError('clear failed')
                def change():
                    source.value = 'UDP HEVC'
                    h.clear_normal_backend_video_frame = lambda: (_ for _ in ()).throw(failure)
                    with self.assertRaises(ValueError): getattr(h, method)()
                frame = captured(h.camera_worker, 'OLD', change)
                h.on_captured_camera_frame(frame)
                self.assertIsNone(h.local_vision._pending)
                self.assertEqual(h._normal_video_timeline.requested_mode, '')

    def test_same_source_polling_preserves_pending_input_and_latest(self):
        h, source = make_host(); source.value = 'UDP HEVC'
        h.ensure_camera_started(); h.consume_backend_video_frame()
        pending = h.local_vision._pending; latest = object(); h.local_vision._latest = latest
        epoch = h.local_vision._epoch
        h.ensure_camera_started(); h.consume_capture_frame()
        self.assertIs(h.local_vision._pending, pending)
        self.assertIs(h.local_vision._latest, latest)
        self.assertEqual(h.local_vision._epoch, epoch)

    def test_backend_source_generation_change_clears_old_input_even_with_no_frame(self):
        h, source = make_host(); source.value = 'UDP HEVC'
        h.consume_backend_video_frame(); self.assertEqual(pending_label(h.local_vision), 'BACKEND')
        h.backend.video_source_snapshot.generation += 1
        h.backend.latest_video_frame = lambda *args: (None, 0., '')
        h.consume_backend_video_frame()
        self.assertIsNone(h.local_vision._pending)

    def test_backend_source_change_during_copy_cannot_submit_old_frame(self):
        h, source = make_host(); source.value = 'UDP HEVC'
        def change():
            source.value = 'Native 0x0310'; h.backend.video_source_snapshot.generation += 1
            h.ensure_camera_started()
        h.backend.latest_video_frame = lambda *args: (Frame('OLD_UDP', change), 200., 'udp')
        h.consume_backend_video_frame()
        self.assertIsNone(h.local_vision._pending)

    def test_same_source_replacement_owner_after_decode_receives_current_frame(self):
        h, source = make_host(); source.value = 'UDP HEVC'; original = h.local_vision
        replacement = LocalAlignedVision(Path('INERT_NO_MODEL')); replacement.running = True
        def latest(*args): h.local_vision = replacement; return Frame('CURRENT'), 200., 'udp'
        h.backend.latest_video_frame = latest
        h.consume_backend_video_frame()
        self.assertIsNone(original._pending)
        self.assertEqual(pending_label(replacement), 'CURRENT')

    def test_same_source_running_property_replacement_is_observed(self):
        h, source = make_host(); source.value = 'UDP HEVC'
        replacement = LocalAlignedVision(Path('INERT_NO_MODEL')); replacement.running = True
        class Changing:
            @property
            def running(self): h.local_vision = replacement; return True
        def latest(*args): h.local_vision = Changing(); return Frame('CURRENT'), 200., 'udp'
        h.backend.latest_video_frame = latest
        h.consume_backend_video_frame()
        self.assertEqual(pending_label(replacement), 'CURRENT')

    def test_initially_stopped_local_can_start_during_same_source_decode(self):
        h, source = make_host(); source.value = 'UDP HEVC'; h.local_vision.running = False
        def latest(*args):
            h.local_vision.running = True; h.local_vision._epoch += 1
            return Frame('CURRENT'), 200., 'udp'
        h.backend.latest_video_frame = latest
        h.consume_backend_video_frame()
        self.assertEqual(pending_label(h.local_vision), 'CURRENT')

    def test_old_owner_stop_and_same_source_replacement_keeps_current_frame(self):
        h, source = make_host(); source.value = 'UDP HEVC'; original = h.local_vision
        replacement = LocalAlignedVision(Path('INERT_NO_MODEL')); replacement.running = True
        def latest(*args):
            original.stop(wait=False); h.local_vision = replacement
            return Frame('CURRENT'), 200., 'udp'
        h.backend.latest_video_frame = latest
        h.consume_backend_video_frame()
        self.assertEqual(pending_label(replacement), 'CURRENT')

    def test_backend_input_retire_and_same_source_aba_during_copy_is_rejected(self):
        h, source = make_host(); source.value = 'UDP HEVC'
        def change():
            with patch.dict(os.environ, {'POLAR_DISABLE_LOCAL_CAPTURE': '1'}): h.ensure_camera_started()
            h.ensure_camera_started()
        h.backend.latest_video_frame = lambda *args: (Frame('OLD', change), 200., 'udp')
        h.consume_backend_video_frame()
        self.assertIsNone(h.local_vision._pending)

    def test_source_changed_with_replacement_does_not_adopt_old_backend_input(self):
        for mode in ('Synthetic', 'Native 0x0310'):
            with self.subTest(mode=mode):
                h, source = make_host(); source.value = 'UDP HEVC'
                replacement = LocalAlignedVision(Path('INERT_NO_MODEL')); replacement.running = True
                def latest(*args):
                    source.value = mode; h.local_vision = replacement
                    return Frame('OLD'), 200., 'udp'
                h.backend.latest_video_frame = latest
                h.consume_backend_video_frame()
                self.assertIsNone(replacement._pending)

    def test_acknowledged_deployment_revokes_copy_before_any_normal_consume(self):
        h, _ = make_host()
        h._last_deploy_mode = h._last_deploy_status_revision = 0
        h.state.deploy_mode = h.state.deploy_status_revision = 1
        h.state.hero_lob_status = ''
        h.economy_phase = EconomyScenePhase.CLOSED; h.gui_visible = False
        h.hero_deploy_ui.sync = lambda *args: None
        h.hero_deploy_ui.open = lambda *args: None
        h.invalidate_transient_overlay_scene = lambda: None
        h.close_match_chat = lambda **kwargs: None
        h.cancel_quick_action_wheel = lambda: None
        h.overlay_coordinator = NS(request_modal=lambda *args: None)
        h.play_gui_transition_sound = lambda *args: None
        h.frame_scheduler = NS(force=lambda: None)
        def deploy():
            h.hero_deploy_video_cut_active = lambda: True
            h.update_hero_deploy_state(20.)
        frame = captured(h.camera_worker, 'OLD', deploy)
        h.on_captured_camera_frame(frame)
        self.assertIsNone(h.local_vision._pending)
        self.assertFalse(h._camera_activation.started)
        self.assertEqual(h._last_deploy_mode, 1)

    def test_stopped_and_nonlocal_vision_keep_existing_submission_gate(self):
        for mode, running in (('Mock', True), ('local', True), ('Local', False)):
            with self.subTest(mode=mode, running=running):
                h, source = make_host(); source.value = 'UDP HEVC'; h._vision_source = mode; h.local_vision.running = running
                h.consume_backend_video_frame()
                self.assertIsNone(h.local_vision._pending)
                self.assertEqual(h._normal_video_timeline.frame_source, 'backend')

    def test_actual_scenario_activation_new_source_epoch_retires_pending_input(self):
        h, source = make_host(); source.value = 'UDP HEVC'; h.backend = inert_backend()
        wire_refresh(h, source)
        h.consume_backend_video_frame(); self.assertEqual(pending_label(h.local_vision), 'BACKEND')
        previous = h.backend.video_source_snapshot.generation
        request = NS(key='new-profile', config=None, referee_profile='test', robot_id=7,
            polar_mode='inert', polar_host='', polar_tcp_port=0, preserve_estop=True, start=False)
        h.backend._activate_scenario(request)
        self.assertEqual(h.backend.video_source_snapshot.generation, previous)
        h.refresh_vision_runtime()
        self.assertEqual(h.backend.video_source_snapshot.generation, previous + 1)
        self.assertIsNone(h.local_vision._pending)
        self.assertTrue(h.local_vision.running)

    def test_unchanged_runtime_refresh_preserves_valid_pending_input(self):
        h, source = make_host(); source.value = 'UDP HEVC'; h.backend = inert_backend()
        wire_refresh(h, source)
        h.consume_backend_video_frame(); pending = h.local_vision._pending
        epoch = h.local_vision._epoch; generation = h.backend.video_source_snapshot.generation
        h.refresh_vision_runtime()
        self.assertIs(h.local_vision._pending, pending)
        self.assertEqual(h.local_vision._epoch, epoch)
        self.assertEqual(h.backend.video_source_snapshot.generation, generation)

    def test_camera_stop_failure_preserves_prior_input_retirement_prefix(self):
        h, source = make_host(); frame = captured(h.camera_worker); h.on_captured_camera_frame(frame)
        pending = h.local_vision._pending; failure = ValueError('stop failed')
        h.camera_worker.stop = lambda **kwargs: (_ for _ in ()).throw(failure)
        source.value = 'UDP HEVC'
        with self.assertRaises(ValueError) as caught: h.ensure_camera_started()
        self.assertIs(caught.exception, failure)
        self.assertIs(h.local_vision._pending, pending)
        self.assertTrue(h._camera_activation.started)

    def test_same_source_failed_backend_copy_keeps_prior_pending_input(self):
        h, source = make_host(); source.value = 'UDP HEVC'; h.consume_backend_video_frame()
        pending = h.local_vision._pending
        h.backend.latest_video_frame = lambda *args: (NS(copy=lambda: None), 201., 'udp')
        h.consume_backend_video_frame()
        self.assertIs(h.local_vision._pending, pending)
        self.assertEqual(h._normal_video_timeline.backend_admitted_at, 200.)

    def test_nonstring_source_away_values_keep_existing_suspension_contract(self):
        for value in (None, 0, False):
            with self.subTest(value=value):
                h, source = make_host(); source.value = value
                h.ensure_camera_started()
                self.assertFalse(h.camera_worker.running)
                self.assertFalse(h._camera_activation.started)

    def test_token_is_captured_before_camera_identity_admission(self):
        h, source = make_host(); old = captured(h.camera_worker, 'OLD')
        def latest():
            source.value = 'UDP HEVC'; h.ensure_camera_started()
            source.value = 'Webcam'; h.ensure_camera_started()
            captured(h.camera_worker, 'FRESH', sequence=2)
            return old
        h.camera_worker.latest_frame = latest
        h.on_captured_camera_frame(old)
        self.assertIsNone(h.local_vision._pending)

    def test_binding_keeps_current_bound_method_identity(self):
        h, _ = make_host(); old_epoch = h.local_vision._epoch
        h._bind_camera_frame_sink()
        self.assertEqual(h.camera_worker.on_frame, h.on_captured_camera_frame)
        self.assertEqual(h.local_vision._epoch, old_epoch)

if __name__ == '__main__': unittest.main()
