#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 扫帧型工具的判据必须能"只认出那一种"：它自己就靠这条被抓出过两个 bug
# （假车攒陈旧帧 => 每种都 PASS；循环里发的是运行期那一种帧 => 六种其实是同一种）
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import dt7_sweep as sw                            # noqa: E402
import dt7_dbus_frame as df                       # noqa: E402
from rm_client.backend import dt7_link as dl      # noqa: E402

FAILED = 0
SKIPPED = []


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    FAILED += 0 if ok else 1


def sweep(accept, *, shift=0, seconds=0.15, names=None):
    sim = sw.SimSweep(accept=accept, shift=shift)
    res = sw.run_sweep(dt7_port="DT7", board_port="BOARD", keys=("X",),
                       seconds=seconds, open_serial=sim.opener, names=names)
    return res, sim


def by_name(res):
    return {r["name"]: r for r in res}


def main() -> int:
    print("\n--- 1) 能不能只认出那一种 ---")
    res, sim = sweep("vendor5a")
    m = by_name(res)
    check("假车只认 vendor5a 时，只有它判 PASS",
          m["vendor5a"]["verdict"] == "PASS"
          and all(m[n]["verdict"] == "NO-CHANGE" for n in m if n != "vendor5a"),
          str({k: v["verdict"] for k, v in m.items()}))
    res, _ = sweep("keys2")
    m = by_name(res)
    check("假车只认 keys2 时，答案必须换成 keys2（不许还是 vendor5a）",
          m["keys2"]["verdict"] == "PASS" and m["vendor5a"]["verdict"] == "NO-CHANGE",
          str({k: v["verdict"] for k, v in m.items()}))
    res, _ = sweep("nope")
    m = by_name(res)
    check("一种都不认时全部 NO-CHANGE，且不会冒出一个 PASS",
          all(v["verdict"] == "NO-CHANGE" for v in m.values()), str(set(
              v["verdict"] for v in m.values())))
    res, _ = sweep("vendor5a", shift=3)
    m = by_name(res)
    check("帧被接受但键位漂了 -> 判 PARTIAL（帧型对、载荷错，方向完全不同）",
          m["vendor5a"]["verdict"] == "PARTIAL", m["vendor5a"]["verdict"])

    print("\n--- 2) 候选表本身 ---")
    bits = df.keys_to_bits(["X"], order="vendor2026")
    prof = dl.load_profile()
    fr = sw.candidate_frames(bits, profile=prof)
    runtime = dl.build_frame(int(dl.cmd_wire_of(prof) or 0),
                             struct_pack := __import__("struct").pack(
                                 "<hhhBBHH", 0, 0, 0, 0, 0, bits, 0), 0)
    check("vendor5a 与运行期实现打出来的字节完全一致（不许两份实现跑偏）",
          fr["vendor5a"] == runtime, fr["vendor5a"].hex(" ").upper())
    lens = {n: len(b) for n, b in fr.items()}
    check("候选之间字节长度不许撞车（撞了就扫出来分不清是谁）",
          len(set(lens.values())) == len(lens), str(lens))
    check("km12 就是 dbus18 的 bytes6-17（所以不再单列 raw12）",
          fr["dbus18"][6:18] == fr["km12"], fr["km12"].hex(" "))
    check("vendor5a 的第 8-19 字节就是同一串 12 字节载荷（三种帧共享载荷）",
          fr["vendor5a"][8:20] == fr["km12"], fr["vendor5a"][8:20].hex(" "))

    zeros = sw.candidate_frames(0, profile=prof)
    check("每种都有同帧型的清零版（换下一种之前必须先把键位松开）",
          set(zeros) == set(fr) and all(z != f for z, f in zip(
              (zeros[n] for n in fr), (fr[n] for n in fr))), str(sorted(fr)))

    print("\n--- 3) 扫完是否真的写过清零帧 ---")
    res, sim = sweep("dbus18")
    wrote = sim.written
    check("每种帧都写了非零版与清零版", len(wrote) >= 2 and wrote[-1] != wrote[0],
          f"writes={len(wrote)}")
    dbus = sw.candidate_frames(bits, profile=prof)["dbus18"]
    zero_dbus = sw.candidate_frames(0, profile=prof)["dbus18"]
    check("扫到该种之后确实发过它的清零帧（不然键会带着走下一轮）",
          wrote.count(zero_dbus) >= 1 and wrote.count(dbus) >= 1,
          f"{wrote.count(dbus)}/{wrote.count(zero_dbus)}")
    check("假车最终键位归零（没留下粘住的痕迹）", sim.keys == 0, str(sim.keys))

    print("\n--- 4) 读不到回读时必须拒绝下结论 ---")

    class Deaf:
        def __init__(self):
            self.written = []

        def read(self, n):
            return b""

        def write(self, data):
            self.written.append(bytes(data))

        def close(self):
            pass

        def opener(self, port, baud):
            return self

    deaf = Deaf()
    res = sw.run_sweep(dt7_port="DT7", board_port="BOARD", keys=("X",), seconds=0.1,
                       open_serial=deaf.opener)
    check("读不到 km_key -> NO-READBACK，绝不给 PASS/NO-CHANGE",
          len(res) == 1 and res[0]["verdict"] == "NO-READBACK", str(res[:1]))

    print("\n--- 5) profile 没定案时一个字节都不写 ---")
    import copy
    p_un = copy.deepcopy(dl.DEFAULT_PROFILE)
    p_un["cmd_confirmed"] = False
    p_un["allow_experimental_cmd"] = False
    p_un["_profile_error"] = ""
    sim = sw.SimSweep(accept="vendor5a")
    res = sw.run_sweep(dt7_port="DT7", board_port="BOARD", keys=("X",), seconds=0.1,
                       profile=p_un, open_serial=sim.opener)
    check("未定案 -> 全部 BLOCKED 且没往 DT7 写东西",
          res and all(r["verdict"] == "BLOCKED" for r in res) and sim.written == [],
          f"{len(res)} verdicts, writes={len(sim.written)}")

    print("\n" + ("有失败项" if FAILED else "扫帧型工具判据全部通过"))
    if SKIPPED:
        print("跳过项：" + "；".join(SKIPPED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())