"""Deterministic input-handoff owner tests; no native/model/device/network use.

All copy/inference/postprocess races use Events. Real history owners are kept;
only model construction and native prediction work are replaced with inert code.
"""
from __future__ import annotations

from contextlib import ExitStack
import inspect
from pathlib import Path
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from rm_client.tongji_yolo import LocalAlignedVision, LocalDetection


A = ('camera', 0, 640, 360)
B = ('backend', 'UDP HEVC', 2)
C = ('backend', 'Native 0x0310', 3)
DETECTION = LocalDetection('three', 'blue', .95, (300., 160., 40., 40.),
                           ((300., 160.), (340., 160.), (340., 200.), (300., 200.)), .8)


class Frame:
    def __init__(self, label):
        self.label = label
        self.copies = 0

    def copy(self):
        self.copies += 1
        return self


class ObservedDataLock:
    """Record publication/drain at the real owner lock's release boundary."""
    def __init__(self, owner):
        self.owner = owner
        self.lock = threading.Lock()
        self.published = []
        self.publish_events = {}
        self.drain_events = {}
        self.previous = None
        self.before = None

    def __enter__(self):
        self.lock.acquire()
        self.before = self.owner._pending
        return self

    def __exit__(self, *_args):
        latest = self.owner._latest
        if latest is not None and latest is not self.previous:
            self.published.append(latest)
            self.publish_events.setdefault(latest[1], threading.Event()).set()
        self.previous = latest
        if self.before is not None and self.owner._pending is None:
            self.drain_events.setdefault(self.before[0], threading.Event()).set()
        self.lock.release()

    def publication(self, sequence):
        return self.publish_events.setdefault(sequence, threading.Event())

    def drain(self, sequence):
        return self.drain_events.setdefault(sequence, threading.Event())


def history(owner):
    selector, loss, prediction = owner._target_selector, owner._loss_probe, owner._prediction
    return {
        'selector': (selector.center, selector.name, selector.color,
                     selector.missed_frames, selector.last_seen_at),
        'loss': (loss.target_id, loss.points, loss.baseline_strength,
                 loss.last_center, loss.previous_center, loss.last_seen_at, loss.previous_seen_at),
        'prediction': (prediction._last_yaw, prediction._last_time, prediction._yaw_rate,
                       prediction._stable_frames, prediction._filtered_rvec,
                       prediction._filtered_tvec, prediction._velocity,
                       prediction._pose_time, prediction._target_key),
        'held': list(owner._held_payload),
        'fov': (selector.fov_radius_x, selector.fov_radius_y),
        'track_id': selector.track_id,
        'config': (owner.armor_count, owner.radius_m, owner.horizon_s),
    }


def seed_prediction(owner):
    def build(*_args, **kwargs):
        prediction = owner._prediction
        prediction._last_yaw = .8
        prediction._last_time = 10.
        prediction._yaw_rate = .3
        prediction._stable_frames = 9
        prediction._filtered_rvec = 'old-rvec'
        prediction._filtered_tvec = 'old-tvec'
        prediction._velocity = 'old-velocity'
        prediction._pose_time = 10.
        prediction._target_key = kwargs['target_key']
        return []
    return build


