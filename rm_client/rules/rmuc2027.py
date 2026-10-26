"""Reviewed RMUC 2027 V1.0.0 facts, not a referee-wire specification.

Only this leaf's DATA is public. Heavy is the new 2027 role, NOT the removed 2026 hero; there is no Engineer.
Page locators are one-based PDF pages (printed page = PDF page - 1).
"""


def _cite(page, section):
    return {"source": 0, "pdf_page": page, "printed_page": page - 1,
            "section": section}


_MODE = {
    "duration_sec": 420,
    "field_size_m": [28.0, 15.0],
    "victory_points": None,
    "score_title": "累计控制度",
    "control": {
        "zone_count": 4,
        "temporary_capture_sec": 5,
        "restore_full_control_sec": 5,
        "both_outpost_positions_score_per_sec": 1,
        "both_base_positions_score_per_sec": 3,
        "fixed_winning_threshold": None,
        "timeout_priority": ["accumulated_control", "total_damage", "remaining_team_health"],
    },
    "roles": [
        {"key": "Heavy", "title": "重装机器人", "short_title": "重装",
         "robot_id": 1, "projectile": "42mm", "operator": True},
        {"key": "Infantry1", "title": "步兵机器人3", "short_title": "步兵3",
         "robot_id": 3, "projectile": "17mm", "operator": True},
        {"key": "Infantry2", "title": "步兵机器人4", "short_title": "步兵4",
         "robot_id": 4, "projectile": "17mm", "operator": True},
        {"key": "Aerial", "title": "空中系统", "short_title": "空中",
         "robot_id": 6, "projectile": "None", "operator": True},
        {"key": "Sentinel", "title": "哨兵机器人", "short_title": "哨兵",
         "robot_id": 7, "projectile": "17mm", "operator": False},
        {"key": "Dart", "title": "飞镖系统", "short_title": "飞镖",
         "robot_id": 8, "projectile": "None", "operator": True},
        {"key": "Radar", "title": "雷达系统", "short_title": "雷达",
         "robot_id": 9, "projectile": "None", "operator": False},
    ],
    # Base attributes, before stance, terrain, rune or logistics modifiers.
    # Infantry: default health-priority chassis / cooling-priority shooter, L1.
    "performance": {
        "Heavy": {"max_health": 400, "power_limit_w": 50,
                 "heat_limit": None, "cooling_rate": None, "projectile": "None"},
        "Infantry1": {"max_health": 200, "power_limit_w": 45,
                      "heat_limit": 40, "cooling_rate": 12, "projectile": "17mm"},
        "Infantry2": {"max_health": 200, "power_limit_w": 45,
                      "heat_limit": 40, "cooling_rate": 12, "projectile": "17mm"},
        "Sentinel": {"max_health": 400, "power_limit_w": 100,
                     "heat_limit": 260, "cooling_rate": 30, "projectile": "17mm"},
        "Aerial": {"max_health": None, "power_limit_w": None,
                   "heat_limit": None, "cooling_rate": None, "projectile": "None"},
        "Dart": {"max_health": None, "power_limit_w": None,
                 "heat_limit": None, "cooling_rate": None, "projectile": "None"},
        "Radar": {"max_health": None, "power_limit_w": None,
                  "heat_limit": None, "cooling_rate": None, "projectile": "None"},
    },
    "performance_variants": {},
    # Independently transcribed from the 2027 tables, not imported from 2026.
    "infantry_levels": {
        "chassis": {
            "Power": {
                "max_health": [150, 175, 200, 225, 250, 275, 300, 325, 350, 400],
                "power_limit_w": [60, 65, 70, 75, 80, 85, 90, 95, 100, 100],
            },
            "Health": {
                "max_health": [200, 225, 250, 275, 300, 325, 350, 375, 400, 400],
                "power_limit_w": [45, 50, 55, 60, 65, 70, 75, 80, 90, 100],
            },
        },
        "shooter": {
            "Burst": {
                "heat_limit": [170, 180, 190, 200, 210, 220, 230, 240, 250, 260],
                "cooling_rate": [5, 7, 9, 11, 12, 13, 14, 16, 18, 20],
            },
            "Cooling": {
                "heat_limit": [40, 48, 56, 64, 72, 80, 88, 96, 104, 120],
                "cooling_rate": [12, 14, 16, 18, 20, 22, 24, 26, 28, 30],
            },
        },
    },
    "initial_ammo": {"Heavy": 0, "Infantry1": 0, "Infantry2": 0, "Sentinel": 300},
    "base_health": 10000,
    "base_max_health": 10000,
    "enemy_base_health": 10000,
    "enemy_base_max_health": 10000,
    "outpost_health": 1000,
    "outpost_max_health": 1000,
    "enemy_outpost_health": 1000,
    "enemy_outpost_max_health": 1000,
    # A 2026 numeric virtual shield must not be silently carried over.
    "base_virtual_shield": None,
    "economy": {
        "initial_coins": 800,
        "periodic_coin_grants": [
            {"countdown": "05:59", "coins": 100},
            {"countdown": "04:59", "coins": 100},
            {"countdown": "03:59", "coins": 100},
            {"countdown": "02:59", "coins": 100},
            {"countdown": "01:59", "coins": 100},
            {"countdown": "00:59", "coins": 300},
        ],
        "ammo_17mm_local": {"coins": 10, "quantity": 10, "team_cap": 1000},
        "ammo_17mm_remote": {"coins": 150, "quantity": 100, "team_cap": 1000},
        "ammo_42mm_local": {"coins": 10, "quantity": 1, "team_cap": 100},
        "ammo_42mm_remote": {"coins": 150, "quantity": 10, "team_cap": 100},
        "remote_delay_sec": 6,
        "out_of_combat_sec": 6,
        "remote_heal": {
            "cost_formula": "50 + ceil(((420 - remaining_sec) / 60) * 20)",
            "health_fraction": 0.60, "delay_sec": 6,
            "requires_out_of_combat": True,
            "logistics_modifier": "multiply health_fraction by logistics_coefficient",
        },
        "respawn": {
            "progress_formula": "round_half_up(10 + (420 - remaining_sec) / 10 + 20 * prior_paid_respawns)",
            "progress_per_sec": 1,
            "accelerated_progress_per_sec": 4,
            "accelerate_base_health_below": 4000,
            "accelerate_in_supply_zone": True,
            "logistics_modifier": "divide required progress by logistics_coefficient",
            "free_health_fraction": 0.10,
            "free_invulnerability_sec": 30,
            "free_min_invulnerability_sec": 10,
            "paid_cost_formula": "ceil((420 - remaining_sec) / 60) * 80 + robot_level * 20",
            "paid_health_fraction": 1.0,
            "paid_weak_and_invulnerable_sec": 3,
            "paid_power_multiplier": 2,
            "paid_power_cap_w": 200,
            "paid_power_duration_sec": 4,
        },
        "sentinel_command_intervention_coins": {"automatic": 50, "semiautomatic": 0},
    },
    "economy_catalogue": [
        {"key": "ammo17_local", "title": "增益点兑换17mm允许发弹量",
         "description": "须激活允许兑换的增益点；全队金币兑换上限1000发。",
         "category": "ammo", "quantity": 10, "cost": 10, "unit": "发",
         "roles": ["Infantry1", "Infantry2", "Sentinel"]},
        {"key": "ammo17_remote", "title": "远程兑换17mm允许发弹量",
         "description": "须脱战；6秒后生效；全队金币兑换上限1000发。",
         "category": "ammo", "quantity": 100, "cost": 150, "unit": "发",
         "roles": ["Infantry1", "Infantry2", "Sentinel"]},
        {"key": "ammo42_local", "title": "增益点兑换42mm允许发弹量",
         "description": "须激活允许兑换的增益点；重装发射仍受模块安装/解锁约束；全队上限100发。",
         "category": "ammo", "quantity": 1, "cost": 10, "unit": "发", "roles": ["Heavy"]},
        {"key": "ammo42_remote", "title": "远程兑换42mm允许发弹量",
         "description": "须脱战；6秒后生效；重装发射仍受模块安装/解锁约束；全队上限100发。",
         "category": "ammo", "quantity": 10, "cost": 150, "unit": "发", "roles": ["Heavy"]},
        {"key": "heal_remote", "title": "远程兑换血量",
         "description": "价格=50+ceil((420-剩余秒数)/60*20)。脱战确认6秒后恢复上限血量60%×后勤系数，不超过上限；期间战亡不退款。",
         "category": "recovery", "quantity": 1, "cost": None, "unit": "次",
         "roles": ["Heavy", "Infantry1", "Infantry2", "Sentinel"]},
        {"key": "revive_paid", "title": "兑换立即复活",
         "description": "价格=ceil((420-剩余秒数)/60)*80+机器人等级*20。满血复活；虚弱和无敌3秒；功率翻倍但不超200W，持续4秒。",
         "category": "revive", "quantity": 1, "cost": None, "unit": "台",
         "roles": ["Heavy", "Infantry1", "Infantry2", "Sentinel"]},
        {"key": "sentinel_intervention", "title": "指挥手干预自动哨兵",
         "description": "每次指挥手干预自动哨兵的指令费用50金币；半自动哨兵干预免费。不是弹药/回血/复活本体价格。",
         "category": "support", "quantity": 1, "cost": 50, "unit": "次", "roles": ["Sentinel"]},
    ],
    "features": {"hero_deploy": False, "rune": True, "base": True, "control_points": True},
    "heavy_stages": {
        "opening": {"max_health": 400, "power_limit_w": 50, "heat_limit": None, "cooling_rate": None},
        "assembly_1": {"max_health": 450, "power_limit_w": 50, "heat_limit": None, "cooling_rate": None},
        "assembly_2": {"max_health": 500, "power_limit_w": 50, "heat_limit": None, "cooling_rate": None},
        "assembly_3_or_shooter_installed": {"max_health": 600, "power_limit_w": 50,
                                            "heat_limit": 300, "cooling_rate": 100,
                                            "projectile_speed_limit_mps": 16.5},
    },
    "heavy_shooter_unlock": {
        "paths": ["complete_assembly_3", "elapsed_sec >= 300 - max_enemy_base_hp_lead / 50 - 2 * max_enemy_control_lead / 3"],
        "installation_location": "supply_zone_workbench",
        "installation_confirmation": "first referee-detected 42mm shot (no heat/speed/damage counted)",
        "opening_defense_fraction": 0.50,
        "opening_defense_until_sec": 180,
        "opening_defense_requires_shooter_not_installed": True,
    },
    "sentinel_control_modes": {
        "Automatic": {"max_health": 400, "power_limit_w": 100, "heat_limit": 260, "cooling_rate": 30, "projectile": "17mm"},
        "SemiAuto": {"max_health": 200, "power_limit_w": 60, "heat_limit": 100, "cooling_rate": 10, "projectile": "17mm"},
    },
    "logistics": {
        "coefficient_formula": "1 - base_health_lost / 20000",
        "respawn_progress": "original / coefficient",
        "supply_heal_rate": "original * coefficient",
        "remote_heal_fraction": "original * coefficient",
        "robot_interaction_bandwidth": "original * coefficient",
        "video_resolution_pixels": "1920 * 1080 * coefficient ** 2",
        "includes_custom_terminal_video": True,
    },
    "notes": [
        "Heavy是2027新角色重装机器人1号；不存在独立Hero/Engineer或2号，也不自动迁移2026配置。",
        "Aerial.operator表示指挥手可操作空中系统；空中机器人本身全自动，安全员仅受限急停；不是旧飞手/云台手驾驶。",
        "roles.Heavy.projectile=42mm表示可安装模块的能力；performance.Heavy.projectile=None表示开局无可用发射机构，热量横杠仍保留None而非0。",
        "Sentinel基础性能为自动哨兵，尚未叠加默认移动姿态等增益；半自动基础见sentinel_control_modes。",
        "V1.0.0正式§5.5仍有步兵1至10级、底盘/发射机构类型；没有可确认的通用性能点/技能加点系统；不映射旧Level表。",
        "步兵完整逐级基础表见infantry_levels：仅Power/Health与Burst/Cooling，没有Rate类型；performance_variants不复制旧Level对象。",
        "仅正式规则离线资料；经济卡不含command_type/param，不证明2027wire、MQTT或队内0x5A兼容。",
        "原英雄部署机制取消，但超热量断图传、飞镖/判罚遮挡及基地受损降清晰度仍需独立处理。",
        "空中冲击接触时间/面累积冲量及雷达干扰波具体参数在正式手册仍待定/后续发布。",
        "paid respawn弱状态条款存在冗余解除描述，按正式3秒条款记录；不将其解释为发射立即解锁。",
    ],
}

