#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0x1E 速度回读补丁的编译 + 行为校验（motion_feedback）。

三层证明，逐层变强：
  1) 结构：三个文件的改动都在、位置对（Observer 每帧刷新、任务启动即注册）。
  2) 编译：从**打完补丁的固件源文件里逐字抽取**的公式，在真实
     struct_typedef.h / custom_typedef.h / usb_typdef.h 环境下编译零警告。
  3) 行为：麦轮与全向轮各跑**运动学往返**——用固件自己的下发式
     ChassisConsole（同样逐字抽取）算出四轮指令速度，令实测轮速恰好等于它，
     再跑反解，断言机体系速度还原回输入值（1e-4 内）。
     往返的两个方向都来自**同一份源码文本**，符号/系数错一个就红。

跑法：
    python tools/firmware/motion_feedback/test_motion_feedback.py

固件副本不存在时跳过（返回 0）。副本存在但还没打补丁时，本测试会
自己调用 apply_motion_feedback.py 装上、校验完再还原（与 test_host_bridge
同一套"拥有则还原"纪律，不把工作树弄脏）。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3] / "tmp_polarbear" / "StandardRobotpp"
MECA_REL = "application/chassis/chassis_mecanum.c"
OMNI_REL = "application/chassis/chassis_omni.c"
USB_REL = "application/communication/usb_task.c"
MARK = "POLAR-MOTION-FEEDBACK"

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""), flush=True)


def extract(text: str, pattern: str, label: str) -> str:
    m = re.search(pattern, text, re.S)
    if not m:
        raise AssertionError(f"在打完补丁的源文件里找不到 {label}")
    return m.group(0)


def findall(text: str, pattern: str, label: str, expect_n: int) -> list[str]:
    rows = re.findall(pattern, text)
    if len(rows) != expect_n:
        raise AssertionError(f"{label} 期望 {expect_n} 条，实际 {len(rows)}")
    return rows


MIRROR = r'''
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "struct_typedef.h"
#include "custom_typedef.h"

#define WHEEL_RADIUS            0.0725f
#define WHEEL_CENTER_DISTANCE   0.1275f

static struct {
    struct { struct { fp32 vel; } fdb; fp32 reduction_ratio; int8_t direction; } wheel[4];
    fp32 feedback[4];
    fp32 set[4];
    struct { fp32 vx, vy, wz; } reference;
} chassis;

static ChassisSpeedVector_t chassis_fdb_speed;   /* 与补丁里同名同型 */
static char published_name[32];
static int publish_calls;

uint8_t Publish(void *address, char *name)
{
    (void)address;
    strcpy(published_name, name);
    publish_calls++;
    return 1;
}
'''

MAIN = r'''
static int failures;

static void near(const char *what, double got, double want)
{
    if (got - want > 1e-4 || got - want < -1e-4) {
        printf("FAIL %s: got %.6f want %.6f\n", what, got, want);
        failures++;
    }
}

static void roundtrip(const char *tag, fp32 vx, fp32 vy, fp32 wz)
{
    chassis.reference.vx = vx;
    chassis.reference.vy = vy;
    chassis.reference.wz = wz;
    __SET_LINES__
    for (int i = 0; i < 4; ++i) {
        chassis.feedback[i] = chassis.set[i];   /* 轮子完美跟随指令 */
    }
    ChassisPublish();
    near(tag, chassis_fdb_speed.vx, vx);
    near(tag, chassis_fdb_speed.vy, vy);
    near(tag, chassis_fdb_speed.wz, wz);
}

int main(void)
{
    const fp32 ratios[4] = { 36.0f, 36.0f, 42.0f, 42.0f };
    const int8_t dirs[4] = { -1, 1, -1, 1 };
    for (int i = 0; i < 4; ++i) {
        chassis.wheel[i].reduction_ratio = ratios[i];
        chassis.wheel[i].direction = dirs[i];
    }
    roundtrip("往返1", 1.5f, -0.7f, 0.9f);
    roundtrip("往返2", -2.0f, 1.2f, -0.4f);
    roundtrip("零速", 0.0f, 0.0f, 0.0f);

    if (strcmp(published_name, CHASSIS_FDB_SPEED_NAME) != 0) {
        printf("FAIL 注册名: %s\n", published_name);
        failures++;
    }
    if (failures) { printf("BEHAVIOR FAILURES: %d\n", failures); return 1; }
    printf("BEHAVIOR OK\n");
    return 0;
}
'''


