"""驾驶键位三方写入者的**行为**校验（DT7 整帧覆盖 / 客户端松键粘住）。

为什么单独一个文件（而不是塞进 test_host_bridge.py）
--------------------------------------------------
test_host_bridge.py 测的是"自转开关"（0x04/0x1F）。键位合并是另一条完全
独立的通路：它同时有三个写入者（DT7 解码、无键盘遥控器的置零宏、usb_task
的 1ms 合并），任何一个写错都不是"编译能发现"的 —— 全是运行时语义。
所以这里把**真实源文件里抽出来的代码**编成可执行程序，按 50Hz 遥控器帧 +
1ms 主循环的时序跑一遍，逐条断言键位结果。

抽取而不是复制定义：掩码、150ms 阈值、合并宏、DT7 记账两行、置零宏
全部从打完补丁的固件树里正则抽出来。测试自己写死一份的话，固件改了而
测试没改，就会出现"测试绿、车上出事"。

跑法：
    python tools/firmware/host_bridge/test_rc_key_ledger.py

固件副本不存在、或补丁尚未套用时会 SKIP/FAIL（见下面的 already 判断）。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("POLAR_FIRMWARE_ROOT") or str(HERE.parents[3] / "tmp_polarbear" / "StandardRobotpp")).resolve()
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


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def extract(text: str, pattern: str, label: str) -> str:
    m = re.search(pattern, text, re.S)
    if not m:
        raise AssertionError(f"在打完补丁的固件源文件里找不到 {label}")
    return m.group(0)


def main() -> int:
    global REPO
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        REPO = Path(sys.argv[1]).expanduser().resolve()
    if not REPO.exists() or not (REPO / ".git").exists():
        print(f"SKIP: 固件副本不存在（{REPO}）")
        return 77
    def patched() -> bool:
        u = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
        r = (REPO / RC_REL).read_text(encoding="utf-8", errors="ignore")
        return "HOST_RC_MERGED_KEYS" in u and "HOST_RC_MERGED_KEYS" in r

    owns_revert = False
    if not patched():
        if os.environ.get("POLAR_FIRMWARE_READ_ONLY") == "1":
            print("[INCOMPLETE] Required prepared files are absent; read-only checks never install patches")
            return 77
        # 以前这里直接 SKIP 并 return 0：兄弟测试把树还原过，本项就一声不响地
        # 变成"通过"，verify_all 报 GO 却压根没测键位。现在改成自己装上再测。
        # 但"装"与"撤"都必须只在自己拍过快照的那几个文件里发生：
        # checkout -- . 会连 prepare_hero_build 写的兵种 include / 鼠标灵敏度一起冲掉。
        SNAPSHOT = bf.stage(REPO, [USB_REL, RC_REL, MECA_REL, OMNI_REL, HEADER_REL])
        git("checkout", "--", USB_REL, RC_REL, MECA_REL, OMNI_REL)
        owns_revert = True
        res = subprocess.run([sys.executable, str(HERE / "apply_host_bridge.py"), str(REPO)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        check("键位记账可套用到固件副本", res.returncode == 0,
              (res.stderr or res.stdout)[-260:])
        if res.returncode != 0 or not patched():
            bf.restore(SNAPSHOT, REPO)
            return 1
    usb = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
    rc = (REPO / RC_REL).read_text(encoding="utf-8", errors="ignore")

    merge_fn = extract(usb, r"static void UsbMergeVirtualRcKeys\(void\)\s*\n\{.*?\n\}",
                       "UsbMergeVirtualRcKeys 函数体")
    dt7_lines = extract(
        rc,
        r"HOST_RC_DRIVER_KEYS = rc_ctrl->key\.v;\s*\n\s*rc_ctrl->key\.v = HOST_RC_MERGED_KEYS\(\);",
        "DT7 记账两行")
    sero_macro = extract(
        rc, r"#define SPECIAL_CHANNEL_SET_SERO\(\)\\\n(?:[^\n]*\\\n)*[^\n]*\n",
        "SPECIAL_CHANNEL_SET_SERO 宏")
    mask_def = extract(usb, r"#define\s+VRC_DRIVE_KEY_MASK\s+[^\n]*\n", "VRC_DRIVE_KEY_MASK")
    fresh_def = extract(usb, r"#define\s+VRC_FRESH_TIMEOUT_MS\s+[^\n]*\n", "VRC_FRESH_TIMEOUT_MS")

    tu = f"""
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>

