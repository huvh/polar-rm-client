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
- 撤销按安装前快照恢复；遇到后续编辑或旧版无快照时拒绝覆盖
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from file_guard import FileJournal, SnapshotError

HERE = Path(__file__).resolve().parent
PATCH = HERE / "polar-virtual-rc-drive-keys.patch"
BASELINE_COMMIT = "2722e0d"
ROBOT_PARAM_REL = "application/robot_param.h"
HERO_INCLUDE = '#include "robot_param_mecannum_hero.h"'
INFANTRY_INCLUDE = '#include "robot_param_omni_infantry.h"'
INFANTRY_PARAM_REL = "application/robot_param_omni_infantry.h"
# 两个兵种的参数文件。C 路（DT7 键鼠）对两者都成立：__RC_TYPE 是 robot_param.h
# 里的全局宏、DT7 的 18 字节解码在 remote_control.c 里也不分兵种；
# 差别只在"该改哪个参数文件的 MOUSE_SENSITIVITY"，所以兵种必须能选。
ROBOT_PROFILES = {
    "hero": {"include": HERO_INCLUDE, "param": "application/robot_param_mecannum_hero.h"},
    "infantry": {"include": INFANTRY_INCLUDE, "param": "application/robot_param_omni_infantry.h"},
}
USB_REL = "application/communication/usb_task.c"
RC_REL = "application/other/remote_control.c"

# 自转桥接（上行 0x04 / 下行 0x1F），见 host_bridge/GAPS.md 第 1 节。
HOST_BRIDGE_DIR = HERE / "host_bridge"
HOST_BRIDGE_HEADER_REL = "application/typedef/host_chassis_bridge.h"
# 速度回读桥（下行 0x1E 复活），见 motion_feedback 目录与 GAPS.md 第 4 节。
MOTION_FEEDBACK_SCRIPT = HERE / "motion_feedback" / "apply_motion_feedback.py"
# 云台直控桥（0x04 param0 bit0），见 gimbal_host 目录与 GAPS.md 第 3 节。
GIMBAL_HOST_SCRIPT = HERE / "gimbal_host" / "apply_gimbal_host.py"
KM_LINK_SCRIPT = HERE / "km_link" / "apply_km_link.py"

# 图传键鼠链路的五档，取值来自固件自己的 robot_typedef.h:80-84。
# 刻意不在这里造新档：宏和取值都是队内作者已经写好的，本脚本只是把它接完。
KM_LINK_NAMES = {
    "rc": "CL_KM_RC",        # 只认遥控器 = 上游默认 = 现役车行为
    "none": "CL_KM_NONE",    # 两路键鼠都屏蔽
    "vt": "CL_KM_VT",        # 只认图传（客户端独占键鼠）
    "rc_vt": "CL_KM_RC_VT",  # 互补，遥控器优先
    "vt_rc": "CL_KM_VT_RC",  # 互补，图传优先
}
KM_OURS_MARK = "prepare_hero_build.py --km"
KM_BLOCK_HEAD = "/* POLAR-HERO-BUILD: 键鼠链路档位"
GIMBAL_REL = "application/gimbal/gimbal_yaw_pitch_direct.c"
# 遥控器类型（__RC_TYPE）。比赛链路是"DT7 遥控器 <-> 车上 DR16 接收机"，默认写
# RC_DT7 是为了让配置说实话。
#
# 准确的影响范围（2026-09-03 逐行核过；本仓库注释的早先版本在这里写重了，已更正）：
#   * 18 字节 DT7 帧**与 __RC_TYPE 无关**：remote_control.c:252 是按"帧长"分派，
#     18 字节无条件进 sbus_to_rc()，键位/鼠标照解、中值用 DT7 自己的
#     RC_CH_VALUE_OFFSET=1024。所以"DT7 硬件 + ET08A 配置"这台车**照样能开**。
#   * 这个宏真正决定两件小事：
#       a) 25 字节帧交给哪家解码器（remote_control.c:264-280 的 #if 链）；
#       b) GetRcOffline() 要不要看 sbus_lost_count（:577-587）。非 DT7 时那一项
#          初值就是超限、且只有 25 字节路径会更新它 -> DT7 车上该判据恒真。
#          后果范围：板间广播 rc_offline 恒 1（communication.c:186、
#          CAN_communication.c:75）+ 平衡底盘会置 DBUS_ERROR_OFFSET
#          （chassis_balance.c:272）；麦轮/全向轮这里是 chassis_task.c:98 的
#          __weak 空实现，所以**不影响本车运动**；离线警报曲 music_task.c:38 的
#          ENABLE_ALARM_RC_OFFLINE 默认 false，也不放。
#   * **真正致命的是反向情形**：车上装 25 字节遥控器（AT9S/HT8A/ET08A）而宏配成
#     dt7 或不匹配的那一家 -> #if 链全不成立，那一帧**一个字段都不解**，车不动。
# 所以 --rc 的价值 = 让"车上装的是谁"和"固件写的是谁"对齐；而"客户端能不能叠在
# 驾驶员上面开车"靠的是键位记账合并（host_bridge/RC_LINKS.md 第 3 节）。
RC_TYPE_NAMES = {
    "dt7": "RC_DT7",
    "at9s": "RC_AT9S_PRO",
    "ht8a": "RC_HT8A",
    "et08a": "RC_ET08A",
}
RC_LINE_RE = re.compile(r"^[ \t]*#define[ \t]+__RC_TYPE[ \t]+(RC_\w+)", re.M)
RC_ORIG_RE = re.compile(r"原始值\s+(RC_\w+)")
RC_OURS_MARK = "prepare_hero_build.py --rc"
NL = chr(10)  # 本函数内拼行用

