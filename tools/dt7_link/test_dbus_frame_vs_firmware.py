#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用固件里**真实的** sbus_to_rc() 验 dt7_dbus_frame.py 的编码。

为什么不能只自测
----------------
自测只能证明"我自己和我自己一致"。真正要证明的是：**按官方手册打出来的
18 字节，到了车上单片机会不会被解成我以为的那个值**。所以这里把固件
application/other/remote_control.c 里的 sbus_to_rc() 函数体原样抽出来，
连 application/typedef/*.h + remote_control.h 的真实头文件一起编成 exe，
拿 Python 生成的帧去喂它，逐字段比对。写错位序会当场报错。

顺带守一件更容易出事的事：固件里的键位 bit 序 / 通道中值 / 帧长一旦改了，
本模块的常量就得跟着改，否则编码会和固件悄悄错开 -> 这些都用断言钉住。

用法
----
    python tools/dt7_link/test_dbus_frame_vs_firmware.py [固件仓库根目录]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dt7_dbus_frame as df  # noqa: E402

DEFAULT_REPO = HERE.parents[2] / "tmp_polarbear" / "StandardRobotpp"
RC_C = "application/other/remote_control.c"
RC_H = "application/other/remote_control.h"

FAILED = False


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED = True


def extract(text: str, pattern: str, label: str) -> str:
    m = re.search(pattern, text, re.S)
    if not m:
        raise RuntimeError(f"抽不到 {label}（锚点 {pattern!r}）")
    return m.group(0)


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_REPO
    rc_path, hdr_path = root / RC_C, root / RC_H
    if not rc_path.exists() or not hdr_path.exists():
        print(f"SKIP: 找不到固件源码（{rc_path}）")
        return 0

    rc = rc_path.read_text(encoding="utf-8", errors="ignore")
    hdr = hdr_path.read_text(encoding="utf-8", errors="ignore")

    body = extract(
        rc,
        r"static void sbus_to_rc\(volatile const uint8_t \*sbus_buf, "
        r"RC_ctrl_t \*rc_ctrl\)\s*\n\{.*?\n\}\n",
        "sbus_to_rc 函数体")

    # 常量守卫：固件一旦改位序/中值/帧长，这里先红，而不是等到车上出问题
    for label, pat, want in (
        ("RC_CH_VALUE_OFFSET", r"RC_CH_VALUE_OFFSET\s+\(\(uint16_t\)(\d+)\)", df.CH_MID),
        ("RC_FRAME_LENGTH", r"#define\s+RC_FRAME_LENGTH\s+(\d+)u", df.FRAME_LEN),
        ("KEY_W", r"#define\s+KEY_W\s+\(\(uint8_t\)(\d+)\)", 0),
        ("KEY_S", r"#define\s+KEY_S\s+\(\(uint8_t\)(\d+)\)", 1),
        ("KEY_A", r"#define\s+KEY_A\s+\(\(uint8_t\)(\d+)\)", 2),
        ("KEY_D", r"#define\s+KEY_D\s+\(\(uint8_t\)(\d+)\)", 3),
        ("KEY_SHIFT", r"#define\s+KEY_SHIFT\s+\(\(uint8_t\)(\d+)\)", 4),
        ("KEY_CTRL", r"#define\s+KEY_CTRL\s+\(\(uint8_t\)(\d+)\)", 5),
        ("KEY_Q", r"#define\s+KEY_Q\s+\(\(uint8_t\)(\d+)\)", 6),
        ("KEY_E", r"#define\s+KEY_E\s+\(\(uint8_t\)(\d+)\)", 7),
    ):
        m = re.search(pat, hdr)
        got = m.group(1) if m else "锚点未找到"
        check(f"固件常量 {label} == {want}（改了必须同步 dt7_dbus_frame）",
              bool(m) and int(m.group(1)) == want, f"实际 {got}")

    # 记账两行是 POLAR-HOST-BRIDGE 补丁注入的，本测试自己提供同语义的账量
    bridge = "HOST_RC_DRIVER_KEYS" in body
    tu_head = """
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "remote_control.h"       /* RC_ctrl_t / KEY_xxx / RC_CH_VALUE_OFFSET 真实定义 */

/* 这两个账量在固件里定义于 usb_task.c；测试按同样语义复刻，
 * 好让抽出来的 sbus_to_rc() 一字不改就能编过。 */
volatile uint16_t HOST_RC_DRIVER_KEYS = 0;
volatile uint16_t HOST_RC_HOST_KEYS = 0;
#define HOST_RC_MERGED_KEYS() ((uint16_t)(HOST_RC_DRIVER_KEYS | HOST_RC_HOST_KEYS))

static RC_ctrl_t g_rc;

"""
    tu = tu_head + "/* ==== 以下为固件原文，一字未改 ==== */\n" + body + r"""
