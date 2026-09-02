"""Display-only localization for the Jello ClickGUI.

Registry keys and persisted option values deliberately stay in English.  The
renderer translates only what the player sees, so language changes cannot
break protocol bindings, config migration, hotbar assignments, or old GUIs.
"""

from __future__ import annotations

import re
from typing import Any


LANGUAGE_SETTING = "Language"
LANGUAGE_ENGLISH = "English"
LANGUAGE_CHINESE = "简体中文"

CATEGORY_ZH = {
    "Combat": "战斗",
    "Movement": "移动",
    "Vision": "视觉",
    "Strategy": "战术",
    "System": "系统",
    "Render": "渲染",
}

MODULE_ZH = {
    "Scenario": "运行场景",
    "StartupVisual": "启动视觉",
    "MatchMode": "比赛模式",
    "RobotProfile": "机器人预设",
    "AllianceProfile": "阵营预设",
    "ConfigManager": "配置管理",
    "ArmorAutoAim": "装甲自瞄",
    "EliminationFX": "淘汰特效",
    "AudioFeedback": "声音反馈",
    "EnergyAutoAim": "能量机关自瞄",
    "ArmorLock": "装甲锁定",
    "HeroLob": "英雄吊射",
    "FireControlStub": "火控接口",
    "SpinMode": "小陀螺",
    "AutoSpinOnHit": "受击自动小陀螺",
    "ChassisAssist": "底盘辅助",
    "PowerGuard": "功率保护",
    "CameraFeed": "图传画面",
    "TongjiVisionBridge": "同济视觉桥接",
    "CameraCalibration": "相机标定",
    "Armor3DESP": "装甲三维透视",
    "RobotOverlay": "机器人透视",
    "RadarOverlay": "雷达覆盖层",
    "MapMarker": "地图标记",
    "TacticalMap": "战术地图",
    "LiquidTacticalMap": "液态战术地图",
    "SentinelCommand": "哨兵指令",
    "AirSupport": "空中支援",
    "MatchTimer": "比赛计时",
    "BaseOutpostStatus": "基地与前哨站",
    "VictoryPointStatus": "胜利点状态",
    "EconomyPanel": "经济面板",
    "ProjectileShop": "弹丸商店",
    "MatchChat": "比赛聊天",
    "QuickActionWheel": "快捷轮盘",
    "ThermalPowerPanel": "热量功率面板",
    "BuffTimeline": "增益时间轴",
    "MQTTLink": "MQTT 连接",
    "UDPVideo": "UDP 图传",
    "SerialBridge": "串口桥接",
    "HUD": "战斗界面",
    "UIScale": "界面缩放",
    "Crosshair": "准星",
    "CombatTargetHUD": "战斗目标面板",
    "MinecraftCombatHUD": "Minecraft 战斗界面",
    "ChassisGimbalIndicator": "底盘云台指示器",
    "ClickGui": "点击界面",
    "GimbalPower": "云台供电",
    "PowerLimit": "功率限制",
    "SpeedLimit": "速度限制",
    "Capacitor": "电容状态",
    "FrictionWheel": "摩擦轮",
    "LockState": "锁定状态",
    "BuffStatus": "增益状态",
    "ProjectileAllowance": "发弹允许量",
    "JumpPTEWheelLES": "机构状态组",
}

