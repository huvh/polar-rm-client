from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time
from typing import Any, Callable, Protocol


CATEGORY_TITLES = {
    "ammo": "弹丸",
    "recovery": "恢复",
    "revive": "复活",
    "support": "支援",
}

TRANSACTION_LABELS = {
    "confirming": "等待确认",
    "pending": "等待裁判系统",
    "succeeded": "操作成功",
    "rejected": "请求被拒绝",
    "timed_out": "确认超时",
}


@dataclass(frozen=True)
class EconomyContext:
    match_mode: str
    robot_profile: str
    projectile_type: str
    gold: int
    total_gold: int
    current_ammo: int
    ammo_capacity: int
    current_health: int
    max_health: int
    in_supply_zone: bool
    out_of_combat: bool
    can_remote_heal: bool
    can_remote_ammo: bool
    respawn_pending: bool
    respawn_progress: float
    respawn_can_free: bool
    respawn_gold_cost: int
    respawn_can_pay: bool
    air_support_active: bool
    air_support_can_free: bool
    mock_mode: bool

    @property
    def alive(self) -> bool:
        return self.current_health > 0

    @classmethod
    def from_state(cls, state: Any) -> "EconomyContext":
        return cls(
            match_mode=str(getattr(state, "match_mode", "RMUC7v7")),
            robot_profile=str(getattr(state, "robot_profile", getattr(state, "robot_type", "Infantry1"))),
            projectile_type=str(getattr(state, "projectile_type", "17mm")),
            gold=max(0, int(getattr(state, "remaining_economy", 0))),
            total_gold=max(0, int(getattr(state, "total_economy_obtained", 0))),
            current_ammo=max(0, int(getattr(state, "remaining_ammo", 0))),
            ammo_capacity=max(0, int(getattr(state, "ammo_capacity", 0))),
            current_health=max(0, int(getattr(state, "current_health", 0))),
            max_health=max(1, int(getattr(state, "max_health", 1))),
            in_supply_zone=bool(getattr(state, "in_supply_zone", True)),
            out_of_combat=bool(getattr(state, "out_of_combat", True)),
            can_remote_heal=bool(getattr(state, "can_remote_heal", True)),
            can_remote_ammo=bool(getattr(state, "can_remote_ammo", True)),
            respawn_pending=bool(getattr(state, "respawn_pending", False)),
            respawn_progress=max(0.0, min(1.0, float(getattr(state, "respawn_progress", 0.0)))),
            respawn_can_free=bool(getattr(state, "respawn_can_free", False)),
            respawn_gold_cost=max(0, int(getattr(state, "respawn_gold_cost", 0))),
            respawn_can_pay=bool(getattr(state, "respawn_can_pay", False)),
            air_support_active=bool(getattr(state, "air_support_active", False)),
            air_support_can_free=bool(getattr(state, "air_support_can_free", False)),
            mock_mode=bool(getattr(state, "economy_mock_mode", True)),
        )


@dataclass(frozen=True)
class EconomyOffer:
    key: str
    category: str
    title: str
    short_title: str
    description: str
    unit: str
    minimum: int
    cost: int
    command_type: int
    command_param: int
    enabled: bool
    reason: str = ""
    confirmation: str = "double"
    topic: str = "CommonCommand"
    estimated: bool = False
    status_only: bool = False

    @property
    def quantity(self) -> int:
        return self.minimum


# Keep the public name used by existing callers while the workspace migrates to
# the more precise EconomyOffer terminology.
EconomyAction = EconomyOffer


@dataclass(frozen=True)
class EconomyRequest:
    sequence: int
    timestamp: float
    match_mode: str
    robot_profile: str
    action: str
    quantity: int
    cost: int
    command_type: int
    command_param: int
    topic: str
    payload: bytes
    mock: bool


@dataclass
class EconomyTransaction:
    request: EconomyRequest
    offer: EconomyOffer
    status: str
    message: str
    submitted_at: float
    deadline_at: float
    mock_complete_at: float
    baseline_gold: int
    baseline_ammo: int
    baseline_health: int
    baseline_revision: int
    baseline_respawn_pending: bool
    baseline_support_active: bool
    completed_at: float = 0.0

    @property
    def sequence(self) -> int:
        return self.request.sequence


