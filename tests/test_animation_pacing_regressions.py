"""Offline animation/scheduler contracts; no Qt, GL, devices or networking.

Run: python tests/test_animation_pacing_regressions.py
Pass --source-root /path/to/baseline to reproduce pre-fix failures without
modifying that checkout. Scheduler class extraction avoids all Qt imports.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if "--source-root" in sys.argv:
    option = sys.argv.index("--source-root")
    ROOT = Path(sys.argv.pop(option + 1)).resolve()
    sys.argv.pop(option)


def load_animation(root, name="animation_pacing_test_source"):
    spec = importlib.util.spec_from_file_location(name, Path(root) / "rm_client/ui/animation.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_scheduler(root):
    path = Path(root) / "rm_client/ui/polar/primitives.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FrameScheduler")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["FrameScheduler"]


animation = load_animation(ROOT)
FrameScheduler = load_scheduler(ROOT)


class SpringFixedPointTests(unittest.TestCase):
    def test_exactly_settled_spring_avoids_analytical_work(self):
        # Cover all damping branches without rounding the actual state to rest.
        for ratio in (0.0, 0.5, 1.0, 1.000005, 2.0):
            with self.subTest(ratio=ratio), patch.object(animation.math, "sqrt", side_effect=AssertionError("settled spring recalculated")):
                self.assertEqual(animation.step_damped_spring(53.25, 0.0, 53.25, .016, damping_ratio=ratio), (53.25, 0.0))

    def test_target_change_and_residual_momentum_still_advance(self):
        for value, velocity, target in ((0., 0., 1.), (1., 2., 1.), (1. + 1.e-10, 0., 1.)):
            with self.subTest(value=value, velocity=velocity, target=target):
                result = animation.step_damped_spring(value, velocity, target, .016)
                self.assertNotEqual(result, (value, velocity))
                self.assertNotEqual(result, (target, 0.))

    def test_moving_spring_is_independent_of_frame_partition(self):
        for ratio in (.5, 1., 2.):
            for elapsed in (.08, .12, .20, .45):
                with self.subTest(ratio=ratio, elapsed=elapsed):
                    expected = animation.step_damped_spring(15., -3., 200., elapsed, damping_ratio=ratio)
                    value, velocity = 15., -3.
                    for _ in range(24):
                        value, velocity = animation.step_damped_spring(value, velocity, 200., elapsed / 24., damping_ratio=ratio)
                    self.assertAlmostEqual(value, expected[0], places=10)
                    self.assertAlmostEqual(velocity, expected[1], places=10)

    def test_zero_negative_time_and_suspend_guard_remain(self):
        for dt in (0., -1.):
            self.assertEqual(animation.step_damped_spring(1., 2., 4., dt), (1., 2.))
        self.assertEqual(animation.step_damped_spring(1., 2., 4., 8.), animation.step_damped_spring(1., 2., 4., 1.))


class IslandElapsedTimeTests(unittest.TestCase):
    def test_regular_cadences_keep_original_exponential_curve(self):
        for hz in (30., 60., 90., 120., 144., 165., 240.):
            timeline = animation.ReversibleExpoTimeline(duration=.8)
            timeline.set_target(1.)
            for frame in range(1, 11):
                timeline.update(1. / hz)
                expected = 1. - 2. ** (-10. * (frame / hz) / .8)
                self.assertAlmostEqual(timeline.progress, expected, places=13)

    def test_delayed_frame_consumes_elapsed_time_open_and_close(self):
        for start, target in ((0., 1.), (1., 0.), (.37, 1.), (.63, 0.)):
            for duration in (.22, .30, .80):
                for elapsed in (.08, .12, .20, .45):
                    with self.subTest(start=start, target=target, duration=duration, elapsed=elapsed):
                        delayed = animation.ReversibleExpoTimeline(progress=start, target=target, duration=duration)
                        regular = animation.ReversibleExpoTimeline(progress=start, target=target, duration=duration)
                        delayed.update(elapsed)
                        for _ in range(24):
                            regular.update(elapsed / 24.)
                        self.assertAlmostEqual(delayed.progress, regular.progress, places=12)

    def test_zero_negative_time_and_one_second_suspend_guard(self):
        for dt in (0., -.1):
            timeline = animation.ReversibleExpoTimeline(progress=.3, target=1.)
            self.assertEqual(timeline.update(dt), .3)
        suspended = animation.ReversibleExpoTimeline(target=1., duration=5.)
        regular = animation.ReversibleExpoTimeline(target=1., duration=5.)
        self.assertEqual(suspended.update(60.), regular.update(1.))
        self.assertAlmostEqual(suspended.progress, .75, places=13)

    def test_reversal_is_continuous_and_uses_existing_duration(self):
        timeline = animation.ReversibleExpoTimeline(target=1., duration=.3)
        timeline.update(.04)
        previous = timeline.progress
        timeline.set_target(0.)
        self.assertEqual(timeline.progress, previous)
        self.assertEqual(timeline.duration, .3)
        self.assertAlmostEqual(timeline.update(.12), previous * 2. ** (-10. * .12 / .3), places=13)

    def test_container_geometry_and_content_follow_same_elapsed_time(self):
        def initialized():
            island = animation.IslandContainerState()
            island.set_target_geometry(10., 20., 220., 42.)
            island.set_target_geometry(30., 40., 520., 280.)
            island.set_content_target(1., .22)
            return island
        delayed, regular = initialized(), initialized()
        delayed.update(.12)
        for _ in range(12):
            regular.update(.01)
        for name in ("x", "y", "width", "height", "radius"):
            self.assertAlmostEqual(getattr(delayed, name), getattr(regular, name), places=11)
        self.assertAlmostEqual(delayed.content.progress, regular.content.progress, places=12)

    def test_map_open_close_including_missed_frame(self):
        state = animation.MapIslandState()
        state.set_target(12., 58., 220., 170., False)
        state.set_target(12., 58., 520., 380., True)
        state.update(.12)
        opened = state.progress
        self.assertAlmostEqual(opened, 1. - 2. ** (-10. * .12 / .22), places=13)
        state.set_target(12., 58., 220., 170., False)
        self.assertEqual(state.progress, opened)
        state.update(.12)
        self.assertAlmostEqual(state.progress, opened * 2. ** (-10. * .12 / .22), places=13)


class SchedulerPacingTests(unittest.TestCase):
    def test_seven_ms_callbacks_request_each_144hz_frame(self):
        scheduler = FrameScheduler()
        requested = [tick for tick in range(0, 71, 7) if scheduler.should_request(tick / 1000., True, 144.)]
        self.assertEqual(requested, list(range(0, 71, 7)))

    def test_regular_supported_refresh_rates_preserve_deadlines(self):
        for hz in (30., 60., 90., 120., 144., 165., 240.):
            scheduler = FrameScheduler()
            for index in range(200):
                self.assertTrue(scheduler.should_request(10. + index / hz, True, hz))
            self.assertAlmostEqual(scheduler.next_request, 10. + 200. / hz, places=10)

    def test_early_allowance_and_no_duplicate_same_callback(self):
        scheduler = FrameScheduler()
        self.assertTrue(scheduler.should_request(10., True, 144.))
        deadline = scheduler.next_request
        allowance = min(.0015, 1. / 144. * .12)
        self.assertFalse(scheduler.should_request(deadline - allowance - .00001, True, 144.))
        self.assertTrue(scheduler.should_request(deadline - allowance, True, 144.))
        self.assertFalse(scheduler.should_request(deadline - allowance, True, 144.))
        # Bulk multiplication can round exactly onto the early boundary.
        scheduler = FrameScheduler()
        scheduler.should_request(1., True, 60.)
        rounded_now = 1.0984999999999998
        self.assertTrue(scheduler.should_request(rounded_now, True, 60.))
        self.assertGreater(scheduler.next_request, rounded_now + .0015)
        self.assertLessEqual(scheduler.next_request, rounded_now + .0015 + 1. / 60.)
        self.assertFalse(scheduler.should_request(rounded_now, True, 60.))

    def test_idle_mode_and_force_preserve_existing_contract(self):
        scheduler = FrameScheduler()
        self.assertTrue(scheduler.should_request(10., False, 144.))
        self.assertFalse(scheduler.should_request(10.03, False, 144.))
        self.assertTrue(scheduler.should_request(10.067, False, 144.))
        scheduler.force()
        self.assertEqual((scheduler.last_request, scheduler.next_request), (0., 0.))
        self.assertTrue(scheduler.should_request(10.068, True, 144.))

    def test_pause_skip_is_bounded_and_preserves_deadline_phase(self):
        class CountedDeadline(float):
            additions = 0
            def __add__(self, other):
                type(self).additions += 1
                if type(self).additions > 8:
                    raise AssertionError("scheduler still walks the missed-frame backlog")
                return type(self)(float(self) + other)
        for hz, high_rate in ((15., False), (144., True), (240., True)):
            for pause in (.2, 60., 8. * 3600.):
                with self.subTest(hz=hz, pause=pause):
                    CountedDeadline.additions = 0
                    scheduler = FrameScheduler()
                    scheduler.should_request(100., high_rate, hz)
                    initial_deadline = scheduler.next_request
                    scheduler.next_request = CountedDeadline(initial_deadline)
                    now = 100. + pause
                    self.assertTrue(scheduler.should_request(now, high_rate, hz))
                    self.assertLessEqual(CountedDeadline.additions, 3)
                    due = now + min(.0015, 1. / hz * .12)
                    self.assertGreater(scheduler.next_request, due)
                    self.assertLessEqual(scheduler.next_request, due + 1. / hz + 1.e-10)
                    intervals = (scheduler.next_request - initial_deadline) * hz
                    self.assertAlmostEqual(intervals, round(intervals), places=7)
                    self.assertEqual(scheduler.last_request, now)
                    self.assertFalse(scheduler.should_request(now, high_rate, hz))


if __name__ == "__main__":
    unittest.main()
