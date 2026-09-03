#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 0x1E 速度回读装进 StandardRobot++ 固件树（motion_feedback 桥）。

为什么需要它（一句话）
----------------------
chassis_task.c 给 ChassisPublish() 留的是 __weak 空实现：麦轮（英雄）与
全向轮（步兵）build 从不 Publish "chassis_fdb_speed"，0x1E RobotMotion 段
因此**停发**（usb_task.c 里 FDB_SPEED_VECTOR == NULL 直接 return）。
客户端只能用 0x0A 测速模块坐标做位移兜底——能回答"车动没动"，
回答不了"速度对不对"。本补丁发布**实测轮速解算出的机体系速度**。

改哪三处（全部带 POLAR-MOTION-FEEDBACK 标记，可精确回滚）
--------------------------------------------------------
1. chassis_mecanum.c / chassis_omni.c：
   * ChassisObserver 末尾每帧更新 static chassis_fdb_speed；
   * 强符号 ChassisPublish() 注册该 static 地址（任务进循环前会被调用一次）。
2. usb_task.c：UsbSendRobotMotionData 的 NULL 守卫改成惰性重订阅——
   底盘任务与 USB 任务的启动先后不再有隐含依赖（平衡底盘同样受益）。

刻意不做的事
------------
- 不发布指令值冒充反馈（那会让"车是否响应"检测永远正常，比没有反馈更危险）。
- 不碰 ChassisConsole 的下发运动学；反解与它用同一组宏与同一套符号约定，
  由 test_motion_feedback.py 的往返断言强制一致。

用法
----
    python tools/firmware/motion_feedback/apply_motion_feedback.py <固件仓库根> [--dry-run]

回滚：在固件仓库 git checkout -- 那三个文件。
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

MARK = "POLAR-MOTION-FEEDBACK"

MECA_REL = "application/chassis/chassis_mecanum.c"
OMNI_REL = "application/chassis/chassis_omni.c"
USB_REL = "application/communication/usb_task.c"

INCLUDES = (
    '#include "custom_typedef.h"  /* ' + MARK + ': ChassisSpeedVector_t / CHASSIS_FDB_SPEED_NAME */\n'
    '#include "data_exchange.h"   /* ' + MARK + ': Publish */\n'
)

OBSERVER_HOOK = "    chassis_update_fdb_speed();  /* " + MARK + ": 每帧刷新实测机体系速度 */\n"

BLOCK_HEAD = """
/* """ + MARK + """-BEGIN: 实测轮速 -> 机体系速度回读，让 0x1E RobotMotion 真正发出来。
 * 发布的是测量值而不是指令值——拿指令冒充反馈会让上位机的
 * "车是否响应"检测永远显示正常，比没有反馈更危险。
 * 坐标系与单位同 ChassisSpeedVector_t：vx/vy m/s（机体系），wz rad/s。 */
static ChassisSpeedVector_t chassis_fdb_speed;

static void chassis_update_fdb_speed(void)
{
    const fp32 norm2 = 2.0f * sqrt(2.0f);
    fp32 q0 = chassis.feedback[0] * """

MECA_TAIL = """;
    fp32 q1 = chassis.feedback[1] * WHEEL_RADIUS * chassis.wheel[1].direction / chassis.wheel[1].reduction_ratio;
    fp32 q2 = chassis.feedback[2] * WHEEL_RADIUS * chassis.wheel[2].direction / chassis.wheel[2].reduction_ratio;
    fp32 q3 = chassis.feedback[3] * WHEEL_RADIUS * chassis.wheel[3].direction / chassis.wheel[3].reduction_ratio;
    chassis_fdb_speed.vx  = (q0 + q1 + q2 + q3) / norm2;
    chassis_fdb_speed.vy  = (-q0 + q1 - q2 + q3) / norm2;
    chassis_fdb_speed.wz  = (-q0 - q1 + q2 + q3) / (4.0f * WHEEL_CENTER_DISTANCE);
}

void ChassisPublish(void)
{
    chassis_update_fdb_speed();
    Publish(&chassis_fdb_speed, CHASSIS_FDB_SPEED_NAME);
}
/* """ + MARK + """-END */
"""