class EconomyTransport(Protocol):
    """Transport boundary used by the workspace without owning MQTT state."""

    def send(self, request: EconomyRequest) -> bool:
        ...


def _encode_varint(value: int) -> bytes:
    value = max(0, int(value))
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte | 0x80)
        else:
            encoded.append(byte)
            return bytes(encoded)


def encode_common_command(command_type: int, param: int) -> bytes:
    """Encode RM 2026 CommonCommand without requiring generated protobuf code."""

    return b"\x08" + _encode_varint(command_type) + b"\x10" + _encode_varint(param)


def encode_air_support_command(command_id: int) -> bytes:
    """Encode RM 2026 AirSupportCommand.command_id."""

    return b"\x08" + _encode_varint(command_id)


def _rmuc_time_step(state: Any) -> int:
    remaining = max(0, int(getattr(state, "stage_countdown_sec", 420)))
    return max(0, math.ceil((420 - remaining) / 60.0))


def _enabled(gold: int, cost: int, condition: bool, reason: str) -> tuple[bool, str]:
    if not condition:
        return False, reason
    if gold < cost:
        return False, f"金币不足，还需要 {cost - gold}"
    return True, ""


def _offer(
    *,
    key: str,
    category: str,
    title: str,
    short_title: str,
    description: str,
    unit: str,
    quantity: int,
    cost: int,
    command_type: int,
    command_param: int,
    enabled: bool,
    reason: str = "",
    confirmation: str = "double",
    topic: str = "CommonCommand",
    estimated: bool = False,
    status_only: bool = False,
) -> EconomyOffer:
    return EconomyOffer(
        key=key,
        category=category,
        title=title,
        short_title=short_title,
        description=description,
        unit=unit,
        minimum=quantity,
        cost=cost,
        command_type=command_type,
        command_param=command_param,
        enabled=enabled,
        reason=reason,
        confirmation=confirmation,
        topic=topic,
        estimated=estimated,
        status_only=status_only,
    )


def _local_ammo_offer(
    context: EconomyContext,
    *,
    key: str,
    projectile: str,
    quantity: int,
    cost: int,
) -> EconomyOffer:
    enabled, reason = _enabled(context.gold, cost, context.in_supply_zone, "需要进入补给区")
    command_type = 1 if projectile == "17mm" else 2
    return _offer(
        key=key,
        category="ammo",
        title=f"购买 {quantity} 颗 {projectile} 弹丸",
        short_title=f"{quantity} × {projectile}",
        description="补给区兑换，二次确认后发送",
        unit=f"{quantity} 颗",
        quantity=quantity,
        cost=cost,
        command_type=command_type,
        command_param=quantity,
        enabled=enabled,
        reason=reason,
        confirmation="double",
    )


def _remote_ammo_offer(
    context: EconomyContext,
    *,
    key: str,
    projectile: str,
    quantity: int,
) -> EconomyOffer:
    cost = 150
    enabled, reason = _enabled(
        context.gold,
        cost,
        context.can_remote_ammo or context.mock_mode,
        "裁判系统暂未开放远程补弹",
    )
    return _offer(
        key=key,
        category="ammo",
        title=f"远程兑换 {quantity} 颗 {projectile}",
        short_title=f"远程 {quantity} × {projectile}",
        description="远程兑换属于高花费操作，需要长按确认",
        unit=f"{quantity} 颗",
        quantity=quantity,
        cost=cost,
        command_type=5,
        command_param=quantity,
        enabled=enabled,
        reason=reason,
        confirmation="hold",
    )


