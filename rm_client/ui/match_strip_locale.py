"""Display-only match-strip vocabulary; raw referee/model values stay intact.

Translate exact built-in labels, never substrings in team aliases, caller-owned
score/roster labels or robot nicknames. The controller marks custom roster copy
explicitly, including copy that happens to match a built-in label.
"""
from __future__ import annotations

from ..top_match_bar import RobotCard


MATCH_STRIP_ZH = {
    "PAUSED": "已暂停", "NO DATA": "无数据", "SCORE —": "比分 —",
    "RM SCORE": "裁判比分", "GROUND ALIVE": "地面存活",
    "ALIVE": "存活", "DOWN": "已毁",
}
_ROLES = {
    1: ("HERO", "英雄"), 2: ("ENG", "工程"),
    3: ("INF-1", "步兵1"), 4: ("INF-2", "步兵2"),
    5: ("INF-3", "步兵3"), 6: ("UAV", "空中"),
    7: ("SENTRY", "哨兵"), 8: ("DART", "飞镖"), 9: ("RADAR", "雷达"),
}


def match_strip_text(value: str, chinese: bool) -> str:
    return MATCH_STRIP_ZH.get(value, value) if chinese else value


def match_role_text(card: RobotCard, chinese: bool) -> str:
    role = _ROLES.get(card.robot_id % 100)
    return role[1] if chinese and role is not None and card.label == role[0] else card.label


def match_health_text(card: RobotCard, chinese: bool) -> str:
    text = card.health_text
    if not chinese:
        return text
    if text == "NO HP":
        return "无血量属性"
    return "血量" + text[2:] if text.startswith("HP ") else text


def match_alliance_text(value: str, chinese: bool) -> str:
    # Canonical identities keep the established English rendering; aliases do
    # not get uppercased or translated, even if they contain a known word.
    labels = {"Red": "红方", "Blue": "蓝方"} if chinese else {"Red": "RED", "Blue": "BLUE"}
    return labels.get(value, value)
