#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨语言对表：固件 C 结构体 prm1_km_cmd_t 的每个字段偏移，必须和客户端
rm_client/backend/protocol.py 的 struct 格式逐字节一致。

为什么单独一个测试
------------------
客户端用 Python struct 打包，固件用 C `__packed__` 结构体解包。只要有一边
多了对齐填充（或者 __packed__ 没生效、或者有人往中间插了字段），字节就会
整体错位：固件解出来的 keys 其实是 seq，鼠标其实是保留位，而且**双方各自
编译都完全正常**，只有上车才看得见。所以这里把 C 侧真实偏移量出来，
再和 Python 侧对表。

用法
----
    python tools/firmware/km_link/test_km_payload_layout.py [固件根目录]
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
DEFAULT_REPO = HERE.parents[3] / "tmp_polarbear" / "StandardRobotpp"
HDR_REL = "application/typedef/host_km_link.h"

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def main() -> int:
    root = (Path(sys.argv[1]).resolve()
            if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
            else DEFAULT_REPO.resolve())
    hdr = root / HDR_REL
    if not hdr.exists():
        print(f"SKIP: 固件树里还没有 {HDR_REL}（先跑 prepare_hero_build.py）")
        return 0

    text = hdr.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"typedef struct\s*\{.*?\}\s*__packed__ prm1_km_cmd_t;", text, re.S)
    if not m:
        print("[FAIL] 抽不到 prm1_km_cmd_t 定义")
        return 1
    c_struct = m.group(0)
    # 字段名按声明顺序取（类型那两token 之后的标识符）
    fields = re.findall(r"^\s*(?:uint8_t|uint16_t|int16_t)\s+(\w+)", c_struct, re.M)
    check("C 结构体字段全部解析出来", len(fields) == 11, str(fields))

    # 主机侧没有 Keil 的 __packed__，先补一个等价定义；那行占位 dummy 是
    # 多余的，留着反而在定义之前就用到 __packed__ 而编不过。
    tu = """
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#define __packed__ __attribute__((packed))
""" + c_struct + """
#define P(f) printf(#f " %zu %zu\\n", offsetof(prm1_km_cmd_t, f), sizeof(((prm1_km_cmd_t*)0)->f));
int main(void)
{
    printf("TOTAL %zu\\n", sizeof(prm1_km_cmd_t));
    P(magic) P(version) P(kind) P(seq) P(keys)
    P(mouse_x) P(mouse_y) P(mouse_z) P(buttons) P(flags) P(reserved)
    return 0;
}
"""
    inc_dirs = sorted({str(p.parent) for p in root.rglob("*.h")})
    with tempfile.TemporaryDirectory() as td:
        cpath, epath = Path(td) / "layout.c", Path(td) / "layout.exe"
        cpath.write_text(tu, encoding="utf-8")
        build = subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-O0", "-w",
             "-o", str(epath), str(cpath)] + [f"-I{d}" for d in inc_dirs],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("C 布局探针编译通过", build.returncode == 0,
              ((build.stderr or "") + build.stdout)[-500:])
        if build.returncode != 0:
            return 1
        run = subprocess.run([str(epath)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        check("C 布局探针运行成功", run.returncode == 0, run.stderr[-300:])
        got = {}
        total = None
        for line in run.stdout.splitlines():
            parts = line.split()
            if parts[0] == "TOTAL":
                total = int(parts[1])
            else:
                got[parts[0]] = (int(parts[1]), int(parts[2]))

    from rm_client.backend import protocol as pr  # noqa: E402

    check("C sizeof == 客户端声明的 TEAM_CONTROL_KM_SIZE",
          total == pr.TEAM_CONTROL_KM_SIZE, f"C={total} py={pr.TEAM_CONTROL_KM_SIZE}")
    fmt_sizes = {
        "magic": (0, 4), "version": (4, 1), "kind": (5, 1), "seq": (6, 2),
        "keys": (8, 2), "mouse_x": (10, 2), "mouse_y": (12, 2),
        "mouse_z": (14, 2), "buttons": (16, 1), "flags": (17, 1),
        "reserved": (18, 8),
    }
    check("客户端 struct 格式算出的偏移与手写表一致",
          struct.calcsize(pr.TEAM_CONTROL_KM_FORMAT) == pr.TEAM_CONTROL_KM_SIZE,
          f"calcsize={struct.calcsize(pr.TEAM_CONTROL_KM_FORMAT)}")
    for name, (off, size) in fmt_sizes.items():
        check(f"字段 {name} 偏移/大小两端一致（{off},{size}）",
              got.get(name) == (off, size), f"C={got.get(name)}")

    # 端到端：Python 打的包，按 C 的偏移手工读回来
    blob = pr.encode_km_control_payload(sequence=0x1234, keyboard_value=0x001F,
                                        mouse_x=-2, mouse_y=300, mouse_z=-7,
                                        left_button=True, right_button=True,
                                        middle_button=True)
    def rd(off, n, signed=False):
        return int.from_bytes(blob[off:off + n], "little", signed=signed)
    check("Python 包按 C 偏移读回：magic/kind/version",
          blob[0:4] == b"PRM1" and blob[4] == 1 and blob[5] == 3)
    check("Python 包按 C 偏移读回：seq/keys",
          (rd(6, 2), rd(8, 2)) == (0x1234, 0x001F))
    check("Python 包按 C 偏移读回：三个鼠标量（有符号）",
          (rd(10, 2, True), rd(12, 2, True), rd(14, 2, True)) == (-2, 300, -7))
    check("Python 包按 C 偏移读回：三个鼠标键都在 buttons 一个字节里",
          blob[16] == 0x07, f"buttons={blob[16]:#04x}")

    print("\n" + "=" * 62)
    print("有失败项" if FAILED else "C 结构体与客户端打包逐字段对齐")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
