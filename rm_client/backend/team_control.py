"""PRM1 team payloads inside CustomControl, independent of referee year."""
from __future__ import annotations
import struct

# Team-defined payload carried inside official CustomControl.data (<=30 B).
# Robot firmware must implement this exact schema before live output is armed.
TEAM_CONTROL_MAGIC = b"PRM1"
TEAM_CONTROL_VERSION = 1
TEAM_CONTROL_VISION = 1
TEAM_CONTROL_SPIN = 2
# kind=3：图传键鼠（0x0311 的 30 字节里前 26 字节是这条），
# 与固件 application/typedef/host_km_link.h 的 prm1_km_cmd_t 逐字节对齐。
# 两边必须一起改，tools/firmware/km_link/test_km_payload_layout.py 会把
# C 结构体编出来量每个字段的偏移，再和这里的 struct 格式对表。
TEAM_CONTROL_KM = 3
TEAM_CONTROL_KM_FORMAT = "<4sBBHHhhhBB8s"
TEAM_CONTROL_KM_SIZE = 26
# Compatibility names retained for existing integrations.
VISION_CONTROL_MAGIC = TEAM_CONTROL_MAGIC
VISION_CONTROL_VERSION = TEAM_CONTROL_VERSION


def encode_km_control_payload(
    *,
    sequence: int,
    keyboard_value: int = 0,
    mouse_x: int = 0,
    mouse_y: int = 0,
    mouse_z: int = 0,
    left_button: bool = False,
    right_button: bool = False,
    middle_button: bool = False,
    alive: bool = True,
) -> bytes:
    """Encode the team KM payload carried inside CustomControl -> 0x0311.

    Layout ``<4sBBHHhhhBB8s`` (26 bytes): magic, version, kind, sequence,
    keyboard bitmap, mouse x/y/z deltas, button bits, alive flag, reserved.
    Field order and semantics mirror the firmware struct in
    ``application/typedef/host_km_link.h`` and the DBUS key/mouse fields,
    so a value that arrives as ``rc_ctrl.key.v`` from a DT7 keyboard means
    the same bit here.
    """

    def clamp16(value: int) -> int:
        return max(-32768, min(32767, int(value)))

    buttons = (0x01 if left_button else 0) | (0x02 if right_button else 0) | (
        0x04 if middle_button else 0)

    return struct.pack(
        TEAM_CONTROL_KM_FORMAT,
        TEAM_CONTROL_MAGIC,
        TEAM_CONTROL_VERSION,
        TEAM_CONTROL_KM,
        int(sequence) & 0xFFFF,
        int(keyboard_value) & 0xFFFF,
        clamp16(mouse_x),
        clamp16(mouse_y),
        clamp16(mouse_z),
        buttons & 0xFF,
        0x01 if alive else 0x00,
        b"\x00" * 8,
    )


def decode_km_control_payload(data: bytes) -> dict | None:
    """Mirror the firmware PRM1 gate and byte order, independent of referee year."""
    data = bytes(data)
    if not TEAM_CONTROL_KM_SIZE <= len(data) <= 30:
        return None
    (magic, version, kind, seq, keys, mx, my, mz, buttons, flags,
     _res) = struct.unpack(TEAM_CONTROL_KM_FORMAT, data[:TEAM_CONTROL_KM_SIZE])
    if magic != TEAM_CONTROL_MAGIC or version != TEAM_CONTROL_VERSION or kind != TEAM_CONTROL_KM:
        return None
    if buttons & ~0x07 or flags & ~0x01 or any(_res) or any(data[TEAM_CONTROL_KM_SIZE:]):
        return None
    return {
        "sequence": seq,
        "keyboard_value": keys,
        "mouse_x": mx,
        "mouse_y": my,
        "mouse_z": mz,
        "left_button": bool(buttons & 0x01),
        "right_button": bool(buttons & 0x02),
        "middle_button": bool(buttons & 0x04),
        "alive": bool(flags & 0x01),
    }


def encode_vision_control_payload(
    *,
    sequence: int,
    yaw_deg: float,
    pitch_deg: float,
    target_id: int = 0,
    tracking: bool = False,
    fire: bool = False,
) -> bytes:
    """Encode POLAR's documented team gimbal payload (14 bytes).

    Layout ``<4sBBHhhBB``: magic, version, kind, sequence, yaw/pitch in
    centidegrees, target id, flags. Desktop call sites force fire false.
    """

    flags = (0x01 if tracking else 0x00) | (0x02 if fire else 0x00)

    def centidegrees(value: float) -> int:
        return max(-32768, min(32767, int(round(float(value) * 100.0))))

    return struct.pack(
        "<4sBBHhhBB",
        TEAM_CONTROL_MAGIC,
        TEAM_CONTROL_VERSION,
        TEAM_CONTROL_VISION,
        int(sequence) & 0xFFFF,
        centidegrees(yaw_deg),
        centidegrees(pitch_deg),
        int(target_id) & 0xFF,
        flags,
    )


def encode_spin_control_payload(
    *,
    sequence: int,
    enabled: bool,
    direction: str = "Auto",
    speed_dps: float = 420.0,
    power_guard: bool = True,
) -> bytes:
    """Encode the documented POLAR team chassis-spin payload (12 bytes).

    Layout ``<4sBBHhBB``: magic, version, kind, sequence, non-negative
    speed in degrees/second, direction (0 auto / 1 CW / 2 CCW), and flags
    (bit 0 enabled, bit 1 power guard).  It is transported only inside the
    official MQTT ``CustomControl`` message; it is never a 115200 serial frame.
    """

    direction_code = {"AUTO": 0, "CW": 1, "CCW": 2}.get(str(direction).upper(), 0)
    speed = max(0, min(32767, int(round(float(speed_dps)))))
    flags = (0x01 if enabled else 0x00) | (0x02 if power_guard else 0x00)
    return struct.pack(
        "<4sBBHhBB",
        TEAM_CONTROL_MAGIC,
        TEAM_CONTROL_VERSION,
        TEAM_CONTROL_SPIN,
        int(sequence) & 0xFFFF,
        speed,
        direction_code,
        flags,
    )

