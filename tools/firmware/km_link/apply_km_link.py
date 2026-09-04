#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把图传键鼠链路（0x0311 PRM1 kind=3 + __CONTROL_LINK_KM 五档仲裁）装进固件树。

为什么要它
----------
队内固件自己定义了五档"键鼠数据从哪来"（robot_typedef.h:80-84），但全仓库
**零消费者**；0x0311（自定义客户端->机器人，30 字节，75Hz）在 referee.c:247
已经 memcpy 进内存，往上交接的几行（usb_task.c:125/181/392/605-609/1216-1219）
全是注释。数据躺在内存里没人读。本脚本把那半截接完。

不用 0x0304 的原因：《RM2026 通信协议》V1.3.0（2026.03.26）修改日志
明写"删除命令码 0x0304"，新赛季裁判系统根本不会再发它。

默认档（CL_KM_RC）下现役车行为逐位不变：仲裁算完就是"驾驶员 | 上位机"，
鼠标一个字节都不动。

用法
----
    python tools/firmware/km_link/apply_km_link.py <固件根目录> [--dry-run]

前置 host_bridge 会自动补装；幂等；所有改动带 POLAR-KM-LINK 标记。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRM_TOOL_DIR = HERE.parent
sys.path.insert(0, str(FIRM_TOOL_DIR / "host_bridge"))
from apply_host_bridge import (_replace_once, _sub_once,  # noqa: E402
                               ensure_drive_keys_patch, MARK as BRIDGE_MARK,
                               USB_REL)

MARK = "POLAR-KM-LINK"
HEADER_NAME = "host_km_link.h"
REF_REL = "application/referee/referee.c"
RC_REL = "application/other/remote_control.c"

# ---------------------------------------------------------------------------
# referee.c —— 只在 0x0311 解包现场补一笔"什么时候到的"
# ---------------------------------------------------------------------------
REF_INCLUDE = f'#include "host_km_link.h"  /* {MARK}: 图传键鼠链路的交接量 */' + "\n"

REF_GLOBALS = f"""
/* {MARK}: 0x0311（自定义客户端->机器人）的到达时刻与计数。
 * 解包现场才知道包真的到了，所以时刻只在这里刷新；仲裁在 remote_control.c。 */
volatile uint32_t HOST_KM_RX_TIME = 0;
volatile uint32_t HOST_KM_RX_COUNT = 0;
"""

REF_RX_STAMP = f"""            /* {MARK}: 记 0x0311 到达时刻，仲裁按它做新鲜度门控 */
            HOST_KM_RX_TIME = HAL_GetTick();
            HOST_KM_RX_COUNT++;
"""

# ---------------------------------------------------------------------------
# remote_control.c —— 仲裁本体（它拥有 rc_ctrl，键鼠最终都落在那儿）
# ---------------------------------------------------------------------------
RC_INCLUDE = (f'#include "host_km_link.h"  /* {MARK}: 图传键鼠与遥控器键鼠的仲裁 */' + "\n"
              '#include "referee.h"  /* {MARK}: robot_custom_data_3 (0x0311) */' + "\n")

RC_DT7_MOUSE = f"""    /* {MARK}: 把驾驶员这一帧的鼠标增量记账，再按 __CONTROL_LINK_KM 决定
     * 云台最终用谁的鼠标。键位那两行是 {BRIDGE_MARK} 的账本，这里只补鼠标。 */
    HostKmApplyDriverFrameMouse(rc_ctrl);
"""

# 25 字节遥控器（ET08A/AT9S/HT8A）既没键位也没鼠标：两笔账都要清。
# 注意续行符：源码里要写 `\\`（= 落盘一个反斜杠 + 换行）。早期版本多打了
# 一层转义，落盘成两个反斜杠，编译器把第二个当成非法 token：
#   error: expected expression  (note: expanded from macro SPECIAL_CHANNEL_SET_SERO)
RC_NOKEY_MOUSE = (f"    HOST_RC_DRIVER_KEYS = 0;   /* {BRIDGE_MARK}: 本帧来自无键盘遥控器，"
                  f"驾驶员侧无键位 */\\\n"
                  f"    HostKmClearDriverMouse();   /* {MARK}: 同理，也没有鼠标可记 */\\\n")

