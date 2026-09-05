#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""一条命令回答：「自定义客户端经 DT7 到底控不控得动车？」

需要两根线（这是最快的闭环判定，全程不用大疆客户端）：
  1. **DT7 插电脑** —— C 路出口，我们往它写键鼠帧（`dt7_link`，22 字节厂商帧）；
  2. **C 板 Type-C 插电脑** —— 只用来**读车上回读**：固件把合并后的最终键位
     `km_key` 与 0x0311 到达计数 `km_rx` 当作 Debug 段从 0x5A 链路上行吐出来
     （`application/other/remote_control.c:380-381`，`__USB_SEND_DEBUG=1`）。
     本工具在这一路**一个字节都不往下写**，所以不抢驾驶权。

判据为什么可靠：`km_key` 是固件三本账合并后的**最终值**
（`rc_ctrl.key.v = HOST_RC_MERGED_KEYS()`）。它出现我们发的那几个位，
就等于证明「PC → DT7 → 空口 → DR16 → UART3 → rc_ctrl」整条链路真的通；
不出现就知道卡在哪一段，而不是靠"车好像动了"猜。

用法：
    python tools/dt7_link/dt7_wireless_selftest.py --dt7-port COM9 --board-port COM3
    python tools/dt7_link/dt7_wireless_selftest.py --dt7-port COM9 --board-port COM3 --keys W --seconds 4
    python tools/dt7_link/dt7_wireless_selftest.py --dry-run     # 不碰硬件，假车走一遍

安全：**先架空驱动轮**。本工具真的往 DT7 写键鼠，`SHIFT` 是小陀螺开关，车会自己切自转。
无论如何结束都补松手帧（DT7 那侧没有过期自动清零）。
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import dt7_dbus_frame as df                       # noqa: E402
from rm_client.backend import dt7_link as dl      # noqa: E402
from rm_client.backend import polar_link as pl    # noqa: E402

BASELINE_S = 0.6
READ_CHUNK = 64


def debug_frame(ts: int, packages: dict[str, float]) -> bytes:
    """造一条车上的 Debug 上行帧（只给 --dry-run 与离线测试当假车用）。"""
    body = bytearray()
    items = list(packages.items())[: pl._DEBUG_PACKAGE_NUM]
    for name, value in items:
        chunk = bytearray(pl._DEBUG_PACKAGE_SIZE)
        raw = name.encode("ascii")[:10]
        # 注意：bytearray 的切片赋值会**改变长度**，所以只能按字节数写，别拿定长切片赋值
        chunk[0:len(raw)] = raw
        chunk[10] = 0                     # type 0 = 整型视图
        struct.pack_into("<f", chunk, 11, float(value))
        body += chunk
    body += bytes(pl._DEBUG_PACKAGE_SIZE * (pl._DEBUG_PACKAGE_NUM - len(items)))
    # 与解码端逐字对齐：0x5A | len(=4+body) | seg_id | crc8(前3字节) | u32 ts | body | crc16(LE)
    head = bytes([0x5A, (4 + len(body)) & 0xFF, pl.SEG_DEBUG])
    frame = head + bytes([pl.crc8(head)]) + struct.pack("<I", ts & 0xFFFFFFFF) + bytes(body)
    return frame + struct.pack("<H", pl.crc16(frame))


def _feed(reader, codec, buf: bytearray, sink: list[int]) -> None:
    """读一小口字节喂解码器，把见过的 km_key 记下来。"""
    chunk = reader(READ_CHUNK)
    if not chunk:
        return
    buf.extend(chunk)
    segments, consumed = codec.decode_with_consumed(bytes(buf))
    del buf[:consumed]
    for seg in segments:
        if seg.segment_id != pl.SEG_DEBUG:
            continue
        value = (seg.fields or {}).get("packages", {}).get("km_key")
        if value is not None:
            sink.append(int(value))


def _collect(reader, codec, buf: bytearray, seconds: float, sink: list[int]) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        _feed(reader, codec, buf, sink)


