"""RMUL 2027 V1.0.0 facts, not a transport codec or a command catalogue.

PDF page numbers are one-based; this edition's printed pages are PDF page - 1.
Heavy is a distinct role, never an alias for the 2026 Hero.  Its opening profile
must not be replaced by its post-installation profile without observed state.
Only the supplied formal 2027 rulebook supplies the numeric facts below.
"""

DATA = {
    'season': 2027,
    'competition': 'RMUL',
    'rule_version': '1.0.0',
    'published': '2026-10-15',
    'sources': [{
        'title': 'RoboMaster 2027 机甲大师高校联盟赛比赛规则手册 V1.0.0（20261015）',
        'sha256': 'a8fd7b7f6ea5212b9e4dfa590b478827992598d91912ed671653c8bdd9727fd6',
        'url': None,
        'kind': 'official_rules',
    }],
    'modes': {
        'RMUL3v3': {
            'duration_sec': 300,
            'field_size_m': [12.0, 8.0],
            # Compatibility field name: the official 2027 quantity is 控制度.
            'victory_points': 600,
            'score_title': '控制度',
            'roles': [
                {'key': 'Heavy', 'title': '重装机器人', 'short_title': '重装',
                 'robot_id': 1, 'projectile': '42mm', 'operator': True},
                {'key': 'Infantry1', 'title': '步兵机器人', 'short_title': '步兵',
                 'robot_id': 3, 'projectile': '17mm', 'operator': True},
                {'key': 'Sentinel', 'title': '哨兵机器人', 'short_title': '哨兵',
                 'robot_id': 7, 'projectile': '17mm', 'operator': False},
            ],
            'performance': {
                'Heavy': {'max_health': 100, 'power_limit_w': 50,
                          'heat_limit': None, 'cooling_rate': None, 'projectile': 'None'},
                'Heavy:Armed': {'max_health': 450, 'power_limit_w': 50,
                                'heat_limit': 250, 'cooling_rate': 66, 'projectile': '42mm'},
                # The book explicitly defaults to Health + Cooling (table 3-4).
                'Infantry1': {'max_health': 350, 'power_limit_w': 75,
                              'heat_limit': 88, 'cooling_rate': 24, 'projectile': '17mm'},
                'Sentinel': {'max_health': 400, 'power_limit_w': 100,
                             'heat_limit': 260, 'cooling_rate': 30, 'projectile': '17mm'},
            },
            'performance_variants': {
                'Infantry1:Power:Burst': {'max_health': 300, 'power_limit_w': 90,
                                        'heat_limit': 230, 'cooling_rate': 14, 'projectile': '17mm'},
                'Infantry1:Power:Cooling': {'max_health': 300, 'power_limit_w': 90,
                                          'heat_limit': 88, 'cooling_rate': 24, 'projectile': '17mm'},
                'Infantry1:Health:Burst': {'max_health': 350, 'power_limit_w': 75,
                                         'heat_limit': 230, 'cooling_rate': 14, 'projectile': '17mm'},
                'Infantry1:Health:Cooling': {'max_health': 350, 'power_limit_w': 75,
                                           'heat_limit': 88, 'cooling_rate': 24, 'projectile': '17mm'},
            },
            'projectile_speed_limit_mps': {'Heavy': None, 'Heavy:Armed': 16.5,
                                         'Infantry1': 25, 'Sentinel': 25},
            'initial_ammo': {'Heavy': 0, 'Infantry1': 0, 'Sentinel': 750},
            'features': {'hero_deploy': False, 'rune': False, 'base': False,
                         'control_points': True},
            'economy': {
                'initial_gold': 200,
                # Official table lists remaining-clock instants, not elapsed time.
                'gold_schedule': [
                    {'remaining_sec': 299, 'gold': 200},
                    {'remaining_sec': 239, 'gold': 200},
                    {'remaining_sec': 179, 'gold': 200},
                    {'remaining_sec': 119, 'gold': 300},
                    {'remaining_sec': 59, 'gold': 300},
                ],
                'comeback_gap_thresholds': [200, 400],
                'comeback_gold_per_threshold': 200,
                'comeback_gold_cap_per_team': 400,
                'ammo_17mm_purchase_quantity': 10,
                'ammo_17mm_purchase_cost': 10,
                'ammo_42mm_purchase_quantity': 1,
                'ammo_42mm_purchase_cost': 10,
                'ammo_purchase_requires_own_supply_activation': True,
                'sentinel_can_increase_ammo': False,
                'gold_only_for_ammo': True,
                'supply_heal_max_health_fraction_per_sec': 0.25,
                'automatic_respawn': True,
                'respawn_first_progress': 5,
                'respawn_progress_increment_per_death': 5,
                'respawn_progress_per_sec': 1,
                'respawn_health_fraction': 0.20,
                'respawn_invulnerability_sec': 30,
                'respawn_weak_shooter_locked': True,
                'respawn_weak_cannot_activate_control': True,
                'own_supply_clears_weak_and_invulnerable': True,
                'comeback_recovery': [
                    {'control_gap_at_least': 200, 'respawn_progress_reduction_fraction': 0.33,
                     'supply_heal_max_health_fraction_per_sec': 0.33},
                    {'control_gap_at_least': 400, 'respawn_progress_reduction_fraction': 0.50,
                     'supply_heal_max_health_fraction_per_sec': 0.50},
                ],
            },
            'economy_catalogue': [
                {'key': 'ammo_17mm', 'title': '兑换17mm允许发弹量',
                 'description': '激活己方补给区后可兑换；10金币/10发，仅步兵，非实物装填指令。',
                 'category': 'ammo', 'quantity': 10, 'cost': 10, 'unit': '发',
                 'roles': ['Infantry1']},
                {'key': 'ammo_42mm', 'title': '兑换42mm允许发弹量',
                 'description': '激活己方补给区后可兑换；10金币/1发，仅重装，安装成功前不推断开火能力。',
                 'category': 'ammo', 'quantity': 1, 'cost': 10, 'unit': '发',
                 'roles': ['Heavy']},
            ],
            'control': {
                'zone_count': 3, 'initial_score': 600, 'initial_zone_state': 'neutral',
                'capture_progress_min': 0, 'capture_progress_max': 5,
                'capture_progress_per_sec': 1, 'enemy_score_loss_per_zone_per_sec': 1,
                'own_score_loss_per_death': 10,
                'contested_progress_pauses': True,
                'empty_non_neutral_progress_decays_per_sec': 1,
            },
            'buffs': {
                'activation_loss_delay_sec': 2,
                'highland_defense_fraction': 0.25,
                'tunnel_two_cards_window_sec': 3,
                'tunnel_cooling_multiplier': 1.5,
                'tunnel_cooling_duration_sec': 60,
                'tunnel_requires_no_other_card_between': True,
                'tunnel_own_side_only': True,
            },
            'heavy_mechanism': {
                'upgrade_requires_installed_module_and_detected_42mm_shot': True,
                'split_merge_install_remove_workbench_only': True,
                'unassembled_own_supply_invulnerable': True,
            },
            'stages': {'preparation_sec': 180, 'self_check_sec': 15,
                       'countdown_sec': 5, 'team_technical_pause_count': 2,
                       'team_technical_pause_sec': 120},
            'notes': [
                '编号来自本册表3-1，不是通信协议消息类型或全局蓝方编码。',
                'Heavy开局发射性能为表中横线，不用2026英雄参数补齐。',
                'Heavy:Armed是规则状态标签；安装且首发被裁判系统正确识别才提升，非技能或底盘选项。',
                '仅两个正式定价兑换卡；补给回血和自动复活是机制，不生成付费或远程操作卡。',
                'Gold schedule第一行299秒就是initial_gold，不应在开局重复入账。',
                '控制区双方有独立进度；先消除敌方进度再增加己方进度，非2026先到先得。',
                '复活33%读条缩减的整数舍入、重装提升时当前HP如何变化未获明确公式。',
            ],
        },
        'RMUL1v1': {
            'duration_sec': 120, 'field_size_m': [5.0, 5.0], 'victory_points': None,
            'roles': [
                {'key': 'Infantry1', 'title': '步兵机器人', 'short_title': '步兵',
                 'robot_id': 3, 'projectile': '17mm', 'operator': True},
            ],
            'performance': {
                'Infantry1': {'max_health': 200, 'power_limit_w': 120,
                              'heat_limit': 80, 'cooling_rate': 12, 'projectile': '17mm'},
            },
            'projectile_speed_limit_mps': {'Infantry1': 25},
            'initial_ammo': {'Infantry1': 200},
            'features': {'hero_deploy': False, 'rune': False, 'base': False,
                         'control_points': False},
            'economy': {
                'can_increase_ammo': False,
                'projectile_damage_heal_fraction': 0.50,
                'automatic_respawn': False,
            },
            'economy_catalogue': [],
            'stages': {'preparation_sec': 120, 'self_check_sec': 15,
                       'countdown_sec': 5, 'team_technical_pause_count': 2,
                       'team_technical_pause_sec': 120},
            'notes': [
                '表4-2仍写回血与复活不适用，但4.3.1明确新增弹丸伤害50%回血；保留专节规则。',
                '无金币兑换目录，不借用3v3金币、自动复活、性能选择或补给区机制。',
                '1v1满血平局时间比较与局均净胜血量特殊赛制见4.4及4.4.1，不臆造自动化判定。',
            ],
        },
    },
    'field_citations': {},
}


