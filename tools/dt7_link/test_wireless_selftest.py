#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 闭环自检工具本身要有证据：它说 PASS 的时候，必须真的是"我们发的位出现在车上合并键位里"。
from __future__ import annotations

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

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 0 if ok else 1


def run(sim, *, keys=("W", "SHIFT"), profile=None):
    t0 = time.perf_counter()
    res = ws.run_selftest(dt7_port="DT7", board_port="BOARD", keys=keys,
                          seconds=0.15, baseline_s=0.12, profile=profile,
                          open_serial=sim.opener)
    return res, time.perf_counter() - t0


def main() -> int:
    print("\n--- C 路闭环自检工具的判据 ---")
    bits = df.keys_to_bits(["W", "SHIFT"], order="vendor2026")

    # 1) Debug 帧能被真解码器认出来（否则一切判定都是空中楼阁）
    buf, sink = bytearray(), []
    codec = __import__("rm_client.backend.polar_link", fromlist=["x"]).PolarFrameCodec()
    ws._feed(lambda n: ws.debug_frame(1, {"km_key": 21.0, "km_rx": 3.0}), codec, buf, sink)
    check("造的 Debug 帧能被解码器解出 km_key", sink == [21], str(sink))

    # 2) 正常通路
    sim = ws.SimRobot()
    res, spent = run(sim)
    check("假车认帧 -> 判 PASS", res["verdict"] == "PASS",
          f"verdict={res['verdict']} sent={res['frames_sent']} base={res['baseline']} "
          f"样本={len(res['observed'])}")
    check("发出去的每一帧都是厂商那 22 字节",
          bool(sim.frames_in) and all(len(f) == 22 for f in sim.frames_in),
          str([len(f) for f in sim.frames_in][:4]))
    check("结束一定补了松手帧（最后几帧键位为 0）",
          sim.keys == 0 and len(sim.frames_in) >= 3, str(sim.keys))
    check("键位确实是按 vendor2026 位序发出去的",
          any(struct.unpack_from("<H", f[16:18], 0)[0] == bits for f in sim.frames_in),
          hex(bits))
    check("一次自检在秒级完成（现场等不起）", spent < 4.0, f"{spent:.2f}s")

    # 3) DT7 不理帧
    res, _ = run(ws.SimRobot(accept=False))
    check("DT7 不理这帧 -> NO-CHANGE（不许误判成通）", res["verdict"] == "NO-CHANGE", res["verdict"])

    # 4) 帧被接受但载荷错位
    res, _ = run(ws.SimRobot(shift=3))
    check("键位漂了 3 位 -> PARTIAL（说明帧被吃、载荷错位）",
          res["verdict"] == "PARTIAL", res["verdict"])

    # 5) 读不到回读
    res, _ = run(ws.SimRobot(reply=False))
    check("读不到车上回读 -> NO-READBACK，判定不成立", res["verdict"] == "NO-READBACK", res["verdict"])

    # 6) 没定案时绝不碰 DT7
    sim6 = ws.SimRobot()
    prof = dict(dl.DEFAULT_PROFILE)
    prof["cmd_confirmed"] = False
    prof["_profile_error"] = ""
    res, _ = run(sim6, profile=prof)
    check("profile 未确认 -> BLOCKED 且一帧都不写",
          res["verdict"] == "BLOCKED" and sim6.frames_in == [],
          f"{res['verdict']} frames={len(sim6.frames_in)}")

    # 7) 假阳性防线：基线里已经有我们那些位，就不能再判 PASS
    preset = ws.SimRobot()
    preset.keys = bits
    res, _ = run(preset)
    check("基线已含目标位时不许判 PASS（防假阳性）",
          res["verdict"] != "PASS", f"{res['verdict']} base={res['baseline']}")

    # 8) 换一个键位组合也要能判（不是把 W|SHIFT 写死了）
    res, _ = run(ws.SimRobot(), keys=("D",))
    check("换单键 D 也判 PASS", res["verdict"] == "PASS", res["verdict"])
    # 9) 现场证据：跑完要留下可复核的 JSON（结论 + 当时用的 profile）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sim = ws.SimRobot()
        res, _ = run(sim)
        rp = Path(td) / "evidence" / "dt7.json"
        rep = ws.build_report(res, dt7_port="COM9", board_port="COM3",
                              profile=dl.load_profile())
        got = ws.write_report(rp, rep)
        loaded = json.loads(got.read_text(encoding="utf-8"))
        check("证据文件真的落盘且能读回", loaded["verdict"] == "PASS"
              and loaded["passed"] is True and loaded["dt7_port"] == "COM9", str(loaded)[:80])
        check("证据里记录了当时用的帧型设置（换 profile 后结论才可追溯）",
              loaded["profile"]["frame_variant"] == "dji_rc_v1"
              and loaded["profile"]["cmd_wire"] == 0x2000, str(loaded["profile"]))
        check("目录不存在时自动建（现场不会因为你少建一层文件夹就没证据）",
              rp.exists(), str(rp))
    print("\n" + ("有失败项" if FAILED else "闭环自检工具判据全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
