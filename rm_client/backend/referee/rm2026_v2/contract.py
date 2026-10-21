"""Reviewed RM2026 V2.0.0 wire contract, official sections 2.1 and 2.2.

Field tuples are (name, protobuf type, repeated). Topic tuples are
(direction, documented rate, section). Rates describe the source, not a new
transport limiter: map marks retain role-specific intervals from section 1.3.1;
AirSupportCommand has no numeric frequency in the table.

RadarInfoToClient wrapper is independently recovered from official 12.0.0.213
CustomClientProReflection descriptor (SHA256 db398c02c9c6636852ab02693df3c51a77b9b219f836e9b1b3deb88b34091b50).
"""

SOURCE_PDF = "RoboMaster 2026 机甲大师高校系列赛通信协议 V2.0.0（20260626）.pdf"
SOURCE_SHA256 = "8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b"
SOURCE_URL = "https://bbs.robomaster.com/wiki/20204847/811363"
PROTOCOL_VERSION = "2.0.0"
MAX_QOS = 1

TOPICS = {
    'KeyboardMouseControl': ('uplink', '75Hz', '2.2.1'),
    'CustomControl': ('uplink', '75Hz', '2.2.2'),
    'GameStatus': ('downlink', '5Hz', '2.2.3'),
    'GlobalUnitStatus': ('downlink', '1Hz', '2.2.4'),
    'GlobalLogisticsStatus': ('downlink', '1Hz', '2.2.5'),
    'GlobalSpecialMechanism': ('downlink', '1Hz', '2.2.6'),
    'Event': ('downlink', '触发式', '2.2.7'),
    'RobotInjuryStat': ('downlink', '1Hz', '2.2.8'),
    'RobotRespawnStatus': ('downlink', '1Hz', '2.2.9'),
    'RobotStaticStatus': ('downlink', '1Hz', '2.2.10'),
    'RobotDynamicStatus': ('downlink', '10Hz', '2.2.11'),
    'RobotModuleStatus': ('downlink', '1Hz', '2.2.12'),
    'RobotPosition': ('downlink', '1Hz', '2.2.13'),
    'Buff': ('downlink', '获得触发，持有期间1Hz', '2.2.14'),
    'PenaltyInfo': ('downlink', '触发式', '2.2.15'),
    'RobotPathPlanInfo': ('downlink', '触发式', '2.2.16'),
    'MapClickInfo': ('downlink', '触发式，继承§1.3.1限制', '2.2.17'),
    'MapClickCmd': ('uplink', '触发式，继承§1.3.1限制', '2.2.18'),
    'RadarInfoToClient': ('downlink', '触发式', '2.2.19'),
    'CustomByteBlock': ('downlink', '50Hz', '2.2.20'),
    'AssemblyCommand': ('uplink', '触发≤10Hz', '2.2.21'),
    'TechCoreMotionStateSync': ('downlink', '1Hz', '2.2.22'),
    'RobotPerformanceSelectionCommand': ('uplink', '触发≤10Hz', '2.2.23'),
    'RobotPerformanceSelectionSync': ('downlink', '1Hz', '2.2.24'),
    'CommonCommand': ('uplink', '触发≤10Hz', '2.2.25'),
    'HeroDeployModeEventCommand': ('uplink', '触发≤10Hz', '2.2.26'),
    'DeployModeStatusSync': ('downlink', '1Hz', '2.2.27'),
    'RuneActivateCommand': ('uplink', '触发≤10Hz', '2.2.28'),
    'RuneStatusSync': ('downlink', '1Hz', '2.2.29'),
    'SentryStatusSync': ('downlink', '1Hz', '2.2.30'),
    'DartCommand': ('uplink', '触发≤10Hz', '2.2.31'),
    'DartSelectTargetStatusSync': ('downlink', '1Hz', '2.2.32'),
    'SentryCtrlCommand': ('uplink', '触发≤10Hz', '2.2.33'),
    'SentryCtrlResult': ('downlink', '触发式', '2.2.34'),
    'AirSupportCommand': ('uplink', '触发式', '2.2.35'),
    'AirSupportStatusSync': ('downlink', '1Hz', '2.2.36'),
}

