"""编译并运行队内固件补丁里的 C 逻辑。

为什么需要它：这台机器没有 Keil/ARMCC，补丁从来没被真正编译过，只能靠人眼审。
本脚本用 `zig cc`（自带 clang）把补丁里**新增的那段 C 原样抽出来**，套上最小
桩件后编译并跑行为测试 —— 能在拿去 Keil 之前抓住语法错、类型错和逻辑错。

关键设计：**代码是从 .patch 文件里抽取的，不是复制粘贴的**。所以补丁一旦改动，
这里测的就是改后的版本；不会出现"测试测的和维护的文档不是一份东西"。

编译选项带 `-Werror`，对齐 Keil 工程里 `--diag_error=warning`（警告即错误）的纪律。

跑法：
    python tools/firmware/test_patch_logic.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "polar-virtual-rc-drive-keys.patch"

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def extract_block(text: str, start_pat: str, end_pat: str) -> str:
    """从源码里截一段（含起止）。"""

    m = re.search(start_pat, text, re.S)
    if not m:
        raise AssertionError(f"找不到 {start_pat}")
    rest = text[m.start():]
    e = re.search(end_pat, rest, re.S)
    if not e:
        raise AssertionError(f"找不到 {end_pat}")
    return rest[: e.end()]


REPO = HERE.parents[2] / "tmp_polarbear" / "StandardRobotpp"
USB_REL = "application/communication/usb_task.c"
RC_REL = "application/other/remote_control.c"


def patched_sources() -> tuple[str, str]:
    """临时把补丁套到固件副本上，从**打完补丁的真实源文件**里抽代码。

    为什么不能从 diff 文本抽：`remote_control.c` 的改动是删一行，新增行里
    只有注释，宏本体在 diff 里是上下文。从真实文件抽还能顺带验证补丁能套上。
    结束时无论成败都还原副本。
    """

    if not REPO.exists():
        raise AssertionError(f"固件副本不存在：{REPO}")
    subprocess.run(["git", "checkout", "--", "."], cwd=REPO, capture_output=True)
    apply = subprocess.run(["git", "apply", str(PATCH)], cwd=REPO, capture_output=True, text=True)
    if apply.returncode != 0:
        raise AssertionError("补丁无法套用到固件副本：" + (apply.stderr or apply.stdout)[:200])
    try:
        usb = (REPO / USB_REL).read_text(encoding="utf-8")
        rc = (REPO / RC_REL).read_text(encoding="utf-8")
    finally:
        subprocess.run(["git", "checkout", "--", "."], cwd=REPO, capture_output=True)
    return usb, rc


C_TEMPLATE = r"""
/* 自动生成的桩件：把补丁里的真实代码嵌进来编译并跑行为测试。 */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>

/* RC_ctrl_t 必须逐字复刻 remote_control.h:141-161 的嵌套形状：
 * 固件宏里写的是 rc_ctrl->rc.ch[...]，不是扫平字段。 */
typedef struct {
    struct { int16_t ch[5]; int8_t s[2]; } rc;
    struct { int16_t x, y, z; uint8_t press_l, press_r; } mouse;
    struct { uint16_t v; } key;
} RC_ctrl_t;

RC_ctrl_t rc_ctrl;              /* remote_control.c 里的全局 */
static RC_ctrl_t VIRTUAL_RC_CTRL;
static bool USB_OFFLINE = true;
static uint32_t VIRTUAL_RC_RECEIVE_TIME = 0;

/* 可控的假时钟 */
static uint32_t FAKE_TICK = 1000u;
uint32_t HAL_GetTick(void) { return FAKE_TICK; }

/* ---- 以下代码逐字来自 polar-virtual-rc-drive-keys.patch ---- */
__PATCH_CODE__
/* ---- 补丁代码结束 ---- */

/* 复刻 remote_control.c 里改后的 SPECIAL_CHANNEL_SET_SERO()，
 * 用来验证它确实不再清 key.v。 */
__RC_MACRO__

/* 固件里 SPECIAL_CHANNEL_SET_SERO() 展开在 sbus_to_rc(...) 内部，那里有一个
 * 叫 rc_ctrl 的**局部指针参数**遮蔽了全局同名变量，所宏里用的是 `->`。
  测试必须复刻这个上下文，否则抽出来的宏根本编译不过。 */
static void apply_special_channel_zero(RC_ctrl_t *rc_ctrl)
{
    SPECIAL_CHANNEL_SET_SERO();
}

static int failures = 0;
#define EXPECT(cond, msg) do { \
    if (!(cond)) { printf("  C-FAIL %s\n", msg); failures++; } \
    else { printf("  C-OK   %s\n", msg); } \
} while (0)

