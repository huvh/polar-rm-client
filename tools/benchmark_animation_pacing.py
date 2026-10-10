"""Compare pure motion helpers against a local pre-change source snapshot.

No Qt, app startup, GL, hardware, services, subprocesses or dependency install.
Measurements are helper CPU costs, not measured application FPS or smoothness.
Example: python tools/benchmark_animation_pacing.py --baseline-root ../baseline
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def time_pair(before, after, *, iterations, samples=9, warmup=10):
    for _ in range(warmup):
        before()
        after()
    values = {"before": [], "after": []}
    gc_enabled = gc.isenabled()
    gc.disable()
    try:
        for sample in range(samples):
            order = (("before", before), ("after", after))
            if sample % 2:
                order = tuple(reversed(order))
            for name, callback in order:
                started = time.perf_counter_ns()
                for _ in range(iterations):
                    callback()
                values[name].append((time.perf_counter_ns() - started) / iterations / 1000.)
    finally:
        if gc_enabled:
            gc.enable()
    result = {key: {"median_us": statistics.median(v), "min_us": min(v), "max_us": max(v)} for key, v in values.items()}
    result.update(iterations_per_sample=iterations, samples=samples)
    result["cpu_change_percent"] = (result["after"]["median_us"] / result["before"]["median_us"] - 1.) * 100.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("animation_pacing_helpers", ROOT / "tests/test_animation_pacing_regressions.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    before = helpers.load_animation(args.baseline_root, "animation_pacing_before")
    after = helpers.load_animation(ROOT, "animation_pacing_after")
    schedulers = [helpers.load_scheduler(path) for path in (args.baseline_root, ROOT)]
    result = {
        "scope": "Pure helper CPU microbenchmarks and deterministic traces, not application FPS, Qt timer or GPU validation",
        "python": platform.python_version(), "platform": platform.platform(),
        "source_sha256": {}, "benchmarks": {}, "verification": {},
    }
    for name, root in (("before", args.baseline_root), ("after", ROOT)):
        result["source_sha256"][name] = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in ("rm_client/ui/animation.py", "rm_client/ui/polar/primitives.py")}

    # Same function inputs, including every damping branch and finite extremes.
    rng = random.Random(20261011)
    exact_matches = 0
    for index in range(10000):
        value, target = rng.uniform(-500., 500.), rng.uniform(-500., 500.)
        velocity = rng.uniform(-200., 200.)
        if index % 5 == 0:
            value, velocity = target, 0.
        params = dict(stiffness=rng.choice((.001, 235., 300., 5000.)), damping_ratio=rng.choice((0., .5, 1., 1.000005, 2., 5.)), mass=rng.choice((.1, 1., 20.)))
        dt = rng.choice((0., -.1, 1. / 144., .12, .5, 5.))
        expected = before.step_damped_spring(value, velocity, target, dt, **params)
        actual = after.step_damped_spring(value, velocity, target, dt, **params)
        assert actual == expected, (index, expected, actual)
        exact_matches += 1
    result["verification"]["spring_exact_numeric_matches"] = exact_matches

    # Preserve the existing exponential formula at every normal cadence.
    expo_matches = 0
    for hz in (30., 60., 90., 120., 144., 165., 240.):
        first, second = (module.ReversibleExpoTimeline(duration=.8) for module in (before, after))
        for frame in range(1000):
            if frame % 31 == 0:
                target = float((frame // 31) % 2)
                first.set_target(target)
                second.set_target(target)
            assert first.update(1. / hz) == second.update(1. / hz)
            expo_matches += 1
    result["verification"]["normal_exponential_samples_exact"] = expo_matches
    for name, module in (("before", before), ("after", after)):
        delayed = module.ReversibleExpoTimeline(target=1., duration=.22)
        regular = module.ReversibleExpoTimeline(target=1., duration=.22)
        delayed.update(.12)
        for _ in range(12):
            regular.update(.01)
        result["verification"][name + "_120ms_alpha"] = {"one_delayed_update": delayed.progress, "twelve_10ms_updates": regular.progress}

    # Compare ordinary callback decisions with actual baseline source.
    decisions, max_deadline_difference = 0, 0.
    for hz in (30., 60., 90., 120., 144., 165., 240.):
        for jitter in (False, True):
            first, second = (cls() for cls in schedulers)
            now = 100.
            for frame in range(10000):
                high_rate = frame % 700 >= 80
                now += (1. / hz) * (rng.uniform(.6, 1.8) if jitter else 1.)
                if frame % 411 == 0:
                    now += .12
                if frame % 707 == 0:
                    first.force()
                    second.force()
                assert first.should_request(now, high_rate, hz) == second.should_request(now, high_rate, hz), (hz, frame)
                max_deadline_difference = max(max_deadline_difference, abs(first.next_request - second.next_request))
                decisions += 1
    result["verification"]["scheduler_callback_decisions_equal"] = decisions
    result["verification"]["scheduler_max_deadline_difference_seconds"] = max_deadline_difference

    for label, value, velocity, target in (("64_settled_springs", 20., 0., 20.), ("64_moving_springs", 20., -5., 200.)):
        def workload(module):
            def run():
                for _ in range(64):
                    module.step_damped_spring(value, velocity, target, 1. / 144.)
            return run
        result["benchmarks"][label] = time_pair(workload(before), workload(after), iterations=1000)
    idle = [module.IslandContainerState() for module in (before, after)]
    result["benchmarks"]["settled_island_update_5_springs_plus_content"] = time_pair(lambda: idle[0].update(1. / 144.), lambda: idle[1].update(1. / 144.), iterations=3000)

    def regular_callbacks(cls):
        stamps = [100. + index * .007 for index in range(144)]
        def run():
            scheduler = cls()
            for stamp in stamps:
                scheduler.should_request(stamp, True, 144.)
        return run
    result["benchmarks"]["144_normal_scheduler_callbacks"] = time_pair(*(regular_callbacks(cls) for cls in schedulers), iterations=1000)
    for pause in (60., 8. * 3600.):
        def resume(cls):
            scheduler = cls()
            def run():
                scheduler.last_request = 100.
                scheduler.next_request = 100. + 1. / 144.
                scheduler.should_request(100. + pause, True, 144.)
            return run
        result["benchmarks"][f"scheduler_resume_after_{int(pause)}_seconds"] = time_pair(*(resume(cls) for cls in schedulers), iterations=3 if pause == 60. else 1, warmup=2)
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
