#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""DT7 直连出口：把键鼠直接写进遥控器那条 DJI USB Virtual COM（`VID_FFF0&PID_0008`）。

与 `cc_link.py`（0x0306 走官方选手端）的区别
--------------------------------------------
`cc_link` 是"借大疆客户端的手"；本模块是我们**自己当那个发键鼠的人**，
不依赖官方选手端在跑 —— 这才是自定义客户端该有的形态。

已经核实 vs 仍是候选（这个区分很重要，别当全懂）
------------------------------------------------
**已核实（来自大疆 12.x 选手端二进制，工具链与地址见 README 第 20 节）**：
  1. 帧编解码逻辑就是厂商 `CommunicationCompiler.Encoder_A5_WithTail`
     （`D:\rmbuild\decomp\CommunicationCompiler.cs`）：
     `sof=165(0xA5)`、`datalen = payload.Length - 2`（**不含 cmd 那 2 字节**）、
     `seq` 自增、`crc8` 覆盖帧头前 4 字节、`crc16` 覆盖 帧头+cmd+data、
     CRC 初值 `CRC8_INIT=0xFF / CRC16_INIT=0xFFFF`、表驱动；
  2. `FrameHeader{sof:1, datalen:2, seq:1, crc8:1}`（Pack=1）；
  3. 命令号是 **16 位两半字节**：`DJI_PRO_CMD_T` 位域
     `Cmd_Set = bits0-7、Cmd_Id = bits8-15`（小端 ushort ⇒ `cmd = (Cmd_Id<<8)|Cmd_Set`）；
  4. 键位位序 `KeyBoard` 枚举（W=1…SHIFT=16 CTRL=32 Q=64 E=128 …B=32768）
     —— 与我们固件/`KEYBOARD_BITS` 一致；
  5. 键鼠内容对象的字段顺序（12.x `dump.cs` 的 `Input_Device_Status`：
     mouse_x/y/z int16、left、right、keyboard_value uint16、mid_button）。

**仍是候选（必须现场确认，profile 里可改）**：
  a. 键鼠那条命令的 `Cmd_Set` 值；`Cmd_Id` 我取 17，因为它在厂商的
     `Video2025MsgID` 里就是 `CMD_ID_Keyboard = 17`，但那张表名字指的是**图传模块**，
     DT7 口是否同一编号体系未经证实；
  b. 载荷是否就是 `Input_Device_Status` 那几个字段（会不会还带 seq/version 前缀）。
⇒ 所以本模块**默认关闭**、写串口要显式确认，并提供 `decode_dt7_frame()`：
   现场抓一次包就能把候选值直接对出来，不用改代码。
