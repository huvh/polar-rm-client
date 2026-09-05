#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 端到端（离线）：键盘按下 -> 闸门 -> 控制层 -> 运行期 DT7 出口 -> 假 DT7 -> "车上键位"
# 唯一不在这条链上的是真实无线。分层测试各自绿不代表接起来能用，所以这条要单独钉。
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import dt7_wireless_selftest as ws                # noqa: E402
import dt7_dbus_frame as df                       # noqa: E402
from rm_client.backend import dt7_link as dl       # noqa: E402
from rm_client.backend.manager import BackendManager  # noqa: E402
from rm_client.control import KeyboardControlBridge   # noqa: E402
from rm_client.model import RobotState, build_default_registry  # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    FAILED += 0 if ok else 1


def keys_of(frames):
    out = []
    for fr in frames:
        dec = dl.decode_dt7_frame(fr)
        if dec is None:
            out.append(None)
            continue
        import struct
        out.append(struct.unpack_from("<H", dec["payload"], 8)[0])
    return out


def build(sim):
    manager = BackendManager(workspace=tempfile.mkdtemp(prefix="e2e_"),
                            scenario_key="OfficialEvent", client_id="3")
    registry = build_default_registry()
    state = RobotState()
    manager.state = state
    manager._apply_config(manager.config)
    module = registry.get("RobotLink")
    module.enabled = True
    for name, value in (("Allow Drive", True), ("Direct DT7 Egress", True),
                        ("DT7 Real TX", True), ("DT7 Port", "DT7")):
        setting = module.get_setting(name)
        if setting is not None:
            setting.value = value
    prof = dl.load_profile()
    link = dl.Dt7KeyMouseLink(port="DT7", profile=prof, mock_output=False,
                              write_bytes=sim.write)
    manager._dt7_link = link
    br = KeyboardControlBridge(publisher=None, mock_output=True)
    return manager, registry, state, br, module, link


