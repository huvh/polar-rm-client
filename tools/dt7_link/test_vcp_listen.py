#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DT7 旁听（只读）模式的离线断言。

旁听是这条路唯一"不用猜"的一步：DT7 若肯从 USB 虚拟串口吐数据，
摇杆/按键的位序当场就能判出来，README 第 3 节那个两套位序打架的死结
也随之解开。它不发包、对车零影响，所以必须保证：
 1. 分帧不能把一帧切两半、也不能把两帧粘一帧（否则解出来的位序全是假的）；
 2. 键位跳变要报到**正确的 bit**，并同时给出两套位序各自的答案；
 3. 非 18 字节的流量要被老实承认"不是 DBUS"，不许硬解；
 4. 两套位序表必须在 bit4-7 真的有差异——哪天有人把它们改成一样，
    第 2 条就变成假绿，这里先把常量钉死。

全程不碰硬件：串口是个喂字节的假对象。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import dt7_dbus_frame as df          # noqa: E402
import dt7_vcp_probe as probe        # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class FakeSerial:
    """按事件回放：每个字节走一小步时间，帧间插入一段静默（空 read）。"""

    BYTE_S = 0.0002
    GAP_S = 0.012

    def __init__(self, frames) -> None:
        self.events = []
        for i, f in enumerate(frames):
            if i:
                self.events.append(None)          # 帧间静默（一整段空闲）
            for byte in f:
                self.events.append(bytes([byte]))
        self.pos = 0
        self.clock = FakeClock()

    def read(self, n: int = 1) -> bytes:
        if self.pos >= len(self.events):
            self.clock.t += 0.05                  # 静置：让旁听窗口能走完
            return b""
        ev = self.events[self.pos]
        self.pos += 1
        if ev is None:
            self.clock.t += self.GAP_S
            return b""
        self.clock.t += self.BYTE_S
        return ev


def frames_with_keys(bits_sequence):
    """一串键位状态 -> DBUS 帧序列（通道固定为中值，鼠标为 0）。"""
    return [df.encode_frame(keys=k) for k in bits_sequence]


def main() -> int:
    # --- 0. 两套位序表必须真的在 bit4-7 打架，否则下面的判读没有意义 ---
    diff_bits = [i for i in range(16)
                 if df.KEY_ORDER_FW[i] != df.KEY_ORDER_DJI2016[i]]
    check("位序分歧只在 bit4-7", diff_bits == [4, 5, 6, 7], str(diff_bits))
    check("bit0-3 两套一致（W/S/A/D 一直没错过，所以这坑藏得住）",
          df.KEY_ORDER_FW[:4] == df.KEY_ORDER_DJI2016[:4])

    # --- 1. 分帧 ---
    fs = FakeSerial(frames_with_keys([0, df.keys_to_bits(["Q"]), 0]))
    got = probe.read_frames(fs, seconds=5.0, gap_s=0.004, clock=fs.clock)
    check("帧数对得上（没切半也没粘连）", len(got) == 3, str([len(x) for x in got]))
    check("每帧都是 18 字节", all(len(x) == df.FRAME_LEN for x in got),
          str([len(x) for x in got]))
    check("内容原样", got[1] == frames_with_keys([df.keys_to_bits(["Q"])])[0])

    # 单帧内部插一个假静默（小于阈值）：不该被切开
    fs2 = FakeSerial([df.encode_frame(keys=0)])
    fs2.GAP_S = 0.001
    got2 = probe.read_frames(fs2, seconds=1.0, gap_s=0.004, clock=fs2.clock)
    check("帧内小间隙不切帧", len(got2) == 1 and len(got2[0]) == df.FRAME_LEN,
          str([len(x) for x in got2]))

    # --- 2. 键位跳变报到正确的 bit + 两套答案 ---
    qbit = df.keys_to_bits(["Q"])                      # 固件位序 Q = bit6
    a = probe.analyze_frames(got)
    bits = sorted({e["bit"] for e in a["key_events"]})
    check("按 Q 报的是 bit6（固件位序）", bits == [6], str(bits))
    ev = a["key_events"][0]
    check("同一个 bit 同时给出手册位序的答案（现场才能一次看懂）",
          (ev["fw"], ev["dji2016"]) == ("Q", "SHIFT"), str(ev))
    check("跳变含按下与松开两个方向",
          [e["pressed"] for e in a["key_events"]] == [True, False],
          str(a["key_events"]))

    # 手册位序的 Q = bit4 -> 判读必须翻过来
    ev4 = probe.analyze_frames(
        [df.encode_frame(keys=0), df.encode_frame(keys=1 << 4)])["key_events"][0]
    check("落在 bit4 时：固件读作 SHIFT、手册读作 Q",
          (ev4["fw"], ev4["dji2016"]) == ("SHIFT", "Q"), str(ev4))

    # --- 3. 通道/鼠标 ---
    moved = [df.encode_frame(channels=(1024, 1024, 1024, 1024)),
             df.encode_frame(channels=(1684, 364, 1024, 1024))]
    am = probe.analyze_frames(moved)
    check("摇杆一动就判定为透传 DBUS", am["ch_moved"] is True, str(am["ch_ranges"]))
    check("通道范围解出端点值", am["ch_ranges"][0] == (1024, 1684), str(am["ch_ranges"]))
    check("通道全中值时不动",
          probe.analyze_frames([df.encode_frame(), df.encode_frame()])["ch_moved"] is False)

    # --- 4. 非 18B 流量不许硬解 ---
    junk = probe.analyze_frames([b"\x5a\x01\x02\x03", b"\x5a\x01\x02\x03"])
    check("非 18 字节块不产出 DBUS 结论", junk["dbus"] == [] and junk["key_events"] == [])
    check("非 18 字节时留了原始头部供人看", junk["raw_head"][0].hex() == "5a010203",
          str(junk["raw_head"]))
    empty = probe.analyze_frames([])
    check("一个字节都没有时也给出可执行建议（不抛异常）",
          empty["n_frames"] == 0 and empty["lengths"] == {})

    # --- 5. 打印路径不许崩（现场全靠这几行字） ---
    probe.print_analysis(am)
    probe.print_analysis(junk)
    probe.print_analysis(empty)
    check("print_analysis 三种情况都不崩", True)

    print("\n" + ("有失败项" if FAILED else "DT7 旁听离线断言全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
