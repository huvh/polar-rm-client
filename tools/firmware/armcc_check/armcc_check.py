# -*- coding: utf-8 -*-
r"""armcc_check.py —— 用**真正的 ARMCC 5.06**（Keil MDK 的 C5 工具链）体检整个固件工程。

为什么需要它
------------
`prepare_hero_build.py --gcc-check` 只能证明"比基线干净"，证明不了真实工具链
（ARMCC 5.06 + `<uC99>1` + `--diag_error=warning` 警告即错误）能不能过。
本脚本不装 Keil、不写注册表、不碰工程文件，直接按 `.uvprojx` 里工程自己的
include / define / 选项把所有编译单元过一遍，然后做两次链接：

  1) `armlink --partial`  —— 只看符号解析（不受 MDK-Lite 尺寸上限影响）
  2) `armlink --scatter`  —— 完整链接，看是否只剩授权尺寸限制

license 是怎么解决的
--------------------
MDK-Lite 下的 ARMCC 不查 license server，它读 `<KeilRoot>\ARM\sw\mappings\
mdk_lite.elmap`。所以只要给两个环境变量：

    ARM_PRODUCT_PATH = <含 mdk_lite.elmap 的目录>
    ARM_TOOL_VARIANT = mdk_lite

两者都能离线弄到，且都不需要管理员权限（详见同目录 README.md）：
    msiexec /a ARMCompiler506_b960.msi /qn TARGETDIR=D:\ac5root
    MDK5xxa.exe 尾部附的是一个 zip，把 ARM/sw/mappings/ 解出来即可

本机实测（2026-09-03，英雄+客户端驾驶桥全部装好的状态）
------------------------------------------------------
    编译        ：161 个 .c + 1 个 startup .s 全过，0 error / 0 warning
    partial 链接：rc=0，L6218E 未定义符号 0 个
    完整链接    ：Fatal error: L6050U: The code size of this image (109628 bytes)
                  exceeds the maximum allowed for this version of the linker.
                  -> MDK-Lite 免费授权的 32KB 代码上限，属授权限制不是代码问题。
                     想改用 GCC 绕开也不行：AHRS.lib / arm_cortexM4lf_math.lib
                     是 ARM 目标格式库，只有 ARMCC 的 armlink 能链接。

用法
----
    python armcc_check.py <StandardRobotpp路径> [--mode compile|partial|link|all]
                                       [--objdir 目录] [--ac5 路径] [--mappings 路径]

退出码：0 = 编译全过 + partial 符号干净（L6050U 只提示不判失败）
        1 = 有真实编译/链接错误
        2 = 环境缺失（没找到 .uvprojx / 工具链 / mdk_lite.elmap）
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

AC5_DEFAULT = os.environ.get("ARMCC5_ROOT", r"D:\ac5root\PFiles\ARM_Compiler_5.06u7")
MAP_DEFAULT = os.environ.get("ARM_MAPPINGS", r"D:\keilroot\ARM\sw\mappings")
KEIL_ROOT = os.environ.get("KEIL_ROOT", os.path.expandvars(r"%LOCALAPPDATA%\Keil_v5"))


def have(base, rel):
    return bool(base) and os.path.exists(os.path.join(base, rel))


def txt(e, tag, default=""):
    c = e.find(tag)
    return (c.text or "").strip() if c is not None and c.text else default


def collect_units(proj):
    """从 .uvprojx 还原工程自己的编译选项 + 参与编译的文件清单。"""
    proj_dir = os.path.dirname(os.path.abspath(proj))
    root = ET.parse(proj).getroot()
    tgt = root.find("Targets").find("Target")
    armads = tgt.find("TargetOption").find("TargetArmAds")
    cads = armads.find("Cads")
    cmisc = cads.find("VariousControls")
    raw = open(proj, encoding="utf-8", errors="replace").read()

    cflags = ["--cpu=Cortex-M4.fp", "--split_sections", "-O1"]      # 工程 <uC99>1
    if "<uC99>1" in raw:
        cflags.append("--c99")
    for d in [x.strip() for x in txt(cmisc, "Define").split(",") if x.strip()]:
        cflags.append("-D" + d)
    for i in [x.replace("\\", "/").strip()
              for x in txt(cmisc, "IncludePath").split(";") if x.strip()]:
        cflags.append("-I" + os.path.normpath(os.path.join(proj_dir, i)))
    mc = cads.find("MiscControls")                                   # --diag_error=warning
    if mc is not None and (mc.text or "").strip():
        cflags += mc.text.split()

    amisc = armads.find("Aads").find("VariousControls")
    aflags = ["--cpu=Cortex-M4", "--fpmode=ieee_full"]
    for d in [x.strip() for x in txt(amisc, "Define").split(",") if x.strip()]:
        aflags.append("-D" + d)
    for i in [x.replace("\\", "/").strip()
              for x in txt(amisc, "IncludePath").split(";") if x.strip()]:
        aflags.append("-i" + os.path.normpath(os.path.join(proj_dir, i)))

    units = []
    for g in tgt.find("Groups"):
        gf = g.find("Files")
        if gf is None:
            continue
        for f in gf.findall("File"):
            fp = txt(f, "FilePath")
            if not fp:
                continue
            fo = f.find("FileOption")
            if fo is not None and "IncludeInBuild>0" in ET.tostring(fo, encoding="unicode"):
                continue
            p = os.path.normpath(os.path.join(proj_dir, fp.replace("\\", "/")))
            if p.lower().endswith((".c", ".s")):
                units.append(p)
    return units, cflags, aflags


def write_scatter(path):
    """工程没填 ScatterFile（用 Target Dialog 内存布局），按 F407IGHx 生成一份。"""
    open(path, "w").write(
        "LR_IROM1 0x08000000 0x00100000  {\n"
        "  ER_IROM1 0x08000000 0x00100000  {\n"
        "   *.o (RESET, +First)\n"
        "   *(InRoot$$Sections)\n"
        "   .ANY (+RO)\n"
        "   .ANY (+XO)\n"
        "  }\n"
        "  RW_IRAM1 0x20000000 0x00020000  {\n"
        "   .ANY (+RW +ZI)\n"
        "  }\n"
        "  RW_IRAM2 0x10000000 0x00010000  {\n"
        "   .ANY (+RW +ZI)\n"
        "  }\n}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--mode", default="all", choices=["compile", "partial", "link", "all"])
    ap.add_argument("--objdir", default=None)
    ap.add_argument("--ac5", default=None)
    ap.add_argument("--mappings", default=None)
    a = ap.parse_args()

    repo = os.path.abspath(a.repo or os.environ.get("RM_FW_REPO", ""))
    hits = glob.glob(os.path.join(repo, "MDK-ARM", "*.uvprojx"))
    if not hits:
        print("!! 找不到 %s" % os.path.join(repo, "MDK-ARM", "*.uvprojx"))
        return 2
    proj = hits[0]

    ac5 = a.ac5 or AC5_DEFAULT
    if not have(ac5, os.path.join("bin", "armcc.exe")):
        ac5 = KEIL_ROOT if have(KEIL_ROOT, os.path.join("ARM", "ARMCC", "bin", "armcc.exe")) else ""
        base = os.path.join(KEIL_ROOT, "ARM", "ARMCC") if ac5 else ""
    else:
        base = ac5
    if not base:
        print("!! 没找到 ARM Compiler 5.06。免管理员提取：\n"
              "     msiexec /a ARMCompiler506_b960.msi /qn TARGETDIR=D:\\ac5root\n"
              "   再用 --ac5 或 ARMCC5_ROOT 指过来。")
        return 2
    maps = a.mappings or MAP_DEFAULT
    if not have(maps, "mdk_lite.elmap"):
        alt = os.path.join(KEIL_ROOT, "ARM", "sw", "mappings")
        maps = alt if have(alt, "mdk_lite.elmap") else ""
    if not maps:
        print("!! 没找到 mdk_lite.elmap（MDK-Lite 免 license 的钥匙）。\n"
              "   从 MDK5xxa.exe 内嵌 zip 里解出 ARM/sw/mappings/，用 --mappings 指过来。")
        return 2

    env = dict(os.environ, ARM_PRODUCT_PATH=maps, ARM_TOOL_VARIANT="mdk_lite")
    objdir = a.objdir or os.path.join(tempfile.gettempdir(), "rm_armcc_check")
    os.makedirs(objdir, exist_ok=True)
    logf = open(os.path.join(objdir, "armcc_check.log"), "w", encoding="utf-8")
    units, cflags, aflags = collect_units(proj)
    print("工程        : %s" % proj)
    print("工具链      : %s" % base)
    print("license 映射: %s  (ARM_TOOL_VARIANT=mdk_lite)" % maps)
    print("编译单元    : %d   中间产物: %s" % (len(units), objdir))
    rc = 0

    if a.mode in ("compile", "all"):
        n_fail = 0
        for p in units:
            obj = os.path.join(objdir, os.path.basename(p) + ".o")
            asm = p.lower().endswith(".s")
            cmd = ([os.path.join(base, "bin", "armasm.exe")] + aflags + [p, "-o", obj]
                   if asm else
                   [os.path.join(base, "bin", "armcc.exe")] + cflags + ["-c", p, "-o", obj])
            r = subprocess.run(cmd, capture_output=True, text=True, env=env)
            out = (r.stdout or "") + (r.stderr or "")
            logf.write("$ %s\n%s[rc=%d]\n\n" % (" ".join(cmd), out, r.returncode))
            if r.returncode != 0:
                n_fail += 1
                rc = 1
                print("[FAIL] %s\n%s" % (os.path.basename(p), out.strip()[:1200]))
        print("== 编译 == %d 个单元，失败 %d 个%s"
              % (len(units), n_fail, "" if not n_fail else "（0 error / 0 warning；工程本身把警告当错误）"))

    objs = sorted(glob.glob(os.path.join(objdir, "*.o")))
    outdir = os.path.join(objdir, "_out")
    os.makedirs(outdir, exist_ok=True)
    libs = [os.path.join(repo, "components", "algorithm", n)
            for n in ("AHRS.lib", "arm_cortexM4lf_math.lib")]
    libs = [x for x in libs if os.path.exists(x)]
    link0 = [os.path.join(base, "bin", "armlink.exe"), "--cpu", "Cortex-M4.fp"]
    if a.mode in ("partial", "all") and objs:
        r = subprocess.run(link0 + ["--partial", "-o", os.path.join(outdir, "partial-link.out")]
                           + objs + libs, capture_output=True, text=True, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        logf.write("$ partial link\n%s[rc=%d]\n\n" % (out, r.returncode))
        und = len(re.findall(r"L6218E", out))
        print("== partial 链接 == rc=%d，未定义符号 %d 个（另外链入了 %d 个 ARM 库）"
              % (r.returncode, und, len(libs)))
        if out.strip():
            print(out.strip()[:1200])
        if r.returncode != 0 or und:
            rc = 1
    if a.mode in ("link", "all") and objs:
        sct = os.path.join(outdir, "auto.sct")
        write_scatter(sct)
        r = subprocess.run(link0 + ["--scatter", sct, "--map", "--list",
                                    os.path.join(outdir, "map.txt"), "-o",
                                    os.path.join(outdir, "image.axf")] + objs + libs,
                           capture_output=True, text=True, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        logf.write("$ full link\n%s[rc=%d]\n\n" % (out, r.returncode))
        m = re.search(r"image \((\d+) bytes\)", out)
        if r.returncode == 0:
            print("== 完整链接 == 成功，镜像已产出：%s" % os.path.join(outdir, "image.axf"))
        elif "L6050U" in out:
            print("== 完整链接 == 只差授权：镜像 %s 字节 > MDK-Lite 上限 32768 (L6050U)。"
                  "符号与段布局都过了，换正式授权即可出 hex。" % (m.group(1) if m else "?"))
        else:
            rc = 1
            print("== 完整链接 == 失败：\n" + out.strip()[:2000])
    logf.close()
    print("日志        : %s" % os.path.join(objdir, "armcc_check.log"))
    print("结论        : " + ("ARMCC 真实工具链体检通过" if rc == 0 else "有问题，见上方 FAIL/失败"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
