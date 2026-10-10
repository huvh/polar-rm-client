#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把"云台直控请求"桥装进 StandardRobot++ 固件树（gimbal_host）。

依赖：host_bridge 必须先装（本桥复用它的 0x04 帧与新鲜度门控）。

为什么需要它（GAPS 第 3 节，选项 2）
------------------------------------
固件里 GIMBAL_AUTO_AIM（云台听 0x01 的角度）唯一入口是 s[0] 上档，
而麦轮（英雄）上档 = 底盘无条件 CHASSIS_SPIN：想让上位机瞄准就得
一直小陀螺，两个需求在英雄板上是死冲突。

本桥用 0x04 里**本来就被忽略的 param0 bit0** 表达"上位机请求云台直控"
（电平语义，与 spin_cmd 共用 150ms 新鲜度门控）：

    中间档 + 请求 -> GIMBAL_AUTO_AIM（底盘模式仍由 spin_cmd/拨杆决定）
    中间档 + 无请求 -> GIMBAL_IMU（与打桥前逐位相同）
    下方安全档、上方档语义完全不变——物理遥控器仍是最终裁决者。

为什么借用 param0 而不是新加帧：不改变帧长与 CRC，老上位机发
param0=0 = 永远不请求，新客户端对老固件发它 = 被忽略。
双向兼容，零协议风险。

改哪四处（全部带 POLAR-GIMBAL-HOST 标记）
------------------------------------------
1. host_chassis_bridge.h：HOST_GIMBAL_REQ_MASK + extern HOST_GIMBAL_REQUEST
2. usb_task.c 全局区：定义 HOST_GIMBAL_REQUEST
3. usb_task.c GetChassisCmdData：随新鲜度门控维护请求位（过期即撤销）
4. gimbal_yaw_pitch_direct.c：中间档 ternary（无请求 = 原行为）

用法：
    python tools/firmware/gimbal_host/apply_gimbal_host.py <固件仓库根> [--dry-run]
回滚：在固件仓库 git checkout -- 相关文件。
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

MARK = "POLAR-GIMBAL-HOST"
BRIDGE_HEADER_REL = "application/typedef/host_chassis_bridge.h"
USB_REL = "application/communication/usb_task.c"
GIMBAL_REL = "application/gimbal/gimbal_yaw_pitch_direct.c"

HDR_ANCHOR = "#define HOST_SPIN_CMD_OFF ((uint8_t)0x02)"
HDR_ADD = '''

/* ''' + MARK + ''': param0 bit0 = 上位机请求云台直控（电平语义，
 * 与 spin_cmd 共用 HOST_SPIN_CMD_VALID_MS 新鲜度门控：上位机崩溃/拔线
 * 150ms 后请求自动撤销，云台控制权回到驾驶员手里）。
 * 背景：英雄板云台 AUTO_AIM 的唯一入口是 s[0] 上档，而麦轮上档 =
 * 底盘强制原地自转；本位让中间档在"上位机显式请求"时进入 AUTO_AIM，
 * 无请求（含老上位机恒 0）时与打桥前完全一致。 */
#define HOST_GIMBAL_REQ_MASK ((uint8_t)0x01)

/* usb_task 写，gimbal 模式仲裁读。与 HOST_SPIN_CMD 同一刷新/过期节奏。 */
extern volatile uint8_t HOST_GIMBAL_REQUEST;
'''

USB_STATIC_ANCHOR = "volatile uint8_t HOST_CHASSIS_SC_FLAG = 0;"
USB_STATIC_ADD = "volatile uint8_t HOST_GIMBAL_REQUEST = 0;  /* " + MARK + " */"

USB_STALE_OLD = """        HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
        return;"""
USB_STALE_NEW = """        HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
        HOST_GIMBAL_REQUEST = 0; /* """ + MARK + """: 过期同样撤销云台直控请求 */
        return;"""