MECA_REL = "application/chassis/chassis_mecanum.c"
OMNI_REL = "application/chassis/chassis_omni.c"

# 本脚本允许触碰的唯一文件（其余一律视为"别人的改动"）。
# 桥接头文件是**新增**的未跟踪文件，也必须列进来，
# 否则 check_clean 会把它当成外来改动而拒绝开工。
# 英雄（麦轮）参数文件：本脚本用 --mouse-sens 改它，所以它属于本脚本拥有的文件
HERO_PARAM_REL = "application/robot_param_mecannum_hero.h"
# MOUSE_SENSITIVITY 的取值要有出处，不能抄一个"看起来像"的数：
#   云台参考角每 1ms 积一次 mouse / MOUSE_SENSITIVITY（弧度），
#   gimbal_yaw_pitch_direct.c:331-332，任务周期 vTaskDelay(GIMBAL_CONTROL_TIME=1)
#   而 configTICK_RATE_HZ=1000（gimbal_task.c:31-32/76、FreeRTOSConfig.h:61）。
#   一个 mouse 值会被 DT7/DR16 保持约 14ms（DBUS 每 14ms 一帧，手册第 5 页），
#   期间固件积 14 次；客户端出口 max_hz=30，一帧的位移只代表 1/30 秒。
#   => 云台角速度 ≈ 1000 * (每帧像素) / S（rad/s）。
#   以前按"1px=1mrad"取的 1000，实际约等于 1000*(1000/30)/1000 = 33 rad/s，
#   手一动就顶到 ±π 限位 —— 表现是"云台乱甩"，不是"没反应"。
#   出厂的 100000 是另一头：同样 1000px/s 只有 0.33 rad/s，慢到像没接上，
#   但它不是"屏蔽"（摇杆用的是另一个常数 REMOTE_CONTROLLER_SENSITIVITY，
#   robot_param_mecannum_hero.h:93，出厂 100000 ⇒ 满偏 660 时 6.6rad/s，合理）。
#   取中值 20000：1000px/s 手速 ⇒ 1.7rad/s，够快也不至于甩飞；手感上车再标。
DEFAULT_MOUSE_SENS = "20000"

