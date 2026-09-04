#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓包差分工具（dt7_frame_diff.py）的离线断言——用**合成**样本。

真抓包要硬件，但"从一串包里认出键位字节并判位序"这件事不需要。
这里喂三种合成捕获，钉住四条：
 1. 认出键位在第几字节（含非零基准值的情况，真设备上很常见）；
 2. **不预设位序**：设备按固件那套就报 fw，按 2016 手册那套就报 dji2016；
 3. 只按 W/S/A/D 时**必须承认判不出来**（两套一致，硬说成某一套就是骗人）；
 4. 键位混在别的数据里（该字节变化位与标签数量对不上）时不许乱认。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dt7_dbus_frame as df          # noqa: E402
import dt7_frame_diff as fd          # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


HEAD = "55aa03001000"          # 6 字节：模拟帧头/地址/命令号


def rows(cases):
    """cases: [(标签, 键位字节值)] -> [(标签, bytes)]，键位固定放在第 6 字节。"""
    out = []
    for label, key_byte in cases:
        body = bytes.fromhex(HEAD) + bytes([key_byte]) + bytes(9)   # 共 16 字节
        out.append((label, body))
    return out


def one(rows_):
    return fd.analyze(rows_)


def group_of(result, length):
    for g in result["groups"]:
        if g["length"] == length:
            return g
    return None


def main() -> int:
    # --- 1) 设备用固件/RM2026 位序：SHIFT=bit4、Q=bit6 ---
    r = one(rows([("NONE", 0x00), ("Q", 0x40), ("SHIFT", 0x10), ("E", 0x80),
                  ("W", 0x01), ("W,SHIFT", 0x11)]))
    g = group_of(r, 16)
    check("认出键位字节 = 第 6 字节", g and g["key_field"]["byte"] == 6,
          str(g and g["key_field"]))
    check("位序判成 fw（与队内固件一致）", g and g["bit_order"].startswith("fw"),
          str(g and g["bit_order"]))
    check("16 字节 != DBUS 18 字节要提醒", bool(r["warnings"]), str(r["warnings"]))

    # --- 2) 设备用 2016 手册位序：Q=bit4、E=bit5、SHIFT=bit6、CTRL=bit7 ---
    r2 = one(rows([("NONE", 0x00), ("Q", 0x10), ("E", 0x20), ("SHIFT", 0x40),
                   ("CTRL", 0x80)]))
    g2 = group_of(r2, 16)
    check("同一份工具在 2016 位序下报 dji2016",
          g2 and g2["bit_order"].startswith("dji2016"), str(g2 and g2["bit_order"]))

    # --- 3) 只按 W/S/A/D：两套一致，必须承认判不出来 ---
    r3 = one(rows([("NONE", 0x00), ("W", 0x01), ("S", 0x02), ("A", 0x04), ("D", 0x08)]))
    g3 = group_of(r3, 16)
    check("只覆盖 W/S/A/D 时不许硬判位序",
          g3 and g3["bit_order"].startswith("both"), str(g3 and g3["bit_order"]))

    # --- 4) 非零基准值（真设备上"松键"那字节常带个固定位）---
    r4 = one(rows([("NONE", 0x20), ("W", 0x21), ("SHIFT", 0x30), ("W,SHIFT", 0x31)]))
    g4 = group_of(r4, 16)
    check("基准值非零也能认出键位字节",
          g4 and g4["key_field"]["byte"] == 6 and g4["key_field"]["base"] == 0x20,
          str(g4 and g4["key_field"]))
    check("基准值非零时位序仍判对", g4 and g4["bit_order"].startswith("fw"),
          str(g4 and g4["bit_order"]))

    # --- 5) 键位混进别的数据：多出来的 bit 数与没见过的键数不符 -> 不许认 ---
    bad = [(lab, bytes.fromhex(HEAD) + bytes([v]) + bytes(9))
           for lab, v in (("NONE", 0x00), ("W", 0x81), ("A", 0x84), ("SHIFT", 0x90))]
    gb = group_of(fd.analyze(bad), 16)
    check("该字节还混着别的数据时不得乱认键位",
          gb is not None and gb["key_field"] is None, str(gb and gb["key_field"]))

    # --- 6) 标签与十六进制的解析：负数/冒号/大写都要能吃 ---
    parsed = fd.parse_lines("W: 55-AA-03-00-10-00-11-00\n"
                            "# 注释行\n"
                            "NONE 55aa030010000000\n"
                            "ab cd ef 00 11\n"
                            "D 55aa030010000008\n")
    labels = [l for l, _ in parsed]
    check("标签支持冒号分隔与连字符十六进制", labels[0] == "W", str(labels))
    check("注释行被跳过（只剩 4 行数据）", len(parsed) == 4, str(len(parsed)))
    check("NONE 标签识别", labels[1] == "NONE", str(labels))
    check("纯空格分隔的十六进制不许把首字节当标签",
          labels[2] == "" and parsed[2][1] == bytes.fromhex("abcdef0011"),
          str(parsed[2]))
    check("单字符十六进制标签在长数据后仍可识别（D 键）",
          labels[3] == "D", str(labels))

    # --- 7) 空输入不许崩 ---
    e = fd.analyze([])
    check("空输入给得出可读结论", e["n_rows"] == 0 and e["warnings"], str(e))

    print("\n" + ("有失败项" if FAILED else "抓包差分工具离线断言全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