def main() -> int:
    print("\n--- 1) 闸门全开：按键必须变成 DT7 帧里的键位，并落到车上那本账 ---")
    sim = ws.SimRobot()
    manager, registry, state, br, module, link = build(sim)
    manager.tick_polar_link(state, registry, br)
    check("C 路出口生效", br.dt7_enabled is True, br.dt7_last_error)
    check("注入的 link 没被 manager 悄悄换成另一个（口径必须一致）",
          br.dt7_link is link, f"{id(br.dt7_link)} vs {id(link)}")
    # KEY_VENDOR_2026_BITS 存的已经是**位值**（不是位序号），再移一次就变成别人家的键
    w = df.KEY_VENDOR_2026_BITS["W"]
    d = df.KEY_VENDOR_2026_BITS["D"]
    br.set_key("W", True, state, registry)
    for step in range(6):
        manager.tick_polar_link(state, registry, br)
        link._next_due = 0.0
        br.send_from_state(state, registry)
    got = keys_of(sim.frames_in)
    check("发出去的都是 22 字节的厂商帧",
          bool(sim.frames_in) and all(len(fr) == 22 for fr in sim.frames_in),
          f"{len(sim.frames_in)} 帧，首帧 {sim.frames_in[0].hex(' ').upper() if sim.frames_in else ''}")
    check("帧里的键位就是按下的 W", all(k == w for k in got if k is not None), str(got[:4]))
    check("假车那本账收到 W（= 车上 km_key 会真的出现 W）",
          (sim.keys & w) == w, hex(sim.keys))
    check("运行期解码器能认自己打的帧（两端不各说各话）", None not in got, str(got))

    print("\n--- 2) 松手必须真的清零（DT7 没有过期兜底）---")
    br.set_key("W", False, state, registry)
    link._next_due = 0.0
    br.send_from_state(state, registry)
    check("松手后发的是零键位帧", keys_of(sim.frames_in)[-1] == 0, hex(sim.keys))
    check("假车键位跟着归零", sim.keys == 0, str(sim.keys))

    print("\n--- 3) 急停：即使手还按着，也要把键位交还给驾驶员 ---")
    br.set_key("D", True, state, registry)
    link._next_due = 0.0
    br.send_from_state(state, registry)
    held = keys_of(sim.frames_in)[-1]
    manager.safety.estop_active = True
    manager.tick_polar_link(state, registry, br)
    check("急停后出口不再生效", br.dt7_enabled is False)
    check("急停时补发了零键位帧（不把手指头留在车上）",
          keys_of(sim.frames_in)[-1] == 0, f"急停前 {hex(held)} 急停后 {hex(keys_of(sim.frames_in)[-1])}")
    manager.safety.estop_active = False

    print("\n--- 4) 键鼠来源互斥：同开两条就谁都不发 ---")
    cc = module.get_setting("Custom Controller Egress")
    if cc is not None:
        cc.value = True
        manager.tick_polar_link(state, registry, br)
        before = len(sim.frames_in)
        link._next_due = 0.0
        br.send_from_state(state, registry)
        check("冲突时 DT7 一条都不写", len(sim.frames_in) == before,
              f"{before} -> {len(sim.frames_in)}")
        check("冲突原因写得出来", "只能有一个" in br.km_source_conflict, br.km_source_conflict)
        cc.value = False
        manager.tick_polar_link(state, registry, br)
        link._next_due = 0.0
        br.send_from_state(state, registry)
        check("撤掉一条后立刻恢复发送", len(sim.frames_in) > before, str(len(sim.frames_in)))

    print("\n--- 5) 鼠标增量：越界被截、不许连累驾驶键 ---")
    link._next_due = 0.0
    br.mouse_x = 9000
    br.send_from_state(state, registry)
    import struct
    dec = dl.decode_dt7_frame(sim.frames_in[-1])
    mx = struct.unpack_from("<h", dec["payload"], 0)[0]
    check("鼠标越界被截进 mouse_limit", mx == 200, str(mx))
    check("驾驶键位仍然照发（没被鼠标值连坐）",
          keys_of(sim.frames_in)[-1] == df.KEY_VENDOR_2026_BITS["D"],
          hex(keys_of(sim.frames_in)[-1]))
    br.mouse_x = 0

    print("\n--- 6) 闸门没过的所有形态都不许碰硬件 ---")
    for name in ("Allow Drive", "Direct DT7 Egress"):
        setting = module.get_setting(name)
        if setting is None:
            continue
        was = setting.value
        setting.value = False
        manager.tick_polar_link(state, registry, br)
        n0 = len(sim.frames_in)
        link._next_due = 0.0
        br.send_from_state(state, registry)
        check(f"关掉 {name} 之后一帧都不写", len(sim.frames_in) == n0, f"{n0}->{len(sim.frames_in)}")
        setting.value = was
    module.enabled = False
    manager.tick_polar_link(state, registry, br)
    n0 = len(sim.frames_in)
    link._next_due = 0.0
    br.send_from_state(state, registry)
    check("模块停用后也不写", len(sim.frames_in) == n0, f"{n0}->{len(sim.frames_in)}")
    module.enabled = True

    print("\n--- 7) 不插 C 板 USB 也必须能控车（这条链路存在的意义就是无线）---")
    sim2 = ws.SimRobot()
    m2, reg2, st2, br2, mod2, link2 = build(sim2)
    m2.polar.port = "Stub"          # 队内 0x5A 那条线没插：C 路不该依赖它
    m2.polar_bridge.reset()
    check("前置确认：队内链路确实没活跃（否则这条测试什么都没测）",
          bool(m2.polar_bridge.active) is False and bool(st2.polar_link_active) is False,
          f"{m2.polar_bridge.active} {st2.polar_link_active}")
    m2.tick_polar_link(st2, reg2, br2)
    check("没有 USB 也照样判定 C 路生效", br2.dt7_enabled is True, br2.dt7_last_error)
    n0 = len(sim2.frames_in)
    br2.set_key("W", True, st2, reg2)
    link2._next_due = 0.0
    br2.send_from_state(st2, reg2)
    check("没有 USB 也真的把帧写进了 DT7", len(sim2.frames_in) > n0,
          f"{n0} -> {len(sim2.frames_in)}")
    check("假车收到的键位就是 W（等价于车上 km_key）",
          (sim2.keys & df.KEY_VENDOR_2026_BITS["W"]) == df.KEY_VENDOR_2026_BITS["W"],
          hex(sim2.keys))

    print("\n" + ("有失败项" if FAILED else "C 路端到端（离线）全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())