int main(void)
{
    /* 1) 硬件侧上限：W/S/A/D + SHIFT；Q/E/F 必须被剥掉 */
    USB_OFFLINE = false;
    FAKE_TICK = 2000u;
    VIRTUAL_RC_RECEIVE_TIME = 2000u;
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    VIRTUAL_RC_CTRL.key.v = 0xFFFF;
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0x001F, "全 1 位图被裁到 W/S/A/D + SHIFT（Q/E/F 被剥）");

    /* 1b) 上限掩码必须仍禁掉开火相关位 */
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    VIRTUAL_RC_CTRL.key.v = (uint16_t)((1u << 6) | (1u << 7) | (1u << 9));  /* Q|E|F */
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0, "Q/E/F 即使在硬件上限内也被剥掉");

    /* 2) 不覆盖遥控器已有的其他位 */
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    rc_ctrl.key.v = (uint16_t)(1u << 12);          /* 遥控器自己的 X 键 */
    VIRTUAL_RC_CTRL.key.v = (uint16_t)(1u << 0);   /* 上位机 W */
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == ((1u << 12) | (1u << 0)), "OR 叠加保留遥控器已有键位");

    /* 3) 链路新鲜度门控：超过 150ms 不再置位 */
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    VIRTUAL_RC_CTRL.key.v = 0x000F;
    FAKE_TICK = 5000u;
    VIRTUAL_RC_RECEIVE_TIME = 4800u;               /* 200ms 前 */
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0, "0x03 断流超阈值后不再注入驾驶位");

    FAKE_TICK = 4900u;                             /* 100ms 前，仍在窗口内 */
    VIRTUAL_RC_RECEIVE_TIME = 4800u;
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0x000F, "150ms 窗口内正常注入");

    /* 4) USB 离线时绝不注入 */
    USB_OFFLINE = true;
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    FAKE_TICK = VIRTUAL_RC_RECEIVE_TIME;
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0, "USB_OFFLINE 时不注入");
    USB_OFFLINE = false;

    /* 5) 32 位 tick 回绕：无符号减法天然正确，不能误判成过期 */
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    VIRTUAL_RC_RECEIVE_TIME = 0xFFFFFFF0u;
    FAKE_TICK = 0x00000020u;                       /* 跨过 0，实际过了 48ms */
    VIRTUAL_RC_CTRL.key.v = 0x000F;
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0x000F, "HAL_GetTick 回绕后仍判为新鲜（无符号差值正确）");

    /* 回绕后真的过期时要能判出来 */
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    VIRTUAL_RC_RECEIVE_TIME = 0xFFFFFFF0u;
    FAKE_TICK = 0x00000200u;                       /* 实际过了 528ms */
    UsbMergeVirtualRcKeys();
    EXPECT(rc_ctrl.key.v == 0, "回绕后超过阈值仍判为过期");

    /* 6) 无键盘遥控器的特殊通道置零不得再清 key.v */
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    rc_ctrl.key.v = 0x001F;
    apply_special_channel_zero(&rc_ctrl);
    EXPECT(rc_ctrl.key.v == 0x001F, "ET08A 置零宏不再抹掉上位机注入的 key.v");
    EXPECT(rc_ctrl.mouse.x == 0 && rc_ctrl.mouse.press_r == 0, "同一宏仍正常清鼠标");
    EXPECT(sizeof(RC_ctrl_t) == 22, "RC_ctrl_t 尺寸 22 字节（与 0x03 帧布局假设一致）");

    if (failures) { printf("C TESTS FAILED: %d\n", failures); return 1; }
    printf("ALL C LOGIC TESTS PASSED\n");
    return 0;
}
"""


def build_patch_code() -> tuple[str, str]:
    usb, rc = patched_sources()

    defines = extract_block(usb, r"#define VRC_DRIVE_KEY_MASK", r"#define VRC_FRESH_TIMEOUT_MS 150")
    func = extract_block(usb, r"static void UsbMergeVirtualRcKeys\(void\)\s*\{", r"\n\}")
    # 注意：re.S 下 $ 只匹配字符串末尾，所以行尾用 【; 到行尾】而不是 【;$】
    macro = extract_block(rc, r"#define SPECIAL_CHANNEL_SET_SERO\(\)",
                          r"rc_ctrl->rc\.ch\[4\] = 0;[^\n]*\n")
    return f"{defines}\n\n{func}\n", macro


def main() -> int:
    if not PATCH.exists():
        print(f"[FAIL] 找不到补丁 {PATCH}")
        return 1
    patch_text = PATCH.read_text(encoding="utf-8")
    check("补丁含 usb_task.c 改动", "application/communication/usb_task.c" in patch_text)
    check("补丁含 remote_control.c 竞态修复", "application/other/remote_control.c" in patch_text)

    code, macro = build_patch_code()
    check("从打完补丁的源文件里抽到了合并函数",
          "UsbMergeVirtualRcKeys" in code and "rc_ctrl.key.v |= drive_keys;" in code)
    check("抽出的置零宏不再清 key.v", "key.v" not in macro, macro.replace("\n", " ")[:70])
    check("宏仍保留鼠标置零（只删了该删的那行）",
          "mouse.press_r" in macro and "rc.ch[4]" in macro)

    source = C_TEMPLATE.replace("__PATCH_CODE__", code).replace("__RC_MACRO__", macro)

    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "patch_logic_test.c"
        xpath = Path(td) / "patch_logic_test.exe"
        cpath.write_text(source, encoding="utf-8")
        cmd = [sys.executable, "-m", "ziglang", "cc", "-Werror", "-Wall", "-O0",
               str(cpath), "-o", str(xpath)]
        print(f"\n--- 编译（-Werror，对齐 Keil 的 --diag_error=warning）---")
        build = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if build.returncode != 0:
            print(build.stdout)
            print(build.stderr)
            check("补丁代码能通过 C 编译器（无警告无错误）", False,
                  (build.stderr or build.stdout)[:300])
            return 1
        check("补丁代码能通过 C 编译器（无警告无错误）", True)

        run = subprocess.run([str(xpath)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        print("--- C 侧行为断言 ---")
        for line in (run.stdout or "").splitlines():
            if "C-OK" in line:
                print(f"[PASS] C: {line.split('C-OK')[-1].strip()}")
            elif "C-FAIL" in line:
                FAILED.append(line.strip())
                print(f"[FAIL] C: {line.split('C-FAIL')[-1].strip()}")
        check("C 行为测试整体通过", run.returncode == 0, f"exit={run.returncode}")

    print("\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for name in FAILED:
            print(f"  - {name[:100]}")
        return 1
    print("ALL FIRMWARE PATCH LOGIC TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