class LocalVisionInputEpochTests(unittest.TestCase):
    def owner(self, running=False):
        owner = LocalAlignedVision(Path('NO_MODEL_MAY_BE_LOADED.xml'))
        owner.running = running
        self.addCleanup(owner.close)
        return owner

    def assert_clean(self, snapshot):
        self.assertEqual(snapshot['selector'], (None, '', '', 0, 0.))
        self.assertEqual(snapshot['loss'], (-1, (), 0., None, None, 0., 0.))
        self.assertEqual(snapshot['prediction'], (0., 0., 0., 0, None, None, None, 0., None))
        self.assertEqual(snapshot['held'], [])

    def test_default_public_submit_and_pending_prefix_are_compatible(self):
        owner = self.owner()
        frame = Frame('standalone')
        self.assertEqual(owner._capture_input_token(), (owner._epoch, 0))
        owner.submit(1, 640, 360, frame)
        self.assertEqual(frame.copies, 0)
        owner.running = True
        self.assertEqual(owner._capture_input_token(), (owner._epoch, 0))
        self.assertIsNone(owner._capture_input_token('camera'))
        owner.submit(2, 640, 360, frame)
        self.assertEqual(owner._pending[:4], (2, 640, 360, frame))
        self.assertEqual(owner._pending[4], 0)
        self.assertEqual(frame.copies, 1)
        self.assertEqual(tuple(inspect.signature(LocalAlignedVision.submit).parameters),
                         ('self', 'sequence', 'width', 'height', 'bgr'))

    def test_stopped_capture_snapshots_identity_but_does_not_authorize_submission(self):
        owner = self.owner()
        owner._set_input_source(A)
        token = owner._capture_input_token('camera')
        self.assertEqual(token, (owner._epoch, owner._input_generation))
        self.assertIsNone(owner._capture_input_token('backend'))
        forbidden = NS(copy=Mock(side_effect=AssertionError('stopped/stale copy was admitted')))
        owner._submit_for_input(token, 1, 640, 360, forbidden)
        owner.submit(2, 640, 360, forbidden)
        entered, release = threading.Event(), threading.Event()
        def run(*_args):
            entered.set()
            if not release.wait(3):
                raise AssertionError('inert worker was not released')
        with patch.object(owner, '_run', side_effect=run):
            owner.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertNotEqual(owner._capture_input_token('camera'), token)
                owner._submit_for_input(token, 3, 640, 360, forbidden)
                forbidden.copy.assert_not_called()
                current = Frame('current-lifetime')
                owner._submit_for_input(owner._capture_input_token('camera'), 4, 640, 360, current)
                self.assertEqual(current.copies, 1)
                self.assertEqual(owner._pending[:4], (4, 640, 360, current))
            finally:
                release.set()
                owner.close()

    def test_changed_source_clears_queue_and_result_without_changing_lifetime(self):
        owner = self.owner(True)
        owner._set_input_source(A)
        epoch = owner._epoch
        token = owner._capture_input_token('camera')
        owner._pending = (1, 640, 360, object(), token[1])
        owner._latest = object()
        owner.inference_fps, owner.latency_ms = 123., 8.
        owner._target_selector.track_id = 77
        owner._set_input_source(B)
        self.assertEqual(owner._epoch, epoch)
        self.assertEqual((owner.inference_fps, owner.latency_ms), (123., 8.))
        self.assertEqual(owner._target_selector.track_id, 77)
        self.assertEqual(owner._capture_input_token('backend'), (epoch, token[1] + 1))
        self.assertIsNone(owner._capture_input_token('camera'))
        self.assertIsNone(owner._pending)
        self.assertIsNone(owner.latest())
        self.assertTrue(owner.running)
        self.assertFalse(owner._stop_event.is_set())

    def test_same_key_is_idempotent_and_aba_retires_old_tokens(self):
        owner = self.owner(True)
        owner._set_input_source(A)
        token = owner._capture_input_token('camera')
        owner.submit(1, 640, 360, Frame('current'))
        pending, latest = owner._pending, object()
        owner._latest = latest
        owner._set_input_source(tuple(list(A)))
        self.assertEqual(owner._capture_input_token(), token)
        self.assertIs(owner._pending, pending)
        self.assertIs(owner._latest, latest)
        owner._set_input_source(B)
        owner._set_input_source(A)
        forbidden = NS(copy=Mock(side_effect=AssertionError('stale copy was admitted')))
        owner._submit_for_input(token, 2, 640, 360, forbidden)
        owner._submit_for_input(None, 3, 640, 360, forbidden)
        forbidden.copy.assert_not_called()
        self.assertEqual(owner._capture_input_token('camera'), (token[0], token[1] + 2))
        self.assertIsNone(owner._pending)

    def test_held_copy_cannot_replace_new_source_pending_and_holds_no_owner_lock(self):
        owner = self.owner(True)
        owner._set_input_source(A)
        token = owner._capture_input_token('camera')
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def copy():
            entered.set()
            if not release.wait(3):
                raise AssertionError('held copy was not released')
            return Frame('retired')
        def submit():
            try:
                owner._submit_for_input(token, 10, 640, 360, NS(copy=copy))
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()
        producer = threading.Thread(target=submit)
        producer.start()
        try:
            self.assertTrue(entered.wait(1))
            for lock in (owner._lifecycle_lock, owner._lock):
                acquired = lock.acquire(blocking=False)
                self.assertTrue(acquired, 'copy held an owner lock')
                if acquired:
                    lock.release()
            owner._set_input_source(B)
            fresh = Frame('current')
            owner._submit_for_input(owner._capture_input_token('backend'), 11, 320, 200, fresh)
            committed = owner._pending
            release.set()
            self.assertTrue(done.wait(1))
            self.assertIs(owner._pending, committed)
            self.assertEqual(owner._pending[:4], (11, 320, 200, fresh))
            self.assertEqual(errors, [])
        finally:
            release.set()
            producer.join(2)
        self.assertFalse(producer.is_alive())

    def test_copy_exceptions_keep_existing_propagation_and_pending_state(self):
        for exception_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(exception_type=exception_type):
                owner = self.owner(True)
                owner._set_input_source(A)
                owner.submit(7, 640, 360, Frame('already-pending'))
                pending = owner._pending
                error = exception_type('synthetic copy failure')
                with self.assertRaises(exception_type) as raised:
                    owner._submit_for_input(owner._capture_input_token('camera'), 8, 640, 360,
                                            NS(copy=Mock(side_effect=error)))
                self.assertIs(raised.exception, error)
                self.assertIs(owner._pending, pending)
                self.assertTrue(owner.running)
                self.assertEqual(owner.last_error, '')

    def test_stop_lifetime_token_still_rejects_held_copy(self):
        owner = self.owner(True)
        owner._set_input_source(A)
        token = owner._capture_input_token()
        entered, release = threading.Event(), threading.Event()
        def copy():
            entered.set()
            if not release.wait(3):
                raise AssertionError('held copy was not released')
            return object()
        producer = threading.Thread(target=lambda: owner.submit(9, 640, 360, NS(copy=copy)))
        producer.start()
        try:
            self.assertTrue(entered.wait(1))
            owner.stop(wait=False)
            owner.running = True  # Inert later lifetime; no model/worker start.
            self.assertEqual(owner._input_generation, token[1])
            self.assertGreater(owner._epoch, token[0])
        finally:
            release.set()
            producer.join(2)
        self.assertFalse(producer.is_alive())
        self.assertIsNone(owner._pending)

    def run_handoff(self, held_phase):
        owner = self.owner()
        owner.configure_autoaim_fov(120., 80.)
        owner.configure_prediction(3, .31, .12)
        owner._set_input_source(A)
        observer = owner._lock = ObservedDataLock(owner)
        old_entered, old_release = threading.Event(), threading.Event()
        fresh_entered, fresh_release = threading.Event(), threading.Event()
        seed_published, fresh_published = observer.publication(1), observer.publication(3)
        reset_threads = []
        fresh_history = []
        calls = []
        def detect(frame):
            calls.append(frame.label)
            if frame.label == 'held' and held_phase == 'inference':
                old_entered.set()
                if not old_release.wait(3):
                    raise AssertionError('old inference was not released')
            if frame.label == 'fresh':
                fresh_history.append(history(owner))
                fresh_entered.set()
                if not fresh_release.wait(3):
                    raise AssertionError('fresh inference was not released')
                return []
            return [DETECTION]
        detector = NS(active_device='INERT', detect=detect)
        original_select = owner._target_selector.select
        def select(*args, **kwargs):
            value = original_select(*args, **kwargs)
            if len(calls) == 2 and held_phase == 'postprocess':
                old_entered.set()
                if not old_release.wait(3):
                    raise AssertionError('old postprocess was not released')
            return value
        with ExitStack() as stack:
            factory = stack.enter_context(patch('rm_client.tongji_yolo.TongjiYoloV5', return_value=detector))
            stack.enter_context(patch.object(owner._prediction, 'build', side_effect=seed_prediction(owner)))
            stack.enter_context(patch.object(owner._target_selector, 'select', side_effect=select))
            for component in (owner._target_selector, owner._loss_probe, owner._prediction):
                original = component.reset
                def reset(original=original):
                    reset_threads.append(threading.get_ident())
                    return original()
                stack.enter_context(patch.object(component, 'reset', side_effect=reset))
            owner.start()
            worker = owner._thread
            try:
                owner.submit(1, 640, 360, Frame('seed'))
                self.assertTrue(seed_published.wait(1), owner.last_error)
                seeded = history(owner)
                self.assertIsNotNone(seeded['selector'][0])
                self.assertTrue(seeded['held'])
                self.assertEqual(seeded['prediction'][3], 9)
                owner.submit(2, 640, 360, Frame('held'))
                self.assertTrue(old_entered.wait(1), owner.last_error)
                before = history(owner)
                epoch, token = owner._epoch, owner._capture_input_token()
                self.assertTrue(owner._lifecycle_lock.acquire(blocking=False))
                owner._lifecycle_lock.release()
                owner._set_input_source(B)
                self.assertEqual(history(owner), before, 'source setter reset worker-owned history')
                self.assertIsNone(owner.latest())
                self.assertEqual(owner._epoch, epoch)
                self.assertEqual(owner._capture_input_token(), (epoch, token[1] + 1))
                self.assertIs(owner._thread, worker)
                self.assertIs(owner._detector, detector)
                self.assertTrue(owner.running)
                self.assertFalse(owner._stop_event.is_set())
                owner.submit(3, 640, 360, Frame('fresh'))
                old_release.set()
                self.assertTrue(fresh_entered.wait(1), owner.last_error)
                # The old result has completed its whole path before this
                # worker starts the next detect call, so absence is decisive.
                self.assertEqual([item[1] for item in observer.published], [1])
                self.assertIsNone(owner.latest())
                self.assert_clean(fresh_history[0])
                self.assertEqual(fresh_history[0]['fov'], (120., 80.))
                self.assertEqual(fresh_history[0]['config'], (3, .31, .12))
                self.assertEqual(fresh_history[0]['track_id'], before['track_id'])
                self.assertEqual(set(reset_threads), {worker.ident})
                fresh_release.set()
                self.assertTrue(fresh_published.wait(1), owner.last_error)
                self.assertEqual([item[1] for item in observer.published], [1, 3])
                self.assertEqual(owner.latest()[4], [])
                self.assertIsNone(owner.latest()[7])
                self.assertIs(owner._thread, worker)
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(owner.last_error, '')
            finally:
                old_release.set()
                fresh_release.set()
                owner.close()
            self.assertFalse(worker.is_alive())

    def test_held_inference_is_discarded_and_next_generation_starts_clean(self):
        self.run_handoff('inference')

    def test_held_postprocess_cannot_publish_and_next_generation_starts_clean(self):
        self.run_handoff('postprocess')

    def test_stale_queued_generation_is_drained_without_inference(self):
        owner = self.owner()
        owner._set_input_source(A)
        stale_generation = owner._input_generation
        owner._set_input_source(B)
        observer = owner._lock = ObservedDataLock(owner)
        drained, published = observer.drain(20), observer.publication(21)
        detector = NS(active_device='INERT', detect=Mock(return_value=[]))
        with patch('rm_client.tongji_yolo.TongjiYoloV5', return_value=detector) as factory:
            owner.start()
            worker = owner._thread
            try:
                with owner._lifecycle_lock:
                    with owner._lock:
                        owner._pending = (20, 640, 360, Frame('stale-queued'), stale_generation)
                    owner._pending_event.set()
                self.assertTrue(drained.wait(1), owner.last_error)
                detector.detect.assert_not_called()
                self.assertTrue(owner.running)
                owner.submit(21, 640, 360, Frame('fresh'))
                self.assertTrue(published.wait(1), owner.last_error)
                self.assertEqual(detector.detect.call_count, 1)
                self.assertEqual([item[1] for item in observer.published], [21])
                self.assertIs(owner._thread, worker)
                self.assertEqual(factory.call_count, 1)
            finally:
                owner.close()

    def test_same_source_during_inference_preserves_token_result_and_model(self):
        owner = self.owner()
        owner._set_input_source(A)
        observer = owner._lock = ObservedDataLock(owner)
        entered, release = threading.Event(), threading.Event()
        published = observer.publication(30)
        def detect(_frame):
            entered.set()
            if not release.wait(3):
                raise AssertionError('inert inference was not released')
            return []
        detector = NS(active_device='INERT', detect=detect)
        with patch('rm_client.tongji_yolo.TongjiYoloV5', return_value=detector) as factory:
            owner.start()
            worker, token = owner._thread, owner._capture_input_token()
            try:
                owner.submit(30, 640, 360, Frame('current'))
                self.assertTrue(entered.wait(1))
                owner._set_input_source(A)
                owner._set_input_source(tuple(list(A)))
                self.assertEqual(owner._capture_input_token(), token)
                self.assertIs(owner._thread, worker)
                self.assertIs(owner._detector, detector)
                self.assertFalse(owner.cleanup_pending)
                release.set()
                self.assertTrue(published.wait(1), owner.last_error)
                current_result = owner.latest()
                owner._set_input_source(A)
                self.assertIs(owner.latest(), current_result)
                self.assertEqual(factory.call_count, 1)
            finally:
                release.set()
                owner.close()

    def test_same_source_restart_retains_history_but_changed_source_resets_on_worker(self):
        for change_while_stopped in (False, True):
            with self.subTest(change_while_stopped=change_while_stopped):
                owner = self.owner()
                owner._set_input_source(A)
                owner.configure_autoaim_fov(120., 80.)
                owner.configure_prediction(3, .31, .12)
                observer = owner._lock = ObservedDataLock(owner)
                first, second = observer.publication(50), observer.publication(51)
                snapshots = []
                def detect(frame):
                    if frame.label == 'after-restart':
                        snapshots.append(history(owner))
                    return [DETECTION]
                detector = NS(active_device='INERT', detect=detect)
                with patch('rm_client.tongji_yolo.TongjiYoloV5', return_value=detector) as factory, \
                     patch.object(owner._prediction, 'build', side_effect=seed_prediction(owner)):
                    owner.start()
                    try:
                        owner.submit(50, 640, 360, Frame('seed'))
                        self.assertTrue(first.wait(1), owner.last_error)
                    finally:
                        owner.close()
                    before = history(owner)
                    self.assertTrue(before['held'])
                    old_generation = owner._history_input_generation
                    if change_while_stopped:
                        owner._set_input_source(B)
                        self.assertEqual(history(owner), before)
                        self.assertEqual(owner._history_input_generation, old_generation)
                    owner.start()
                    try:
                        owner.submit(51, 640, 360, Frame('after-restart'))
                        self.assertTrue(second.wait(1), owner.last_error)
                        if change_while_stopped:
                            self.assert_clean(snapshots[0])
                            self.assertEqual(snapshots[0]['track_id'], before['track_id'])
                            self.assertEqual(snapshots[0]['fov'], before['fov'])
                            self.assertEqual(snapshots[0]['config'], before['config'])
                            self.assertEqual(owner._history_input_generation, old_generation + 1)
                        else:
                            self.assertEqual(snapshots[0], before)
                            self.assertEqual(owner._history_input_generation, old_generation)
                        self.assertEqual(factory.call_count, 2)
                        self.assertEqual(owner.last_error, '')
                    finally:
                        owner.close()

    def test_initial_standalone_start_keeps_existing_history_semantics(self):
        owner = self.owner()
        owner._target_selector.track_id = 37
        owner._target_selector.center = (320., 180.)
        owner._target_selector.name = 'three'
        owner._held_payload = [{'id': 37, 'held': True}]
        seed_prediction(owner)(target_key=37)
        before = history(owner)
        observer = owner._lock = ObservedDataLock(owner)
        published = observer.publication(60)
        snapshots = []
        def detect(_frame):
            snapshots.append(history(owner))
            return [DETECTION]
        detector = NS(active_device='INERT', detect=detect)
        with patch('rm_client.tongji_yolo.TongjiYoloV5', return_value=detector), \
             patch.object(owner._prediction, 'build', side_effect=seed_prediction(owner)):
            owner.start()
            try:
                owner.submit(60, 640, 360, Frame('initial'))
                self.assertTrue(published.wait(1), owner.last_error)
                self.assertEqual(snapshots[0], before)
                self.assertEqual(owner._history_input_generation, 0)
            finally:
                owner.close()

    def test_source_switch_during_model_load_preserves_single_worker(self):
        owner = self.owner()
        owner._set_input_source(A)
        observer = owner._lock = ObservedDataLock(owner)
        loading, release = threading.Event(), threading.Event()
        published = observer.publication(41)
        detector = NS(active_device='INERT', detect=Mock(return_value=[]))
        def load(*_args):
            loading.set()
            if not release.wait(3):
                raise AssertionError('inert model constructor was not released')
            return detector
        with patch('rm_client.tongji_yolo.TongjiYoloV5', side_effect=load) as factory:
            owner.start()
            worker = owner._thread
            try:
                self.assertTrue(loading.wait(1))
                epoch = owner._epoch
                owner.submit(40, 640, 360, Frame('old'))
                owner._set_input_source(B)
                owner.submit(41, 640, 360, Frame('current'))
                release.set()
                self.assertTrue(published.wait(1), owner.last_error)
                self.assertEqual([item[1] for item in observer.published], [41])
                self.assertEqual(detector.detect.call_count, 1)
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(owner._epoch, epoch)
                self.assertIs(owner._thread, worker)
            finally:
                release.set()
                owner.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