def available_actions(state: Any) -> list[EconomyOffer]:
    """Build the visible offer matrix for the selected match and robot."""

    context = EconomyContext.from_state(state)
    profile = context.robot_profile
    offers: list[EconomyOffer] = []

    if context.match_mode == "RMUL3v3":
        if profile == "Hero":
            offers.extend(
                [
                    _local_ammo_offer(context, key="rmul_hero_42_1", projectile="42mm", quantity=1, cost=10),
                    _local_ammo_offer(context, key="rmul_hero_42_10", projectile="42mm", quantity=10, cost=100),
                ]
            )
        elif profile.startswith("Infantry"):
            offers.extend(
                [
                    _local_ammo_offer(context, key="rmul_infantry_17_10", projectile="17mm", quantity=10, cost=10),
                    _local_ammo_offer(context, key="rmul_infantry_17_100", projectile="17mm", quantity=100, cost=100),
                ]
            )
        elif profile == "Sentinel":
            offers.append(
                _offer(
                    key="rmul_sentinel_ammo_status",
                    category="ammo",
                    title="哨兵初始弹量",
                    short_title="仅显示弹量",
                    description="联盟赛哨兵不能额外购买弹丸",
                    unit=f"剩余 {context.current_ammo}",
                    quantity=0,
                    cost=0,
                    command_type=0,
                    command_param=0,
                    enabled=False,
                    reason="联盟赛哨兵不开放弹丸购买",
                    status_only=True,
                )
            )
        if not context.alive:
            offers.append(
                _offer(
                    key="rmul_auto_respawn",
                    category="revive",
                    title="自动复活进度",
                    short_title=f"{round(context.respawn_progress * 100)}%",
                    description="联盟赛使用自动复活，不支持金币立即复活",
                    unit="自动",
                    quantity=0,
                    cost=0,
                    command_type=0,
                    command_param=0,
                    enabled=False,
                    reason="等待自动复活",
                    status_only=True,
                )
            )
        return offers

    if context.match_mode != "RMUC7v7":
        return offers

    if profile == "Hero":
        offers.extend(
            [
                _local_ammo_offer(context, key="rmuc_hero_42_1", projectile="42mm", quantity=1, cost=10),
                _local_ammo_offer(context, key="rmuc_hero_42_10", projectile="42mm", quantity=10, cost=100),
                _remote_ammo_offer(context, key="rmuc_hero_remote_42_10", projectile="42mm", quantity=10),
            ]
        )
    elif profile.startswith("Infantry") or profile == "Sentinel":
        prefix = "sentinel" if profile == "Sentinel" else "infantry"
        offers.extend(
            [
                _local_ammo_offer(context, key=f"rmuc_{prefix}_17_10", projectile="17mm", quantity=10, cost=10),
                _local_ammo_offer(context, key=f"rmuc_{prefix}_17_100", projectile="17mm", quantity=100, cost=100),
                _remote_ammo_offer(context, key=f"rmuc_{prefix}_remote_17_100", projectile="17mm", quantity=100),
            ]
        )

    combat_profiles = profile == "Hero" or profile.startswith("Infantry") or profile == "Sentinel"
    if combat_profiles and context.alive:
        heal_cost = 50 + _rmuc_time_step(state) * 20
        enabled, reason = _enabled(
            context.gold,
            heal_cost,
            context.out_of_combat and (context.can_remote_heal or context.mock_mode),
            "需要脱离战斗并等待裁判系统开放远程补血",
        )
        offers.append(
            _offer(
                key="rmuc_remote_heal",
                category="recovery",
                title="远程补血",
                short_title="恢复 60% HP",
                description="远程补血需要长按确认，实际结果以裁判系统为准",
                unit="60% 最大血量",
                quantity=1,
                cost=heal_cost,
                command_type=6,
                command_param=0,
                enabled=enabled,
                reason=reason,
                confirmation="hold",
            )
        )

    ground_profiles = combat_profiles or profile == "Engineer"
    if ground_profiles and not context.alive:
        confirm_enabled = context.respawn_can_free or context.mock_mode
        offers.append(
            _offer(
                key="rmuc_confirm_respawn",
                category="revive",
                title="确认复活",
                short_title="确认复活",
                description="确认当前可用的免费或普通复活流程",
                unit="一次",
                quantity=1,
                cost=0,
                command_type=3,
                command_param=0,
                enabled=confirm_enabled,
                reason="裁判系统尚未开放确认复活" if not confirm_enabled else "",
                confirmation="hold",
            )
        )
        estimated = False
        revive_cost = context.respawn_gold_cost
        if revive_cost <= 0 and context.mock_mode:
            revive_cost = _rmuc_time_step(state) * 80 + max(1, int(getattr(state, "level", 1))) * 20
            estimated = True
        can_pay = (context.respawn_can_pay or context.mock_mode) and revive_cost > 0
        enabled, reason = _enabled(context.gold, revive_cost, can_pay, "等待裁判系统下发复活价格")
        offers.append(
            _offer(
                key="rmuc_gold_respawn",
                category="revive",
                title="金币立即复活",
                short_title="立即复活",
                description="价格优先使用裁判系统下发值" if not estimated else "实验室预计价格，不代表正式比赛结果",
                unit="一次",
                quantity=1,
                cost=revive_cost,
                command_type=4,
                command_param=0,
                enabled=enabled,
                reason=reason,
                confirmation="hold",
                estimated=estimated,
            )
        )

    if profile == "Aerial":
        if context.air_support_active:
            offers.append(
                _offer(
                    key="rmuc_air_support_cancel",
                    category="support",
                    title="结束空中支援",
                    short_title="结束支援",
                    description="停止当前空中支援计费",
                    unit="立即",
                    quantity=1,
                    cost=0,
                    command_type=0,
                    command_param=0,
                    enabled=True,
                    confirmation="hold",
                    topic="AirSupportCommand",
                )
            )
        else:
            offers.append(
                _offer(
                    key="rmuc_air_support_paid",
                    category="support",
                    title="开启付费空中支援",
                    short_title="1 金币 / 秒",
                    description="开启后按比赛规则持续计费，需长按确认",
                    unit="按秒计费",
                    quantity=1,
                    cost=1,
                    command_type=2,
                    command_param=0,
                    enabled=context.gold >= 1,
                    reason="金币不足" if context.gold < 1 else "",
                    confirmation="hold",
                    topic="AirSupportCommand",
                )
            )
            if context.air_support_can_free:
                offers.append(
                    _offer(
                        key="rmuc_air_support_free",
                        category="support",
                        title="开启免费空中支援",
                        short_title="免费支援",
                        description="使用当前可用的免费空中支援时段",
                        unit="免费时段",
                        quantity=1,
                        cost=0,
                        command_type=1,
                        command_param=0,
                        enabled=True,
                        confirmation="hold",
                        topic="AirSupportCommand",
                    )
                )
    return offers


