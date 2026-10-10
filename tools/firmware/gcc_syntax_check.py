#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""armcc 不可用时的离线语法体检工具（差分模式）。

用途
----
本机没有 Keil/ARMCC 时，用 GCC(arm-none-eabi) 对整个固件工程做
-fsyntax-only 检查，并且**只比较打补丁前后的诊断差集**。
基线代码本身的噪音（Keil 专有语法、RVDS 端口、newlib 与 struct_typedef.h
的 int32_t 冲突）在差分里会互相抵消，剩下的才是补丁引入的真问题。

这不是 ARMCC 的等价物：
  * 查不出 AC5 独有问题（例如 _Static_assert 在 --c99 下不被 AC5 接受）；
    这一类靠"补丁规范"里的人工规则守（见 GAPS.md §8）。
  * 反之 GCC 会额外报一些 AC5 不报的错，所以差分结果为空 != Keil 一定能过。

用法
----
  python gcc_syntax_check.py <StandardRobotpp目录> [--gcc 路径] [--out 文件]

差分：
  python gcc_syntax_check.py <补丁树> --baseline <基线树>
"""
import argparse
import os
import re
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
# shim 目录随仓库走：换机器只需要 GCC 本体，不用再手搭替身头文件。
SHIM = os.environ.get("POLAR_GCC_SHIM", str(Path(HERE) / "gcc_shim"))
DEFAULT_GCC = os.environ.get(
    "POLAR_GCC",
    r"D:\toolchain\gx\xpack-arm-none-eabi-gcc-15.2.1-1.1\bin\arm-none-eabi-gcc.exe",
)

# 用 RVDS 汇编写的端口文件 GCC 解析不了，交给 shim/portmacro.h 替身
EXCLUDE_BASENAMES = {"port.c"}


def parse_uvprojx(uvprojx):
    """从 Keil 工程文件里取 include 目录、宏定义与全部 .c 源文件。"""
    tree = ET.parse(uvprojx)
    root = tree.getroot()
    inc_dirs, defines, sources = [], [], []
    for node in root.iter():
        tag = node.tag.lower()
        text = (node.text or "").strip()
        if tag == "includepath" and text:
            inc_dirs += [p for p in text.split(";") if p]
        elif tag == "define" and text:
            defines += [d for d in text.split(",") if d]
        elif tag == "filepath" and text.lower().endswith(".c"):
            sources.append(text)
    project_dir = os.path.dirname(os.path.abspath(uvprojx))
    norm = lambda p: os.path.normpath(os.path.join(project_dir, p.replace("\\", "/")))
    return ([norm(p) for p in dict.fromkeys(inc_dirs)],
            [d for d in dict.fromkeys(defines) if d != "__CC_ARM"],
            [norm(p) for p in dict.fromkeys(sources)])


def build_cmd(gcc, root, incs, defines, sources):
    cmd = [gcc, "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16",
           "-mfloat-abi=hard", "-std=gnu99", "-fsyntax-only", "-fno-builtin",
           "-w", "-Werror=implicit-function-declaration",
           "-Wno-builtin-macro-redefined",
           # newlib 的 int32_t 是 long，固件自己的 struct_typedef.h 是 int；
           # 对齐成 int，消除基线噪音
           "-D__int32_t=int", "-D__uint32_t=unsigned int",
           "-D__int64_t=long long int", "-D__uint64_t=unsigned long long int",
           "-D__CC_ARM_CHECK=0", "-include", os.path.join(SHIM, "keil_compat.h")]
    # shim 目录必须排在 RVDS 之前，才能顶掉 portmacro.h
    cmd += ["-I", SHIM]
    cmd += [a for p in incs if os.path.isdir(p) for a in ("-I", p)]
    cmd += ["-D" + d for d in defines]
    cmd += [p for p in sources if os.path.isfile(p)
            and os.path.basename(p) not in EXCLUDE_BASENAMES]
    return cmd


def run(gcc, root):
    uvprojx = os.path.join(root, "MDK-ARM", "standard_robot.uvprojx")
    if not os.path.isfile(uvprojx):
        cands = [f for f in os.listdir(os.path.join(root, "MDK-ARM"))
                 if f.endswith(".uvprojx")]
        uvprojx = os.path.join(root, "MDK-ARM", cands[0])
    incs, defines, sources = parse_uvprojx(uvprojx)
    cmd = build_cmd(gcc, root, incs, defines, sources)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.stderr or "", len(cmd) - cmd.index(sources[0]) if sources else 0



# 基线宏 `LAST_SEND_TIME.##send_name` 会让 GCC 报"pasting ... 不是合法的预处理
# token"，消息里带着字段名。补丁新增一个字段就多一条新消息，看着像新增诊断，
# 其实和基线同一回事（AC5 对这条是容忍的，否则整个工程都编不过）。
# 所以把引号里的标识符抹平成 NAME，让这类诊断归并成一条。
FOLD_PASTE = re.compile(r"pasting .* does not give a valid preprocessing token")
DIAG = re.compile(r"^(.+?):(\d+):(\d+): (error|warning): (.+)$")


def normalize(diag_text, root):
    """去掉绝对路径行号等易变信息，只留下"哪个文件的哪句诊断"。"""
    root_norm = os.path.normpath(os.path.abspath(root)).replace("\\", "/").lower()
    out = set()
    for line in diag_text.splitlines():
        m = DIAG.match(line.strip())
        if not m:
            continue
        f, _ln, _col, kind, msg = m.groups()
        f_norm = os.path.normpath(f).replace("\\", "/").lower()
        # 工具链/系统头文件的抱怨算基线噪音，不参与差分
        if "toolchain" in f_norm or "/include/" in f_norm and root_norm not in f_norm:
            continue
        rel = os.path.relpath(f_norm, root_norm).replace("\\", "/") if f_norm.startswith(root_norm) else f_norm
        msg = re.sub(r"\s+", " ", msg.strip())
        if FOLD_PASTE.search(msg):
            msg = re.sub(r"\"[^\"]*\"", "NAME", msg)
        out.add("%s|%s|%s" % (rel, kind, msg))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree", help="固件工程根目录（含 MDK-ARM/*.uvprojx）")
    ap.add_argument("--baseline", help="基线树（同一仓库未打补丁的副本），做差分时使用")
    ap.add_argument("--gcc", default=DEFAULT_GCC)
    ap.add_argument("--out", default=None, help="把原始诊断写到该文件")
    args = ap.parse_args()

    for p in (args.gcc, args.tree):
        if not os.path.exists(p):
            print("[FAIL] 路径不存在: %s" % p, file=sys.stderr)
            return 2

    text, n = run(args.gcc, args.tree)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    cur = normalize(text, args.tree)
    print("[info] 翻译单元约 %d 个；本次诊断 %d 条" % (n, len(cur)))

    if not args.baseline:
        for d in sorted(cur):
            print("  " + d)
        return 0 if not cur else 1

    btext, _ = run(args.gcc, args.baseline)
    base = normalize(btext, args.baseline)
    new = sorted(cur - base)
    fixed = sorted(base - cur)
    print("[info] 基线诊断 %d 条 / 补丁后 %d 条" % (len(base), len(cur)))
    print("=== 补丁新增的诊断 (%d) ===" % len(new))
    for d in new:
        print("  NEW  " + d)
    print("=== 补丁消除的诊断 (%d) ===" % len(fixed))
    for d in fixed:
        print("  GONE " + d)
    if new:
        print("[RESULT] FAIL - 补丁引入了新的诊断，Keil 大概率编不过")
        return 1
    print("[RESULT] PASS - 补丁未引入新诊断（注意：不等于 ARMCC 保证通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
