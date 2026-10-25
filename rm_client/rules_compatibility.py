"""Season policy is not a wire version, firmware schema, or motion authority.

Only reviewed annual referee contracts can supply official observations and
commands. RM2026 V2 remains 2026. Offline 2027 rule data is not wire support.
"""
from __future__ import annotations

from typing import Any


def normalize_rule_season(value: Any) -> int:
    """No coercion: an absent legacy field defaults at its owner, not here."""
    if type(value) is not int or value not in (2026, 2027):
        raise ValueError("rules season must be explicitly 2026 or 2027 (integer)")
    return value


def official_rule_compatibility(rule_season: Any, protocol_year: Any, *,
                                state: Any = None) -> tuple[bool, str]:
    try:
        season = normalize_rule_season(rule_season)
        state_season = normalize_rule_season(getattr(state, "rules_season", 2026))
    except ValueError as exc:
        return False, str(exc)
    if state is not None and state_season != season:
        return False, "rules season owner/state mismatch; official referee path locked"
    # Deliberately explicit. Adding a profile or a year label must not enable
    # an unreviewed annual adapter/contract implicitly.
    if season != 2026:
        return False, "2027 rules have no reviewed 2027 referee wire; official path locked"
    if type(protocol_year) is not int or protocol_year != season:
        return False, "rules season differs from referee protocol year; official path locked"
    return True, "reviewed 2026 referee protocol (not an authorization)"


def backend_rule_compatibility(backend: Any, state: Any = None) -> tuple[bool, str]:
    """Use reviewed metadata even for legacy lightweight backend owners."""
    from .referee_profiles import get_profile_definition
    profile = backend.referee
    try:
        year = get_profile_definition(profile.profile_id).year
    except ValueError as exc:
        return False, str(exc)
    if getattr(profile, "year", year) != year:
        return False, "referee profile year differs from reviewed metadata"
    season = getattr(backend, "rule_season", 2026)
    if season != getattr(backend.mqtt, "rule_season", 2026):
        return False, "rules season manager/transport mismatch"
    return official_rule_compatibility(season, year, state=state)


def retire_official_observations(state: Any) -> None:
    """Retire official data only; do not reset independent Polar/DT7/PRM1.

    Keep local rule/performance defaults when no official state was applied.
    Containers and presence/freshness witnesses never survive a season epoch.
    """
    if state is None:
        return
    had_official = bool(getattr(state, "official_state_active", False))
    # Presence must be revoked even if a malformed container fails cleanup.
    for name, value in (("official_state_active", False), ("official_state_at", 0.),
                        ("official_feed_at", 0.), ("official_events_online", False),
                        ("backend_frontend_synced", False)):
        if hasattr(state, name):
            setattr(state, name, value)
    for name in (
        "official_robot_health", "official_robot_bullets", "robot_positions",
        "robot_rows", "map_robots", "map_markers", "buff_rows", "buffs",
        "penalties", "active_penalty", "radar_detections", "path_plan",
        "tech_core", "performance_sync", "rune_status", "sentry_status",
        "dart_status", "sentry_ctrl_result", "special_mechanisms",
        "robot_statics", "robot_dynamics", "robot_modules", "robot_module_status",
        "injury_stats", "student_ui_data",
        "control_zones",
    ):
        container = getattr(state, name, None)
        if container is not None:
            container.clear()
    values = dict(
        official_state_active=False, official_state_at=0., official_feed_at=0.,
        official_events_online=False, backend_frontend_synced=False,
        current_stage="NOT_STARTED", radar_detections_at=0.,
        injury_stats_initialized=False, projectile_damage_small_initialized=False,
        projectile_damage_large_initialized=False, projectile_damage_small_total=0,
        projectile_damage_large_total=0, last_projectile_hit_at=0.,
        last_projectile_damage_delta=0, last_projectile_kind="", last_projectile_killer_id=0,
        total_damage_ally=None, total_damage_enemy=None, deploy_mode=0, deploy_status_at=0.,
        economy_command_status="", economy_managed=False, supply_zone_known=False,
        in_supply_zone=False, respawn_pending=False, respawn_can_free=False,
        respawn_can_pay=False, can_remote_heal=False, can_remote_ammo=False,
        small_buff=False, large_buff=False,
    )
    if had_official:
        for name in ("current_health", "max_health", "current_heat", "max_heat",
                     "current_chassis_energy", "max_chassis_energy", "current_buffer_energy",
                     "max_buffer_energy", "remaining_ammo", "ammo_capacity", "power_limit",
                     "heat_cooldown_rate", "remaining_economy", "total_economy_obtained",
                     "projectile_allowance_17mm", "projectile_allowance_42mm",
                     "base_health", "base_shield", "outpost_health", "enemy_base_health",
                     "enemy_base_shield", "enemy_outpost_health", "stage_countdown_sec",
                     "stage_elapsed_sec", "red_score", "blue_score"):
            values[name] = 0
    for name, value in values.items():
        if hasattr(state, name):
            setattr(state, name, value)
    for name in ("clear_air_support_observations", "clear_match_settlement"):
        clear = getattr(state, name, None)
        if clear is not None:
            clear()
    for name in ("deploy_status_revision", "economy_status_revision"):
        if hasattr(state, name):
            setattr(state, name, getattr(state, name) + 1)
    stats = getattr(state, "backend_stats", {})
    for key in ("respawn_status", "student_legacy_roster", "student_legacy_fields"):
        stats.pop(key, None)
