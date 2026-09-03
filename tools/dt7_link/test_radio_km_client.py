#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无线键鼠出口（PRM1 kind=3 -> CustomControl -> 0x0311）客户端侧断言。

三件容易悄悄坏掉的事：
 1. 默认必须**关**（开着等于没确认就占用图传带宽）；
 2. 关着的时候一个 CustomControl 都不许多发；
 3. 打开后键位必须能清零发走（粘键 = 车刹不住）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rm_client.backend import protocol as proto                      # noqa: E402
from rm_client.control import ChassisCommand, KeyboardControlBridge  # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


class FakePub:
    def __init__(self):
        self.kmc, self.km = [], []

    def publish_keyboard_mouse(self, mx, my, mz, *, left, right, keyboard_value, mid):
        self.kmc.append(keyboard_value)
        return True, "ok"

    def publish_km_control(self, **kw):
        self.km.append(kw)
        return True, "ok"


def cmd(keys, mx=0, my=0):
    return ChassisCommand(seq=1, timestamp=0.0, vx=0.0, vy=0.0, wz=0.0,
                          spin_mode=False, speed_limit=0, power_limit=0,
                          mock_output=False, keyboard_value=keys,
                          mouse_x=mx, mouse_y=my)


def main() -> int:
    pub = FakePub()
    br = KeyboardControlBridge(publisher=pub, mock_output=False)
    check("默认是关的", br.radio_km_enabled is False)

    br.send_command(cmd(1 << 0))                       # W
    check("关着时 KMC 照发", len(pub.kmc) == 1, str(pub.kmc))
    check("关着时一条无线键鼠都不发", pub.km == [], str(pub.km))

    br.radio_km_enabled = True
    br.send_command(cmd((1 << 0) | (1 << 1), mx=-45, my=120))   # W+S
    check("打开后无线键鼠出口跟着发", len(pub.km) == 1, str(len(pub.km)))
    sent = pub.km[-1]
    check("转发的键位与鼠标和 KMC 完全同一份值",
          (sent["keyboard_value"], sent["mouse_x"], sent["mouse_y"]) == (3, -45, 120),
          str(sent))
    check("计数器在走", br.radio_km_sent == 1, str(br.radio_km_sent))

    br.send_command(cmd(0))                            # 全部松手
    check("松键后发过全零键位帧（不粘键）",
          pub.km[-1]["keyboard_value"] == 0, str([k["keyboard_value"] for k in pub.km]))

    # 发布器没有这个口的时候，不能把主通道（KMC）的成功也带崩
    class NoKm(FakePub):
        publish_km_control = None      # type: ignore[assignment]

    # 注意只能构造一次：早先写成 NoKm() 两次，断言看的是 A 实例、
    # 桥用的是 B 实例，于是"KMC 没发出去"这条假红了一个测试。
    pub2 = NoKm()
    br2 = KeyboardControlBridge(publisher=pub2, mock_output=False)
    br2.radio_km_enabled = True
    br2.send_command(cmd(1))
    check("出口缺失时 KMC 仍然发出去了", len(pub2.kmc) == 1, str(pub2.kmc))
    check("出口缺失时错误原因写清楚（不静默）",
          "publish_km_control" in br2.last_error, br2.last_error)

    blob = proto.encode_km_control_payload(sequence=1, keyboard_value=0x1F)
    check("载荷 26 字节 = 固件 prm1_km_cmd_t",
          len(blob) == proto.TEAM_CONTROL_KM_SIZE == 26, str(len(blob)))
    check("不超 CustomControl 的 30 字节上限", len(blob) <= 30)
    check("解回来还是同一份值",
          proto.decode_km_control_payload(blob)["keyboard_value"] == 0x1F)
    check("别的 kind 不会被当键鼠解", proto.decode_km_control_payload(
        proto.encode_vision_control_payload(sequence=1, yaw_deg=1.0,
                                           pitch_deg=2.0) + b"\x00" * 12) is None)

    print("\n" + ("有失败项" if FAILED else "无线键鼠出口客户端侧全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
