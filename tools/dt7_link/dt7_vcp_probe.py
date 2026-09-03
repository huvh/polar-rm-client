#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""DT7 虚拟串口（大疆官方"虚拟控制链路"）的枚举与报文试探工具。

为什么是"串口"而不是 HID —— 证据在大疆自己的驱动 INF 里
------------------------------------------------------
官方 DT7/DR16 配套驱动包 RM_remote_driver.7z 里的 dji_vcom_driver11.inf
（用 innoextract 只**解包**读文本，没有运行那个安装器）：

    [Version]
    Class=Ports
    ClassGuid={4D36E978-E325-11CE-BFC1-08002BE10318}
    Provider=%DJI%
    [DeviceList]
    %DJIVCOM% = XP40, USB\VID_FFF0&PID_0008&MI_00
    %DJIVCOM% = XP40, USB\VID_FFF0&PID_0008
    [DriverService]
    ServiceBinary=%12%\usbser.sys
    [Strings]
    DJIVCOM = "DJI USB Virtual COM"

三件事一次定死：
 1. DT7 的 USB 口在电脑上是**虚拟串口**（Class=Ports），不是 HID 手柄；
 2. 硬件 ID 是 VID_FFF0 / PID_0008（复合设备的 MI_00 那一面），
    **不是** DJI 消费机的 VID_2CA3 —— 所以只搜 2ca3 的取证必然假阴性；
 3. 驱动服务就是微软自带的 usbser.sys（标准 USB CDC-ACM），**不需要厂商 DLL**
    -> 客户端用 pyserial 就能直接读写这个口。

于是"电脑连 DT7 控车"这条路缺的东西从"逆向外设协议"缩小成一件事：
**这个串口上的帧格式**。大疆没公开它，所以本脚本把它变成黑盒排除法：
四种候选帧型 + 一条命令换一种，车动不动当场就有答案。

用法
----
    python tools/dt7_link/dt7_vcp_probe.py --list
    python tools/dt7_link/dt7_vcp_probe.py --candidates --keys W,SHIFT --mouse 12 -5
    python tools/dt7_link/dt7_vcp_probe.py --port COM5 --candidate dbus18 \
           --keys W --confirm-move-car
    python tools/dt7_link/dt7_vcp_probe.py --port COM5 --send-hex "5A 01 ..." \
           --confirm-move-car
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dt7_dbus_frame as df  # noqa: E402

# 官方 INF 里写死的硬件 ID。VID_FFF0&PID_0008 是 DT7 那一面；
# 2ca3 也一起扫，免得把别的 DJI 设备误判成"没插上"。
DJI_USB_IDS = (
    ("fff0", "0008", "DJI USB Virtual COM（DT7 官方 VCP）"),
    ("2ca3", None, "DJI 消费机 VID（顺带扫）"),
)

CANDIDATE_DOC = {
    "dbus18": "整帧 18 字节，与 DR16 出口完全同构。DT7 若只做透传，最可能是这个。",
    "km12": "只给键鼠那 12 字节（DBUS bytes6-17）。DT7 若把摇杆留给摇杆、只收键鼠，是这个。",
    "km6": "鼠标三轴 + 键位共 8 字节，不含左右键。精简实现常见。",
    "keys2": "最裸的 2 字节键位图。若这条链路只支持键盘不支持鼠标，就是这个。",
}


def build_candidate(name: str, keys: int, mouse) -> bytes:
    """按候选帧型打包。帧型来自官方手册第 6-7 页的 DBUS 位序（已用固件真解码器验过）。"""
    full = df.encode_frame(mouse=mouse, keys=keys)
    if name == "dbus18":
        return full
    if name == "km12":
        return full[6:18]
    if name == "km6":
        return full[6:12] + struct.pack("<H", keys)
    if name == "keys2":
        return struct.pack("<H", keys)
    raise KeyError(name)


def parse_mouse(text: str) -> tuple[int, int, int]:
    parts = [x.strip() for x in str(text).split(",") if x.strip() != ""]
    if len(parts) != 3:
        raise SystemExit("--mouse 要三个数（DX,DY,DZ），例如 12,-5,0")
    return tuple(int(float(x)) for x in parts)   # type: ignore[return-value]


def find_ports() -> list[dict]:
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        print("[FAIL] 没装 pyserial：pip install pyserial", file=sys.stderr)
        return []
    rows = []
    for p in lp.comports():
        hw = (p.hwid or "")
        inst = getattr(p, "device_instance_path", "") or ""
        blob = f"{hw} {inst} {p.description}".lower()
        tag = ""
        for vid, pid, why in DJI_USB_IDS:
            if vid in blob and (pid is None or pid in blob):
                tag = why
                break
        rows.append({"port": p.device, "desc": p.description, "hwid": hw, "dji": tag})
    return rows


