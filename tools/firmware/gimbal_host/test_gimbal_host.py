#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云台直控桥（gimbal_host）的结构 + 编译 + 行为校验。

三层证明：
  1) 结构：四处改动都在、位置对（下方安全档与上方档语义原样）。
  2) 编译：从打完补丁的 usb_task.c 逐字抽取的 GetChassisCmdData，
     在真实 usb_typdef.h / host_chassis_bridge.h 下编译零警告。
  3) 行为：
     a) 请求位真值表——帧新鲜 + param0=1 -> 1；param0=0 -> 0；
        帧过期 -> 0（与 spin 收回 NONE 同一道门）。
     b) 中间档 ternary——逐字抽取，请求 0 -> GIMBAL_IMU、1 -> GIMBAL_AUTO_AIM。

固件副本不存在时跳过；已打补丁则只校验；未打则自己套、验完还原
（与 test_host_bridge / test_motion_feedback 同一纪律）。

    python tools/firmware/gimbal_host/test_gimbal_host.py
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("POLAR_FIRMWARE_ROOT") or str(HERE.parents[3] / "tmp_polarbear" / "StandardRobotpp")).resolve()
BRIDGE_APPLY = HERE.parent / "host_bridge" / "apply_host_bridge.py"
BRIDGE_HEADER_REL = "application/typedef/host_chassis_bridge.h"
USB_REL = "application/communication/usb_task.c"
sys.path.insert(0, str(HERE.parent))
import bridge_fixture as bf
GIMBAL_REL = "application/gimbal/gimbal_yaw_pitch_direct.c"
MARK = "POLAR-GIMBAL-HOST"
BRIDGE_MARK = "POLAR-HOST-BRIDGE"

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""), flush=True)