def _cite(path, page, section):
    """Expand a verified table/paragraph reference onto its scalar field paths."""
    value = DATA
    for part in path.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]

    def walk(item, field):
        if isinstance(item, dict):
            for key, child in item.items():
                walk(child, f'{field}.{key}')
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f'{field}.{index}')
        else:
            DATA['field_citations'][field] = {
                'source': 0, 'pdf_page': page, 'printed_page': page - 1,
                'section': section,
            }
    walk(value, path)


_cite('season', 11, '1.2 新赛季主要变更')
_cite('rule_version', 3, '修改日志，首次发布V1.0.0')
_cite('published', 3, '修改日志，2026.10.15')
_cite('modes.RMUL3v3.duration_sec', 17, '3 3V3对抗赛')
_cite('modes.RMUL3v3.field_size_m', 23, '3.2.1 战场概述；图3-5见PDF p25')
_cite('modes.RMUL3v3.victory_points', 38, '3.3.4.2 控制度机制')
_cite('modes.RMUL3v3.score_title', 38, '3.3.4.2 控制度机制')
_cite('modes.RMUL3v3.roles', 17, '3.1 表3-1 3V3对抗赛机器人及操作手阵容')
_cite('modes.RMUL3v3.roles.1.projectile', 19, '3.1.2 表3-4 步兵17mm发射机构')
_cite('modes.RMUL3v3.roles.2.projectile', 21, '3.1.3 表3-5 哨兵17mm发射机构')
_cite('modes.RMUL3v3.performance.Heavy', 18, '3.1.1 表3-2 开局行；横线为不适用')
_cite('modes.RMUL3v3.performance.Heavy:Armed', 18, '3.1.1 表3-2 安装后行；触发条件另见3.3.6/PDF p38')
_cite('modes.RMUL3v3.performance.Infantry1', 19, '3.1.2 表3-4 血量/冷却默认及底盘类型')
_cite('modes.RMUL3v3.performance.Sentinel', 21, '3.1.3 表3-5')
for _variant in DATA['modes']['RMUL3v3']['performance_variants']:
    _cite(f'modes.RMUL3v3.performance_variants.{_variant}', 19, '3.1.2 表3-4 底盘类型')
    for _field in ('heat_limit', 'cooling_rate'):
        _cite(f'modes.RMUL3v3.performance_variants.{_variant}.{_field}', 20, '3.1.2 表3-4 发射机构类型续表')
