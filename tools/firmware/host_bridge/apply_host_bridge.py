#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 host_chassis_bridge 装进 StandardRobot++ 固件树。

为什么需要它（一句话）
----------------------
客户端原来只能借"虚拟遥控器的 SHIFT 键"来开小陀螺，而固件对 SHIFT 是
**按一下翻转一次**：只能开、关不掉，再开一次反而关掉。
本脚本给固件补一对语义明确的数据段：

    上行 0x04  上位机 -> 机器人   "自转要开 / 自转要关"
    下行 0x1F  机器人 -> 上位机   "自转现在是开是关 + 底盘模式 + 自检位"

有了下行回读，客户端才能确认指令真的生效（闭环），而不是"发出去就算成功"。

用法
----
    python tools/firmware/host_bridge/apply_host_bridge.py <固件仓库根目录>
        [--dry-run] [--emit-patch 输出路径]

幂等：重复执行不会叠加。所有改动都带 "POLAR-HOST-BRIDGE" 标记，
可据此精确回滚（见 --revert）。

刻意不做的事
------------
- 不碰 ChassisSetMode 里原有的模式仲裁逻辑。物理遥控器永远是最终裁决者，
  上位机只维护 spin_flag 这一个量。
- 不让 usb_task.c include 任何底盘头文件。usb_task 只认报文，底盘只认全局量，
  避免麦轮/全向轮编译配置互相污染。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

MARK = "POLAR-HOST-BRIDGE"
HEADER_NAME = "host_chassis_bridge.h"
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# usb_task.c 的改动点
# ---------------------------------------------------------------------------

USB_INCLUDE = f"""#include "host_chassis_bridge.h"  /* {MARK}: 上位机自转指令桥 */
"""

USB_DURATION = f"""#define SEND_DURATION_ChassisState 50  // ms  /* {MARK} */
"""

USB_LASTSEND = f"""    uint32_t ChassisState;  /* {MARK} */
"""

USB_STATICS = f"""
/* {MARK}: 上位机 <-> 底盘 桥接全局量。
 * 定义放在 usb_task.c，因为它是唯一认识 USB 报文的一方；
 * 底盘侧只通过 host_chassis_bridge.h 里的 extern 声明读写它们。 */
volatile uint8_t HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
volatile uint32_t HOST_SPIN_CMD_TIME = 0;
volatile uint8_t HOST_SPIN_STATE = 0;
volatile uint8_t HOST_CHASSIS_MODE = 0;
volatile uint8_t HOST_CHASSIS_SC_FLAG = 0;

static ReceiveDataChassisCmd_s RECEIVE_CHASSIS_CMD_DATA;  /* {MARK} */
static SendDataChassisState_s SEND_CHASSIS_STATE_DATA;    /* {MARK} */
"""

USB_MEMSET = f"""    memset(&RECEIVE_CHASSIS_CMD_DATA, 0, sizeof(ReceiveDataChassisCmd_s));  /* {MARK} */
"""

USB_SEND_CALL = f"""    // 发送ChassisState数据（{MARK}：自转状态回读，客户端靠它确认指令生效）
    CheckDurationAndSend(ChassisState);
"""

USB_RX_CASE = f"""                    case CHASSIS_CMD_DATA_RECEIVE_ID: {{  /* {MARK} */
                        memcpy(
                            &RECEIVE_CHASSIS_CMD_DATA,
                            sof_address,
                            sizeof(ReceiveDataChassisCmd_s));
                        /* 收到即刷新新鲜度时刻；掉线判定在 GetChassisCmdData 里做，
                         * 这样底盘文件不必看见 HAL_GetTick。 */
                        HOST_SPIN_CMD_TIME = HAL_GetTick();
                    }} break;
"""

USB_TASK_CALL = f"""        GetChassisCmdData();  /* {MARK} */
"""

# 新增的两个静态函数定义排在文件后段，主循环与 UsbSendData 在前段就要调用。
# ARMCC 5.06 是单遍 C99 编译，漏了前置声明就是 #223-D 隐式声明；
# 本工程还开着 --diag_error=warning，警告即错误，所以必须补。
USB_PROTOTYPES = f"""/* {MARK}: 前置声明（定义在本文件后段） */
static void GetChassisCmdData(void);
static void UsbSendChassisStateData(void);
"""

