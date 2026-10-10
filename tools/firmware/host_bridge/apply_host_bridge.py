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
# 键位记账要改写的那段合并代码由同级驾驶补丁引入。单独跑本脚本（测试自己
# bootstrap、或手工准备工程）时必须先把它补上，否则会撞"锚点未找到"。
DRIVE_KEYS_PATCH = HERE.parent / "polar-virtual-rc-drive-keys.patch"
USB_REL = "application/communication/usb_task.c"

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


def refresh_marked_block(text: str, head: str, tail: str, fresh: str,
                         label: str, log: list) -> str:
    """把树里那段"带标记的实现块"收敛成模板的最新版。

    为什么必须有：安装器的幂等一直是"标记已存在就 skip"，于是**模板改了、
    树里还是旧代码**，而日志一片 [ok]、上游照样报 GO（本轮真实踩到：
    新加的函数装不上，测试报"undeclared identifier"才暴露）。
    head/tail 定不出位或内容本来就一样时，原样返回，交给 _sub_once 去插入。
    """
    if head not in text or tail not in text or head not in fresh or tail not in fresh:
        return text
    i = text.index(head)
    j = text.index(tail, i)
    if j < 0:
        return text
    j += len(tail)
    old_block = text[i:j]
    k = fresh.index(head)
    m = fresh.index(tail, k) + len(tail)
    new_block = fresh[k:m]
    if old_block == new_block:
        return text
    log.append(f"  [ok]   {label}：模板已更新，用新版替换旧实现块"
               f"（{len(old_block)} -> {len(new_block)} 字节）")
    return text[:i] + new_block + text[j:]


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


def _replace_once(text: str, pattern: str, replacement: str, what: str, log: list) -> str:
    """把 pattern 匹配到的那一行**整体替换**为 replacement；已替换过则跳过。

    与 _sub_once 的区别很关键：`rc_ctrl.key.v |= drive_keys;` 这种"旧写法"必须
    被删掉而不是留在原地。否则旧行先 |= 置位、新行再写合并值，虽然最终结果
    正确，但 |= 那行会一直掩盖"松键粘住"这个真实缺陷（verify_changes 也查不出
    补丁到底生效了没有）。
    """
    probe = _probe(replacement)
    if any(line.strip() == probe for line in text.splitlines()):
        log.append(f"  [skip] {what}（已存在）")
        return text
    new, n = re.subn(pattern, lambda m: replacement, text, count=1)
    if n == 0:
        raise RuntimeError(f"锚点未找到：{what}（探针={probe!r}）")
    log.append(f"  [ok]   {what}")
    return new


