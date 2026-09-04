#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""自定义控制器出口（cc_link）的离线断言。

为什么这里必须有一次"跟固件真代码对表"
--------------------------------------
0x0306 这条路的帧是**裁判系统串口帧**（0xA5 头 + CRC8 + CRC16）。
文档只描述字段，字节序/覆盖范围这种细节一旦搞错，选手端整帧丢弃，
而现象是"我明明发了、车没反应"——最难查的一类。所以这里不是"自己跟自己一致"，
而是**把队内固件里那份官方 CRC 代码编成 exe，让它来验收 Python 拼的帧**：
`components/support/CRC8_CRC16.c` 的表与函数原样抽出来用，改算法必红。

其余断言钉住文档里那几个容易记错的点：
  * `data_length` 只算 cmd_id 之后的载荷（算术来自 referee_usart_task.c:124-169）；
  * 0x0306 是**绝对像素坐标**不是增量（表 1-43 备注），鼠标键各占一个 bit12；
  * 2 键无冲是官方限制，第三个键必须**报出来**，不许静默丢；
  * 松手帧键值为 0；频率超上限要丢帧并计数。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.backend import cc_link as cc            # noqa: E402
from rm_client.backend.cc_link import (               # noqa: E402
    CC_CMD_KEYMOUSE, CC_CMD_ROBOT_INTERACT, encode_cc_frame,
    encode_keymouse_0306, keys_to_two_usages, decode_cc_frame,
    CustomControllerLink, VirtualCursor,
)

FAILED = 0
DEFAULT_FIRMWARE = Path(r"C:\Users\lulunomaro\Desktop\claude\openzenuicodexver"
                       r"\tmp_polarbear\StandardRobotpp")
CRC_C = "components/support/CRC8_CRC16.c"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def extract_crc_source(firmware: Path) -> str:
    """把固件里那份官方 CRC 实现原样切出来（从 CRC8_INIT 到文件末尾）。"""
    src = (firmware / CRC_C).read_text(encoding="utf-8", errors="ignore")
    i = src.index("const uint8_t CRC8_INIT")
    j = src.rindex("}")                      # 最后一个函数 append_CRC16_check_sum 的收尾
    body = src[i:j + 1]
    assert "get_CRC8_check_sum" in body and "wCRC_table" in body, "CRC 代码抽取越界"
    return body


TU = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>

@@CRC@@