_CITATIONS = {
    "duration_sec": _cite(13, "1.1 关于比赛"),
    "field_size_m": _cite(30, "4.1 战场概述"),
    "victory_points": _cite(115, "5.8 赛制及获胜条件"),
    "score_title": _cite(115, "5.8 累计控制度优先"),
    "control": _cite(98, "5.6.2 表5-21 控制状态与控制度；前文PDF97；胜负优先级PDF115-116"),
    "roles": _cite(21, "表3-1 机器人阵容；表3-2见PDF22"),
    "performance.Heavy": _cite(92, "表5-16 重装机器人整机属性，续PDF93"),
    "performance.Infantry1.max_health": _cite(93, "表5-17 血量优先1级"),
    "performance.Infantry1.power_limit_w": _cite(93, "表5-17 血量优先1级"),
    "performance.Infantry1.heat_limit": _cite(95, "表5-18 冷却优先1级"),
    "performance.Infantry1.cooling_rate": _cite(95, "表5-18 冷却优先1级"),
    "performance.Sentinel": _cite(27, "3.1.3 表3-6 自动哨兵"),
    "initial_ammo.Heavy": _cite(23, "3.1.1 表3-3"),
    "initial_ammo.Infantry1": _cite(25, "3.1.2 表3-5"),
    "initial_ammo.Infantry2": _cite(25, "3.1.2 表3-5"),
    "initial_ammo.Sentinel": _cite(26, "3.1.3 表3-6"),
    "economy.initial_coins": _cite(76, "5.4.1 表5-6"),
    "economy.periodic_coin_grants": _cite(76, "表5-6，续PDF77"),
    "economy.remote_delay_sec": _cite(78, "5.4.2 远程兑换"),
    "economy.out_of_combat_sec": _cite(17, "表2-1 机器人主要状态"),
    "economy.remote_heal": _cite(74, "5.3.1；成本见PDF77表5-7；后勤见PDF95-96"),
    "economy.respawn": _cite(75, "5.3.2，续PDF76；成本见PDF77；后勤见PDF95-96"),
    "economy.sentinel_command_intervention_coins": _cite(110, "5.7.2 指挥手干预费用"),
    "features.hero_deploy": _cite(14, "1.2 取消英雄机器人特殊机制"),
    "features.rune": _cite(98, "5.6.3 能量机关机制"),
    "features.base": _cite(95, "5.6.1 基地及前哨站机制"),
    "features.control_points": _cite(97, "5.6.2 战场控制机制"),
    "heavy_stages.opening": _cite(92, "表5-16"),
    "heavy_stages.assembly_1": _cite(93, "表5-16"),
    "heavy_stages.assembly_2": _cite(93, "表5-16"),
    "heavy_stages.assembly_3_or_shooter_installed": _cite(93, "表5-16"),
    "heavy_shooter_unlock": _cite(109, "5.7.1 重装机器人特殊机制"),
    "sentinel_control_modes": _cite(27, "表3-6"),
    "logistics": _cite(95, "5.6.1 后勤系数；表5-19见PDF96"),
}
for _key in ("base_health", "base_max_health", "enemy_base_health", "enemy_base_max_health",
             "outpost_health", "outpost_max_health", "enemy_outpost_health", "enemy_outpost_max_health"):
    _CITATIONS[_key] = _cite(95, "5.6.1 基地及前哨站机制")
