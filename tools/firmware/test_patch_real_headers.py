"""用固件**真实头文件**编译补丁新增的 C 代码。

为什么需要它：`test_patch_logic.py` 用的是我自己手写的桩结构体。如果桩和固件
真实定义不一致（字段名、嵌套、类型、对齐），我的桩测试会绿而 Keil 会红。
本脚本改为直接 `#include "usb_typdef.h"` / `"remote_control.h"`，让补丁代码在
**固件真实类型定义**下通过 `clang -fsyntax-only -Wall -Wextra`。

可行性依据：`attribute_typedef.h` 把 `__packed__` 定义为
`__attribute__((packed))`，clang 原生支持；`remote_control.h` 的 include 链
（bsp_rc.h → struct_typedef.h）不拉 STM32 HAL，所以不需要伪造寄存器头。

跑法：
    python tools/firmware/test_patch_real_headers.py

固件副本不存在时跳过（返回 0），因为它依赖 tmp_polarbear 的只读 clone。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "polar-virtual-rc-drive-keys.patch"
REPO = HERE.parents[2] / "tmp_polarbear" / "StandardRobotpp"
USB_REL = "application/communication/usb_task.c"
RC_REL = "application/other/remote_control.c"

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def extract(text: str, pattern: str, label: str) -> str:
    m = re.search(pattern, text, re.S)
    if not m:
        raise AssertionError(f"在真实源文件里找不到 {label}")
    return m.group(0)


def main() -> int:
    if not REPO.exists() or not (REPO / ".git").exists():
        print(f"SKIP: 固件副本不存在（{REPO}）")
        return 0
    if not PATCH.exists():
        print(f"SKIP: 补丁不存在（{PATCH}）")
        return 0

    # 关键：先判断补丁是不是**已经在树里**了。如果是，绝对不能为了“测完恢复干净”
    # 而去 git checkout —— 那会把调用方（如 prepare_hero_build.py）刚准备好的
    # 工作树默默重置，导致“报 GO 但改动已被撤销”。
    already = "UsbMergeVirtualRcKeys" in (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
    owns_revert = False

    if already:
        print("[info] 补丁已存在于工作树，直接编译当前内容（不动 git，不做撤销）")
    else:
        git("checkout", "--", ".")
        owns_revert = True
        apply = git("apply", str(PATCH))
        check("补丁可套用到固件副本", apply.returncode == 0,
              (apply.stderr or apply.stdout)[:160])
        if apply.returncode != 0:
            git("checkout", "--", ".")
            return 1

    try:
        usb = (REPO / USB_REL).read_text(encoding="utf-8")
        rc = (REPO / RC_REL).read_text(encoding="utf-8")

        func = extract(usb, r"static void UsbMergeVirtualRcKeys\(void\)\s*\n\{.*?\n\}",
                       "UsbMergeVirtualRcKeys 函数体")
        macro = extract(rc, r"#define SPECIAL_CHANNEL_SET_SERO\(\)\\\n(?:[^\n]*\\\n)*[^\n]*\n",
                        "SPECIAL_CHANNEL_SET_SERO 宏")
        check("从打完补丁的真实源文件抽到了函数与宏",
              "rc_ctrl.key.v |= drive_keys;" in func and "mouse" in macro)
        check("真实源文件里的宏确实不再清 key.v", "key.v" not in macro)

        # 补丁能成立的一个隐含前提：remote_control.h **不导出** rc_ctrl（只给
        # const 指针），所以补丁必须自带 `extern RC_ctrl_t rc_ctrl;`。
        # 少了那行，Keil 会报 “use of undeclared identifier 'rc_ctrl'”。
        check("补丁自带 extern RC_ctrl_t rc_ctrl 声明（否则编译必输）",
              re.search(r"extern\s+RC_ctrl_t\s+rc_ctrl\s*;", usb) is not None)
        check("rc_ctrl 在定义处不是 static（否则 extern 链接失败）",
              re.search(r"^\s*static\s+RC_ctrl_t\s+rc_ctrl", rc, re.M) is None)

        # 用固件真实头文件编译：RC_ctrl_t / VIRTUAL_RC_CTRL 类型全部来自固件定义
        tu = f"""
