"""Standalone, stdlib-only motion tests: no QApplication, windows or devices.

Run from the repository root:
    py -B -m unittest discover -s tests -p test_endfield_source_motion.py -v

The reference uses Decimal Bernstein polynomials, never the production solver.
Real-source golden numbers are mathematical samples, not Unity runtime captures.
"""
from copy import deepcopy
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rm_client.ui.endfield_source_motion import sample_weighted_curve


def key(time, value, **overrides):
    result = {"time": time, "value": value, "inSlope": 0.0, "outSlope": 0.0,
              "weightedMode": 0, "inWeight": 1 / 3, "outWeight": 1 / 3}
    result.update(overrides)
    return result


def decimal_number(value):
    return Decimal.from_float(float(value))


def bernstein(points, u):
    v = 1 - u
    return points[0] * v**3 + 3 * points[1] * v*v*u + 3 * points[2] * v*u*u + points[3] * u**3


def reference_controls(left, right):
    dt = decimal_number(right["time"]) - decimal_number(left["time"])
    outgoing = (decimal_number(left["outWeight"])
                if left.get("weightedMode", 0) & 2 else Decimal(1) / 3)
    incoming = (decimal_number(right["inWeight"])
                if right.get("weightedMode", 0) & 1 else Decimal(1) / 3)
    start, end = decimal_number(left["value"]), decimal_number(right["value"])
    return ((Decimal(0), outgoing, 1 - incoming, Decimal(1)),
            (start, start + dt * outgoing * decimal_number(left["outSlope"]),
             end - dt * incoming * decimal_number(right["inSlope"]), end))


def reference_sample(left, right, seconds):
    """High-precision oracle with independent Bernstein-form time inversion."""
    with localcontext() as context:
        context.prec = 70
        xs, ys = reference_controls(left, right)
        time = ((decimal_number(seconds) - decimal_number(left["time"]))
                / (decimal_number(right["time"]) - decimal_number(left["time"])))
        low, high = Decimal(0), Decimal(1)
        for _ in range(240):
            u = (low + high) / 2
            if bernstein(xs, u) < time:
                low = u
            else:
                high = u
        return float(bernstein(ys, (low + high) / 2))