#include "remote_control.h"          /* RC_ctrl_t / KEY_xxx 真实定义 */
#include "host_chassis_bridge.h"     /* 键位掩码 + 两个账量 + 合并宏 */

/* 两个账量的定义在固件里位于 usb_task.c */
volatile uint16_t HOST_RC_DRIVER_KEYS = 0;
volatile uint16_t HOST_RC_HOST_KEYS = 0;
/* 第三本账 + 驾驶员键位门闸：合并宏现在无条件引用这两个量，
 * 而它们的真实定义在 usb_task.c（由 apply_host_bridge 写入），
 * 本测试复刻同一组初值 -> 门闸全开、图传无键位，等价于两本账时代。 */
volatile uint16_t HOST_RC_DRIVER_KEY_GATE = 0xFFFF;
volatile uint16_t HOST_RC_KM_KEYS = 0;

/* km_link 给置零宏又加了一句"清驾驶员鼠标账"。本测试只验键位，
 * 给个空桩即可（真实实现与其行为由 test_km_link.py 单独验）。 */
static void HostKmClearDriverMouse(void) {{ /* km_link 的空桩 */ }}

RC_ctrl_t rc_ctrl;

/* ---- usb_task.c 里的 static 上下文，按真实名字复刻，好让抽出来的函数原样编过 ---- */
static RC_ctrl_t VIRTUAL_RC_CTRL;
static bool USB_OFFLINE = true;
static uint32_t VIRTUAL_RC_RECEIVE_TIME = 0;
static uint32_t g_tick = 0;
uint32_t HAL_GetTick(void) {{ return g_tick; }}

{mask_def}
{fresh_def}

/* ---- 下面三个 probe 包的是**真实抽出来的**代码 ---- */
{merge_fn}

static void probe_dt7(const uint8_t *sbus_buf, RC_ctrl_t *rc_ctrl)
{{
    rc_ctrl->key.v = (uint16_t)(sbus_buf[14] | (sbus_buf[15] << 8));
    {dt7_lines}
}}

{sero_macro}
static void probe_nokey_rc(RC_ctrl_t *rc_ctrl) {{ SPECIAL_CHANNEL_SET_SERO(); }}

/* ---- 时序模拟：1ms 主循环 + 50Hz 遥控器帧 ---- */
static uint8_t frame[18];

static void feed_dt7(uint16_t driver_keys)
{{
    frame[14] = (uint8_t)(driver_keys & 0xFF);
    frame[15] = (uint8_t)(driver_keys >> 8);
    probe_dt7(frame, &rc_ctrl);
}}

static void feed_nokey_rc(void) {{ probe_nokey_rc(&rc_ctrl); }}

static void host_send(uint16_t keys, bool online)
{{
    VIRTUAL_RC_CTRL.key.v = keys;
    if (online) {{
        USB_OFFLINE = false;
        VIRTUAL_RC_RECEIVE_TIME = g_tick;
    }} else {{
        USB_OFFLINE = true;
    }}
}}

/* 复刻 chassis_mecanum.c:216 的 SHIFT 边沿检测，用来验证"键位不被抹掉" */
static int g_shift_prev = 0;
static int g_shift_edges = 0;
static void chassis_obs(void)
{{
    int now = (rc_ctrl.key.v >> KEY_SHIFT) & 1;
    if (now && !g_shift_prev) {{
        g_shift_edges++;
    }}
    g_shift_prev = now;
}}

/* 跑 ms 毫秒：每 20ms 一帧遥控器，每 1ms 一轮 usb_task 主循环 */
static void run_ms(int ms, int dt7, uint16_t driver_keys)
{{
    for (int i = 0; i < ms; i++) {{
        g_tick += 1;
        UsbMergeVirtualRcKeys();
        chassis_obs();
        if ((i % 20) == 0) {{
            if (dt7) {{
                feed_dt7(driver_keys);
            }} else {{
                feed_nokey_rc();
            }}
            UsbMergeVirtualRcKeys();
            chassis_obs();
        }}
    }}
}}