# Phrases whose natural Chinese order cannot be produced by token joining.
SETTING_ZH = {
    "Language": "界面语言",
    "Render Backend": "渲染后端",
    "Save Layout": "保存布局",
    "Old ClickGUIs": "旧版点击界面",
    "Combat Preset": "战斗界面预设",
    "GUI Scale": "原版界面倍率",
    "Scale Multiplier": "缩放系数",
    "Right Display": "右侧显示",
    "Module List": "功能列表",
    "ModuleList Style": "功能列表样式",
    "ModuleList Alignment": "功能列表对齐",
    "ModuleList Order": "功能列表排序",
    "ModuleList Surface": "功能列表表面",
    "Module Animation": "功能列表动画",
    "Module Tags": "功能标签",
    "Jello List Size": "Jello 列表大小",
    "Jello List Animations": "Jello 列表动画",
    "Jello List Sound": "Jello 列表音效",
    "Dynamic Island": "灵动岛",
    "White": "纯白",
    "Threat": "威胁度",
    "Target HUD": "目标面板",
    "Target Style": "目标样式",
    "Target RPM": "目标转速",
    "Tactical Map": "战术地图",
    "Map Size": "地图大小",
    "Map Marks": "地图标记",
    "Robot Dots": "机器人点位",
    "Status Display": "状态显示",
    "Show Values": "显示数值",
    "Show Labels": "显示标签",
    "Entity Color": "实体颜色",
    "Pointer Style": "指针样式",
    "Dock Animation": "状态栏动画",
    "Scale": "缩放",
    "Size": "大小",
    "Style": "样式",
    "Mode": "模式",
    "Preset": "预设",
    "Profile": "配置",
    "Role": "兵种",
    "Side": "阵营",
    "Alliance": "阵营",
    "Source": "来源",
    "Opacity": "不透明度",
    "Density": "信息密度",
    "Visual Tone": "视觉色调",
    "Watermark": "水印",
    "KeyBinds": "按键列表",
    "Robot List": "机器人列表",
    "Status Cards": "状态卡片",
    "RM Indicators": "RM 状态指示",
    "Draw Fov": "绘制视场范围",
    "Circle Size": "圆圈大小",
    "ESP Style": "透视样式",
    "Line Width": "线宽",
    "Show Depth": "显示深度",
    "Show Prediction": "显示预测",
    "Show Angle": "显示角度",
    "Show Mode": "显示模式",
    "Show State": "显示状态",
    "Show Speed": "显示速度",
    "Show Bar": "显示条形图",
    "Show Lock": "显示锁定",
    "Show Limit": "显示限制",
    "Show Voltage": "显示电压",
    "Show Progress": "显示进度",
    "Show Scores": "显示比分",
    "Show Stage": "显示阶段",
    "Show Startup": "显示启动页",
    "Show Cost": "显示花费",
    "Show Status Line": "显示状态行",
    "Auto Connect": "自动连接",
    "Auto Save": "自动保存",
    "Auto Scale": "自动缩放",
    "Auto Disable": "自动关闭",
    "Auto Limit": "自动限幅",
    "Power Guard": "功率保护",
    "Power Limit": "功率上限",
    "Chassis Power": "底盘功率",
    "Heat Guard": "热量保护",
    "Heat Warn": "热量警告",
    "Energy Warn": "能量警告",
    "Warn Below": "低于此值警告",
    "Warn Low": "低值警告",
    "Glow Alert": "发光警告",
    "Use Glow": "使用辉光",
    "Lock Source": "锁定来源",
    "Lock Style": "锁定样式",
    "Lock Point": "锁定点",
    "Pulse Locked": "锁定时脉冲",
    "Only During Match": "仅比赛期间",
    "Require Confirm": "需要确认",
    "Require Fresh Telemetry": "要求新鲜遥测",
    "Require Referee Link": "要求裁判系统连接",
    "Open Deploy Interface": "打开部署界面",
    "Arm Assisted Lob": "启用辅助吊射",
    "Disarm Assisted Lob": "关闭辅助吊射",
    "Preview Lob": "预览吊射",
    "Calibrate Lob Pitch": "标定吊射俯仰",
    "Calibrate Lob Yaw": "标定吊射偏航",
    "Muzzle Speed": "弹丸初速",
    "Muzzle Length": "枪管长度",
    "Pitch Offset": "俯仰偏移",
    "Yaw Offset": "偏航偏移",
    "Spin Speed": "小陀螺速度",
    "Spin Preview": "小陀螺预览",
    "Minimum Damage": "最低受击伤害",
    "Minimum Buffer": "最低缓冲能量",
    "Buffer Protect": "缓冲能量保护",
    "Prediction Labels": "预测标签",
    "Predict Plates": "预测装甲板",
    "Predict Horizon": "预测时间范围",
    "Vision Source": "视觉来源",
    "Vision Kill Sensitivity": "视觉淘汰灵敏度",
    "Camera ID": "相机编号",
    "Capture Width": "采集宽度",
    "Capture Height": "采集高度",
    "Telemetry Timeout": "遥测超时",
    "HUD Scale": "战斗界面缩放",
    "HUD Refresh Rate": "战斗界面刷新率",
    "UI Volume": "界面音量",
    "Sound Enabled": "启用声音",
    "Sound Theme": "声音主题",
    "Sound Volume": "声音音量",
    "Animation Speed": "动画速度",
    "Wallpaper Profile": "壁纸配置",
    "Background Mode": "背景模式",
    "Background Zoom": "背景缩放",
    "Import Wallpaper": "导入壁纸",
    "Reset Wallpaper": "重置壁纸",
    "Load On Start": "启动时加载",
    "Save Current": "保存当前配置",
    "Import Config": "导入配置",
    "Reload Profile": "重新加载配置",
    "Restore Compact HUD": "恢复紧凑界面",
    "Official Map": "官方地图",
    "Official Limits": "官方限制",
    "Robot ID": "机器人编号",
    "Team Theme": "队伍主题",
    "Team Status": "队伍状态",
    "Own Base": "我方基地",
    "Enemy Base": "敌方基地",
    "Outposts": "前哨站",
    "Victory Points": "胜利点",
    "Control Zone": "控制区",
    "Referee Notices": "裁判系统提示",
    "Projectile Allowance": "发弹允许量",
    "Ammo Type": "弹丸类型",
    "Tech Level": "科技等级",
    "Small Buff": "小增益",
    "Large Buff": "大增益",
    "Anti Rotation": "反小陀螺",
}

