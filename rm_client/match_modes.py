from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .rules import competition_rules, match_modes_for_season, validate_season


MATCH_MODE_KEYS = ["RMUC7v7", "RMUL3v3"]


@dataclass
class MapHotZone:
    name: str
    x: float
    y: float
    w: float
    h: float
    kind: str


@dataclass
class FieldLayout:
    key: str
    title: str
    asset_path: str
    width_m: float
    height_m: float
    mirror_for_blue: bool = True
    zones: list[MapHotZone] = field(default_factory=list)
    positions_calibrated: bool = True


@dataclass
class MatchModeConfig:
    key: str
    title: str
    subtitle: str
    duration_sec: int
    field: FieldLayout
    default_right_display: str
    default_map_size: str
    default_module_list_style: str
    enabled_modules: set[str]
    disabled_modules: set[str] = field(default_factory=set)
    season: int = 2026
    rule_version: str = 'legacy-client-baseline'


MATCH_MODES: dict[str, MatchModeConfig] = {
    "RMUC7v7": MatchModeConfig(
        key="RMUC7v7",
        title="RMUC 7v7",
        subtitle="官方 28m x 15m 战场",
        duration_sec=420,
        field=FieldLayout(
            key="RMUC7v7",
            title="RMUC 7v7 Official Map",
            asset_path="assets/maps/rmuc_7v7_official.png",
            width_m=28.0,
            height_m=15.0,
            zones=[
                MapHotZone("Red Base", 1.1, 1.2, 2.1, 2.8, "base"),
                MapHotZone("Blue Base", 24.8, 11.0, 2.1, 2.8, "base"),
                MapHotZone("Red Outpost", 4.9, 6.2, 1.7, 2.0, "outpost"),
                MapHotZone("Blue Outpost", 21.4, 6.8, 1.7, 2.0, "outpost"),
                MapHotZone("Power Rune", 13.3, 6.1, 1.4, 1.8, "rune"),
                MapHotZone("Red Resupply", 0.9, 11.6, 2.7, 2.2, "supply"),
                MapHotZone("Blue Resupply", 24.4, 1.2, 2.7, 2.2, "supply"),
            ],
        ),
        default_right_display="ModuleListHud",
        default_map_size="Compact",
        default_module_list_style="PolarTextList",
        enabled_modules={
            "ArmorAutoAim",
            "EnergyAutoAim",
            "SpinMode",
            "CameraFeed",
            "RobotOverlay",
            "RadarOverlay",
            "MapMarker",
            "HUD",
            "TacticalMap",
            "MatchTimer",
            "BaseOutpostStatus",
            "EconomyPanel",
            "ProjectileShop",
            "ThermalPowerPanel",
            "BuffTimeline",
            "ProjectileAllowance",
            "GimbalPower",
            "ChassisGimbalIndicator",
            "PowerLimit",
            "SpeedLimit",
            "Capacitor",
            "FrictionWheel",
            "LockState",
        },
        disabled_modules={"VictoryPointStatus"},
    ),
    "RMUL3v3": MatchModeConfig(
        key="RMUL3v3",
        title="RMUL 3v3",
        subtitle="官方 12m x 8m 战场",
        duration_sec=300,
        field=FieldLayout(
            key="RMUL3v3",
            title="RMUL 3v3 Official Map",
            asset_path="assets/maps/rmul_3v3_official.png",
            width_m=12.0,
            height_m=8.0,
            zones=[
                MapHotZone("Red Supply", 0.0, 0.0, 1.5, 1.7, "supply"),
                MapHotZone("Blue Supply", 10.5, 6.3, 1.5, 1.7, "supply"),
                MapHotZone("Control", 5.0, 3.1, 2.2, 1.8, "control"),
                MapHotZone("Red High", 2.5, 0.8, 2.0, 3.1, "highland"),
                MapHotZone("Blue High", 7.2, 4.1, 2.0, 3.1, "highland"),
            ],
        ),
        default_right_display="ModuleListHud",
        default_map_size="Compact",
        default_module_list_style="PolarTextList",
        enabled_modules={
            "ArmorAutoAim",
            "SpinMode",
            "CameraFeed",
            "RobotOverlay",
            "RadarOverlay",
            "MapMarker",
            "HUD",
            "TacticalMap",
            "MatchTimer",
            "VictoryPointStatus",
            "EconomyPanel",
            "ProjectileShop",
            "ThermalPowerPanel",
            "BuffTimeline",
            "ProjectileAllowance",
            "GimbalPower",
            "ChassisGimbalIndicator",
            "PowerLimit",
            "SpeedLimit",
            "Capacitor",
            "FrictionWheel",
            "LockState",
        },
        disabled_modules={"EnergyAutoAim", "BaseOutpostStatus", "AirSupport"},
    ),
}