def do_list() -> int:
    rows = find_ports()
    if not rows:
        print("一个 COM 口都没有。DT7 开机插线后应出现 "
              "'DJI USB Virtual COM'（USB\\VID_FFF0&PID_0008）。")
        print("没有就按顺序查：① 那根线是不是只能充电没有数据芯（最常见）"
              "② 官方驱动装没装 ③ 换一台电脑，别在这台机器上猜。")
        return 1
    print(f"{'端口':8} {'DJI?':6} 说明")
    for r in rows:
        print(f"{r['port']:8} {'是' if r['dji'] else '-':6} {r['desc'][:58]}"
              + (f"   <- {r['dji']}" if r["dji"] else ""))
    if not any(r["dji"] for r in rows):
        print("\n没有任何口带 VID_FFF0&PID_0008。官方 INF 的硬件 ID 是死值，"
              "插上就一定匹配得上 -> 现在的问题是**没枚举到**，不是协议不对。")
    return 0


def do_candidates(keys_names: list[str], mouse) -> int:
    names = [n for n in keys_names if n and n != "NONE"]
    keys = df.keys_to_bits(names) if names else 0
    print(f"键位 {'+'.join(names) if names else 'NONE'} -> 0x{keys:04X}"
          f"（固件位序：bit0=W bit1=S bit2=A bit3=D bit4=SHIFT；"
          f"注意 2016 遥控器手册是另一套位序，见 README 第 3 节）\n")
    for name in CANDIDATE_DOC:
        body = build_candidate(name, keys, mouse)
        print(f"[{name:7}] {len(body):2}B  {body.hex(' ')}\n          {CANDIDATE_DOC[name]}")
    print("\n以上四种都是**假设**，大疆没公开过这个口的帧格式；用来做排除法。")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="列出 COM 口并标出 DJI VCP")
    ap.add_argument("--candidates", action="store_true", help="打印四种候选帧（不发送）")
    ap.add_argument("--candidate", choices=sorted(CANDIDATE_DOC), default="dbus18")
    ap.add_argument("--keys", default="W", help="按键名，逗号分隔；NONE=松键")
    # 用逗号串而不是 nargs=3：argparse 会把 `-5` 当成选项名，
    # 而鼠标位移**经常是负的**，nargs=3 等于把最有用的用例堵死了。
    ap.add_argument("--mouse", default="0,0,0", metavar="DX,DY,DZ",
                    help="鼠标三轴位移，逗号分隔，可为负")
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=115200,
                    help="CDC 通常不吃波特率，但 usbser.sys 要求先设一个")
    ap.add_argument("--frames", type=int, default=1, help="发几帧（14ms 节奏）")
    ap.add_argument("--send-hex", help="直接发这串十六进制（回放抓包样本）")
    ap.add_argument("--confirm-move-car", action="store_true",
                    help="已架空驱动轮且驾驶员能随时抢回控制；不给就只打印不发")
    args = ap.parse_args(argv)

    if args.list or not (args.port or args.candidates):
        return do_list()

    names = [n.strip().upper() for n in args.keys.split(",") if n.strip()]
    keys = df.keys_to_bits(names) if names and names != ["NONE"] else 0

    mouse = parse_mouse(args.mouse)
    if args.candidates:
        return do_candidates(names, mouse)

    payload = (bytes.fromhex(args.send_hex.replace(" ", "")) if args.send_hex
               else build_candidate(args.candidate, keys, mouse))
    if not args.port:
        print("[FAIL] 要发包得给 --port（先 --list）", file=sys.stderr)
        return 2
    if not args.confirm_move_car:
        print("只打印、不发送。这工具直接驱动遥控器：一旦帧型猜对，**车就会动**。\n"
              "先架空驱动轮、驾驶员手放摇杆上，再加 --confirm-move-car。\n"
              f"将发送：{payload.hex(' ')}  （{args.candidate}）")
        return 0
    try:
        import serial
    except ImportError:
        print("[FAIL] 没装 pyserial", file=sys.stderr)
        return 2
    with serial.Serial(args.port, args.baud, timeout=1) as sp:
        for i in range(max(1, args.frames)):
            sp.write(payload)
            sp.flush()
            print(f"  #{i + 1} -> {args.port}  {payload.hex(' ')}")
            time.sleep(0.014)
        sp.write(bytes(len(payload)))   # 收尾发等长全零：别把键粘在车上
        sp.flush()
        time.sleep(0.05)
    print("已发完并补了一帧全零释放。车动 -> 帧型对了；不动 -> 换下一个 --candidate。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