USB_SEND_FN = f"""
/**
 * @brief 发送底盘状态（{MARK}）
 * @note  数据由 chassis_*.c 在 ChassisSetMode() 里回填，本函数只负责打包发出。
 *        客户端拿到 spin_state 才能区分"指令没送到"和"指令送到了但没生效"。
 */
static void UsbSendChassisStateData(void)
{{
    SEND_CHASSIS_STATE_DATA.time_stamp = HAL_GetTick();

    SEND_CHASSIS_STATE_DATA.data.spin_state = HOST_SPIN_STATE;
    SEND_CHASSIS_STATE_DATA.data.chassis_mode = HOST_CHASSIS_MODE;
    SEND_CHASSIS_STATE_DATA.data.sc_flag = HOST_CHASSIS_SC_FLAG;
    SEND_CHASSIS_STATE_DATA.data.reserved = 0;

    append_CRC16_check_sum(
        (uint8_t *)&SEND_CHASSIS_STATE_DATA, sizeof(SendDataChassisState_s));
    USB_Transmit(
        (uint8_t *)&SEND_CHASSIS_STATE_DATA, sizeof(SendDataChassisState_s));
}}
"""

USB_GET_FN = f"""
/**
 * @brief 消费上位机底盘指令（{MARK}）
 * @note  在 usb_task 主循环里每轮都调用，与 GetCmdData/GetVirtualRcCtrlData 并列。
 *
 *        新鲜度门控是关键：上位机按"电平"方式持续重发指令，一旦超过
 *        HOST_SPIN_CMD_VALID_MS 没刷新，就把 HOST_SPIN_CMD 置回 NONE，
 *        底盘随即停止被强制、控制权交还物理遥控器。
 *        这样即使客户端崩溃或串口被拔，也不会把车锁死在自转里。
 */
static void GetChassisCmdData(void)
{{
    if ((HAL_GetTick() - HOST_SPIN_CMD_TIME) >= HOST_SPIN_CMD_VALID_MS) {{
        HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
        return;
    }}

    /* 只接受已知取值，未知值一律当作"不干预"，避免半包/串位导致误动作 */
    switch (RECEIVE_CHASSIS_CMD_DATA.data.spin_cmd) {{
        case HOST_SPIN_CMD_ON:
        case HOST_SPIN_CMD_OFF:
            HOST_SPIN_CMD = RECEIVE_CHASSIS_CMD_DATA.data.spin_cmd;
            break;
        default:
            HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
            break;
    }}
}}
"""

CHASSIS_INCLUDE = f"""#include "host_chassis_bridge.h"  /* {MARK}: 上位机自转指令桥 */
"""

CHASSIS_HOOK = f"""    /* {MARK}: 消费上位机自转指令并回填状态。
     * 放在最开头，因为后面 s[0] 拨杆仲裁可能直接覆盖 chassis.mode
     * （麦轮拨到上方是无条件 CHASSIS_SPIN），但 spin_flag 由本宏维护，
     * 客户端因此第一次拥有了"关掉自转"的能力。 */
    HOST_CHASSIS_BRIDGE_APPLY(&chassis);
"""


def _probe(replacement: str) -> str:
    """取插入文本里第一行**非注释的有效代码**作为幂等探针。

    为什么不能直接取第一行：像 UsbSendChassisStateData 这种插入块以
    Doxygen 注释开头，第一行是 `/**` —— 而固件里到处都是 `/**`，
    会造成"已存在"的误判，把最关键的两个函数静默略过。
    （dry-run 实测踩过这个坑，此处是修正。）
    """
    for raw in replacement.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("/*", "*", "//")):
            continue
        return line
    raise RuntimeError("插入块里没有可用于幂等判断的有效代码行")