OWNED = {
    ROBOT_PARAM_REL, USB_REL, RC_REL,
    MECA_REL, OMNI_REL, HOST_BRIDGE_HEADER_REL, GIMBAL_REL,
    # km_link 会改 referee.c（记 0x0311 到达时刻）并新增一个头文件。
    # 不登记进 OWNED 的话，第二次跑 prepare 会被 check_clean 当成
    # "别人的改动"而拒绝执行——症状是"第一次成功、第二次 NO-GO"。
    "application/referee/referee.c",
    "application/typedef/host_km_link.h",
    # 同上：--mouse-sens 会改这个文件。不登记的话第二次跑 prepare 会被
    # check_clean 当成"别人的改动"而 NO-GO —— 这个坑本文件注释里已经记过一次
    # （referee.c），加 --mouse-sens 时又踩了一遍。凡脚本会写的文件都必须进 OWNED。
    HERO_PARAM_REL,
    INFANTRY_PARAM_REL,      # --robot infantry 时会改它，同样必须登记
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


GYRO_BIAS_MARKER = "#ifndef __GYRO_BIAS_YAW"
GYRO_BIAS_GUARD = (
    "\n"
    "// --- prepare_hero_build.py 追加：补齐 __GYRO_BIAS_YAW -------------------\n"
    "// application/IMU/IMU_solve.c 无条件用到 __GYRO_BIAS_YAW，但仓库里只有\n"
    "// robot_param_balanced_infantry*.h / robot_param_communicate.h 定义了它，\n"
    "// 英雄（mecannum_hero）与步兵（omni_infantry）参数文件都没有 -> 直接编不过：\n"
    "//   Error:  #20: identifier \"__GYRO_BIAS_YAW\" is undefined   (ARMCC 5.06)\n"
    "// 值先沿用仓库其它机型的标定值。换车/换 IMU 后请实车重新标定并改这一行：\n"
    "//   车辆静置，读陀螺仪 z 轴输出均值，取相反数填进来（单位 rad/s）。\n"
    "#ifndef __GYRO_BIAS_YAW\n"
    "#define __GYRO_BIAS_YAW 0.003096855f\n"
    "#endif\n"
    "// --- 追加结束 -----------------------------------------------------------\n"
)


def normalize_includes(lines: list, want: str, prof: dict, other: dict) -> list:
    """保证兵种 include 永远只有两行，并且**放回原位**：
    一行生效（所选兵种）+ 一行注释掉的备选。

    两个坑都踩过：
      1. 每次切换追加一行 `// #include ...` ⇒ 来回切几遍能攒出三行，读的人分不清哪条是真的；
      2. 用"找某条注释锚点，找不到就 append 到文件尾"来决定插哪儿 ⇒ 换一种
         robot_param.h 写法就会把 include 挤到 #define 后面（甚至落到 include guard 外面）。
    所以这里记住第一条兵种 include 原本排在第几个"非 include 行"之后，原位插回去。
    """
    def is_include(line: str) -> bool:
        s = line.strip()
        return ("robot_param_" in s
                and (s.startswith("#include") or s.startswith("// #include")))
    keep_before = 0
    for line in lines:
        if is_include(line):
            break
        if not line.strip():          # 空行不算"内容行"，不影响定位
            continue
        keep_before += 1
    body = [l for l in lines if not is_include(l)]
    live = f'{prof["include"]}   // {want}（prepare_hero_build.py --robot {want}）'
    alt = f'// {other["include"]}   // 另一个兵种，切回时取消注释'
    idx = 0
    seen = 0
    for i, line in enumerate(body):
        if seen == keep_before:
            idx = i
            break
        if line.strip():
            seen += 1
    body[idx:idx] = [live, alt]
    return body


def switch_robot(repo: Path, step: Step, want: str = "hero") -> None:
    """把 robot_param.h 指向所选兵种的参数文件（两个方向都支持、可反复跑）。"""
    prof = ROBOT_PROFILES[want]
    other = ROBOT_PROFILES["infantry" if want == "hero" else "hero"]
    print(f"\n[3/6] 切兵种配置 -> {want}（{prof['param']}）")
    path = repo / ROBOT_PARAM_REL
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    hit = None
    for idx, line in enumerate(lines):
        s = line.strip()
        if s.startswith(prof["include"]) or s.startswith("// " + prof["include"]) \
                or s.startswith(other["include"]) or s.startswith("// " + other["include"]):
            hit = idx
            break
    if hit is None:
        step.bad("robot_param.h 里找不到英雄/步兵任一条 include",
                 "上游改了写法，请同步本脚本")
        return
    fixed = normalize_includes(lines, want, prof, other)
    changed = fixed != lines
    if changed:
        path.write_text("\n".join(fixed), encoding="utf-8")
    if lines[hit].strip().startswith(prof["include"]) and not changed:
        step.ok(f"已经是 {want} 配置（幂等跳过）")
    elif changed and lines[hit].strip().startswith(prof["include"]):
        step.ok(f"已经是 {want} 配置，顺手把 include 区收成两行（原先攒了重复注释）")
    else:
        step.ok(f"include 已指向 {prof['param']}")


def switch_to_hero(repo: Path, step: Step) -> None:      # 兼容旧调用
    switch_robot(repo, step, "hero")


def _switch_to_hero_old(repo: Path, step: Step) -> None:
    path = repo / ROBOT_PARAM_REL
    text = path.read_text(encoding="utf-8")
    if HERO_INCLUDE in text:
        step.ok("已经是英雄配置（幂等跳过）")
    elif INFANTRY_INCLUDE in text:
        # 只替换这一行，保留原行作为注释方便回切
        text = text.replace(
            INFANTRY_INCLUDE,
            f'{HERO_INCLUDE}   // 英雄（麦轮）\n'
            f'// {INFANTRY_INCLUDE}   // 步兵（全向轮），切回时取消注释',
            1,
        )
        path.write_text(text, encoding="utf-8")
        step.ok("已改为 robot_param_mecannum_hero.h")
    else:
        step.bad("既不是步兵也不是英雄配置，不敢自动改", "请手工确认 robot_param.h 第 26 行")
        return
    ensure_gyro_bias(path, step)


def switch_rc_type(repo: Path, step: Step, want_key: str) -> None:
    """把 robot_param.h 的 __RC_TYPE 改成与车上接收机配套的那一种。"""
    want = RC_TYPE_NAMES[want_key]
    print(f"\n[3b] 切遥控器类型 -> {want}（--rc {want_key}）")
    path = repo / ROBOT_PARAM_REL
    text = path.read_text(encoding="utf-8")
    m = RC_LINE_RE.search(text)
    if not m:
        step.bad("robot_param.h 里找不到 `#define __RC_TYPE RC_xxx`",
                 "该宏是单行，若被手工改写过多行/注释，请恢复成一行后再跑")
        return
    cur = m.group(1)
    line = text[m.start():text.index(NL, m.start())]
    # 原始值：第一次改动时记在行尾注释里，之后反复切换都以它为准，
    # 这样"回切"不会把上游默认值丢掉。
    om = RC_ORIG_RE.search(line)
    orig = om.group(1) if om else cur

    if cur == want and RC_OURS_MARK not in line:
        # 上游默认就是它：加一行标记，不动取值，方便下次切回来时找得到原始值
        orig = cur
    elif cur == want:
        step.ok(f"已经是 {want}（幂等跳过）")
        return

    new_line = (
        f"#define __RC_TYPE {want:<12}// 遥控器类型（{RC_OURS_MARK} {want_key}）；"
        f"原始值 {orig}" + NL
        + f"// #define __RC_TYPE {orig}   // 回切：跑 --rc "
        + "/".join(k for k, v in RC_TYPE_NAMES.items() if v == orig)
        + "，或 git checkout -- " + ROBOT_PARAM_REL + NL
    # 结尾这个 NL 不能省：早先漏掉它时，回切注释行会把紧随其后的
    # `#define __DEVELOP 1` 拼成一行，反复运行还会把注释叠好几遍。
    )
    path.write_text(text[:m.start()] + new_line + text[text.index(NL, m.start()) + 1:],
                    encoding="utf-8")
    step.ok(f"__RC_TYPE: {cur} -> {want}（原始值 {orig} 已记在行尾注释）")


def switch_km_link(repo: Path, step: Step, want_key: str,
                   fire_keys: bool) -> None:
    """选键鼠链路档位，并按需放开 Q/E 键位掩码。

    为什么要插在 robot_param.h 的 `#ifndef __CONTROL_LINK_KM` **之前**：
    那个默认块写成 ifndef 守卫，所以只要前面已经定义过，它就会自动跳过，
    不需要去改动上游那三行（改动越少，回切越干净）。
    """
    want = KM_LINK_NAMES[want_key]
    print(f"\n[3c] 键鼠链路 -> {want}（--km {want_key}"+("，并放开 Q/E 开火键位）"
          if fire_keys else "）"))
    path = repo / ROBOT_PARAM_REL
    text = path.read_text(encoding="utf-8")

    # 注意：这里的注释必须**逐条自己闭合**。上一版把第一行写成了 "...链路）>"
    # （少了 "*/"），于是从下一行的 /* 开始一路吞到 "#define __CONTROL_LINK_KM"
    # 和 "#define KM_KEY_ALLOWED_MASK" 两行 —— 结果 "--km vt" 与 "--km-fire-keys"
    # 都是**静默空转**：值靠下面那个 #ifndef 兜底恰好还是 CL_KM_RC，开火键位则根本没打开。
    block = (
        KM_BLOCK_HEAD + "（图传键鼠链路） */\n"
        + "/* 固件自己定义的五档键鼠来源在 robot_typedef.h:80-84。\n"
        + " * tools/firmware/km_link/apply_km_link.py 是那半截的消费者接线。\n"
        + f" * {KM_OURS_MARK} {want_key}；上游默认值 CL_KM_RC（只认遥控器）。 */\n"
        + f"#define __CONTROL_LINK_KM {want}\n"
        + ("/* 开火相关键位（Q/E 摩擦轮）经图传注入的许可，由 --km-fire-keys 给 */\n"
           "#define KM_KEY_ALLOWED_MASK (KM_KEY_MASK_DRIVE | KM_KEY_MASK_FIRE)\n"
           if fire_keys else
           "/* 没给 --km-fire-keys：图传只能注入 W/S/A/D/SHIFT，开火权限不外送 */\n")
        + "/* ---- POLAR-HERO-BUILD 键鼠链路块结束 ---- */\n\n"
    )

    # 幂等：先摘掉旧的块，再按本次参数插回去（一次成型，避免反复叠加）
    if KM_BLOCK_HEAD in text:
        head = text.index(KM_BLOCK_HEAD)
        tail = text.index("键鼠链路块结束", head)
        tail = text.index("\n", tail) + 2  # 连 "*/" 那一行和它后面的空行
        text = text[:head] + text[tail:]
        step.ok("先摘掉旧的键鼠链路块，再按本次参数插回")

    anchor = "#ifndef __CONTROL_LINK_KM"
    if anchor not in text:
        step.bad("robot_param.h 里找不到 #ifndef __CONTROL_LINK_KM 默认块",
                 "上游若改了这个宏的写法，请同步本脚本的插入位置")
        return
    text = text.replace(anchor, block + anchor, 1)
    path.write_text(text, encoding="utf-8")
    step.ok(f"__CONTROL_LINK_KM = {want}"
            + ("（含 Q/E 开火键位）" if fire_keys else "（驾驶键位 only）"))


def strip_c_comments(text: str) -> str:
    """剥掉 C 的 // 与 /* */ 注释（含字符串字面量保护），用来证明某个 #define
    是**真的生效**而不是躺在注释里。verify_changes 光 grep 字符串会被注释骗到。"""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"' or ch == "'":
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def switch_mouse_sensitivity(repo: Path, step: Step, value: str,
                             param_rel: str = HERO_PARAM_REL) -> None:
    """改英雄参数里的 MOUSE_SENSITIVITY。

    出厂值 100000.0f（application/robot_param_mecannum_hero.h:91）等于**把鼠标屏蔽掉**：
    云台参考角增量 = mouse / SENSITIVITY（gimbal_yaw_pitch_direct.c:331-332），
    除以十万后增量为 0；那两处代码上方的自注也写着"暂时先屏蔽一下鼠标功能"。
    走 C 路（键鼠进 DT7）要用鼠标控云台，就得给一个可用量级（非英雄板那份是 0.5f），
    方向与手感仍须实车标定。
    """
    print(f"\n[3d] MOUSE_SENSITIVITY -> {value}（{param_rel}）")
    path = repo / param_rel
    if not path.exists():
        step.bad("找不到英雄参数文件", str(path))
        return
    text = path.read_text(encoding="utf-8")
    pat = re.compile(r"(#define\s+MOUSE_SENSITIVITY\s+)\(\s*[0-9.]+f?\s*\)")
    m = pat.search(text)
    if not m:
        step.bad("英雄参数里找不到 MOUSE_SENSITIVITY 定义", "上游改了写法，请同步本脚本")
        return
    old = m.group(0)
    literal = value if value.endswith("f") else value + "f"
    new = m.group(1) + "(" + literal + ")"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    step.ok(f"MOUSE_SENSITIVITY：{old}  ->  {new}")


def ensure_gyro_bias(path: Path, step: Step) -> None:
    """ARMCC 5.06 实测：英雄参数文件缺 __GYRO_BIAS_YAW，IMU_solve.c 编不过，这里补兜底定义。"""
    text = path.read_text(encoding="utf-8")
    if GYRO_BIAS_MARKER in text:
        step.ok("__GYRO_BIAS_YAW 兜底定义已存在（幂等跳过）")
        return
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if any(line.strip().startswith(p["include"]) for p in ROBOT_PROFILES.values()):
            lines.insert(idx + 1, GYRO_BIAS_GUARD.rstrip("\n"))
            path.write_text("\n".join(lines), encoding="utf-8")
            step.ok("补上 __GYRO_BIAS_YAW 兜底定义（英雄/步兵参数文件都没给）")
            return
    step.bad("没找到英雄 include 行，无法插入 __GYRO_BIAS_YAW", "请手工在 robot_param.h 补该宏")



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

    # 云台直控桥。依赖 host_bridge 的 0x04 帧（上面先装），这里最后叠加。
    if not GIMBAL_HOST_SCRIPT.exists():
        step.bad("云台直控桥脚本不存在", str(GIMBAL_HOST_SCRIPT))
        return False
    res = subprocess.run(
        [sys.executable, str(GIMBAL_HOST_SCRIPT), str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        step.bad("云台直控桥套用失败", ((res.stderr or res.stdout).strip()[-260:]))
        return False
    step.ok("云台直控桥已装入（桥接头 + usb_task + 云台仲裁）")

    # 图传键鼠链路。必须最后装：它要改写 host_bridge 写进 key.v 的那几行，
    # 而 gimbal_host 又会把 usb_task.c 整体读改写一遍，顺序错了就撞锚点。
    if not KM_LINK_SCRIPT.exists():
        step.bad("图传键鼠链路脚本不存在", str(KM_LINK_SCRIPT))
        return False
    res = subprocess.run(
        [sys.executable, str(KM_LINK_SCRIPT), str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        step.bad("图传键鼠链路套用失败", ((res.stderr or res.stdout).strip()[-300:]))
        return False
    step.ok("图传键鼠链路已接入（referee.c 到包时刻 + 五档仲裁 + usb_task 周期）")
    return True


def verify_changes(repo: Path, step: Step, want_rc: str = 'dt7',
                   want_robot: str = "hero") -> bool:
    print("\n[5/6] 逐项确认改动存在")
    usb = read(repo, USB_REL)
    rc = read(repo, RC_REL)
    param = read(repo, ROBOT_PARAM_REL)
    hdr0 = read(repo, HOST_BRIDGE_HEADER_REL)

    want_include = ROBOT_PROFILES[want_robot]["include"]
    checks = [
        (f"robot_param.h 指向所选兵种配置（{want_robot}）",
         want_include in param and param.count("#include \"robot_param_") >= 1),
        ("__RC_TYPE 与车上装的遥控器是同一家（真实影响范围见 RC_LINKS.md 第 2 节）",
         RC_LINE_RE.search(param) is not None
         and RC_LINE_RE.search(param).group(1) == RC_TYPE_NAMES[want_rc]),
        ("改 __RC_TYPE 时没把下一行吞进注释（行尾换行完好）",
         all("__DEVELOP" not in l and l.count("__RC_TYPE") <= 1
             for l in param.splitlines() if "回切" in l)),
        ("robot_param.h 里生效的 __RC_TYPE 只有一条、后续 #define 未被复制",
         len([l for l in param.splitlines() if RC_LINE_RE.match(l)]) == 1
         and param.count("#define __DEVELOP") == 1),
        ("补丁自带 extern RC_ctrl_t rc_ctrl（头文件不导出该符号）",
         re.search(r"extern\s+RC_ctrl_t\s+rc_ctrl\s*;", usb) is not None),
        # 键位必须是"记账 + 写合并值"，不能是 |=，也不能让 DT7 整字段覆盖。
        # 三个取值各对应一个真实故障，缺任一项就会在现场复现：
        #   旧写法 `|=`  -> 客户端松手后位粘住，车刹不住（非 DT7 时没人清零）
        #   缺 DT7 记账 -> DT7 每帧 `key.v =` 覆盖，客户端键位按帧率被抹掉，
        #                  而 SHIFT 是边沿检测 -> 小陀螺开关自己乱跳
        #   缺宏内置零 -> 车上从 DT7 换成 25 字节遥控器时，驾驶员键位冻在最后一帧
        ("客户端键位写合并值（已改掉 |= 粘键写法）",
         "HOST_RC_HOST_KEYS = drive_keys;" in usb
         and "rc_ctrl.key.v = HOST_RC_MERGED_KEYS();" in usb
         and "rc_ctrl.key.v |= drive_keys" not in usb),
        ("DT7 解码先记账再写合并值（客户端键位不被整帧抹掉）",
         "HOST_RC_DRIVER_KEYS = rc_ctrl->key.v;" in rc
         and "rc_ctrl->key.v = HOST_RC_MERGED_KEYS();" in rc),
        ("无键盘遥控器路径把驾驶员键位记为 0",
         re.search(r"HOST_RC_DRIVER_KEYS\s*=\s*0\s*;", rc) is not None),
        ("桥接头导出键位账本三件套（掩码/两个账量/合并宏）",
         "HOST_RC_DRIVE_KEY_MASK" in hdr0 and "HOST_RC_MERGED_KEYS()" in hdr0),
        ("驾驶键掩码含 W/S/A/D + SHIFT（上限），且不含 Q/E/F",
         re.search(r"#define\s+VRC_DRIVE_KEY_MASK\s+\(\(uint16_t\)0x001F\)", usb) is not None),
        ("新鲜度门控存在（150ms）", "VRC_FRESH_TIMEOUT_MS 150" in usb),
        ("1ms 循环里调用了合并函数", "UsbMergeVirtualRcKeys();" in usb),
        ("0x03 接收时记录新鲜时刻",
         "VIRTUAL_RC_RECEIVE_TIME = HAL_GetTick();" in usb),
        ("ET08A 置零宏不再抹 key.v（竞态修复）",
         re.search(r"#define\s+SPECIAL_CHANNEL_SET_SERO\(\)[^#]*?key\.v\s*=\s*0", rc, re.S) is None),
        ("同一宏仍保留鼠标置零", "rc_ctrl->mouse.press_r = 0;" in rc),
        # 下面两条是防"注释吞 define"。历史上 --km vt / --km-fire-keys 就是这样
        # 静默空转的：值在文件里、grep 得到，但在注释里，编译器根本没看见。
        ("__CONTROL_LINK_KM 的 #define 在注释外（真的生效）",
         re.search(r"^\s*#define\s+__CONTROL_LINK_KM\s+CL_KM_\w+",
                   strip_c_comments(param), re.M) is not None),
        # 鼠标灵敏度：出厂值等于把鼠标整条废掉（英雄 100000.0f、步兵 40000.0f），
        # 云台参考角增量 = mouse / SENSITIVITY（gimbal_yaw_pitch_direct.c:331-332）。
        # 走 C 路要用鼠标控云台，就必须知道**当前兵种这份文件**里它等于多少 ——
        # 所以体检读的是 --robot 选中的那份参数文件，不是写死的英雄。
        (f"{want_robot} 参数里的 MOUSE_SENSITIVITY 是可用量级",
         (lambda hero_param: (
             (m := re.search(r"#define\s+MOUSE_SENSITIVITY\s+\(\s*([0-9.]+)f?\s*\)",
                             hero_param)) is not None
             and 5000.0 <= float(m.group(1)) <= 50000.0)
             or step.warn("MOUSE_SENSITIVITY 不在可用量级",
                          "云台每 1ms 积一次 mouse/S，一个值会被保持约 14ms，所以角速度≈1000*(每帧像素)/S；出厂 100000 慢到像没接上，上一版误取的 1000 会一帧甩到限位。用 --mouse-sens 给值，实车再标定手感")
         )(read(repo, ROBOT_PROFILES[want_robot]["param"])
           if (repo / ROBOT_PROFILES[want_robot]["param"]).exists() else "")),
        ("KM_KEY_ALLOWED_MASK 若被覆盖也必须落在注释外",
         ("KM_KEY_ALLOWED_MASK" not in param)
         or re.search(r"^\s*#define\s+KM_KEY_ALLOWED_MASK",
                      strip_c_comments(param), re.M) is not None),
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

    # ---- 云台直控桥（0x04 param0 bit0）----
    gim = read(repo, GIMBAL_REL)
    checks += [
        ("桥接头文件带 HOST_GIMBAL_REQ_MASK 定义",
         "HOST_GIMBAL_REQ_MASK" in header and "HOST_GIMBAL_REQUEST" in header),
        ("usb_task 维护请求位（新鲜赋值 + 过期撤销）",
         "HOST_GIMBAL_REQUEST = 0;" in usb
         and "RECEIVE_CHASSIS_CMD_DATA.data.param0 & HOST_GIMBAL_REQ_MASK" in usb),
        ("云台中间档按请求提档（无请求 = 打桥前）",
         "(HOST_GIMBAL_REQUEST != 0) ? GIMBAL_AUTO_AIM : GIMBAL_IMU" in gim),
        ("中间档提档位置在上方档之前、下方安全档未动",
         0 <= gim.find("switch_is_mid") < gim.find("HOST_GIMBAL_REQUEST != 0")
         < gim.find("switch_is_up") and "mode=GIMBAL_ZERO_FORCE;" in gim),
    ]
    # ---- 编译可行性（ARMCC 5.06 + --c99 + --diag_error=warning）----
    # 这四项都是"离线就能撞死、但只有真编译器才肯说"的坑，2026-09-03 全部
    # 用 tools/firmware/gcc_syntax_check.py 差分实测过：
    #   * 挤行 include 会被预处理器吞掉第二条（本工程 #include 少一行 = 少一批类型）
    #   * _Static_assert 是 C11，AC5 不认
    #   * 静态函数没有前置声明 => #223-D 隐式声明，而警告即错误
    all_src = "\n".join([header, usb, rc, param, meca, omni, gim])
    checks += [
        ("补丁没有把新代码挤进已有行（include 后不得再有代码）",
         re.search(r'#\s*include\s+"[^"]+"[^\S\r\n]*(?!//|/\*)\S', all_src) is None),
        ("桥接头不用 C11 的 _Static_assert（AC5 只到 C99）",
         "_Static_assert(" not in header
         and "HOST_BRIDGE_STATIC_ASSERT(" in header),
        ("usb_task 新增静态函数有前置声明（否则 #223-D 直接变错误）",
         "static void GetChassisCmdData(void);" in usb
         and "static void UsbSendChassisStateData(void);" in usb),
        ("底盘新增静态函数有前置声明（ChassisObserver 先调用后定义）",
         "static void chassis_update_fdb_speed(void);" in meca
         and "static void chassis_update_fdb_speed(void);" in omni),
    ]

    for name, passed in checks:
        (step.ok if passed else step.bad)(name)
    return all(p for _, p in checks)


# 第 6 步要跑的两个真实头文件校验。第二个是**可执行**的行为校验
# （把抽出来的键位代码编成 exe 跑一遍时序），因为键位合并的缺陷全都
# 发生在运行时：编译器看不出 `|=` 会粘键，也看不出 DT7 会把客户端键位抹掉。
COMPILE_CHECKS = (
    ("补丁新增代码在真实头文件下零错误零警告", "test_patch_real_headers.py", ()),
    ("驾驶键位三方写入者行为正确（DT7 不被抹 / 松键能归零）",
     "host_bridge/test_rc_key_ledger.py", ()),
)


def compile_check(repo: Path, step: Step) -> None:
    print("\n[6/6] 用固件真实头文件编译 + 运行补丁新增代码")
    try:
        import ziglang  # noqa: F401
    except ImportError:
        step.bad("INCOMPLETE: 未安装 ziglang，编译/行为校验未运行",
                  "装一下即可启用：pip install ziglang")
        return
    env = dict(os.environ, POLAR_FIRMWARE_ROOT=str(repo.resolve()), POLAR_FIRMWARE_READ_ONLY="1")
    print(f"[target] {repo.resolve()}")
    for name, rel, extra in COMPILE_CHECKS:
        script = HERE / rel
        if not script.exists():
            step.bad(f"INCOMPLETE: 找不到 {rel}，该项校验未运行")
            continue
        try:
            res = subprocess.run([sys.executable, str(script), str(repo.resolve()), *extra],
                                 capture_output=True, text=True, env=env, timeout=180,
                                 encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            step.bad(name, f"INCOMPLETE: {exc}")
            continue
        output = (res.stdout or "") + (res.stderr or "")
        skipped = re.search(r"(?im)^\s*(?:\[SKIP\]|SKIP:|\[INCOMPLETE\])", output)
        if res.returncode == 0 and not skipped:
            step.ok(name)
        else:
            tail = ((res.stderr or "") + (res.stdout or "")).strip().splitlines()[-6:]
            step.bad(name, " | ".join(t[:120] for t in tail))


CHECKLIST = """
上车前必须知道的六件事
------------------------------------------------------------
1. **`__RC_TYPE` 要和车上装的遥控器是同一家**。本脚本默认 `--rc dt7`
   （DT7 遥控器 + 车上 DR16），上游出厂写的是 et08a。
   准确的影响（2026-09-03 逐行核过，别再用"配错就整车瘫痪"这种夸大版本）：
     - DT7 的 18 字节帧**跟这个宏无关**：`remote_control.c:252` 按帧长分派，
       18 字节无条件进 `sbus_to_rc()`，键位、鼠标、中值全都照常 ->
       **你们以前拿 DT7 键鼠开车能开，这条从来没坏过**；
     - 宏配成 et08a 时真实损失只有一项：`GetRcOffline()` 恒真
       （`remote_control.c:577` 非 DT7 分支要看那个初值就超限、又只有
       25 字节路径会更新的 `sbus_lost_count`）。后果是板间广播 `rc_offline`
       恒 1（`communication.c:186`、`CAN_communication.c:75`）和**平衡底盘**
       置 `DBUS_ERROR_OFFSET`（`chassis_balance.c:272`）；麦轮/全向轮这里是
       `__weak` 空实现、离线警报曲默认关（`music_task.c:38`），所以这台英雄车
       上你几乎看不出差别 —— 但别的板、或换平衡底盘就会出事；
     - **真正"车完全不动"的是反向情形**：车上装 25 字节遥控器
       （AT9S / HT8A / ET08A）而宏配成 dt7 或不匹配那一家 ->
       `remote_control.c:264-280` 的 #if 链全不成立，那一帧一个字段都不解。
   换遥控器就重跑 `prepare_hero_build.py <固件树> --rc et08a|at9s|ht8a`，别手改宏。
2. **不插 USB 线也能用车上的遥控器开车**。比赛主链路是
   电脑 --USB--> DT7 --2.4G--> 车上 DR16 --SBUS--> C 板 UART3 -> rc_ctrl；
   DT7 的 18 字节帧本身就带键盘位和鼠标位移，驾驶员按 W/S/A/D 直接生效。
   USB 线（0x5A 帧）是**客户端专用的第二条入口**，插上以后客户端才能
   叠加驾驶键位、发 0x04 自转指令、拿 0x1E 速度 / 0x1F 状态回读。
3. **键位是"或"进去的，不是接管**。驾驶员键位与客户端键位各记一本账
   （HOST_RC_DRIVER_KEYS / HOST_RC_HOST_KEYS），谁按谁动、两边都松才停；
   0x03 超过 150ms 没刷新，客户端那份账立刻归零，控制权自动回到遥控器手里。
   客户端只可能碰 W/S/A/D，SHIFT、Q/E（摩擦轮）、F（sc_flag）
   在掩码外，永远只能由遥控器触发。
4. 遥控器三位拨杆 s[0]（右拨杆）建议拨到 **中间**。
   停在下方时固件走 CHASSIS_LOCK（chassis_mecanum.c:97），根本不读
   驾驶键位图 —— 补丁打得再对车也不动。
   上方也能开车，但那是固件**无条件强制常转**（:113），与 spin_flag 无关。
5. 验小陀螺必须拨中间。上方档下客户端的自转开关看上去"没反应"，
   因为车本来就在转（固件强制的）；拨到中间才能看出 0x04 指令真的生效。
   全向轮步兵不同：上方是 CHASSIS_FOLLOW（chassis_omni.c:114-117），不冲突。
6. 客户端侧要开：RobotLink 模块 enabled + Allow Drive + Client Chassis Drive，
   并把 Drive Channel 设为 virtual_rc（驾驶走 0x03 键位图，不走 speed_vector）。
   小陀螺走独立的 0x04，**不需要**驾驶授权也能发；但需开 Allow Spin Key。
   英雄限速 2.0 m/s（步兵是 1.5），客户端按机器人自报编号取限幅，
   界面选错兵种会告警，不会静默按错的限速发。
------------------------------------------------------------
"""


def revert(repo: Path, step: Step) -> None:
    print("\n[revert] 按安装前快照撤销，保留原有文件与修改")
    try:
        journal = FileJournal(repo, OWNED)
        with journal.locked():
            count = journal.revert()
        step.ok(f"已按快照恢复 {count} 个文件")
    except (SnapshotError, OSError) as exc:
        step.bad("安全回退被阻止；未使用 git checkout", str(exc))


def gcc_differential_check(repo: Path, step: Step) -> None:
    """可选：用 arm-none-eabi-gcc 做"打补丁前后"的诊断差分。

    没有 Keil/ARMCC 时唯一能自动跑起来的整工程编译检查。做法是临时
    worktree 出一份未打补丁的 HEAD，两棵树跑同一条 GCC 命令，只比对
    差集 —— 基线本身的噪音（Keil 专有语法、RVDS 端口、newlib int32_t）
    两边相同，会互相抵消。

    诚实声明：这**不等于** ARMCC 通过。AC5 独有的坑（C11 关键字等）
    要靠 verify_changes 里那几条人工规则守；反过来 GCC 也不含 AC5 的
    --diag_error=warning 全部检查。
    """
    print("\n[可选] GCC 差分语法体检（非 ARMCC 等价，--gcc-check 触发）")
    script = HERE / "gcc_syntax_check.py"
    if not script.exists():
        step.bad("INCOMPLETE: 找不到 gcc_syntax_check.py，差分体检未运行")
        return
    baseline_dir = tempfile.TemporaryDirectory(prefix="polar-gcc-baseline-")
    base = Path(baseline_dir.name) / "worktree"
    res = git(repo, "worktree", "add", "--detach", str(base), "HEAD")
    if res.returncode != 0:
        step.bad("INCOMPLETE: 无法创建基线 worktree，差分体检未运行",
                 (res.stderr or res.stdout).strip()[:160])
        baseline_dir.cleanup()
        return
    try:
        chk = subprocess.run(
            [sys.executable, str(script), str(repo), "--baseline", str(base)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = ((chk.stdout or "") + (chk.stderr or "")).strip().splitlines()
        if chk.returncode == 0:
            step.ok("补丁未引入新的 GCC 诊断（" + out[-1][:90] + "）")
        else:
            tail = [x.strip()[:150] for x in out if x.strip().startswith("NEW")]
            step.bad("GCC 差分发现补丁新增诊断",
                     " | ".join(tail[:6]) or (out[-1] if out else "")[:150])
    finally:
        git(repo, "worktree", "remove", "--force", str(base))
        baseline_dir.cleanup()


def main() -> int:
    ap = argparse.ArgumentParser(description="把固件工程准备成英雄板可驾驶状态")
    ap.add_argument("repo", help="StandardRobotpp 仓库路径")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--revert", action="store_true", help="按安装前快照撤销，后续改动会阻止回退")
    mode.add_argument("--check-only", action="store_true", help="只检查指定工作树，禁止自动安装/改写")
    ap.add_argument("--robot", choices=sorted(ROBOT_PROFILES), default="hero",
                    help="准备哪个兵种的工程。C 路（DT7 键鼠）两个兵种都成立："
                         "__RC_TYPE 与 DT7 解码都在 robot_param.h/remote_control.c 里不分兵种，"
                         "差别只是改哪个参数文件的 MOUSE_SENSITIVITY。"
                         "默认 hero = 英雄（麦轮）；步兵用 --robot infantry")
    ap.add_argument("--rc", choices=sorted(RC_TYPE_NAMES), default="dt7",
                    help="车上接收机配套的遥控器类型。默认 dt7 = DT7 遥控器 + DR16 接收机"
                         "（18 字节 SBUS 帧自带键盘/鼠标位）；上游仓库默认写的是 et08a")
    ap.add_argument("--gcc-check", action="store_true",
                    help="额外跑一次 GCC 差分语法体检（需 arm-none-eabi-gcc）")
    ap.add_argument("--km", choices=sorted(KM_LINK_NAMES), default="rc",
                    help="键鼠链路档位（固件自己的 __CONTROL_LINK_KM 五档）。"
                         "默认 rc = 只认遥控器 = 现役车行为逐位不变；"
                         "要无线用客户端控键鼠才改成 vt/rc_vt/vt_rc")
    ap.add_argument("--km-fire-keys", action="store_true",
                    help="允许图传注入 Q/E（摩擦轮/开火相关）。默认不给，"
                         "开火权限不偷偷外送")
    ap.add_argument("--mouse-sens", default=DEFAULT_MOUSE_SENS,
                    help="英雄参数的 MOUSE_SENSITIVITY。云台每 1ms 积一次 mouse/该值，一个鼠标值会被保持约 14ms ⇒ 角速度≈1000*(每帧像素)/该值 rad/s。默认 20000（1000px/s 手速约 1.7rad/s）；仓库出厂 100000 慢到像没接上，想按出厂行为就 --mouse-sens 100000。注意这只管鼠标，摇杆是另一个常数 REMOTE_CONTROLLER_SENSITIVITY。")
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
    elif args.check_only:
        try:
            verify_changes(repo, step, args.rc, args.robot)
            compile_check(repo, step)
        except (OSError, ValueError, IndexError) as exc:
            step.bad("INCOMPLETE: 指定树缺少完整的待验证文件", str(exc))
    elif check_clean(repo, step):
        try:
            journal = FileJournal(repo, OWNED)
            with journal.locked():
                journal.begin()
                try:
                    switch_robot(repo, step, args.robot)
                    switch_rc_type(repo, step, args.rc)
                    switch_km_link(repo, step, args.km, args.km_fire_keys)
                    if args.mouse_sens:
                        switch_mouse_sensitivity(repo, step, args.mouse_sens,
                                                 ROBOT_PROFILES[args.robot]["param"])
                    if apply_patch(repo, step):
                        verify_changes(repo, step, args.rc, args.robot)
                        compile_check(repo, step)
                        if args.gcc_check:
                            gcc_differential_check(repo, step)
                finally:
                    journal.finish()
        except (SnapshotError, OSError, RuntimeError) as exc:
            step.bad("文件保护/准备操作失败", str(exc))

    print("\n" + "=" * 62)
    if step.failures:
        print(f"结论：NO-GO，{len(step.failures)} 项未通过")
        for name in step.failures:
            print(f"  - {name}")
        print("\n不要拿去 Keil 编译；先解决上面这些。")
        return 1
    for name in step.warnings:
        print(f"提醒：{name}")
    if args.revert:
        print("回退完成：已恢复安装前内容；这不是构建通过报告。")
        return 0
    print("结论：GO —— 指定工程的离线检查通过；尚未验证 Keil 编译或实机。")
    print(CHECKLIST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
