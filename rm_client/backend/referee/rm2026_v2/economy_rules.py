"""RMUC7v7 V2 rule estimates and documented command membership.

Pure arithmetic and peer-state request prerequisites, not an offer, server
quote, current Safety authorization or permission to publish. Callers must establish explicit V2/RMUC identity and authoritative,
current target observations before using these values. No defaults or clamps.
V1 behavior, transport and UI remain unchanged; V2 request prerequisites are
explicit local policy. No profile is registered here.
"""
import math

from .contract import AIR_SUPPORT_COMMAND_IDS, SENTRY_COMMAND_IDS
from .observations import WireSnapshot

RULES_URL = "https://bbs.robomaster.com/wiki/20204847/809871"
RULES_VERSION = "2.2.0 (2026-08-07)"
RULES_SHA256 = "88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5"


def _integer_in_range(value: int, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def estimate_remote_heal_cost(remaining_seconds: int) -> int:
    """Base 60%-HP heal cost; excludes any Sentry intervention surcharge.

    Table 5-6 p.77: 50 + ceil((420-T)/60 * 20). Multiplication is
    inside the ceiling. This is a rule estimate, not a received server quote.
    """
    remaining = _integer_in_range(remaining_seconds, 0, 420, "remaining_seconds")
    return 50 + (420 - remaining + 2) // 3


def estimate_leveled_revive_cost(remaining_seconds: int, level: int) -> int:
    """Base same-level ground revival comparator, not a target quote.

    Table 5-6 p.77: ceil((420-T)/60)*80 + L*20. Level1..10 is
    the Hero/Infantry/Aerial system (§5.4.1), not an inferred Sentry level.
    """
    remaining = _integer_in_range(remaining_seconds, 0, 420, "remaining_seconds")
    observed_level = _integer_in_range(level, 1, 10, "level")
    return ((420 - remaining + 59) // 60) * 80 + observed_level * 20


def estimate_air_countermeasure_cost(remaining_seconds: int, level: int) -> int:
    """Rule estimate for release-and-call: twice the same-level comparator.

    Requires the actual aerial level. Does not infer shooter_status, eligibility,
    counter count, operator permission, or unique execution acknowledgement.
    """
    return 2 * estimate_leveled_revive_cost(remaining_seconds, level)


def is_documented_command(topic: str, command_id: int) -> bool:
    """Only membership in the V2 Sentry/Air enums; never send permission."""
    if type(topic) is not str or type(command_id) is not int:
        return False
    if topic == "SentryCtrlCommand":
        return command_id in SENTRY_COMMAND_IDS
    if topic == "AirSupportCommand":
        return command_id in AIR_SUPPORT_COMMAND_IDS
    if topic == "CommonCommand":
        return command_id in range(1, 7)
    if topic == "MapClickCmd":
        return command_id == 0
    return False


# Local action-use policy, matching the existing readiness two-second bound.
# This is not an official TTL; each required field keeps its own wire receipt.
_ACTION_MAX_AGE_S = 2.0
_V2_PROFILE_ID = "rm2026-v2.0.0"


def _fresh_integer(snapshot, message: str, field: str, now: float) -> int:
    observation = snapshot.get(message, field)
    if observation is None:
        raise ValueError(f"missing {message}.{field}")
    receipt = observation.received_at
    if (type(receipt) not in (int, float) or not math.isfinite(receipt)
            or receipt < 0 or not 0 <= now - receipt <= _ACTION_MAX_AGE_S):
        raise ValueError(f"stale or invalid {message}.{field} receipt")
    if type(observation.value) is not int:
        raise ValueError(f"invalid {message}.{field} integer")
    return observation.value


def _fresh_bool(snapshot, message: str, field: str, now: float) -> bool:
    observation = snapshot.get(message, field)
    if observation is None:
        raise ValueError(f"missing {message}.{field}")
    receipt = observation.received_at
    if (type(receipt) not in (int, float) or not math.isfinite(receipt)
            or receipt < 0 or not 0 <= now - receipt <= _ACTION_MAX_AGE_S
            or type(observation.value) is not bool):
        raise ValueError(f"invalid or stale {message}.{field} boolean")
    return observation.value


def _business_decision(topic, command_id, snapshot, *, now, param):
    """RMUC estimates for explicit requests, not proof of target eligibility.

    Caller must bind actual RMUC7v7 state/session at initial and final enqueue.
    This pure snapshot intentionally does not claim a mode exists on the wire.
    """
    value = lambda message, field: _fresh_integer(snapshot, message, field, now)
    flag = lambda message, field: _fresh_bool(snapshot, message, field, now)
    value("GameStatus", "current_round")
    if value("GameStatus", "current_stage") != 4:
        raise ValueError("V2 economic requests require MATCH")
    robot = value("RobotStaticStatus", "robot_id")
    value("RobotStaticStatus", "robot_type")
    if robot not in {*range(1, 10), *range(101, 110)} or snapshot.client_id != str(robot):
        raise ValueError("observed robot ID must match configured ClientId")
    if (value("RobotStaticStatus", "connection_state") != 1
            or value("RobotStaticStatus", "field_state") != 0):
        raise ValueError("requester must be observed connected/on-field")
    penalty = snapshot.get("PenaltyInfo", "penalty_type")
    if penalty is not None and penalty.value == 3:
        raise ValueError("current red-card observation blocks economic request")
    role = robot % 100
    reason = "Request only; server decides eligibility and completion; not a payment ACK"
    if topic in {"SentryCtrlCommand", "MapClickCmd"}:
        if param != 0:
            raise ValueError("Sentry/Map request has no quantity parameter")
        if topic == "SentryCtrlCommand" and role != 6:
            raise ValueError("Sentry requester must be aerial6/106, target same-team7/107")
        if topic == "SentryCtrlCommand" and command_id == 6:
            raise ValueError("Sentry6 target can_pay/respawn quote and included intervention fee unavailable")
        mode = value("RobotPerformanceSelectionSync", "sentry_control")
        if mode not in {0, 1}:
            raise ValueError("unknown same-team Sentry control mode")
        fee = 50 if mode == 0 else 0
        cost = fee
        if topic == "SentryCtrlCommand":
            if command_id == 1:
                cost += 50
                reason += "; fixed50 local17mm rounds; zone/team quota server-checked"
            elif command_id == 3:
                cost += 150
                reason += "; fixed100 remote17mm rounds; target remote eligibility unknown; six-second service"
            elif command_id == 4:
                cost += estimate_remote_heal_cost(value("GameStatus", "stage_countdown_sec"))
                reason += "; target HP/remote eligibility unknown; six-second service"
            elif command_id == 5:
                reason += "; target pending/free-respawn eligibility unknown"
            else:
                posture = value("SentryStatusSync", "posture_id")
                if posture not in {1, 2, 3}:
                    raise ValueError("unknown target Sentry posture")
                flag("SentryStatusSync", "is_weakened")
                flag("SentryStatusSync", "is_powered")
                reason += "; target stance cooldown/enhanced remaining time server-checked"
        else:
            reason += "; same-team Sentry map intervention"
        reason += f"; intervention fee {fee} coins"
    elif topic == "CommonCommand":
        infantry = role in {3, 4, 5}
        hero = role == 1
        if command_id in {3, 4}:
            if role not in {1, 2, 3, 4, 5}:
                raise ValueError("Common revival requires own ground Hero/Infantry/Engineer")
            if param != 0 or value("RobotStaticStatus", "alive_state") != 2:
                raise ValueError("revival requires param0 and observed dead state")
            if not flag("RobotRespawnStatus", "is_pending_respawn"):
                raise ValueError("no observed pending respawn")
            if not flag("RobotRespawnStatus", "can_free_respawn" if command_id == 3 else "can_pay_for_respawn"):
                raise ValueError("observed respawn permission denied")
            cost = 0 if command_id == 3 else value("RobotRespawnStatus", "gold_cost_for_respawn")
            if cost < 0:
                raise ValueError("invalid current respawn quote")
        else:
            if not (hero or infantry) or value("RobotStaticStatus", "alive_state") != 1:
                raise ValueError("Common supply/heal requires alive Hero/Infantry")
            if command_id == 1:
                if not infantry or not 10 <= param <= 1000 or param % 10:
                    raise ValueError("local17mm requires Infantry and positive ten-round units <=1000")
                cost = param
                reason += "; supply zone/cumulative team quota server-checked"
            elif command_id == 2:
                if not hero or not 1 <= param <= 100:
                    raise ValueError("local42mm requires Hero and quantity1..100")
                cost = 10 * param
                reason += "; supply zone/cumulative team quota server-checked"
            else:
                if param != 0:
                    raise ValueError("remote command parameter must be0, not a quantity multiplier")
                if not flag("RobotDynamicStatus", "is_out_of_combat"):
                    raise ValueError("remote request requires observed out-of-combat")
                if command_id == 5:
                    if not flag("RobotDynamicStatus", "can_remote_ammo"):
                        raise ValueError("remote ammo permission denied")
                    cost = 150
                    reason += "; fixed10x42mm" if hero else "; fixed100x17mm"
                else:
                    if not flag("RobotDynamicStatus", "can_remote_heal"):
                        raise ValueError("remote heal permission denied")
                    hp = value("RobotDynamicStatus", "current_health")
                    maximum = value("RobotStaticStatus", "max_health")
                    if not 0 < hp < maximum:
                        raise ValueError("remote heal requires positive nonfull observed HP")
                    cost = estimate_remote_heal_cost(value("GameStatus", "stage_countdown_sec"))
                reason += "; six-second service, not a five-second transaction ACK"
    else:
        raise ValueError("unsupported V2 economic route")
    coins = value("GlobalLogisticsStatus", "remaining_economy")
    if coins < cost:
        return False, "insufficient observed coins for current estimate", cost
    return True, reason, cost


def request_decision(topic: str, command_id: int, snapshot, *, now: float, param: int = 0
                     ) -> tuple[bool, str, int | None]:
    """Pure peer-state request prerequisites; Safety is checked separately.

    Values come from
    the current owner's immutable wire snapshot, not RobotState or UI defaults.
    Returns requestable, prospective reason and fixed estimate (None for Air2's
    ongoing charge). Neither a positive result nor a held snapshot is authority,
    server acceptance, a quote guarantee or a transaction acknowledgement.
    """
    if not is_documented_command(topic, command_id):
        return False, "unsupported V2 command", None
    if type(snapshot) is not WireSnapshot or snapshot.profile_id != _V2_PROFILE_ID:
        return False, "current V2 wire observations required", None
    try:
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            return False, "invalid action observation clock", None
        if type(param) is not int:
            return False, "command parameter must be an integer", None
        if topic != "AirSupportCommand":
            return _business_decision(topic, command_id, snapshot, now=now, param=param)
        value = lambda message, field: _fresh_integer(snapshot, message, field, now)
        value("GameStatus", "current_round")  # Explicit stored scope, not a vendor sequence.
        if value("GameStatus", "current_stage") != 4:
            return False, "V2 live Air requests require MATCH (local policy)", None
        robot_id = value("RobotStaticStatus", "robot_id")
        value("RobotStaticStatus", "robot_type")  # Raw scope only; no guessed type enum.
        if robot_id not in {6, 106} or snapshot.client_id != str(robot_id):
            return False, "observed aerial robot ID must match configured ClientId", None
        active = value("AirSupportStatusSync", "airsupport_status")
        if active not in {0, 1}:
            return False, "unknown air support state", None
        reason = "请求条件满足，待服务器确认；判罚状态未核实"
        if command_id == 0:
            if active != 1:
                return False, "cancel requires observed active support (local policy)", None
            return True, reason, 0
        if (value("RobotStaticStatus", "connection_state") != 1
                or value("RobotStaticStatus", "field_state") != 0):
            return False, "Air start requires observed connected/on-field state", None
        penalty = snapshot.get("PenaltyInfo", "penalty_type")
        # Trigger-based last-value evidence: no TTL clearance or inferred history.
        # Other/missing values remain unknown, never proof a red card was revoked.
        if penalty is not None and penalty.value == 3:
            return False, "current red-card observation blocks Air start", None
        shooter = value("AirSupportStatusSync", "shooter_status")
        if command_id == 3:
            if shooter != 2:
                return False, "paid release requires observed shooter_status=2", None
            cost = estimate_air_countermeasure_cost(
                value("GameStatus", "stage_countdown_sec"),
                value("RobotStaticStatus", "level"))
            if value("GlobalLogisticsStatus", "remaining_economy") < cost:
                return False, "insufficient observed coins for current release estimate", cost
            return True, (reason + f"；解除反制费用估价{cost}金币；后续支援模式/总价未确认"), cost
        if active != 0 or shooter != 1:
            return False, "ordinary Air call requires inactive/normal shooter (local policy)", None
        free_time = value("AirSupportStatusSync", "left_time")
        if free_time < 0:
            return False, "invalid observed free-time balance", None
        if command_id == 1:
            if free_time == 0:
                return False, "no observed free support time", None
            return True, reason, 0
        if free_time == 0 and value("GlobalLogisticsStatus", "remaining_economy") < 1:
            return False, "paid start needs observed first-second balance (local policy)", None
        return True, reason + "；免费优先，用尽后按1金币/秒持续消耗", None
    except (ValueError, OverflowError) as exc:
        return False, str(exc), None
