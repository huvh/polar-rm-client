"""host_chassis_bridge 的编译校验 + 行为校验。

为什么要两套校验
----------------
1) **编译校验**：把新代码放进固件**真实头文件**环境编译（ziglang 提供的 clang）。
   手写桩结构体测不出字段名/对齐/include 缺失的问题，桩绿而 Keil 红。
2) **行为校验**：模拟"开自转 → 关自转 → 再开"的完整序列。

   这一条才是本次改动的**目的所在**：原来借 SHIFT 键，固件是边沿翻转，
   客户端只能开、关不掉，再开一次反而关掉。如果行为校验只测"能开"，
   就等于没测到真正的缺陷。

跑法：
    python tools/firmware/host_bridge/test_host_bridge.py

固件副本不存在时跳过（返回 0）。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3] / "tmp_polarbear" / "StandardRobotpp"
USB_REL = "application/communication/usb_task.c"
MECA_REL = "application/chassis/chassis_mecanum.c"
OMNI_REL = "application/chassis/chassis_omni.c"
HEADER_REL = "application/typedef/host_chassis_bridge.h"
# 临时打桥要按字节快照还原，不能用 git checkout -- .（会冲掉别人的改动）
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
        raise AssertionError(f"在打完桥接的真实源文件里找不到 {label}")
    return m.group(0)


def compile_tu(tu: str, inc_dirs: list[str], name: str) -> tuple[int, list[str], list[str], str]:
    """编译一个临时 TU，返回 (returncode, errors, warnings, 完整输出)。"""
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / f"{name}.c"
        opath = Path(td) / f"{name}.o"
        cpath.write_text(tu, encoding="utf-8")
        # 不用 -fsyntax-only：它在 ziglang 的 Windows 轮子上会报 FileNotFound
        # （连 int main(){return 0;} 都编不过），与被测代码无关。
        cmd = ([sys.executable, "-m", "ziglang", "cc", "-c", "-o", str(opath),
                "-Wall", "-Wextra", "-Wno-unused-parameter"]
               + [f"-I{d}" for d in inc_dirs] + [str(cpath)])
        build = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    out = ((build.stderr or "") + (build.stdout or "")).strip()
    own = [l for l in out.splitlines() if f"{name}.c" in l or "host_chassis_bridge.h" in l]
    errors = [l for l in own if " error:" in l]
    warnings = [l for l in own if " warning:" in l]
    return build.returncode, errors, warnings, out


def main() -> int:
    if not REPO.exists() or not (REPO / ".git").exists():
        print(f"SKIP: 固件副本不存在（{REPO}）")
        return 0

    # 判"已打桥"要看 .c 内容：头文件是未跟踪文件，兄弟测试 git checkout 之后
    # .c 已回到基线、头文件却还留着，那时若因为"文件存在"就跳过安装，
    # 校验对象其实是没打桥的源文件（实测踩过，症状是"找不到函数体"）。
    usb_probe = ((REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
                 if (REPO / USB_REL).exists() else "")
    already = "POLAR-HOST-BRIDGE" in usb_probe
    owns_revert = False

    if already:
        print("[info] 桥接已存在于工作树，直接校验当前内容（不动 git）")
    else:
        # 顺序很重要：**先拍快照**，再把要改的文件放回干净状态。
        # 反过来做的话 checkout 丢掉的东西（prepare_hero_build 写的桥、别的自检装的补丁）
        # 就再也 restore 不回来了。收尾只认这份快照，绝不用 git checkout -- .
        SNAPSHOT = bf.stage(REPO, [USB_REL, MECA_REL, OMNI_REL, HEADER_REL])
        git("checkout", "--", USB_REL, MECA_REL, OMNI_REL)
        owns_revert = True
        apply = subprocess.run(
            [sys.executable, str(HERE / "apply_host_bridge.py"), str(REPO)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("桥接可套用到固件副本", apply.returncode == 0,
              (apply.stderr or apply.stdout)[-300:])
        if apply.returncode != 0:
            bf.restore(SNAPSHOT, REPO)
            return 1

    try:
        usb = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
        meca = (REPO / MECA_REL).read_text(encoding="utf-8", errors="ignore")
        omni = (REPO / OMNI_REL).read_text(encoding="utf-8", errors="ignore")
        header = (REPO / HEADER_REL).read_text(encoding="utf-8", errors="ignore")

        # ---------------- 结构校验 ----------------
        get_fn = extract(usb, r"static void GetChassisCmdData\(void\)\s*\n\{.*?\n\}",
                         "GetChassisCmdData 函数体")
        send_fn = extract(usb, r"static void UsbSendChassisStateData\(void\)\s*\n\{.*?\n\}",
                          "UsbSendChassisStateData 函数体")

        check("usb_task.c 已定义 5 个桥接全局量",
              all(f"volatile {t} {n}" in usb
                  for t, n in (("uint8_t", "HOST_SPIN_CMD"),
                               ("uint32_t", "HOST_SPIN_CMD_TIME"),
                               ("uint8_t", "HOST_SPIN_STATE"),
                               ("uint8_t", "HOST_CHASSIS_MODE"),
                               ("uint8_t", "HOST_CHASSIS_SC_FLAG"))))
        check("接收分发已挂上 0x04", "case CHASSIS_CMD_DATA_RECEIVE_ID:" in usb)
        check("主循环已调用 GetChassisCmdData", re.search(r"^\s*GetChassisCmdData\(\);", usb, re.M) is not None)
        check("发送编排已挂上 ChassisState", "CheckDurationAndSend(ChassisState);" in usb)
        check("LastSendTime_t 已加 ChassisState 字段", "uint32_t ChassisState;" in usb)
        check("UsbInit 已清零新缓冲", "memset(&RECEIVE_CHASSIS_CMD_DATA" in usb)

        # 掉线安全：必须把指令收回 NONE，否则上位机断线后车会被锁死在自转里
        check("指令过期会收回为 NONE（掉线不锁死自转）",
              "HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;" in get_fn
              and "HOST_SPIN_CMD_VALID_MS" in get_fn)
        # 未知取值必须当作不干预，避免半包/串位误动作
        check("未知指令值一律不干预", "default:" in get_fn and get_fn.count("HOST_SPIN_CMD_NONE") >= 2)

        for name, text in (("chassis_mecanum.c", meca), ("chassis_omni.c", omni)):
            check(f"{name} 已在 ChassisSetMode 接入桥接",
                  "HOST_CHASSIS_BRIDGE_APPLY(&chassis);" in text)
            # 真正要断言的是**位置**：桥接必须早于 s[0] 拨杆仲裁。
            # 不能用"函数体第一行"去判：插入块以注释开头，宏在第 5 行。
            fn_at = text.find("void ChassisSetMode(void)")
            hook_at = text.find("HOST_CHASSIS_BRIDGE_APPLY(&chassis);", fn_at)
            arb_at = text.find("switch_is_down(chassis.rc->rc.s[0])", fn_at)
            check(f"{name} 的桥接早于 s[0] 仲裁（spin_flag 先被维护）",
                  fn_at >= 0 and hook_at > fn_at and arb_at > hook_at,
                  f"fn={fn_at} hook={hook_at} arb={arb_at}")
            check(f"{name} 已 include 桥接头文件", 'host_chassis_bridge.h' in text)

        # 刻意不改固件原有的模式仲裁：物理遥控器必须始终是最终裁决者
        check("麦轮 s[0] 仲裁逻辑未被改动（遥控器仍是最终裁决者）",
              "switch_is_up(chassis.rc->rc.s[0])" in meca
              and "chassis.mode = CHASSIS_SPIN;" in meca)
        check("桥接宏不依赖 HAL（底盘文件无需看见 HAL_GetTick）",
              "HAL_GetTick" not in header.split("#define HOST_CHASSIS_BRIDGE_APPLY")[1])

        # ---------------- 编译校验 ----------------
        inc_dirs = sorted({str(p.parent) for p in REPO.rglob("*.h")})

        # (a) 头文件独立编译：验证它不需要 usb_typdef.h / FrameHeader_t
        rc, errs, warns, out = compile_tu(
            '#include "host_chassis_bridge.h"\n'
            "volatile uint8_t HOST_SPIN_CMD;\n"
            "volatile uint32_t HOST_SPIN_CMD_TIME;\n"
            "volatile uint8_t HOST_SPIN_STATE;\n"
            "volatile uint8_t HOST_CHASSIS_MODE;\n"
            "volatile uint8_t HOST_CHASSIS_SC_FLAG;\n"
            "int probe(void){ return (int)sizeof(SendDataChassisState_s); }\n",
            inc_dirs, "hdr_standalone")
        check("头文件可独立编译（不依赖 FrameHeader_t）", rc == 0 and not errs,
              errs[0][:200] if errs else f"exit={rc}")
        check("头文件独立编译无警告", not warns, warns[0][:160] if warns else "")

        # (b) 抽取的两个函数在真实头文件下编译
        tu = f"""
