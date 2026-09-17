"""RM2026 自定义客户端协议层（对齐官方 V1.3.1 messages.proto）。

手写 protobuf wire 编解码，零第三方依赖：
- 解码全部下行消息（25 条）为 dict
- 编码全部上行消息（11 条）为 bytes

消息名、方向与字段号以 2026-05-19 发布的 V1.3.1 为准。
"""

from __future__ import annotations

import struct
from typing import Any, Callable
from .contract import FIELDS, SOURCE_PDF, SOURCE_SHA256
from ..validation import InvalidRefereePayload, validate_message

from ..wire import (
    encode_varint,
    _tag,
    encode_uint,
    encode_int,
    encode_bool,
    encode_float,
    encode_bytes,
    encode_string,
    encode_packed_uints,
    encode_packed_ints,
    _read_varint,
    decode_fields,
    _u,
    _i,
    _f,
    _b,
    _s,
    _bool,
    _packed,
    _packed_ints,
    _sub
)

PROTOCOL_VERSION = "1.3.1"

# --------------------------------------------------------------------------
# protobuf wire 基础编解码
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# 消息清单（对齐 messages.proto）
# --------------------------------------------------------------------------

UPLINK_MESSAGES = frozenset({
    "KeyboardMouseControl",
    "CustomControl",
    "MapClickCmd",
    "AssemblyCommand",
    "RobotPerformanceSelectionCommand",
    "CommonCommand",
    "HeroDeployModeEventCommand",
    "RuneActivateCommand",
    "DartCommand",
    "SentryCtrlCommand",
    "AirSupportCommand",
})

DOWNLINK_MESSAGES = frozenset({
    "GameStatus",
    "GlobalUnitStatus",
    "GlobalLogisticsStatus",
    "GlobalSpecialMechanism",
    "Event",
    "RobotInjuryStat",
    "RobotRespawnStatus",
    "RobotStaticStatus",
    "RobotDynamicStatus",
    "RobotModuleStatus",
    "RobotPosition",
    "Buff",
    "PenaltyInfo",
    "RobotPathPlanInfo",
    "MapClickInfo",
    "RadarInfoToClient",
    "CustomByteBlock",
    "TechCoreMotionStateSync",
    "RobotPerformanceSelectionSync",
    "DeployModeStatusSync",
    "RuneStatusSync",
    "SentryStatusSync",
    "DartSelectTargetStatusSync",
    "SentryCtrlResult",
    "AirSupportStatusSync",
})

ALL_MESSAGES = frozenset(UPLINK_MESSAGES | DOWNLINK_MESSAGES)


def topic_message_name(topic: str) -> str:
    name = str(topic).strip().rstrip("/").rsplit("/", 1)[-1]
    return name if name in ALL_MESSAGES else ""


# --------------------------------------------------------------------------
# 下行解码
# --------------------------------------------------------------------------

def _decode_game_status(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "current_round": _u(fields, 1),
        "total_rounds": _u(fields, 2),
        "red_score": _u(fields, 3),
        "blue_score": _u(fields, 4),
        "current_stage": _u(fields, 5),
        "stage_countdown_sec": _i(fields, 6),
        "stage_elapsed_sec": _i(fields, 7),
        "is_paused": _bool(fields, 8),
    }


def _decode_global_unit_status(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "base_health": _u(fields, 1),
        "base_status": _u(fields, 2),
        "base_shield": _u(fields, 3),
        "outpost_health": _u(fields, 4),
        "outpost_status": _u(fields, 5),
        "enemy_base_health": _u(fields, 6),
        "enemy_base_status": _u(fields, 7),
        "enemy_base_shield": _u(fields, 8),
        "enemy_outpost_health": _u(fields, 9),
        "enemy_outpost_status": _u(fields, 10),
        "robot_health": _packed(fields, 11),
        "robot_bullets": _packed_ints(fields, 12),
        "total_damage_ally": _u(fields, 13),
        "total_damage_enemy": _u(fields, 14),
    }


def _decode_global_logistics(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "remaining_economy": _u(fields, 1),
        "total_economy_obtained": _u(fields, 2),
        "tech_level": _u(fields, 3),
        "encryption_level": _u(fields, 4),
    }