def ensure_drive_keys_patch(root: Path, log: list, *, dry_run: bool = False) -> None:
    """保证 usb_task.c 里已有 UsbMergeVirtualRcKeys()（驾驶补丁的产物）。

    为什么在这里自动补而不是让调用方负责：本脚本的键位那三步
    （替换 `|=`、DT7 记账、置零宏清账）都是**改写**补丁带来的代码。少了前置
    补丁就只有锚点可寻，实测会让所有单独跑本脚本的测试整片报"锚点未找到"。
    自动补一次，调用顺序就不再是坑。
    """
    usb = root / USB_REL
    if not usb.exists():
        log.append(f"  [skip] 找不到 {USB_REL}，不自动补驾驶补丁")
        return
    if "UsbMergeVirtualRcKeys" in usb.read_text(encoding="utf-8", errors="surrogateescape"):
        log.append("  [ok]   驾驶补丁（0x03 键位合并）已在树里")
        return
    if not DRIVE_KEYS_PATCH.exists():
        raise RuntimeError(
            f"缺少驾驶补丁，且 usb_task.c 里没有 UsbMergeVirtualRcKeys：{DRIVE_KEYS_PATCH}")
    if dry_run:
        raise RuntimeError("dry-run: prerequisite drive patch is absent; no files changed. "
                           "Full planning requires an already prepared disposable copy.")
    res = subprocess.run(["git", "apply", str(DRIVE_KEYS_PATCH)],
                         cwd=root, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(
            "自动套用驾驶补丁失败（HEAD 可能不是基线 2722e0d）："
            + (res.stderr or res.stdout).strip()[:200])
    log.append("  [ok]   自动套用驾驶补丁 polar-virtual-rc-drive-keys.patch")


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
        r'volatile\s+uint8_t\s+HOST_CHASSIS_SC_FLAG\s*=\s*0;\s*\n',
        RC_GLOBALS,
        "usb_task.c: 定义驾驶键位记账量",
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
    text = _replace_once(
        text,
        r'[ \t]*rc_ctrl\.key\.v \|= drive_keys;[ \t]*\n',
        RC_USB_TASK,
        "usb_task.c: 驾驶键位改为记账合并（修松键粘住）",
        log,
    )
    return original if text == original else text


# ---------------------------------------------------------------------------
# 键位记账（DT7 整帧覆盖 / 客户端松键粘住 两个坑的统一解法）
# ---------------------------------------------------------------------------

RC_GLOBALS = f"""
/* {MARK}: 驾驶键位的两个记账量。定义仍放 usb_task.c，与上面那组全局量同处，
 * 但**写入者是两处**：HOST_RC_DRIVER_KEYS 由 remote_control.c 的 DT7 解码写，
 * HOST_RC_HOST_KEYS 由本文件的 UsbMergeVirtualRcKeys 写；两边都只通过
 * HOST_RC_MERGED_KEYS() 往 key.v 里写最终值。 */
volatile uint16_t HOST_RC_DRIVER_KEYS = 0;  /* {MARK} */
volatile uint16_t HOST_RC_HOST_KEYS = 0;    /* {MARK} */
/* {MARK}: 第三本账与驾驶员键位门闸。没装 km_link 时它们恒为
 * 「图传无键位 / 门闸全开」，合并值就退化成上面两本账的并集，
 * 行为与打 km_link 之前逐位相同；装了 km_link 之后由它按
 * __CONTROL_LINK_KM 刷新这两个量。 */
volatile uint16_t HOST_RC_DRIVER_KEY_GATE = HOST_RC_DRIVER_GATE_OPEN;
volatile uint16_t HOST_RC_KM_KEYS = HOST_RC_KM_KEY_NONE;
"""

RC_USB_TASK = f"""    /* {MARK}: 不是 `|=` 而是"记账 + 写合并值"。
     * 纯 |= 在无键盘遥控器（ET08A 等）上有个致命问题：没人负责清零，
     * 客户端按下 W 之后即使松手、即使 0x03 已过期，那一位也一直留在
     * rc_ctrl.key.v 里 -> 车踩不住刹车。改成写合并值以后，本函数每 1ms
     * 跑一轮，过期即 drive_keys=0，key.v 立刻回到"只有驾驶员键位"。 */
    HOST_RC_HOST_KEYS = drive_keys;
    rc_ctrl.key.v = HOST_RC_MERGED_KEYS();
"""

RC_DT7_CAPTURE = f"""    /* {MARK}: DT7 上面那行是对 key.v 的**整字段覆盖**（键位来自 SBUS 字节 14-15），
     * 直接保留它会让 usb_task 注入的客户端驾驶键位在下一帧被抹掉，而
     * chassis_mecanum.c 的 SHIFT 是边沿检测 -> 抹一下补一下会让 shift_pressed
     * 反复翻转，小陀螺开关跟着乱跳。所以这里把"驾驶员键位"记到账上，
     * 再由合并宏写出最终值（驾驶员 | 客户端，双方都不丢）。 */
    HOST_RC_DRIVER_KEYS = rc_ctrl->key.v;
    rc_ctrl->key.v = HOST_RC_MERGED_KEYS();
"""

RC_INCLUDE = f"""#include "host_chassis_bridge.h"  /* {MARK}: DT7 键位要与上位机键位合并 */
"""

RC_NOKEY_CLEAR = f"""    HOST_RC_DRIVER_KEYS = 0;   /* {MARK}: 本帧来自无键盘遥控器，驾驶员侧无键位 */\\
"""


def apply_remote_control(path: Path, log: list) -> str:
    """remote_control.c：DT7 解码处记账；顺带 include 桥接头文件。"""
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text

    text = _sub_once(
        text,
        r'#include\s+"communication\.h"\s*\n',
        RC_INCLUDE,
        "remote_control.c: include 桥接头文件",
        log,
    )
    text = _sub_once(
        text,
        r'rc_ctrl->key\.v = sbus_buf\[14\] \| \(sbus_buf\[15\] << 8\);\s*//[^\n]*\n',
        RC_DT7_CAPTURE,
        "remote_control.c: DT7 键位记账并写合并值",
        log,
    )
    # 无键盘遥控器（ET08A / AT9S / HT8A）：驾驶员侧键位恒 0，必须显式记这笔账。
    # 不写这一行的话，一旦车上先收到过 DT7 的 18 字节帧、之后换成了 25 字节帧，
    # HOST_RC_DRIVER_KEYS 会永远停在 DT7 最后一帧的按键上（车刹不住）。
    text = _sub_once(
        text,
        r'rc_ctrl->mouse\.press_r = 0;[ \t]*\\\n',
        RC_NOKEY_CLEAR,
        "remote_control.c: 无键盘遥控器清驾驶键账目",
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
    try:
        ensure_drive_keys_patch(root, log, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return 2

    rcrel = root / "application" / "other" / "remote_control.c"
    changed: list[tuple[Path, str]] = []

    new_usb = apply_usb_task(usb, log)
    if new_usb != usb.read_text(encoding="utf-8", errors="surrogateescape"):
        changed.append((usb, new_usb))

    if rcrel.exists():
        new_rc = apply_remote_control(rcrel, log)
        if new_rc != rcrel.read_text(encoding="utf-8", errors="surrogateescape"):
            changed.append((rcrel, new_rc))
    else:
        log.append(f"  [skip] remote_control.c（不存在，跳过键位合并）")

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