def _sub_once(text: str, pattern: str, replacement: str, what: str, log: list) -> str:
    """在 pattern 匹配处之后插入 replacement；已存在则跳过（幂等）。"""
    probe = _probe(replacement)
    # 必须按"整行相等"判断，不能用 `probe in text`：
    # 前置声明 static void GetChassisCmdData(void); 里包含了定义行
    # static void GetChassisCmdData(void) 这个子串，用子串判断会把
    # 真正的函数体误判成"已存在"而静默跳过（实测踩过，症状是 usb_task
    # 里只剩一句调用、函数根本没插进去）。
    if any(line.strip() == probe for line in text.splitlines()):
        log.append(f"  [skip] {what}（已存在）")
        return text
    new, n = re.subn(pattern, lambda m: m.group(0) + replacement, text, count=1)
    if n == 0:
        raise RuntimeError(f"锚点未找到：{what}（探针={probe!r}）")
    log.append(f"  [ok]   {what}")
    return new


def apply_usb_task(path: Path, log: list) -> str:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text

    text = _sub_once(
        text,
        r'#include\s+"IMU\.h"\s*\n',
        USB_INCLUDE,
        "usb_task.c: include 桥接头文件",
        log,
    )
    text = _sub_once(
        text,
        r'#define\s+SEND_DURATION_RobotMotion\s+[^\n]*\n',
        USB_DURATION,
        "usb_task.c: 新增发送周期 SEND_DURATION_ChassisState",
        log,
    )
    text = _sub_once(
        text,
        r'\n([ \t]*)uint32_t\s+RobotMotion\s*;\s*\n',
        USB_LASTSEND,
        "usb_task.c: LastSendTime_t 增加 ChassisState 字段",
        log,
    )
    text = _sub_once(
        text,
        r'static\s+ReceiveDataVirtualRc_s\s+RECEIVE_VIRTUAL_RC_DATA\s*;\s*\n',
        USB_STATICS,
        "usb_task.c: 定义桥接全局量与收发缓冲",
        log,
    )
    text = _sub_once(
        text,
        r'memset\(&RECEIVE_VIRTUAL_RC_DATA,\s*0,\s*sizeof\(ReceiveDataVirtualRc_s\)\)\s*;\s*\n',
        USB_MEMSET,
        "usb_task.c: UsbInit 清零新缓冲",
        log,
    )
    text = _sub_once(
        text,
        r'CheckDurationAndSend\(RobotMotion\)\s*;\s*\n',
        USB_SEND_CALL,
        "usb_task.c: UsbSendData 挂上 ChassisState",
        log,
    )
    text = _sub_once(
        text,
        r'case\s+VIRTUAL_RC_DATA_RECEIVE_ID\s*:\s*\{[\s\S]{0,300}?\}\s*break;\s*\n',
        USB_RX_CASE,
        "usb_task.c: 接收分发增加 0x04 分支",
        log,
    )
    text = _sub_once(
        text,
        r'([ \t]*)GetVirtualRcCtrlData\(\)\s*;\s*\n',
        USB_TASK_CALL,
        "usb_task.c: 主循环消费底盘指令",
        log,
    )
    text = _sub_once(
        text,
        r'static\s+void\s+GetVirtualRcCtrlData\(void\)\s*;\s*\n',
        USB_PROTOTYPES,
        "usb_task.c: 新函数前置声明",
        log,
    )
    text = _sub_once(
        text,
        r'static\s+void\s+UsbSendRobotMotionData\(void\)\s*\{[\s\S]*?\n\}\s*\n',
        USB_SEND_FN,
        "usb_task.c: 新增 UsbSendChassisStateData()",
        log,
    )
    text = _sub_once(
        text,
        r'static\s+void\s+GetVirtualRcCtrlData\(void\)\s*\{[\s\S]*?\n\}\s*\n',
        USB_GET_FN,
        "usb_task.c: 新增 GetChassisCmdData()",
        log,
    )
    return original if text == original else text