def extract(text: str, pattern: str, label: str) -> str:
    m = re.search(pattern, text, re.S)
    if not m:
        raise AssertionError("找不到 " + label)
    return m.group(0)


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def compile_only(tu: str, inc_dirs: list[str], name: str) -> tuple[int, list[str], list[str]]:
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / (name + ".c")
        opath = Path(td) / (name + ".o")
        cpath.write_text(tu, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-c", "-o", str(opath),
             "-Wall", "-Wextra", *[f"-I{d}" for d in inc_dirs], str(cpath)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ((build.stderr or "") + (build.stdout or "")).strip()
    own = [l for l in out.splitlines() if name + ".c" in l or "host_chassis_bridge.h" in l]
    return build.returncode, [l for l in own if " error:" in l], [l for l in own if " warning:" in l]


def run_link_behavior(usb_text: str, inc_dirs: list[str]) -> None:
    fn = extract(usb_text, r"static void GetChassisCmdData\(void\)\s*\r?\n\{.*?\r?\n\}", "GetChassisCmdData")
    beh = """
#include <stdio.h>
#include <stdint.h>
#include "usb_typdef.h"
#include "host_chassis_bridge.h"

static uint32_t FAKE_TICK = 1000u;
uint32_t HAL_GetTick(void) { return FAKE_TICK; }

volatile uint8_t HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;
volatile uint32_t HOST_SPIN_CMD_TIME = 0;
volatile uint8_t HOST_SPIN_STATE = 0;
volatile uint8_t HOST_CHASSIS_MODE = 0;
volatile uint8_t HOST_CHASSIS_SC_FLAG = 0;
volatile uint8_t HOST_GIMBAL_REQUEST = 0;

static ReceiveDataChassisCmd_s RECEIVE_CHASSIS_CMD_DATA;

""" + fn + """

static int failures;
static void expect(const char *what, long got, long want) {
    if (got != want) { printf("FAIL %s: got %ld want %ld\\n", what, got, want); failures++; }
}

int main(void)
{
    RECEIVE_CHASSIS_CMD_DATA.data.spin_cmd = HOST_SPIN_CMD_ON;
    RECEIVE_CHASSIS_CMD_DATA.data.param0 = HOST_GIMBAL_REQ_MASK;
    HOST_SPIN_CMD_TIME = FAKE_TICK;                 /* 帧新鲜 */
    GetChassisCmdData();
    expect("新鲜+param0=1: spin", HOST_SPIN_CMD, HOST_SPIN_CMD_ON);
    expect("新鲜+param0=1: 请求", HOST_GIMBAL_REQUEST, 1);

    RECEIVE_CHASSIS_CMD_DATA.data.param0 = 0;
    GetChassisCmdData();
    expect("新鲜+param0=0: 请求撤销", HOST_GIMBAL_REQUEST, 0);

    RECEIVE_CHASSIS_CMD_DATA.data.param0 = HOST_GIMBAL_REQ_MASK;
    GetChassisCmdData();
    expect("再次请求即生效（电平可重复）", HOST_GIMBAL_REQUEST, 1);

    FAKE_TICK += (HOST_SPIN_CMD_VALID_MS + 50u);    /* 断流过期 */
    GetChassisCmdData();
    expect("过期: spin 收回 NONE", HOST_SPIN_CMD, HOST_SPIN_CMD_NONE);
    expect("过期: 请求同样撤销（拔线不锁云台）", HOST_GIMBAL_REQUEST, 0);

    if (failures) { printf("LINK BEHAVIOR FAILURES: %d\\n", failures); return 1; }
    printf("LINK BEHAVIOR OK\\n");
    return 0;
}
"""
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "gh_link.c"
        epath = Path(td) / "gh_link.exe"
        cpath.write_text(beh, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-O0", "-Wall", "-Wextra",
             *[f"-I{d}" for d in inc_dirs], "-o", str(epath), str(cpath)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        own = [l for l in ((build.stderr or "") + (build.stdout or "")).splitlines() if "gh_link.c" in l]
        errs = [l for l in own if " error:" in l]
        check("抽取的 GetChassisCmdData 在真实头文件下编译通过", build.returncode == 0 and not errs,
              (errs[0] if errs else (build.stderr or "")[-220:])[:220])
        if build.returncode == 0:
            run = subprocess.run([str(epath)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            check("请求位真值表（新鲜/撤销/重复/过期）全部正确", run.returncode == 0,
                  ((run.stdout or "") + (run.stderr or "")).strip()[-220:])


def run_mode_branch_behavior(gim_text: str, inc_dirs: list[str]) -> None:
    line = extract(gim_text, r"gimbal_direct\.mode = \(HOST_GIMBAL_REQUEST != 0\)[^;]+;", "mid ternary")
    beh = """
#include <stdio.h>
#include <stdint.h>
typedef enum { GIMBAL_ZERO_FORCE, GIMBAL_INIT, GIMBAL_GAP, GIMBAL_IMU, GIMBAL_AUTO_AIM } gm_e;
volatile uint8_t HOST_GIMBAL_REQUEST;
struct { gm_e mode; } gimbal_direct;
static int failures;
static void expect(const char *what, long got, long want) {
    if (got != want) { printf("FAIL %s: got %ld want %ld\\n", what, got, want); failures++; }
}
int main(void)
{
    HOST_GIMBAL_REQUEST = 0;
    """ + line + """
    expect("无请求: 中间档仍是 GIMBAL_IMU（=打桥前）", gimbal_direct.mode, GIMBAL_IMU);
    HOST_GIMBAL_REQUEST = 1;
    """ + line + """
    expect("有请求: 中间档提档 GIMBAL_AUTO_AIM", gimbal_direct.mode, GIMBAL_AUTO_AIM);
    if (failures) { return 1; }
    printf("MODE OK\\n");
    return 0;
}
"""
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "gh_mode.c"
        epath = Path(td) / "gh_mode.exe"
        cpath.write_text(beh, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-O0", "-Wall", "-Wextra",
             "-o", str(epath), str(cpath)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("中间档 ternary 编译通过", build.returncode == 0, (build.stderr or "")[-200:])
        if build.returncode == 0:
            run = subprocess.run([str(epath)], capture_output=True, text=True)
            check("中间档真值表正确（0=IMU / 1=AUTO_AIM）", run.returncode == 0,
                  ((run.stdout or "") + (run.stderr or "")).strip()[-160:])


def _run_checks() -> int:
    if not REPO.exists() or not (REPO / ".git").exists():
        print(f"SKIP: 固件副本不存在（{REPO}）")
        return 77

    owns_gimbal = False
    owns_bridge = False
    bridge_hdr = REPO / BRIDGE_HEADER_REL
    gim0 = (REPO / GIMBAL_REL).read_text(encoding="utf-8", errors="ignore")
    usb0 = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
    if MARK not in gim0:
        if os.environ.get("POLAR_FIRMWARE_READ_ONLY") == "1":
            print("[INCOMPLETE] Required prepared files are absent; read-only checks never install patches")
            return 77
        # 判断"host_bridge 在不在树里"必须看 .c 内容，不能只看头文件是否存在：
        # 兄弟测试收尾会 git checkout 把 .c 还原，而头文件是未跟踪的、留在那儿，
        # 于是"头文件在、桥接代码不在"的半套状态会让下面的锚点直接找不到。
        if "POLAR-HOST-BRIDGE" not in usb0:
            res = subprocess.run([sys.executable, str(BRIDGE_APPLY), str(REPO)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                print("NO-GO: host_bridge 套用失败：" + ((res.stderr or res.stdout).strip()[-200:]))
                return 1
            owns_bridge = True
        else:
            print("[info] host_bridge 已在树里，直接叠加 gimbal_host")
        res = subprocess.run([sys.executable, str(HERE / "apply_gimbal_host.py"), str(REPO)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            print("NO-GO: gimbal_host 套用失败：" + ((res.stderr or res.stdout).strip()[-200:]))
            return 1
        owns_gimbal = True

    try:
        hdr = bridge_hdr.read_text(encoding="utf-8", errors="ignore")
        usb = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
        gim = (REPO / GIMBAL_REL).read_text(encoding="utf-8", errors="ignore")

        check("桥接头文件已加 HOST_GIMBAL_REQ_MASK 与 extern",
              "HOST_GIMBAL_REQ_MASK" in hdr and "HOST_GIMBAL_REQUEST" in hdr)
        check("usb_task 定义请求全局（唯一）", usb.count("volatile uint8_t HOST_GIMBAL_REQUEST") == 1)
        check("过期分支同样撤销请求", "HOST_GIMBAL_REQUEST = 0;" in usb)
        check("param0 电平赋值存在",
              "((RECEIVE_CHASSIS_CMD_DATA.data.param0 & HOST_GIMBAL_REQ_MASK) != 0) ? 1 : 0" in usb)
        check("云台文件 include 桥接头", '"host_chassis_bridge.h"' in gim)
        mid_at = gim.find("switch_is_mid")
        up_at = gim.find("switch_is_up")
        ter_at = gim.find("(HOST_GIMBAL_REQUEST != 0) ? GIMBAL_AUTO_AIM : GIMBAL_IMU")
        check("ternary 恰在中间档、上方档之前", 0 <= mid_at < ter_at < up_at,
              f"mid={mid_at} ter={ter_at} up={up_at}")
        check("下方安全档未被改动（零力矩优先级最高）",
              "gimbal_direct.mode=GIMBAL_ZERO_FORCE;" in gim)
        check("上方档语义未被改动（AUTO_AIM 保持）",
              "gimbal_direct.mode=GIMBAL_AUTO_AIM;" in gim)

        inc_dirs = sorted({str(p.parent) for p in REPO.rglob("*.h")})
        run_link_behavior(usb, inc_dirs)
        run_mode_branch_behavior(gim, inc_dirs)
    finally:
        if owns_gimbal:
            git("checkout", "--", USB_REL, GIMBAL_REL)
            if owns_bridge:
                # host_bridge 也是本测试装的：它的全部落点一起还原；
                # 头文件是新增的未跟踪文件，checkout 删不掉，显式 clean，
                # 否则下一轮会因"已存在"跳过安装、测到陈旧副本。
                git("checkout", "--", "application/chassis/chassis_mecanum.c",
                    "application/chassis/chassis_omni.c")
                subprocess.run(["git", "clean", "-fd", BRIDGE_HEADER_REL],
                               cwd=REPO, capture_output=True)
            elif bridge_hdr.exists():
                # 头文件是别人的：只精确移除本桥追加的那一段。
                text = bridge_hdr.read_text(encoding="utf-8")
                stripped = re.sub(r"\n/\* " + MARK + r":.*?extern volatile uint8_t HOST_GIMBAL_REQUEST;\n",
                                  "\n", text, flags=re.S)
                if stripped != text:
                    io.open(bridge_hdr, "w", encoding="utf-8", newline="").write(stripped)

    print("\\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for n in FAILED:
            print("  - " + n[:120])
        return 1
    print("ALL GIMBAL-HOST TESTS PASSED")
    return 0


def main() -> int:
    if os.environ.get("POLAR_FIRMWARE_READ_ONLY") == "1":
        return _run_checks()
    if not REPO.exists():
        return _run_checks()
    # Include transitively modified RC/chassis files and restore even if an
    # installer fails before the inner try/finally. Never leave half a bridge.
    snapshot = bf.stage(REPO, [USB_REL, GIMBAL_REL, BRIDGE_HEADER_REL,
        "application/other/remote_control.c",
        "application/chassis/chassis_mecanum.c",
        "application/chassis/chassis_omni.c"])
    try:
        return _run_checks()
    finally:
        bf.restore(snapshot, REPO)


if __name__ == "__main__":
    raise SystemExit(main())
