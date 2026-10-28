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

# Crosshair editor/import identifiers only; persisted protocol keys stay English.
_CROSSHAIR_ZH = {
    "Match Team Identities": "比赛队伍资料 / 校徽",
    "Crosshair Scale": "准星整体大小",
    "Open Crosshair Editor": "打开CS准星编辑器", "Import Crosshair Code": "导入准星代码 / 文本",
    "Import Crosshair File": "导入准星文件", "Crosshair Import Details": "准星导入参数与限制",
    "CS2 Style": "CS准星样式编号", "Length": "准星长度", "Gap": "准星间距", "Thickness": "准星粗细",
    "Center Dot": "中心点", "T Shape": "T形准星", "Geometry Units": "准星尺寸单位",
    "Red": "红色通道", "Green": "绿色通道", "Blue": "蓝色通道", "Alpha": "不透明度",
    "Color Mode": "颜色模式", "Use Alpha": "使用不透明度", "Outline Mode": "描边模式",
    "Outline Width": "描边宽度", "Outline Red": "描边红色", "Outline Green": "描边绿色",
    "Outline Blue": "描边蓝色", "Outline Alpha": "描边不透明度", "Follow Recoil": "跟随后坐力（仅保留）",
    "Dynamic Spread Limit": "动态散布上限（仅保留）", "Split Distance": "散布分离距离（仅保留）",
    "Inner Split Alpha": "内侧散布透明度（仅保留）", "Outer Split Alpha": "外侧散布透明度（仅保留）",
    "Split Size Ratio": "散布分离比例（仅保留）", "Fixed Gap": "旧版固定间距（仅保留）",
    "Weapon Gap": "武器间距（仅保留）", "Scope Dot Scale": "瞄准镜点缩放（仅保留）",
    "Scope Dot Uses Color": "瞄准镜点使用准星颜色（仅保留）", "Source Format": "导入来源格式",
    "Imported Code": "原始准星分享码", "Import Notes": "准星规范限幅说明",
    "CS2": "CS准星", "Pixels": "参考分辨率像素", "Legacy": "旧版尺寸单位",
}

CATEGORY_ZH = {
    "Combat": "战斗",
    "Movement": "移动",
    "Vision": "视觉",
    "Strategy": "战术",
    "System": "系统",
    "Render": "渲染",
}

