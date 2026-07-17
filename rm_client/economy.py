from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time
from typing import Any, Callable


@dataclass(frozen=True)
class EconomyAction:
    key: str
    title: str
    short_title: str
    unit: str
    minimum: int
    cost: int
    enabled: bool
    reason: str = ""


@dataclass(frozen=True)
class EconomyRequest:
    sequence: int
    timestamp: float
    match_mode: str
    robot_profile: str
    action: str
    quantity: int
    cost: int
    mock: bool = True


class EconomyCommandBridge:
    """经济操作安全桥。默认只缓存请求，显式注册发送器后才向队内协议转发。"""

    def __init__(self) -> None:
        self.sequence = 0
        self.last_request: EconomyRequest | None = None
        self.history: list[EconomyRequest] = []
        self.sender: Callable[[EconomyRequest], None] | None = None

    def submit(self, state: Any, action: EconomyAction, quantity: int = 1) -> EconomyRequest:
        self.sequence += 1
        quantity = max(1, int(quantity))
        request = EconomyRequest(
            sequence=self.sequence,
            timestamp=time.time(),
            match_mode=str(state.match_mode),
            robot_profile=str(getattr(state, "robot_profile", state.robot_type)),
            action=action.key,
            quantity=quantity,
            cost=int(action.cost * quantity),
            mock=self.sender is None,
        )
        self.last_request = request
        self.history.append(request)
        self.history = self.history[-32:]
        if self.sender is not None:
            self.sender(request)
        elif action.key in ("ammo17", "ammo42"):
            added = max(0, int(action.minimum) * quantity)
            state.remaining_ammo = max(0, int(getattr(state, "remaining_ammo", 0))) + added
            state.ammo_capacity = max(int(getattr(state, "ammo_capacity", 0)), state.remaining_ammo)
        return request


def _rmuc_time_step(state: Any) -> int:
    remaining = max(0, int(getattr(state, "stage_countdown_sec", 420)))
    return max(0, math.ceil((420 - remaining) / 60.0))


def available_actions(state: Any) -> list[EconomyAction]:
    gold = int(getattr(state, "remaining_economy", 0))
    profile = str(getattr(state, "robot_profile", "Infantry1"))
    match_mode = str(getattr(state, "match_mode", "RMUC7v7"))
    projectile = str(getattr(state, "projectile_type", "17mm"))

    if match_mode == "RMUL3v3":
        actions = [
            EconomyAction("ammo17", "购买 17 mm 弹丸", "17 MM", "100 发", 10, 10, projectile == "17mm" and gold >= 10, "仅步兵/哨兵可用"),
            EconomyAction("ammo42", "购买 42 mm 弹丸", "42 MM", "1 发", 1, 10, projectile == "42mm" and gold >= 10, "仅英雄可用"),
        ]
        return actions

    step = _rmuc_time_step(state)
    level = max(1, int(getattr(state, "level", 1)))
    heal_cost = 50 + step * 20
    revive_cost = step * 80 + level * 20
    alive = int(getattr(state, "current_health", 0)) > 0
    chassis_robot = profile in ("Hero", "Engineer", "Infantry1", "Infantry2", "Sentinel")
    actions = [
        EconomyAction("ammo17", "远程购买 17 mm 弹丸", "17 MM", "100 发", 100, 150, projectile == "17mm" and gold >= 150, "当前机器人不使用 17 mm"),
        EconomyAction("ammo42", "远程购买 42 mm 弹丸", "42 MM", "10 发", 10, 150, projectile == "42mm" and gold >= 150, "当前机器人不使用 42 mm"),
        EconomyAction("remote_heal", "远程补血", "HEAL", "60% HP", 1, heal_cost, chassis_robot and alive and gold >= heal_cost, "仅存活的地面机器人可购买"),
        EconomyAction("instant_revive", "立即复活", "REVIVE", "100% HP", 1, revive_cost, chassis_robot and not alive and gold >= revive_cost, "仅战亡的地面机器人可购买"),
        EconomyAction("aerial_support", "空中支援时间", "AIR", "1 秒", 1, 1, profile == "Aerial" and gold >= 1, "仅空中机器人使用"),
    ]
    return actions


def request_payload(request: EconomyRequest) -> dict[str, Any]:
    return {"protocol": "rm.economy.request.v1", **asdict(request)}
