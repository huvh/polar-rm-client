"""Bounded, display-only vocabulary for the Hero deployment surface.

Internal phases, readiness reasons, protocol identifiers and action payloads
remain unchanged. Unknown operator text and external exception details are
opaque: do not apply token substitution or translate arbitrary substrings.
"""

from __future__ import annotations

import re
from typing import Any

from .jello_locale import option_label, toast_text, diagnostic_text


HERO_ZH = {
    "HERO LOB": "英雄吊射",
    "Range deployment · ballistic assist": "远程部署 · 弹道辅助",
    "MOBILE": "机动状态",
    "DEPLOYED": "已部署",
    "ENTERING {seconds}s": "正在进入 {seconds}秒",
    "EXITING {seconds}s": "正在退出 {seconds}秒",
    "ENTER DEPLOY": "进入部署",
    "EXIT DEPLOY": "退出部署",
    "CONFIRM {label}": "确认{label}",
    "PREVIEW": "预览",
    "ARM ASSIST": "预备辅助",
    "DISARM": "撤销预备",
    "CLOSE": "关闭",
    "BALLISTIC PREVIEW": "弹道预览",
    "NO VALID BALLISTIC SOLUTION": "无有效弹道解",
    "OFFICIAL VIDEO CUT · CUSTOM UI + MAP STAY ACTIVE": "官方图传中断 · 自定义界面与地图仍可用",
    "TARGET {target}  ·  RANGE {distance} m": "目标 {target}  ·  距离 {distance} m",
    "DEPLOY / GIMBAL": "部署 / 云台",
    "STATUS": "状态",
    "SOLUTION": "弹道解",
    "READY": "就绪",
    "BLOCKED": "受阻",
    "YAW / PITCH": "偏航 / 俯仰",
    "FLIGHT": "飞行时间",
    "MUZZLE": "弹丸初速",
    "HEAT / AMMO": "热量 / 弹药",
    "GIMBAL": "云台",
    "ONLINE": "在线",
    "OFFLINE": "离线",
    "RM2026 DEPLOY MODE": "RM2026 部署模式",
    "CHASSIS POWER OFF · DEFENCE +25%": "底盘断电 · 防御 +25%",
    "OFFICIAL VIDEO CUT · UI + MAP STAY": "官方图传中断 · 界面与地图保留",
    "42 mm BASE BONUS · MAX 16.5 m/s": "42 mm 基地伤害加成 · 最高 16.5 m/s",
    "DEPLOYMENT ACTIVE": "部署已生效",
    "DEPLOYED · VIDEO CUT · K TO OPEN": "已部署 · 图传中断 · 按 K 打开",
    "Open Hero deploy console": "打开英雄部署控制台",
    "Close Hero deploy controls": "关闭英雄部署控制台",
    "VIDEO SIGNAL LOST · WAITING FOR FRESH DECODED FRAME": "图传信号丢失 · 等待新解码帧",
    "WAITING FOR NATIVE 0x0310 COMPRESSED VIDEO": "等待原生 0x0310 压缩图传",
    "NATIVE 0x0310 VIDEO LOST · NO CAMERA FALLBACK": "原生 0x0310 图传丢失 · 不切换摄像头",
}

# Shared translations are reused only for exact, application-owned reasons
# emitted by HeroLobPlanner. This is also the bounded diagnostic inventory.
HERO_READINESS_REASONS = frozenset({
    "Hero profile required", "Hero Range preset required", "gimbal offline",
    "telemetry stale", "yaw not calibrated", "pitch not calibrated",
    "relocalization invalid", "roll/yaw coupling guard", "match stage required",
    "no projectile", "heat guard", "non-finite input", "distance too small",
    "invalid speed/gravity", "target is outside ballistic envelope",
    "muzzle-offset iteration left ballistic envelope", "near-vertical solution",
    "unsafe flight time",
})

HERO_DIAGNOSTIC_ZH = {
    "DeployModeStatusSync timeout": "部署状态同步超时（DeployModeStatusSync）",
    "E-stop active; only the dedicated zero KMC bypass is allowed": "急停已触发；仅允许专用键鼠零输出通道",
    "current scenario is mock-only and does not allow real MQTT publishing": "当前场景仅支持模拟，不允许真实 MQTT 发布",
    "match control is LOCKED": "比赛控制已锁止",
    "qualification token invalid or expired": "资格检查令牌无效或已过期",
    "capability hero remains LOCKED MOCK": "英雄部署权限仍处于锁止模拟状态",
    "not in an authoritative fighting stage": "裁判系统尚未确认进入比赛阶段",
}


def hero_text(value: str, chinese: bool, **values: Any) -> str:
    """Translate a known template before inserting untouched runtime values."""
    text = HERO_ZH.get(value, value) if chinese else value
    return text.format(**values) if values else text


def hero_phase(value: str, chinese: bool) -> str:
    """Format a phase without modifying HeroDeployInterfaceState.phase()."""
    if chinese:
        countdown = re.fullmatch(r"(ENTERING|EXITING) (\d+\.\d)s", value)
        if countdown:
            return hero_text(countdown[1] + " {seconds}s", True, seconds=countdown[2])
    return hero_text(value, chinese)


def hero_target(value: str, chinese: bool) -> str:
    # Stock enum labels may be localized; a future/custom target stays opaque.
    if value not in {"Enemy Base", "Enemy Outpost", "Manual"}:
        return value
    return option_label(value, True) if chinese else value.upper()


def hero_diagnostic(value: str, chinese: bool) -> str:
    return diagnostic_text(value, chinese)