class EconomyCommandBridge:
    """Transaction boundary shared by official MQTT and deterministic mock."""

    def __init__(self) -> None:
        self.sequence = 0
        self.last_request: EconomyRequest | None = None
        self.history: list[EconomyTransaction] = []
        self.sender: Callable[[EconomyRequest], bool] | None = None

    @property
    def latest(self) -> EconomyTransaction | None:
        return self.history[-1] if self.history else None

    def submit(
        self,
        state: Any,
        offer: EconomyOffer,
        quantity: int = 1,
        *,
        mock: bool | None = None,
        now: float | None = None,
    ) -> EconomyTransaction:
        if not offer.enabled or offer.status_only:
            raise ValueError(offer.reason or "当前操作不可用")
        now = time.perf_counter() if now is None else float(now)
        quantity = max(1, int(quantity))
        mock = self.sender is None if mock is None else bool(mock)
        command_param = offer.command_param * quantity if offer.command_param > 0 else 0
        payload = (
            encode_air_support_command(offer.command_type)
            if offer.topic == "AirSupportCommand"
            else encode_common_command(offer.command_type, command_param)
        )
        self.sequence += 1
        request = EconomyRequest(
            sequence=self.sequence,
            timestamp=time.time(),
            match_mode=str(getattr(state, "match_mode", "")),
            robot_profile=str(getattr(state, "robot_profile", getattr(state, "robot_type", ""))),
            action=offer.key,
            quantity=quantity,
            cost=offer.cost * quantity,
            command_type=offer.command_type,
            command_param=command_param,
            topic=offer.topic,
            payload=payload,
            mock=mock,
        )
        transaction = EconomyTransaction(
            request=request,
            offer=offer,
            status="pending",
            message="MOCK 正在处理" if mock else "已发送，等待裁判系统确认",
            submitted_at=now,
            deadline_at=now + (2.0 if mock else 5.0),
            mock_complete_at=now + 0.36 if mock else 0.0,
            baseline_gold=int(getattr(state, "remaining_economy", 0)),
            baseline_ammo=int(getattr(state, "remaining_ammo", 0)),
            baseline_health=int(getattr(state, "current_health", 0)),
            baseline_revision=int(getattr(state, "economy_status_revision", 0)),
            baseline_respawn_pending=bool(getattr(state, "respawn_pending", False)),
            baseline_support_active=bool(getattr(state, "air_support_active", False)),
        )
        self.last_request = request
        self.history.append(transaction)
        self.history = self.history[-32:]
        if not mock:
            accepted = bool(self.sender and self.sender(request))
            if not accepted:
                transaction.status = "rejected"
                transaction.message = "MQTT 请求未发送"
                transaction.completed_at = now
        return transaction

    def update(self, state: Any, now: float | None = None) -> EconomyTransaction | None:
        transaction = self.latest
        if transaction is None or transaction.status != "pending":
            return transaction
        now = time.perf_counter() if now is None else float(now)
        if transaction.request.mock and now >= transaction.mock_complete_at:
            self._apply_mock(state, transaction)
            transaction.status = "succeeded"
            transaction.message = "MOCK 操作成功"
            transaction.completed_at = now
            return transaction
        explicit = str(getattr(state, "economy_command_status", "")).lower()
        revision_changed = int(getattr(state, "economy_status_revision", 0)) > transaction.baseline_revision
        if revision_changed and explicit in {"succeeded", "accepted", "success"}:
            transaction.status = "succeeded"
            transaction.message = "裁判系统已确认"
            transaction.completed_at = now
        elif revision_changed and explicit in {"rejected", "denied", "failed"}:
            transaction.status = "rejected"
            transaction.message = "裁判系统拒绝请求"
            transaction.completed_at = now
        elif not transaction.request.mock and self._official_result_observed(state, transaction):
            transaction.status = "succeeded"
            transaction.message = "裁判系统已确认"
            transaction.completed_at = now
        elif now >= transaction.deadline_at:
            transaction.status = "timed_out"
            transaction.message = "未在时限内收到状态确认"
            transaction.completed_at = now
        return transaction

    @staticmethod
    def _official_result_observed(state: Any, transaction: EconomyTransaction) -> bool:
        revision = int(getattr(state, "economy_status_revision", 0))
        if revision <= transaction.baseline_revision:
            return False
        key = transaction.offer.key
        gold = int(getattr(state, "remaining_economy", transaction.baseline_gold))
        ammo = int(getattr(state, "remaining_ammo", transaction.baseline_ammo))
        health = int(getattr(state, "current_health", transaction.baseline_health))
        if "ammo" in key or "_17_" in key or "_42_" in key:
            return ammo > transaction.baseline_ammo or gold < transaction.baseline_gold
        if "heal" in key:
            return health > transaction.baseline_health or gold < transaction.baseline_gold
        if "respawn" in key:
            pending = bool(getattr(state, "respawn_pending", True))
            return health > transaction.baseline_health or (transaction.baseline_respawn_pending and not pending)
        if "support" in key:
            desired = "cancel" not in key
            active = bool(getattr(state, "air_support_active", transaction.baseline_support_active))
            return active == desired and active != transaction.baseline_support_active
        return False

    @staticmethod
    def _apply_mock(state: Any, transaction: EconomyTransaction) -> None:
        request = transaction.request
        offer = transaction.offer
        state.economy_managed = True
        state.remaining_economy = max(0, int(getattr(state, "remaining_economy", 0)) - request.cost)
        if offer.category == "ammo":
            added = max(0, offer.minimum * request.quantity)
            state.remaining_ammo = max(0, int(getattr(state, "remaining_ammo", 0))) + added
            state.ammo_capacity = max(int(getattr(state, "ammo_capacity", 0)), state.remaining_ammo)
        elif offer.key == "rmuc_remote_heal":
            maximum = max(1, int(getattr(state, "max_health", 1)))
            state.current_health = min(maximum, int(getattr(state, "current_health", 0)) + round(maximum * 0.60))
        elif "respawn" in offer.key:
            state.current_health = max(1, int(getattr(state, "max_health", 1)))
            state.respawn_pending = False
            state.respawn_progress = 1.0
        elif offer.topic == "AirSupportCommand":
            state.air_support_active = offer.command_type != 0
        state.economy_status_revision = int(getattr(state, "economy_status_revision", 0)) + 1
        state.economy_command_status = "succeeded"


def request_payload(request: EconomyRequest) -> dict[str, Any]:
    data = asdict(request)
    data["payload"] = request.payload.hex()
    return {"protocol": "rm.economy.request.v2", **data}
