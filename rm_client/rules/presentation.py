"""Annual preference visibility; it does not mutate saved legacy selections."""
from . import competition_rules,validate_season


def visible_rule_settings(registry,module):
    match=registry.get('MatchMode')
    setting=match.get_setting('Season') if match else None
    season=validate_season(setting.value if setting else 2026)
    if season!=2027 or module.name!='RobotProfile':
        return module.settings
    mode=match.get_setting('Mode')
    role=module.get_setting('Role')
    role=str(role.value) if role else ''
    allowed={'Role'}
    # The reviewed RMUL table still has these exact independent branches.
    # Its Heavy installation state is NOT a selectable Hero Type.
    if mode and mode.value=='RMUL3v3' and role.startswith('Infantry'):
        allowed.update({'Infantry Chassis','Infantry Shooter'})
    if mode and mode.value=='RMUC7v7':
        rules=competition_rules(2027,mode.value)
        if role.startswith('Infantry') and rules.facts.get('infantry_levels'):
            allowed.update({'Level','Infantry Chassis','Infantry Shooter'})
        if role=='Sentinel' and rules.facts.get('sentinel_control_modes'):
            allowed.add('Sentinel Control')
    return [item for item in module.settings if item.name in allowed]


def control_zone_display(state):
    if getattr(state,'rules_season',2026)==2027:
        rules=competition_rules(2027,state.match_mode)
        count=rules.facts.get('control',{}).get('zone_count')
        return f'{count}区待同步' if count is not None else '待2027裁判同步'
    return f'{int(state.control_progress)}%'