#include "usb_typdef.h"
#include "host_chassis_bridge.h"

volatile uint8_t HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
volatile uint32_t HOST_SPIN_CMD_TIME = 0;
volatile uint8_t HOST_SPIN_STATE = 0;
volatile uint8_t HOST_CHASSIS_MODE = 0;
volatile uint8_t HOST_CHASSIS_SC_FLAG = 0;

static ReceiveDataChassisCmd_s RECEIVE_CHASSIS_CMD_DATA;
static SendDataChassisState_s SEND_CHASSIS_STATE_DATA;

uint32_t HAL_GetTick(void);
void USB_Transmit(uint8_t *data, uint16_t len);
void append_CRC16_check_sum(uint8_t *pdata, uint16_t len);

{get_fn}

{send_fn}

int probe(void)
{{
    GetChassisCmdData();
    UsbSendChassisStateData();
    return (int)HOST_SPIN_CMD;
}}
"""
        rc, errs, warns, out = compile_tu(tu, inc_dirs, "bridge_funcs")
        check("抽取的收发函数在固件真实头文件下编译通过", rc == 0 and not errs,
              errs[0][:200] if errs else f"exit={rc}")
        check("收发函数编译无警告（Keil 视警告为需处理项）", not warns,
              warns[0][:160] if warns else "")
        if rc != 0 and not errs:
            print("\n--- 完整输出尾部 ---")
            print(out[-1200:])

        # ---------------- 行为校验 ----------------
        # 用一个最小底盘结构体（字段名与麦轮/全向轮一致），跑真实抽取的宏。
        macro = extract(header, r"#define HOST_CHASSIS_BRIDGE_APPLY\(chassis_ptr\)[\s\S]*?while \(0\)",
                        "HOST_CHASSIS_BRIDGE_APPLY 宏")
        behav = f"""
