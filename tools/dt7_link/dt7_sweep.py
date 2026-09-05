#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""闭环扫帧型：哪种帧能让车上 km_key 动，当场就出来，不用人盯着看。

为什么需要它：`dt7_wireless_selftest.py` 只会告诉你"通/不通"，
判成 NO-CHANGE 之后还得人手工一种一种试（vendor5a / dbus18 / km12 / keys2 …）。
本脚本把那一串变成机械步骤：**每一种候选各发一小段，同时读车上 km_key**，
按键位真的动起来的那一种就是答案；漂了几位的那种说明"帧被吃、载荷错位"。

前提与安全性
------------
* 两根线：DT7 插电脑（写）、C 板 Type-C 插电脑（只读回读，不往下写，不抢驾驶权）。
* 探针键**默认用 X**：全固件对 R/G/Z/X/C/V/B 零消费，所以扫帧型不会让车动起来。
* 每一种候选结束后都补松手帧；整体结束再补一次。
* 需要 profile 已定案（cmd_confirmed），否则一律 BLOCKED、一个字节都不写。

用法
----
    python tools/dt7_link/dt7_sweep.py --dt7-port COM9 --board-port COM3 --report field_evidence/sweep.json
    python tools/dt7_link/dt7_sweep.py --dry-run --sim-accept vendor5a        # 离线彩排
    python tools/dt7_link/dt7_sweep.py --list
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import dt7_dbus_frame as df                       # noqa: E402
import dt7_wireless_selftest as ws                # noqa: E402
from rm_client.backend import dt7_link as dl      # noqa: E402
from rm_client.control import KEYBOARD_BITS       # noqa: E402


def _payload(keys: int, mouse=(0, 0, 0), left=0, right=0) -> bytes:
    return struct.pack("<hhhBBHH", mouse[0], mouse[1], mouse[2], left, right, keys & 0xFFFF, 0)


def candidate_frames(keys: int, mouse=(0, 0, 0), left: int = 0, right: int = 0,
                     profile: dict | None = None) -> dict:
    """候选帧型表。键名会被打印出来，也是 --sim-accept 要匹配的名字。"""
    prof = profile if profile is not None else dl.load_profile()
    payload = _payload(keys, mouse, left, right)
    full = df.encode_frame(mouse=mouse, keys=keys)
    out = {
        "vendor5a": dl.build_frame(int(dl.cmd_wire_of(prof) or 0x2000), payload, 0,
                                   frame_variant="dji_rc_v1", crc_variant="rc_check"),
        "a5_tail": dl.build_frame(0x1100, payload, 0, frame_variant="a5_tail",
                                  datalen_includes_cmd=False, crc_variant="student"),
        "dbus18": full,
        "km12": full[6:18],
        "keys2": struct.pack("<H", keys & 0xFFFF),
    }
    return out


CANDIDATE_DOC = {
    "vendor5a": "厂商那 22 字节（5A|len|ver|crc8|seq|cmd|12B|crc16）——**最可能就是这个**",
    "a5_tail": "图传/裁判那族 A5 帧（旧假设，留着当对照）",
    "dbus18": "整帧 18 字节，与 DR16 出口同构（DT7 若纯透传就吃这个）",
    "km12": "只给键鼠那 12 字节（DBUS bytes6-17）",
    "keys2": "最裸的 2 字节键位图",
    # 没有 raw12：它和 km12 打出来是**同一串 12 字节**（Input_Device_Status_RC
    # 就是 DBUS 帧的 bytes6-17），两种一起扫只是白耗轮次
}


def run_sweep(*, dt7_port: str, board_port: str, keys=("X",), seconds: float = 0.8,
              profile: dict | None = None, open_serial=None, names=None) -> list:
    """一种一种试：**把那种帧原样写进 DT7**，同时读车上 km_key。"""
    prof = profile if profile is not None else dl.load_profile()
    bits = df.keys_to_bits([k.upper() for k in keys], order="vendor2026")
    frames = candidate_frames(bits, profile=prof)
    zeros = candidate_frames(0, profile=prof)        # 同一种帧型、键位清零 = 该种的松手帧
    order = [n for n in (names or CANDIDATE_DOC) if n in frames]
    opener = open_serial
    if opener is None:
        import serial

        def opener(port: str, baud: int):
            return serial.Serial(port, baud, timeout=0.05)
    results: list = []
    board = opener(board_port, int(prof.get("baudrate", 961200)))
    codec = ws.pl.PolarFrameCodec()
    buf = bytearray()
    dt7 = None
    try:
        # 闸门仍复用运行期实现：profile 没定案时一个字节都不该写出去
        link = dl.Dt7KeyMouseLink(port=dt7_port, profile=prof, mock_output=False)
        gate = link._gate()
        if gate:
            return [{"name": n, "verdict": "BLOCKED", "note": gate, "sent": 0,
                     "bytes": len(frames[n]), "samples": 0} for n in order]
        dt7 = opener(dt7_port, int(prof.get("baudrate", 961200)))
        for name in order:
            frame, zero = frames[name], zeros[name]
            base: list[int] = []
            ws._collect(lambda n: board.read(n), codec, buf, ws.BASELINE_S, base)
            baseline = ws.mode(base)
            if baseline is None:
                results.append({"name": name, "verdict": "NO-READBACK", "sent": 0,
                                "bytes": len(frame), "samples": 0,
                                "note": "读不到车上回读，整轮扫帧型都不成立"})
                break
            seen: list[int] = []
            sent = 0
            start = time.perf_counter()
            while time.perf_counter() - start < seconds:
                try:
                    dt7.write(frame)
                    sent += 1
                except Exception as exc:            # noqa: BLE001
                    results.append({"name": name, "verdict": "WRITE-FAIL", "sent": sent,
                                    "bytes": len(frame), "samples": len(seen),
                                    "note": f"写 DT7 口失败：{exc}"})
                    break
                ws._collect(lambda n: board.read(n), codec, buf, 0.02, seen)
            else:
                try:
                    dt7.write(zero)                 # 换下一种之前先把这一种的键位清掉
                except Exception:
                    pass
                verdict = ws.judge(baseline, bits, seen)
                matched = sum(1 for s in seen
                              if (s & bits) == bits and (baseline & bits) != bits)
                results.append({"name": name, "verdict": verdict, "sent": sent,
                                "bytes": len(frame), "samples": len(seen),
                                "hex": frame[:8].hex(" ").upper(),
                                "note": (f"匹配样本 {matched} 个："
                                         + ws.VERDICT_HELP.get(verdict, ""))})
                continue
            break                                   # WRITE-FAIL 分支：整轮停
        return results
    finally:
        for handle in (board, dt7):
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass


