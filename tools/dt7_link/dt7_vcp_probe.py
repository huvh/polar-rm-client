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

    # 只读旁听：先看 DT7 自己吐不吐东西（这一步不发包，对车零影响）
    python tools/dt7_link/dt7_vcp_probe.py --port COM5 --listen 8
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
    "vendor5a": "**首选**：大疆选手端实际写进 DT7 口的那 22 字节"
                "（5A|len|ver|crc8|seq|cmd|12B 载荷|crc16）。"
                "从 12.x 选手端反汇编现场复原，详见 rm_client/backend/dt7_link.py 顶部。",
    "dbus18": "整帧 18 字节，与 DR16 出口完全同构。DT7 若只做透传，最可能是这个。",
    "km12": "只给键鼠那 12 字节（DBUS bytes6-17）。DT7 若把摇杆留给摇杆、只收键鼠，是这个。",
    "km6": "鼠标三轴 + 键位共 8 字节，不含左右键。精简实现常见。",
    "keys2": "最裸的 2 字节键位图。若这条链路只支持键盘不支持鼠标，就是这个。",
}


def _crc8_77(data: bytes, init: int = 0x77) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc & 0xFF


def _crc16_1862(data: bytes, init: int = 0x1862) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def vendor_frame(keys: int, mouse, left: int = 0, right: int = 0,
                 cmd: int = 0x2000, seq: int = 0) -> bytes:
    """厂商那 22 字节：5A | len(=4+12) | ver(1) | crc8(0x77) | seq u16 | cmd u16 | 12B | crc16(0x1862)。

    与运行期实现 ``rm_client/backend/dt7_link.build_frame`` 同构；测试
    （tools/dt7_link/test_dt7_link.py）会把两边钉在一起，防跑偏。
    """
    body = struct.pack("<HH", seq & 0xFFFF, cmd & 0xFFFF) + struct.pack(
        "<hhhBBHH", int(mouse[0]), int(mouse[1]), int(mouse[2]),
        1 if left else 0, 1 if right else 0, keys & 0xFFFF, 0)
    head = bytes([0x5A, len(body) & 0xFF, 1])
    frame = head + bytes([_crc8_77(head)]) + body
    return frame + struct.pack("<H", _crc16_1862(frame))


def build_candidate(name: str, keys: int, mouse) -> bytes:
    """按候选帧型打包。帧型来自官方手册第 6-7 页的 DBUS 位序（已用固件真解码器验过）。"""
    if name == "vendor5a":
        return vendor_frame(keys, mouse)
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


# ---------------------------------------------------------------------------
# 只读旁听：不猜帧型，先让 DT7 自己把话说出来
# ---------------------------------------------------------------------------
#
# 为什么值得先做这一步：大疆那一代 RC 助手软件（Phantom 2 的 "RC System"，
# 解包见 README 第 4.3 节）里有 "Channel Monitor"/"ch_monitor" 这种**读通道**
# 功能，用的就是同一类 DJI USB Virtual COM。也就是说"DJI 的遥控器愿意把
# 自己的通道数据从 USB 串口吐给电脑看"是这一系硬件的既有能力。
# 只要 DT7 肯吐：
#   * 吐的是 18 字节 DBUS 同构帧 -> 这个口就是串口桥，PC 反向写同一个格式
#     成功的概率立刻大得多；
#   * 顺带就把 README 第 3 节那个"键位 bit4-7 两套官方定义打架"的死结
#     **当场判掉**：驾驶员按一下 Q，看它落在 bit4 还是 bit6 就完事，
#     不用猜、不用示波器、不用冒险往车上发包。

GAP_S_DEFAULT = 0.004      # 4ms 静默算一帧结束（帧周期 14ms，帧内字节间隔 <0.2ms）