class ScalarCurveTests(unittest.TestCase):
    def test_clamps_endpoints_and_single_key(self):
        keys = [key(2, -7), key(4, 9), key(7, 3)]
        for time, expected in ((-50, -7), (2, -7), (4, 9), (7, 3), (50, 3)):
            self.assertEqual(sample_weighted_curve(keys, time), expected)
        for time in (-100, 0.1, 10):
            self.assertEqual(sample_weighted_curve([key(0.1, 8)], time), 8)

    def test_unweighted_hermite_uses_duration_and_ignores_inactive_weights(self):
        keys = [key(2, -3, outSlope=4, inWeight=0.9, outWeight=0),
                key(7, 9, inSlope=-2, inWeight=0, outWeight=0.9)]
        for t in (0.01, 0.2, 0.5, 0.9, 0.99):
            expected = ((2*t**3 - 3*t*t + 1)*-3 + (t**3 - 2*t*t + t)*5*4
                        + (-2*t**3 + 3*t*t)*9 + (t**3 - t*t)*5*-2)
            self.assertAlmostEqual(sample_weighted_curve(keys, 2 + 5*t), expected, places=11)

    def test_legacy_keys_may_omit_weight_fields(self):
        keys = [{"time": 2, "value": 3, "inSlope": 0, "outSlope": 2},
                {"time": 5, "value": 9, "inSlope": 2, "outSlope": 0}]
        self.assertEqual(sample_weighted_curve(keys, 3.5), 6)

    def test_each_weighted_mode_is_a_per_side_bitmask(self):
        for left_mode in range(4):
            for right_mode in range(4):
                keys = [key(2, -3, weightedMode=left_mode, outWeight=0.8,
                            inWeight=0.95, outSlope=4, inSlope=99),
                        key(7, 9, weightedMode=right_mode, inWeight=0.1,
                            outWeight=0.9, inSlope=-2, outSlope=-99)]
                for time in (2.05, 3.2, 4.5, 6.8):
                    with self.subTest(left_mode=left_mode, right_mode=right_mode, time=time):
                        self.assertAlmostEqual(sample_weighted_curve(keys, time),
                                               reference_sample(*keys, time), places=10)

    def test_zero_unit_crossed_and_asymmetric_handles(self):
        for outgoing, incoming in ((0, 0), (0, 1), (1, 0), (1, 1),
                                   (0.99, 0.99), (0.001, 0.9), (0.8, 0.02)):
            keys = [key(-1, 4, weightedMode=2, outWeight=outgoing, outSlope=3),
                    key(3, -2, weightedMode=1, inWeight=incoming, inSlope=-7)]
            for fraction in (1e-9, 0.01, 0.25, 0.5, 0.75, 0.99, 1 - 1e-9):
                time = -1 + 4 * fraction
                with self.subTest(outgoing=outgoing, incoming=incoming, fraction=fraction):
                    self.assertAlmostEqual(sample_weighted_curve(keys, time),
                                           reference_sample(*keys, time), places=9)

    def test_stationary_time_axis_near_midpoint(self):
        keys = [key(0, 0, weightedMode=2, outWeight=1, outSlope=3),
                key(1, 1, weightedMode=1, inWeight=1, inSlope=-2)]
        for time in (math.nextafter(0.5, 0), 0.5, math.nextafter(0.5, 1)):
            self.assertAlmostEqual(sample_weighted_curve(keys, time),
                                   reference_sample(*keys, time), places=11)

    def test_zero_weights_produce_linear_segment(self):
        keys = [key(2, -8, weightedMode=2, outWeight=0, outSlope=900),
                key(6, 12, weightedMode=1, inWeight=0, inSlope=-800)]
        for time in (2.001, 3, 4.4, 5.999):
            self.assertAlmostEqual(sample_weighted_curve(keys, time), -8 + 5*(time-2), places=11)

    def test_step_from_either_infinite_slope_holds_until_exact_right_key(self):
        for side in ("left", "right", "both"):
            for infinity in (math.inf, -math.inf):
                keys = [key(0, 3, outSlope=infinity if side != "right" else 0),
                        key(1, -7, inSlope=infinity if side != "left" else 0),
                        key(2, 5)]
                with self.subTest(side=side, infinity=infinity):
                    for time in (0.01, 0.5, math.nextafter(1, 0)):
                        self.assertEqual(sample_weighted_curve(keys, time), 3)
                    self.assertEqual(sample_weighted_curve(keys, 1), -7)
                    self.assertEqual(sample_weighted_curve(keys, 1.5), -1)

    def test_unused_outer_infinite_slopes_do_not_make_a_step(self):
        keys = [key(0, 0, inSlope=math.inf), key(1, 1, outSlope=-math.inf)]
        self.assertEqual(sample_weighted_curve(keys, 0.5), 0.5)

    def test_overshoot_is_not_clamped(self):
        keys = [key(0, 0, outSlope=12), key(1, 1, inSlope=-12)]
        self.assertGreater(sample_weighted_curve(keys, 0.5), 1)

    def test_input_is_not_sorted_mutated_or_cached(self):
        keys = [key(0, 0, weightedMode=2, outWeight=0.8), key(1, 1)]
        original = deepcopy(keys)
        before = sample_weighted_curve(keys, 0.4)
        self.assertEqual(keys, original)
        keys[0]["outWeight"] = 0.1
        self.assertNotEqual(before, sample_weighted_curve(keys, 0.4))

    def test_deterministic_synthetic_curves_against_decimal(self):
        rng = random.Random(71027)
        for index in range(30):
            start = rng.uniform(-5, 5)
            keys = [key(start, rng.uniform(-50, 50), weightedMode=rng.randrange(4),
                        outWeight=rng.random(), outSlope=rng.uniform(-80, 80)),
                    key(start + rng.uniform(0.001, 5), rng.uniform(-50, 50),
                        weightedMode=rng.randrange(4), inWeight=rng.random(),
                        inSlope=rng.uniform(-80, 80))]
            time = keys[0]["time"] + (keys[1]["time"] - keys[0]["time"])*rng.uniform(0.001, 0.999)
            with self.subTest(index=index):
                self.assertAlmostEqual(sample_weighted_curve(keys, time),
                                       reference_sample(*keys, time), places=9)