def apply_chassis(path: Path, header_anchor: str, log: list) -> str:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text

    text = _sub_once(
        text,
        rf'#include\s+"{re.escape(header_anchor)}"\s*\n',
        CHASSIS_INCLUDE,
        f"{path.name}: include 桥接头文件",
        log,
    )
    text = _sub_once(
        text,
        r'void\s+ChassisSetMode\(void\)\s*\n\{\s*\n',
        CHASSIS_HOOK,
        f"{path.name}: ChassisSetMode 开头接入桥接",
        log,
    )
    return original if text == original else text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("firmware_root", type=Path, help="StandardRobot++ 仓库根目录")
    ap.add_argument("--dry-run", action="store_true", help="只报告将改哪些文件，不落盘")
    ap.add_argument("--emit-patch", type=Path, default=None, help="生成 unified diff 到该路径")
    args = ap.parse_args(argv)

    root: Path = args.firmware_root.resolve()
    usb = root / "application" / "communication" / "usb_task.c"
    typedef_dir = root / "application" / "typedef"
    meca = root / "application" / "chassis" / "chassis_mecanum.c"
    omni = root / "application" / "chassis" / "chassis_omni.c"

    for p in (usb, typedef_dir):
        if not p.exists():
            print(f"[FAIL] 找不到 {p}\n       请确认传入的是 StandardRobot++ 仓库根目录")
            return 2

    header_src = HERE / HEADER_NAME
    if not header_src.exists():
        print(f"[FAIL] 缺少 {header_src}")
        return 2

    log: list[str] = []
    print(f"固件树：{root}")

    changed: list[tuple[Path, str]] = []

    new_usb = apply_usb_task(usb, log)
    if new_usb != usb.read_text(encoding="utf-8", errors="surrogateescape"):
        changed.append((usb, new_usb))

    for chassis_path, anchor in ((meca, "chassis_mecanum.h"), (omni, "chassis_omni.h")):
        if not chassis_path.exists():
            log.append(f"  [skip] {chassis_path.name}（不存在，该兵种未使用此底盘实现）")
            continue
        new_ch = apply_chassis(chassis_path, anchor, log)
        if new_ch != chassis_path.read_text(encoding="utf-8", errors="surrogateescape"):
            changed.append((chassis_path, new_ch))

    header_dst = typedef_dir / HEADER_NAME
    header_new = header_src.read_text(encoding="utf-8")
    if not header_dst.exists() or header_dst.read_text(encoding="utf-8") != header_new:
        changed.append((header_dst, header_new))
        log.append(f"  [ok]   安装 {HEADER_NAME} -> application/typedef/")
    else:
        log.append(f"  [skip] {HEADER_NAME}（已是最新）")

    print("\n".join(log))

    if args.dry_run:
        print(f"\n[dry-run] 将写入 {len(changed)} 个文件，未落盘")
        return 0

    if not changed:
        print("\n无需改动：桥接已完整安装")
        return 0

    for path, content in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", errors="surrogateescape")
    print(f"\n[OK] 已写入 {len(changed)} 个文件")

    if args.emit_patch is not None:
        try:
            diff = subprocess.run(
                ["git", "diff", "--no-color", "--", *[str(p.relative_to(root)) for p, _ in changed if p.exists()]],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if diff.returncode == 0 and diff.stdout.strip():
                args.emit_patch.parent.mkdir(parents=True, exist_ok=True)
                args.emit_patch.write_text(diff.stdout, encoding="utf-8")
                print(f"[OK] 补丁已生成：{args.emit_patch}")
            else:
                print("[warn] 未能生成 git diff（可能不是 git 仓库，或新文件未跟踪）")
        except FileNotFoundError:
            print("[warn] 系统没有 git，跳过补丁生成")

    print(
        "\n下一步：\n"
        "  1) Keil 里确认 application/typedef/host_chassis_bridge.h 能被找到"
        "（它在 include 路径目录里，不需加入编译列表，只要被 usb_task.c 引用即可）\n"
        "  2) 编译。若报 ChassisState_t / ChassisCmd_t 未定义，说明 include 路径没覆盖 typedef 目录\n"
        "  3) 烧录后：s[0] 拨杆必须在【中间】——上方是固件强制常转、下方是底盘锁定，"
        "两种都会让上位机指令看上去毫无反应\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