#include <stdint.h>
#include <stdio.h>

volatile uint8_t HOST_SPIN_CMD = 0;
volatile uint32_t HOST_SPIN_CMD_TIME = 0;
volatile uint8_t HOST_SPIN_STATE = 0;
volatile uint8_t HOST_CHASSIS_MODE = 0;
volatile uint8_t HOST_CHASSIS_SC_FLAG = 0;

#define HOST_SPIN_CMD_NONE ((uint8_t)0x00)
#define HOST_SPIN_CMD_ON   ((uint8_t)0x01)
#define HOST_SPIN_CMD_OFF  ((uint8_t)0x02)

{macro}

typedef struct {{ uint8_t spin_flag; uint8_t mode; uint8_t sc_flag; }} FakeChassis;

/* 复刻 usb_task.c 里 GetChassisCmdData 的新鲜度门控 */
static uint32_t now_tick = 0;
static uint8_t  wire_cmd = HOST_SPIN_CMD_NONE;   /* 串口上收到的原始值 */
static uint32_t wire_time = 0;                   /* 收到时刻 */
#define VALID_MS 150

static void host_tick(uint32_t t) {{ now_tick = t; }}
static void host_send(uint8_t cmd, uint32_t t) {{ wire_cmd = cmd; wire_time = t; }}
static void usb_get_chassis_cmd(void) {{
    HOST_SPIN_CMD_TIME = wire_time;
    if ((now_tick - HOST_SPIN_CMD_TIME) >= VALID_MS) {{
        HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
        return;
    }}
    switch (wire_cmd) {{
        case HOST_SPIN_CMD_ON:
        case HOST_SPIN_CMD_OFF: HOST_SPIN_CMD = wire_cmd; break;
        default: HOST_SPIN_CMD = HOST_SPIN_CMD_NONE; break;
    }}
}}

