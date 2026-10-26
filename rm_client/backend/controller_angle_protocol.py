"""实体控制器六轴角度的纯协议契约；不依赖设备、授权状态或图传实现。"""
from __future__ import annotations

import math
import struct

ANGLE_CMD = 0x0302
# Proven source clamps in robot_param_engineer_controller.h + its observer.
# J4/J5 are ALREADY coupled source positions; never invert them again here.
ANGLE_BOUNDS = ((-2 * math.pi, 2 * math.pi), (-1.10, 1.20), (-2.50, 0.0),
                (-4 * math.pi, 4 * math.pi), (-4.5 * math.pi, 4.5 * math.pi),
                (-4.5 * math.pi, 4.5 * math.pi))
ANGLE_TOLERANCE = 1e-5  # Binary32 rounding at source clamp boundaries, radians.


def angle_payload(data: bytes) -> tuple[tuple[float, ...], bytes]:
    """Validate the known six-axis contract; never forward source padding.

    Old firmware sends 30 bytes from a 28-byte object. The last six bytes
    are not part of the six-angle contract and can contain out-of-bounds data.
    Units/axis signs remain exactly those chosen by the source firmware.
    """
    data = bytes(data)
    if len(data) != 30:
        raise ValueError("controller angles require exactly 30 bytes")
    angles = struct.unpack("<6f", data[:24])
    if not all(math.isfinite(value) for value in angles):
        raise ValueError("controller angles must be finite")
    if any(not low - ANGLE_TOLERANCE <= value <= high + ANGLE_TOLERANCE
           for value, (low, high) in zip(angles, ANGLE_BOUNDS)):
        raise ValueError("angles outside the pinned engineer controller source bounds")
    return angles, data[:24] + bytes(6)