for _field in ('heat_limit', 'cooling_rate'):
    _cite(f'modes.RMUL3v3.performance.Infantry1.{_field}', 20, '3.1.2 表3-4 冷却优先续表')
for _profile, _page in [('Heavy', 18), ('Heavy:Armed', 18), ('Infantry1', 19), ('Sentinel', 21)]:
    _cite(f'modes.RMUL3v3.projectile_speed_limit_mps.{_profile}', _page, '3.1 对应机器人关键特征表')
for _profile, _page in [('Heavy', 18), ('Infantry1', 20), ('Sentinel', 22)]:
    _cite(f'modes.RMUL3v3.initial_ammo.{_profile}', _page, '3.1 对应机器人表，弹丸的装载和补给')
_cite('modes.RMUL3v3.features', 23, '3.1 表3-1；3.2.1 场地组成；全章无基地、能量机关或英雄部署机制')
for _field in ('initial_gold', 'gold_schedule', 'comeback_gap_thresholds',
               'comeback_gold_per_threshold', 'comeback_gold_cap_per_team', 'gold_only_for_ammo'):
    _cite(f'modes.RMUL3v3.economy.{_field}', 36, '3.3.3 经济体系；表3-11')
for _field in ('ammo_17mm_purchase_quantity', 'ammo_17mm_purchase_cost',
               'ammo_42mm_purchase_quantity', 'ammo_42mm_purchase_cost',
               'ammo_purchase_requires_own_supply_activation'):
    _cite(f'modes.RMUL3v3.economy.{_field}', 37, '3.3.3 表3-12兑换原则及下文兑换条件')
