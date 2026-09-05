#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# prepare_hero_build.py 新增的两条能力要有离线证据：改鼠标灵敏度、以及"注释吞 define"能被体检抓住。
from __future__ import annotations

import importlib.util as ilu
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "rm_custom_client")) if not (ROOT / "rm_client").exists() else None
sys.path.insert(0, str(HERE))

_SPEC = ilu.spec_from_file_location("phb", HERE / "prepare_hero_build.py")
phb = ilu.module_from_spec(_SPEC)
_SPEC.loader.exec_module(phb)

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    FAILED += 0 if ok else 1


def main() -> int:
    print("\n--- prepare_hero_build 新增选项 ---")
    step = phb.Step()

    # 1) 注释剥离器：证明"躺在注释里的 #define"再也骗不过体检
    src = ("/* 说明\n#define __CONTROL_LINK_KM CL_KM_VT\n*/\n"
           "#ifndef X\n#define X 1\n#endif\n"
           "// #define Y 2\n#define Z 3\n")
    stripped = phb.strip_c_comments(src)
    check("块注释里的 #define 被剥掉", "CL_KM_VT" not in stripped, stripped.replace(chr(10), "|"))
    check("注释外的 #define 留着", "Z 3" in stripped and "Y 2" not in stripped)
    check("字符串里的 // 不会被当注释", "http://x" in phb.strip_c_comments('a="http://x";'))
    check("剥注释后还能看见 ifndef", "#ifndef X" in stripped)

    # 2) --mouse-sens 在临时副本上真的改得动，且幂等
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "application").mkdir()
        hero = repo / phb.HERO_PARAM_REL
        hero.write_text('#define MOUSE_SENSITIVITY (100000.0f)\n#define OTHER 1\n',
                        encoding="utf-8")
        phb.switch_mouse_sensitivity(repo, step, "0.5")
        t1 = hero.read_text(encoding="utf-8")
        check("英雄参数被改成可用量级", "#define MOUSE_SENSITIVITY (0.5f)" in t1, t1.splitlines()[0])
        check("旁边的宏不受影响", "#define OTHER 1" in t1)
        phb.switch_mouse_sensitivity(repo, step, "1.2")
        t2 = hero.read_text(encoding="utf-8")
        check("再改一次是替换不是叠加（只有一行定义）",
              t2.count("#define MOUSE_SENSITIVITY") == 1 and "1.2f" in t2, t2.splitlines()[0])
        phb.switch_mouse_sensitivity(repo, step, "0.5f")
        check("带 f 后缀的输入也不会变成 0.5ff",
              "#define MOUSE_SENSITIVITY (0.5f)" in hero.read_text(encoding="utf-8"))
        n_before = len(step.failures)
        phb.switch_mouse_sensitivity(Path(td) / "missing", step, "0.5")
        check("找不到文件时记一条失败，不是静默返回",
              len(step.failures) == n_before + 1, str(step.failures[-1:]))
        hero.write_text("#define SOMETHING_ELSE 1\n", encoding="utf-8")
        n_before = len(step.failures)
        phb.switch_mouse_sensitivity(repo, step, "0.5")
        check("文件在但宏写法变了也要报错（上游改了不能装看不见）",
              len(step.failures) == n_before + 1, str(step.failures[-1:]))
        shutil.rmtree(td, ignore_errors=True)
    # 2b) 默认值本身要有物理含义，不能是抄来的"看起来像"的数
    check("默认 MOUSE_SENSITIVITY 是有物理含义的量级（1px≈1mrad 那一档）",
          phb.DEFAULT_MOUSE_SENS == "1000", str(phb.DEFAULT_MOUSE_SENS))
    check("默认值不是死配置 0.5（那是配套没有鼠标的遥控器的）",
          float(phb.DEFAULT_MOUSE_SENS) > 10.0, str(phb.DEFAULT_MOUSE_SENS))

    # 3) 最关键的一条：--km 与 --km-fire-keys 必须真的生效（历史上是静默空转）
    import re
    with tempfile.TemporaryDirectory() as td2:
        repo2 = Path(td2)
        (repo2 / "application").mkdir()
        param = repo2 / "application" / "robot_param.h"
        param.write_text(
            "#define __RC_TYPE RC_ET08A\n"
            "#ifndef __CONTROL_LINK_KM\n#define __CONTROL_LINK_KM CL_KM_RC\n#endif\n",
            encoding="utf-8")
        st = phb.Step()
        phb.switch_km_link(repo2, st, "vt", False)
        text = param.read_text(encoding="utf-8")
        stripped = phb.strip_c_comments(text)
        hit = re.search(r"^\s*#define\s+__CONTROL_LINK_KM\s+(CL_KM_\w+)", stripped, re.M)
        check("--km vt 把宏写在**注释外**（编译器真看得见，不是靠 ifndef 兜底）",
              hit is not None and hit.group(1) == "CL_KM_VT",
              str(hit.group(1)) if hit else "注释外没有这个 define")
        check("ifndef 兜底块还在（幂等重跑不会叠出两份）",
              text.count("#define __CONTROL_LINK_KM") == 2, str(text.count("#define __CONTROL_LINK_KM")))
        phb.switch_km_link(repo2, st, "rc", True)
        stripped2 = phb.strip_c_comments(param.read_text(encoding="utf-8"))
        check("--km rc 换档也真的生效（切回来同样要有效）",
              re.search(r"^\s*#define\s+__CONTROL_LINK_KM\s+CL_KM_RC\b", stripped2, re.M) is not None)
        check("--km-fire-keys 的 KM_KEY_ALLOWED_MASK 也在注释外（开火键位不再静默失效）",
              re.search(r"^\s*#define\s+KM_KEY_ALLOWED_MASK", stripped2, re.M) is not None)
        phb.switch_km_link(repo2, st, "vt", False)
        stripped3 = phb.strip_c_comments(param.read_text(encoding="utf-8"))
        check("不给 --km-fire-keys 时必须**没有**开火掩码（不偷偷扩权）",
              re.search(r"^\s*#define\s+KM_KEY_ALLOWED_MASK", stripped3, re.M) is None)
        check("重跑不会把块叠成两份",
              param.read_text(encoding="utf-8").count(phb.KM_BLOCK_HEAD) == 1)

    # 4) 脚本会写的文件必须登记在 OWNED：否则第二次跑 prepare 会被 check_clean 拒
    #    （referee.c 踩过一次，--mouse-sens 又踩一次，所以这条要变成断言）
    check("英雄参数文件在 OWNED 名单里（第二次 prepare 不会被拒）",
          phb.HERO_PARAM_REL in phb.OWNED)
    check("robot_param.h 也在 OWNED 里", phb.ROBOT_PARAM_REL in phb.OWNED)
    import subprocess
    real_git = phb.git

    def fake_git(owned_only):
        def _f(repo, *args):
            if args and args[0] == "status":
                out = (" M " + phb.HERO_PARAM_REL + "\n"
                       + (" M application/typedef/host_km_link.h\n" if owned_only else
                          " M application/somebody_else.c\n"))
                return subprocess.CompletedProcess(["git"], 0, out, "")
            return real_git(repo, *args)
        return _f

    try:
        with tempfile.TemporaryDirectory() as td3:
            phb.git = fake_git(True)
            st = phb.Step()
            check("只有本脚本碰过的改动时 check_clean 放行（幂等重跑）",
                  phb.check_clean(Path(td3), st) is True and not st.failures)
            st2 = phb.Step()
            phb.git = fake_git(False)
            check("别人改的文件仍然要拒绝（不能为了幂等把闸门拆了）",
                  phb.check_clean(Path(td3), st2) is False and bool(st2.failures))
    finally:
        phb.git = real_git

    print("\n" + ("有失败项" if FAILED else "prepare_hero_build 新选项全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
