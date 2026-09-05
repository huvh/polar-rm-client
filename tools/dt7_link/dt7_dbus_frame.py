#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DT7/DR16 官方 18 字节 DBUS 帧的编解码（电脑 <-> 遥控器 <-> 车上 C 板）。

为什么是"官方"两个字
--------------------
大疆《DT7 & DR16 2.4 GHz 遥控接收系统用户手册》V1.0 (2016.09) 第 5-7 页
原文（本地副本：D:/rmbuild/DT7_DR16_RM_manual_official.txt，PDF 同目录）：

    "DR16接收机输出的信号为标准的DBUS协议数据,当遥控器与接收机建立连接后，
     接收机每隔14ms通过DBUS发送一帧18字节数据。**为了满足通过PC控制战车的
     需求，增加了额外的键盘鼠标控制信息**，控制链路示意如图所示：
      键盘鼠标 -> PC主机USB -> (虚拟控制链路) -> 遥控器发射机(DT7)
                                -> 遥控器接收机(DR16) -> (DBUS) -> 战车"

也就是说：**"电脑插遥控器就能控车"是大疆自己设计并写进手册的能力**，不是
野路子。车上固件之所以能解出 rc_ctrl.mouse / rc_ctrl.key.v，正是因为这 18
字节里本来就带键鼠字段（DT7 自己没有键盘鼠标：部件表只有 2 摇杆/2 拨杆/
1 滑杆/Micro-USB，见同一本手册第 2 页）。

帧内位序（手册表 + 固件 remote_control.c:370-391 逐位对齐）
----------------------------------------------------------
  bit  0-10  通道0   11 bit 无符号  364..1684 中值 1024
  bit 11-21  通道1
  bit 22-32  通道2
  bit 33-43  通道3
  bit 44-45  S1 拨杆   1=上 2=下 3=中
  bit 46-47  S2 拨杆
  bit 48-63  鼠标 X 位移   int16   （负=左，正=右）
  bit 64-79  鼠标 Y 位移   int16
  bit 80-95  鼠标 Z 滚轮   int16
  bit 96-103 鼠标左键      uint8   0/1
  bit104-111 鼠标右键      uint8   0/1
  bit112-127 键盘位图      uint16  每键 1 bit
  bit128-143 保留（固件当作 ch[4] 读，见 remote_control.c:391）

注：固件把 s[0] 解在 bit44-45、s[1] 解在 bit46-47（remote_control.c:376-377），
和手册的"S1/S2"命名谁左谁右存在文档层面的歧义；本模块**以固件为准**，
因为它才是真正决定车会不会动的那一端。

键位位序的坑（两套官方定义互相打架，务必读这段）
------------------------------------------------
  A) 遥控器手册(2016) bit0..7 = W S A D **Q E Shift Ctrl**
     （手册第 7 页与附录示例代码 KEY_PRESSED_OFFSET_Q = 0x01<<4）
  B) 裁判系统协议/队内固件 bit0..15 = W S A D **Shift Ctrl** Q E R F G Z X C V B
     （application/other/remote_control.h:103-118；RM2026 协议
      "键盘按键位掩码 bit4=Shift bit5=Ctrl bit6=Q bit7=E" 与此一致）