def match_mode_config(key: str, season=2026) -> MatchModeConfig:
    year=validate_season(season)
    if year==2026:
        if key=='RMUL1v1':
            raise ValueError('RMUL1v1 is available only in the reviewed 2027 rule pack')
        return MATCH_MODES.get(key,MATCH_MODES['RMUC7v7'])
    rules=competition_rules(year,key)
    if rules.duration_sec is None or rules.field_size_m is None:
        raise ValueError(f'{rules.title}: duration/field geometry not reviewed')
    base=MATCH_MODES['RMUL3v3' if key.startswith('RMUL') else 'RMUC7v7']
    width,height=rules.field_size_m
    # An old map's calibration/zones cannot be relabelled as the new field.
    illustrations={'RMUL3v3':'assets/maps/rmul_2027_3v3_rules.png',
                   'RMUL1v1':'assets/maps/rmul_2027_1v1_rules.png',
                   'RMUC7v7':'assets/maps/rmuc_2027_7v7_rules.png'}
    field=FieldLayout(key,rules.title+' · 规则图示（未标定）',
        rules.facts.get('field_asset') or illustrations.get(key,''),
        width,height,mirror_for_blue=False,zones=[],positions_calibrated=False)
    enabled=set(base.enabled_modules);disabled=set(base.disabled_modules)
    for feature,module in (('hero_deploy','HeroLob'),('rune','EnergyAutoAim'),
                           ('base','BaseOutpostStatus'),('control_points','VictoryPointStatus')):
        if rules.features.get(feature) is False:disabled.add(module)
        elif rules.features.get(feature) is True:
            disabled.discard(module)
            enabled.add(module)
    enabled-=disabled
    if key=='RMUL1v1':
        disabled.update({'VictoryPointStatus','BaseOutpostStatus','EnergyAutoAim','AirSupport','HeroLob',
                         'EconomyPanel','ProjectileShop','ReloadingPanel'})
        enabled-=disabled
    return replace(base,key=key,title=rules.title,
        subtitle=f'{width:g}m × {height:g}m · 2027 V{rules.version} · 协议须单独核对',
        duration_sec=rules.duration_sec,field=field,enabled_modules=enabled,
        disabled_modules=disabled,season=year,rule_version=rules.version)


class MatchModeManager:
    def __init__(self, default: str = "RMUC7v7", *, season=2026) -> None:
        self.season=validate_season(season)
        self.current=match_mode_config(default,self.season)

    @property
    def mode_keys(self):
        return match_modes_for_season(self.season)

    def config_for(self,key):
        return match_mode_config(key,self.season)

    def set_mode(self, key: str, *, season=None) -> MatchModeConfig:
        year=self.season if season is None else validate_season(season)
        current=match_mode_config(key,year)
        self.season,self.current=year,current
        return self.current

    def apply_to_registry(self, registry: Any) -> None:
        config = self.current
        self._set_setting(registry, "MatchMode", "Season", str(self.season))
        self._set_setting(registry, "MatchMode", "Mode", config.key)
        module=registry.get('MatchMode')
        setting=module.get_setting('Mode') if module else None
        if setting is not None:setting.options=list(self.mode_keys)
        self._set_setting(registry, "TacticalMap", "Map Size", config.default_map_size)
        self._set_setting(registry, "TacticalMap", "Official Map", config.field.title)
        self._set_setting(registry, "HUD", "Right Display", config.default_right_display)
        self._set_setting(registry, "HUD", "ModuleList Style", config.default_module_list_style)
        for module in registry.modules:
            if module.name in config.enabled_modules:
                module.set_enabled(True)
            if module.name in config.disabled_modules:
                module.set_enabled(False)

    def _set_setting(self, registry: Any, module_name: str, setting_name: str, value: object) -> None:
        module = registry.get(module_name)
        setting = module.get_setting(setting_name) if module else None
        if setting is not None:
            setting.value = value
