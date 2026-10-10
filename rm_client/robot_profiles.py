from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RobotPerformance:
    max_health: int
    power_limit_w: int
    heat_limit: int
    cooling_rate: int
    projectile: str


@dataclass(frozen=True)
class RobotProfile:
    key: str
    title: str
    short_title: str
    robot_id: int
    icon: str
    description: str
    operator_role: bool = True


RMUC_ROBOTS = (
    RobotProfile("Hero", "英雄机器人", "HERO", 1, "H", "42 mm 火力与高价值目标压制"),
    RobotProfile("Engineer", "工程机器人", "ENG", 2, "E", "矿石、能量单元与战场支援"),
    RobotProfile("Infantry1", "步兵机器人 1", "INF-1", 3, "3", "17 mm 主战与区域争夺"),
    RobotProfile("Infantry2", "步兵机器人 2", "INF-2", 4, "4", "17 mm 主战与交叉火力"),
    RobotProfile("Aerial", "空中机器人", "UAV", 6, "A", "空中支援与全场机动"),
    RobotProfile("Sentinel", "哨兵机器人", "SEN", 7, "S", "自动巡逻、标点与战术支援"),
    RobotProfile("Dart", "飞镖系统", "DART", 8, "D", "飞镖发射与目标选择", False),
    RobotProfile("Radar", "雷达", "RADAR", 9, "R", "全场感知、标点与双倍易伤", False),
)

RMUL_ROBOTS = (
    RobotProfile("Hero", "英雄机器人", "HERO", 1, "H", "42 mm 火力核心"),
    RobotProfile("Infantry1", "步兵机器人", "INF", 3, "3", "17 mm 主战与控制区争夺"),
    RobotProfile("Sentinel", "哨兵机器人", "SEN", 7, "S", "自动巡逻与持续火力"),
)

HERO_HP_MELEE = (200, 225, 250, 275, 300, 325, 350, 375, 400, 450)
HERO_POWER_MELEE = (70, 75, 80, 85, 90, 95, 100, 105, 110, 120)
HERO_HEAT_MELEE = (140, 150, 160, 170, 180, 190, 200, 210, 220, 240)
HERO_COOL_MELEE = (12, 14, 16, 18, 20, 22, 24, 26, 28, 30)
HERO_HP_RANGE = (150, 165, 180, 195, 210, 225, 240, 255, 270, 300)
HERO_POWER_RANGE = (50, 55, 60, 65, 70, 75, 80, 85, 90, 100)
HERO_HEAT_RANGE = (100, 102, 104, 106, 108, 110, 115, 120, 125, 130)
HERO_COOL_RANGE = (20, 23, 26, 29, 32, 35, 38, 41, 44, 50)

INF_HP_POWER = (150, 175, 200, 225, 250, 275, 300, 325, 350, 400)
INF_POWER_POWER = (60, 65, 70, 75, 80, 85, 90, 95, 100, 100)
INF_HP_HEALTH = (200, 225, 250, 275, 300, 325, 350, 375, 400, 400)
INF_POWER_HEALTH = (45, 50, 55, 60, 65, 70, 75, 80, 90, 100)
INF_HEAT_BURST = (170, 180, 190, 200, 210, 220, 230, 240, 250, 260)
INF_COOL_BURST = (5, 7, 9, 11, 12, 13, 14, 16, 18, 20)
INF_HEAT_COOL = (40, 48, 56, 64, 72, 80, 88, 96, 114, 120)
INF_COOL_COOL = (12, 14, 16, 18, 20, 22, 24, 26, 28, 30)
AERIAL_HEAT = (100, 110, 120, 130, 140, 150, 160, 170, 180, 200)
AERIAL_COOL = (20, 30, 40, 50, 60, 70, 80, 90, 100, 120)


def profiles_for_match(match_mode: str) -> tuple[RobotProfile, ...]:
    return RMUL_ROBOTS if match_mode == "RMUL3v3" else RMUC_ROBOTS


def profile_by_key(match_mode: str, key: str) -> RobotProfile:
    profiles = profiles_for_match(match_mode)
    return next((profile for profile in profiles if profile.key == key), profiles[0])


def resolve_performance(
    match_mode: str,
    profile_key: str,
    *,
    level: int = 1,
    hero_type: str = "Melee",
    infantry_chassis: str = "Power",
    infantry_shooter: str = "Burst",
    sentinel_control: str = "Automatic",
) -> RobotPerformance:
    if match_mode == "RMUL3v3":
        if profile_key == "Hero":
            return RobotPerformance(350, 100, 200, 24, "42mm")
        if profile_key.startswith("Infantry"):
            hp, power = (300, 90) if infantry_chassis == "Power" else (350, 75)
            heat, cooling = (230, 14) if infantry_shooter == "Burst" else (88, 24)
            return RobotPerformance(hp, power, heat, cooling, "17mm")
        return RobotPerformance(400, 100, 260, 30, "17mm")

    index = max(0, min(9, int(level) - 1))
    if profile_key == "Hero":
        if hero_type == "Range":
            return RobotPerformance(HERO_HP_RANGE[index], HERO_POWER_RANGE[index], HERO_HEAT_RANGE[index], HERO_COOL_RANGE[index], "42mm")
        return RobotPerformance(HERO_HP_MELEE[index], HERO_POWER_MELEE[index], HERO_HEAT_MELEE[index], HERO_COOL_MELEE[index], "42mm")
    if profile_key.startswith("Infantry"):
        hp = INF_HP_POWER[index] if infantry_chassis == "Power" else INF_HP_HEALTH[index]
        power = INF_POWER_POWER[index] if infantry_chassis == "Power" else INF_POWER_HEALTH[index]
        heat = INF_HEAT_BURST[index] if infantry_shooter == "Burst" else INF_HEAT_COOL[index]
        cooling = INF_COOL_BURST[index] if infantry_shooter == "Burst" else INF_COOL_COOL[index]
        return RobotPerformance(hp, power, heat, cooling, "17mm")
    if profile_key == "Engineer":
        return RobotPerformance(250, 120, 0, 0, "None")
    if profile_key == "Aerial":
        return RobotPerformance(0, 0, AERIAL_HEAT[index], AERIAL_COOL[index], "17mm")
    if profile_key == "Sentinel":
        return RobotPerformance(200, 60, 100, 10, "17mm") if sentinel_control == "SemiAuto" else RobotPerformance(400, 100, 260, 30, "17mm")
    return RobotPerformance(0, 0, 0, 0, "None")


def robot_id_for_alliance(profile: RobotProfile, alliance: str) -> int:
    if alliance not in ("Red", "Blue"):
        raise ValueError("Unknown robot alliance")
    return profile.robot_id + (100 if alliance == "Blue" else 0)


def apply_profile_to_state(state: Any, profile: RobotProfile, performance: RobotPerformance, level: int) -> None:
    state.robot_profile = profile.key
    state.robot_type = profile.title
    state.robot_id = robot_id_for_alliance(profile, getattr(state, "alliance_color", "Red"))
    state.level = max(1, min(10, int(level)))
    state.max_health = performance.max_health
    state.current_health = performance.max_health
    state.power_limit = performance.power_limit_w
    state.max_heat = float(performance.heat_limit)
    state.heat_cooldown_rate = float(performance.cooling_rate)
    state.projectile_type = performance.projectile
    capacity = 12 if performance.projectile == "42mm" else (180 if performance.projectile == "17mm" else 0)
    state.ammo_capacity = capacity
    state.remaining_ammo = capacity
