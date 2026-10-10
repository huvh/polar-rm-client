# -*- coding: utf-8 -*-
"""DT7 侦察探针：搞清楚"大疆客户端插 USB 线连 DT7"这一步走的到底是哪条通道。

为什么需要它
------------
队内确认过：**比赛时是大疆官方客户端 USB 连 DT7，然后控车**。这就证明了两件事：

1. 固件侧那条链路本来就是通的 —— 电脑键鼠 -> DT7 填进 18 字节 SBUS 的
   键盘位图(bytes14-15)与鼠标位移(bytes6-13) -> `remote_control.c:252` 无条件进
   `sbus_to_rc()` -> `chassis_mecanum.c:157-160` / `gimbal_yaw_pitch_direct.c:331-332`
   消费。这一段一行代码都不用改。
2. 缺的只有 **"PC <-> DT7" 那一段的协议**（DJI 私有的 键盘映射/HID/CDC 细节）。

本脚本的作用就是**只用现场能拿到的信息**把那段协议的性质定下来：
它是 HID 设备？虚拟串口？两者都有？谁在读写它？

跑法（不需要管理员）：
    python tools/dt7_hid_probe.py            # 只看现状
    python tools/dt7_hid_probe.py --watch 12 # 边看边操作：12 秒内插拔/开关大疆客户端/按键
    python tools/dt7_hid_probe.py --capture  # 装了 hidapi(pip install hidapi) 后逐个设备抓上报

输出都是文本，直接贴回来就能判。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

# 2026-09-04 修正：官方 dji_vcom_driver11.inf 里写的是
#   Class=Ports + USB\VID_FFF0&PID_0008 + ServiceBinary=usbser.sys
# 也就是说 **DT7 的 USB 口是虚拟串口，硬件 ID 是 FFF0:0008，不是 2CA3**。
# 原先这里只有 2ca3，等于拿错门牌号找人 —— 插了 DT7 也会报"没看到 DJI 设备"。
DJI_VIDS = {"fff0", "2ca3"}          # fff0 = DT7 VCP（官方 INF）；2ca3 = DJI 消费机
KW_INTEREST = ("dji", "dt7", "dr16", "keyboard", "mouse", "键盘", "鼠标",
               "joystick", "game", "controller", "rc", "transmitter", "receiver")


def ps(script: str) -> str:
    """跑一段 PowerShell，返回文本（用 -OutputFormat 让中文不乱）。"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$OutputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def hid_devices() -> list[dict]:
    """HID / USB 输入类设备（WMI，不需要管理员）。"""
    out = ps(
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.DeviceID -match 'HID\\\\|USB\\\\VID' } | "
        # 踩过的两个坑：
        #  1) 反引号 t 只在 PowerShell **双引号**串里才是制表符，单引号里是字面量；
        #  2) [string]::Format 的 {0} 在 Python 字符串里要写 {{0}}，多一层转义容易翻车。
        # 直接字符串拼接最省事。
"ForEach-Object { $_.Name + \'|#|\' + $_.DeviceID + \'|#|\' + "
            "($_.Manufacturer -replace \'[|#]\', \' \') }",
    )
    rows = []
    for line in out.splitlines():
        parts = line.split("|#|")
        if len(parts) < 2 or not parts[0].strip():
            continue
        dev_id = parts[1].strip().upper()
        vid = ""
        if "VID_" in dev_id:
            vid = dev_id.split("VID_")[1][:4]
        rows.append({"name": parts[0].strip(), "id": dev_id, "vid": vid.lower(),
                     "maker": parts[2].strip() if len(parts) > 2 else ""})
    return rows