OPTION_ZH = {
    "English": "英语",
    "简体中文": "简体中文",
    "Auto": "自动",
    "Enabled": "启用",
    "Disabled": "关闭",
    "On": "开",
    "Off": "关",
    "None": "无",
    "Empty": "空",
    "Default": "默认",
    "default": "默认",
    "Right": "右侧",
    "Left": "左侧",
    "Upper Right": "右上",
    "Upper Left": "左上",
    "Lower Right": "右下",
    "Lower Left": "左下",
    "Small": "小",
    "Normal": "标准",
    "Tiny": "微型",
    "Compact": "紧凑",
    "Wide": "宽幅",
    "Full": "完整",
    "Minimal": "极简",
    "Thin": "轻量",
    "High": "高",
    "Medium": "中",
    "Low": "低",
    "Manual": "手动",
    "Vision": "视觉",
    "Radar": "雷达",
    "Team": "队伍",
    "Category": "分类",
    "Ascending": "升序",
    "Descending": "降序",
    "Unified GPU": "统一 GPU",
    "Compatibility Painter": "兼容绘制器",
    "Minecraft 1.21.11": "Minecraft 1.21.11",
    "Polar": "POLAR",
    "LiquidGlass": "液态玻璃",
    "SubGlass": "次级玻璃",
    "MainGlass": "主玻璃",
    "LiquidAuto": "液态自动",
    "LiquidBars": "液态条形",
    "LiquidCards": "液态卡片",
    "LegacyOrbit": "传统环形",
    "LegacyBars": "传统条形",
    "Show all": "显示全部",
    "Hide": "收起",
    "Run": "执行",
}

_TOKEN_ZH = {
    "auto": "自动", "show": "显示", "hide": "隐藏", "enable": "启用", "disable": "关闭",
    "preview": "预览", "reset": "重置", "restore": "恢复", "import": "导入", "export": "导出",
    "save": "保存", "load": "加载", "open": "打开", "close": "关闭", "send": "发送",
    "mode": "模式", "style": "样式", "size": "大小", "scale": "缩放", "color": "颜色",
    "speed": "速度", "power": "功率", "heat": "热量", "energy": "能量", "limit": "限制",
    "warn": "警告", "source": "来源", "target": "目标", "map": "地图", "status": "状态",
    "robot": "机器人", "base": "基地", "shield": "护盾", "buff": "增益", "timeline": "时间轴",
    "sound": "声音", "volume": "音量", "animation": "动画", "background": "背景", "visual": "视觉",
    "width": "宽度", "height": "高度", "offset": "偏移", "radius": "半径", "distance": "距离",
    "left": "左", "right": "右", "upper": "上", "lower": "下", "only": "仅", "during": "期间",
    "match": "比赛", "team": "队伍", "alliance": "阵营", "profile": "配置", "level": "等级",
    "opacity": "不透明度", "smooth": "平滑", "follow": "跟随", "mirror": "镜像", "repeat": "重复",
    "priority": "优先级", "direction": "方向", "duration": "持续时间", "cooldown": "冷却",
    "predict": "预测", "prediction": "预测", "labels": "标签", "label": "标签", "values": "数值",
    "bars": "条形", "bar": "条", "glow": "辉光", "alert": "警报", "lock": "锁定",
    "unit": "单位", "host": "主机", "port": "端口", "baud": "波特率", "device": "设备",
    "local": "本地", "external": "外部", "official": "官方", "mock": "模拟", "request": "请求",
    "requests": "请求", "confirm": "确认", "fresh": "新鲜", "telemetry": "遥测", "referee": "裁判系统",
    "x": "横向", "y": "纵向", "up": "上", "down": "下", "arc": "弧线", "gravity": "重力",
}


def chinese_enabled(registry: Any) -> bool:
    module = registry.get("ClickGui") if registry is not None else None
    setting = module.get_setting(LANGUAGE_SETTING) if module is not None else None
    return bool(setting is not None and str(setting.value) == LANGUAGE_CHINESE)


def category_label(value: str, chinese: bool) -> str:
    return CATEGORY_ZH.get(str(value), str(value)) if chinese else str(value)


def module_label(value: str, chinese: bool) -> str:
    return MODULE_ZH.get(str(value), str(value)) if chinese else str(value)


def _tokenized_label(value: str) -> str:
    words = re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?(?:mm|ms|px|W|V|%)?|[^\x00-\x7f]+", value)
    if not words:
        return value
    translated: list[str] = []
    changed = False
    for word in words:
        replacement = _TOKEN_ZH.get(word.lower(), word)
        changed = changed or replacement != word
        translated.append(replacement)
    return "".join(translated) if changed else value


def setting_label(value: str, chinese: bool) -> str:
    value = str(value)
    if not chinese:
        return value
    slot = re.fullmatch(r"Slot\s+(\d+)", value)
    if slot:
        return f"功能栏 {slot.group(1)}"
    return SETTING_ZH.get(value, _tokenized_label(value))


def option_label(value: Any, chinese: bool) -> str:
    text = str(value)
    if not chinese:
        return text
    if text in MODULE_ZH:
        return MODULE_ZH[text]
    if text in CATEGORY_ZH:
        return CATEGORY_ZH[text]
    return OPTION_ZH.get(text, SETTING_ZH.get(text, _tokenized_label(text)))


def action_label(value: str, chinese: bool) -> str:
    return option_label(value, chinese)


def profile_language_badge(chinese: bool) -> str:
    return "中文" if chinese else "EN"