def _decode_special_mechanism(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "mechanism_id": _packed(fields, 1),
        "mechanism_time_sec": _packed_ints(fields, 2),
    }


def _decode_event(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {"event_id": _i(fields, 1), "param": _s(fields, 2)}


def _decode_injury(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "total_damage": _u(fields, 1),
        "collision_damage": _u(fields, 2),
        "small_projectile_damage": _u(fields, 3),
        "large_projectile_damage": _u(fields, 4),
        "dart_splash_damage": _u(fields, 5),
        "module_offline_damage": _u(fields, 6),
        "offline_damage": _u(fields, 7),
        "penalty_damage": _u(fields, 8),
        "server_kill_damage": _u(fields, 9),
        "killer_id": _u(fields, 10),
    }


def _decode_respawn(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "is_pending_respawn": _bool(fields, 1),
        "total_respawn_progress": _u(fields, 2),
        "current_respawn_progress": _u(fields, 3),
        "can_free_respawn": _bool(fields, 4),
        "gold_cost_for_respawn": _u(fields, 5),
        "can_pay_for_respawn": _bool(fields, 6),
    }


def _decode_static(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "connection_state": _u(fields, 1),
        "field_state": _u(fields, 2),
        "alive_state": _u(fields, 3),
        "robot_id": _u(fields, 4),
        "robot_type": _u(fields, 5),
        "performance_system_shooter": _u(fields, 6),
        "performance_system_chassis": _u(fields, 7),
        "level": _u(fields, 8),
        "max_health": _u(fields, 9),
        "max_heat": _u(fields, 10),
        "heat_cooldown_rate": _f(fields, 11),
        "max_power": _u(fields, 12),
        "max_buffer_energy": _u(fields, 13),
        "max_chassis_energy": _u(fields, 14),
    }


def _decode_dynamic(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "current_health": _u(fields, 1),
        "current_heat": _f(fields, 2),
        "last_projectile_fire_rate": _f(fields, 3),
        "current_chassis_energy": _u(fields, 4),
        "current_buffer_energy": _u(fields, 5),
        "current_experience": _u(fields, 6),
        "experience_for_upgrade": _u(fields, 7),
        "total_projectiles_fired": _u(fields, 8),
        "remaining_ammo": _u(fields, 9),
        "is_out_of_combat": _bool(fields, 10),
        "out_of_combat_countdown": _u(fields, 11),
        "can_remote_heal": _bool(fields, 12),
        "can_remote_ammo": _bool(fields, 13),
    }


def _decode_module_status(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "power_manager": _u(fields, 1),
        "rfid": _u(fields, 2),
        "light_strip": _u(fields, 3),
        "small_shooter": _u(fields, 4),
        "big_shooter": _u(fields, 5),
        "uwb": _u(fields, 6),
        "armor": _u(fields, 7),
        "video_transmission": _u(fields, 8),
        "capacitor": _u(fields, 9),
        "main_controller": _u(fields, 10),
        "laser_detection_module": _u(fields, 11),
    }


def _decode_position(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "x": _f(fields, 1),
        "y": _f(fields, 2),
        "z": _f(fields, 3),
        "yaw": _f(fields, 4),
        "robot_id": _u(fields, 5),
    }


def _decode_buff(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "robot_id": _u(fields, 1),
        "buff_type": _u(fields, 2),
        "buff_level": _i(fields, 3),
        "buff_max_time": _u(fields, 4),
        "buff_left_time": _u(fields, 5),
    }


def _decode_penalty(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "penalty_type": _u(fields, 1),
        "penalty_effect_sec": _u(fields, 2),
        "total_penalty_num": _u(fields, 3),
    }


def _decode_path_plan(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "intention": _u(fields, 1),
        "start_pos_x": _u(fields, 2),
        "start_pos_y": _u(fields, 3),
        "offset_x": _packed_ints(fields, 4),
        "offset_y": _packed_ints(fields, 5),
        "sender_id": _u(fields, 6),
    }


def _decode_map_click(fields: dict[int, list[Any]]) -> dict[str, Any]:
    """V1.3.1 地图标记公共结构（下行 Info / 上行 Cmd 字段相同）。"""
    return {
        "is_send_all": _u(fields, 1),
        "robot_id": _b(fields, 2),
        # 官方 proto 的字段名与表格文字存在 mode/type 描述互换；wire 编号
        # 以 proto 为准：3=mode、6=type。
        "mode": _u(fields, 3),
        "enemy_id": _u(fields, 4),
        "ascii": _u(fields, 5),
        "type": _u(fields, 6),
        "map_x": _f(fields, 7),
        "map_y": _f(fields, 8),
    }


def _decode_radar(fields: dict[int, list[Any]]) -> dict[str, Any]:
    robots = []
    for sub in _sub(fields, 1):
        robots.append({
            "target_pos_x": _u(sub, 1),
            "target_pos_y": _u(sub, 2),
            "is_high_light": _u(sub, 3),
        })
    return {"robots": robots}


def _decode_custom_byte_block(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {"data": _b(fields, 1)}


def _decode_tech_core(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "maximum_difficulty_level": _u(fields, 1),
        "basic_state": _u(fields, 2),
        "putin_state": _u(fields, 3),
        "move_state": _u(fields, 4),
        "rotate_state": _u(fields, 5),
        "enemy_core_status": _u(fields, 6),
        "remain_time_all": _u(fields, 7),
        "remain_time_step": _u(fields, 8),
    }


def _decode_performance_sync(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "shooter": _u(fields, 1),
        "chassis": _u(fields, 2),
        "sentry_control": _u(fields, 3),
    }


def _decode_deploy(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {"status": _u(fields, 1)}


def _decode_rune(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "rune_status": _u(fields, 1),
        "activated_arms": _u(fields, 2),
        "average_rings": _f(fields, 3),
    }


def _decode_sentry(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "posture_id": _u(fields, 1),
        "is_weakened": _bool(fields, 2),
    }


def _decode_dart(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {"target_id": _u(fields, 1), "open": _u(fields, 2)}


def _decode_sentry_result(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {"command_id": _u(fields, 1), "result_code": _u(fields, 2)}


def _decode_air_support(fields: dict[int, list[Any]]) -> dict[str, Any]:
    return {
        "airsupport_status": _u(fields, 1),
        "left_time": _u(fields, 2),
        "cost_coins": _u(fields, 3),
        "is_being_targeted": _u(fields, 4),
        "shooter_status": _u(fields, 5),
    }


_DOWNLINK_DECODERS: dict[str, Callable[[dict[int, list[Any]]], dict[str, Any]]] = {
    "GameStatus": _decode_game_status,
    "GlobalUnitStatus": _decode_global_unit_status,
    "GlobalLogisticsStatus": _decode_global_logistics,
    "GlobalSpecialMechanism": _decode_special_mechanism,
    "Event": _decode_event,
    "RobotInjuryStat": _decode_injury,
    "RobotRespawnStatus": _decode_respawn,
    "RobotStaticStatus": _decode_static,
    "RobotDynamicStatus": _decode_dynamic,
    "RobotModuleStatus": _decode_module_status,
    "RobotPosition": _decode_position,
    "Buff": _decode_buff,
    "PenaltyInfo": _decode_penalty,
    "RobotPathPlanInfo": _decode_path_plan,
    "MapClickInfo": _decode_map_click,
    "RadarInfoToClient": _decode_radar,
    "CustomByteBlock": _decode_custom_byte_block,
    "TechCoreMotionStateSync": _decode_tech_core,
    "RobotPerformanceSelectionSync": _decode_performance_sync,
    "DeployModeStatusSync": _decode_deploy,
    "RuneStatusSync": _decode_rune,
    "SentryStatusSync": _decode_sentry,
    "DartSelectTargetStatusSync": _decode_dart,
    "SentryCtrlResult": _decode_sentry_result,
    "AirSupportStatusSync": _decode_air_support,
}


def decode_message(name: str, payload: bytes) -> dict[str, Any]:
    """按消息名解码下行 payload。

    - 未知消息 / 空 payload / 首个字段就截断时返回 {}（调用方应丢弃）
    - 成功时附带 __present__（实际出现的字段号集合），供状态层避免
      把“缺字段的默认值 0”当作有效数据覆盖本地状态
    """
    decoder = _DOWNLINK_DECODERS.get(str(name).strip())
    if decoder is None:
        return {}
    try:
        validate_message(str(name).strip(), bytes(payload), FIELDS)
    except InvalidRefereePayload:
        return {}
    fields = decode_fields(bytes(payload))
    if not fields or not set(fields).intersection(FIELDS[str(name).strip()]):
        return {}
    # Unknown enum values are not authority to enter a phase/video mode.
    if name == "GameStatus" and 5 in fields and _u(fields, 5) not in range(6):
        return {}
    if name == "DeployModeStatusSync" and 1 in fields and _u(fields, 1) not in {0, 1}:
        return {}
    data = decoder(fields)
    data["__present__"] = frozenset(fields.keys())
    return data


# --------------------------------------------------------------------------
# 上行编码
# --------------------------------------------------------------------------

def encode_keyboard_mouse_control(
    mouse_x: int = 0,
    mouse_y: int = 0,
    mouse_z: int = 0,
    left_button_down: bool = False,
    right_button_down: bool = False,
    keyboard_value: int = 0,
    mid_button_down: bool = False,
) -> bytes:
    return b"".join([
        encode_int(1, mouse_x),
        encode_int(2, mouse_y),
        encode_int(3, mouse_z),
        encode_bool(4, left_button_down),
        encode_bool(5, right_button_down),
        encode_uint(6, keyboard_value),
        encode_bool(7, mid_button_down),
    ])




def encode_custom_control(data: bytes) -> bytes:
    data = bytes(data)
    if len(data) > 30:
        raise ValueError(f"CustomControl 载荷最多 30 字节，实际 {len(data)} 字节")
    return encode_bytes(1, data)






def encode_map_click_cmd(
    is_send_all: int = 0,
    robot_id: bytes = bytes(7),
    mode: int = 1,
    enemy_id: int = 0,
    ascii_code: int = 0,
    mark_type: int = 1,
    map_x: float = 0.0,
    map_y: float = 0.0,
) -> bytes:
    robot_id = bytes(robot_id)
    if len(robot_id) > 7:
        raise ValueError(f"MapClickCmd robot_id 固定 7 字节，实际 {len(robot_id)} 字节")
    robot_id = robot_id.ljust(7, b"\x00")
    return b"".join([
        encode_uint(1, is_send_all),
        encode_bytes(2, robot_id),
        encode_uint(3, mode),
        encode_uint(4, enemy_id),
        encode_uint(5, ascii_code),
        encode_uint(6, mark_type),
        encode_float(7, map_x),
        encode_float(8, map_y),
    ])


# 仅保留 Python API 兼容性；实际发布 topic 必须是 V1.3.1 MapClickCmd。
encode_map_click_info_notify = encode_map_click_cmd


def encode_assembly_command(operation: int, difficulty: int) -> bytes:
    return b"".join([encode_uint(1, operation), encode_uint(2, difficulty)])


def encode_robot_performance_selection_command(
    shooter: int, chassis: int, sentry_control: int
) -> bytes:
    return b"".join([
        encode_uint(1, shooter),
        encode_uint(2, chassis),
        encode_uint(3, sentry_control),
    ])


def encode_common_command(cmd_type: int, param: int) -> bytes:
    return b"".join([encode_uint(1, cmd_type), encode_uint(2, param)])


def encode_hero_deploy_mode_event_command(mode: int) -> bytes:
    return encode_uint(1, mode)


def encode_rune_activate_command(activate: int) -> bytes:
    return encode_uint(1, activate)


def encode_dart_command(target_id: int, open_gate: bool, launch_confirm: bool) -> bytes:
    return b"".join([
        encode_uint(1, target_id),
        encode_bool(2, open_gate),
        encode_bool(3, launch_confirm),
    ])


def encode_sentry_ctrl_command(command_id: int) -> bytes:
    return encode_uint(1, command_id)


def encode_air_support_command(command_id: int) -> bytes:
    return encode_uint(1, command_id)