FIELDS = {
    'KeyboardMouseControl': {
        1: ('mouse_x', 'int32', False),
        2: ('mouse_y', 'int32', False),
        3: ('mouse_z', 'int32', False),
        4: ('left_button_down', 'bool', False),
        5: ('right_button_down', 'bool', False),
        6: ('keyboard_value', 'uint32', False),
        7: ('mid_button_down', 'bool', False),
    },
    'CustomControl': {
        1: ('data', 'bytes', False),
    },
    'GameStatus': {
        1: ('current_round', 'uint32', False),
        2: ('total_rounds', 'uint32', False),
        3: ('red_score', 'uint32', False),
        4: ('blue_score', 'uint32', False),
        5: ('current_stage', 'uint32', False),
        6: ('stage_countdown_sec', 'int32', False),
        7: ('stage_elapsed_sec', 'int32', False),
        8: ('is_paused', 'bool', False),
        9: ('game_result', 'uint32', False),
        10: ('end_reason', 'uint32', False),
    },
    'GlobalUnitStatus': {
        1: ('base_health', 'uint32', False),
        2: ('base_status', 'uint32', False),
        3: ('base_shield', 'uint32', False),
        4: ('outpost_health', 'uint32', False),
        5: ('outpost_status', 'uint32', False),
        6: ('enemy_base_health', 'uint32', False),
        7: ('enemy_base_status', 'uint32', False),
        8: ('enemy_base_shield', 'uint32', False),
        9: ('enemy_outpost_health', 'uint32', False),
        10: ('enemy_outpost_status', 'uint32', False),
        11: ('robot_health', 'uint32', True),
        12: ('robot_bullets', 'int32', True),
        13: ('total_damage_ally', 'uint32', False),
        14: ('total_damage_enemy', 'uint32', False),
    },
    'GlobalLogisticsStatus': {
        1: ('remaining_economy', 'uint32', False),
        2: ('total_economy_obtained', 'uint64', False),
        3: ('tech_level', 'uint32', False),
        4: ('encryption_level', 'uint32', False),
    },
    'GlobalSpecialMechanism': {
        1: ('mechanism_id', 'uint32', True),
        2: ('mechanism_time_sec', 'int32', True),
    },
    'Event': {
        1: ('event_id', 'int32', False),
        2: ('param', 'string', False),
    },
    'RobotInjuryStat': {
        1: ('total_damage', 'uint32', False),
        2: ('collision_damage', 'uint32', False),
        3: ('small_projectile_damage', 'uint32', False),
        4: ('large_projectile_damage', 'uint32', False),
        5: ('dart_splash_damage', 'uint32', False),
        6: ('module_offline_damage', 'uint32', False),
        7: ('offline_damage', 'uint32', False),
        8: ('penalty_damage', 'uint32', False),
        9: ('server_kill_damage', 'uint32', False),
        10: ('killer_id', 'uint32', False),
    },
    'RobotRespawnStatus': {
        1: ('is_pending_respawn', 'bool', False),
        2: ('total_respawn_progress', 'uint32', False),
        3: ('current_respawn_progress', 'uint32', False),
        4: ('can_free_respawn', 'bool', False),
        5: ('gold_cost_for_respawn', 'uint32', False),
        6: ('can_pay_for_respawn', 'bool', False),
    },
    'RobotStaticStatus': {
        1: ('connection_state', 'uint32', False),
        2: ('field_state', 'uint32', False),
        3: ('alive_state', 'uint32', False),
        4: ('robot_id', 'uint32', False),
        5: ('robot_type', 'uint32', False),
        6: ('performance_system_shooter', 'uint32', False),
        7: ('performance_system_chassis', 'uint32', False),
        8: ('level', 'uint32', False),
        9: ('max_health', 'uint32', False),
        10: ('max_heat', 'uint32', False),
        11: ('heat_cooldown_rate', 'float', False),
        12: ('max_power', 'uint32', False),
        13: ('max_buffer_energy', 'uint32', False),
        14: ('max_chassis_energy', 'uint32', False),
    },
    'RobotDynamicStatus': {
        1: ('current_health', 'uint32', False),
        2: ('current_heat', 'float', False),
        3: ('last_projectile_fire_rate', 'float', False),
        4: ('current_chassis_energy', 'uint32', False),
        5: ('current_buffer_energy', 'uint32', False),
        6: ('current_experience', 'uint32', False),
        7: ('experience_for_upgrade', 'uint32', False),
        8: ('total_projectiles_fired', 'uint32', False),
        9: ('remaining_ammo', 'uint32', False),
        10: ('is_out_of_combat', 'bool', False),
        11: ('out_of_combat_countdown', 'uint32', False),
        12: ('can_remote_heal', 'bool', False),
        13: ('can_remote_ammo', 'bool', False),
    },
    'RobotModuleStatus': {
        1: ('power_manager', 'uint32', False),
        2: ('rfid', 'uint32', False),
        3: ('light_strip', 'uint32', False),
        4: ('small_shooter', 'uint32', False),
        5: ('big_shooter', 'uint32', False),
        6: ('uwb', 'uint32', False),
        7: ('armor', 'uint32', False),
        8: ('video_transmission', 'uint32', False),
        9: ('capacitor', 'uint32', False),
        10: ('main_controller', 'uint32', False),
        11: ('laser_detection_module', 'uint32', False),
    },
    'RobotPosition': {
        1: ('x', 'float', False),
        2: ('y', 'float', False),
        3: ('z', 'float', False),
        4: ('yaw', 'float', False),
        5: ('robot_id', 'uint32', False),
    },
    'Buff': {
        1: ('robot_id', 'uint32', False),
        2: ('buff_type', 'uint32', False),
        3: ('buff_level', 'int32', False),
        4: ('buff_max_time', 'uint32', False),
        5: ('buff_left_time', 'uint32', False),
    },
    'PenaltyInfo': {
        1: ('penalty_type', 'uint32', False),
        2: ('penalty_effect_sec', 'uint32', False),
        3: ('total_penalty_num', 'uint32', False),
    },
    'RobotPathPlanInfo': {
        1: ('intention', 'uint32', False),
        2: ('start_pos_x', 'uint32', False),
        3: ('start_pos_y', 'uint32', False),
        4: ('offset_x', 'int32', True),
        5: ('offset_y', 'int32', True),
        6: ('sender_id', 'uint32', False),
    },
    'MapClickInfo': {
        1: ('is_send_all', 'uint32', False),
        2: ('robot_id', 'bytes', False),
        3: ('mode', 'uint32', False),
        4: ('enemy_id', 'uint32', False),
        5: ('ascii', 'uint32', False),
        6: ('type', 'uint32', False),
        7: ('map_x', 'float', False),
        8: ('map_y', 'float', False),
    },
    'MapClickCmd': {
        1: ('is_send_all', 'uint32', False),
        2: ('robot_id', 'bytes', False),
        3: ('mode', 'uint32', False),
        4: ('enemy_id', 'uint32', False),
        5: ('ascii', 'uint32', False),
        6: ('type', 'uint32', False),
        7: ('map_x', 'float', False),
        8: ('map_y', 'float', False),
    },
    'CustomByteBlock': {
        1: ('data', 'bytes', False),
    },
    'AssemblyCommand': {
        1: ('operation', 'uint32', False),
        2: ('difficulty', 'uint32', False),
    },
    'TechCoreMotionStateSync': {
        1: ('maximum_difficulty_level', 'uint32', False),
        2: ('basic_state', 'uint32', False),
        3: ('putin_state', 'uint32', False),
        4: ('move_state', 'uint32', False),
        5: ('rotate_state', 'uint32', False),
        6: ('enemy_core_status', 'uint32', False),
        7: ('remain_time_all', 'uint32', False),
        8: ('remain_time_step', 'uint32', False),
    },
    'RobotPerformanceSelectionCommand': {
        1: ('shooter', 'uint32', False),
        2: ('chassis', 'uint32', False),
        3: ('sentry_control', 'uint32', False),
    },
    'RobotPerformanceSelectionSync': {
        1: ('shooter', 'uint32', False),
        2: ('chassis', 'uint32', False),
        3: ('sentry_control', 'uint32', False),
    },
    'CommonCommand': {
        1: ('cmd_type', 'uint32', False),
        2: ('param', 'uint32', False),
    },
    'HeroDeployModeEventCommand': {
        1: ('mode', 'uint32', False),
    },
    'DeployModeStatusSync': {
        1: ('status', 'uint32', False),
    },
    'RuneActivateCommand': {
        1: ('activate', 'uint32', False),
    },
    'RuneStatusSync': {
        1: ('rune_status', 'uint32', False),
        2: ('activated_arms', 'uint32', False),
        3: ('average_rings', 'float', False),
    },
    'SentryStatusSync': {
        1: ('posture_id', 'uint32', False),
        2: ('is_weakened', 'bool', False),
        3: ('is_powered', 'bool', False),
    },
    'DartCommand': {
        1: ('target_id', 'uint32', False),
        2: ('open', 'bool', False),
        3: ('launch_confirm', 'bool', False),
    },
    'DartSelectTargetStatusSync': {
        1: ('target_id', 'uint32', False),
        2: ('open', 'uint32', False),
    },
    'SentryCtrlCommand': {
        1: ('command_id', 'uint32', False),
    },
    'SentryCtrlResult': {
        1: ('command_id', 'uint32', False),
        2: ('result_code', 'uint32', False),
    },
    'AirSupportCommand': {
        1: ('command_id', 'uint32', False),
    },
    'AirSupportStatusSync': {
        1: ('airsupport_status', 'uint32', False),
        2: ('left_time', 'uint32', False),
        3: ('cost_coins', 'uint32', False),
        4: ('is_being_targeted', 'uint32', False),
        5: ('shooter_status', 'uint32', False),
    },
}

# Official descriptor calls the repeated wrapper field robot_info. Preserve
# the existing year-neutral consumer alias without changing its wire number.
FIELDS["RadarInfoToClient"] = {1: ("robot_info", "RadarSingleRobotInfo", True)}
FIELDS["RadarSingleRobotInfo"] = {
    1: ("target_pos_x", "uint32", False),
    2: ("target_pos_y", "uint32", False),
    3: ("is_high_light", "uint32", False),
}
ALIASES = {("RadarInfoToClient", "robot_info"): "robots"}
UNAVAILABLE_MESSAGES = frozenset()

# Section 2.2.33: 0 is invalid; 2 is not listed in V2. These are values of
# protobuf field 1, not additional field numbers.
SENTRY_COMMAND_IDS = frozenset({1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12})
AIR_SUPPORT_COMMAND_IDS = frozenset({0, 1, 2, 3})
