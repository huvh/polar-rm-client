"""用固件**真实头文件**编译补丁新增的 C 代码。

为什么需要它：`test_patch_logic.py` 用的是我自己手写的桩结构体。如果桩和固件
真实定义不一致（字段名、嵌套、类型、对齐），我的桩测试会绿而 Keil 会红。
本脚本改为直接 `#include "usb_typdef.h"` / `"remote_control.h"` /
`"host_chassis_bridge.h"`，让补丁代码在**固件真实类型定义**下通过 clang 编译。

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
MECA_REL = "application/chassis/chassis_mecanum.c"
OMNI_REL = "application/chassis/chassis_omni.c"
HEADER_REL = "application/typedef/host_chassis_bridge.h"
# 临时打桥要按字节快照还原，不能用 git checkout -- .（会把别的脚本写好的东西一起冲掉）
sys.path.insert(0, str(HERE.parent))
import bridge_fixture as bf  # noqa: E402
SNAPSHOT: dict = {}

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

    # 关键：先判断补丁是不是**已经在树里**了。如果是，绝对不能为了"测完恢复干净"
    # 而去 git checkout —— 那会把调用方（如 prepare_hero_build.py）刚准备好的
    # 工作树默默重置，导致"报 GO 但改动已被撤销"。
    def ledger_present() -> bool:
        """本测试要的最低状态：驾驶补丁 + 键位记账桥都在树里。"""
        u = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
        r = (REPO / RC_REL).read_text(encoding="utf-8", errors="ignore")
        return "HOST_RC_MERGED_KEYS" in u and "HOST_RC_MERGED_KEYS" in r

    already = ledger_present()
    owns_revert = False

    if already:
        print("[info] 补丁已存在于工作树，直接编译当前内容（不动 git，不做撤销）")
    else:
        # 先拍快照再定向 checkout；收尾只按快照还原（见 bridge_fixture 的说明）
        SNAPSHOT = bf.stage(REPO, [USB_REL, RC_REL, MECA_REL, OMNI_REL, HEADER_REL])
        git("checkout", "--", USB_REL, RC_REL, MECA_REL, OMNI_REL)
        owns_revert = True
        # 必须走 apply_host_bridge.py：它会先自动补上驾驶补丁，再装键位记账。
        # 早期版本在这里只 `git apply PATCH`，于是 DT7 记账那两行永远抽不到，
        # 报的是"找不到 DT7 键位记账两行"——看起来像测试坏了，其实是安装步骤不完整。
        bridge = HERE / "host_bridge" / "apply_host_bridge.py"
        apply = subprocess.run([sys.executable, str(bridge), str(REPO)],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        check("补丁 + 桥接可套用到固件副本", apply.returncode == 0,
              (apply.stderr or apply.stdout)[-260:])
        if apply.returncode != 0:
            bf.restore(SNAPSHOT, REPO)
            return 1

    try:
        usb = (REPO / USB_REL).read_text(encoding="utf-8")
        rc = (REPO / RC_REL).read_text(encoding="utf-8")

        func = extract(usb, r"static void UsbMergeVirtualRcKeys\(void\)\s*\n\{.*?\n\}",
                       "UsbMergeVirtualRcKeys 函数体")
        macro = extract(rc, r"#define SPECIAL_CHANNEL_SET_SERO\(\)\\\n(?:[^\n]*\\\n)*[^\n]*\n",
                        "SPECIAL_CHANNEL_SET_SERO 宏")
        # DT7 解码里的"记账 + 写合并值"两行。必须从真实文件抽：本次适配的全部风险
        # 都在这两行上（少了它，DT7 每帧整字段覆盖会把客户端键位抹掉）。
        dt7 = extract(
            rc,
            r"HOST_RC_DRIVER_KEYS = rc_ctrl->key\.v;\s*\n\s*rc_ctrl->key\.v = HOST_RC_MERGED_KEYS\(\);",
            "DT7 键位记账两行")
        # 两个阈值宏也用真实定义，避免测试自己写死 0x000F 与固件的 0x001F 悄悄分叉
        mask_def = extract(usb, r"#define\s+VRC_DRIVE_KEY_MASK\s+[^\n]*\n",
                           "VRC_DRIVE_KEY_MASK 定义")
        fresh_def = extract(usb, r"#define\s+VRC_FRESH_TIMEOUT_MS\s+[^\n]*\n",
                            "VRC_FRESH_TIMEOUT_MS 定义")

        check("从打完补丁的真实源文件抽到了函数、宏与 DT7 记账",
              "HOST_RC_HOST_KEYS = drive_keys;" in func
              and "mouse" in macro and "HOST_RC_MERGED_KEYS" in dt7)
        check("真实源文件里的宏确实不再清 key.v", "key.v" not in macro)
        # 旧写法 `key.v |= drive_keys` 必须彻底消失：在无键盘遥控器（ET08A 等）上
        # 它会让客户端一松手键位就永久粘住（车刹不住刹车）。
        check("usb_task 不再用 |= 写 key.v（已换成记账合并）",
              "rc_ctrl.key.v |=" not in func)
        # 无键盘遥控器必须把驾驶员侧账目记为 0，否则车上从 DT7 换成 25 字节
        # 遥控器时，键位会冻在 DT7 的最后一帧上。
        check("无键盘遥控器的置零宏会清驾驶员键位账目",
              "HOST_RC_DRIVER_KEYS = 0" in macro)

        # 补丁能成立的一个隐含前提：remote_control.h **不导出** rc_ctrl（只给
        # const 指针），所以补丁必须自带 `extern RC_ctrl_t rc_ctrl;`。
        # 少了那行，Keil 会报 "use of undeclared identifier 'rc_ctrl'"。
        check("补丁自带 extern RC_ctrl_t rc_ctrl 声明（否则编译必输）",
              re.search(r"extern\s+RC_ctrl_t\s+rc_ctrl\s*;", usb) is not None)
        check("rc_ctrl 在定义处不是 static（否则 extern 链接失败）",
              re.search(r"^\s*static\s+RC_ctrl_t\s+rc_ctrl", rc, re.M) is None)

        # 用固件真实头文件编译：RC_ctrl_t / VIRTUAL_RC_CTRL 类型全部来自固件定义
        tu = f"""
