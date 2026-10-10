"""Parser for the ``PDL1`` vehicle telemetry used by rm-native-viewer.

The payload is carried inside the existing ``CustomByteBlock`` field.  This
module intentionally does not add a new wire message or reinterpret the
300-byte ``0x0310`` H.264 packet format; it only decodes the documented
little-endian telemetry structure when its magic and length are valid.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct


TELEMETRY_MAGIC = b"PDL1"
TELEMETRY_VERSION = 1
TELEMETRY_MIN_BYTES = 74
TELEMETRY_FLAG_CAMERA_ONLINE = 1 << 0
TELEMETRY_FLAG_GIMBAL_ONLINE = 1 << 1

GIMBAL_MODE_NAMES = {
    0: "IDLE",
    1: "AUTO_AIM",
    2: "SMALL_BUFF",
    3: "BIG_BUFF",
}

VIDEO_0310_PACKET_BYTES = 300
VIDEO_0310_HEADER_BYTES = 3
VIDEO_0310_PAYLOAD_BYTES = 297
VIDEO_0310_FLAG_RESET = 1 << 0
VIDEO_0310_PAYLOAD_BYTES_MSB_MASK = 1 << 1
VIDEO_0310_RESERVED_MASK = 0xFC


@dataclass(frozen=True, slots=True)
class VehicleTelemetry:
    version: int
    struct_bytes: int
    flags: int
    unix_ms: int
    frame_seq: int
    image_width: int
    image_height: int
    fps_x100: int
    gain_x100: int
    exposure_us: int
    gimbal_mode: int
    bullet_count: int
    yaw: float
    yaw_vel: float
    pitch: float
    pitch_vel: float
    bullet_speed: float
    quaternion: tuple[float, float, float, float]
    status_text: str

    @property
    def camera_online(self) -> bool:
        return bool(self.flags & TELEMETRY_FLAG_CAMERA_ONLINE)

    @property
    def gimbal_online(self) -> bool:
        return bool(self.flags & TELEMETRY_FLAG_GIMBAL_ONLINE)

    @property
    def fps(self) -> float:
        return self.fps_x100 / 100.0

    @property
    def gain(self) -> float:
        return self.gain_x100 / 100.0

    @property
    def gimbal_mode_name(self) -> str:
        return GIMBAL_MODE_NAMES.get(self.gimbal_mode, "UNKNOWN")


@dataclass(frozen=True, slots=True)
class Video0310Chunk:
    codec: str
    flags: int
    sequence: int
    sequence_modulus: int
    stream_ms: int
    payload: bytes

    @property
    def reset(self) -> bool:
        return bool(self.flags & VIDEO_0310_FLAG_RESET)


# 4s magic, H version, H struct bytes, I flags, Q unix ms, I frame sequence,
# 4H image/fps/gain, I exposure, B mode, B reserved, H bullets, 9f attitude.
_FIXED = struct.Struct("<4sHHIQIHHHHIBBH9f")
TELEMETRY_FIXED_BYTES = _FIXED.size  # 76 bytes; Rust's outer guard is 74.


def parse_vehicle_telemetry(data: bytes | bytearray | memoryview) -> VehicleTelemetry | None:
    """Decode one strict ``PDL1`` record, returning ``None`` when malformed.

    The validation mirrors rm-native-viewer's Rust parser: version 1 only,
    a declared structure length of at least 74 bytes and no read beyond the
    supplied block.  Non-finite floats are rejected here because downstream
    aiming math must fail closed rather than propagate NaN/Inf.
    """

    view = memoryview(data)
    if len(view) < TELEMETRY_MIN_BYTES:
        return None
    try:
        unpacked = _FIXED.unpack_from(view, 0)
    except (struct.error, TypeError, ValueError):
        return None
    (
        magic,
        version,
        struct_bytes,
        flags,
        unix_ms,
        frame_seq,
        image_width,
        image_height,
        fps_x100,
        gain_x100,
        exposure_us,
        gimbal_mode,
        _reserved,
        bullet_count,
        yaw,
        yaw_vel,
        pitch,
        pitch_vel,
        bullet_speed,
        q0,
        q1,
        q2,
        q3,
    ) = unpacked
    if magic != TELEMETRY_MAGIC or version != TELEMETRY_VERSION:
        return None
    if struct_bytes < TELEMETRY_MIN_BYTES or struct_bytes > len(view):
        return None
    floats = (yaw, yaw_vel, pitch, pitch_vel, bullet_speed, q0, q1, q2, q3)
    if not all(math.isfinite(value) for value in floats):
        return None
    status_raw = bytes(view[TELEMETRY_FIXED_BYTES:struct_bytes])
    # Rust's decoder treats the text tail as a NUL-terminated, lossy UTF-8
    # status string.  Python's replacement decoder provides the same safety.
    status_text = status_raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
    return VehicleTelemetry(
        version=version,
        struct_bytes=struct_bytes,
        flags=flags,
        unix_ms=unix_ms,
        frame_seq=frame_seq,
        image_width=image_width,
        image_height=image_height,
        fps_x100=fps_x100,
        gain_x100=gain_x100,
        exposure_us=exposure_us,
        gimbal_mode=gimbal_mode,
        bullet_count=bullet_count,
        yaw=yaw,
        yaw_vel=yaw_vel,
        pitch=pitch,
        pitch_vel=pitch_vel,
        bullet_speed=bullet_speed,
        quaternion=(q0, q1, q2, q3),
        status_text=status_text,
    )


def parse_video_0310_chunk(data: bytes | bytearray | memoryview) -> Video0310Chunk | None:
    """Parse rm-native-viewer's exact fixed 300-byte H.264 transport packet.

    This is intentionally separate from :func:`parse_vehicle_telemetry`; a
    video chunk must never be interpreted as gimbal metadata or vice versa.
    """

    payload = bytes(data)
    if len(payload) != VIDEO_0310_PACKET_BYTES:
        return None
    header = payload[0]
    if header & VIDEO_0310_RESERVED_MASK:
        return None
    length = payload[2] | (int(bool(header & VIDEO_0310_PAYLOAD_BYTES_MSB_MASK)) << 8)
    if length > VIDEO_0310_PAYLOAD_BYTES:
        return None
    return Video0310Chunk(
        codec="h264",
        flags=header & VIDEO_0310_FLAG_RESET,
        sequence=payload[1],
        sequence_modulus=256,
        stream_ms=0,
        payload=payload[VIDEO_0310_HEADER_BYTES:VIDEO_0310_HEADER_BYTES + length],
    )


def find_h264_sps_offset(data: bytes | bytearray | memoryview) -> int | None:
    """Return the Annex-B start-code offset of the first SPS NAL (type 7).

    rm-native-viewer intentionally stops feeding ffmpeg after a 0x0310
    sequence gap or stream-reset flag, then resumes at the next SPS.  Starting
    in the middle of a NAL can poison ffmpeg's parser even when an IDR arrives
    later, so this recovery gate is part of the transport contract rather than
    merely a visual optimisation.
    """

    payload = bytes(data)
    index = 0
    while index + 3 < len(payload):
        three_byte = payload[index:index + 3] == b"\x00\x00\x01"
        four_byte = (
            index + 4 < len(payload)
            and payload[index:index + 4] == b"\x00\x00\x00\x01"
        )
        if three_byte:
            if payload[index + 3] & 0x1F == 7:
                return index
            index += 3
        elif four_byte:
            if payload[index + 4] & 0x1F == 7:
                return index
            index += 4
        else:
            index += 1
    return None