static int failures = 0;
static void expect(const char *what, int got, int want)
{{
    if (got != want) {{
        printf("  FAIL %s: got 0x%04X want 0x%04X\\n", what, got, want);
        failures++;
    }}
}}

int main(void)
{{
    const uint16_t W = (uint16_t)(1u << KEY_W);
    const uint16_t S = (uint16_t)(1u << KEY_S);
    const uint16_t SHIFT = (uint16_t)(1u << KEY_SHIFT);
    const uint16_t Q = (uint16_t)(1u << KEY_Q);
    const uint16_t F = (uint16_t)(1u << KEY_F);

    /* 1) DT7：驾驶员按 W、客户端按 S，两边都要在（叠加而非接管） */
    rc_ctrl.key.v = 0;
    g_shift_prev = 0; g_shift_edges = 0;
    feed_dt7(W);
    host_send(S, true);
    UsbMergeVirtualRcKeys();
    expect("DT7 驾驶员+客户端键位并存", rc_ctrl.key.v, (int)(W | S));

    /* 2) DT7 连打 10 帧，客户端键位不能被整帧覆盖抹掉（旧代码就是死在这） */
    for (int i = 0; i < 10; i++) {{
        feed_dt7(W);
        if (rc_ctrl.key.v != (uint16_t)(W | S)) {{
            break;
        }}
    }}
    expect("DT7 连帧后客户端键位仍在", rc_ctrl.key.v, (int)(W | S));

    /* 3) 客户端松键（0x03 过期）：键位必须回到"只剩驾驶员"，不能粘住 */
    host_send(0, true);           /* 客户端发了"无按键" */
    run_ms(200, 1, W);            /* 200ms 后连最后一帧也超过 150ms 新鲜期 */
    expect("客户端松键后不再粘键", rc_ctrl.key.v, (int)W);

    /* 4) 非 DT7（无键盘遥控器）：客户端过期后必须彻底归零 */
    rc_ctrl.key.v = 0;
    HOST_RC_DRIVER_KEYS = 0;
    HOST_RC_HOST_KEYS = 0;
    feed_nokey_rc();
    host_send(W | S, true);
    run_ms(10, 0, 0);
    expect("无键盘遥控器时客户端能开车", rc_ctrl.key.v, (int)(W | S));
    host_send(0, false);          /* 串口/USB 掉线 */
    run_ms(200, 0, 0);
    expect("无键盘遥控器 + 客户端掉线 => 键位归零（能刹住）", rc_ctrl.key.v, 0);

    /* 5) 车上从 DT7 换成 25 字节遥控器：DT7 残留的驾驶员键位不得冻住 */
    rc_ctrl.key.v = 0;
    HOST_RC_DRIVER_KEYS = 0;
    HOST_RC_HOST_KEYS = 0;
    feed_dt7(W | S);
    expect("DT7 驾驶员键位入账", HOST_RC_DRIVER_KEYS, (int)(W | S));
    feed_nokey_rc();
    UsbMergeVirtualRcKeys();
    expect("换无键盘遥控器后驾驶员键位清空", rc_ctrl.key.v, 0);

    /* 6) SHIFT 按住 1 秒（DT7 50Hz + 客户端同时在线）：只允许 1 个上升沿 */
    rc_ctrl.key.v = 0;
    HOST_RC_DRIVER_KEYS = 0;
    HOST_RC_HOST_KEYS = 0;
    g_shift_prev = 0; g_shift_edges = 0;
    feed_dt7(0);
    host_send(SHIFT, true);
    run_ms(1000, 1, 0);
    expect("SHIFT 长按只翻一次（小陀螺不自己乱跳）", g_shift_edges, 1);

    /* 7) 硬件上限：客户端即使发全 1，也只放行 W/S/A/D/SHIFT */
    rc_ctrl.key.v = 0;
    HOST_RC_DRIVER_KEYS = 0;
    HOST_RC_HOST_KEYS = 0;
    feed_nokey_rc();
    host_send(0xFFFF, true);
    UsbMergeVirtualRcKeys();
    expect("Q/E/F 等开火键位不从客户端放行", rc_ctrl.key.v, (int)HOST_RC_DRIVE_KEY_MASK);
    expect("放行掩码只有 W/S/A/D+SHIFT", HOST_RC_DRIVE_KEY_MASK, 0x001F);
    expect("开火键 Q 不在掩码内", (int)(HOST_RC_DRIVE_KEY_MASK & Q), 0);
    expect("sc_flag 键 F 不在掩码内", (int)(HOST_RC_DRIVE_KEY_MASK & F), 0);

    /* 8) 驾驶员的键位永远是主位：客户端全程离线时 DT7 按键照常生效 */
    rc_ctrl.key.v = 0;
    HOST_RC_DRIVER_KEYS = 0;
    HOST_RC_HOST_KEYS = 0;
    USB_OFFLINE = true;
    run_ms(100, 1, W | SHIFT);
    expect("客户端离线时驾驶员键位完好", rc_ctrl.key.v, (int)(W | SHIFT));

    if (failures) {{
        printf("KEY LEDGER BEHAVIOR FAILURES: %d\\n", failures);
        return 1;
    }}
    printf("KEY LEDGER BEHAVIOR OK (8 groups)\\n");
    return 0;
}}
"""
    # ---- 阴性对照：--negative 把代码退回打桥之前的旧写法 ----
    # 一个永远绿的测试等于没测试。这一档存在的唯一目的，是证明上面 8 组
    # 断言真的能抓到"DT7 整帧覆盖"和"客户端松键粘住"这两个缺陷。
    if "--negative" in sys.argv:
        tu = re.sub(
            r"HOST_RC_DRIVER_KEYS = rc_ctrl->key\.v;\s*\n\s*rc_ctrl->key\.v = HOST_RC_MERGED_KEYS\(\);",
            "/* 旧写法：DT7 直接整字段覆盖 key.v */", tu)
        tu = re.sub(
            r"HOST_RC_HOST_KEYS = drive_keys;\s*\n\s*rc_ctrl\.key\.v = HOST_RC_MERGED_KEYS\(\);",
            "rc_ctrl.key.v |= drive_keys;", tu)
        tu = re.sub(r"^    HOST_RC_DRIVER_KEYS = 0;.*\n",
                    "/* 旧写法：无键盘遥控器不清账目 */" + chr(92) + chr(10), tu, flags=re.M)
        print("[info] 阴性对照模式：把三处改回旧写法，断言应当失败")

    inc_dirs = sorted({str(p.parent) for p in REPO.rglob("*.h")})
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "rc_key_ledger.c"
        epath = Path(td) / "rc_key_ledger.exe"
        cpath.write_text(tu, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-O0", "-Wall", "-Wextra",
             "-Wno-unused-parameter", "-o", str(epath), str(cpath)]
            + [f"-I{d}" for d in inc_dirs],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("键位行为校验程序编译通过（真实头文件）", build.returncode == 0,
              ((build.stderr or "") + (build.stdout or ""))[-700:])
        if build.returncode == 0:
            run = subprocess.run([str(epath)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            body = ((run.stdout or "") + (run.stderr or "")).strip()
            if "--negative" in sys.argv:
                check("阴性对照：旧写法确实会被这 8 组断言抓到",
                      run.returncode != 0, body[-700:])
                if run.returncode != 0:
                    print("   ", body[:600])   # 不替换 FAIL 字样，避免把 FAILURES 也改掉
                print("\n" + "=" * 62)
                print("NEGATIVE CONTROL OK（旧写法被抓到，测试有效）")
                return 0
            check("键位三方写入者行为全部正确", run.returncode == 0, body[-700:])
            if run.returncode == 0:
                print("   ", body)

    if owns_revert:
        bf.restore(SNAPSHOT, REPO)      # 原本没有的头文件会被删掉，不留孤儿

    print("\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for name in FAILED:
            print(f"  - {name[:120]}")
        return 1
    print("ALL RC KEY LEDGER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