RC_IMPL = f"""
/* ==== {MARK}: 图传键鼠链路（0x0311 PRM1 kind=3）+ __CONTROL_LINK_KM 五档仲裁 ====
 *
 * 刻意写成"运行期 switch 一档一分支"而不是五套 #if：五档共用同一份代码，
 * 行为差异全在 switch 里，能被同一份测试跑遍；而五套 #if 会让默认档编出来
 * 的代码和非默认档完全不同，测试就只覆盖了自己编译的那一档。
 * 代价是每轮多几个跳转，这个任务 1ms 一轮，量不出来。
 */

/* 驾驶员鼠标账本：SBUS 解码写，仲裁读。所有档位都定义，
 * 免得某一档"引用不到"撞上 --diag_error=warning。 */
static int16_t HOST_KM_DRV_MX = 0;    /* {MARK} */
static int16_t HOST_KM_DRV_MY = 0;    /* {MARK} */
static int16_t HOST_KM_DRV_MZ = 0;    /* {MARK} */
static uint8_t HOST_KM_DRV_BTN_L = 0; /* {MARK} */
static uint8_t HOST_KM_DRV_BTN_R = 0; /* {MARK} */
static uint8_t HOST_KM_DRV_SEEN = 0;  /* {MARK}: 有没有记过一笔（开机零值不等于驾驶员意图） */

/**
 * @brief 从 0x0311 的 30 字节里取队内 PRM1 键鼠载荷
 * @return 1=魔数/版本/类型三项全对；0=不是本队伍的键鼠包，一个字节都不许动
 * @note  version/kind 双校验是刻意的：客户端将来在同一通道上还会加别的
 *        指令（VISION=1 / SPIN=2 已经在发），键鼠这条不能被误当成别的包解。
 */
static uint8_t HostKmPeep(prm1_km_cmd_t *out)
{{
    const uint8_t *raw = robot_custom_data_3.data;

    if (raw[0] != PRM1_MAGIC_0 || raw[1] != PRM1_MAGIC_1 ||
        raw[2] != PRM1_MAGIC_2 || raw[3] != PRM1_MAGIC_3) {{
        return 0;
    }}
    if (raw[4] != (uint8_t)PRM1_VERSION || raw[5] != (uint8_t)PRM1_KIND_KM) {{
        return 0;
    }}
    memcpy(out, raw, sizeof(prm1_km_cmd_t));
    return 1;
}}

/**
 * @brief 决定云台用谁的鼠标并写回 rc->mouse
 *
 * 为什么鼠标必须"选一路"而键位可以"或两路"：鼠标字段是**本帧位移增量**
 * （官方 DR16 手册原话"鼠标在 X 轴的移动速度"），两路相加会把云台甩双倍；
 * 键位是位图，或起来才是想要的语义。
 */
static void HostKmMouseOut(RC_ctrl_t *rc)
{{
    prm1_km_cmd_t km;
    uint8_t km_ok;

    if (__CONTROL_LINK_KM == CL_KM_RC) {{
        return;  /* 默认档：鼠标一律归遥控器 */
    }}
    if (__CONTROL_LINK_KM == CL_KM_NONE) {{
        rc->mouse.x = 0;
        rc->mouse.y = 0;
        rc->mouse.z = 0;
        rc->mouse.press_l = 0;
        rc->mouse.press_r = 0;
        return;
    }}

    km_ok = HostKmPeep(&km) && HOST_KM_IS_FRESH();

    if (__CONTROL_LINK_KM == CL_KM_RC_VT && !km_ok) {{
        return;  /* 遥控器优先且图传不可用 -> 保持驾驶员这帧的鼠标 */
    }}
    if (__CONTROL_LINK_KM == CL_KM_RC_VT && HOST_KM_DRV_SEEN &&
        (HOST_KM_DRV_MX != 0 || HOST_KM_DRV_MY != 0 || HOST_KM_DRV_MZ != 0 ||
         HOST_KM_DRV_BTN_L != 0 || HOST_KM_DRV_BTN_R != 0)) {{
        return;  /* 驾驶员这帧真的动了鼠标 -> 遥控器优先，让给他 */
    }}
    if (!km_ok) {{
        /* 走到这里说明这一档以图传为准（CL_KM_VT / CL_KM_VT_RC）而图传不可用。
         * CL_KM_VT_RC 回落给驾驶员（账本还在 rc_ctrl->mouse 里，不用动）；
         * CL_KM_VT 按字面语义清零，且**摇杆照旧**，驾驶员仍能用摇杆停车。 */
        if (__CONTROL_LINK_KM == CL_KM_VT) {{
            rc->mouse.x = 0;
            rc->mouse.y = 0;
            rc->mouse.z = 0;
            rc->mouse.press_l = 0;
            rc->mouse.press_r = 0;
        }} else {{
            rc->mouse.press_l = 0;
            rc->mouse.press_r = 0;
        }}
        return;
    }}

    rc->mouse.x = km.mouse_x;
    rc->mouse.y = km.mouse_y;
    rc->mouse.z = km.mouse_z;
    rc->mouse.press_l = (uint8_t)((km.buttons & 0x01u) ? 1u : 0u);
    rc->mouse.press_r = (uint8_t)((km.buttons & 0x02u) ? 1u : 0u);
}}

/**
 * @brief 无键鼠的遥控器（25 字节帧）来帧时清驾驶员鼠标账
 * @note  与 {BRIDGE_MARK} 在同一个宏里那笔 HOST_RC_DRIVER_KEYS = 0 同理：
 *        不记这笔账，从 DT7 换成 ET08A 之后，"遥控器优先"会一直拿 DT7
 *        最后一帧的非零鼠标当依据，把图传鼠标永久挡在门外。
 */
void HostKmClearDriverMouse(void);
void HostKmClearDriverMouse(void)
{{
    HOST_KM_DRV_MX = 0;
    HOST_KM_DRV_MY = 0;
    HOST_KM_DRV_MZ = 0;
    HOST_KM_DRV_BTN_L = 0;
    HOST_KM_DRV_BTN_R = 0;
    HOST_KM_DRV_SEEN = 0;
}}

/**
 * @brief SBUS 解码每帧调用：记驾驶员鼠标账，再决定本帧鼠标归属
 */
void HostKmApplyDriverFrameMouse(RC_ctrl_t *rc)
{{
    if (__CONTROL_LINK_KM == CL_KM_RC) {{
        return;  /* 默认档：不记账也不改，与打补丁前逐位相同 */
    }}
    HOST_KM_DRV_MX = rc->mouse.x;
    HOST_KM_DRV_MY = rc->mouse.y;
    HOST_KM_DRV_MZ = rc->mouse.z;
    HOST_KM_DRV_BTN_L = rc->mouse.press_l;
    HOST_KM_DRV_BTN_R = rc->mouse.press_r;
    HOST_KM_DRV_SEEN = 1;
    HostKmMouseOut(rc);
}}

/**
 * @brief 键鼠链路仲裁主入口
 *
 * 两个调用点，各补对方的盲区：
 *   - usb_task 主循环 1ms 一轮：负责"图传过期就归零"，不依赖遥控器还在发帧
 *     （车上没插 DBUS、或 0x0311 是唯一链路时，全靠这条兜底）；
 *   - SBUS 解码末尾：负责"这一帧的鼠标增量给谁"，鼠标是增量，晚一帧就丢。
 */
void HostKmLinkUpdate(void)
{{
    prm1_km_cmd_t km;
    uint8_t km_ok;

    if (__CONTROL_LINK_KM == CL_KM_RC) {{
        /* 现役车档位：图传不参与。显式写死这两个量，是为了让"从别的档
         * 切回 rc"之后不会留下脏账。 */
        HOST_RC_DRIVER_KEY_GATE = HOST_RC_DRIVER_GATE_OPEN;
        HOST_RC_KM_KEYS = HOST_RC_KM_KEY_NONE;
        /* 这一档也重算一次 key.v：值与 POLAR-HOST-BRIDGE 的 UsbMergeVirtualRcKeys 写进去的
         * 完全相同（合并式里图传那项恒 0、门闸全开），所以行为不变；
         * 好处是本函数在**任何**档位都保证"调完一次，key.v 就是三本账的当前
         * 合并值"，不留"某档要等下一个写入者才收敛"的不对称。 */
        rc_ctrl.key.v = HOST_RC_MERGED_KEYS();
        HostKmMouseOut(&rc_ctrl);
        return;
    }}
    if (__CONTROL_LINK_KM == CL_KM_NONE) {{
        HOST_RC_DRIVER_KEY_GATE = HOST_RC_DRIVER_GATE_SHUT;
        HOST_RC_KM_KEYS = HOST_RC_KM_KEY_NONE;
        rc_ctrl.key.v = HOST_RC_MERGED_KEYS();
        HostKmMouseOut(&rc_ctrl);
        return;
    }}

    km_ok = HostKmPeep(&km) && HOST_KM_IS_FRESH();

    /* 键位门闸：只有"只认图传"那一档关驾驶员键位。关的**只是键位**，
     * 摇杆 ch[] 与拨杆 s[] 一律不动——图传当场断掉，驾驶员还能用摇杆
     * 把车开回来、把模式锁掉。这是这条链路的底线。 */
    HOST_RC_DRIVER_KEY_GATE =
        (__CONTROL_LINK_KM == CL_KM_VT) ? HOST_RC_DRIVER_GATE_SHUT
                                       : HOST_RC_DRIVER_GATE_OPEN;
    HOST_RC_KM_KEYS = km_ok ? (uint16_t)(km.keys & (uint16_t)KM_KEY_ALLOWED_MASK)
                           : HOST_RC_KM_KEY_NONE;
    rc_ctrl.key.v = HOST_RC_MERGED_KEYS();
    HostKmMouseOut(&rc_ctrl);
}}
/* ==== {MARK} 结束 ==== */
"""

