#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""往**官方选手端**的"自定义控制器"串口发 0x0306 键鼠包，现场一条命令试一个键。

为什么需要这个命令行版（客户端里已经有出口了还要它）
----------------------------------------------------
第 14.3 节列的三个未知数里，最难缠的是**"通用键值"到底是哪张表**：
文档只写"使用通用键值"，没附表，而选手端还有一句"仅响应选手端开放的按键"。
这意味着现场要一个键一个键地试。在 GUI 里改设置 + 授权 + 观察，
每一步都比命令行慢；而这条路失败的表现恰好是最难查的那种
（"我发了，车没反应，也不知道谁吞的"）。

用法
----
    # 1) 先看帧长什么样（**不碰串口**，默认就是 dry-run）
    python tools/dt7_link/cc_probe.py --keys W --mouse 1000,600

    # 2) 逐键验表：一次只按一个键，看选手端日志有没有"收到0306数据包"、车动不动
    python tools/dt7_link/cc_probe.py --port COM7 --keys W --confirm-move-car

    # 3) 松手（全零键值），这条永远安全
    python tools/dt7_link/cc_probe.py --port COM7 --release

    # 4) 一次把所有候选键各发 6 包，打印每包字节，供人对着选手端表现记表
    python tools/dt7_link/cc_probe.py --sweep W,A,S,D,Q,E,SHIFT,CTRL

安全
----
* 不给 `--confirm-move-car` 就只打印字节，一个字节都不写串口；
* 2 键无冲是文档限制：超过两个键会**报出来**并只发前两个，不静默丢；
* 频率默认 30Hz（选手端对超频包直接丢弃，日志原话"0306收包超频，丢弃多余包！"）；
* 发完自动补一帧全零键值，别把键粘在选手端上（它"保持上一帧按下状态"）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.backend import cc_link as cc          # noqa: E402

SWEEP_DEFAULT = ("W", "A", "S", "D", "Q", "E", "SHIFT", "CTRL", "SPACE", "F")


def show(payload: bytes, keys, xy, buttons) -> None:
    frame = cc.encode_cc_frame(cc.CC_CMD_KEYMOUSE, payload, seq=0)
    print(f"  键值 {keys}  绝对坐标 {xy}  按键 {buttons}")
    print(f"  帧 ({len(frame)}B) {frame.hex(' ')}")
    print(f"  载荷字段  key1/key2={payload[0]:#04x}/{payload[1]:#04x} "
          f"x={payload[2] | ((payload[3] & 0x0F) << 8)} "
          f"y={payload[4] | ((payload[5] & 0x0F) << 8)} "
          f"LB={(payload[3] >> 4) & 1} RB={(payload[5] >> 4) & 1}")


def build_payload(keys, x, y, left, right) -> tuple[bytes, list[str]]:
    k1, k2, dropped = cc.keys_to_two_usages(keys)
    return cc.encode_keymouse_0306(key1=k1, key2=k2, x=x, y=y,
                                   left=left, right=right), dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="选手端那个自定义控制器串口，例如 COM7")
    ap.add_argument("--keys", default="NONE", help="按键名，逗号分隔（W,A,S,D,Q,E,SHIFT,CTRL…）")
    ap.add_argument("--mouse", default="", metavar="X,Y",
                    help="绝对像素坐标（默认沿用 960,540 中心）")
    ap.add_argument("--buttons", default="", help="左右键：l / r / lr")
    ap.add_argument("--hz", type=float, default=cc.DEFAULT_MAX_HZ)
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--release", action="store_true", help="只发一帧全零键值（永远安全）")
    ap.add_argument("--sweep", nargs="?", const=",".join(SWEEP_DEFAULT),
                    help="逐键各发几帧，用来现场把键值表对出来")
    ap.add_argument("--confirm-move-car", action="store_true",
                    help="真的往串口写。不给就只打印字节")
    args = ap.parse_args(argv)

    xy = (960, 540)
    if args.mouse:
        parts = [x.strip() for x in args.mouse.split(",") if x.strip() != ""]
        if len(parts) != 2:
            raise SystemExit("--mouse 要两个数 X,Y（绝对像素，0..1919 / 0..1079）")
        xy = (max(0, min(cc.SCREEN_W - 1, int(float(parts[0])))),
              max(0, min(cc.SCREEN_H - 1, int(float(parts[1])))))
    btn = set((args.buttons or "").lower())
    left, right = ("l" in btn), ("r" in btn)
    interval = 1.0 / max(1.0, float(args.hz))

    def emit(keys, *, label="") -> int:
        payload, dropped = build_payload(keys, *xy, left, right)
        print(f"[{label or ('+'.join(keys) or 'RELEASE')}]")
        show(payload, keys, xy, (left, right))
        if dropped:
            print(f"  [提醒] 2 键无冲，这些键没发出去：{dropped}")
        # 只为了把"将会发出去的那一帧"原样打出来；这里**不碰串口**
        frame = cc.encode_cc_frame(cc.CC_CMD_KEYMOUSE, payload, seq=1)
        assert cc.decode_cc_frame(frame) is not None, "dry-run 打印的帧自己都不过校验"
        return len(frame)

    if args.sweep is not None:
        names = [n for n in (args.sweep or "").replace(" ", ",").split(",") if n]
        print(f"逐键扫描（每键 {args.frames} 帧）；选手端日志里应当看到"
              f"\"收到0306数据包\"，同时观察车/界面的反应：")
        for n in names:
            emit([n], label=n)
        emit([], label="RELEASE")
        print("\n以上是 dry-run。要真发：加 --port COMx --confirm-move-car")
        return 0

    keys = [] if args.release or args.keys.upper() == "NONE" else \
        [k.strip().upper() for k in args.keys.split(",") if k.strip()]
    emit(keys if not args.release else [], label="RELEASE" if args.release else "")

    if not args.confirm_move_car:
        print("\n只打印、未发送。这条路一旦表对上了**车就会动**，"
              "先架空驱动轮、手放摇杆上，再加 --confirm-move-car。")
        return 0
    if not args.port:
        print("[FAIL] 要真发必须给 --port", file=sys.stderr)
        return 2
    link = cc.CustomControllerLink(port=args.port, mock_output=False)
    print(f"往 {args.port} 以 {args.hz:g}Hz 发 {args.frames} 帧…")
    ok = 0
    for _ in range(max(1, args.frames)):
        got, why = link.send_keymouse(pressed=keys, left=left, right=right)
        if got:
            ok += 1
        else:
            print("  发送失败:", why)
        time.sleep(interval)
    rel_ok, rel_why = link.release_all()
    print(f"已发 {ok}/{args.frames} 帧，松手帧 {'已发' if rel_ok else '失败：' + rel_why}")
    if ok or rel_ok:
        print("选手端日志该出现「收到0306数据包」。没有 -> 是挑口问题；有但车不动 -> 是键值表问题。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