/* 只依赖固件真实头文件，不伪造寄存器 */
#include "usb_typdef.h"
#include "remote_control.h"
/* 键位账本（掩码 / 两个账量 / 合并宏）一律取真实桥接头里的定义。
 * 这里不复制一份，否则测的是副本而不是固件里真正跑的宏。 */
#include "host_chassis_bridge.h"

static RC_ctrl_t VIRTUAL_RC_CTRL;
static bool USB_OFFLINE = true;
static uint32_t VIRTUAL_RC_RECEIVE_TIME = 0;
/* 与补丁一致：头文件不导出 rc_ctrl，必须自己 extern */
extern RC_ctrl_t rc_ctrl;
uint32_t HAL_GetTick(void);

/* 两个键位账量：定义在固件里位于 usb_task.c，本 TU 自行定义一份 */
volatile uint16_t HOST_RC_DRIVER_KEYS = 0;
volatile uint16_t HOST_RC_HOST_KEYS = 0;

{mask_def}
{fresh_def}

{func}

{macro}
static void probe_sero(RC_ctrl_t *rc_ctrl) {{ SPECIAL_CHANNEL_SET_SERO(); }}

/* DT7 真实解码尾部：与 remote_control.c 里逐字一致 */
static void probe_dt7(const uint8_t *sbus_buf, RC_ctrl_t *rc_ctrl)
{{
    rc_ctrl->key.v = (uint16_t)(sbus_buf[14] | (sbus_buf[15] << 8));
    {dt7}
}}

_Static_assert(sizeof(RC_ctrl_t) == 22, "RC_ctrl_t must be 22 bytes");

int probe(void)
{{
    uint8_t frame[18] = {{0}};

    VIRTUAL_RC_CTRL.key.v = 0xFFFF;
    rc_ctrl.key.v = 0;
    VIRTUAL_RC_RECEIVE_TIME = HAL_GetTick();
    UsbMergeVirtualRcKeys();
    probe_sero(&rc_ctrl);
    frame[14] = 0x03;
    probe_dt7(frame, &rc_ctrl);
    return (int)rc_ctrl.key.v;
}}
"""
        inc_dirs = sorted({str(p.parent) for p in REPO.rglob("*.h")})
        with tempfile.TemporaryDirectory() as td:
            cpath = Path(td) / "real_headers_test.c"
            opath = Path(td) / "real_headers_test.o"
            cpath.write_text(tu, encoding="utf-8")
            # 不用 -fsyntax-only：它在 ziglang 的 Windows 轮子上会报
            # "error: FileNotFound"（连 int main(){return 0;} 都编不过），
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
        # zig 自身驱动错（非 clang 诊断）要单独报出来，不能当成"代码有问题"
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
            bf.restore(SNAPSHOT, REPO)   # 原本没有的头文件会被删掉，不留孤儿

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