def mode(samples: list[int]) -> int | None:
    if not samples:
        return None
    counts: dict[int, int] = {}
    for s in samples:
        counts[s] = counts.get(s, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def judge(base: int, sent_bits: int, samples: list[int]) -> str:
    """PASS=出现我们发的位；PARTIAL=变了但不是我们的位（载荷错位）；NO-CHANGE=DT7 没理。"""
    if any((s & sent_bits) == sent_bits and (base & sent_bits) != sent_bits for s in samples):
        return "PASS"
    if any(s != base for s in samples):
        return "PARTIAL"
    return "NO-CHANGE"


def run_selftest(*, dt7_port: str, board_port: str, keys=("W", "SHIFT"),
                 seconds: float = 4.0, profile: dict | None = None,
                 open_serial=None, baseline_s: float = BASELINE_S) -> dict:
    """跑一遍闭环判定。`open_serial(port, baud)` 可注入，离线测试拿它造假车。"""
    prof = profile if profile is not None else dl.load_profile()
    sent_bits = df.keys_to_bits([k.upper() for k in keys], order="vendor2026")
    out: dict = {"sent_bits": sent_bits, "keys": [k.upper() for k in keys],
                 "frames_sent": 0, "baseline": None, "observed": [],
                 "verdict": "", "note": "", "refused_before": 0}
    opener = open_serial
    if opener is None:
        import serial

        def opener(port: str, baud: int):
            return serial.Serial(port, baud, timeout=0.05)

    board = opener(board_port, int(prof.get("baudrate", 961200)))
    codec = pl.PolarFrameCodec()
    buf = bytearray()
    dt7 = None
    try:
        _collect(lambda n: board.read(n), codec, buf, baseline_s, out["observed"])
        base = mode(out["observed"])
        out["baseline"] = base
        if base is None:
            out["verdict"] = "NO-READBACK"
            out["note"] = ("C 板一个 Debug 帧都没回读：本判定不成立（别当成没通）。"
                           "先查 --board-port 是不是那个 DJI/CDC 串口、"
                           "固件 __USB_SEND_DEBUG 是否为 1")
            return out
        link = dl.Dt7KeyMouseLink(port=dt7_port, profile=prof, mock_output=False)
        gate = link._gate()
        if gate:
            out["verdict"] = "BLOCKED"
            out["note"] = gate + "（没往 DT7 写一个字节）"
            return out
        dt7 = opener(dt7_port, int(prof.get("baudrate", 961200)))
        link.write_bytes = lambda b: dt7.write(b)
        seen: list[int] = []
        start = time.perf_counter()
        while time.perf_counter() - start < seconds:
            ok, why = link.send(pressed_bits=sent_bits)
            if ok:
                out["frames_sent"] += 1
            else:
                out["note"] = f"发送失败：{why}"
            _collect(lambda n: board.read(n), codec, buf, 0.05, seen)
        for _ in range(2):
            link._next_due = 0.0
            link.send(pressed_bits=0)
        link._next_due = 0.0
        link.release()
        out["refused_before"] = link.refused
        out["observed"] = out["observed"] + seen
        out["verdict"] = judge(base, sent_bits, seen)
        return out
    finally:
        for handle in (board, dt7):
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass


VERDICT_HELP = {
    "PASS": "通了。键位从 PC 经 DT7 真的落到 rc_ctrl.key.v（车端合并后的最终值）。",
    "PARTIAL": "键位变了但**不是**我们发的位 —— 帧被接受了、载荷错位（字段顺序/偏移/位序）。"
               "下一步抓一次 USBPcap 对比：tools/dt7_link/dt7_frame_diff.py。",
    "NO-CHANGE": "DT7 完全没理这一帧。换帧型再试："
                 "dt7_vcp_probe.py --candidate dbus18/km12/keys2，或 --send-hex 回放抓包。",
    "NO-READBACK": "读不到车上回读，本判定不成立 —— 先修 A 路的 Debug 上行，再谈结论。",
    "BLOCKED": "profile 未定案或自相矛盾，本工具没往 DT7 写任何东西。",
}


class SimRobot:
    """最小可信的"假车"：DT7 收到我们的键鼠帧 -> 车上合并键位才变成那个值。

    `accept=False` 模拟"DT7 完全不理这一帧"；`shift` 模拟"帧被接受但载荷错位"
    （键位漂了几位）；`reply=False` 模拟"C 板一个 Debug 都不回"。
    这不是为了好看：判据本身也需要一个已知行为的东西来验，否则"能判 PASS"
    这句话没有证据。
    """

    def __init__(self, *, accept: bool = True, shift: int = 0, reply: bool = True):
        self.accept = accept
        self.shift = shift
        self.reply = reply
        self.keys = 0
        self.frames_in = []
        self._buf = bytearray()
        self._ts = 0

    # ---- DT7 那一侧 ----
    def write(self, data: bytes) -> int:
        frame = bytes(data)
        self.frames_in.append(frame)
        decoded = dl.decode_dt7_frame(frame)
        if decoded is None or not self.accept:
            return len(frame)
        payload = decoded["payload"]
        if len(payload) >= 10:
            (keys,) = struct.unpack_from("<H", payload, 8)
            self.keys = (keys << self.shift) & 0xFFFF if self.shift else keys
        return len(frame)

    # ---- C 板那一侧（只被读） ----
    def read(self, n: int) -> bytes:
        if not self.reply:
            return b""
        while len(self._buf) < n * 2:
            self._buf.extend(debug_frame(self._ts, {"km_key": float(self.keys),
                                                    "km_rx": float(len(self.frames_in))}))
            self._ts += 1
        out, self._buf[:] = bytes(self._buf[:n]), self._buf[n:]
        return out

    def close(self) -> None:
        pass

    def opener(self, port: str, baud: int):
        return self


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="C 路（PC→DT7→DR16→C 板）闭环自检")
    ap.add_argument("--dt7-port", default=None, help="DT7 那个 DJI USB Virtual COM")
    ap.add_argument("--board-port", default=None, help="C 板 Type-C 虚拟串口（只读回读）")
    ap.add_argument("--keys", default="W,SHIFT", help="要注入的键位，逗号分隔")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--dry-run", action="store_true", help="不碰硬件，用假车走一遍流程")
    ap.add_argument("--sim-reject", action="store_true", help="配合 --dry-run：假车不理帧")
    ap.add_argument("--sim-shift", type=int, default=0, help="配合 --dry-run：键位漂移几位")
    args = ap.parse_args(argv)
    names = [k.strip().upper() for k in str(args.keys).split(",") if k.strip()]
    if args.dry_run:
        sim = SimRobot(accept=not args.sim_reject, shift=args.sim_shift)
        res = run_selftest(dt7_port="DT7", board_port="BOARD", keys=names,
                           seconds=0.3, open_serial=sim.opener)
        print(f"[dry-run] 结论 {res['verdict']}；DT7 收到 {len(sim.frames_in)} 帧，"
              f"每帧 {len(sim.frames_in[0]) if sim.frames_in else 0} 字节；"
              f"假车最终键位 0b{sim.keys:016b}")
        return 0
    if not args.dt7_port or not args.board_port:
        print("[FAIL] 要同时给 --dt7-port 与 --board-port（先 dt7_vcp_probe.py --list 找口）",
              file=sys.stderr)
        return 2
    res = run_selftest(dt7_port=args.dt7_port, board_port=args.board_port,
                       keys=names, seconds=max(1.0, args.seconds))
    print(f"注入键位 {res['keys']} = 0b{res['sent_bits']:016b}，实际发出 {res['frames_sent']} 帧")
    print(f"基线 km_key={res['baseline']}，回读样本 {len(res['observed'])} 个")
    print(f"结论：**{res['verdict']}** —— {VERDICT_HELP.get(res['verdict'], '')}")
    if res["note"]:
        print(f"补充：{res['note']}")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())