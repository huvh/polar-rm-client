"""角度出口线格式适配；VT02 元数据和兼容序号仅在本模块解释。"""
from __future__ import annotations

import math
import struct

from ...protocol import RefereeFrameCodec, crc16
from ..controller_angle_protocol import ANGLE_CMD, angle_payload

LEGACY_ANGLE_ROUTES = ("Legacy Receiver", "VT02 Encoder")


def vt02_encoder_payload(data: bytes, sequence: int) -> bytes:
    """VT02 仅输出 cmd + 24B；用空闲关节槽保留源序号和端到端 CRC。

    此出口只接受单编码器 J0，其余关节必须为零。所有元数据仍是档案范围内的
    精确 binary32 数值，车端验证后还原为 J0 + 五个零，不能用于六轴机械臂。
    """
    angles, _ = angle_payload(data)
    if not 0 <= angles[0] < 2 * math.pi or any(value != 0 for value in angles[1:]):
        raise ValueError("VT02 Encoder requires J0 in [0, 2pi) and all other joints zero")
    if not 0 <= sequence <= 255:
        raise ValueError("VT02 Encoder requires an 8-bit source sequence")
    payload = bytearray(struct.pack("<6f", angles[0], sequence / 256.0, 0, 3.25, -3.25, 1.0))
    checksum = crc16(b"\x02\x03" + payload[:8] + payload[12:24])
    struct.pack_into("<f", payload, 8, -checksum / 32768.0)
    return bytes(payload) + bytes(6)


def encode_angle_forward_frame(payload: bytes, sequence: int, output_route: str) -> bytes:
    """根据已选出口生成完整 A5 帧，通用转发器只持有授权和样本时效。"""
    if output_route == "VT02 Encoder":
        payload = vt02_encoder_payload(payload, sequence)
        # 本机 VT02 固件仅接受此兼容头；原始序号保留在受 CRC 保护的负载中。
        sequence = 0x13
    return RefereeFrameCodec().encode(ANGLE_CMD, payload, seq=sequence)
