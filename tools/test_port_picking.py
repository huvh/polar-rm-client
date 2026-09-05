#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# DT7 / 自定义控制器的 Auto 挑口。认错口的代价不是"连不上"，而是**产出假结论**：
# 把遥控器帧写进 C 板的 CDC，又拿同一块板的 km_key 回读判读 => 永远 NO-CHANGE
# => 我们会误判成"DT7 不认这帧"，然后白换一整轮帧型。
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from rm_client import serial_ports as sp          # noqa: E402
from rm_client.backend import cc_link as cc       # noqa: E402
from rm_client.backend import dt7_link as dl      # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    FAILED += 0 if ok else 1


ROBOT = {"device": "COM3", "name": "COM3", "description": "STMicroelectronics Virtual COM Port",
         "vid": 0x0483, "pid": 0x5720, "serial_number": ""}
DT7 = {"device": "COM9", "name": "COM9", "description": "DJI USB Virtual COM",
       "vid": 0xFFF0, "pid": 0x0008, "serial_number": ""}
FTDI = {"device": "COM7", "name": "COM7", "description": "USB Serial Port (COM7)",
        "vid": 0x0403, "pid": 0x6001, "serial_number": ""}
OTHER = {"device": "COM5", "name": "COM5", "description": "USB Serial",
         "vid": 0x1A86, "pid": 0x7523, "serial_number": ""}


def with_ports(entries):
    real = sp.list_serial_ports
    sp.list_serial_ports = lambda: [dict(e) for e in entries]
    return real


def main() -> int:
    print("\n--- 1) 车与遥控器同时插着（现场最常见的形态）---")
    real = with_ports([ROBOT, DT7, FTDI, OTHER])
    try:
        check("DT7 的 Auto 必须挑 DJI 那个口，而不是分最高的机器人口",
              sp.resolve_rc_port("Auto") == "COM9", sp.resolve_rc_port("Auto"))
        check("运行期链路解析到同一个口", dl.Dt7KeyMouseLink(port="Auto")._open_target()[0] == "COM9")
        target, why = dl.Dt7KeyMouseLink(port="COM3")._open_target()
        check("显式把 DT7 指到车的口 -> 拒发并说清为什么",
              target == "" and "机器人本体" in why, why[:60])
        forced = dl.Dt7KeyMouseLink(port="COM3", profile={**dl.DEFAULT_PROFILE,
                                                          "allow_robot_port": True})
        check("真要这么接时能显式放行（不把工具做成死路）",
              forced._open_target()[0] == "COM3", str(forced._open_target()))
        check("下拉里不混进车的口", sp.rc_port_choices() == ["Auto", "COM9"],
              str(sp.rc_port_choices()))
        check("CC 的 Auto 挑 FTDI（选手端只认它）", sp.resolve_cc_port("Auto") == "COM7",
              sp.resolve_cc_port("Auto"))
        check("CC 打分把车与遥控器的口都判负",
              sp.score_cc_port(ROBOT) < 0 and sp.score_cc_port(DT7) < 0
              and sp.score_cc_port(FTDI) == 100)
        check("cc_link 有 resolved_port 字段（缺了会在真发那刻抛 AttributeError）",
              hasattr(cc.CustomControllerLink(port="Auto", mock_output=False), "resolved_port"))
    finally:
        sp.list_serial_ports = real

    print("\n--- 2) 只插了车、没插遥控器 ---")
    real = with_ports([ROBOT])
    try:
        check("Auto 退回 Stub，绝不退到机器人口上", sp.resolve_rc_port("Auto") == sp.STUB_PORT)
        target, why = dl.Dt7KeyMouseLink(port="Auto")._open_target()
        check("错误信息说人话（不是 could not open port 'Auto'）",
              target == "" and "DJI USB Virtual COM" in why, why[:60])
    finally:
        sp.list_serial_ports = real

    print("\n--- 3) 两个 DJI 口（双遥控器）---")
    real = with_ports([DT7, dict(DT7, device="COM11")])
    try:
        check("同分两个候选 -> 不猜，返回 Stub 让人显式选",
              sp.resolve_rc_port("Auto") == sp.STUB_PORT)
    finally:
        sp.list_serial_ports = real

    print("\n--- 4) 显式端口一律原样 ---")
    check("DT7 显式 COM7 不重解析", sp.resolve_rc_port("COM7") == "COM7")
    check("CC 显式 COM8 不重解析", sp.resolve_cc_port("COM8") == "COM8")
    check("空值退回 Stub（不会拿空串去开端口）",
          sp.resolve_rc_port("") == sp.STUB_PORT and sp.resolve_cc_port(None) == sp.STUB_PORT)
    check("profile 里默认值不是 Auto 时也不会被改口", dl.DEFAULT_PROFILE.get("baudrate") == 961200)

    print("\n" + ("有失败项" if FAILED else "挑口识别全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