_cite('modes.RMUL3v3.economy.sentinel_can_increase_ammo', 22, '3.1.3 表3-5续表，局内不可增加允许发弹量')
for _field in ('supply_heal_max_health_fraction_per_sec', 'automatic_respawn',
               'respawn_first_progress', 'respawn_progress_increment_per_death',
               'respawn_progress_per_sec', 'respawn_health_fraction',
               'respawn_invulnerability_sec', 'respawn_weak_shooter_locked',
               'respawn_weak_cannot_activate_control', 'own_supply_clears_weak_and_invulnerable'):
    _cite(f'modes.RMUL3v3.economy.{_field}', 36, '3.3.2.1 回血机制；3.3.2.2 复活机制')
_cite('modes.RMUL3v3.economy.comeback_recovery', 38, '3.3.4.2 控制度差200/400时落后方恢复增益')
_cite('modes.RMUL3v3.economy_catalogue', 37, '3.3.3 表3-12兑换原则及下文兑换兵种/补给区条件')
_cite('modes.RMUL3v3.control', 37, '3.3.4.1 控制区机制')
for _field in ('initial_score', 'enemy_score_loss_per_zone_per_sec', 'own_score_loss_per_death'):
    _cite(f'modes.RMUL3v3.control.{_field}', 38, '3.3.4.2 控制度机制')
_cite('modes.RMUL3v3.buffs', 38, '3.3.5 场地增益机制及脚注')
_cite('modes.RMUL3v3.heavy_mechanism', 39, '3.3.6 重装机器人特殊机制续页')
_cite('modes.RMUL3v3.heavy_mechanism.upgrade_requires_installed_module_and_detected_42mm_shot', 38, '3.3.6 重装机器人特殊机制')
_cite('modes.RMUL1v1.duration_sec', 40, '4 步兵对抗赛')
_cite('modes.RMUL1v1.field_size_m', 42, '4.2 比赛场地')
_cite('modes.RMUL1v1.roles', 40, '4.1 表4-1；4.1.1 表4-2')
_cite('modes.RMUL1v1.performance', 40, '4.1.1 表4-2')
for _field in ('power_limit_w', 'cooling_rate'):
    _cite(f'modes.RMUL1v1.performance.Infantry1.{_field}', 41, '4.1.1 表4-2续表')
_cite('modes.RMUL1v1.projectile_speed_limit_mps', 40, '4.1.1 表4-2 射击初速度上限')
_cite('modes.RMUL1v1.initial_ammo', 41, '4.1.1 表4-2续表，弹丸的装载和补给')
_cite('modes.RMUL1v1.features', 42, '4.1 表4-1；4.2 场地组成；4.4获胜条件/PDF p45')
_cite('modes.RMUL1v1.economy.can_increase_ammo', 41, '4.1.1 表4-2续表，初始200发局内不可增加')
_cite('modes.RMUL1v1.economy.projectile_damage_heal_fraction', 45, '4.3.1 回血机制，优于表4-2旧式概括')
_cite('modes.RMUL1v1.economy.automatic_respawn', 45, '4.4 第1项，血量降为0立即结束；另见表4-2')
for _mode in ('RMUL3v3', 'RMUL1v1'):
    _cite(f'modes.{_mode}.stages.preparation_sec', 48, '5.3 准备阶段')
    for _field in ('self_check_sec', 'countdown_sec', 'team_technical_pause_count', 'team_technical_pause_sec'):
        _cite(f'modes.{_mode}.stages.{_field}', 50, '5.3.2 参赛队伍技术暂停；5.4 自检；5.5 五秒倒计时')

del _variant, _field, _profile, _page, _mode, _cite