OMNI_TAIL = """;
    fp32 q1 = chassis.feedback[1] * WHEEL_RADIUS / chassis.wheel[1].reduction_ratio;
    fp32 q2 = chassis.feedback[2] * WHEEL_RADIUS / chassis.wheel[2].reduction_ratio;
    fp32 q3 = chassis.feedback[3] * WHEEL_RADIUS / chassis.wheel[3].reduction_ratio;
    chassis_fdb_speed.vx  = (-q0 - q1 + q2 + q3) / norm2;
    chassis_fdb_speed.vy  = (q0 - q1 - q2 + q3) / norm2;
    chassis_fdb_speed.wz  = -(q0 + q1 + q2 + q3) / (4.0f * WHEEL_CENTER_DISTANCE);
}

void ChassisPublish(void)
{
    chassis_update_fdb_speed();
    Publish(&chassis_fdb_speed, CHASSIS_FDB_SPEED_NAME);
}
/* """ + MARK + """-END */
"""

MECA_BLOCK = BLOCK_HEAD + "WHEEL_RADIUS * chassis.wheel[0].direction / chassis.wheel[0].reduction_ratio" + MECA_TAIL
OMNI_BLOCK = BLOCK_HEAD + "WHEEL_RADIUS / chassis.wheel[0].reduction_ratio" + OMNI_TAIL

USB_OLD = """    if (FDB_SPEED_VECTOR == NULL) {
        return;
    }"""
USB_NEW = """    if (FDB_SPEED_VECTOR == NULL) { /* """ + MARK + """: 惰性重订阅，摆脱任务启动顺序隐含依赖 */
        FDB_SPEED_VECTOR = Subscribe(CHASSIS_FDB_SPEED_NAME);
        if (FDB_SPEED_VECTOR == NULL) {
            return;
        }
    }"""


def eol_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def to_eol(block, eol):
    return block.replace("\r\n", "\n").replace("\n", eol)


def apply_chassis(src, block, rel):
    if MARK in src:
        print("  [skip] " + rel + " 已含标记")
        return src
    eol = eol_of(src)
    inc_anchor = to_eol('#include "chassis_power_control.h"', eol)
    assert src.count(inc_anchor) == 1, rel + ": include 锚点不唯一"
    hook_anchor = to_eol("    chassis.yaw_delta = GetGimbalDeltaYawMid();", eol)
    assert src.count(hook_anchor) == 1, rel + ": observer 锚点不唯一"
    src = src.replace(inc_anchor, inc_anchor + to_eol(INCLUDES.rstrip("\n"), eol), 1)
    src = src.replace(hook_anchor, hook_anchor + to_eol(OBSERVER_HOOK.rstrip("\n"), eol), 1)
    # 收尾不假设大括号前有没有空行：从 observer 锚点往后找第一个独立右大括号。
    hook_at = src.find(hook_anchor)
    close_at = src.find("}", hook_at)
    assert hook_at >= 0 and close_at > hook_at, rel + ": 找不到 observer 收尾大括号"
    tail = eol + to_eol(block.rstrip("\n"), eol)
    src = src[: close_at + 1] + tail + src[close_at + 1:]
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo
    for rel in (MECA_REL, OMNI_REL, USB_REL):
        if not (repo / rel).exists():
            print("NO-GO: 固件树缺 " + rel)
            return 2

    results = {}
    for rel, block in ((MECA_REL, MECA_BLOCK), (OMNI_REL, OMNI_BLOCK)):
        src = io.open(repo / rel, encoding="utf-8").read()
        new = apply_chassis(src, block, rel)
        if new != src:
            results[rel] = new

    src = io.open(repo / USB_REL, encoding="utf-8").read()
    if MARK in src:
        print("  [skip] usb_task.c 已含标记")
    else:
        eol = eol_of(src)
        old = to_eol(USB_OLD, eol)
        assert src.count(old) == 1, "usb_task.c: FDB 守卫锚点不唯一"
        results[USB_REL] = src.replace(old, to_eol(USB_NEW, eol), 1)

    if args.dry_run:
        for rel in results:
            print("  [dry] 将改 " + rel)
        if not results:
            print("  [dry] 三处都已带标记，无需改动")
        return 0

    if not results:
        print("GO: 三处均已套用过，无需改动")
        return 0
    for rel, new in results.items():
        io.open(repo / rel, "w", encoding="utf-8", newline="").write(new)
        print("  [ok] 写入 " + rel)
    print("GO: motion_feedback 已套用到 " + str(repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
