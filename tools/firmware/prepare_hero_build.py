"""一条命令把固件工程准备成"英雄板 + 上位机可驾驶"的可编译状态。

用法：
    python prepare_hero_build.py <StandardRobotpp 仓库路径>
    python prepare_hero_build.py <路径> --revert      # 撤销本脚本做的一切改动

它做四件事，每件都验证：

1. 把兵种配置从步兵切到英雄（`application/robot_param.h` 里那一行 include）
   —— 不改这行会编出步兵固件，把全向轮运动学烧进麦轮车。
2. 套用 `polar-virtual-rc-drive-keys.patch`（让上位机能驾驶）
3. 逐项确认改动真的存在（extern 声明、合并函数、不再清 key.v、英雄 include）
4. 用固件**真实头文件**编译补丁新增代码，零错误零警告才放行

设计约束：
- **幂等**：重复运行不会重复插入或报错
- **不碰无关文件**：工作树有别人的本地改动时直接拒绝，不做半套修改
- 撤销用 git，不留手工回退痕迹
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "polar-virtual-rc-drive-keys.patch"
BASELINE_COMMIT = "2722e0d"
ROBOT_PARAM_REL = "application/robot_param.h"
HERO_INCLUDE = '#include "robot_param_mecannum_hero.h"'
INFANTRY_INCLUDE = '#include "robot_param_omni_infantry.h"'
USB_REL = "application/communication/usb_task.c"
RC_REL = "application/other/remote_control.c"

# 自转桥接（上行 0x04 / 下行 0x1F），见 host_bridge/GAPS.md 第 1 节。
HOST_BRIDGE_DIR = HERE / "host_bridge"
HOST_BRIDGE_HEADER_REL = "application/typedef/host_chassis_bridge.h"
# 速度回读桥（下行 0x1E 复活），见 motion_feedback 目录与 GAPS.md 第 4 节。
MOTION_FEEDBACK_SCRIPT = HERE / "motion_feedback" / "apply_motion_feedback.py"
MECA_REL = "application/chassis/chassis_mecanum.c"
OMNI_REL = "application/chassis/chassis_omni.c"

# 本脚本允许触碰的唯一文件（其余一律视为"别人的改动"）。
# 桥接头文件是**新增**的未跟踪文件，也必须列进来，
# 否则 check_clean 会把它当成外来改动而拒绝开工。
OWNED = {
    ROBOT_PARAM_REL, USB_REL, RC_REL,
    MECA_REL, OMNI_REL, HOST_BRIDGE_HEADER_REL,
}


class Step:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def ok(self, name: str, detail: str = "") -> None:
        print(f"  [OK]   {name}" + (f"  -> {detail}" if detail else ""))

    def bad(self, name: str, detail: str = "") -> None:
        self.failures.append(name)
        print(f"  [FAIL] {name}" + (f"  -> {detail}" if detail else ""))

    def warn(self, name: str, detail: str = "") -> None:
        self.warnings.append(name)
        print(f"  [WARN] {name}" + (f"  -> {detail}" if detail else ""))


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def read(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def check_repo(repo: Path, step: Step) -> bool:
    print("\n[1/6] 检查仓库")
    if not (repo / ".git").exists():
        step.bad("目标不是 git 仓库", str(repo))
        return False
    if not (repo / ROBOT_PARAM_REL).exists():
        step.bad("找不到 application/robot_param.h（路径给错了吗？）")
        return False
    head = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    if head.startswith(BASELINE_COMMIT):
        step.ok(f"HEAD 与补丁基线一致：{head}")
    else:
        step.warn(f"HEAD 是 {head}，补丁基线是 {BASELINE_COMMIT}",
                  "行号可能已漂移，若套不上请用 --revert 后手工合并")
    return True


def check_clean(repo: Path, step: Step) -> bool:
    """只允许本脚本自己碰过的文件有改动，别人的改动一律先拒绝。"""

    print("\n[2/6] 检查工作树")
    porcelain = git(repo, "status", "--porcelain").stdout
    foreign: list[str] = []
    owned: list[str] = []
    for line in porcelain.splitlines():
        path = line[3:].strip().strip('"')
        # 重命名条目取右侧
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path in OWNED:
            owned.append(path)
        else:
            foreign.append(path)
    if owned:
        step.ok(f"检测到本脚本此前的改动：{', '.join(owned)}（将继续并保证幂等）")
    if foreign:
        step.bad("工作树有非本脚本范围的改动，拒绝执行以免做出半套修改",
                 ", ".join(foreign[:5]) + (" ..." if len(foreign) > 5 else ""))
        print("         请先提交或 stash 这些改动，再重跑本脚本。")
        return False
    return True


def switch_to_hero(repo: Path, step: Step) -> None:
    print("\n[3/6] 切兵种配置：步兵 -> 英雄")
    path = repo / ROBOT_PARAM_REL
    text = path.read_text(encoding="utf-8")
    if HERO_INCLUDE in text:
        step.ok("已经是英雄配置（幂等跳过）")
        return
    if INFANTRY_INCLUDE not in text:
        step.bad("既不是步兵也不是英雄配置，不敢自动改", "请手工确认 robot_param.h 第 26 行")
        return
    # 只替换这一行，保留原行作为注释方便回切
    new = text.replace(
        INFANTRY_INCLUDE,
        f'{HERO_INCLUDE}   // 英雄（麦轮）\n'
        f'// {INFANTRY_INCLUDE[2:-1]}   // 步兵（全向轮），切回时取消注释',
        1,
    )
    path.write_text(new, encoding="utf-8")
    step.ok("已改为 robot_param_mecannum_hero.h")


def apply_patch(repo: Path, step: Step) -> bool:
    print("\n[4/6] 套用驾驶补丁 + 自转桥接")
    if not PATCH.exists():
        step.bad("补丁文件不存在", str(PATCH))
        return False
    usb = read(repo, USB_REL)
    if "UsbMergeVirtualRcKeys" in usb:
        step.ok("驾驶补丁已应用过（幂等跳过）")
    else:
        res = git(repo, "apply", str(PATCH))
        if res.returncode != 0:
            step.bad("git apply 失败", (res.stderr or res.stdout).strip()[:200])
            print("         可能原因：HEAD 不是基线提交，或这些文件已被改过。")
            return False
        step.ok("驾驶补丁 git apply 成功")

    # 自转桥接（上行 0x04 / 下行 0x1F）。必须一起装：
    # 光有驾驶补丁的话，小陀螺仍然只能借 SHIFT 键位——而固件对 SHIFT
    # 是边沿翻转，客户端只能开、关不掉，再开一次反而关掉。
    bridge = HOST_BRIDGE_DIR / "apply_host_bridge.py"
    if not bridge.exists():
        step.bad("自转桥接脚本不存在", str(bridge))
        return False
    res = subprocess.run(
        [sys.executable, str(bridge), str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        step.bad("自转桥接套用失败", ((res.stderr or res.stdout).strip()[-260:]))
        return False
    step.ok("自转桥接已装入（usb_task.c + 两个底盘文件 + 新头文件）")

    # 底盘速度回读（下行 0x1E）。和桥接一起装：麦轮/全向轮的 ChassisPublish
    # 本来是 __weak 空实现，0x1E 整段停发，客户端只能拿 0x0A 坐标做位移兜底。
    if not MOTION_FEEDBACK_SCRIPT.exists():
        step.bad("速度回读桥脚本不存在", str(MOTION_FEEDBACK_SCRIPT))
        return False
    res = subprocess.run(
        [sys.executable, str(MOTION_FEEDBACK_SCRIPT), str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        step.bad("速度回读桥套用失败", ((res.stderr or res.stdout).strip()[-260:]))
        return False
    step.ok("速度回读桥已装入（两个底盘文件 + usb_task.c 惰性订阅）")
    return True


def verify_changes(repo: Path, step: Step) -> bool:
    print("\n[5/6] 逐项确认改动存在")
    usb = read(repo, USB_REL)
    rc = read(repo, RC_REL)
    param = read(repo, ROBOT_PARAM_REL)

    checks = [
        ("robot_param.h 指向英雄配置", HERO_INCLUDE in param),
        ("补丁自带 extern RC_ctrl_t rc_ctrl（头文件不导出该符号）",
         re.search(r"extern\s+RC_ctrl_t\s+rc_ctrl\s*;", usb) is not None),
        ("合并函数存在且做按位 OR", "rc_ctrl.key.v |= drive_keys;" in usb),
        ("驾驶键掩码含 W/S/A/D + SHIFT（上限），且不含 Q/E/F",
         re.search(r"#define\s+VRC_DRIVE_KEY_MASK\s+\(\(uint16_t\)0x001F\)", usb) is not None),
        ("新鲜度门控存在（150ms）", "VRC_FRESH_TIMEOUT_MS 150" in usb),
        ("1ms 循环里调用了合并函数", "UsbMergeVirtualRcKeys();" in usb),
        ("0x03 接收时记录新鲜时刻",
         "VIRTUAL_RC_RECEIVE_TIME = HAL_GetTick();" in usb),
        ("ET08A 置零宏不再抹 key.v（竞态修复）",
         re.search(r"#define\s+SPECIAL_CHANNEL_SET_SERO\(\)[^#]*?key\.v\s*=\s*0", rc, re.S) is None),
        ("同一宏仍保留鼠标置零", "rc_ctrl->mouse.press_r = 0;" in rc),
    ]

    # ---- 自转桥接（上行 0x04 / 下行 0x1F）----
    # 这几项是“小陀螺能不能关得掉”的全部证据。少了任一项，客户端就
    # 会回到“只能开不能关”的老问题，而且看上去像是已经对齐了。
    header = read(repo, HOST_BRIDGE_HEADER_REL)
    meca = read(repo, MECA_REL)
    omni = read(repo, OMNI_REL)
    checks += [
        ("桥接头文件已装到 application/typedef/", bool(header)),
        # 注意不能写成 `"FrameHeader_t" not in header`：头文件的注释里
        # 正好提到了这个词（用来说明为什么刻意不用它），那样会假失败。
        # 真正要卡的是“没把它当类型用”。
        ("头文件自带帧头定义（不依赖两个同名的 FrameHeader_t）",
         re.search(r"\bFrameHeader_t\s+\w+\s*;", header) is None
         and "uint8_t sof;" in header),
        ("上行 0x04 / 下行 0x1F 的 id 已定义",
         "CHASSIS_CMD_DATA_RECEIVE_ID ((uint8_t)0x04)" in header
         and "CHASSIS_STATE_DATA_SEND_ID ((uint8_t)0x1F)" in header),
        ("接收分发已挂上 0x04", "case CHASSIS_CMD_DATA_RECEIVE_ID:" in usb),
        ("主循环已消费底盘指令", "GetChassisCmdData();" in usb),
        ("发送编排已挂上 0x1F", "CheckDurationAndSend(ChassisState);" in usb),
        ("指令过期会收回为 NONE（掉线不锁死自转）",
         "HOST_SPIN_CMD_VALID_MS" in usb and "HOST_SPIN_CMD = HOST_SPIN_CMD_NONE;" in usb),
        ("麦轮底盘已接入桥接", "HOST_CHASSIS_BRIDGE_APPLY(&chassis);" in meca),
        ("全向轮底盘已接入桥接（若该文件存在）",
         (not omni) or "HOST_CHASSIS_BRIDGE_APPLY(&chassis);" in omni),
        # 英雄板的关键：麦轮 s[0] 拨到上方是无条件 CHASSIS_SPIN，
        # 拨到下方是 CHASSIS_LOCK，两种都不读 spin_flag。
        # 桥接必须早于这段仲裁，否则 spin_flag 维护了也没用。
        ("麦轮桥接早于 s[0] 拨杆仲裁",
         meca.find("HOST_CHASSIS_BRIDGE_APPLY(&chassis);") < meca.find("switch_is_down(chassis.rc->rc.s[0])")
         and meca.find("HOST_CHASSIS_BRIDGE_APPLY(&chassis);") >= 0),
        ("原有模式仲裁未被改动（遥控器仍是最终裁决者）",
         "switch_is_up(chassis.rc->rc.s[0])" in meca),
    ]

    # ---- 速度回读桥（下行 0x1E）----
    # 少了这几项，客户端的"车是否响应"检测只能退回 0x0A 位移兜底。
    checks += [
        ("麦轮速度回读：强符号 ChassisPublish + 每帧刷新",
         "void ChassisPublish(void)" in meca and "chassis_update_fdb_speed();" in meca),
        ("全向轮速度回读：强符号 ChassisPublish + 每帧刷新",
         "void ChassisPublish(void)" in omni and "chassis_update_fdb_speed();" in omni),
        ("回读发布的是实测 feedback（不是指令 set）",
         "chassis.feedback[0]" in meca and "chassis.feedback[0]" in omni
         and "chassis.set[" not in meca.split("chassis_update_fdb_speed(void)")[1][:800]),
        ("usb_task 对 0x1E 做了惰性重订阅（摆脱启动顺序）",
         usb.count("Subscribe(CHASSIS_FDB_SPEED_NAME)") >= 2),
    ]
    for name, passed in checks:
        (step.ok if passed else step.bad)(name)
    return all(p for _, p in checks)


def compile_check(repo: Path, step: Step) -> None:
    print("\n[6/6] 用固件真实头文件编译补丁新增代码")
    script = HERE / "test_patch_real_headers.py"
    if not script.exists():
        step.warn("找不到 test_patch_real_headers.py，跳过编译校验")
        return
    try:
        import ziglang  # noqa: F401
    except ImportError:
        step.warn("未安装 ziglang，跳过编译校验",
                  "装一下即可启用：pip install ziglang")
        return
    res = subprocess.run([sys.executable, str(script)], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0:
        step.ok("补丁新增代码在真实头文件下零错误零警告")
    else:
        tail = ((res.stderr or "") + (res.stdout or "")).strip().splitlines()[-6:]
        step.bad("编译校验未通过", " | ".join(t[:120] for t in tail))


CHECKLIST = """
上车前必须知道的四件事
------------------------------------------------------------
1. 遥控器三位拨杆 s[0] 建议拨到 **中间**。
   停在下方时固件走 CHASSIS_LOCK（chassis_mecanum.c:86），根本不读
   驾驶键位图 —— 补丁打得再对车也不动。
   上方也能开车，但那是固件**无条件强制常转**（:102），与 spin_flag 无关。