bit0-3（W/S/A/D）两套完全相同 —— 这正好解释了为什么"键鼠开车"一直好用、
而 Q/E/Shift 的错位从来没人当场抓出来。本模块把两种位序都实现了，
默认用 **B（固件位序）**，并把 A 作为 --key-order dji2016 保留，
现场一抓包就能定死 DT7 实际按哪一套打包（这是尚未验证项，不要当结论用）。
"""

from __future__ import annotations

import argparse
import random
import struct
import sys

FRAME_LEN = 18

CH_MIN, CH_MID, CH_MAX = 364, 1024, 1684
SW_UP, SW_DOWN, SW_MID = 1, 2, 3

# 位序 B：与队内固件 remote_control.h:103-118 一致（本模块默认）
KEY_ORDER_FW = ("W", "S", "A", "D", "SHIFT", "CTRL", "Q", "E",
                "R", "F", "G", "Z", "X", "C", "V", "B")
# 位序 A：DT7&DR16 遥控器手册(2016) 第 7 页 + 附录示例代码
KEY_ORDER_DJI2016 = ("W", "S", "A", "D", "Q", "E", "SHIFT", "CTRL") + KEY_ORDER_FW[8:]
KEY_ORDERS = {"fw": KEY_ORDER_FW, "dji2016": KEY_ORDER_DJI2016}# ---------------------------------------------------------------------------
# 大疆自己心里的键位位序（**从官方选手端 12.x 二进制里抠出来的**，不是手册、不是猜）
# ---------------------------------------------------------------------------
# 取法：Il2CppDumper 解 `RoboMasterClient 12.0.0.30_1v1_Student` 的
# GameAssembly.dll + global-metadata.dat（Metadata Version 29.1），
# 产物 dump.cs 里两处枚举逐字如下：
#
#   dump.cs:136133-136148   public const KeyBoard KEY_PRESSED_OFFSET_W     = 1;      // bit0
#                           ... S = 2, A = 4, D = 8,
#                           SHIFT = 16,   -> bit4
#                           CTRL  = 32,   -> bit5
#                           Q     = 64,   -> bit6
#                           E     = 128,  -> bit7
#                           R=256 F=512 G=1024 Z=2048 X=4096 C=8192 V=16384 B=32768
#   dump.cs:146776-146791   InputRecord.KeyBoardRC 同一套数值，一字不差
#
# ⇒ 第 3 节那个"两套官方定义打架"的悬案**结了**：
#   现役大疆客户端用的是 `SHIFT=bit4 CTRL=bit5 Q=bit6 E=bit7`，
#   与队内固件 `remote_control.h:103-118` 完全一致；
#   《DT7&DR16 遥控器手册 V1.0(2016)》第 7 页那套（Q4 E5 Shift6 Ctrl7）是**过时的**。
# ⇒ 顺带定死一件事：图传键鼠链路的默认掩码 `KM_KEY_MASK_DRIVE=0x1F`
#   确实是 W/S/A/D + **SHIFT（小陀螺）**，不含 Q/E。之前这点靠推断，现在有厂商枚举背书。
KEY_ORDER_VENDOR_2026 = ("W", "S", "A", "D", "SHIFT", "CTRL", "Q", "E",
                         "R", "F", "G", "Z", "X", "C", "V", "B")
# 注意两个映射的**值类型不同**，混用就会静默算出别人家的键：
#   KEYBOARD_BITS（客户端 control 里）  -> 位序号（W=0）   用之前要 1 << 它
#   KEY_VENDOR_2026_BITS（这里）        -> 已经是位值（W=1）再移一次就错
# 本轮端到端测试第一次就栽在这个上面（断言当场红，才算没漏出去）。
KEY_VENDOR_2026_BITS = {name: 1 << i for i, name in enumerate(KEY_ORDER_VENDOR_2026)}

KEY_ORDERS["vendor2026"] = KEY_ORDER_VENDOR_2026



def _set_bits(buf: bytearray, bit_pos: int, n_bits: int, value: int) -> None:
    """把 value 的低 n_bits 位按 LSB-first 写进 buf 的 bit_pos 处。

    为什么手写位打包而不用 struct：帧里是 11 bit 的通道 + 2 bit 的拨杆混排，
    和 C 端 `sbus_to_rc()` 一样只能按位拼；拼错一位，车上读到的就是
    另一个通道值（表现为"车自己慢慢动"或"拨杆档位不对"）。
    """
    if value < 0:
        raise ValueError(f"只接受无符号位域，负数请先转成补码：{value}")
    if value >> n_bits:
        raise ValueError(f"{value} 超出 {n_bits} bit")
    for i in range(n_bits):
        if value & (1 << i):
            pos = bit_pos + i
            buf[pos >> 3] |= 1 << (pos & 7)


def _get_bits(buf: bytes, bit_pos: int, n_bits: int) -> int:
    value = 0
    for i in range(n_bits):
        pos = bit_pos + i
        if buf[pos >> 3] & (1 << (pos & 7)):
            value |= 1 << i
    return value


def _signed(value: int, n_bits: int) -> int:
    if value >= (1 << (n_bits - 1)):
        value -= 1 << n_bits
    return value


def keys_to_bits(pressed, order: str = "fw") -> int:
    """按键名集合 -> 16 bit 键盘位图。"""
    table = KEY_ORDERS[order]
    bits = 0
    for name in pressed:
        key = str(name).upper()
        if key not in table:
            raise KeyError(f"{order} 位序里没有按键 {key!r}（可用：{','.join(table)}）")
        bits |= 1 << table.index(key)
    return bits


def bits_to_keys(bits: int, order: str = "fw") -> tuple[str, ...]:
    table = KEY_ORDERS[order]
    return tuple(table[i] for i in range(16) if bits & (1 << i))


def encode_frame(channels=(CH_MID,) * 4,
                 s1: int = SW_MID, s2: int = SW_MID,
                 mouse=(0, 0, 0), buttons=(0, 0),
                 keys: int = 0, reserved: int = 0) -> bytes:
    """按官方位序打包一帧 18 字节。

    channels: 4 个通道值（364..1684，中值 1024）
    s1/s2:    两个三档拨杆（1=上 2=下 3=中）
    mouse:    (x, y, z) 位移，int16
    buttons:  (左键, 右键) 0/1
    keys:     16 bit 键盘位图（用 keys_to_bits() 生成，别手填数字）
    """
    if len(channels) != 4:
        raise ValueError(f"通道必须 4 个，实际 {len(channels)}")
    buf = bytearray(FRAME_LEN)
    for i, value in enumerate(channels):
        _set_bits(buf, i * 11, 11, int(value))
    _set_bits(buf, 44, 2, int(s1))
    _set_bits(buf, 46, 2, int(s2))
    mx, my, mz = (int(v) for v in mouse)
    for bit_pos, value in ((48, mx), (64, my), (80, mz)):
        _set_bits(buf, bit_pos, 16, value & 0xFFFF)
    _set_bits(buf, 96, 8, int(buttons[0]) & 0xFF)
    _set_bits(buf, 104, 8, int(buttons[1]) & 0xFF)
    _set_bits(buf, 112, 16, int(keys) & 0xFFFF)
    _set_bits(buf, 128, 16, int(reserved) & 0xFFFF)
    return bytes(buf)


def decode_frame(frame: bytes) -> dict:
    """解一帧，语义与固件 application/other/remote_control.c:370-391 一致。

    注意：返回的 ch[] 是**原始通道值**（未减中值），和固件解完之后的语义相同
    （固件在 :393-397 才各自减 RC_CH_VALUE_OFFSET）。
    """
    if len(frame) != FRAME_LEN:
        raise ValueError(f"帧长必须 {FRAME_LEN} 字节，实际 {len(frame)}")
    return {
        "ch": [_get_bits(frame, i * 11, 11) for i in range(4)],
        "s": [_get_bits(frame, 44, 2), _get_bits(frame, 46, 2)],
        "mouse": {
            "x": _signed(_get_bits(frame, 48, 16), 16),
            "y": _signed(_get_bits(frame, 64, 16), 16),
            "z": _signed(_get_bits(frame, 80, 16), 16),
            "press_l": _get_bits(frame, 96, 8),
            "press_r": _get_bits(frame, 104, 8),
        },
        "key_v": _get_bits(frame, 112, 16),
        "reserved": _get_bits(frame, 128, 16),
    }


def describe(frame: bytes, order: str = "fw") -> str:
    d = decode_frame(frame)
    return (f"ch={d['ch']} s={d['s']} mouse={d['mouse']} "
            f"keys={bits_to_keys(d['key_v'], order)} (0x{d['key_v']:04X})")


def _selftest(rounds: int = 4000) -> int:
    rng = random.Random(20260904)
    fails = 0
    for _ in range(rounds):
        want = {
            "ch": [rng.randint(CH_MIN, CH_MAX) for _ in range(4)],
            "s": [rng.randint(SW_UP, SW_MID), rng.randint(SW_UP, SW_MID)],
            "mouse": {"x": rng.randint(-32768, 32767), "y": rng.randint(-32768, 32767),
                      "z": rng.randint(-32768, 32767),
                      "press_l": rng.randint(0, 1), "press_r": rng.randint(0, 1)},
            "key_v": rng.getrandbits(16),
            "reserved": 0,
        }
        frame = encode_frame(channels=want["ch"], s1=want["s"][0], s2=want["s"][1],
                             mouse=(want["mouse"]["x"], want["mouse"]["y"],
                                    want["mouse"]["z"]),
                             buttons=(want["mouse"]["press_l"], want["mouse"]["press_r"]),
                             keys=want["key_v"])
        got = decode_frame(frame)
        if got != want:
            fails += 1
            if fails <= 3:
                print(f"FAIL 帧长={len(frame)}\n  want={want}\n  got ={got}")
    # 位序差异必须真的体现在 bit 上，否则两套位序是假的
    assert keys_to_bits(["SHIFT"]) == 1 << 4, "固件位序里 SHIFT 应在 bit4"
    assert keys_to_bits(["SHIFT"], "dji2016") == 1 << 6, "2016 手册位序里 Shift 应在 bit6"
    assert keys_to_bits(["Q"], "dji2016") == 1 << 4, "2016 手册位序里 Q 应在 bit4"
    assert keys_to_bits(["W"]) == keys_to_bits(["W"], "dji2016") == 1, "两套位序 W 都在 bit0"
    # 边界：全中值/全零帧
    assert decode_frame(encode_frame())["key_v"] == 0
    assert decode_frame(encode_frame())["ch"] == [CH_MID] * 4
    print(f"round-trip {rounds} 帧：{'FAIL ' + str(fails) if fails else '全部一致'}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="随机帧编解码往返一致性")
    ap.add_argument("--encode", nargs="*", metavar="键名", help="按固件位序编码一帧并打 hex")
    ap.add_argument("--key-order", choices=sorted(KEY_ORDERS), default="fw")
    ap.add_argument("--decode", metavar="HEX", help="解一帧 hex")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.decode:
        print(describe(bytes.fromhex(args.decode.replace(" ", "")), args.key_order))
        return 0
    if args.encode is not None:
        print(encode_frame(keys=keys_to_bits(args.encode, args.key_order)).hex(" "))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