def read_frames(source, seconds: float = 8.0, gap_s: float = GAP_S_DEFAULT,
                clock=time.perf_counter) -> list[bytes]:
    """按"空闲线"切帧：连续 gap_s 没有新字节就认为上一帧结束。

    不靠波特率、不靠帧头、不猜长度——DT7 只要在同一格式上吐，长度分布
    自己会浮出来。source 只要有 read(1) 即可（真 pyserial 对象或假对象都行）。
    """
    frames: list[bytes] = []
    cur = bytearray()
    last = None
    t0 = clock()
    while (clock() - t0) < seconds:
        byte = source.read(1)
        now = clock()
        if not byte:
            if cur and last is not None and (now - last) > gap_s:
                frames.append(bytes(cur))
                cur = bytearray()
                last = None
            continue
        if cur and last is not None and (now - last) > gap_s:
            frames.append(bytes(cur))
            cur = bytearray()
        cur += byte
        last = now
    if cur:
        frames.append(bytes(cur))
    return frames


def analyze_frames(frames: list[bytes]) -> dict:
    """把一堆字节块变成能读懂的结论（帧长分布 / 18B 帧的通道与键位跳变）。"""
    lengths: dict[int, int] = {}
    for f in frames:
        lengths[len(f)] = lengths.get(len(f), 0) + 1
    out = {
        "n_frames": len(frames),
        "n_bytes": sum(len(f) for f in frames),
        "lengths": lengths,
        "dbus": [],
        "key_events": [],
        "ch_ranges": [],
        "ch_moved": False,
        "mouse_moved": False,
        "raw_head": [bytes(f) for f in frames[:3]],
    }
    dbus = [f for f in frames if len(f) == df.FRAME_LEN]
    out["dbus"] = dbus
    if not dbus:
        return out
    per_ch = [set() for _ in range(4)]
    mouse_seen = set()
    prev_keys = None
    for f in dbus:
        d = df.decode_frame(f)
        for i, value in enumerate(d["ch"]):
            per_ch[i].add(value)
        mouse_seen.add((d["mouse"]["x"], d["mouse"]["y"], d["mouse"]["z"]))
        keys = d["key_v"]
        if prev_keys is not None and keys != prev_keys:
            diff = keys ^ prev_keys
            for bit in range(16):
                if diff & (1 << bit):
                    out["key_events"].append({
                        "bit": bit,
                        "pressed": bool(keys & (1 << bit)),
                        "fw": df.KEY_ORDER_FW[bit],
                        "dji2016": df.KEY_ORDER_DJI2016[bit],
                    })
        prev_keys = keys
    out["ch_ranges"] = [(min(s), max(s)) for s in per_ch]
    out["ch_moved"] = any(hi > lo for lo, hi in out["ch_ranges"])
    out["mouse_moved"] = len(mouse_seen) > 1
    return out


def print_analysis(a: dict) -> None:
    print(f"共读到 {a['n_frames']} 块 / {a['n_bytes']} 字节；长度分布 {a['lengths'] or '（空）'}")
    if not a["n_frames"]:
        print("一个字节都没读到。两种可能：① 这个口 DT7 根本不主动吐数据"
              "（那只能回到发包排除法）；② 口开错了/线是充电线。")
        return
    if not a["dbus"]:
        print(f"没有 {df.FRAME_LEN} 字节的块 -> 这个口上跑的不是 DBUS 同构帧。")
        print("前几块原样（够判断有没有固定帧头/帧尾/长度规律）：")
        for i, f in enumerate(a["raw_head"]):
            print(f"  #{i + 1} ({len(f)}B) {f.hex(' ')}")
        return
    print(f"其中 {len(a['dbus'])} 块正好 {df.FRAME_LEN} 字节，按 DBUS 解出来：")
    print(f"  首帧  {df.describe(a['dbus'][0])}")
    print(f"  末帧  {df.describe(a['dbus'][-1])}")
    print(f"  通道范围 {a['ch_ranges']}（中值 {df.CH_MID}）-> "
          f"{'摇杆一动通道就动，这口在透传 DBUS' if a['ch_moved'] else '通道全程不动'}")
    if a["mouse_moved"]:
        print("  鼠标三轴有变化（这帧里的键鼠字段确实有人在写）")
    if a["key_events"]:
        print("\n按键跳变（这才是本轮最想要的东西）：")
        for e in a["key_events"]:
            print(f"  bit{e['bit']:<2} {'按下' if e['pressed'] else '松开'}"
                  f"   固件/RM2026 位序 = {e['fw']:<6} 2016 遥控器手册位序 = {e['dji2016']}")
        bits = sorted({e["bit"] for e in a["key_events"]})
        print(f"\n判读：你按的那些键落在 bit {bits}。")
        print("  · 若按的是 Q 而报的是 bit6 -> DT7 用**固件/RM2026 位序**，"
              "客户端现有编码直接可用。")
        print("  · 若按的是 Q 而报的是 bit4 -> DT7 用**2016 手册位序**，"
              "发包时必须 --key-order dji2016（见 dt7_dbus_frame.keys_to_bits）。")
    else:
        print("\n没看到键位跳变：旁听期间要有人真的按 DT7 上的键（Q/E/Shift/Ctrl 各按一次）。")