int main(int argc, char **argv)
{
    uint8_t frame[256];
    unsigned int i, b;
    unsigned int n;
    if (argc < 2) { printf("usage crc_verify hex\n"); return 2; }
    n = (unsigned int)(strlen(argv[1]) / 2);
    if (n > sizeof(frame) || n < 9) { printf("bad length\n"); return 2; }
    for (i = 0; i < n; i++) { sscanf(argv[1] + i * 2, "%02x", &b); frame[i] = (uint8_t)b; }
    /* 与裁判系统收包一致：CRC8 校验帧头 5 字节（内部按 length-1 计算），
       CRC16 校验整帧去掉尾部 2 字节。输出四个数，顺序固定：
       verify_crc8  verify_crc16  expect_crc8  expect_crc16 */
    printf("%u %u %u %u\n",
           (unsigned)verify_CRC8_check_sum(frame, 5),
           (unsigned)verify_CRC16_check_sum(frame, n),
           (unsigned)get_CRC8_check_sum(frame, 4, CRC8_INIT),
           (unsigned)get_CRC16_check_sum(frame, n - 2, CRC16_INIT));
    return 0;
}
"""


def parse_verifier_stdout(text: str) -> dict:
    nums = re.findall(r"\d+", text or "")
    if len(nums) < 4:
        raise ValueError(f"验收器输出不可解析: {text!r}")
    return {"crc8_ok": int(nums[0]), "crc16_ok": int(nums[1]),
            "crc8_expect": int(nums[2]), "crc16_expect": int(nums[3]),
            "header_len": 5, "frame_len": 0}


def build_crc_verifier(firmware: Path, td: str) -> Path | None:
    tu = TU.replace("@@CRC@@", extract_crc_source(firmware))
    cpath = Path(td) / "crc_verify.c"
    epath = Path(td) / "crc_verify.exe"
    cpath.write_text(tu, encoding="utf-8")
    build = subprocess.run(
        [sys.executable, "-m", "ziglang", "cc", "-O0", "-w", "-o", str(epath), str(cpath)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("固件官方 CRC 代码编成验收器成功", build.returncode == 0,
          ((build.stderr or "") + (build.stdout or ""))[-400:])
    return epath if build.returncode == 0 else None


def verify_with_firmware(exe: Path, frame: bytes) -> dict:
    run = subprocess.run([str(exe), frame.hex()], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return parse_verifier_stdout(run.stdout)




class FakeLink:
    """假自定义控制器发送器：记录每一次的按键集合与 release 调用。"""

    def __init__(self):
        self.calls = []
        self.released = 0
        self.dropped_keys: list[str] = []
        self.mock_output = True
        self.port = "Stub"
        self.max_hz = 30.0

    def send_keymouse(self, *, pressed, dx=0, dy=0, left=False, right=False, now=None):
        self.calls.append((tuple(pressed), dx, dy, left, right))
        self.dropped_keys = [p for p in pressed if p not in ("W", "S", "A", "D", "SHIFT")]
        return True, "ok"

    def release_all(self, now=None):
        self.released += 1
        return True, "ok"


def test_bridge_side() -> None:
    """桥这一侧要钉住：默认只转发驾驶四键、Q/E 被挡、急停会归零。"""
    from rm_client.control import ChassisCommand, KeyboardControlBridge

    print("\n--- KeyboardControlBridge 的自定义控制器出口 ---")
    link = FakeLink()
    br = KeyboardControlBridge(publisher=None, mock_output=True)
    br.cc_link = link
    check("默认 cc 关着，一个字节都不发", br.cc_enabled is False)
    br.send_command(ChassisCommand(seq=1, timestamp=0.0, vx=1.0, vy=0.0, wz=0.0,
                                  spin_mode=False, speed_limit=0, power_limit=0,
                                  mock_output=True, keyboard_value=0x01, mouse_x=9,
                                  mouse_y=-4, left_button_down=True))
    check("关着时不转发", link.calls == [], str(link.calls))
    br.cc_enabled = True
    br.send_command(ChassisCommand(seq=2, timestamp=0.0, vx=1.0, vy=0.0, wz=0.0,
                                  spin_mode=False, speed_limit=0, power_limit=0,
                                  mock_output=True, keyboard_value=0x01 | 0x40,
                                  mouse_x=9, mouse_y=-4, left_button_down=True))
    check("默认掩码只放行 W（Q=bit6 被挡）",
          link.calls[-1][0] == ("W",), str(link.calls[-1]))
    br.cc_key_mask = 0x1F
    br.send_command(ChassisCommand(seq=3, timestamp=0.0, vx=0.0, vy=0.0, wz=0.0,
                                  spin_mode=True, speed_limit=0, power_limit=0,
                                  mock_output=True, keyboard_value=0x11,
                                  mouse_x=0, mouse_y=0))
    check("开了 Allow Spin Key 后 SHIFT 才允许经 0x0306 注入",
          set(link.calls[-1][0]) == {"W", "SHIFT"}, str(link.calls[-1]))
    check("鼠标增量原样带给选手端（由 VirtualCursor 攒成绝对坐标）",
          link.calls[-1][1:3] == (0, 0) and link.calls[-2][1:3] == (9, -4),
          str(link.calls[-2:]))
    br.release_custom_controller()
    check("release 会归零选手端那侧的键鼠", link.released == 1, str(link.released))

    # 出口报错不许污染主通道
    class Boom(FakeLink):
        def send_keymouse(self, **kw):
            raise RuntimeError("串口被占用")

    br2 = KeyboardControlBridge(publisher=None, mock_output=True)
    br2.cc_link = Boom()
    br2.cc_enabled = True
    br2.send_command(ChassisCommand(seq=4, timestamp=0.0, vx=0.0, vy=0.0, wz=0.0,
                                    spin_mode=False, speed_limit=0, power_limit=0,
                                    mock_output=False, keyboard_value=1))
    check("出口异常只记在自己的 cc_last_error 里",
          "串口被占用" in br2.cc_last_error and br2.last_error == "",
          f"{br2.cc_last_error!r} / {br2.last_error!r}")


def test_manager_gates() -> None:
    """manager 侧：三道闸 + 掩码跟 Allow Spin Key + 急停归零。"""
    import tempfile

    from rm_client.backend.manager import BackendManager
    from rm_client.model import RobotState, build_default_registry

    print("\n--- manager 的自定义控制器闸门 ---")
    ws = tempfile.mkdtemp(prefix="cc_gate_")
    manager = BackendManager(workspace=ws, scenario_key="OfficialEvent", client_id="3")
    registry = build_default_registry()
    state = RobotState()
    manager.state = state
    manager._apply_config(manager.config)
    module = registry.get("RobotLink")
    for name in ("Custom Controller Egress", "CC Port", "CC Hz", "CC Mock Writes"):
        check(f"RobotLink 有 {name}", module.get_setting(name) is not None)
    check("出口默认关", bool(module.get_setting("Custom Controller Egress").value) is False)
    check("默认不写真串口（CC Mock Writes 必须默认 True）",
          bool(module.get_setting("CC Mock Writes").value) is True)
    check("频率默认取官方上限 30Hz", float(module.get_setting("CC Hz").value) == 30.0,
          str(module.get_setting("CC Hz").value))

    class Ctrl:
        last_command = None

    from rm_client.control import KeyboardControlBridge
    control = KeyboardControlBridge(publisher=None, mock_output=True)
    on = module.get_setting("Custom Controller Egress")
    drive = module.get_setting("Allow Drive")
    spin = module.get_setting("Allow Spin Key")
    on.value = True
    drive.value = False
    module.enabled = True
    manager.tick_polar_link(state, registry, control)
    check("没给 Allow Drive -> 不生效并写明原因",
          control.cc_enabled is False and "Allow Drive" in control.cc_last_error,
          control.cc_last_error)
    drive.value = True
    manager.tick_polar_link(state, registry, control)
    check("三闸齐开 -> 生效", control.cc_enabled is True, str(control.cc_enabled))
    check("注入的是 mock 发送器（现场先看不写）",
          control.cc_link is not None and control.cc_link.mock_output is True)
    check("默认掩码只放驾驶四键", control.cc_key_mask == 0x0F, hex(control.cc_key_mask))
    spin.value = True
    manager.tick_polar_link(state, registry, control)
    check("Allow Spin Key 才把 SHIFT 放进 0x0306 掩码",
          control.cc_key_mask == 0x1F, hex(control.cc_key_mask))
    manager.safety.estop_active = True
    manager.tick_polar_link(state, registry, control)
    check("急停一票否决", control.cc_enabled is False and "急停" in control.cc_last_error,
          control.cc_last_error)
    manager.safety.estop_active = False
    on.value = False
    manager.tick_polar_link(state, registry, control)
    check("关开关后立刻不生效", control.cc_enabled is False)

def main() -> int:
    firmware = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
        else DEFAULT_FIRMWARE
    if not (firmware / CRC_C).exists():
        print(f"SKIP: 找不到 {firmware / CRC_C}")
        return 0

    payload = encode_keymouse_0306(key1=cc.HID_USAGE["W"], key2=cc.HID_USAGE["SHIFT"],
                                   x=1000, y=600, left=True)
    frame = encode_cc_frame(CC_CMD_KEYMOUSE, payload, seq=7)

    # --- 1) 帧结构：字段位置与文档/固件算法一致 ---
    check("帧头 SOF=0xA5", frame[0] == 0xA5, hex(frame[0]))
    check("data_length 只算 cmd_id 之后的载荷（8）",
          frame[1] == len(payload) and frame[2] == 0, f"{frame[1:3].hex(' ')}")
    check("seq 在第 4 字节", frame[3] == 7, str(frame[3]))
    check("cmd_id 小端紧跟帧头", frame[5:7] == bytes([0x06, 0x03]), frame[5:7].hex(" "))
    check("整帧长度 = 5 + 2 + 8 + 2", len(frame) == 17, str(len(frame)))
    check("载荷尾两字节是保留位（必须为 0）", frame[-4:-2] == b"\x00\x00", frame[-4:-2].hex())

    # --- 2) 用固件那份 CRC 代码验收 ---
    with tempfile.TemporaryDirectory() as td:
        exe = build_crc_verifier(firmware, td)
        if exe is not None:
            v = verify_with_firmware(exe, frame)
            check("**固件官方 CRC 实现认这条帧：CRC8 通过**", v["crc8_ok"] == 1, str(v))
            check("**固件官方 CRC 实现认这条帧：CRC16 通过**", v["crc16_ok"] == 1, str(v))
            bad = bytearray(frame)
            bad[-3] ^= 0x01                      # 改一个数据字节
            v2 = verify_with_firmware(exe, bytes(bad))
            check("改一个字节必须被固件 CRC16 拒掉", v2["crc16_ok"] == 0, str(v2))
            bad2 = bytearray(frame)
            bad2[1] += 2                         # 只改长度、不动尾部
            v3 = verify_with_firmware(exe, bytes(bad2))
            check("长度域造假必须被拒", v3["crc8_ok"] == 0 or v3["crc16_ok"] == 0, str(v3))

    # --- 3) Python 自己也能解回来（回放抓包要用） ---
    dec = decode_cc_frame(frame)
    check("encode/decode 互逆", dec is not None and dec["cmd_id"] == CC_CMD_KEYMOUSE
          and dec["seq"] == 7 and dec["data"] == payload, str(dec))
    corrupt = bytearray(frame); corrupt[-3] ^= 0x01
    lie_len = bytearray(frame); lie_len[1] += 2
    check("坏帧/长度造假都解不出东西",
          decode_cc_frame(bytes(corrupt)) is None and decode_cc_frame(bytes(lie_len)) is None
          and decode_cc_frame(b"") is None)

    # --- 4) 0x0306 载荷布局：表 1-43 逐字段 ---
    check("键值1 在低字节、键值2 在高字节",
          frame[7] == cc.HID_USAGE["W"] and frame[8] == cc.HID_USAGE["SHIFT"],
          f"{frame[7]:#02x} {frame[8]:#02x}")
    check("X=1000 落 bit0-11", (frame[9] | (frame[10] << 8)) & 0x0FFF == 1000)
    xy = frame[9] | (frame[10] << 8)
    check("左键占 bit12 而不是挤进坐标", (xy >> 12) == 1 and (xy & 0x0FFF) == 1000,
          bin(xy))
    check("Y=600 落 bit0-11、右键位为 0",
          (frame[11] | (frame[12] << 8)) & 0x0FFF == 600 and
          ((frame[11] | (frame[12] << 8)) >> 12) == 0)
    big = encode_keymouse_0306(x=4095, y=4095, left=True, right=True)
    check("边界：坐标 4095 + 双键按下仍不串位",
          struct_unpack_u16(big[2:4]) == 0x1FFF and struct_unpack_u16(big[4:6]) == 0x1FFF)
    for bad_xy in ((4096, 0), (0, 4096), (-1, 0)):
        try:
            encode_keymouse_0306(x=bad_xy[0], y=bad_xy[1])
            check(f"越界坐标 {bad_xy} 必须报错", False)
        except ValueError:
            check(f"越界坐标 {bad_xy} 被拒（不会静默截断成别的点）", True)

    # --- 5) 2 键无冲必须报出来，不能静默丢 ---
    k1, k2, dropped = keys_to_two_usages(["W", "A", "SHIFT"])
    check("三键组合报出被挤掉的键", dropped == ["SHIFT"], f"{k1:#x} {k2:#x} {dropped}")
    k1, k2, dropped = keys_to_two_usages(["W"])
    check("单键时第二键值为 0（0=无按键按下）", (k1, k2, dropped) == (cc.HID_USAGE["W"], 0, []))
    k1, k2, dropped = keys_to_two_usages([])
    check("空集合 = 松手", (k1, k2) == (0, 0))
    _, _, dropped = keys_to_two_usages(["W", "不存在的键"])
    check("不认识的键名进 dropped（不静默当没按）", dropped == ["不存在的键"], str(dropped))

    # --- 6) 鼠标是绝对坐标：VirtualCursor 攒增量 ---
    cur = VirtualCursor()
    start = (cur.x, cur.y)
    cur.move(120, -45)
    check("增量攒成绝对位置", (cur.x, cur.y) == (start[0] + 120, start[1] - 45),
          f"{start} -> {(cur.x, cur.y)}")
    for _ in range(200):
        cur.move(500, 500)
    check("绝对坐标被夹在屏幕内（1920x1080 内）",
          0 <= cur.x < cc.SCREEN_W and 0 <= cur.y < cc.SCREEN_H, f"{cur.x},{cur.y}")

    # --- 7) 发送器：mock 默认不碰硬件、限流、seq 回绕、松手 ---
    written = []
    link = CustomControllerLink(mock_output=False, write_bytes=written.append, max_hz=30.0)
    t = {"now": 1000.0}
    link.time_fn = lambda: t["now"]
    ok, why = link.send_keymouse(pressed=["W"], dx=5, dy=-3, left=True, now=t["now"])
    check("真发模式经 write_bytes 出去一帧", ok and len(written) == 1, f"{ok} {why}")
    check("写出的帧解回来是 0x0306", (decode_cc_frame(written[0]) or {}).get("cmd_id")
          == CC_CMD_KEYMOUSE, str(decode_cc_frame(written[0])))
    ok2, why2 = link.send_keymouse(pressed=["W"], now=t["now"])
    check("同一时刻再发必须被限流丢掉（选手端会丢超频包）",
          not ok2 and "上限" in why2 and link.dropped_rate == 1, f"{ok2} {why2}")
    t["now"] += 1.0 / 30.0 + 0.001
    ok3, _ = link.send_keymouse(pressed=["W"], now=t["now"])
    check("过窗口后可以继续发", ok3 and len(written) == 2, str(len(written)))
    link.seq = 0xFE
    t["now"] += 0.1
    link.send_keymouse(pressed=["W"], now=t["now"])
    check("seq 回绕不越界", 0 <= link.seq <= 0xFF, str(link.seq))
    before = len(written)
    link.send_keymouse(pressed=[], now=t["now"] + 1.0)
    last = decode_cc_frame(written[-1]) or {}
    check("松手帧键值为 0", len(last.get("data", b"\x00" * 8)) == 8
          and last["data"][0] == 0 and last["data"][1] == 0, str(last))
    check("release_all 归零并回中心", link.release_all(now=t["now"] + 2.0)[0]
          and (decode_cc_frame(written[-1]) or {}).get("data", b"")[0] == 0)
    mock = CustomControllerLink(mock_output=True)
    mock_ok, mock_why = mock.send_keymouse(pressed=["S"])
    check("mock 模式仍产帧但不写硬件", mock_ok and mock_why == "mock"
          and mock.last_frame and len(mock.last_frame) == 17, mock_why)
    over = CustomControllerLink(mock_output=True)
    ok4, why4 = over.send_robot_interact(b"\x00" * 31)
    check("0x0302 超 30 字节直接拒", not ok4 and "30" in why4, why4)
    ok5, _ = over.send_robot_interact(b"\x00" * 30, now=over.time_fn() + 5.0)
    check("0x0302 正常帧是 30 字节载荷", ok5 and len(decode_cc_frame(over.last_frame)["data"]) == 30)
    check("超大载荷被 encoder 拦住", raises_value(lambda: encode_cc_frame(0x0306, b"\x00" * 200, 0)))
    test_bridge_side()
    test_manager_gates()
    return finish()


def struct_unpack_u16(b: bytes) -> int:
    return b[0] | (b[1] << 8)


def raises_value(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def finish() -> int:
    print("\n" + ("有失败项" if FAILED else "自定义控制器出口（0x0306/帧格式）全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
