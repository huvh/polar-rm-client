#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""从"官方选手端 ↔ DT7"抓包样本里把键鼠字段的位置与位序**算**出来。

为什么需要这个工具
------------------
大疆对 PC↔DT7 这段上行只字未公开（见 README 第 9.3、11.5 节），
但官方选手端里确实有这条链路（日志原话
`Input_Device_RC Sent x:.., y:.., z:.., LB:.., RB:.., KeyValue:..`，约 30Hz）。
所以最省力的做法不是逆向 30MB 的 IL2CPP 二进制，而是：
**插着 DT7 跑一次官方选手端，用 USBPcap 抓那段 OUT 报文，粘进本工具。**

用法
----
    # 1) 抓包：Wireshark/USBPcap 里筛 方向=主机->设备 且 长度稳定 的那条 URB，
    #    选中若干条，Edit > Copy > As Hex Stream，每包一行存进 samples.txt，
    #    行首可以打标签（标签就是"当时按了什么键"）：
    #        NONE    55aa0300...
    #        W       55aa0300...
    #        SHIFT   55aa0300...
    # 2) 分析：
    python tools/dt7_link/dt7_frame_diff.py samples.txt
    python tools/dt7_link/dt7_frame_diff.py --no-label samples.txt
    python tools/dt7_link/dt7_frame_diff.py --emit python samples.txt

标签是给"键位在哪一字节、哪一 bit"用的：同一长度的一组包里，
只有某些字节会随按键变化，工具把它们对出来。
没有标签时退化成"只报变化字节"，仍然能看出帧结构与字段候选。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dt7_dbus_frame as df  # noqa: E402

HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}[ \t:-]?)+")


def _split_label(line: str) -> tuple[str, str]:
    """把 "W 55aa03.." / "W: 55-aa" / "55aa03.." 三种写法分开。

    难点是真包文本常长这样："ab cd ef 00"（纯十六进制、空格分隔），
    而标签也可能是单个十六进制字母（D 键）。规则：
      * 标签本身含非十六进制字母（W/S/NONE/SHIFT 的 S/H/I/T/N/O 等）-> 认作标签；
      * 只有 1 个字符、且后面那串是一整块长十六进制（>=8 字符、不再有空格）
        才勉强当标签（覆盖 "D 55aa030010..." 这种）；
      * 其余一律"整行都是数据"，绝不把 "ab cd ef" 里的 ab 当标签。
    """
    m = re.match(r"^(\S+?)[:\s]\s*(.+)$", line)
    if not m:
        return "", line
    tok, rest = m.group(1), m.group(2)
    if not re.fullmatch(r"[0-9a-fA-F]+", tok):
        return tok.upper(), rest
    if len(tok) == 1 and re.fullmatch(r"(?:[0-9a-fA-F]{2}[ \t:-]?){4,}", rest):
        return tok.upper(), rest
    return "", line


