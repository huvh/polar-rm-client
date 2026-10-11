"""Economy presentation strings; request objects and transport IDs stay raw."""
from __future__ import annotations

ECONOMY_ZH = {
    "ECONOMY  ·  {gold} GOLD": "战斗经济  ·  {gold} 金币",
    "{match} · {profile} · 默认 MOCK": "{match} · {profile} · 默认模拟",
    "{cost} GOLD  ·  {unit}": "{cost} 金币  ·  {unit}",
    "CLOSE  [B]": "关闭  [B]",
    "SEND MOCK REQUEST": "发送模拟请求",
    "经济  ·  {gold} G": "经济  ·  {gold} 金币",
    "{gold} G": "{gold} 金币",
    "G": "金",
    "HP": "血量",
    "AMMO": "弹量",
}


def economy_text(template: str, chinese: bool, **values: object) -> str:
    text = ECONOMY_ZH.get(template, template) if chinese else template
    return text.format(**values) if values else text
