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




def test_manager_gates() -> None:
    """UI 开关 -> BackendManager 三道闸 -> 桥上的 enabled。

    这一节是"实战能不能无线开车"的真正关口：界面上那个勾只是意愿，
    manager 每次 tick 都会按 急停 / 模块启用 / Allow Drive 重算。
    同时钉住一条设计决定：**不要求 0x5A USB 链路活着**，
    否则"不插线无线开车"这个目标会被自己的闸门锁死。
    """
    import tempfile

    from rm_client.backend.manager import BackendManager
    from rm_client.model import RobotState, build_default_registry

    print("\n--- RobotLink 开关与三道闸 ---")
    workspace = tempfile.mkdtemp(prefix="radio_km_")
    manager = BackendManager(workspace=workspace, scenario_key="OfficialEvent", client_id="3")
    registry = build_default_registry()
    state = RobotState()
    manager.state = state
    manager._apply_config(manager.config)

    module = registry.get("RobotLink")
    check("RobotLink 有 Radio KM Egress 这个开关",
          module.get_setting("Radio KM Egress") is not None)
    check("开关默认关", bool(module.get_setting("Radio KM Egress").value) is False)

    class FakeControl(KeyboardControlBridge):
        def __init__(self):
            super().__init__(publisher=None, mock_output=True)

    control = FakeControl()
    setting = module.get_setting("Radio KM Egress")
    drive = module.get_setting("Allow Drive")

    # 只开开关：Allow Drive 没给 -> 不得生效
    setting.value = True
    drive.value = False
    module.enabled = True
    manager.tick_polar_link(state, registry, control)
    check("只勾开关、没 Allow Drive -> 不生效", control.radio_km_enabled is False,
          str(control.radio_km_enabled))
    check("不生效时给得出原因（不让现场猜）", "Allow Drive" in control.radio_km_gate_reason,
          control.radio_km_gate_reason)

    # 补上 Allow Drive，但模块没启用 -> 不得生效
    drive.value = True
    module.enabled = False
    manager.tick_polar_link(state, registry, control)
    check("模块未启用 -> 不生效", control.radio_km_enabled is False)
    check("原因是模块未启用", "RobotLink" in control.radio_km_gate_reason,
          control.radio_km_gate_reason)

    # 三闸齐开，且 **0x5A USB 链路是死的**（这里从不 feed bridge）-> 必须生效
    module.enabled = True
    manager.tick_polar_link(state, registry, control)
    check("三闸齐开就生效，且不要求插 USB 线", control.radio_km_enabled is True,
          str(control.radio_km_enabled))
    check("生效后清掉旧的闸门原因（不留骗人的残留）",
          control.radio_km_gate_reason == "", control.radio_km_gate_reason)

    # 急停必须一票否决
    manager.safety.estop_active = True
    manager.tick_polar_link(state, registry, control)
    check("急停一票否决", control.radio_km_enabled is False)
    check("急停时原因写明", "急停" in control.radio_km_gate_reason,
          control.radio_km_gate_reason)

    # 关掉开关后必须立刻回到"不生效"，且 manager 每 tick 重算（不留残留）
    manager.safety.estop_active = False
    setting.value = False
    manager.tick_polar_link(state, registry, control)
    # --- 车上回读（km_rx / km_key）决定"实况"到底是什么 ---
    setting.value = True
    drive.value = True
    module.enabled = True
    manager.tick_polar_link(state, registry, control)
    check("开关开了但车上计数读不到 -> no-readback（不当成没收到）",
          control.radio_km_link_state == "no-readback", control.radio_km_link_state)
    manager.polar_bridge.debug_packages = {"km_rx": 0.0, "km_key": 0.0}
    manager.tick_polar_link(state, registry, control)
    check("车上回了 0 帧 -> silent，并给出口向排查话",
          control.radio_km_link_state == "silent", control.radio_km_link_state)
    check("silent 的话里点明图传发送端那一路串口", "921600" in control.radio_km_link_note,
          control.radio_km_link_note)
    # 光说"921600"会把人带去接一根根本没用的线：本固件没有那一路 UART。
    # 所以提示必须同时给出两条真能走的做法，缺任何一条都算提示退化。
    note = control.radio_km_link_note
    check("提示要说清[本固件没有 921600 那一路]（否则操作员会去接线白等）",
          "没有" in note and "USART" in note, note[:70])
    check("提示要给出两条可行做法（C 路 / 车载电脑喂 HostKmFeed）",
          "C 路" in note and "HostKmFeed" in note, note[-80:])
    manager.polar_bridge._handle_debug({"packages": {"km_rx": 12.0, "km_key": 17.0}})
    manager.tick_polar_link(state, registry, control)
    check("计数在涨 -> live", control.radio_km_link_state == "live",
          control.radio_km_link_state)
    check("live 时把车上的帧数带出来", control.radio_km_robot_rx == 12,
          str(control.radio_km_robot_rx))
    check("车上合并后的键位也回读到了", control.radio_km_robot_key == 17,
          str(control.radio_km_robot_key))
    # 「帧到了」和「这一档会用它的键位」是两件事：默认档 CL_KM_RC 下 0x0311 整个
    # 不参与，但到达计数在 referee 收到那一帧就涨 —— 只报「已收到 N 帧」会被读成「能控车了」
    manager.polar_bridge.debug_packages = {"km_rx": 240.0, "km_key": 0.0, "km_pol": 1.0}
    manager.tick_polar_link(state, registry, control)
    check("车上是 rc 档时把[不参与]写进提示（默认档最容易被误读）",
          control.radio_km_policy == "rc" and "不参与" in control.radio_km_link_note,
          control.radio_km_link_note)
    manager.polar_bridge.debug_packages = {"km_rx": 280.0, "km_key": 0.0, "km_pol": 3.0}
    manager.tick_polar_link(state, registry, control)
    check("rc_vt 档时提示里说得出档位", control.radio_km_policy == "rc_vt"
          and "rc_vt" in control.radio_km_link_note, control.radio_km_link_note)
    manager.polar_bridge.debug_packages = {"km_rx": 320.0, "km_key": 0.0}
    manager.tick_polar_link(state, registry, control)
    check("车上没报档位要明说，不许当成[能用了]",
          control.radio_km_policy == "?" and "没报档位" in control.radio_km_policy_hint,
          control.radio_km_policy_hint)
    from rm_client.control import describe_km_policy as dkp
    check("五档编号都翻对名字",
          [dkp(i)[0] for i in range(5)] == ["none", "rc", "vt", "rc_vt", "vt_rc"],
          str([dkp(i)[0] for i in range(5)]))
    check("只有 none/rc 两档被标成图传不参与",
          [dkp(i)[1] for i in range(5)] == [False, False, True, True, True],
          str([dkp(i)[1] for i in range(5)]))
    check("垃圾值归到[没报档位]，不许随便猜一档",
          dkp(None)[0] == "?" and dkp("x")[0] == "?" and dkp(77)[0] == "?")
    manager.tick_polar_link(state, registry, control)
    check("计数不再涨 -> stalled（跟 silent 区分开）",
          control.radio_km_link_state == "stalled", control.radio_km_link_state)
    # 关掉开关后不得把上一轮的实况留在脸上
    setting.value = False
    manager.tick_polar_link(state, registry, control)
    check("关开关后不再尝试发送", control.radio_km_enabled is False)
    check("关开关后闸门原因也清空", control.radio_km_gate_reason == "",
          control.radio_km_gate_reason)
    check("关开关后实况回到 off", control.radio_km_link_state == "off",
          control.radio_km_link_state)


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
    check("出口缺失时错误原因写清楚（不静默，也不冒充主通道）",
          "publish_km_control" in br2.radio_km_last_error, br2.radio_km_last_error)
    check("出口缺失不污染主通道 last_error", br2.last_error == "", br2.last_error)

    # --- 位序对表：客户端编码必须等于**大疆自己二进制里**那套键位位序 ---
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dt7_dbus_frame as df
    from rm_client.control import KEYBOARD_BITS
    check("客户端 KEYBOARD_BITS == 官方选手端枚举（dump.cs:136133）",
          all(KEYBOARD_BITS[k] == i for i, k in enumerate(df.KEY_ORDER_VENDOR_2026)),
          str(KEYBOARD_BITS))
    check("0x1F 默认掩码 = W/S/A/D + SHIFT（小陀螺），不含 Q/E",
          (0x1F & (1 << KEYBOARD_BITS["SHIFT"])) != 0
          and (0x1F & (1 << KEYBOARD_BITS["Q"])) == 0
          and (0x1F & (1 << KEYBOARD_BITS["E"])) == 0,
          hex(0x1F))
    check("2016 手册那套位序确实与现役不同（否则这条守卫没意义）",
          df.KEY_ORDER_DJI2016[4:8] != df.KEY_ORDER_VENDOR_2026[4:8],
          str(df.KEY_ORDER_DJI2016[4:8]))

    blob = proto.encode_km_control_payload(sequence=1, keyboard_value=0x1F)
    check("载荷 26 字节 = 固件 prm1_km_cmd_t",
          len(blob) == proto.TEAM_CONTROL_KM_SIZE == 26, str(len(blob)))
    check("不超 CustomControl 的 30 字节上限", len(blob) <= 30)
    check("解回来还是同一份值",
          proto.decode_km_control_payload(blob)["keyboard_value"] == 0x1F)
    check("别的 kind 不会被当键鼠解", proto.decode_km_control_payload(
        proto.encode_vision_control_payload(sequence=1, yaw_deg=1.0,
                                           pitch_deg=2.0) + b"\x00" * 12) is None)

    # --- 独立出口语义：开关就是它的开关，不看主通道脸色 ---
    pub3 = FakePub()
    br3 = KeyboardControlBridge(publisher=pub3, mock_output=True)   # mock 模式
    br3.radio_km_enabled = True
    br3.send_command(cmd(1 << 0))
    check("mock 模式下开关打开照样走出口（由 MQTT 层决定上不上网络）",
          len(pub3.km) == 1, str(pub3.km))
    check("mock 模式下计数器也照走，现场才分得清'\"没开\"和\"开了但被 mock\"'",
          br3.radio_km_sent == 1, str(br3.radio_km_sent))

    class KmcFails(FakePub):
        def publish_keyboard_mouse(self, *a, **k):
            return False, "官方 MQTT 未连接"

    pub4 = KmcFails()
    br4 = KeyboardControlBridge(publisher=pub4, mock_output=False)
    br4.radio_km_enabled = True
    br4.send_command(cmd(1 << 2))
    check("KMC 失败不拖累无线键鼠出口", len(pub4.km) == 1, str(pub4.km))
    check("KMC 的错误仍记在 last_error（主通道诊断不被污染）",
          br4.last_error == "官方 MQTT 未连接", br4.last_error)

    class KmFails(FakePub):
        def publish_km_control(self, **kw):
            return False, "急停激活，禁止发布"

    br5 = KeyboardControlBridge(publisher=KmFails(), mock_output=False)
    br5.radio_km_enabled = True
    br5.send_command(cmd(1))
    check("出口被门控时原因单独记录", br5.radio_km_last_error == "急停激活，禁止发布",
          br5.radio_km_last_error)
    check("出口失败不污染主通道 last_error", br5.last_error == "", br5.last_error)
    check("出口失败不涨计数", br5.radio_km_sent == 0, str(br5.radio_km_sent))

    test_manager_gates()

    # --- 自检判据：必须看车上计数，不能看客户端自己发了多少 ---
    from rm_client.control import evaluate_radio_km_selftest as ev

    ok, why = ev(100, 180, 10, 90)
    check("车上计数在涨 -> PASS", ok and "100->180" in why, why)
    ok, why = ev(-1, -1, 10, 90)
    check("读不到回读 -> 不能算通过（要插 USB）", not ok and "USB" in why, why)
    ok, why = ev(100, -1, 10, 90)
    check("自检中途回读断了 -> FAIL 而不是崩溃", not ok and "USB" in why, why)
    ok, why = ev(100, 100, 10, 10)
    check("一帧都没发出去 -> FAIL 说是客户端侧", not ok and "没发出去" in why, why)
    ok, why = ev(100, 100, 10, 190)
    check("**发了但车上没涨 -> FAIL**（这正是自证与实证的差别）",
          not ok and "921600" in why, why)

    print("\n" + ("有失败项" if FAILED else "无线键鼠出口客户端侧全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