"""
from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..protocol import crc16, crc8

ROOT = Path(__file__).resolve().parents[2]
PROFILE_FILE = ROOT / "configs" / "dt7_profile.json"

SOF = 0xA5
HEADER_SIZE = 5           # sof + datalen(2) + seq + crc8
CRC16_SIZE = 2
CMD_SIZE = 2
DEFAULT_KEYS = {"cmd_set": 0, "cmd_id_keyboard": 17,
                "payload_layout": "<hhhBBHB", "baudrate": 115200, "max_hz": 30.0}


def load_profile(path: str | None = None) -> dict:
    """读 profile；缺失/坏/字段非法一律退回默认，**不许因为配置把链路打瘫**。"""
    prof = dict(DEFAULT_KEYS)
    fp = Path(path) if path else PROFILE_FILE
    try:
        raw = json.loads(fp.read_text(encoding="utf-8-sig"))
    except OSError:
        return prof
    except Exception:
        return prof
    if not isinstance(raw, dict):
        return prof
    for key in ("cmd_set", "cmd_id_keyboard"):
        v = raw.get(key)
        if isinstance(v, int) and 0 <= v <= 0xFF:
            prof[key] = v
    layout = raw.get("payload_layout")
    if isinstance(layout, str):
        try:
            struct.calcsize(layout)          # 能算 size 才敢收
            size = struct.calcsize(layout)
            if 0 < size <= 24:
                prof["payload_layout"] = layout
        except Exception:
            pass
    baud = raw.get("baudrate")
    if isinstance(baud, int) and 9600 <= baud <= 921600:
        prof["baudrate"] = baud
    hz = raw.get("max_hz")
    if isinstance(hz, (int, float)) and 1 <= float(hz) <= 200:
        prof["max_hz"] = float(hz)
    return prof


def pack_cmd(cmd_set: int, cmd_id: int) -> bytes:
    """DJI_PRO_CMD_T：Cmd_Set 占低字节、Cmd_Id 占高字节（位域已核实）。"""
    if not (0 <= cmd_set <= 0xFF and 0 <= cmd_id <= 0xFF):
        raise ValueError(f"cmd_set/cmd_id 都要是 1 字节：{cmd_set!r} {cmd_id!r}")
    return struct.pack("<H", cmd_set | (cmd_id << 8))


def build_frame(cmd_set: int, cmd_id: int, payload: bytes, seq: int) -> bytes:
    """跟厂商 Encoder_A5_WithTail 同构的一帧。

    `datalen` 只算 cmd 之后的载荷（厂商写法是 `payload.Length - 2`），
    `crc8` 覆盖帧头前 4 字节，`crc16` 覆盖 帧头+cmd+载荷。
    """
    payload = bytes(payload)
    if len(payload) > 0xFFFF:
        raise ValueError("载荷过长")
    header = bytearray()
    header.append(SOF)
    header += struct.pack("<H", len(payload))
    header.append(seq & 0xFF)
    header.append(crc8(bytes(header)))
    frame = bytes(header) + pack_cmd(cmd_set, cmd_id) + payload
    frame += struct.pack("<H", crc16(frame))
    return frame


def decode_dt7_frame(frame: bytes) -> dict | None:
    """解一帧（抓包核对用）；任何校验不过都返回 None，不猜。"""
    if len(frame) < HEADER_SIZE + CMD_SIZE + CRC16_SIZE or frame[0] != SOF:
        return None
    (datalen,) = struct.unpack_from("<H", frame, 1)
    if crc8(frame[:4]) != frame[4]:
        return None
    total = HEADER_SIZE + CMD_SIZE + datalen + CRC16_SIZE
    if len(frame) != total:
        return None
    (cmd,) = struct.unpack_from("<H", frame, HEADER_SIZE)
    if crc16(frame[:total - CRC16_SIZE]) != struct.unpack_from("<H", frame, total - 2)[0]:
        return None
    return {"seq": frame[3], "cmd_set": cmd & 0xFF, "cmd_id": cmd >> 8,
            "payload": frame[HEADER_SIZE + CMD_SIZE: HEADER_SIZE + CMD_SIZE + datalen]}


@dataclass
class Dt7KeyMouseLink:
    """把键鼠按 profile 编成帧、写进 DT7 那个虚拟串口。

    默认 `mock_output=True`：只产帧不碰硬件。`write_bytes` 给测试注入假串口。
    """

    port: str = "COM3"
    profile: dict = field(default_factory=load_profile)
    mock_output: bool = True
    write_bytes: object | None = None
    seq: int = 0
    sent: int = 0
    dropped_rate: int = 0
    last_error: str = ""
    last_frame: bytes = b""
    last_payload: bytes = b""
    _next_due: float = 0.0
    time_fn: object = time.perf_counter

    def encode(self, *, mouse_x: int = 0, mouse_y: int = 0, mouse_z: int = 0,
               left: bool = False, right: bool = False,
               keyboard_value: int = 0, mid: bool = False) -> bytes:
        prof = self.profile
        payload = struct.pack(prof["payload_layout"],
                              int(mouse_x), int(mouse_y), int(mouse_z),
                              1 if left else 0, 1 if right else 0,
                              int(keyboard_value) & 0xFFFF, 1 if mid else 0)
        self.seq = (self.seq + 1) & 0xFF
        self.last_payload = payload
        return build_frame(int(prof["cmd_set"]), int(prof["cmd_id_keyboard"]),
                           payload, self.seq)

    def send(self, *, pressed_bits: int = 0, mouse_dx: int = 0, mouse_y: int = 0,
             mouse_z: int = 0, left: bool = False, right: bool = False,
             mid: bool = False, now: float | None = None) -> tuple[bool, str]:
        now = float(self.time_fn()) if now is None else float(now)
        interval = 1.0 / max(1.0, float(self.profile.get("max_hz", 30)))
        if now + 1e-9 < self._next_due:
            self.dropped_rate += 1
            self.last_error = f"超过 {self.profile.get('max_hz'):g}Hz 上限，本帧未发"
            return False, self.last_error
        self._next_due = now + interval
        frame = self.encode(mouse_x=mouse_dx, mouse_y=mouse_y, mouse_z=mouse_z,
                            left=left, right=right, keyboard_value=pressed_bits, mid=mid)
        self.last_frame = frame
        if not self.mock_output:
            try:
                if self.write_bytes is not None:
                    self.write_bytes(frame)
                else:
                    import serial
                    with serial.Serial(self.port, int(self.profile.get("baudrate", 115200)),
                                       timeout=0.2) as sp:
                        sp.write(frame)
            except Exception as exc:
                self.last_error = str(exc)
                return False, str(exc)
        self.last_error = ""
        self.sent += 1
        return True, "mock" if self.mock_output else "ok"

    def release(self, now: float | None = None) -> tuple[bool, str]:
        """全零键值一帧：把 DT7 里的键位松开（它没有"保持上一帧"的保护给我们兜底）。"""
        now = float(self.time_fn()) if now is None else float(now)
        self._next_due = 0.0
        return self.send(pressed_bits=0, now=now)