# ---------------------------------------------------------------------------
# usb_task.c —— 只要一个 1ms 周期调用
# ---------------------------------------------------------------------------
USB_INCLUDE = f'#include "host_km_link.h"  /* {MARK}: 周期仲裁 */' + "\n"
USB_CALL = f"        HostKmLinkUpdate();  /* {MARK}: 图传键鼠过期归零/仲裁 */\n"


def ensure_host_bridge(root: Path, log: list) -> None:
    """前置：host_bridge（键位账本 + 门闸）必须先装，本脚本要改写它那几行。"""
    rc = (root / RC_REL).read_text(encoding="utf-8", errors="surrogateescape")
    if "HOST_RC_DRIVER_KEY_GATE" in rc or "HOST_RC_MERGED_KEYS" in rc:
        log.append("  [ok]   host_bridge（键位账本）已在树里")
        return
    bridge = FIRM_TOOL_DIR / "host_bridge" / "apply_host_bridge.py"
    if not bridge.exists():
        raise RuntimeError(f"缺少前置脚本 POLAR-HOST-BRIDGE")
    ensure_drive_keys_patch(root, log)
    res = subprocess.run([sys.executable, str(bridge), str(root)],
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError("自动套用 host_bridge 失败："
                           + ((res.stderr or res.stdout).strip()[-260:]))
    log.append("  [ok]   自动套用 host_bridge（键位账本 + 门闸）")


def apply_referee(path: Path, log: list) -> str:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text
    text = _sub_once(text, r'#include\s+"protocol\.h"\s*\n', REF_INCLUDE,
                     "referee.c: include 图传键鼠头文件", log)
    text = _sub_once(text, r'robot_custom_data_3_t robot_custom_data_3;[^\n]*\n',
                     REF_GLOBALS, "referee.c: 定义到达时刻/计数", log)
    text = _sub_once(text,
                     r'memcpy\(&robot_custom_data_3,\s*frame \+ index,\s*'
                     r'sizeof\(robot_custom_data_3_t\)\)\s*;\s*\n',
                     REF_RX_STAMP, "referee.c: 0x0311 刷新到达时刻", log)
    return text


def apply_remote_control(path: Path, log: list) -> str:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text
    text = _sub_once(text, r'#include\s+"host_chassis_bridge\.h"[^\n]*\n',
                     RC_INCLUDE, "remote_control.c: include 图传键鼠头文件", log)
    text = _sub_once(text, r'rc_ctrl->key\.v = HOST_RC_MERGED_KEYS\(\);\s*\n',
                     RC_DT7_MOUSE, "remote_control.c: DT7 鼠标记账并仲裁", log)
    text = _replace_once(
        text,
        r'[ \t]*HOST_RC_DRIVER_KEYS = 0;\s*/\* ' + BRIDGE_MARK + r'[^\n]*\\\n',
        RC_NOKEY_MOUSE, "remote_control.c: 无鼠标遥控器清鼠标账", log)
    text = _sub_once(text, r'// clang-format on\s*\n',
                     RC_IMPL + "\n// clang-format on\n",
                     "remote_control.c: 仲裁函数实现", log)
    return text


def apply_usb_task(path: Path, log: list) -> str:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text
    text = _sub_once(text, r'#include\s+"host_chassis_bridge\.h"[^\n]*\n',
                     USB_INCLUDE, "usb_task.c: include 图传键鼠头文件", log)
    text = _sub_once(text, r'[ \t]*UsbMergeVirtualRcKeys\(\);\s*\n',
                     USB_CALL, "usb_task.c: 主循环 1ms 仲裁一轮", log)
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("firmware_root", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root: Path = args.firmware_root.resolve()
    ref, rc, usb = root / REF_REL, root / RC_REL, root / USB_REL
    typedef_dir = root / "application" / "typedef"
    for p in (ref, rc, usb, typedef_dir):
        if not p.exists():
            print(f"[FAIL] 找不到 {p}")
            return 2

    log: list[str] = []
    print(f"固件树：{root}")
    try:
        ensure_host_bridge(root, log)
        r1 = apply_referee(ref, log)
        r2 = apply_remote_control(rc, log)
        r3 = apply_usb_task(usb, log)
    except RuntimeError as exc:
        for line in log:
            print(line)
        print(f"[FAIL] {exc}")
        return 2

    for line in log:
        print(line)
    if args.dry_run:
        print("\n[dry-run] 以上为计划改动，未落盘")
        return 0

    touched = 0
    for path, text in ((ref, r1), (rc, r2), (usb, r3)):
        if text != path.read_text(encoding="utf-8", errors="surrogateescape"):
            path.write_text(text, encoding="utf-8", errors="surrogateescape")
            touched += 1

    # 兜底闸门：三个文件一个都没落盘、可树里又没有本层标记，说明改动被
    # 某个 return/条件静默丢掉了。以前就踩过这个坑——日志一片 [ok]、
    # prepare 照样报 GO，但树其实没动，等于所有"验证"验的是空气。
    marker = (rc.read_text(encoding="utf-8", errors="surrogateescape")
              .count(MARK))
    if touched == 0 and marker == 0:
        print(f"[FAIL] 没有任何文件落盘，且 {RC_REL} 里找不到 {MARK} 标记")
        return 2
    print(f"  [ok]   本轮落盘 {touched} 个文件；树内 {MARK} 标记 {marker} 处")

    shutil.copy2(HERE / HEADER_NAME, typedef_dir / HEADER_NAME)
    print(f"  [ok]   安装 {HEADER_NAME} -> application/typedef/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