def do_listen(port: str, seconds: float, baud: int, parity: str, gap_s: float) -> int:
    try:
        import serial
    except ImportError:
        print("[FAIL] 没装 pyserial", file=sys.stderr)
        return 2
    kwargs = dict(baudrate=baud, bytesize=8,
                  parity=(serial.PARITY_EVEN if parity == "even" else serial.PARITY_NONE),
                  stopbits=1, timeout=0.05)
    print(f"旁听 {port}  {baud} 8{parity[0].upper()}1  {seconds:g}s —— 这一步**只读不写**，"
          "对车没有任何影响。\n现在请：摇左右摇杆各一次，再把 Q、E、Shift、Ctrl 各按一次。")
    with serial.Serial(port, **kwargs) as sp:
        frames = read_frames(sp, seconds=seconds, gap_s=gap_s)
    print_analysis(analyze_frames(frames))
    return 0



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="列出 COM 口并标出 DJI VCP")
    ap.add_argument("--candidates", action="store_true", help="打印四种候选帧（不发送）")
    ap.add_argument("--candidate", choices=sorted(CANDIDATE_DOC), default="vendor5a")
    ap.add_argument("--keys", default="W", help="按键名，逗号分隔；NONE=松键")
    # 用逗号串而不是 nargs=3：argparse 会把 `-5` 当成选项名，
    # 而鼠标位移**经常是负的**，nargs=3 等于把最有用的用例堵死了。
    ap.add_argument("--mouse", default="0,0,0", metavar="DX,DY,DZ",
                    help="鼠标三轴位移，逗号分隔，可为负")
    ap.add_argument("--port")
    ap.add_argument("--listen", type=float, metavar="SEC", default=None,
                    help="只读旁听若干秒，看 DT7 自己吐什么（不发包，对车无影响）")
    ap.add_argument("--gap-ms", type=float, default=GAP_S_DEFAULT * 1000.0,
                    help="空闲线分帧的静默阈值，毫秒")
    ap.add_argument("--parity", choices=("even", "none"), default="even",
                    help="官方 DBUS 是偶校验(8E1)；CDC 桥一般不吃这个，但旁听/回写时"
                         "若真接的是 UART 桥就必须对，所以默认按手册给 even")
    ap.add_argument("--baud", type=int, default=961200,
                    help="选手端对 RC 口设的就是 961200（decomp/SerialPortThread.cs:92-95）。"
                         "CDC 通常不吃波特率，但 usbser.sys 要求先设一个；"
                         "若这口其实是 UART 桥，官方 DBUS 值是 100000")
    ap.add_argument("--frames", type=int, default=1, help="发几帧（14ms 节奏）")
    ap.add_argument("--send-hex", help="直接发这串十六进制（回放抓包样本）")
    ap.add_argument("--confirm-move-car", action="store_true",
                    help="已架空驱动轮且驾驶员能随时抢回控制；不给就只打印不发")
    args = ap.parse_args(argv)

    if args.list or not (args.port or args.candidates):
        return do_list()

    if args.listen is not None:
        if not args.port:
            print("[FAIL] --listen 也要给 --port（先 --list 找口）", file=sys.stderr)
            return 2
        return do_listen(args.port, max(0.2, args.listen), args.baud,
                         args.parity, max(0.0005, args.gap_ms / 1000.0))

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
    import serial as _serial  # noqa: F401
    with serial.Serial(args.port, args.baud, timeout=1, bytesize=8,
                       parity=(serial.PARITY_EVEN if args.parity == "even"
                               else serial.PARITY_NONE), stopbits=1) as sp:
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
