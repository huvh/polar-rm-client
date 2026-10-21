"""Display-only HUD vocabulary.

Call after layout/colour/state decisions. ``hud_text`` is for renderer-owned
status strings, never opaque names, ports, diagnostics, identifiers or payloads.
Templates substitute runtime fields only *after* translation. Raw measurements
and raw status keys deliberately remain independent of the selected language.
"""
from __future__ import annotations

import re

from .jello_locale import CATEGORY_ZH, MODULE_ZH

HUD_ZH = {
    "Sentry map intervention (fee confirmation)": "哨兵地图干预（费用确认）",
    "1 = Supply-point ammunition": "1 = 补血点补弹", "2 = Supply-station physical ammunition": "2 = 补给站实体补弹",
    "3 = Remote ammunition": "3 = 远程补弹", "4 = Remote healing": "4 = 远程回血",
    "5 = Confirm respawn": "5 = 确认复活", "6 = Confirm paid respawn": "6 = 确认金币复活",
    "7 = Attack stance": "7 = 进攻姿态", "8 = Defense stance": "8 = 防御姿态", "9 = Movement stance": "9 = 移动姿态",

    "Infantry only: activate energy mechanism": "仅步兵：激活能量机关",
    "Aerial operator: same-team dart target": "空中云台手：本方飞镖目标",
    "1 = Outpost": "1 = 前哨站", "2 = Base fixed": "2 = 基地固定目标",
    "3 = Base random fixed": "3 = 基地随机固定目标", "4 = Base random moving": "4 = 基地随机移动目标",
    "5 = Base terminal moving": "5 = 基地末端移动目标",
    "Opening request (never closes the gate):": "开闸请求（不会关闭闸门）：",
    "No opening request": "不请求开闸", "Request opening": "请求开闸",
    "Engineer only: assembly operation": "仅工程：装配操作",
    "0 = Start exchange": "0 = 开始兑换", "1 = Confirm assembly": "1 = 确认装配",
    "2 = Cancel": "2 = 取消", "Difficulty (1-4):": "难度（1-4）：", "Air Support": "空中支援",

    "rings": "环", "UNKNOWN": "未知",
    "Rune Activate (energy mechanism)": "激活能量机关", "Dart Command": "飞镖指令",
    "Sentry Control": "哨兵控制", "Assembly Command": "工程指令",
    "Performance Selection (from RobotProfile)": "性能选择（机器人预设）",
    "Event commands": "赛事指令", "Referee event command:": "裁判系统赛事指令：",
    "RuneActivateCommand": "能量机关激活指令", "DartCommand": "飞镖指令",
    "SentryCtrlCommand": "哨兵控制指令", "AssemblyCommand": "工程指令",
    "Activate value:": "激活操作：", "1 = activate": "1 = 激活", "0 = cancel": "0 = 取消",
    "Target robot ID:": "目标机器人编号：", "Open gate:": "打开闸门：",
    "False": "否", "True": "是", "Command ID (consult the selected referee protocol):": "指令编号（请查阅当前裁判系统协议）：",
    "Operation (1=exchange ore,2=submit,3=stash):": "操作（1=兑换矿石，2=提交，3=暂存）：",
    "Difficulty (1-3):": "难度（1-3）：",
    "AIM": "瞄准", "LOCK": "锁定", "TRACK": "跟踪", "IDLE": "待机",
    "HP": "生命", "HEAT": "热量", "AMMO": "弹药", "RUNE": "能量机关",
    "SMALL": "小能量", "LARGE": "大能量", "CW": "顺时针", "CCW": "逆时针",
    "TRUE": "是", "FALSE": "否", "INACTIVE": "未激活", "ACTIVATING": "激活中", "ACTIVE": "已激活", "PLAYING": "比赛中", "Armor Target": "装甲目标", "Energy Target": "能量机关目标",
    "RobotTargetHUD": "装甲目标", "EnergyTargetHUD": "能量机关目标", "Robot": "机器人",
    "LOCKOUT": "锁出", "ESTOP": "急停", "OK": "正常",
    "RADAR": "雷达", "ALLY": "我方", "ENEMY": "敌方", "ENMY": "敌方",
    "RED": "红方", "BLUE": "蓝方", "Red": "红方", "Blue": "蓝方", "YOU": "本方",
    "NEUTRAL": "中立", "NONE": "无", "BASE": "基地", "A BASE": "我方基地",
    "E BASE": "敌方基地", "EBASE": "敌方基地", "E.BASE": "敌方基地",
    "OWN BASE": "我方基地", "OUTPOST": "前哨站", "OUT": "前哨", "POST": "前哨",
    "CTRL": "控制", "CONTROL": "控制", "VP": "胜利点", "SCORE": "比分",
    "SHIELD": "护盾", "GOLD": "金币", "PRICE": "价格", "POWER": "功率",
    "PWR": "功率", "SPEED": "速度", "SPD": "速度", "CAP": "电容", "BUF": "缓冲",
    "ONLINE": "在线", "OFFLINE": "离线", "DOWN": "已毁", "ALIVE": "存活", "DEAD": "已毁",
    "WAITING": "等待", "NOT_STARTED": "未开始", "PREPARE": "准备", "SELF_CHECK": "自检",
    "COUNTDOWN": "倒计时", "MATCH": "比赛中", "SETTLEMENT": "结算", "RESULTS": "赛果",
    "modules": "模块", "Hotkeys": "快捷键", "KeyBinds": "按键绑定",
    "RobotListHud": "机器人列表", "RMIndicatorsHud": "机器人状态",
    "GIMPOWER": "云台供电", "POWERLIM": "功率上限", "SPEEDLIM": "速度上限",
    "FRIC": "摩擦轮", "ANTIRO": "反小陀螺", "ATKBUF": "攻击增益", "DEFBUF": "防御增益",
    "JUP": "跳跃", "WHE": "轮组", "SBF": "攻击", "LBF": "防御",
    "SHT": "发射", "CV": "图传", "ARM": "装甲", "MAIN": "主控",
    "LNK": "链路", "DRV": "驾驶", "GIM": "云台", "MOT": "运动",
    "ON": "开", "OFF": "关", "COOL": "冷却",
    "STUCK": "无响应", "NO_FEEDBACK": "无反馈", "STALE_FEEDBACK": "反馈过期", "NO_MOTION": "未运动",
    "PASSIVE": "被动", "CLIENT": "客户端", "VISION": "视觉", "REMOTE": "遥控器", "BLOCKED": "受阻",
    "DRIVE BLOCKED": "驾驶受阻", "ROLE MISMATCH": "兵种不符", "LINK OFF": "链路断开",
    "official map asset missing": "缺少官方地图资源",
    "Attack Boost": "攻击增益", "Defense Boost": "防御增益", "Heat Cooling": "冷却增益",
    "Chassis Power": "底盘功率", "Health Regen": "生命回复", "Exchange Ammo": "弹药兑换", "Terrain": "地形增益",
    "Time left": "剩余时间", "Ally": "我方", "Enemy": "敌方", "Base": "基地", "Shield": "护盾",
    "Post": "前哨", "Kills": "击败", "Ammo": "弹药", "Gold": "金币",
    **{name[:3].upper(): label for name, label in CATEGORY_ZH.items()},
}
HUD_TEMPLATES_ZH = {
    "{title} Tactical Map": "{title} 战术地图",
    "{title} official map": "{title} 官方地图",
    "{width}m x {height}m official field": "{width}m x {height}m 官方场地",
    "AIR LOCK · {label} {confidence}": "空中锁定 · {label} {confidence}",
    "DIST {value}": "距离 {value}",
    "DROP {name}": "放置 {name}",
    "ROBOT {port} · {segments} seg · {role}#{id} {limit}m/s": "机器人 {port} · {segments} 段 · {role}#{id} {limit}m/s",
    "ROLE MISMATCH UI#{selected}!=ROBOT#{reported}": "兵种不符 界面#{selected}!=机器人#{reported}",
}
# Longest first prevents BASE from consuming OWN BASE and preserves units/IDs.
_STATUS_WORDS = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(key) for key in sorted(HUD_ZH, key=len, reverse=True)) + r")(?![A-Za-z0-9_])")


def hud_text(value: str, chinese: bool) -> str:
    """Translate bounded, renderer-owned status copy, never its source value."""
    text = str(value)
    if not chinese:
        return text
    return _STATUS_WORDS.sub(lambda match: HUD_ZH[match[0]], text)


def hud_template(template: str, chinese: bool, **values: object) -> str:
    return (HUD_TEMPLATES_ZH.get(template, template) if chinese else template).format(**values)


def hud_buff_name(value: str, chinese: bool) -> str:
    """Known referee names only; arbitrary/custom buff names remain intact."""
    text = str(value)
    if not chinese:
        return text
    if re.fullmatch(r"MECH\d+", text):
        return "机制" + text[4:]
    if re.fullmatch(r"Buff \d+", text):
        return "增益 " + text[5:]
    return HUD_ZH.get(text, text)


def hud_module_name(value: str, chinese: bool) -> str:
    return MODULE_ZH.get(str(value), str(value)) if chinese else str(value)


class HudDisplayText(str):
    """Raw text for existing sizing plus an explicitly supplied draw string."""
    def __new__(cls, raw: str, display: str):
        value = super().__new__(cls, raw)
        value.display = display
        return value
