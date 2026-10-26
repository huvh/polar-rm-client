"""旧接收端 DUML 编解码：状态/信道白名单、严格校验及 A5 角度外封装。"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from ...protocol import crc8, crc16


CHANNEL_FREQUENCIES = {1: 0x09F2, 2: 0x0A08, 3: 0x0A1E,
                       4: 0x0A34, 5: 0x0A4A, 6: 0x0A60}
HOST_ADDRESS = 0x8A  # module type 10, id 4
RECEIVER_ADDRESS = 0x0E  # module type 14, id 0
QUERY_STATUS = 0x61
PUSH_STATUS = 0x40
SET_CONFIG = 0x0D


def _crc(data: bytes, initial: int, polynomial: int) -> int:
    value = initial
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value


def encode_receiver_command(command: int, payload: bytes = b"") -> bytes:
    """只允许本适配所需的两种官方请求；序号与官方相同固定为零。"""
    if not ((command == QUERY_STATUS and not payload) or
            (command == SET_CONFIG and len(payload) == 6 and payload[0] == 15
             and payload[3] == 17 and payload[1:3] == payload[4:6]
             and int.from_bytes(payload[1:3], "little") in CHANNEL_FREQUENCIES.values())):
        raise ValueError("Unsupported legacy receiver command/payload")
    header = bytearray(struct.pack("<BH", 0x55, (13 + len(payload)) | 0x0400))
    header.append(_crc(header, 0x77, 0x8C))
    header.extend(struct.pack("<BBHBBB", HOST_ADDRESS, RECEIVER_ADDRESS, 0, 0x40, 9, command))
    header.extend(payload)
    return bytes(header) + struct.pack("<H", _crc(header, 0x3692, 0x8408))


def channel_payload(channel: int) -> bytes:
    """官方 SET_CONFIG_INFO：configuration_id、freq_id、camp_freq、freq。"""
    if channel not in CHANNEL_FREQUENCIES:
        raise ValueError("Legacy channel must be 1..6")
    frequency = CHANNEL_FREQUENCIES[channel]
    return struct.pack("<BHBH", 15, frequency, 17, frequency)


@dataclass(frozen=True)
class ReceiverFrame:
    sender: int
    receiver: int
    sequence: int
    flags: int
    command_set: int
    command: int
    payload: bytes
    packet: bytes = b""


class ReceiverFrameParser:
    """有界增量 DUML V1 解析；坏校验后重新定位，保留未完成的半帧。"""
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.invalid_frames = 0

    def feed(self, data: bytes) -> list[ReceiverFrame]:
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            if self.buffer[0] != 0x55:
                del self.buffer[0]
                continue
            if len(self.buffer) < 4:
                break
            word = int.from_bytes(self.buffer[1:3], "little")
            length = word & 0x03FF
            if word >> 10 != 1 or not 13 <= length <= 1023 or _crc(self.buffer[:3], 0x77, 0x8C) != self.buffer[3]:
                self.invalid_frames += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < length:
                break
            packet = bytes(self.buffer[:length])
            if _crc(packet[:-2], 0x3692, 0x8408) != int.from_bytes(packet[-2:], "little"):
                self.invalid_frames += 1
                del self.buffer[0]
                continue
            sender, receiver, sequence, flags, command_set, command = struct.unpack_from("<BBHBBB", packet, 4)
            frames.append(ReceiverFrame(sender, receiver, sequence, flags, command_set, command, packet[11:-2], packet))
            del self.buffer[:length]
        return frames


def status_parameters(frame: ReceiverFrame) -> dict[int, int] | None:
    """仅接受接收端到本机的 54 字节参数响应，不把任意串口流量算作就绪。"""
    if (frame.sender != RECEIVER_ADDRESS or frame.receiver != HOST_ADDRESS
            or frame.command_set != 9 or frame.command != PUSH_STATUS
            or len(frame.payload) != 54 or frame.flags != 0):
        return None
    parameters = {key: value for key, value in struct.iter_unpack("<BH", frame.payload)
                  if 1 <= key <= 18}
    return parameters if 15 in parameters else None


def encode_receiver_angles(frame: bytes) -> bytes:
    """将完整 A5/0302/30B 封装为官方 VideoSerialPortThread 的 09/63 请求。

    自定义数据发往模块 type=23/id=3（0x77），不同于状态查询的 0x0E。
    接收端 UART 速率沿用现有连接，不能直接往 COM14 写裸 A5 帧。
    """
    frame = bytes(frame)
    if (len(frame) != 39 or frame[:3] != b"\xa5\x1e\x00"
            or frame[5:7] != b"\x02\x03" or crc8(frame[:4]) != frame[4]
            or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little")):
        raise ValueError("Legacy angle output requires a valid A5/0302/30-byte frame")
    header = bytearray(struct.pack("<BH", 0x55, 52 | 0x0400))
    header.append(_crc(header, 0x77, 0x8C))
    header.extend(struct.pack("<BBHBBB", 0x8A, 0x77, 0, 0x40, 9, 0x63))
    packet = bytes(header) + frame
    return packet + struct.pack("<H", _crc(packet, 0x3692, 0x8408))
