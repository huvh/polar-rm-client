"""Old official V1.1.0 field facts, for read-only Student preview only.

Type names were checked against local 12.0.0.30 metadata. Wire interoperability
still requires a Student broker capture. Old unspecified roster order is never
guessed. This contract is not authority to send legacy RemoteControl.
"""
SOURCE_URL = "https://bbs-web-static.robomaster.com/502f6389eb64439c942327f56c8289cc1766051819355/RoboMaster%202026%20%E6%9C%BA%E7%94%B2%E5%A4%A7%E5%B8%88%E9%AB%98%E6%A0%A1%E7%B3%BB%E5%88%97%E8%B5%9B%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.1.0%EF%BC%8820251217%EF%BC%89.pdf"
SOURCE_SHA256 = 'c08c66042b3c9129e3a176d343df54cf72538bb11902dde762a504890969d12f'

FIELDS = {
    'RemoteControl': {
        1: ('mouse_x', 'int32', False),
        2: ('mouse_y', 'int32', False),
        3: ('mouse_z', 'int32', False),
        4: ('left_button_down', 'bool', False),
        5: ('right_button_down', 'bool', False),
        6: ('keyboard_value', 'uint32', False),
        7: ('mid_button_down', 'bool', False),
        8: ('data', 'bytes', False),
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
    },
    'GlobalUnitStatus': {
        1: ('base_health', 'uint32', False),
        2: ('base_status', 'uint32', False),
        3: ('base_shield', 'uint32', False),
        4: ('outpost_health', 'uint32', False),
        5: ('outpost_status', 'uint32', False),
        6: ('robot_health', 'uint32', True),
        7: ('robot_bullets', 'int32', True),
        8: ('total_damage_red', 'uint32', False),
        9: ('total_damage_blue', 'uint32', False),
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
        7: ('wifi_offline_damage', 'uint32', False),
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
    },
    'RobotPosition': {
        1: ('x', 'float', False),
        2: ('y', 'float', False),
        3: ('z', 'float', False),
        4: ('yaw', 'float', False),
    },
    'Buff': {
        1: ('robot_id', 'uint32', False),
        2: ('buff_type', 'uint32', False),
        3: ('buff_level', 'int32', False),
        4: ('buff_max_time', 'uint32', False),
        5: ('buff_left_time', 'uint32', False),
        6: ('msg_params', 'string', False),
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
    'MapClickInfoNotify': {
        1: ('is_send_all', 'uint32', False),
        2: ('robot_id', 'bytes', False),
        3: ('mode', 'uint32', False),
        4: ('enemy_id', 'uint32', False),
        5: ('ascii', 'uint32', False),
        6: ('type', 'uint32', False),
        7: ('screen_x', 'uint32', False),
        8: ('screen_y', 'uint32', False),
        9: ('map_x', 'float', False),
        10: ('map_y', 'float', False),
    },
    'RaderInfoToClient': {
        1: ('robots', 'RadarSingleRobotInfo', True),
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
        2: ('status', 'uint32', False),
    },
    'RobotPerformanceSelectionCommand': {
        1: ('shooter', 'uint32', False),
        2: ('chassis', 'uint32', False),
    },
    'RobotPerformanceSelectionSync': {
        1: ('shooter', 'uint32', False),
        2: ('chassis', 'uint32', False),
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
        3: ('average_rings', 'uint32', False),
    },
    'SentinelStatusSync': {
        1: ('posture_id', 'uint32', False),
        2: ('is_weakened', 'bool', False),
    },
    'DartCommand': {
        1: ('target_id', 'uint32', False),
        2: ('open', 'bool', False),
    },
    'DartSelectTargetStatusSync': {
        1: ('target_id', 'uint32', False),
        2: ('open', 'bool', False),
    },
    'GuardCtrlCommand': {
        1: ('command_id', 'uint32', False),
    },
    'GuardCtrlResult': {
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
    },
    'RadarSingleRobotInfo': {
        1: ('target_pos_x', 'uint32', False),
        2: ('target_pos_y', 'uint32', False),
        3: ('is_high_light', 'uint32', False),
    },
}