static int failures = 0;
static void expect(const char *what, int got, int want) {{
    if (got != want) {{ printf("  FAIL %s: got %d want %d\\n", what, got, want); failures++; }}
}}

int main(void)
{{
    FakeChassis ch = {{0, 2, 0}};

    /* 1) 开自转 */
    host_tick(1000); host_send(HOST_SPIN_CMD_ON, 1000);
    usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("开自转", ch.spin_flag, 1);
    expect("状态已回填", HOST_SPIN_STATE, 1);

    /* 2) 持续发 ON 不会翻转（这是原 SHIFT 方案做不到的） */
    for (int i = 0; i < 5; i++) {{
        host_tick(1010 + i); host_send(HOST_SPIN_CMD_ON, 1010 + i);
        usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    }}
    expect("连发5次ON仍是开", ch.spin_flag, 1);

    /* 3) 关自转 —— 原方案在这里彻底失效 */
    host_tick(1020); host_send(HOST_SPIN_CMD_OFF, 1020);
    usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("关自转", ch.spin_flag, 0);
    expect("状态回填为关", HOST_SPIN_STATE, 0);

    /* 4) 再开 —— 原方案在这里会把自转关掉，语义完全反了 */
    host_tick(1030); host_send(HOST_SPIN_CMD_ON, 1030);
    usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("再开自转", ch.spin_flag, 1);

    /* 5) 上位机掉线：停止强制，spin_flag 保持原值，控制权还给遥控器 */
    host_tick(5000);   /* 距上次指令已远超 150ms */
    usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("掉线后收回为NONE", HOST_SPIN_CMD, HOST_SPIN_CMD_NONE);
    expect("掉线不主动停转（防御姿态维持）", ch.spin_flag, 1);

    /* 6) 掉线期间物理遥控器仍可翻转 spin_flag，桥接不得覆盖 */
    ch.spin_flag = 0;   /* 模拟驾驶员用遥控器关掉 */
    host_tick(5010); usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("掉线时遥控器操作被尊重", ch.spin_flag, 0);

    /* 7) 未知指令值不得误动作 */
    host_tick(6000); host_send(0x7F, 6000);
    usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("未知值不干预", ch.spin_flag, 0);

    /* 8) tick 回绕（HAL_GetTick 约 49.7 天溢出）时新鲜度判断仍正确 */
    host_tick(10); host_send(HOST_SPIN_CMD_ON, 0xFFFFFFF0u);
    usb_get_chassis_cmd(); HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("tick回绕后仍判为新鲜", ch.spin_flag, 1);

    /* 9) 底盘模式与自检位如实回传 */
    ch.mode = 3; ch.sc_flag = 1;
    HOST_CHASSIS_BRIDGE_APPLY(&ch);
    expect("模式回传", HOST_CHASSIS_MODE, 3);
    expect("自检位回传", HOST_CHASSIS_SC_FLAG, 1);

    if (failures) {{ printf("BEHAVIOR FAILURES: %d\\n", failures); return 1; }}
    printf("BEHAVIOR OK (9 groups)\\n");
    return 0;
}}
"""
        with tempfile.TemporaryDirectory() as td:
            cpath = Path(td) / "bridge_behavior.c"
            epath = Path(td) / "bridge_behavior.exe"
            cpath.write_text(behav, encoding="utf-8")
            build = subprocess.run(
                [sys.executable, "-m", "ziglang", "cc", "-O0", "-Wall", "-Wextra",
                 "-o", str(epath), str(cpath)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            check("行为校验程序编译通过", build.returncode == 0,
                  (build.stderr or "")[-400:])
            if build.returncode == 0:
                run = subprocess.run([str(epath)], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace")
                body = ((run.stdout or "") + (run.stderr or "")).strip()
                check("行为校验：开→保持→关→再开→掉线→遥控器接管 全部正确",
                      run.returncode == 0, body[-400:])

    finally:
        if owns_revert:
            # 按字节还原：原本没有的头文件会被删掉，所以不会留下"陈旧副本"
            bf.restore(SNAPSHOT, REPO)

    print("\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for name in FAILED:
            print(f"  - {name[:120]}")
        return 1
    print("ALL HOST-BRIDGE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