int main(int argc, char **argv)
{
    uint8_t f[18];
    int i;
    if (argc < 2) { printf("usage: exe HEX\n"); return 2; }
    for (i = 0; i < 18; i++) {
        unsigned int b;
        sscanf(argv[1] + i * 2, "%02x", &b);
        f[i] = (uint8_t)b;
    }
    memset(&g_rc, 0, sizeof(g_rc));
    HOST_RC_DRIVER_KEYS = 0;
    HOST_RC_HOST_KEYS = 0;
    sbus_to_rc((volatile const uint8_t *)f, &g_rc);
    printf("{\"ch0\":%d,\"ch1\":%d,\"ch2\":%d,\"ch3\":%d,\"s0\":%d,\"s1\":%d,"
           "\"mx\":%d,\"my\":%d,\"mz\":%d,\"pl\":%d,\"pr\":%d,\"key\":%u}\n",
           g_rc.rc.ch[0], g_rc.rc.ch[1], g_rc.rc.ch[2], g_rc.rc.ch[3],
           g_rc.rc.s[0], g_rc.rc.s[1],
           g_rc.mouse.x, g_rc.mouse.y, g_rc.mouse.z,
           g_rc.mouse.press_l, g_rc.mouse.press_r,
           (unsigned)g_rc.key.v);
    return 0;
}
"""

    inc_dirs = sorted({str(p.parent) for p in root.rglob("*.h")})
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "fw_decode.c"
        epath = Path(td) / "fw_decode.exe"
        cpath.write_text(tu, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-O0", "-w",
             "-o", str(epath), str(cpath)] + [f"-I{d}" for d in inc_dirs],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("固件真实解码函数编成 exe 成功", build.returncode == 0,
              ((build.stderr or "") + (build.stdout or ""))[-500:])
        if build.returncode != 0:
            return 1

        cases = [
            ("中位摇杆+中拨杆+无键鼠", dict()),
            ("W 前进", dict(keys=df.keys_to_bits(["W"]))),
            ("S+A 平移", dict(keys=df.keys_to_bits(["S", "A"]))),
            ("SHIFT 小陀螺（固件位序 bit4）", dict(keys=df.keys_to_bits(["SHIFT"]))),
            ("鼠标 dx=+120 dy=-45 左键按下", dict(mouse=(120, -45, 0), buttons=(1, 0))),
            ("滚轮 +7 右键按下", dict(mouse=(0, 0, 7), buttons=(0, 1))),
            ("四通道推到最大", dict(channels=[df.CH_MAX] * 4)),
            ("四通道拉到最小", dict(channels=[df.CH_MIN] * 4)),
            ("S1 上 / S2 下", dict(s1=df.SW_UP, s2=df.SW_DOWN)),
            ("极端负位移", dict(mouse=(-32768, -32768, -32768))),
            ("全键按下 0xFFFF", dict(keys=0xFFFF)),
        ]
        for label, kw in cases:
            frame = df.encode_frame(**kw)
            run = subprocess.run([str(epath), frame.hex()], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            if run.returncode != 0:
                check(label, False, (run.stderr or run.stdout)[-200:])
                continue
            got = json.loads(run.stdout.strip())
            w = df.decode_frame(frame)
            exp = {"ch0": w["ch"][0] - df.CH_MID, "ch1": w["ch"][1] - df.CH_MID,
                   "ch2": w["ch"][2] - df.CH_MID, "ch3": w["ch"][3] - df.CH_MID,
                   "s0": w["s"][0], "s1": w["s"][1],
                   "mx": w["mouse"]["x"], "my": w["mouse"]["y"], "mz": w["mouse"]["z"],
                   "pl": w["mouse"]["press_l"], "pr": w["mouse"]["press_r"],
                   "key": w["key_v"]}
            # 打了 POLAR-HOST-BRIDGE 的树里，key.v 是"合并值"，账量初值 0 -> 等价
            if bridge:
                exp["key"] = w["key_v"]
            check(f"固件解出与编码逐字段一致：{label}", got == exp,
                  "" if got == exp else f"\n      固件={got}\n      期望={exp}")

        f_fw = df.encode_frame(keys=df.keys_to_bits(["SHIFT"], "fw"))
        f_2016 = df.encode_frame(keys=df.keys_to_bits(["SHIFT"], "dji2016"))
        check("两套官方键位位序产生不同帧（所以必须现场定死 DT7 用哪套）",
              f_fw != f_2016, f"\n      fw      ={f_fw.hex(' ')}\n      dji2016 ={f_2016.hex(' ')}")
        check("W/S/A/D 在两套位序里完全相同（解释错位为何一直没被发现）",
              df.keys_to_bits(["W", "S", "A", "D"], "fw")
              == df.keys_to_bits(["W", "S", "A", "D"], "dji2016"))

    print("\n" + "=" * 62)
    print("有失败项" if FAILED else "官方手册位序 == 固件真实解码结果，逐字段核对通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