def com_ports() -> list[str]:
    """虚拟串口（DT7 也可能是 CDC 串口，那就完全另一套打法）。"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return ["（没装 pyserial，跳过）"]
    out = []
    for p in list_ports.comports():
        out.append(f"{p.device}  VID:PID={p.vid:04x}:{p.pid:04x}  "
                   f"manufacturer={p.manufacturer or '-'}  product={p.product or '-'}"
                   if p.vid else f"{p.device}  {p.description}")
    return out


def report(rows: list[dict], ports: list[str]) -> None:
    print("\n--- 虚拟串口（COM）---")
    for line in ports or ["（无）"]:
        print("  ", line)
    print("\n--- HID / USB 输入设备 ---")
    interesting = [r for r in rows
                   if r["vid"] in DJI_VIDS or any(k in r["name"].lower() for k in KW_INTEREST)]
    other = [r for r in rows if r not in interesting]
    for tag, lst in (("★ 疑似 DJI / 键鼠 / 手柄", interesting), ("其它输入设备", other)):
        print(f"  [{tag}] {len(lst)} 个")
        for r in lst[:20]:
            print(f"     vid={r['vid'] or '?':4} {r['name'][:44]:44} {r['id'][:66]}")
        if not lst:
            print("     （无）")
    if not interesting:
        print("\n  注意：**没看到 DJI(VID 2ca3) 或任何键鼠/手柄类新设备**。")
        print("  要么 DT7 现在没插在这台电脑上，要么它不认成 HID（那就是 CDC 串口，见上表）。")


def capture(seconds: float) -> None:
    """装了 hidapi 之后：逐个 HID 设备读 input report，看官方客户端在发什么。"""
    try:
        import hid  # type: ignore
    except ImportError:
        print("\n[跳过抓包] 没装 hidapi。装上再跑就能真正看到报文：")
        print("    pip install hidapi")
        return
    print(f"\n--- 抓 {seconds:.0f}s 各 HID 设备的上报（期间去点大疆客户端/按遥控器键）---")
    devs = hid.device()
    found = hid.enumerate()
    if not found:
        print("  hidapi 没枚举到任何设备")
        return
    handles = []
    for info in found:
        try:
            h = hid.device()
            h.open_path(info["path"])
            h.set_nonblocking(1)
            handles.append((info, h))
            print(f"  打开 {info.get('manufacturer_string') or '?'} / "
                  f"{info.get('product_string') or '?'} "
                  f"VID:PID={info['vendor_id']:04x}:{info['product_id']:04x}")
        except OSError as exc:
            print(f"  打不开 {info.get('product_string') or info['path']}: {exc}")
    t0 = time.time()
    seen = 0
    while time.time() - t0 < seconds:
        for info, h in handles:
            data = h.read(64)
            if data:
                seen += 1
                print(f"  [{info['vendor_id']:04x}:{info['product_id']:04x}] "
                      + " ".join(f"{b:02X}" for b in data[:32]))
        time.sleep(0.01)
    for _, h in handles:
        h.close()
    print(f"  共读到 {seen} 条上报（0 条 = 这些设备不是通道，或需要独占句柄）")


def main() -> int:
    ap = argparse.ArgumentParser(description="DT7 通道侦察")
    ap.add_argument("--watch", type=float, default=0.0,
                    help="持续 N 秒轮询设备变化（插拔、开大疆客户端时看谁出现/消失）")
    ap.add_argument("--capture", action="store_true", help="用 hidapi 抓 HID 上报（需 pip install hidapi）")
    ap.add_argument("--capture-seconds", type=float, default=15.0)
    args = ap.parse_args()

    base = {(r["id"],) for r in hid_devices()}
    report(hid_devices(), com_ports())

    if args.capture:
        capture(args.capture_seconds)

    if args.watch > 0:
        print(f"\n--- 观察 {args.watch:.0f}s：现在去插/拔 DT7、打开大疆客户端、按几下遥控器键 ---")
        t0 = time.time()
        while time.time() - t0 < args.watch:
            time.sleep(1.5)
            now = {(r["id"],) for r in hid_devices()}
            for added in sorted(x[0] for x in (now - base)):
                print(f"  + 新增 {added}")
            for gone in sorted(x[0] for x in (base - now)):
                print(f"  - 消失 {gone}")
            if now != base:
                print("  （变化已记录，等它稳定后把上面的输出贴回来）")
                base = now
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