MODULE_ZH = {
    "ControllerAngles": "实体控制器角度",
    "TopMatchBar": "CS顶部战况",
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
    "MinecraftInventory": "Minecraft 模块背包",
    "InjuryStatistics": "受伤害统计",
    "MatchSettlement": "比赛结算",
    "DartPanel": "飞镖面板",
    "SkillConfiguration": "性能点与技能配置",
    "ReloadingPanel": "补弹与换弹面板",
    "RuneRingStatus": "能量机关环数",
    "ResourceIsland": "资源岛",
    "GainZone": "增益点",
    "UWBStatus": "UWB 定位状态",
    "ArmorStatus": "护甲状态",
    "WirelessCharging": "无线充电",
    "MinecraftBuffs": "Minecraft 增益效果",
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
    "Angle RX Port": "角度接收串口",
    "Angle TX Port": "角度转发串口",
    "Angle Output": "角度发送出口",
    "Official Client Serial": "官方选手端串口",
    "Legacy Receiver": "旧图传接收端直发",
    "VT02 Encoder": "VT02 单编码器直发",
    "Forward Angles": "启用角度转发",
    "Angle Mock Writes": "角度模拟发送",
    "Arm Angle Forward": "授权角度转发",
    "Angle Auto Arm": "启动自动授权角度",
    "Disarm Angle Forward": "撤销角度转发授权",
    "Show Angle Status": "查看角度链路状态",
    "Open Keybind Manager": "打开键盘绑定管理器",
    "Mouse Sensitivity": "鼠标灵敏度", "Invert Mouse Y": "反转鼠标垂直方向", "Mouse Wheel Scale": "鼠标滚轮倍率",
    "Language": "界面语言",
    "Record DT7 Safety Test": "记录DT7物理安全测试",
    "Open Injury Statistics": "打开伤害计分板",
    "Open Settlement": "打开比赛结算",
    "Open Dart Panel": "打开飞镖面板",
    "Open Skill Configuration": "打开性能点 / 技能配置",
    "Open Minecraft Inventory": "打开模块背包",
    "Open Reloading Panel": "打开补弹 / 换弹",
    "Chassis Points": "底盘性能点（草稿）",
    "Shooter Points": "发射性能点（草稿）",
    "Shooter Draft": "发射机构类型（草稿）",
    "Chassis Draft": "底盘类型（草稿）",
    "Gate Draft": "补弹闸口（草稿）",
    "Quantity Draft": "补弹数量（草稿）",
    "Auto Open": "比赛结束自动打开",
    "Icon Scale": "图标缩放",
    "Show in Island": "灵动岛显示",
    "Show Status": "显示状态",
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
    "Alliance": "阵营", "Season": "规则赛季",
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
    "Legacy Channel": "旧图传信道",
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

# Explicit display labels keep technical identifiers out of heuristic translation.
MODULE_ZH.update({
    "EmergencyStop": "紧急停止",
    "MatchReadiness": "比赛就绪检查",
    "RobotLink": "机器人连接",
})

SETTING_ZH.update({
    "Kill Feed": "击杀信息流",
    "17mm": "17 mm 弹丸", "42mm": "42 mm 弹丸", "3D Depth": "三维深度",
    "Allow Drive": "允许底盘驾驶", "Allow Spin Key": "允许小陀螺按键",
    "Anchor Policy": "锚点策略", "Arc": "弹道弧线", "Armor Boxes": "装甲框",
    "Armor Count": "装甲数量", "BF6 Progress": "战地 6 进度条",
    "Battlefield Icons": "战地图标", "Baud": "波特率", "Bearing": "方位角",
    "Board Columns": "棋盘格列数", "Board Rows": "棋盘格行数",
    "Bonus Tags": "加分标签", "Bridge Host": "桥接主机", "Bridge Port": "桥接端口",
    "Buffer": "缓冲能量", "Buffs": "增益效果", "CC Hz": "自定义控制器发送频率",
    "CC Mock Writes": "自定义控制器模拟输出", "CC Port": "自定义控制器端口",
    "Capture Chessboard": "采集棋盘格", "Card Icons": "卡牌图标", "Chrome": "界面装饰",
    "Client Chassis Drive": "客户端底盘驾驶", "Client Gimbal Control": "客户端云台控制",
    "Closed Lines": "收起时行数", "Color": "颜色", "Combo Icons": "连杀图标",
    "Combo Subtitle": "连杀字幕", "Combo Window": "连杀判定时限", "Command": "指令",
    "Confirm Prompt": "确认提示", "Confirm Relocalization": "确认重定位",
    "Cooldown": "冷却时间", "Custom Controller Egress": "自定义控制器输出",
    "Custom Disable Sound": "自定义关闭音效", "Custom Enable Sound": "自定义开启音效",
    "Custom Invalid Sound": "自定义无效操作音效", "DT7 Allow Fire Keys": "DT7 允许开火按键",
    "DT7 Port": "DT7 端口", "DT7 Real TX": "DT7 真实发送", "Dead Zone": "死区",
    "Desktop Safe": "桌面安全模式", "Dim Overlay": "遮罩暗化", "Direct DT7 Egress": "DT7 直连输出",
    "Direction": "方向", "Distance": "距离", "Down": "下方", "Drive Channel": "驾驶通道",
    "Duration": "持续时间", "Element Visibility": "元素可见性", "Enabled": "启用",
    "Evidence Mode": "证据模式", "Export Tongji YAML": "导出同济 YAML",
    "External Device": "外部设备", "Fade": "淡出", "Fade Seconds": "淡出时长",
    "Follow": "跟随", "Fov": "视场角", "Gimbal Slew": "云台转速上限",
    "Glass Strength": "玻璃效果强度", "Glass Style": "玻璃样式", "Gold": "金币",
    "Gravity": "重力加速度", "Heat": "热量", "Heat Color": "热量配色",
    "Height Delta": "高度差", "Hero Type": "英雄类型", "High Light": "高亮",
    "High Res Optimize": "高分辨率优化", "Hit Info": "命中信息", "Honor Badges": "荣誉徽章",
    "Host": "主机", "Icon Style": "图标样式", "Import Disable Sound": "导入关闭音效",
    "Import Enable Sound": "导入开启音效", "Import Invalid Sound": "导入无效操作音效",
    "Infantry Chassis": "步兵底盘", "Infantry Shooter": "步兵发射机构",
    "Invalidate Relocalization": "使重定位失效", "JUP": "JUP 机构状态", "LES": "LES 机构状态",
    "Label Style": "标签样式", "Lead Time": "提前量", "Left": "左侧", "Level": "等级",
    "Limit": "上限", "Link Mode": "连接方式", "Listen": "监听", "Local Device": "本地设备",
    "Local Model": "本地模型", "Lock Target Bonus": "锁定目标加分", "Lower Left": "左下",
    "Lower Right": "右下", "Map": "地图", "Mark Type": "标记类型", "Match Progress": "比赛进度",
    "Match Scope": "适用比赛制式", "Max Rate": "最大频率", "Max Roll": "最大横滚角",
    "Max Targets": "最大目标数", "Mirror": "镜像", "Mirror Blue": "蓝方镜像",
    "Mirror Tactical Map": "镜像战术地图", "Mock Output": "模拟输出", "Mock Request": "模拟请求",
    "Mock Requests": "模拟请求", "Mock Writes": "模拟输出", "Module Toggle Sounds": "模块开关音效",
    "Motion Quality": "动画质量", "Only Secondary": "仅次级界面", "Open Lines": "展开时行数",
    "Open Style": "展开样式", "PTE": "PTE 机构状态", "Palette": "配色",
    "Parallax Strength": "视差强度", "Pitch Calibration Tolerance": "俯仰标定容差",
    "Port": "端口", "Posture": "姿态", "Predict": "预测", "Preview Disable": "试听关闭音效",
    "Preview Enable": "试听开启音效", "Preview FX": "预览特效", "Preview Invalid": "试听无效操作音效",
    "Preview Sequence": "预览序列", "Priority": "优先级", "Pulse Last 30s": "最后 30 秒脉冲提示",
    "Pulse Overrun": "超限脉冲提示", "Qualification Actions": "比赛资格操作",
    "Radar Level": "雷达等级", "Radar Pulse": "雷达脉冲", "Radio KM Egress": "无线键鼠输出",
    "Radius": "半径", "Radius M": "半径（米）", "Reassemble": "旧兼容项（不切换入口）",
    "Referee Profile": "裁判协议版本", "Reference Height": "参考高度", "Reference Width": "参考宽度",
    "Release E-Stop": "解除急停", "Renderer": "渲染器", "Repeat": "重复",
    "Rescan Serial Ports": "重新扫描串口", "Responsive Scale": "自适应缩放", "Right": "右侧",
    "Roster Scope": "机器人列表范围", "Run DT7 Link Selftest": "运行 DT7 连接自检",
    "Run Wireless KM Selftest": "运行无线键鼠自检", "Rune Type": "能量机关类型",
    "Safety Lock": "安全锁", "Score Metric": "计分依据", "Score Popup": "得分弹字",
    "Scrolling Icons": "滚动图标", "Second Step": "显示比赛制式选择", "Sectors": "扇区数量",
    "Send All": "发送给全队", "Send Hz": "发送频率", "Sentinel Control": "哨兵控制",
    "Shield": "护盾", "Show Bars": "显示条形图", "Show Health": "显示血量",
    "Show Kills": "显示击杀数", "Smooth": "平滑度", "Solve Calibration": "计算标定参数",
    "Source Motion Preview": "原始动画预览", "Special Mechanism": "特殊机构",
    "Local CS2 Assets": "本机CS2素材", "CS2 Feedback": "CS2购买反馈", "CS2 Native": "CS2原生",
    "Shop Layout": "购买页布局", "CS2 Grid": "CS2购买矩阵",
    "Speed Scale %": "速度比例（%）", "Square Size": "棋盘格边长", "Startup Style": "启动页样式",
    "Target": "目标", "Test Elimination": "测试击杀事件", "Timeline": "时间轴",
    "Trigger E-Stop": "触发急停", "UDP Port": "UDP 端口", "UDP Timeout": "UDP 超时",
    "Unit": "单位", "Up": "上方", "Upper Left": "左上", "Upper Right": "右上",
    "Valorant Icons": "无畏契约图标", "Vision NUC Occupied": "视觉小电脑占用",
    "Visual": "视觉效果", "WHE": "WHE 机构状态", "Warn": "警告",
    "X Offset": "横向偏移", "Y Offset": "纵向偏移", "Yaw Calibration Tolerance": "偏航标定容差",
    "Yaw Scale %": "偏航比例（%）",
})

OPTION_ZH.update({
    "Abort": "中止", "Accent": "强调色", "Action": "操作", "Adaptive": "自适应",
    "Aerial": "空中机器人", "All Kill Types": "全部击杀类型", "All Match Modes": "全部比赛制式",
    "All Roles": "全部兵种", "Ammo": "弹药", "Arm Match Control": "解锁比赛控制",
    "Armor": "装甲", "Armor Lock": "装甲锁定", "Attack": "进攻", "Auto Aim": "自动瞄准",
    "Automatic": "自动", "AUTO": "自动", "Backspace": "退格", "Balanced": "均衡",
    "Balanced30": "均衡 30 帧", "BarOnly": "仅状态条", "Battlefield 1": "战地 1",
    "Battlefield 5": "战地 5", "Battlefield 6": "战地 6", "BlackHole": "黑洞",
    "Blue": "蓝方", "Both": "两者", "Burst": "爆发", "CCW": "逆时针", "CW": "顺时针",
    "CT Blue": "CT 蓝色", "CampusSimulation": "校内模拟", "Card": "卡片", "Center": "居中",
    "Circle": "圆形", "Classic": "经典", "Clear": "清除", "ClickGUI": "配置界面",
    "Combat Focus": "战斗聚焦", "CombatCompact": "紧凑战斗", "Combo": "连杀", "Compass": "指南针",
    "Confirm": "确认", "Cooling": "冷却", "Cross": "十字", "Custom": "自定义", "Dart": "飞镖",
    "DebugFull": "完整调试", "Default Scrolling": "默认滚动",
    "Default3000925581Pkg": "默认场景壁纸", "Defense": "防守", "Delete": "删除",
    "Distance": "距离", "Dot": "圆点", "Down": "下", "DynamicIsland": "灵动岛",
    "Economy": "经济", "End": "末尾", "Enemy Outpost": "敌方前哨站", "Energy": "能量",
    "Engineer": "工程机器人", "Enhanced": "增强", "Enter": "回车", "Escape": "返回（Esc）",
    "Export Evidence": "导出证据", "Fade": "淡出", "Field": "现场", "Field Sign-off": "现场签字确认",
    "Fixed": "固定", "Flat 2D": "二维平面", "Flip": "翻转", "Fly": "飞入", "FlyFlip": "飞入翻转",
    "Free": "免费", "Friction Wheel": "摩擦轮", "Full HUD": "完整战斗界面", "Full Sheet": "完整面板",
    "Full Tactical": "完整战术界面", "FullCard": "完整卡片", "Gimbal": "云台", "GlowRows": "辉光列表",
    "GPU Auto": "GPU 自动", "Ground Robots": "地面机器人", "Health": "血量",
    "Heli Gimbal": "空中云台", "Hero": "英雄机器人", "Heavy": "重装机器人", "Hidden": "隐藏", "Home": "起始",
    "Icons Only": "仅图标", "Infantry1": "步兵一号", "Infantry2": "步兵二号", "Initials": "缩写",
    "Insert": "插入", "JelloActiveMods": "Jello 功能列表", "JelloShadow": "Jello 阴影",
    "KeyBindsHud": "按键面板", "KeyBindsRows": "按键列表", "Keybind": "按键绑定",
    "Lab Responsive": "实验室低延迟", "LabDebug": "实验室调试", "Large": "大", "Legacy": "旧版",
    "Liquid Neutral": "液态中性色", "LiquidArrayCompact": "液态紧凑列表",
    "LiquidArrayDock": "液态停靠栏", "LiquidArrayList": "液态列表", "LiquidArrayTags": "液态标签",
    "LiquidClean": "液态简洁", "LiquidMenu": "液态菜单", "Local": "本地",
    "Lock Match Control": "锁止比赛控制", "Match Chat": "比赛聊天", "Match Reliable": "比赛可靠优先",
    "Match Roles": "当前比赛兵种", "Melee": "近战", "Mini": "缩略图", "Minimal Bracket": "极简边角",
    "Mock": "模拟", "ModuleListHud": "功能列表面板", "Move": "移动", "Native": "原生",
    "Native 0x0310": "原生 0x0310", "New Qualification Session": "新建资格检查会话",
    "No Sound": "静音", "Normal 1-6": "普通 1–6", "Observe Firmware Zero": "观察固件归零",
    "OfficialEvent": "官方赛事", "Original Bottom": "原版底部", "PUBG Subtitle": "绝地求生字幕",
    "PageDown": "下一页", "PageUp": "上一页", "Paid": "付费", "ParticleGrid": "粒子网格",
    "PkgScene": "壁纸包场景", "Polar Classic": "POLAR 经典", "Polar Corner": "POLAR 边角",
    "Polar Outline": "POLAR 轮廓", "Polar UI": "POLAR 界面", "PolarDropdown": "POLAR 下拉界面",
    "PolarLauncher": "POLAR 启动页", "PolarLegacy": "POLAR 旧版", "PolarMulti": "POLAR 多面板",
    "PolarNew": "POLAR 新版", "PolarOld": "POLAR 经典界面", "PolarOutline2D": "POLAR 二维轮廓",
    "PolarPanel": "POLAR 面板", "PolarRainbowRight": "POLAR 右侧彩虹列表",
    "PolarTextList": "POLAR 文本列表", "PolarUnified": "POLAR 统一界面", "Power": "功率",
    "Predict": "预测", "Prediction Rack": "预测架", "RM Dot": "RM 圆点", "RM Tactical": "RM 战术",
    "RMIndicatorsHud": "RM 状态指示面板", "RMUC 7v7 Official Map": "RMUC 7v7 官方地图",
    "RMUC Only": "仅 RMUC", "RMUC7v7": "RMUC 7 对 7", "RMUL 3v3 Official Map": "RMUL 3v3 官方地图",
    "RMUL3v3": "RMUL 3 对 3", "Radar Assisted": "雷达辅助", "Range": "远程", "Rate": "射速",
    "Record E-Stop Test": "记录急停测试", "Record Economy Test": "记录经济操作测试",
    "Record Firmware Zero Test": "记录固件归零测试",
    "Hero deployment has been removed": "英雄部署功能已移除",
    "Red": "红方", "Referee Only": "仅裁判系统", "Referee Score": "裁判系统得分",
    "Reset Qualification Session": "重置资格检查会话", "Review PRM1 Spin Schema": "审查 PRM1 小陀螺协议",
    "Review PRM1 Vision Schema": "审查 PRM1 视觉协议", "RobotCards": "机器人卡片",
    "RobotListHud": "机器人列表面板", "RoundCompact": "圆形紧凑", "Run Economy Send Test": "运行经济请求发送测试",
    "Run KMC Test": "运行键鼠控制测试", "Run Loss Recovery Test": "运行断连恢复测试",
    "Run PRM1 Spin Bench": "运行 PRM1 小陀螺台架测试", "Run PRM1 Vision Bench": "运行 PRM1 视觉台架测试",
    "Run Preflight": "运行赛前检查", "Run Video Test": "运行图传测试", "Rune Ring": "能量机关环数",
    "Segmented": "分段", "SemiAuto": "半自动", "Sentinel": "哨兵机器人", "Shark UDP": "Shark UDP",
    "Single": "单个", "Slide": "滑入", "Smooth60": "流畅 60 帧", "Space": "空格",
    "Spin Mode": "小陀螺模式", "Start Match Soak": "开始比赛持续测试", "Static": "静态",
    "StatusBars": "状态条", "StatusCardsHud": "状态卡片面板", "Stop Match Soak": "停止比赛持续测试",
    "Stub": "占位接口", "Synthetic": "合成画面", "T Gold": "T 金色", "TacticalMapHud": "战术地图面板",
    "Tank": "坦克", "TargetHud": "目标面板", "TexasMP4": "德克萨斯视频", "Tongji": "同济",
    "Tongji YOLOv5": "同济 YOLOv5", "Top": "顶部", "Total Battlefield": "战地综合",
    "Triangle": "三角形", "UDP HEVC": "UDP HEVC", "Legacy VT02 UDP": "旧图传", "New Video Link": "新图传（暂未实现）", "Legacy Official Bridge": "官方旧图传旁路桥接", "Unavailable": "不可用", "Up": "上",
    "VendingMachine4K": "自动售货机少女 4K", "VideoParallax": "视频视差", "Vision Only": "仅视觉",
    "Warning": "警告", "Webcam": "电脑摄像头", "Wedge": "楔形", "White Outline": "白色轮廓",
    "Wireframe3D": "三维线框", "3D Glass": "三维玻璃", "3D Wire": "三维线框",
    "both": "双通道", "serial": "串口", "tcp": "TCP 网络", "robot_cmd": "机器人指令",
    "virtual_rc": "虚拟遥控器", "polar_webcam": "POLAR 电脑摄像头",
    "rm2026-v1.1.0-student-readonly": "RM2026 v1.1.0 学生只读",
    "rm2026-v1.3.1": "RM2026 v1.3.1",
})

# Theme names and standard units/identifiers remain recognizable. They are
# deliberately not split or reassembled (for example 1x, 0x0310, X and COM3).
# Unknown user profiles, paths and devices also round-trip untouched.
DESCRIPTION_ZH = {
    "Decision support only; this module never fires automatically.": "仅提供决策辅助；此模块不会自动开火。",
    "Align yaw against a known field line.": "对齐已知场地线，标定偏航角。",
    "Store the operator-confirmed iterative pitch calibration.": "保存操作员确认的迭代俯仰标定结果。",
    "Confirm radar/map relocalization after every reset.": "每次重置后确认雷达或地图重定位。",
    "Fail closed after a localisation discontinuity.": "定位发生跳变后保持安全锁止。",
    "Open the dedicated deployment/lob operator console.": "打开专用部署与吊射控制台。",
    "Calculate yaw, pitch and flight time without sending a command.": "计算偏航角、俯仰角和飞行时间，不发送控制指令。",
    "Arm decision support only; no fire command is emitted.": "仅启用决策辅助预备状态，不发送开火指令。",
    "Sigma ActiveMods toggle sound.": "Sigma 功能列表开关音效。",
    "Fail-closed 现场资格、证据导出和比赛控制硬闸门。": "失效时安全锁止的现场资格检查、证据导出与比赛控制安全门禁。",
}

UI_ZH = {
    "30 s supervised Air window: use Event commands during MATCH only, then explicitly Observe Economy. Status change is not a unique ACK; normal arming qualification pending.": "受监督空中支援窗口开放 30 秒：仅在比赛阶段使用赛事指令，随后手动观察经济状态。状态变化不是唯一回执，普通比赛授权仍待验收。",
    "Create a V2 qualification session with a named operator first": "请先创建注明操作员的 V2 资格会话。",
    "V2 preview: Hero requests are pending review; no command submitted": "V2 预览：英雄请求尚待审查，未提交任何指令。",
    "V2 Air requires current connected OfficialEvent wire observations": "V2 空中支援需要当前已连接的官方赛事协议观测。",
    "Air dialog context changed; reopen it for the current profile/session": "空中支援上下文已变化，请在当前配置和会话中重新打开。",
    "Air dialog context changed; request discarded": "空中支援上下文已变化，请求已丢弃。",
    "Air conditions changed again; reopen the dialog. No request was sent.": "空中支援条件再次变化，请重新打开对话框；未发送请求。",
    "MOCK Air request recorded; no live enqueue or qualification evidence": "已记录模拟空中支援请求，未实际入队，也不作为资格证据。",
    "Supervised Air requires a matching V2 session and named operator": "受监督空中支援需要匹配的 V2 会话及实名操作员。",
    "V2 fixed-price Economy unavailable; opening supervised Air requests. Normal arming qualification pending.": "V2 固定价格经济操作不可用，改为打开受监督空中支援请求；普通比赛授权尚待验收。",
    "V2 legacy offers, including captured/mock offers, are unavailable; use the Air menu": "V2 不提供旧版报价（含缓存或模拟报价），请使用空中支援菜单。",
    "POLAR-RM Custom Client": "POLAR-RM 自定义客户端",
    "Continue": "继续", "Settings": "设置", "Return to startup": "返回启动页", "Exit client": "退出客户端",
    "VIDEO SIGNAL LOST · WAITING FOR FRESH DECODED FRAME": "图传信号丢失 · 等待新解码帧",
    "Cancel": "取消", "Exit client?": "退出客户端？",
    "Controls will lock before shutdown": "退出前将锁止控制输出",
    "Telemetry and safety monitoring remain active": "遥测与安全监控继续运行",
    "Esc  Back     ↑ ↓  Select     Enter  Confirm": "Esc 返回　↑ ↓ 选择　Enter 确认",
}


UI_ZH.update({
    "Step 1/3 | 当前: {title} | 按 1/2/3 快速选择": "第 1/3 步 | 当前：{title} | 按 1/2/3 快速选择",
    "Step 2/3 | Backspace 返回 | Enter 选择机器人": "第 2/3 步 | Backspace 返回 | Enter 选择机器人",
    "Step 2/3 | 1/2 选择比赛制式 | Backspace 返回运行场景 | Enter 选择机器人": "第 2/3 步 | 1/2 选择比赛制式 | Backspace 返回运行场景 | Enter 选择机器人",
    "HERO": "英雄", "ENG": "工程", "INF-1": "步兵一号", "INF-2": "步兵二号",
    "UAV": "空中", "SEN": "哨兵", "DART": "飞镖", "RADAR": "雷达",
    "Return to the main ClickGUI": "返回主配置界面",
    "Step 2/3 | Backspace: scenario | Enter: robot selection": "第 2/3 步 | Backspace：场景 | Enter：选择机器人",
    "POLAR VIEW": "POLAR 视图", "Keybind": "按键绑定", "KEY": "按键", "No settings": "没有设置项",
    "P Old": "POLAR 经典", "P Panel": "POLAR 面板", "P New": "POLAR 新版",
    "P Drop": "POLAR 下拉", "Polar One": "POLAR 统一界面", "Polar Multi": "POLAR 多面板",
    "Search modules...": "搜索模块…",
    "Import enable sound": "导入开启音效", "Import disable sound": "导入关闭音效",
    "Import invalid sound": "导入无效操作音效", "Import startup wallpaper": "导入启动壁纸",
    "Audio files (*.wav *.ogg *.mp3 *.flac *.m4a *.aac)": "音频文件 (*.wav *.ogg *.mp3 *.flac *.m4a *.aac)",
    "Wallpaper media (*.mp4 *.webm *.mov *.avi *.mkv *.gif *.png *.jpg *.jpeg)": "壁纸媒体 (*.mp4 *.webm *.mov *.avi *.mkv *.gif *.png *.jpg *.jpeg)",
    "Field qualification": "现场资格检查", "Operator name:": "操作员姓名：",
    "Robot firmware SHA-256:": "机器人固件 SHA-256：",
    "Physical firmware watchdog observation": "固件看门狗物理观察",
    "After physically observing neutral output, type ZERO OBSERVED:": "实际观察到物理零输出后，请输入英文确认口令 ZERO OBSERVED：",
    "PRM1 capability evidence": "PRM1 功能证据",
    "Named schema reviewer / bench safety observer:": "协议审查员 / 台架安全观察员姓名：",
    "Type OBSERVED ON FIXTURE to confirm supervised evidence:": "确认已在监督下完成台架观察后，请输入英文确认口令 OBSERVED ON FIXTURE：",
    "Export field evidence": "导出现场证据", "Dual sign-off": "双人签字确认", "Safety lead name:": "安全负责人姓名：",
    "MATCH MODE": "比赛制式", "SCENE SELECT": "场景选择", "CUSTOM CLIENT": "自定义客户端",
    "Choose runtime environment": "选择运行环境", "{title} profile": "{title} 配置",
    "PROFILE  {profile}": "配置  {profile}", "NEXT": "下一步", "Back": "返回",
    "Return to scene select": "返回场景选择", "Backspace also works": "也可按 Backspace 返回",
    "BACK": "返回", "Return to scene selection.": "返回场景选择。", "LIVE": "真实连接",
    "MOCK": "模拟", "ROBOT PROFILE": "机器人配置", "{title} · Step 3/3": "{title} · 第 3/3 步",
    "Robot ID {id} · {title}": "机器人编号 {id} · {title}", "ID {id}": "编号 {id}",
    "MAX HP": "最大血量", "POWER": "功率", "HEAT": "热量", "COOLING": "冷却",
    "PROJECTILE": "弹丸", "N/A": "暂无", "<  BACK": "<  返回", "CANCEL": "取消", "RELEASE": "松开",
    "SESSION": "会话", "ENV": "环境", "MATCH": "比赛", "CONFIG": "配置", "SERIAL": "串口",
    "mock": "模拟", "live": "真实连接", "Press 1/2 to load. Backspace returns.": "按 1/2 加载，Backspace 返回。",
    "Press 1/2/3 to select. Enter continues.": "按 1/2/3 选择，Enter 继续。", "Config": "配置",
    "Import": "导入", "Wallpaper": "壁纸", "Exit": "退出", "KEYBIND": "按键绑定",
    "Press any key to bind": "按任意键绑定", "Return to the main ClickGUI.": "返回主配置界面。",
    "←  Back to Jello Sigma": "←  返回 Jello Sigma", "Warning": "警告", "Success": "成功",
    "Client State": "客户端状态", "Radar": "雷达", "DJI Official": "DJI 官方赛事",
    "Official limits and referee links": "官方限制与裁判系统连接",
    "Load official safety limits, referee protocol defaults, and event HUD presets.": "加载官方安全限制、裁判协议默认值及赛事界面预设。",
    "Campus Sim": "校内模拟", "Shark bridge and local match mock": "Shark 桥接与本地比赛模拟",
    "Load campus simulation defaults for SharkDataServer, mock sending, and local video.": "加载 SharkDataServer 校内模拟、模拟发送与本地图传默认值。",
    "Lab Debug": "实验室调试", "Camera preview and protocol stubs": "摄像头预览与协议占位接口",
    "Load lab debug defaults for webcam preview, protocol testing, and mock outputs.": "加载摄像头预览、协议测试与模拟输出的实验室调试默认值。",
    "POLAR profile": "POLAR 配置", "Super combat map and full HUD": "超级对抗赛地图与完整战斗界面",
    "Load RMUC 7v7 official map, tactical HUD, base, outpost, gold, ammo, and buff modules.": "加载 RMUC 7v7 官方地图、战术界面、基地、前哨站、金币、弹药与增益模块。",
    "Alliance map and control zone HUD": "联盟赛地图与控制区界面",
    "Load RMUL 3v3 official map, control zone, victory points, robot status, and compact HUD.": "加载 RMUL 3v3 官方地图、控制区、胜利点、机器人状态与紧凑界面。",
    "Match profile": "比赛配置", "WALLPAPER LIBRARY": "壁纸库", "LOADING": "加载中", "GRID": "网格",
    "Reset": "重置", "Remove": "移除", "Close": "关闭", "ROBOT PROFILE · STEP 3/3": "机器人配置 · 第 3/3 步",
    "LAUNCHER / SCENE SELECT": "启动页 / 场景选择", "Open ConfigManager in ClickGUI.": "在配置界面中打开配置管理。",
    "Import a config json.": "导入 JSON 配置。", "Open StartupVisual wallpaper settings.": "打开启动视觉壁纸设置。",
    "Enter HUD and open ClickGUI.": "进入战斗界面并打开配置界面。", "Close POLAR-RM.": "关闭 POLAR-RM。",
    "Return to scene select.": "返回场景选择。",
})

TOAST_ZH = {
    'V2 custom marks are disputed; Sentry map intervention needs its separate confirmation dialog': 'V2自定义标记存在协议争议；哨兵地图干预需使用独立费用确认窗口',
    'No reviewed event commands are available': '当前没有已审查可用的赛事指令',
    'Event command context changed; reopen the dialog': '赛事指令上下文已变，请重新打开窗口',
    'Event command context changed; request discarded': '赛事指令上下文已变，已丢弃请求',
    'V2 economy requires connected OfficialEvent RMUC7v7 and a matching session': 'V2经济请求需要已连接的官方赛事、RMUC7v7制式及匹配会话',
    'Supervised economy requires a matching named V2 session': '受监督经济请求需要匹配且填写操作员姓名的V2会话',
    'Unsupported V2 economic dialog': '不支持此V2经济确认类型',
    'Economic dialog context changed; reopen it': '经济确认上下文已变，请重新打开窗口',
    'Economic dialog context changed; request discarded': '经济确认上下文已变，已丢弃请求',
    'Economic conditions changed again; reopen the dialog. No request was sent.': '经济条件再次变化，请重新打开窗口；未发送请求',
    'Current team identity is required for Sentry map intervention': '哨兵地图干预需要当前可信的本方身份',
    'V2 legacy offers are unavailable; use the explicit V2 economic confirmation workspace': 'V2不使用旧版报价，请使用独立V2经济确认工作台',
    '30 s supervised V2 economy window: confirm one request during MATCH in the V2 workspace. Air observation is not a unique request/payment ACK; other capabilities keep independent safety gates.': 'V2经济监督窗口开放30秒：请在比赛阶段的V2工作台确认一次请求。Air观测不等于唯一请求或支付确认；其它能力仍受各自安全门约束。',
    'Sentry mode requires fresh PREPARE, Aerial identity and a matching named V2 session': '哨兵模式需要最新准备期观测、空中身份及匹配的实名V2会话',
    'Sentry mode context changed; request discarded': '哨兵模式上下文已变，已丢弃请求',

    "Hero deploy console is locked until exit sync": "部署状态同步完成前，英雄控制台保持锁定",
    "Quick action is unavailable": "快捷操作不可用",
    "ClickGUI opened from launcher": "已从启动页打开配置界面",
    "ConfigManager opened from launcher": "已从启动页打开配置管理",
    "Confirm ENTER deploy mode within 3 seconds": "请在 3 秒内确认进入部署模式",
    "Confirm EXIT deploy mode within 3 seconds": "请在 3 秒内确认退出部署模式",
    "E-STOP ACTIVE": "急停已触发",
    "E-STOP RELEASED — verify robot before control": "急停已解除，请先检查机器人再恢复控制",
    "Drop a module onto a Minecraft hotbar slot": "请将模块拖到 Minecraft 功能栏的栏位上",
    "KMC neutral 75 Hz qualification started": "已开始 75 Hz 键鼠零输出资格测试",
    "Compact HUD restored": "已恢复紧凑战斗界面",
    "KMC qualification is already running": "键鼠控制资格测试已在进行中",
    "KMC qualification requires a live real MQTT connection": "键鼠控制资格测试需要真实 MQTT 连接",
    "Spin live output armed; toggle SpinMode again to enable": "小陀螺真实输出已预备，请再次切换小陀螺模块以启用",
    "Qualification session created; control remains LOCKED": "已创建资格检查会话，控制输出保持锁止",
    "Qualification evidence reset": "已重置资格检查证据",
    "HeroLob disabled; explicitly EXIT deploy mode": "英雄吊射已关闭，请手动确认退出部署模式",
    "Trigger a new F12 E-stop in this qualification session first": "请先在本次资格检查会话中按 F12 触发一次新的急停",
    "Firmware zero observation cancelled": "已取消固件归零观察",
    "Match-duration soak started": "已开始比赛时长持续测试", "Dual sign-off recorded": "已记录双人签字确认",
    "Match control LOCKED": "比赛控制已锁止", "MATCH CONTROL ARMED": "比赛控制已解锁",
    "Yaw calibration blocked: fresh gimbal telemetry required": "偏航标定受阻：需要有效且未超时的云台遥测",
    "Yaw calibration blocked: correction exceeds offset range": "偏航标定受阻：修正量超出偏移范围",
    "Pitch calibration blocked: fresh gimbal telemetry required": "俯仰标定受阻：需要有效且未超时的云台遥测",
    "Pitch calibration blocked: unreachable or offset out of range": "俯仰标定受阻：目标不可达或偏移超出范围",
    "Hero lob relocalization confirmed": "已确认英雄吊射重定位",
    "Relocalization blocked: fresh telemetry and both calibrations required": "重定位受阻：需要有效遥测及偏航、俯仰标定",
    "Hero lob disarmed": "已撤销英雄吊射预备状态",
    "Hero lob armed (decision support only; no automatic fire)": "英雄吊射已预备（仅决策辅助，不自动开火）",
    "Enable HeroLob before opening the deploy console": "请先启用英雄吊射，再打开部署控制台",
    "Exit deploy mode and wait for DeployModeStatusSync before closing": "请先退出部署模式，等待部署状态同步后再关闭",
    "Wait for DeployModeStatusSync before closing the console": "请等待部署状态同步后再关闭控制台",
    "A deploy-mode request is already pending": "已有部署模式请求等待确认",
    "Deploy mode is already in the requested state": "部署模式已处于请求的状态",
    "HeroLob is disabled": "英雄吊射已关闭", "Deploy mode requires the Hero / Range profile": "部署模式需要英雄远程配置",
    "Deploy mode entry is available only during the match stage": "只能在比赛阶段进入部署模式",
    "Economy test window active for 30 s; send one supervised request": "经济测试窗口开放 30 秒，请在监督下发送一次请求",
    "Economy qualification requires OfficialEvent": "经济操作资格测试需要官方赛事场景",
    "Create a qualification session first": "请先创建资格检查会话",
    "Back to Jello Sigma": "已返回 Jello Sigma", "ClickGUI opened": "配置界面已打开", "ClickGUI closed": "配置界面已关闭",
    "Preflight PASS": "赛前检查通过", "Preflight BLOCKED": "赛前检查未通过",
    "Video field test PASS": "图传现场测试通过", "Video test needs a 60 s field capture": "图传测试需要 60 秒现场采集",
    "Soak PASS": "持续测试通过", "Soak stopped too early": "持续测试提前停止",
    "Chessboard capture failed": "棋盘格采集失败", "Calibration solve failed": "标定计算失败",
    "Tongji YAML export failed": "同济 YAML 导出失败", "AutoSpin OFF: hit window complete": "受击自动小陀螺已关闭：触发时限结束",
    "ClickGUI：简体中文": "配置界面：简体中文",
    "ClickGUI 已就绪：Jello Sigma": "配置界面已就绪：Jello Sigma",
    "DeployModeStatusSync timeout": "部署状态同步超时（DeployModeStatusSync）",
    "E-stop active; only the dedicated zero KMC bypass is allowed": "急停已触发；仅允许专用键鼠零输出通道",
    "current scenario is mock-only and does not allow real MQTT publishing": "当前场景仅支持模拟，不允许真实 MQTT 发布",
    "match control is LOCKED": "比赛控制已锁止",
    "qualification token invalid or expired": "资格检查令牌无效或已过期",
    "capability hero remains LOCKED MOCK": "英雄部署权限仍处于锁止模拟状态",
    "not in an authoritative fighting stage": "裁判系统尚未确认进入比赛阶段",
    "READY": "已就绪", "OFF": "已关闭", "DISARMED": "未预备", "ARMED PREVIEW ONLY": "已预备，仅预览",
    "DEPLOYED / VIDEO CUT": "已部署 / 图传中断", "DEPLOY MODE EXITED": "已退出部署模式",
    "DEPLOY ENTER PENDING": "等待进入部署模式", "DEPLOY EXIT PENDING": "等待退出部署模式",
    "non-finite input": "输入包含非有限数值", "distance too small": "距离过小", "invalid speed/gravity": "速度或重力参数无效",
    "target is outside ballistic envelope": "目标超出弹道可达范围",
    "muzzle-offset iteration left ballistic envelope": "炮口偏移迭代超出弹道可达范围",
    "near-vertical solution": "弹道解接近垂直", "unsafe flight time": "飞行时间不安全",
    "Hero profile required": "需要英雄配置", "Hero Range preset required": "需要英雄远程预设",
    "2027 rules removed the Hero deployment mechanic": "2027规则已取消旧英雄部署机制",
    "gimbal offline": "云台离线", "telemetry stale": "遥测已超时", "yaw not calibrated": "偏航未标定",
    "pitch not calibrated": "俯仰未标定", "relocalization invalid": "重定位无效",
    "relocalization invalidated by telemetry reset": "遥测重置导致重定位失效",
    "roll/yaw coupling guard": "横滚与偏航耦合保护", "match stage required": "需要处于比赛阶段",
    "no projectile": "无可用弹丸", "heat guard": "热量保护",
    "Configuration must contain finite JSON values": "配置只能包含有限的 JSON 数值",
}

# Prefix matching is restricted to messages emitted by the application. The
# suffix (especially file names, device paths and third-party errors) is kept
# intact unless it is itself a known complete diagnostic.
_TOAST_PREFIX_ZH = {
    "Invalid configuration value: ": "配置值无效：",
    "Evidence exported: ": "证据已导出：", "Arm blocked: ": "解锁受阻：",
    "Qualification blocked: ": "资格检查受阻：", "Deploy command blocked: ": "部署指令受阻：",
    "Sound import failed: ": "音效导入失败：", "Wallpaper import failed: ": "壁纸导入失败：",
    "Wallpaper loaded: ": "壁纸已加载：", "Import failed: ": "导入失败：",
    "Tongji YAML exported: ": "同济 YAML 已导出：", "Match mode: ": "比赛制式：",
    "Robot profile: ": "机器人配置：", "MC slot target missing: ": "功能栏目标不存在：",
    "Old ClickGUI：": "旧版配置界面：", "AutoSpin ON: ": "受击自动小陀螺已启用：",
    "BLOCKED: ": "受阻：",
    "Event command failed: ": "事件指令失败：",
    "Exit cleanup warnings: ": "退出清理警告：",
    "Scenario: ": "运行场景：",
}


def diagnostic_text(value: str, chinese: bool) -> str:
    """Known application safety diagnostics only; preserve unknown suffixes."""
    text = str(value)
    if not chinese:
        return text
    if text in TOAST_ZH:
        return TOAST_ZH[text]
    rate = re.fullmatch(r"(HeroDeployModeEventCommand) exceeds (\d+(?:\.\d+)?) Hz", text)
    if rate:
        return f"{rate[1]} 超过 {rate[2]} Hz 频率上限"
    profile = r"(rm2026-v1\.3\.1|rm2026-v1\.1\.0-student-readonly)"
    readonly = re.fullmatch(profile + r": READ ONLY; no control/economy uplink", text)
    if readonly:
        return f"{readonly[1]}：只读；禁止控制与经济上行"
    unsupported = re.fullmatch(profile + r": not an official uplink topic: (HeroDeployModeEventCommand)", text)
    if unsupported:
        return f"{unsupported[1]}：非官方上行主题：{unsupported[2]}"
    qos = re.fullmatch(profile + r": QoS must be 0\.\.(\d+)", text)
    if qos:
        return f"{qos[1]}：QoS 必须为 0..{qos[2]}"
    invalid = "invalid HeroDeployModeEventCommand: "
    if text.startswith(invalid):
        return "HeroDeployModeEventCommand 数据无效：" + text[len(invalid):]
    return text


def ui_text(value: str, chinese: bool, **values: Any) -> str:
    """Translate a known UI template before inserting untouched runtime data."""
    text = str(value)
    if chinese:
        text = UI_ZH.get(text, option_label(text, True))
    return text.format(**values) if values else text


def toast_text(message: str, chinese: bool) -> str:
    """Translate display messages only; never change stored diagnostic strings."""
    text = str(message)
    if not chinese:
        return text
    if text in TOAST_ZH:
        return TOAST_ZH[text]
    if text in UI_ZH:
        return UI_ZH[text]
    toggle = re.fullmatch(r"([A-Za-z0-9]+) (enabled|disabled|已启用|已关闭)", text)
    if toggle and toggle[1] in MODULE_ZH:
        return f"{MODULE_ZH[toggle[1]]} {'已启用' if toggle[2] in ('enabled', '已启用') else '已关闭'}"
    for prefix, label in _TOAST_PREFIX_ZH.items():
        if text.startswith(prefix):
            detail = text[len(prefix):]
            if prefix == "BLOCKED: ":
                parts = detail.split(", ")
                readiness_reasons = {
                    "Hero profile required", "Hero Range preset required", "gimbal offline",
                    "telemetry stale", "yaw not calibrated", "pitch not calibrated",
                    "relocalization invalid", "roll/yaw coupling guard", "match stage required",
                    "no projectile", "heat guard", "non-finite input", "distance too small",
                    "invalid speed/gravity", "target is outside ballistic envelope",
                    "muzzle-offset iteration left ballistic envelope", "near-vertical solution",
                    "unsafe flight time", "relocalization invalidated by telemetry reset",
                }
                if len(parts) > 1 and all(part in readiness_reasons for part in parts):
                    detail = "、".join(diagnostic_text(part, True) for part in parts)
                else:
                    detail = diagnostic_text(detail, True)
            elif prefix in {"Match mode: ", "Robot profile: ", "Old ClickGUI：", "MC slot target missing: "}:
                detail = option_label(detail, True)
            elif prefix in {"Arm blocked: ", "Qualification blocked: ", "Deploy command blocked: "}:
                detail = diagnostic_text(detail, True)
            # File names, paths, user configuration values and third-party
            # error details are opaque, even when they equal a known label.
            return label + detail
    qualification = re.fullmatch(
        r"(estop_robot_test|firmware_loss_zero_test|loss_recovery_test|hero_deploy_status_test|economy_live_test|prm1_vision_schema_review|prm1_vision_bench_test|prm1_spin_schema_review|prm1_spin_bench_test): (PASS|BLOCKED)( · LOCKED)?", text)
    if qualification:
        result = "通过" if qualification[2] == "PASS" else "未通过"
        return f"{qualification[1]}：{result}" + (" · 已锁止" if qualification[3] else "")
    kmc = re.fullmatch(r"KMC (PASS|FAIL) · P95 (\d+(?:\.\d+)?) ms · LOCKED", text)
    if kmc:
        return f"KMC {'通过' if kmc[1] == 'PASS' else '未通过'} · P95 {kmc[2]} ms · 已锁止"
    event_command = re.fullmatch(r"(Rune|Dart|Sentry|Assembly|Performance selection) (.+)", text)
    if event_command:
        command = {"Rune": "能量机关指令", "Dart": "飞镖指令", "Sentry": "哨兵指令",
                   "Assembly": "装配指令", "Performance selection": "性能配置指令"}[event_command[1]]
        result = "已发送" if event_command[2] == "sent" else TOAST_ZH.get(event_command[2], event_command[2])
        return f"{command}：{result}"
    map_click = re.fullmatch(r"Map click \((\d+\.\d), (\d+\.\d)\)m (.+)", text)
    if map_click:
        result = "已发送" if map_click[3] == "sent" else TOAST_ZH.get(map_click[3], map_click[3])
        return f"地图标记（{map_click[1]}, {map_click[2]}）m：{result}"
    emergency = re.fullmatch(r"E-STOP ACTIVE \((.*)\)", text)
    if emergency:
        return f"急停已触发（{TOAST_ZH.get(emergency[1], emergency[1])}）"
    slot = re.fullmatch(r"MC slot (\d+)( is empty|: (.*))", text)
    if slot:
        return f"功能栏 {slot[1]} 为空" if slot[2] == " is empty" else f"功能栏 {slot[1]}：{module_label(slot[3], True)}"
    custom = re.fullmatch(r"Custom (enable|disable|invalid) sound ready", text)
    if custom:
        kind = {"enable": "开启", "disable": "关闭", "invalid": "无效操作"}[custom[1]]
        return f"自定义{kind}音效已就绪"
    deployed = re.fullmatch(r"(ENTER|EXIT) deploy mode requested \((mock|official)\)", text)
    if deployed:
        return f"已请求{'进入' if deployed[1] == 'ENTER' else '退出'}部署模式（{'模拟' if deployed[2] == 'mock' else '官方'}）"
    # Translate known calibration formats while retaining signed numeric values.
    numeric_formats = (
        (r"PREVIEW Y([+\-]\d+\.\d) P([+\-]\d+\.\d) T(\d+\.\d{2})", "预览：偏航 {0}°，俯仰 {1}°，飞行时间 {2} 秒"),
        (r"Physical neutral output observed at ([\d.]+) ms", "已观察到物理零输出，耗时 {0} ms"),
        (r"Calibration sample (\d+): corners locked", "标定样本 {0}：角点已锁定"),
        (r"Calibration solved: ([\d.]+)px RMS", "标定完成：均方根误差 {0} px"),
        (r"Hero lob yaw calibrated ([+\-\d.]+) deg", "英雄吊射偏航已标定：{0} 度"),
        (r"Hero lob pitch calibrated ([+\-\d.]+) deg", "英雄吊射俯仰已标定：{0} 度"),
        (r"Yaw calibration residual ([\d.]+) deg", "偏航标定残差：{0} 度"),
        (r"Pitch calibration residual ([\d.]+) deg", "俯仰标定残差：{0} 度"),
    )
    for pattern, template in numeric_formats:
        match = re.fullmatch(pattern, text)
        if match:
            return template.format(*match.groups())
    return text


def description_label(value: str, chinese: bool) -> str:
    """Localize documented display text without rewriting protocol examples."""
    text = str(value)
    return DESCRIPTION_ZH.get(text, text) if chinese else text


def ui_label(value: str, chinese: bool) -> str:
    """Translate common interface copy; preserve unsupported text verbatim."""
    text = str(value)
    return UI_ZH.get(text, text) if chinese else text

def chinese_enabled(registry: Any) -> bool:
    module = registry.get("ClickGui") if registry is not None else None
    setting = module.get_setting(LANGUAGE_SETTING) if module is not None else None
    return setting is None or str(setting.value) != LANGUAGE_ENGLISH


def category_label(value: str, chinese: bool) -> str:
    return CATEGORY_ZH.get(str(value), str(value)) if chinese else str(value)


def module_label(value: str, chinese: bool) -> str:
    return MODULE_ZH.get(str(value), str(value)) if chinese else str(value)


def setting_label(value: str, chinese: bool) -> str:
    value = str(value)
    if not chinese:
        return value
    slot = re.fullmatch(r"Slot\s+(\d+)", value)
    if slot:
        return f"功能栏 {slot.group(1)}"
    binding = re.fullmatch(r"Bind\s+([A-Z]+)", value)
    if binding:
        return f"绑定 {binding.group(1)}"
    return SETTING_ZH.get(value, value)


def option_label(value: Any, chinese: bool) -> str:
    text = str(value)
    if text == "rm2026-v2.0.0":
        return "RM2026 V2.0.0 · 遥测/监督空中请求预览" if chinese else "RM2026 V2.0.0 · telemetry/supervised Air preview"
    if not chinese:
        return text
    if text in MODULE_ZH:
        return MODULE_ZH[text]
    if text in CATEGORY_ZH:
        return CATEGORY_ZH[text]
    return OPTION_ZH.get(text, SETTING_ZH.get(text, text))


def action_label(value: str, chinese: bool) -> str:
    return option_label(value, chinese)


def profile_language_badge(chinese: bool) -> str:
    return "中文" if chinese else "EN"

# Added crosshair labels do not alter config/protocol identifiers.
SETTING_ZH.update(_CROSSHAIR_ZH)
OPTION_ZH.update(_CROSSHAIR_ZH)
