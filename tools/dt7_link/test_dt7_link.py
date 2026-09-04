#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DT7 直连出口（dt7_link）的离线断言。

这里能离线证的部分都证掉，证不了的部分明确标成候选，绝不含糊：
  * 可证：帧头位域（Cmd_Set 低字节 / Cmd_Id 高字节）、datalen 不含 cmd、
    crc8 只覆盖帧头前 4 字节、crc16 覆盖整帧、profile 容错、默认不碰硬件、限流、松手归零；
  * 交叉验证：**CRC 用队内固件里那份官方 CRC 代码验收**（跟 test_cc_link 同一手法），
    这样"我以为的 0xA5 帧"跟大疆收包端的校验必须互相认；
  * 不可证（写在断言名字里，不假装）：cmd_id=17 与载荷字段顺序 —— 那是
    从厂商 `Video2025MsgID` / `Input_Device_Status` 借的候选值，要现场确认。
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from rm_client.backend import dt7_link as dl          # noqa: E402
from rm_client.control import KEYBOARD_BITS          # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1




class FakeDt7:
    def __init__(self):
        self.calls = []
        self.released = 0
        self.profile = dl.DEFAULT_KEYS
        self.port = "Stub"

    def send(self, **kw):
        self.calls.append(kw)
        return True, "ok"

    def release(self, now=None):
        self.released += 1
        return True, "ok"


def test_bridge_and_gates() -> None:
    """桥侧只转发开关打开后的指令；manager 三道闸与"默认关"是这条路的底线。"""
    import tempfile

    from rm_client.backend.manager import BackendManager
    from rm_client.control import ChassisCommand, KeyboardControlBridge
    from rm_client.model import RobotState, build_default_registry

    print("\n--- 桥侧与 manager 闸门（DT7 直连）---")
    link = FakeDt7()
    br = KeyboardControlBridge(publisher=None, mock_output=True)
    br.dt7_link = link
    check("默认不直连 DT7", br.dt7_enabled is False)
    br.send_command(ChassisCommand(seq=1, timestamp=0.0, vx=1.0, vy=0.0, wz=0.0,
                                   spin_mode=False, speed_limit=0, power_limit=0,
                                   mock_output=True, keyboard_value=1,
                                   mouse_x=-45, mouse_y=120, left_button_down=True))
    check("关着时一帧都不发", link.calls == [], str(link.calls))
    br.dt7_enabled = True
    br.send_command(ChassisCommand(seq=2, timestamp=0.0, vx=1.0, vy=0.0, wz=0.0,
                                   spin_mode=False, speed_limit=0, power_limit=0,
                                   mock_output=False, keyboard_value=0x11,
                                   mouse_x=-45, mouse_y=120, mouse_z=7,
                                   left_button_down=True, mid_button_down=True))
    got = link.calls[-1]
    check("直连用的就是 command 的键位图（位序已厂商核实）", got["pressed_bits"] == 0x11, str(got))
    check("DT7 的鼠标是增量，不是绝对像素（与 0x0306 那条不同，不能互相借用）",
          (got["mouse_dx"], got["mouse_y"], got["mouse_z"]) == (-45, 120, 7), str(got))
    check("左右键与中键都带过去", got["left"] is True and got["mid"] is True, str(got))
    br.release_direct_dt7()
    check("主动松手会发全零帧（DT7 那侧没有过期兜底）", link.released == 1, str(link.released))

    ws = tempfile.mkdtemp(prefix="dt7_gate_")
    manager = BackendManager(workspace=ws, scenario_key="OfficialEvent", client_id="3")
    registry = build_default_registry()
    state = RobotState()
    manager.state = state
    manager._apply_config(manager.config)
    module = registry.get("RobotLink")
    check("RobotLink 有 Direct DT7 Egress", module.get_setting("Direct DT7 Egress") is not None)
    check("有 DT7 Port 可指定", module.get_setting("DT7 Port") is not None)
    check("直连默认关（命令号还是候选值，不许默认开）",
          bool(module.get_setting("Direct DT7 Egress").value) is False)
    br2 = KeyboardControlBridge(publisher=None, mock_output=True)
    on = module.get_setting("Direct DT7 Egress")
    drive = module.get_setting("Allow Drive")
    on.value = True
    drive.value = False
    module.enabled = True
    manager.tick_polar_link(state, registry, br2)
    check("没 Allow Drive -> 不生效并写明",
          br2.dt7_enabled is False and "未生效" in br2.dt7_last_error, br2.dt7_last_error)
    drive.value = True
    manager.tick_polar_link(state, registry, br2)
    check("三闸齐开 -> 生效", br2.dt7_enabled is True, str(br2.dt7_enabled))
    check("注入的是 mock 发送器（不会偷偷写真串口）",
          br2.dt7_link is not None and br2.dt7_link.mock_output is True)
    manager.safety.estop_active = True
    manager.tick_polar_link(state, registry, br2)
    check("急停一票否决", br2.dt7_enabled is False)
    manager.safety.estop_active = False
    on.value = False
    manager.tick_polar_link(state, registry, br2)
    check("关开关后立刻停", br2.dt7_enabled is False)