def parse_lines(text: str) -> list[tuple[str, bytes]]:
    """每行 -> (标签, 字节)。没有标签的整行当字节流。"""
    rows: list[tuple[str, bytes]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        label, body = _split_label(line)
        h = HEX_RE.search(body)
        if not h:
            continue
        compact = re.sub(r"[^0-9a-fA-F]", "", h.group(0))
        if len(compact) % 2:
            continue
        rows.append((label, bytes.fromhex(compact)))
    return rows


def _bits_that_toggle(samples: list[bytes], base: bytes) -> list[int]:
    """相对 base，哪些 **bit** 会变化（bit 编号：字节序号*8 + 位内 0..7，低位在前）。"""
    togg = set()
    for s in samples:
        if len(s) != len(base):
            continue
        for i, (a, b) in enumerate(zip(s, base)):
            togg.update(i * 8 + bit for bit in range(8) if ((a ^ b) >> bit) & 1)
    return sorted(toggles)


def analyze(rows: list[tuple[str, bytes]]) -> dict:
    """按长度分组 -> 找固定帧头/变化字节 -> 用标签把键位字节与位序算出来。"""
    out: dict = {"n_rows": len(rows), "groups": [], "warnings": []}
    if not rows:
        out["warnings"].append("没有解析到任何一包（检查是不是每行一包、十六进制成对）")
        return out
    by_len: dict[int, list[tuple[str, bytes]]] = defaultdict(list)
    for label, data in rows:
        by_len[len(data)].append((label, data))
    for length, group in sorted(by_len.items(), key=lambda kv: -len(kv[1])):
        packets = [d for _, d in group]
        labels = [l for l, _ in group]
        fixed = [all(p[i] == packets[0][i] for p in packets) for i in range(length)]
        changed = [i for i, f in enumerate(fixed) if not f]
        # 每字节取值集合，用来区分"计数器/校验"与"字段"
        per_byte = {i: sorted({p[i] for p in packets}) for i in range(length)}
        entry = {
            "length": length,
            "count": len(packets),
            "head": packets[0][:8].hex(" "),
            "fixed_prefix_len": _prefix_len(fixed),
            "changed_bytes": changed,
            "byte_cardinality": {str(i): len(per_byte[i]) for i in changed},
            "key_field": None,
            "bit_order": None,
        }
        # 键位字节推断：某个字节的取值恰好是"标签集合"的位图，且 bit0-3 与 W/S/A/D 对得上
        labelled = [l for l in labels if l]
        if labelled:
            entry["key_field"] = _guess_key_byte(packets, labels)
            if entry["key_field"]:
                entry["bit_order"] = _bit_order_of(entry["key_field"]["bit_map"])
        out["groups"].append(entry)
    if len(out["groups"]) == 1 and out["groups"][0]["length"] != df.FRAME_LEN:
        out["warnings"].append(
            f"只有一组、长度 {out['groups'][0]['length']} 字节，不是 DBUS 的 18 字节；"
            "说明 PC->DT7 与 空口 DBUS 不是同一种帧（与 README 第 11 节判断一致）")
    return out


def _prefix_len(fixed: list[bool]) -> int:
    n = 0
    for f in fixed:
        if not f:
            break
        n += 1
    return n


def _bits_of(value: int) -> list[int]:
    return [b for b in range(8) if (value >> b) & 1]


def _names(label: str) -> list[str]:
    return [n for n in re.split(r"[+,|]", label or "") if n and n != "NONE"]


def _guess_key_byte(packets: list[bytes], labels: list[str]) -> dict | None:
    """**不预设位序**地找出键位字节。

    为什么不能拿某一套官方位序去对：本工具存在的意义就是判"设备用哪一套"
    （README 第 3 节那两套位序打架）。所以判据只能是纯结构事实：
      * 松键包该字节为 0（或以最高频值为基准则 XOR 后为 0）；
      * 单个键名的包恰好只置 1 个 bit，且不同键名落在不同 bit；
      * 多个键名的包 = 各单键 bit 的并集。
    满足之后再把 {键名: bit} 与两套官方位序对表，报出用的是哪一套。
    """
    length = len(packets[0])
    best = None
    for byte_index in range(length):
        values = [p[byte_index] for p in packets]
        base = Counter(values).most_common(1)[0][0]
        bits_of = {i: set(_bits_of(v ^ base)) for i, v in enumerate(values)}
        single: dict[str, int] = {}
        ok = True
        saw_zero = False
        for i, lab in enumerate(labels):
            names = _names(lab)
            got = bits_of[i]
            if not names:
                saw_zero = saw_zero or not got
                continue
            if len(names) == 1:
                if len(got) != 1:
                    ok = False
                    break
                bit = next(iter(got))
                if names[0] in single and single[names[0]] != bit:
                    ok = False
                    break
                single[names[0]] = bit
            else:
                # 多键包：已知键的 bit 必须都在；多出来的 bit 数量必须正好等于
                # "没见过单键样本的那些键"的数量（否则这字节就还有别的数据混进来）。
                known = {single[n] for n in names if n in single}
                unknown = [n for n in names if n not in single]
                if not single or not known <= got:
                    ok = False
                    break
                if len(got - known) != len(unknown):
                    ok = False
                    break
        if not ok or len(single) < 2 or byte_index in [b for b in ()]:
            continue
        # 至少要见过一次"全松"，否则分不清键位字节与别的常变字段
        if not saw_zero:
            continue
        cand = {"byte": byte_index, "bit_map": single, "samples": len(packets),
                "base": base}
        if best is None or len(cand["bit_map"]) > len(best["bit_map"]):
            best = cand
    return best


def _bit_order_of(bit_map: dict[str, int]) -> str:
    """把发现的 (键名->bit) 与两套官方位序对表。"""
    low = {k: b for k, b in bit_map.items() if b < 8}
    if not low:
        return "unknown(键位 bit 全在高位，不像 8 键位图)"

    def mismatch(order):
        return sum(1 for k, b in low.items() if order.index(k) != b)
    m_fw = mismatch(list(df.KEY_ORDER_FW))
    m_2016 = mismatch(list(df.KEY_ORDER_DJI2016))
    if m_fw == 0 and m_2016 == 0:
        return "both(样本只覆盖到 W/S/A/D，两套一致，判不出来)"
    if m_fw == 0:
        return "fw（与队内固件、RM2026 协议一致）"
    if m_2016 == 0:
        return "dji2016（与 2016 遥控器手册一致，客户端现编码在此位序下会错）"
    return f"unknown(fw 差 {m_fw} 位, dji2016 差 {m_2016} 位)"


def emit(out: dict, style: str) -> str:
    if style == "json":
        return json.dumps(out, ensure_ascii=False, indent=1)
    lines = ["# 由 dt7_frame_diff.py 从抓包样本生成，字段仍待人工确认后再用",
             "GROUPS = ["]
    for g in out["groups"]:
        lines.append("    {")
        for k in ("length", "count", "head", "fixed_prefix_len", "changed_bytes"):
            lines.append(f"        {k!r}: {g[k]!r},")
        if g.get("key_field"):
            lines.append(f"        'key_byte': {g['key_field']['byte']},")
            lines.append(f"        'bit_map': {g['key_field']['bit_map']!r},")
            lines.append(f"        'bit_order': {g['bit_order']!r},")
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def report(out: dict) -> None:
    print(f"解析到 {out['n_rows']} 包")
    for g in out["groups"]:
        print(f"\n[{g['length']} 字节 x {g['count']} 包]  首包 {g['head']}")
        print(f"  前 {g['fixed_prefix_len']} 字节完全不变（疑似帧头/地址/命令号）")
        print(f"  会变的字节: {g['changed_bytes']}   各自取值种数: {g['byte_cardinality']}")
        if g.get("key_field"):
            kf = g["key_field"]
            print(f"  **键位候选：第 {kf['byte']} 字节**（基准值 0x{kf.get('base', 0):02X}），"
                  f"标签对表 {kf['bit_map']}")
            print(f"  **位序判定：{g['bit_order']}**")
        else:
            print("  没认出键位字节（要么没打标签，要么样本里按键没变）")
    for w in out["warnings"]:
        print(f"\n[提醒] {w}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sample", help="每行一包十六进制（可带标签）的文本文件；- 表示读标准输入")
    ap.add_argument("--no-label", action="store_true", help="忽略行首标签")
    ap.add_argument("--emit", choices=("none", "text", "json"), default="none")
    args = ap.parse_args(argv)

    text = sys.stdin.read() if args.sample == "-" else Path(args.sample).read_text(
        encoding="utf-8", errors="replace")
    rows = parse_lines(text)
    if args.no_label:
        rows = [("", d) for _, d in rows]
    out = analyze(rows)
    report(out)
    if args.emit != "none":
        print("\n" + emit(out, args.emit))
    return 0 if out["n_rows"] else 1


if __name__ == "__main__":
    sys.exit(main())
