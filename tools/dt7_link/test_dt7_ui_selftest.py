#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 界面上那个"Run DT7 Link Selftest"按钮的可测部分：判据、两个把手、以及"按钮不许是空壳"。
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import dt7_dbus_frame as df                        # noqa: E402
from rm_client import control as C                 # noqa: E402
from rm_client.control import ChassisCommand, KeyboardControlBridge  # noqa: E402

FAILED = 0
SKIPPED = []


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    FAILED += 0 if ok else 1


def cmd(keys=0, seq=1):
    return ChassisCommand(seq=seq, timestamp=0.0, vx=0.0, vy=0.0, wz=0.0,
                          spin_mode=False, speed_limit=0, power_limit=0,
                          mock_output=False, keyboard_value=keys)


class Spy:
    def __init__(self):
        self.calls = []
        self.released = 0

    def send(self, **kw):
        self.calls.append(kw)
        self.sent = len(self.calls)
        return True, "ok"

    def release(self, now=None):
        self.released += 1
        return True, "ok"

    def close(self):
        pass


def main() -> int:
    print("\n--- 1) C 路自检判据（纯函数）---")
    x = int(1 << C.KEYBOARD_BITS["X"])
    check("探针是 X 键、位序按厂商表在 bit12", x == 4096 and df.KEY_VENDOR_2026_BITS["X"] == x,
          str(x))
    fw = ROOT.parent / "tmp_polarbear" / "StandardRobotpp"
    if (fw / "application").exists():
        hits = [p.relative_to(fw) for p in (fw / "application").rglob("*.c")
                if "KEY_X" in p.read_text(encoding="utf-8", errors="ignore")]
        check("探针选的键在固件里真的没有消费者（选错键自检就会把车开走）",
              not hits, str(hits[:3]))
    else:
        SKIPPED.append("没有固件树：X 键无消费者的交叉核对未跑")
    v, d = C.evaluate_dt7_selftest([0, 0, x, x], x, 0)
    check("出现目标键位 -> PASS", v == "PASS", f"{v} {d}")
    v, _ = C.evaluate_dt7_selftest([0, 8, 12], x, 0)
    check("键位动了但不是我们发的位 -> PARTIAL（载荷错位，不许判通）", v == "PARTIAL", v)
    v, _ = C.evaluate_dt7_selftest([0, 0, 0], x, 0)
    check("什么都没变 -> NO-CHANGE", v == "NO-CHANGE", v)
    v, _ = C.evaluate_dt7_selftest([], x, 0)
    check("没有回读 -> NO-READBACK（判定不成立，不许算通过）", v == "NO-READBACK", v)
    v, _ = C.evaluate_dt7_selftest([x, x], x, x)
    check("基线里本来就有这些位时不许判 PASS（假阳性防线）", v != "PASS", v)

    print("\n--- 2) 粘键判据：超时清零的形态不许被误判成粘键 ---")
    stuck = [x] * 40
    v, _ = C.evaluate_dt7_hold(stuck, x)
    check("停发后稳态仍停在 X -> STUCK", v == "STUCK", v)
    fading = [x] * 30 + [0] * 10          # 前一段还停着、后面自己掉：这是安全侧
    v, _ = C.evaluate_dt7_hold(fading, x)
    check("前一段仍停着但最后掉回 -> 必须判 EXPIRES（判据看稳态）", v == "EXPIRES", v)
    v, _ = C.evaluate_dt7_hold([], x)
    check("没样本 -> NO-READBACK", v == "NO-READBACK", v)

    print("\n--- 3) 两个把手真的作用在发送路径上 ---")
    br = KeyboardControlBridge(publisher=None, mock_output=True)
    spy = Spy()
    br.dt7_link = spy
    br.dt7_enabled = True
    # KEYBOARD_BITS 存的是**位序号**（W=0），要的是位图值：1 << 位序
    br.send_command(cmd(keys=1 << C.KEYBOARD_BITS["W"]))
    check("平时发的是键盘当前值", spy.calls and spy.calls[-1]["pressed_bits"] == 1, str(spy.calls[-1:]))
    br.dt7_forced_keys = x
    br.send_command(cmd(keys=1))
    check("强制键位时发的是探针位 X（覆盖键盘当前值）",
          spy.calls[-1]["pressed_bits"] == x, str(spy.calls[-1]))
    n = len(spy.calls)
    br.dt7_send_paused = True
    br.send_command(cmd(keys=1))
    check("暂停阶段一帧都不写", len(spy.calls) == n, f"{len(spy.calls)} vs {n}")
    check("暂停阶段也不许补松手帧（否则量的就不是进程被杀）", spy.released == 0, str(spy.released))
    br.dt7_send_paused = False
    br.dt7_forced_keys = None
    br.send_command(cmd(keys=5))
    check("把手复位后恢复正常", spy.calls[-1]["pressed_bits"] == 5, str(spy.calls[-1]))

    print("\n--- 4) 按钮不许是空壳：设置项、分派、处理函数三处必须成对存在 ---")
    model = (ROOT / "rm_client/model.py").read_text(encoding="utf-8")
    mix = (ROOT / "rm_client/ui/polar/mixins/config_actions_mixin.py").read_text(encoding="utf-8")
    check("RobotLink 设置项里有这个按钮", model.count('"Run DT7 Link Selftest"') == 1)
    check("分派表里有同名分支", 'action_name == "Run DT7 Link Selftest"' in mix)
    check("处理函数存在", "def run_dt7_link_selftest(self) -> None:" in mix)
    check("按钮自己不开新串口（同口互抢是最难查的故障）",
          "import serial" not in mix and "Serial(" not in mix)
    check("按钮不阻塞渲染线程（用 QTimer，不用 sleep）",
          "time.sleep" not in mix.split("def run_dt7_link_selftest")[1].split("def start_kmc")[0])
    check("探针键位走的是 control 的两个把手，不是绕过去直写",
          "dt7_forced_keys = probe" in mix and "dt7_send_paused = True" in mix)
    rep = C.build_dt7_selftest_report(keys=["X"], forced_bits=x, baseline=0,
                                      verdict="PASS", detail="d", hold_verdict="EXPIRES",
                                      hold_detail="h", samples=10, tail_samples=8)
    check("报告字段齐且 passed/safe 是算出来的",
          rep["passed"] is True and rep["safe_when_dying"] is True
          and rep["sent_bits"] == x and rep["tool"].endswith("(ui)"), str(rep)[:70])
    print("\n" + ("有失败项" if FAILED else "C 路界面自检全部通过"))
    if SKIPPED:
        print("跳过项（别当已验）：" + "；".join(SKIPPED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())