def main() -> int:
    test_bridge_and_gates()
    # --- 1) 命令号位域（厂商 DJI_PRO_CMD_T 已核实） ---
    check("Cmd_Set 占低字节、Cmd_Id 占高字节",
          dl.pack_cmd(0, 17) == bytes([0x00, 0x11]), dl.pack_cmd(0, 17).hex(" "))
    check("两个半字节都保留得回来",
          dl.decode_dt7_frame(dl.build_frame(3, 17, bytes([1]), 0))["cmd_set"] == 3
          and dl.decode_dt7_frame(dl.build_frame(3, 17, bytes([1]), 0))["cmd_id"] == 17)
    for bad in ((0x100, 0), (0, 0x100), (-1, 0)):
        try:
            dl.pack_cmd(*bad)
            check(f"越界命令号 {bad} 必须报错", False)
        except ValueError:
            check(f"越界命令号 {bad} 被拒", True)

    # --- 2) 帧结构 ---
    PAY = bytes([1, 2, 3, 4])                      # 别再写字面转义，容易把自己骗了
    f = dl.build_frame(0, 17, PAY, seq=9)
    check("SOF=0xA5", f[0] == 0xA5, hex(f[0]))
    check("datalen 只算 cmd 之后的载荷（不含 cmd 那 2 字节）",
          struct.unpack_from("<H", f, 1)[0] == 4, str(struct.unpack_from("<H", f, 1)[0]))
    check("seq 在第 4 字节", f[3] == 9, str(f[3]))
    check("整帧 = 5 + 2 + 载荷 + 2", len(f) == 5 + 2 + 4 + 2, str(len(f)))
    d = dl.decode_dt7_frame(f)
    check("encode/decode 互逆", d is not None and d["payload"] == PAY
          and d["seq"] == 9 and d["cmd_id"] == 17, str(d))
    tampered = bytearray(f); tampered[7] ^= 0x01
    liedin = bytearray(f); liedin[1] += 1
    check("改一个字节 / 长度域造假都解不出东西",
          dl.decode_dt7_frame(bytes(tampered)) is None
          and dl.decode_dt7_frame(bytes(liedin)) is None
          and dl.decode_dt7_frame(b"") is None)

    # --- 3) 与队内固件那份官方 CRC 交叉验收 ---
    import subprocess
    import tempfile
    try:
        import test_cc_link as tc
        fw = tc.DEFAULT_REPO if hasattr(tc, "DEFAULT_REPO") else Path(
            r"C:\\Users\\lulunomaro\\Desktop\\claude\\openzenuicodexver\\tmp_polarbear\\StandardRobotpp")
        if not (fw / "components/support/CRC8_CRC16.c").exists():
            print("[SKIP] 没有固件树，跳过 CRC 交叉验收")
        else:
            with tempfile.TemporaryDirectory() as td:
                exe = tc.build_crc_verifier(fw, td)
                if exe is None:
                    print("[SKIP] CRC 验收器编译失败")
                else:
                    v = tc.verify_with_firmware(exe, bytes(f))
                    check("**固件那份官方 CRC 认这帧：CRC8 通过**", v["crc8_ok"] == 1, str(v))
                    check("**固件那份官方 CRC 认这帧：CRC16 通过**", v["crc16_ok"] == 1, str(v))
                    v2 = tc.verify_with_firmware(exe, bytes(tampered))
                    check("改一字节必须被固件 CRC16 拒掉", v2["crc16_ok"] == 0, str(v2))
    except Exception as exc:
        print(f"[SKIP] CRC 交叉验收未跑：{type(exc).__name__}: {exc}")

    # --- 4) profile：现场可改 + 坏配置不致命 ---
    check("仓库带 dt7 profile", dl.PROFILE_FILE.exists(), str(dl.PROFILE_FILE))
    base = dl.load_profile()
    check("默认 cmd_id 候选 = 17（厂商 Video2025MsgID.CMD_ID_Keyboard，**未经现场确认**）",
          base["cmd_id_keyboard"] == 17, str(base))
    fp = os.path.join(os.path.dirname(dl.PROFILE_FILE), "_t_dt7.json")
    tmp = Path(os.environ.get("TEMP", "/tmp")) / "dt7_profile_test.json"
    tmp.write_text(json.dumps({"cmd_id_keyboard": 42, "cmd_set": 1}), encoding="utf-8")
    one = dl.load_profile(str(tmp))
    check("改 profile 就能换命令号（不改代码）",
          (one["cmd_id_keyboard"], one["cmd_set"]) == (42, 1), str(one))
    check("没写的字段保留默认", one["payload_layout"] == base["payload_layout"])
    tmp.write_text("{坏 json", encoding="utf-8")
    check("profile 坏了退回默认（不许把链路打瘫）",
          dl.load_profile(str(tmp))["cmd_id_keyboard"] == 17)
    tmp.write_text(json.dumps({"cmd_id_keyboard": 99999, "baudrate": 7, "max_hz": 0}),
                   encoding="utf-8")
    weird = dl.load_profile(str(tmp))
    check("越界的命令号/波特率/频率被拒收，用默认",
          (weird["cmd_id_keyboard"], weird["baudrate"], weird["max_hz"])
          == (17, 115200, 30.0), str(weird))
    tmp.unlink(missing_ok=True)

    # --- 5) 发送器：默认不碰硬件、限流、松手归零、载荷顺序 ---
    link = dl.Dt7KeyMouseLink()
    check("默认 mock（不碰硬件）", link.mock_output is True)
    ok, why = link.send(pressed_bits=(1 << KEYBOARD_BITS["W"]) | (1 << KEYBOARD_BITS["SHIFT"]),
                        mouse_dx=-45, mouse_y=120, mouse_z=7, left=True)
    dec = dl.decode_dt7_frame(link.last_frame) or {}
    x, y, z, lb, rb, key, mid = struct.unpack(link.profile["payload_layout"], dec.get("payload", b""))
    check("载荷字段顺序与 Input_Device_Status 一致",
          (x, y, z, lb, rb, key, mid) == (-45, 120, 7, 1, 0, 0x11, 0),
          str((x, y, z, lb, rb, key, mid)))
    check("发送计数在走", ok and link.sent == 1, f"{ok} {why}")
    ok2, why2 = link.send(pressed_bits=1)
    check("同一时刻再发被限流丢掉", not ok2 and "上限" in why2 and link.dropped_rate == 1,
          f"{ok2} {why2}")
    link._next_due = 0.0
    link.release()
    dec2 = dl.decode_dt7_frame(link.last_frame) or {}
    check("release 把键盘位图归零",
          struct.unpack(link.profile["payload_layout"], dec2["payload"])[5] == 0,
          str(dec2))
    written = []
    live = dl.Dt7KeyMouseLink(mock_output=False, write_bytes=written.append)
    live._next_due = 0.0
    live.send(pressed_bits=1)
    check("真发模式才走 write_bytes", len(written) == 1 and written[0] == live.last_frame)

    boom = dl.Dt7KeyMouseLink(mock_output=False, write_bytes=lambda b: (_ for _ in ()).throw(
        OSError("口被占用")))
    boom._next_due = 0.0
    okb, whyb = boom.send(pressed_bits=1)
    check("写串口失败要有原因且不涨计数",
          not okb and "口被占用" in boom.last_error and boom.sent == 0, f"{whyb}")
    print("\\n" + ("有失败项" if FAILED else "DT7 直连出口（帧/位域/profile/限流）全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
