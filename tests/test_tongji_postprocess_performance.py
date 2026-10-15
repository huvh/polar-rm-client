"""Exact old-loop parity and call-count regression; no wall-time pass/fail gate.

Run with .venv/Scripts/python.exe -X utf8 tests/test_tongji_postprocess_performance.py
Add --benchmark for a bounded, synthetic (1, 25200, 22) NumPy gate microbenchmark.
That shape is the bundled yolov5.xml Result port, not a camera-FPS measurement.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client import tongji_yolo as tongji


_REAL_NMS = cv2.dnn.NMSBoxes
_NAMES = ("sentry", "one", "two", "three", "four", "five", "outpost", "base", "not_armor")
_COLORS = ("blue", "red", "extinguish", "purple")


def _legacy_sigmoid(value: float) -> float:
    # Independent copy of the pre-optimization scalar implementation.
    return 1.0 / (1.0 + math.exp(-value)) if value >= 0 else math.exp(value) / (1.0 + math.exp(value))


def _legacy_light_strength(bgr, points):
    height, width = bgr.shape[:2]
    centers = (
        ((points[0][0] + points[3][0]) * 0.5, (points[0][1] + points[3][1]) * 0.5),
        ((points[1][0] + points[2][0]) * 0.5, (points[1][1] + points[2][1]) * 0.5),
    )
    samples = []
    for x, y in centers:
        ix, iy = int(round(x)), int(round(y))
        patch = bgr[max(0, iy - 4):min(height, iy + 5), max(0, ix - 4):min(width, ix + 5)]
        if patch.size:
            samples.append(float(np.mean(np.max(patch, axis=2))) / 255.0)
    return sum(samples) / len(samples) if samples else 0.0


def _legacy_postprocess(output, bgr, score_threshold, min_confidence, nms):
    """Old row loop, without calling the new helper or production sigmoid."""
    height, width = bgr.shape[:2]
    scale = min(640.0 / max(1, height), 640.0 / max(1, width))
    rows = np.asarray(output, dtype=np.float32).reshape(-1, 22)
    boxes, confidences, candidates, sampled_points = [], [], [], []
    for row in rows:
        confidence = _legacy_sigmoid(float(row[8]))
        if confidence < score_threshold or confidence < min_confidence:
            continue
        color_id = int(np.argmax(row[9:13]))
        number_id = int(np.argmax(row[13:22]))
        if number_id >= len(_NAMES):
            continue
        name = _NAMES[number_id]
        if name == "not_armor":
            continue
        points = (
            (float(row[0] / scale), float(row[1] / scale)),
            (float(row[6] / scale), float(row[7] / scale)),
            (float(row[4] / scale), float(row[5] / scale)),
            (float(row[2] / scale), float(row[3] / scale)),
        )
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        x, y = max(0.0, min(xs)), max(0.0, min(ys))
        box_w, box_h = max(xs) - x, max(ys) - y
        if box_w < 2.0 or box_h < 2.0:
            continue
        boxes.append([int(x), int(y), int(box_w), int(box_h)])
        confidences.append(confidence)
        sampled_points.append(points)
        light_strength = _legacy_light_strength(bgr, points)
        candidates.append(tongji.LocalDetection(
            name, _COLORS[min(color_id, len(_COLORS) - 1)], confidence,
            (x, y, box_w, box_h), points, light_strength,
        ))
    keep = nms(boxes, confidences, score_threshold, 0.30)
    indices = [int(index) for index in keep.flatten()] if len(keep) else []
    return [candidates[index] for index in indices], sampled_points


def _float_bits(value):
    # Exact confidence comparison, including NaN (which is not equal to itself).
    return struct.pack("!d", value)


def _detection_signature(detections):
    return [(d.name, d.color, _float_bits(d.confidence), d.box, d.points,
             _float_bits(d.light_strength)) for d in detections]


class _NmsRecorder:
    def __init__(self, real=True):
        self.real = real
        self.calls = []

    def __call__(self, boxes, confidences, score, overlap):
        self.calls.append((
            [list(box) for box in boxes], [_float_bits(c) for c in confidences],
            _float_bits(score), _float_bits(overlap),
        ))
        if self.real:
            return _REAL_NMS(boxes, confidences, score, overlap)
        # Isolate Python comparison semantics for thresholds rejected by OpenCV.
        return np.arange(len(boxes), dtype=np.int32).reshape(-1, 1)


def _rows(logits):
    rows = np.zeros((len(logits), 22), dtype=np.float32)
    for index, logit in enumerate(logits):
        x, y = 20.0 + (index % 10) * 50.0, 20.0 + (index % 5) * 40.0
        rows[index, :8] = (x, y, x, y + 12.0, x + 24.0, y + 12.0, x + 24.0, y)
        rows[index, 8] = logit
        rows[index, 9 + index % 4] = 1.0
        rows[index, 13 + index % 8] = 1.0
    return rows


class TongjiPostprocessPerformanceTests(unittest.TestCase):
    def assert_matches_legacy(self, output, bgr=None, score=0.70, minimum=0.80, *, real_nms=True):
        if bgr is None:
            bgr = np.random.default_rng(27).integers(0, 256, (360, 960, 3), dtype=np.uint8)
        old_nms, new_nms = _NmsRecorder(real_nms), _NmsRecorder(real_nms)
        expected, sampled_points = _legacy_postprocess(output, bgr, score, minimum, old_nms)
        detector = object.__new__(tongji.TongjiYoloV5)
        detector.input = SimpleNamespace(any_name="test_input")
        detector.output = "test_output"
        detector.compiled = mock.Mock(return_value={detector.output: output})
        original_output = output.copy()
        with mock.patch.object(cv2.dnn, "NMSBoxes", new=new_nms), \
             mock.patch.object(tongji, "_sigmoid", wraps=tongji._sigmoid) as sigmoid, \
             mock.patch.object(detector, "_sample_light_strength", wraps=detector._sample_light_strength) as light:
            actual = detector.detect(bgr, score, minimum)
        self.assertEqual(_detection_signature(actual), _detection_signature(expected))
        self.assertEqual(new_nms.calls, old_nms.calls, "NMS inputs, order and thresholds must be identical")
        self.assertEqual([call.args[1] for call in light.call_args_list], sampled_points)
        np.testing.assert_array_equal(output, original_output)
        detector.compiled.assert_called_once()
        tensor = detector.compiled.call_args.args[0]["test_input"]
        self.assertEqual(tensor.shape, (1, 3, 640, 640))
        self.assertEqual(tensor.dtype, np.float32)
        return actual, sigmoid

    def test_randomized_exact_results_and_light_samples(self):
        rng = np.random.default_rng(8321)
        for height, width in ((480, 960), (720, 1280), (301, 577)):
            rows = _rows(rng.normal(-2.0, 5.0, 768))
            xy = rng.uniform(-20, 600, (len(rows), 2)).astype(np.float32)
            wh = rng.uniform(0, 60, (len(rows), 2)).astype(np.float32)
            rows[:, :8] = np.column_stack((xy, xy + wh * (0, 1), xy + wh, xy + wh * (1, 0)))
            rows[:, 9:] = rng.normal(size=(len(rows), 13))
            bgr = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            for score, minimum in ((0.70, 0.80), (0.85, 0.30), (0.0, 0.0), (1.0, 1.0)):
                with self.subTest(size=(height, width), thresholds=(score, minimum)):
                    self.assert_matches_legacy(rows[None], bgr, score, minimum)

    def test_threshold_equality_neighbors_and_scalar_confidence_bits(self):
        for logit in (-100.0, -30.0, -2.0, -0.0, 0.0, 1.0, 2.0, 17.0, 100.0):
            confidence = _legacy_sigmoid(float(np.float32(logit)))
            rows = _rows([logit, np.nextafter(np.float32(logit), np.float32(-np.inf)),
                          np.nextafter(np.float32(logit), np.float32(np.inf))])
            for threshold in (math.nextafter(confidence, -math.inf), confidence,
                              math.nextafter(confidence, math.inf)):
                with self.subTest(logit=logit, threshold=threshold):
                    self.assert_matches_legacy(rows, score=0.0, minimum=threshold, real_nms=False)
                    self.assert_matches_legacy(rows, score=threshold, minimum=0.0, real_nms=False)
        # OpenCV has its own strict score gate: min-confidence equality still passes.
        actual, _ = self.assert_matches_legacy(_rows([0.0]), score=0.40, minimum=0.50)
        self.assertEqual(actual[0].confidence, 0.50)

    def test_rounding_guard_keeps_boundary_but_scalar_still_rejects(self):
        numpy_exp = np.exp

        def rounded_up_exp(values):
            result = numpy_exp(values)
            for _ in range(4):
                result = np.nextafter(result, np.inf)
            return result

        self.assertLess(1.0 / (1.0 + rounded_up_exp(np.array([0.0]))[0]), 0.50)
        with mock.patch.object(np, "exp", side_effect=rounded_up_exp):
            actual, sigmoid = self.assert_matches_legacy(_rows([0.0]), score=0.40, minimum=0.50)
            self.assertEqual(len(actual), 1)
            self.assertEqual(sigmoid.call_count, 1)
            actual, sigmoid = self.assert_matches_legacy(
                _rows([0.0]), score=0.40, minimum=math.nextafter(0.50, math.inf),
            )
            self.assertEqual(actual, [])
            self.assertEqual(sigmoid.call_count, 1, "near-boundary rejects still use the exact old check")

    def test_non_builtin_thresholds_keep_original_scalar_promotion(self):
        rows = _rows([-8.0, np.float32(1.3862944), 2.0])
        for threshold in (np.float16(0.8), np.float32(0.8), np.float64(0.8), 0, 1):
            with self.subTest(threshold=threshold, kind=type(threshold).__name__):
                self.assert_matches_legacy(rows, score=threshold, real_nms=False)
                _, sigmoid = self.assert_matches_legacy(rows, minimum=threshold, real_nms=False)
                self.assertEqual(sigmoid.call_count, len(rows))
        # This value rounds to float32(0.8), though its exact double is lower.
        confidence = _legacy_sigmoid(float(rows[1, 8]))
        self.assertLess(confidence, float(np.float32(0.8)))
        self.assertFalse(confidence < np.float32(0.8))
        actual, _ = self.assert_matches_legacy(rows[1:2], minimum=np.float32(0.8), real_nms=False)
        self.assertEqual(len(actual), 1)

    def test_nan_inf_logits_and_thresholds_preserve_old_comparisons(self):
        rows = _rows([math.nan, -math.inf, math.inf, -1000.0, -745.0, -744.0,
                      -100.0, -0.0, 0.0, 100.0, 1000.0])
        thresholds = (math.nan, -math.inf, math.inf, -0.5, -0.0, 0.70, 0.80, 1.0,
                      math.nextafter(1.0, math.inf), 1.5)
        for score in thresholds:
            for minimum in thresholds:
                with self.subTest(score=score, minimum=minimum):
                    self.assert_matches_legacy(rows, score=score, minimum=minimum, real_nms=False)
        with np.errstate(all="raise"):
            indices = tongji._confidence_candidate_indices(rows[:, 8], 0.70, 0.80)
        np.testing.assert_array_equal(indices, [0, 2, 9, 10])
        self.assert_matches_legacy(rows)  # Also compare the actual OpenCV NaN path.

    def test_empty_and_background_only_outputs(self):
        for shape in ((0, 22), (1, 0, 22)):
            actual, sigmoid = self.assert_matches_legacy(np.empty(shape, dtype=np.float32))
            self.assertEqual(actual, [])
            self.assertEqual(sigmoid.call_count, 0)
        actual, sigmoid = self.assert_matches_legacy(_rows([-8.0] * 256)[None])
        self.assertEqual(actual, [])
        self.assertEqual(sigmoid.call_count, 0)

    def test_not_armor_ties_small_boxes_and_overlapping_multi_target_nms(self):
        rows = _rows([2.0, 4.0, 2.0, 3.0, 5.0, -8.0, 2.0, 2.0])
        rows[1, 13:] = 0.0
        rows[1, 21] = 10.0  # High-confidence not_armor is still rejected.
        rows[2, :8] = rows[0, :8]  # Equal score/overlap must keep original row order.
        rows[4, :8] = 100.0  # Degenerate box is still rejected before sampling.
        rows[6, 9:] = 0.0  # argmax ties still select the first color/number.
        rows[7, 9] = math.nan  # Keep NumPy argmax's original NaN behavior.
        actual, sigmoid = self.assert_matches_legacy(rows)
        self.assertEqual(sigmoid.call_count, 7)
        self.assertEqual(len(actual), 4)
        self.assertNotIn("not_armor", [item.name for item in actual])
        self.assertEqual([item.name for item in actual], ["three", "sentry", "sentry", "base"])
        # A separate non-square frame checks TL, TR, BR, BL mapping and clipping.
        rows = _rows([2.0])
        rows[0, :8] = (-4, 6, -4, 18, 20, 18, 20, 6)
        actual, _ = self.assert_matches_legacy(rows, np.full((720, 1280, 3), 128, dtype=np.uint8))
        self.assertEqual(actual[0].points, ((-8.0, 12.0), (40.0, 12.0), (40.0, 36.0), (-8.0, 36.0)))
        self.assertEqual(actual[0].box, (0.0, 12.0, 40.0, 24.0))

    def test_real_model_output_shape_reduces_scalar_calls_from_n_to_candidates(self):
        # Bundled yolov5.xml output/sink_port_0: [1, 25200, 22].
        rows = _rows([-8.0] * 25200)
        retained = [0, 127, 8400, 16800, 25199]
        rows[retained, 8] = [2.0, 3.0, math.inf, math.nan, 4.0]
        rows[127, 13:] = 0.0
        rows[127, 21] = 1.0  # Still counted: class rejection belongs to the old loop.
        for output in (rows[None], rows.astype(np.float64), rows.reshape(3, 8400, 22),
                       np.asfortranarray(rows[None])):
            with self.subTest(shape=output.shape, dtype=output.dtype, contiguous=output.flags.c_contiguous):
                _, sigmoid = self.assert_matches_legacy(output, real_nms=False)
                self.assertEqual(sigmoid.call_count, len(retained))
                self.assertEqual([call.args[0] for call in sigmoid.call_args_list if not math.isnan(call.args[0])],
                                 [2.0, 3.0, math.inf, 4.0])

    def test_dense_output_does_not_cap_or_reorder_candidates(self):
        rows = _rows([2.0] * 2048)
        actual, sigmoid = self.assert_matches_legacy(rows[None], real_nms=False)
        self.assertEqual(sigmoid.call_count, len(rows))
        self.assertEqual(len(actual), len(rows))


def _benchmark():
    """Time only the removed Python gate vs NumPy + retained scalar checks."""
    def legacy(rows):
        result = []
        for index, row in enumerate(rows):
            confidence = _legacy_sigmoid(float(row[8]))
            if confidence < 0.70 or confidence < 0.80:
                continue
            result.append((index, confidence))
        return result

    def optimized(rows):
        result = []
        for index in tongji._confidence_candidate_indices(rows[:, 8], 0.70, 0.80):
            confidence = tongji._sigmoid(float(rows[index, 8]))
            if confidence < 0.70 or confidence < 0.80:
                continue
            result.append((int(index), confidence))
        return result

    report = {"python": sys.version, "platform": platform.platform(),
              "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
              "numpy": np.__version__, "opencv": cv2.__version__, "shape": [1, 25200, 22],
              "timing": "gate only; 7 medians of 30 iterations, after 3 warmups", "cases": []}
    for count in (0, 16, 6300):
        rows = _rows(np.random.default_rng(17).uniform(-12.0, -2.0, 25200))
        rows[np.linspace(0, len(rows) - 1, count, dtype=int), 8] = 2.0
        assert legacy(rows) == optimized(rows)
        samples = {"legacy": [], "numpy_prefilter": []}
        for function in (legacy, optimized):
            for _ in range(3):
                function(rows)
        for batch in range(7):
            functions = (("legacy", legacy), ("numpy_prefilter", optimized))
            for name, function in functions[::1 if batch % 2 == 0 else -1]:
                start = time.perf_counter()
                for _ in range(30):
                    function(rows)
                samples[name].append((time.perf_counter() - start) * 1000.0 / 30)
        old, new = statistics.median(samples["legacy"]), statistics.median(samples["numpy_prefilter"])
        report["cases"].append({"retained": count, "scalar_calls_before": len(rows),
                                "scalar_calls_after": count, "legacy_ms": old,
                                "numpy_prefilter_ms": new, "speedup": old / new})
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if "--benchmark" in sys.argv:
        _benchmark()
    else:
        unittest.main()