USB_LEVEL_OLD = """        default:
            HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
            break;
    }
}"""
USB_LEVEL_NEW = """        default:
            HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
            break;
    }

    /* """ + MARK + """: param0 bit0 作电平：1 = 上位机请求云台直控。
     * 收不到帧时上面已提前 return 并清零，不会残留旧请求。 */
    HOST_GIMBAL_REQUEST =
        ((RECEIVE_CHASSIS_CMD_DATA.data.param0 & HOST_GIMBAL_REQ_MASK) != 0) ? 1 : 0;
}"""

GIMBAL_INCLUDE = '#include "host_chassis_bridge.h"  /* ' + MARK + ': HOST_GIMBAL_REQUEST */'

GIMBAL_MID_OLD = """  else if (switch_is_mid(gimbal_direct.rc->rc.s[0]))
  {
    gimbal_direct.mode=GIMBAL_IMU;
  }"""
GIMBAL_MID_NEW = """  else if (switch_is_mid(gimbal_direct.rc->rc.s[0]))
  {
    /* """ + MARK + """: 上位机显式请求（0x04 param0 bit0，150ms 新鲜度门控）
     * 时中间档也进 GIMBAL_AUTO_AIM——英雄板上档 = 底盘强制自转，只有
     * 中间档能同时"底盘听 spin_cmd/拨杆、瞄准听上位机"。
     * 无请求 / 断链时与本补丁之前完全一致（GIMBAL_IMU）。 */
    gimbal_direct.mode = (HOST_GIMBAL_REQUEST != 0) ? GIMBAL_AUTO_AIM : GIMBAL_IMU;
  }"""


def eol_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def to_eol(block: str, eol: str) -> str:
    return block.replace("\r\n", "\n").replace("\n", eol)


def replace_once(text: str, old: str, new: str, label: str, eol: str) -> str:
    o, n = to_eol(old, eol), to_eol(new, eol)
    assert text.count(o) == 1, "锚点不唯一/缺失：" + label
    return text.replace(o, n, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    repo = args.repo

    bridge = repo / BRIDGE_HEADER_REL
    if not bridge.exists():
        print("NO-GO: 缺 host_chassis_bridge.h —— 本桥依赖 host_bridge 先套"
              "（先运行 host_bridge/apply_host_bridge.py 或 prepare_hero_build.py）")
        return 2

    edited = {}

    hdr = io.open(bridge, encoding="utf-8").read()
    if MARK in hdr:
        print("  [skip] 桥接头文件已含标记")
    else:
        edited[BRIDGE_HEADER_REL] = replace_once(
            hdr, HDR_ANCHOR, HDR_ANCHOR + HDR_ADD, "header anchor", eol_of(hdr))

    usb = io.open(repo / USB_REL, encoding="utf-8").read()
    if MARK in usb:
        print("  [skip] usb_task.c 已含标记")
    else:
        eol = eol_of(usb)
        new = replace_once(usb, USB_STATIC_ANCHOR,
                           USB_STATIC_ANCHOR + "\n" + USB_STATIC_ADD, "usb statics", eol)
        new = replace_once(new, USB_STALE_OLD, USB_STALE_NEW, "usb stale", eol)
        new = replace_once(new, USB_LEVEL_OLD, USB_LEVEL_NEW, "usb level", eol)
        edited[USB_REL] = new

    gim = io.open(repo / GIMBAL_REL, encoding="utf-8").read()
    if MARK in gim:
        print("  [skip] 云台文件已含标记")
    else:
        eol = eol_of(gim)
        inc_anchor = '#include "gimbal_yaw_pitch_direct.h"'
        new = replace_once(gim, inc_anchor, inc_anchor + "\n" + GIMBAL_INCLUDE,
                           "gimbal include", eol)
        new = replace_once(new, GIMBAL_MID_OLD, GIMBAL_MID_NEW, "gimbal mid branch", eol)
        edited[GIMBAL_REL] = new

    if args.dry_run:
        for rel in edited:
            print("  [dry] 将改 " + rel)
        if not edited:
            print("  [dry] 全部已套用，无需改动")
        return 0
    for rel, text in edited.items():
        io.open(repo / rel, "w", encoding="utf-8", newline="").write(text)
        print("  [ok] 写入 " + rel)
    print("GO: gimbal_host 桥已套用到 " + str(repo) if edited else "GO: 已全部套用，无需改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
