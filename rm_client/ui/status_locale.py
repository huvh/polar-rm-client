"""Display-only vocabulary for the island, watermark and chassis compass.

This is the bounded inventory for those surfaces.  Identifiers (POLAR-RM,
MQTT, DT7, ports, FPS and units) remain recognizable; unrecognized messages,
custom names and diagnostic details are opaque.  No producer/state is edited.
English deliberately retains the original display, including legacy Chinese.
"""
from __future__ import annotations

from typing import Any

from .jello_locale import toast_text


STATUS_ZH = {
    # Dynamic-island title and idle-session fields.
    "Warning": "警告", "Success": "成功", "Client State": "客户端状态", "Radar": "雷达",
    "MQTT live": "MQTT 实时", "MQTT mock": "MQTT 模拟",
    "SERIAL live": "串口 实时", "SERIAL mock": "串口 模拟",
    "RMUC 7v7": "RMUC 7 对 7", "RMUL 3v3": "RMUL 3 对 3",
    # Watermark camera, radio-key/mouse and custom-controller states.
    "CAM": "摄像头", "SYN": "合成图传", "KM off": "KM 关闭",
    "KM blocked": "KM 受阻", "KM on(?)": "KM 开启(?)",
    "KM live↑{count}": "KM 实时↑{count}", "KM NO-RX!!": "KM 无接收!!",
    "KM stall@{count}": "KM 停滞@{count}", "KM ?": "KM 未知",
    "CC on": "CC 开启", "CC off": "CC 关闭",
    # Compass display values. The underlying Follow and SpinMode values stay raw.
    "SPIN": "小陀螺", "FOLLOW": "跟随", "FIELD": "场地", "FREE": "自由",
    "REL {angle}": "相对 {angle}", "N": "北",
    # Built-in model/video event messages (all other messages use toast_text).
    "Armor target acquired": "已捕获装甲目标", "Radar highlight refreshed": "雷达高亮已刷新",
    "VISION CONFIRMED": "视觉已确认", "Referee elimination": "裁判系统淘汰事件",
    "Official combat event": "官方战斗事件", "ClickGUI: English": "配置界面：英语",
}


def status_text(value: str, chinese: bool, **values: Any) -> str:
    """Translate one known caption/template before inserting untouched data."""
    text = str(value)
    text = STATUS_ZH.get(text, text) if chinese else text
    return text.format(**values) if values else text


def status_event_text(message: str, chinese: bool) -> str:
    """Localize a final island description, after classification of raw text."""
    text = str(message)
    if not chinese:
        return text
    if text in STATUS_ZH:
        return STATUS_ZH[text]
    return toast_text(text, True)


def dt7_display_token(raw: str, chinese: bool, *, resolved_port: str = "") -> str:
    """Translate the known DT7 status envelope; keep port/error bytes verbatim.

    ``backend.dt7_link.status_token`` stays the sole raw diagnostic generator.
    Consume only its ordered fixed fragments before the opaque ``(!error)``
    suffix. In particular, never replace words within a port or an error.
    """
    if not chinese or not raw:
        return raw
    if raw.startswith("DT7:mock"):
        prefix, label = "DT7:mock", "DT7:模拟"
    elif resolved_port and raw.startswith("DT7:real@" + resolved_port):
        prefix, label = "DT7:real@" + resolved_port, "DT7:真实输出@" + resolved_port
    elif raw.startswith("DT7:real(口未开)"):
        prefix, label = "DT7:real(口未开)", "DT7:真实输出(口未开)"
    else:
        return raw
    remainder = raw[len(prefix):]
    for fragment in ("(线上仍带按键)", "(松手帧未送达!)"):
        if remainder.startswith(fragment):
            label += fragment
            remainder = remainder[len(fragment):]
    if remainder and not remainder.startswith("(!"):
        return raw
    return label + remainder