2. 验小陀螺必须拨中间。上方档下客户端的自转开关看上去"没反应"，
   因为车本来就在转（固件强制的）；拨到中间才能看出 0x04 指令真的生效。
   全向轮步兵不同：上方是 CHASSIS_FOLLOW（chassis_omni.c:114-117），不冲突。
3. 客户端侧要开：RobotLink 模块 enabled + Allow Drive + Client Chassis Drive，
   并把 Drive Channel 设为 virtual_rc（驾驶走 0x03 键位图，不走 speed_vector）。
   小陀螺走独立的 0x04，**不需要**驾驶授权也能发；但需开 Allow Spin Key。
4. 英雄限速 2.0 m/s（步兵是 1.5）。客户端按机器人自报编号取限幅，
   界面选错兵种会告警，不会静默按错的限速发。
------------------------------------------------------------
"""


def revert(repo: Path, step: Step) -> None:
    print("\n[revert] 撤销本脚本做过的改动")
    res = git(repo, "checkout", "--", ROBOT_PARAM_REL, USB_REL, RC_REL,
              MECA_REL, OMNI_REL)
    if res.returncode == 0:
        step.ok("已还原被改动的源文件")
    else:
        step.bad("还原失败", (res.stderr or res.stdout).strip()[:200])
    # 桥接头文件是**新增**的，git checkout 不会删未跟踪文件。
    # 不显式清掉的话，下一次跑会被当成“已应用”而跳过安装，
    # 测到的是陈旧副本。
    header = repo / HOST_BRIDGE_HEADER_REL
    if header.exists():
        header.unlink()
        step.ok("已删除新增的桥接头文件")


def main() -> int:
    ap = argparse.ArgumentParser(description="把固件工程准备成英雄板可驾驶状态")
    ap.add_argument("repo", help="StandardRobotpp 仓库路径")
    ap.add_argument("--revert", action="store_true", help="撤销本脚本的改动")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    step = Step()
    print(f"固件工程：{repo}")

    if not repo.exists():
        print(f"[FAIL] 路径不存在：{repo}")
        return 2
    if not check_repo(repo, step):
        return 2
    if args.revert:
        revert(repo, step)
    elif check_clean(repo, step):
        switch_to_hero(repo, step)
        if apply_patch(repo, step):
            verify_changes(repo, step)
            compile_check(repo, step)

    print("\n" + "=" * 62)
    if step.failures:
        print(f"结论：NO-GO，{len(step.failures)} 项未通过")
        for name in step.failures:
            print(f"  - {name}")
        print("\n不要拿去 Keil 编译；先解决上面这些。")
        return 1
    for name in step.warnings:
        print(f"提醒：{name}")
    print("结论：GO —— 工程已就绪，可以开 Keil 编译（工程启用了警告即错误）。")
    print(CHECKLIST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