/* 只依赖固件真实头文件，不伪造寄存器 */
#include "usb_typdef.h"
#include "remote_control.h"

static RC_ctrl_t VIRTUAL_RC_CTRL;
static bool USB_OFFLINE = true;
static uint32_t VIRTUAL_RC_RECEIVE_TIME = 0;
/* 与补丁一致：头文件不导出 rc_ctrl，必须自己 extern */
extern RC_ctrl_t rc_ctrl;
uint32_t HAL_GetTick(void);

#define VRC_DRIVE_KEY_MASK ((uint16_t)0x000F)
#define VRC_FRESH_TIMEOUT_MS 150

{func}

{macro}
static void probe_sero(RC_ctrl_t *rc_ctrl) {{ SPECIAL_CHANNEL_SET_SERO(); }}

_Static_assert(sizeof(RC_ctrl_t) == 22, "RC_ctrl_t must be 22 bytes");

int probe(void)
{{
    VIRTUAL_RC_CTRL.key.v = 0xFFFF;
    rc_ctrl.key.v = 0;
    VIRTUAL_RC_RECEIVE_TIME = HAL_GetTick();
    UsbMergeVirtualRcKeys();
    probe_sero(&rc_ctrl);
    return (int)rc_ctrl.key.v;
}}
"""
        inc_dirs = sorted({str(p.parent) for p in REPO.rglob("*.h")})
        with tempfile.TemporaryDirectory() as td:
            cpath = Path(td) / "real_headers_test.c"
            opath = Path(td) / "real_headers_test.o"
            cpath.write_text(tu, encoding="utf-8")
            # 不用 -fsyntax-only：它在 ziglang 的 Windows 轮子上会报
            # “error: FileNotFound”（连 int main(){return 0;} 都编不过），
            # 与被测代码无关。改成真的编到 .o，错误同样能报出来。
            cmd = ([sys.executable, "-m", "ziglang", "cc", "-c", "-o", str(opath),
                    "-Wall", "-Wextra", "-Wno-unused-parameter"]
                   + [f"-I{d}" for d in inc_dirs] + [str(cpath)])
            build = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")

        out = ((build.stderr or "") + (build.stdout or "")).strip()
        # 只关心指向本次测试 TU 的诊断；其他头文件的噪声单独统计
        own = [l for l in out.splitlines() if "real_headers_test.c" in l]
        errors = [l for l in own if " error:" in l]
        warnings = [l for l in own if " warning:" in l]
        # zig 自身驱动错（非 clang 诊断）要单独报出来，不能当成“代码有问题”
        driver_err = [l for l in out.splitlines()
                      if "FileNotFound" in l or "argument unused" in l]
        if driver_err and not errors:
            print("\n[warn] 编译器驱动层报错（与被测代码无关）：")
            for line in driver_err[:4]:
                print("   ", line[:170])

        print("\n--- 指向本次编译单元的诊断 ---")
        for line in (errors + warnings)[:12]:
            print("   ", line[:180])
        if not own:
            print("   （无）")

        check("补丁代码在固件真实头文件下语法/类型检查通过",
              build.returncode == 0 and not errors,
              errors[0][:180] if errors else f"exit={build.returncode}")
        check("无指向补丁代码的警告（对齐 Keil 警告即错误）",
              not warnings, warnings[0][:160] if warnings else "")
        check("RC_ctrl_t 尺寸断言由真实头文件成立",
              not any("sizeof(RC_ctrl_t)" in l for l in errors))

        if build.returncode != 0 and not errors:
            print("\n--- 完整输出尾部（供判断是否为无关头文件噪声）---")
            print(out[-1200:])

    finally:
        if owns_revert:
            git("checkout", "--", ".")

    print("\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for name in FAILED:
            print(f"  - {name[:110]}")
        return 1
    print("ALL REAL-HEADER COMPILE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