class SimSweep:
    """假 DT7：只认某一种帧型（默认 vendor5a），可配置成"键位漂一位"。

    扫帧型工具本身必须有已知答案可核对，否则"扫出来是 vendor5a"这句话没有证据。
    """

    def __init__(self, *, accept: str = "vendor5a", shift: int = 0):
        self.accept = accept
        self.shift = shift
        self.keys = 0
        self.written: list[bytes] = []
        self._buf = bytearray()
        self._ts = 0
        self._pub_keys = -1

    def _decode(self, frame: bytes):
        try:
            if frame[0] == 0x5A and len(frame) == 22:
                payload = frame[8:20]
            elif frame[0] == 0xA5 and len(frame) > 7:
                payload = frame[7:19]
            elif len(frame) == 12:
                payload = frame
            elif len(frame) == 18:
                payload = frame[6:18]
            elif len(frame) == 2:
                payload = _payload(struct.unpack("<H", frame)[0])
            else:
                return None
            (keys,) = struct.unpack_from("<H", payload, 8)
            return int(keys)
        except Exception:
            return None

    def write(self, data: bytes) -> int:
        data = bytes(data)
        self.written.append(data)
        keys = self._decode(data)
        if keys is None:
            return len(data)
        got = self._which(data)
        if got != self.accept:
            return len(data)
        self.keys = ((keys << self.shift) & 0xFFFF) if self.shift else keys
        return len(data)

    def _which(self, data: bytes) -> str:
        if len(data) == 22 and data[0] == 0x5A:
            return "vendor5a"
        if data[0] == 0xA5:
            return "a5_tail"
        if len(data) == 18:
            return "dbus18"
        if len(data) == 12:
            return "km12"
        if len(data) == 2:
            return "keys2"
        return "?"

    def read(self, n: int) -> bytes:
        """与 SimRobot 同一套规矩：状态一变就丢掉未发的旧字节，但保住半帧续读。"""
        if self.keys != self._pub_keys:
            self._buf.clear()
        while len(self._buf) < n:
            self._buf.extend(ws.debug_frame(self._ts, {"km_key": float(self.keys),
                                                       "km_rx": float(len(self.written))}))
            self._ts += 1
            self._pub_keys = self.keys
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def close(self) -> None:
        pass

    def opener(self, port: str, baud: int):
        return self


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="C 路帧型闭环扫描（读车上 km_key 判）")
    ap.add_argument("--dt7-port")
    ap.add_argument("--board-port")
    ap.add_argument("--keys", default="X", help="探针键位，默认 X（全固件无消费者，不会让车动）")
    ap.add_argument("--seconds", type=float, default=0.8)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sim-accept", default="vendor5a")
    ap.add_argument("--sim-shift", type=int, default=0)
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)
    names = [k.strip().upper() for k in str(args.keys).split(",") if k.strip()]
    if args.list:
        for name, doc in CANDIDATE_DOC.items():
            print(f"{name:9} {doc}")
        return 0
    if args.dry_run:
        sim = SimSweep(accept=args.sim_accept, shift=args.sim_shift)
        res = run_sweep(dt7_port="DT7", board_port="BOARD", keys=names, seconds=0.2,
                        open_serial=sim.opener)
    else:
        if not args.dt7_port or not args.board_port:
            print("[FAIL] 要同时给 --dt7-port 与 --board-port", file=sys.stderr)
            return 2
        res = run_sweep(dt7_port=args.dt7_port, board_port=args.board_port,
                        keys=names, seconds=max(0.3, args.seconds))
    print(f"{'候选':10} {'结论':12} {'帧长':>4} {'发出':>4}  细节")
    for row in res:
        print(f"{row['name']:10} {row.get('verdict',''):12} {row.get('bytes',0):>4} "
              f"{row.get('sent',0):>4}  {row.get('note','')[:70]}")
    hit = [r for r in res if r.get("verdict") == "PASS"]
    part = [r for r in res if r.get("verdict") == "PARTIAL"]
    if hit:
        print(f"答案：{hit[0]['name']}（车上 km_key 出现了我们发的键位）")
    elif part:
        print(f"最接近：{part[0]['name']} 被接受但键位不对 —— 帧型对了、载荷错位，先修载荷")
    else:
        print("没有任何候选让车上键位动起来")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"tool": "dt7_sweep", "keys": names,
                                   "accepted": [h["name"] for h in hit],
                                   "partial": [p["name"] for p in part],
                                   "results": res}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"证据已写入：{out}")
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())