for _index in range(len(_MODE["roles"])):
    _CITATIONS[f"roles.{_index}.robot_id"] = _cite(21, "表3-1 机器人阵容")
    _CITATIONS[f"roles.{_index}.operator"] = _cite(22, "表3-2 操作手阵容")
for _field in ("max_health", "power_limit_w"):
    _CITATIONS[f"performance.Heavy.{_field}"] = _cite(92, "表5-16 开局默认")
for _field in ("max_health", "power_limit_w", "heat_limit", "cooling_rate"):
    _CITATIONS[f"performance.Infantry2.{_field}"] = _CITATIONS[f"performance.Infantry1.{_field}"].copy()
    _CITATIONS[f"performance.Sentinel.{_field}"] = _cite(27, "表3-6 自动哨兵")
for _key in ("ammo_17mm_local", "ammo_17mm_remote", "ammo_42mm_local", "ammo_42mm_remote"):
    _CITATIONS[f"economy.{_key}"] = _cite(77, "表5-7 兑换规则")
for _index in range(len(_MODE["economy_catalogue"])):
    _CITATIONS[f"economy_catalogue.{_index}"] = _cite(
        110 if _index == 6 else 77,
        "5.7.2 干预费用" if _index == 6 else "表5-7；最小兑换单位见PDF78表5-8/5-9")
