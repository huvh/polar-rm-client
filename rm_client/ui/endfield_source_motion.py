"""Pure scalar sampling of exported Unity keyframes; no Qt or asset I/O.

The caller supplies ``m_Curve`` keys, not a clip/curve wrapper. Times outside
the keys are clamped; clip looping and pre/post-infinity modes belong to the
caller. This evaluates the authored scalar curve in Python double precision,
not Unity's native float32 rounding or editor tangent generation.

Unity's weight flags and default unweighted handle length are documented at:
https://docs.unity3d.com/ScriptReference/WeightedMode.html
https://docs.unity3d.com/ScriptReference/Keyframe-inWeight.html
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from numbers import Integral, Real
from typing import NamedTuple


__all__ = ("sample_weighted_curve",)

_DEFAULT_WEIGHT = 1.0 / 3.0


class _Key(NamedTuple):
    time: float
    value: float
    in_slope: float
    out_slope: float
    in_weight: float
    out_weight: float


def _number(value: object, field: str, *, slope: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field} must be a real number (not bool)")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} is not representable as a float") from exc
    if math.isnan(result) or (not slope and not math.isfinite(result)):
        raise ValueError(f"{field} must be {'non-NaN' if slope else 'finite'}")
    return result


def _validate_keys(keys: Sequence[Mapping[str, object]]) -> list[_Key]:
    if isinstance(keys, (str, bytes, bytearray)) or not isinstance(keys, Sequence):
        raise TypeError("keys must be a non-empty sequence of keyframe mappings")
    if not keys:
        raise ValueError("keys must not be empty")
    result = []
    for index, key in enumerate(keys):
        prefix = f"keys[{index}]"
        if not isinstance(key, Mapping):
            raise TypeError(f"{prefix} must be a keyframe mapping")
        for field in ("time", "value", "inSlope", "outSlope"):
            if field not in key:
                raise ValueError(f"{prefix}.{field} is required")
        mode = key.get("weightedMode", 0)
        if isinstance(mode, bool) or not isinstance(mode, Integral):
            raise TypeError(f"{prefix}.weightedMode must be an integer in 0..3")
        if mode not in (0, 1, 2, 3):
            raise ValueError(f"{prefix}.weightedMode must be in 0..3")
        weights = []
        for field, flag in (("inWeight", 1), ("outWeight", 2)):
            if mode & flag and field not in key:
                raise ValueError(f"{prefix}.{field} is required by weightedMode")
            weight = _number(key.get(field, _DEFAULT_WEIGHT), f"{prefix}.{field}")
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"{prefix}.{field} must be in [0, 1]")
            # Inactive serialized weights (often zero) are NOT handle lengths.
            weights.append(weight if mode & flag else _DEFAULT_WEIGHT)
        parsed = _Key(
            _number(key["time"], f"{prefix}.time"),
            _number(key["value"], f"{prefix}.value"),
            _number(key["inSlope"], f"{prefix}.inSlope", slope=True),
            _number(key["outSlope"], f"{prefix}.outSlope", slope=True),
            *weights,
        )
        if result:
            duration = parsed.time - result[-1].time
            if duration <= 0.0 or not math.isfinite(duration):
                raise ValueError(f"{prefix}.time must increase by a finite positive interval")
        result.append(parsed)
    return result


def _time_residual(u: float, time: float, outgoing: float, incoming: float) -> float:
    """B_x(u) - time, without subtracting nearly equal numbers near a flat x.

    The normalized x controls are (0, outgoing, 1-incoming, 1). They stay
    monotone for all valid weights, even when the two inner controls cross.
    In particular, weights (1, 1) have a stationary point at u=1/2; a centered
    polynomial preserves its small cubic residual instead of rounding x to 1/2.
    """
    if u > 0.75:
        return -_time_residual(1.0 - u, 1.0 - time, incoming, outgoing)
    cubic = 3.0 * (outgoing + incoming) - 2.0
    if u < 0.25:
        return u * (3.0 * outgoing + u * (
            3.0 * (1.0 - incoming) - 6.0 * outgoing + cubic * u
        )) - time
    centered = u - 0.5
    variable = centered * (
        0.75 * ((1.0 - outgoing) + (1.0 - incoming))
        + centered * (1.5 * (incoming - outgoing) + cubic * centered)
    )
    return math.fsum((variable, 0.5 - time, 0.375 * (outgoing - incoming)))


def _solve_time(time: float, outgoing: float, incoming: float) -> float:
    if outgoing == _DEFAULT_WEIGHT and incoming == _DEFAULT_WEIGHT:
        return time  # B_x(u) = u: the ordinary cubic Hermite case.
    low, high = 0.0, 1.0
    # Bracketing needs no derivative division, including zero-length handles
    # and the (1, 1) stationary point. Never fall back to using time as u.
    for _ in range(64):
        u = (low + high) * 0.5
        if u == low or u == high:
            return u
        residual = _time_residual(u, time, outgoing, incoming)
        if residual == 0.0:
            return u
        if residual < 0.0:
            low = u
        else:
            high = u
    return (low + high) * 0.5


def _bezier_value(p0: float, p1: float, p2: float, p3: float, u: float) -> float:
    # de Casteljau avoids the large subtractive Hermite basis coefficients.
    v = 1.0 - u
    a, b, c = v * p0 + u * p1, v * p1 + u * p2, v * p2 + u * p3
    return v * (v * a + u * b) + u * (v * b + u * c)


def sample_weighted_curve(keys: Sequence[Mapping[str, object]], seconds: float) -> float:
    """Sample raw Unity scalar keys without mutating or sorting them.

    Required fields: time, value, inSlope, outSlope. weightedMode defaults to
    0; bits 1 (In) / 2 (Out) enable the corresponding mandatory [0, 1] weight.
    Disabled sides use 1/3, independently for each key and side. A segment uses
    ONLY the left key's outSlope/outWeight and the right key's inSlope/inWeight.

    Finite times/values and strictly increasing key times are required. Slopes
    may be +/-infinity to encode a step: hold the left value on the open
    interval, but return the exact right value at its key time. Outside the
    range (including a one-key curve), hold the endpoint value. Values are not
    clamped, so authored overshoot remains possible.

    TypeError rejects wrong types; ValueError rejects missing fields, NaN,
    invalid modes/weights/order and arithmetic overflow. All key fields are
    validated before endpoint clamping, including inactive supplied weights.
    No files, Qt state, caches, global mutable state or devices are involved.
    """
    seconds = _number(seconds, "seconds")
    parsed = _validate_keys(keys)
    if seconds <= parsed[0].time:
        return parsed[0].value
    for index, (left, right) in enumerate(zip(parsed, parsed[1:])):
        if seconds > right.time:
            continue
        if seconds == right.time:
            return right.value
        if math.isinf(left.out_slope) or math.isinf(right.in_slope):
            return left.value
        duration = right.time - left.time
        p1 = left.value + (duration * left.out_weight) * left.out_slope
        p2 = right.value - (duration * right.in_weight) * right.in_slope
        if not (math.isfinite(p1) and math.isfinite(p2)):
            raise ValueError(f"segment {index} Bezier control values overflow")
        time = (seconds - left.time) / duration
        u = _solve_time(time, left.out_weight, right.in_weight)
        value = _bezier_value(left.value, p1, p2, right.value, u)
        if not math.isfinite(value):
            raise ValueError(f"segment {index} sampled value overflows")
        return value
    return parsed[-1].value