def compile_only(tu: str, inc_dirs: list[str], name: str) -> tuple[int, list[str], list[str]]:
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / f"{name}.c"
        opath = Path(td) / f"{name}.o"
        cpath.write_text(tu, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-c", "-o", str(opath),
             "-Wall", "-Wextra", *[f"-I{d}" for d in inc_dirs], str(cpath)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ((build.stderr or "") + (build.stdout or "")).strip()
    own = [l for l in out.splitlines() if f"{name}.c" in l]
    return build.returncode, [l for l in own if " error:" in l], [l for l in own if " warning:" in l]


def run_chassis_behavior(tag: str, rel: str, inc_dirs: list[str]) -> None:
    text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
    update_fn = extract(text, r"static void chassis_update_fdb_speed\(void\)\s*\r?\n\{.*?\r?\n\}", tag + " update")
    publish_fn = extract(text, r"void ChassisPublish\(void\)\s*\r?\n\{.*?\r?\n\}", tag + " publish")
    set_lines = findall(text, r"[ \t]*(chassis\.set\[\d\] = [^\n]*?;)[ \t]*\r?\n", tag + " ChassisConsole 下发式", 4)
    tu = "\n".join([MIRROR, update_fn, publish_fn,
                    MAIN.replace("__SET_LINES__", "\n".join(x.strip() for x in set_lines))])
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / f"mf_{tag}.c"
        epath = Path(td) / f"mf_{tag}.exe"
        cpath.write_text(tu, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-O0", "-Wall", "-Wextra",
             *[f"-I{d}" for d in inc_dirs], "-o", str(epath), str(cpath)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        own = [l for l in ((build.stderr or "") + (build.stdout or "")).splitlines() if f"mf_{tag}.c" in l]
        errs = [l for l in own if " error:" in l]
        warns = [l for l in own if " warning:" in l]
        check(f"{tag}: 抽取的运动学代码编译通过", build.returncode == 0 and not errs,
              (errs[0] if errs else (build.stderr or "")[-220:])[:220])
        check(f"{tag}: 编译零警告", not warns, warns[0][:180] if warns else "")
        if build.returncode == 0:
            run = subprocess.run([str(epath)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            body = ((run.stdout or "") + (run.stderr or "")).strip()
            check(f"{tag}: 运动学往返断言全部正确", run.returncode == 0, body[-260:])


def run_usb_check(inc_dirs: list[str]) -> None:
    text = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
    fn = extract(text, r"static void UsbSendRobotMotionData\(void\)\s*\r?\n\{.*?\r?\n\}", "usb 0x1E 发送")
    check("usb_task 守卫改为惰性重订阅", "Subscribe(CHASSIS_FDB_SPEED_NAME)" in fn and MARK in fn)
    tu = (
        '#include <string.h>\n#include "struct_typedef.h"\n#include "custom_typedef.h"\n'
        '#include "usb_typdef.h"\n\n'
        "uint32_t HAL_GetTick(void) { return 123u; }\n"
        "void append_CRC16_check_sum(uint8_t *pdata, uint16_t len) { (void)pdata; (void)len; }\n"
        "void USB_Transmit(uint8_t *data, uint16_t len) { (void)data; (void)len; }\n"
        "static ChassisSpeedVector_t g_vec;\n"
        "const void *Subscribe(char *name) { return strcmp(name, CHASSIS_FDB_SPEED_NAME) == 0 ? &g_vec : 0; }\n\n"
        "static const ChassisSpeedVector_t * FDB_SPEED_VECTOR;\n"
        "static SendDataRobotMotion_s SEND_ROBOT_MOTION_DATA;\n\n"
        + fn + "\n"
        "int probe(void);\nint probe(void) { UsbSendRobotMotionData(); return FDB_SPEED_VECTOR == 0; }\n"
    )
    rc, errs, warns = compile_only(tu, inc_dirs, "mf_usb")
    check("usb 发送函数在真实头文件下编译通过", rc == 0 and not errs, (errs[0] if errs else "")[:220])
    check("usb 发送函数编译零警告", not warns, warns[0][:180] if warns else "")


def main() -> int:
    if not REPO.exists() or not (REPO / ".git").exists():
        print(f"SKIP: 固件副本不存在（{REPO}）")
        return 0

    meca = (REPO / MECA_REL).read_text(encoding="utf-8", errors="ignore")
    omni = (REPO / OMNI_REL).read_text(encoding="utf-8", errors="ignore")
    usb = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")
    own_apply = False
    if not (MARK in meca and MARK in omni and MARK in usb):
        res = subprocess.run(
            [sys.executable, str(HERE / "apply_motion_feedback.py"), str(REPO)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            print("NO-GO: 套用补丁失败：" + ((res.stderr or res.stdout).strip()[-300:]))
            return 1
        own_apply = True
        print("[info] 本测试套用了补丁，校验完会还原（树保持干净）")
        meca = (REPO / MECA_REL).read_text(encoding="utf-8", errors="ignore")
        omni = (REPO / OMNI_REL).read_text(encoding="utf-8", errors="ignore")
        usb = (REPO / USB_REL).read_text(encoding="utf-8", errors="ignore")

    # ---------------- 结构校验 ----------------
    for name, text in (("chassis_mecanum.c", meca), ("chassis_omni.c", omni)):
        check(f"{name} 恰有一个强符号 ChassisPublish", text.count("void ChassisPublish(void)") == 1)
        obs = extract(text, r"void ChassisObserver\(void\)\s*\r?\n\{.*?\r?\n\}", name + " observer")
        check(f"{name} Observer 每帧刷新速度回读",
              "chassis_update_fdb_speed();" in obs
              and obs.find("GetGimbalDeltaYawMid") < obs.find("chassis_update_fdb_speed();"),
              "刷新必须排在轮速测量之后")
        check(f"{name} 已 include custom_typedef/data_exchange",
              '"custom_typedef.h"' in text and '"data_exchange.h"' in text)
        upd = extract(text, r"static void chassis_update_fdb_speed\(void\)\s*\r?\n\{.*?\r?\n\}", name + " update")
        check(f"{name} 反解读的是实测 feedback（不是指令 set）",
              "chassis.feedback[" in upd and "chassis.set[" not in upd)
    check("麦轮反解带 direction（与其下发式同系数）",
          extract(meca, r"static void chassis_update_fdb_speed.*?\r?\n\}", "meca update").count(".direction") == 4)
    check("全向轮反解不含 direction（与其下发式一致）",
          ".direction" not in extract(omni, r"static void chassis_update_fdb_speed.*?\r?\n\}", "omni update"))

    try:
        inc_dirs = sorted({str(p.parent) for p in REPO.rglob("*.h")})
        run_chassis_behavior("meca", MECA_REL, inc_dirs)
        run_chassis_behavior("omni", OMNI_REL, inc_dirs)
        run_usb_check(inc_dirs)
    finally:
        if own_apply:
            subprocess.run(["git", "checkout", "--", MECA_REL, OMNI_REL, USB_REL],
                           cwd=REPO, capture_output=True)

    print("\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for n in FAILED:
            print(f"  - {n[:120]}")
        return 1
    print("ALL MOTION-FEEDBACK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