for _family, _variants in _MODE["infantry_levels"].items():
    for _variant, _fields in _variants.items():
        for _field, _values in _fields.items():
            for _index in range(len(_values)):
                if _family == "chassis":
                    _page = 93 if _variant == "Power" or _index < 2 else 94
                    _section = "表5-17 步兵机器人底盘属性"
                else:
                    _page = 94 if _variant == "Burst" else 95
                    _section = "表5-18 步兵机器人17mm发射机构属性"
                _CITATIONS[f"infantry_levels.{_family}.{_variant}.{_field}.{_index}"] = _cite(_page, _section)

DATA = {
    "season": 2027,
    "competition": "RMUC",
    "rule_version": "1.0.0",
    "published": "2026-10-15",
    "sources": [{
        "title": "RoboMaster 2027 机甲大师超级对抗赛比赛规则手册V1.0.0（20261015）",
        "sha256": "9e2eed9295536c6fd547b62d634df1d5e70a2e1e2250e5dff3521d557e5d54be",
        "url": "https://bbs.robomaster.com/wiki/20204847/1969149?source=7",
        "kind": "official_rules",
    }],
    "modes": {"RMUC7v7": _MODE},
    "field_citations": {
        f"modes.RMUC7v7.{key}": value for key, value in _CITATIONS.items()
    },
}
