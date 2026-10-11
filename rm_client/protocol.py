from __future__ import annotations

from dataclasses import dataclass
import struct


SOF = 0xA5
CRC8_INIT = 0xFF
CRC16_INIT = 0xFFFF
# Largest documented RM2026 serial payload (0x0310 CustomByteBlock).
# Reject impossible headers before waiting for their advertised payload.
MAX_REFEREE_PAYLOAD = 300


@dataclass
class RefereeFrame:
    cmd_id: int
    data: bytes
    seq: int


class RefereeFrameCodec:
    """大疆 RoboMaster 裁判系统串口帧编解码器。

    线缆传输格式：
    SOF(0xA5) + data_length(uint16 LE) + seq(uint8) + CRC8 +
    cmd_id(uint16 LE) + data + CRC16(uint16 LE).
    """

    def __init__(self) -> None:
        self.seq = 0

    def encode(self, cmd_id: int, data: bytes = b"", seq: int | None = None) -> bytes:
        data = bytes(data)
        if not 0 <= cmd_id <= 0xFFFF:
            raise ValueError("cmd_id must fit uint16")
        if len(data) > MAX_REFEREE_PAYLOAD:
            raise ValueError("referee payload exceeds 300 bytes")
        seq_value = self._next_seq() if seq is None else seq & 0xFF
        header = bytearray([SOF])
        header.extend(len(data).to_bytes(2, "little"))
        header.append(seq_value)
        header.append(crc8(bytes(header)))
        frame = bytearray(header)
        frame.extend(cmd_id.to_bytes(2, "little"))
        frame.extend(data)
        frame.extend(crc16(bytes(frame)).to_bytes(2, "little"))
        return bytes(frame)

    def decode(self, stream: bytes) -> list[RefereeFrame]:
        """解码全部完整帧（保持旧接口，返回帧列表）。"""
        frames, _consumed = self.decode_with_consumed(stream)
        return frames

    def decode_with_consumed(self, stream: bytes) -> tuple[list[RefereeFrame], int]:
        """解码完整帧，并返回已消费字节偏移（供流式读取保留半帧）。"""
        frames: list[RefereeFrame] = []
        index = 0
        while index < len(stream):
            if stream[index] != SOF:
                index += 1
                continue
            if index + 5 > len(stream):
                break
            header = stream[index : index + 5]
            if crc8(header[:4]) != header[4]:
                index += 1
                continue
            data_len = int.from_bytes(header[1:3], "little")
            if data_len > MAX_REFEREE_PAYLOAD:
                index += 1
                continue
            total_len = 5 + 2 + data_len + 2
            if index + total_len > len(stream):
                break
            frame_bytes = stream[index : index + total_len]
            expected = int.from_bytes(frame_bytes[-2:], "little")
            if crc16(frame_bytes[:-2]) != expected:
                index += 1
                continue
            cmd_id = int.from_bytes(frame_bytes[5:7], "little")
            data = frame_bytes[7:-2]
            frames.append(RefereeFrame(cmd_id=cmd_id, data=data, seq=header[3]))
            index += total_len
        return frames, index

    def _next_seq(self) -> int:
        value = self.seq & 0xFF
        self.seq = (self.seq + 1) & 0xFF
        return value


def crc8(data: bytes) -> int:
    crc = CRC8_INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x01:
                crc = ((crc >> 1) ^ 0x8C) & 0xFF
            else:
                crc = (crc >> 1) & 0xFF
    return crc & 0xFF


def crc16(data: bytes) -> int:
    crc = CRC16_INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = ((crc >> 1) ^ 0x8408) & 0xFFFF
            else:
                crc = (crc >> 1) & 0xFFFF
    return crc & 0xFFFF


def encode_custom_control_30(
    *,
    seq: int,
    vx: float,
    vy: float,
    wz: float,
    speed_limit: int,
    power_limit: int,
    spin_mode: bool,
) -> bytes:
    """官方 CustomControl / cmd_id 0x0311 使用的紧凑载荷。

    官方容器最多允许 30 字节。真实机器人固件协议定稿前，
    这里先保留一份已记录的队内 12 字节本地格式，并补零到 30 字节。
    """

    flags = 0x01 if spin_mode else 0x00
    payload = struct.pack(
        "<BhhhHHB",
        seq & 0xFF,
        clamp_i16(round(vx * 1000)),
        clamp_i16(round(vy * 1000)),
        clamp_i16(round(wz * 1000)),
        max(0, min(0xFFFF, int(speed_limit))),
        max(0, min(0xFFFF, int(power_limit))),
        flags,
    )
    return payload.ljust(30, b"\x00")


def clamp_i16(value: int) -> int:
    return max(-32768, min(32767, value))