class RejectedInputTests(unittest.TestCase):
    def test_wrong_container_and_row_types(self):
        for keys in (None, 4, {}, "keys", b"keys", iter([]), [None], [[0, 1]]):
            with self.subTest(keys=keys), self.assertRaises(TypeError):
                sample_weighted_curve(keys, 0)
        with self.assertRaisesRegex(ValueError, "empty"):
            sample_weighted_curve([], 0)

    def test_missing_fields_and_active_weights(self):
        for field in ("time", "value", "inSlope", "outSlope"):
            row = key(0, 1)
            del row[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                sample_weighted_curve([row], 0)
        for field, mode in (("inWeight", 1), ("outWeight", 2)):
            row = key(0, 1, weightedMode=mode)
            del row[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                sample_weighted_curve([row], 0)

    def test_invalid_seconds(self):
        for value in (None, True, "0.1", 1 + 2j):
            with self.subTest(value=value), self.assertRaisesRegex(TypeError, "seconds"):
                sample_weighted_curve([key(0, 1)], value)
        for value in (math.nan, math.inf, -math.inf, 10**1000):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "seconds"):
                sample_weighted_curve([key(0, 1)], value)

    def test_invalid_numeric_fields_even_outside_sampled_range(self):
        for field in ("time", "value", "inSlope", "outSlope", "inWeight", "outWeight"):
            invalid_values = [math.nan, None, "0", True]
            if field not in ("inSlope", "outSlope"):
                invalid_values.extend((math.inf, -math.inf))
            for value in invalid_values:
                row = key(1, 1)
                row[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex((TypeError, ValueError), field):
                        sample_weighted_curve([key(0, 0), row], -50)

    def test_invalid_modes_and_weights(self):
        for mode in (-1, 4, 8, 1.0, "3", True, None):
            with self.subTest(mode=mode), self.assertRaisesRegex((TypeError, ValueError), "weightedMode"):
                sample_weighted_curve([key(0, 1, weightedMode=mode)], 0)
        for field in ("inWeight", "outWeight"):
            for weight in (-0.001, 1.001):
                with self.subTest(field=field, weight=weight), self.assertRaisesRegex(ValueError, field):
                    sample_weighted_curve([key(0, 1, **{field: weight})], 0)

    def test_duplicate_unsorted_and_overflowing_time_intervals(self):
        for times in ((0, 0), (1, 0), (-1e308, 1e308)):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, "finite positive interval"):
                sample_weighted_curve([key(times[0], 0), key(times[1], 1)], -1e308)

    def test_overflowing_control_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "control values overflow"):
            sample_weighted_curve([key(0, 1e308, outSlope=1e308), key(10, 0)], 5)


class SourceClipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "assets/endfield_settings/source_layout.json"
        cls.clips = json.loads(path.read_text(encoding="utf-8"))["clips"]

    def source_keys(self, clip, path, attribute):
        return next(row["curve"]["m_Curve"] for row in self.clips[clip]["curves"]
                    if row["path"] == path and row["attribute"] == attribute)

    def test_authored_in_out_and_checkbox_midpoints_have_fixed_goldens(self):
        cases = (
            ("gamesetting_in", "Main/TopNode", "m_AnchoredPosition.y", 10.59292420225468),
            ("gamesetting_out", "Main/TopNode", "m_AnchoredPosition.y", 10.59292420225468),
            ("common_toggle_to_left01", "SelectedBG/Node2/SelectedBG", "m_AnchoredPosition.x", -30.820252742995783),
            ("common_toggle_to_left01", "SelectedBG/Node1/SelectedBG", "m_AnchoredPosition.x", 48.62667877391432),
            ("common_toggle_to_right01", "SelectedBG/Node1/SelectedBG", "m_AnchoredPosition.x", 22.144368268277618),
            ("common_toggle_to_right01", "SelectedBG/Node2/SelectedBG", "m_AnchoredPosition.x", -57.302563248632484),
        )
        for clip, path, attribute, expected in cases:
            with self.subTest(clip=clip, path=path):
                keys = self.source_keys(clip, path, attribute)
                time = keys[0]["time"] + (keys[1]["time"] - keys[0]["time"]) / 2
                self.assertAlmostEqual(sample_weighted_curve(keys, time), expected, places=9)
                # A zero-slope, unweighted Hermite would simply average values.
                self.assertGreater(abs(expected - (keys[0]["value"] + keys[1]["value"]) / 2), 1)

    def test_all_real_segments_at_non_key_times_against_decimal(self):
        count = 0
        for clip, data in self.clips.items():
            for row in data["curves"]:
                keys = row["curve"]["m_Curve"]
                for left, right in zip(keys, keys[1:]):
                    for fraction in (0.1, 0.25, 0.5, 0.75, 0.9):
                        time = left["time"] + (right["time"] - left["time"]) * fraction
                        with self.subTest(clip=clip, path=row["path"], attribute=row["attribute"], time=time):
                            self.assertAlmostEqual(sample_weighted_curve(keys, time),
                                                   reference_sample(left, right, time), places=9)
                        count += 1
        self.assertGreaterEqual(count, 300)

    def test_all_source_keys_and_single_key_tracks_are_exact(self):
        for clip, data in self.clips.items():
            for row in data["curves"]:
                keys = row["curve"]["m_Curve"]
                for source in keys:
                    with self.subTest(clip=clip, path=row["path"], time=source["time"]):
                        self.assertEqual(sample_weighted_curve(keys, source["time"]), source["value"])
                self.assertEqual(sample_weighted_curve(keys, keys[0]["time"] - 1), keys[0]["value"])
                self.assertEqual(sample_weighted_curve(keys, keys[-1]["time"] + 1), keys[-1]["value"])

    def test_source_alpha_and_tab_change_non_endpoints(self):
        for clip, path in (("gamesetting_in", "Main/ContentNode"),
                           ("gamesetting_out", "Main/ContentNode"),
                           ("gamesetting_change", "Main/ContentNode/SettingListNode")):
            keys = self.source_keys(clip, path, "m_Alpha")
            for fraction in (0.25, 0.5, 0.75):
                expected = keys[0]["value"] + (keys[1]["value"] - keys[0]["value"]) * (
                    3*fraction*fraction - 2*fraction**3)
                time = keys[0]["time"] + (keys[1]["time"] - keys[0]["time"]) * fraction
                with self.subTest(clip=clip, fraction=fraction):
                    self.assertAlmostEqual(sample_weighted_curve(keys, time), expected, places=12)


class ImportIsolationTests(unittest.TestCase):
    def test_fresh_import_and_sampling_do_not_load_qt_or_theme(self):
        script = """
import sys
from rm_client.ui.endfield_source_motion import sample_weighted_curve
keys = [dict(time=0, value=0, inSlope=0, outSlope=0),
        dict(time=1, value=1, inSlope=0, outSlope=0)]
assert sample_weighted_curve(keys, 0.5) == 0.5
assert not any(name.startswith(('PySide6', 'shiboken6')) for name in sys.modules)
assert 'rm_client.ui.endfield_settings_theme' not in sys.modules
"""
        completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
