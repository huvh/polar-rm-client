"""Production presentation/persistence methods with inert owners, no device I/O."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_client.match_modes import MatchModeManager, match_mode_config
from rm_client.model import RobotState, build_default_registry
from rm_client.top_match_bar import TopMatchBarFeed
from rm_client.ui.match_strip_locale import match_role_text
from rm_client.ui.polar.mixins.persistence_mixin import PersistenceMixin
from rm_client.ui.top_match_bar_controller import TopMatchBarController
from rm_client.rules.presentation import visible_rule_settings, control_zone_display


class Host(PersistenceMixin):
    def __init__(self):
        self.registry = build_default_registry()
        self.state = RobotState()
        self.match_mode_manager = MatchModeManager()
        self.backend = NS(mqtt=NS(client_id='3', mock_output=True, _started=False, connected=False),
                          polar=None, serial=None, lock_control=Mock(),
                          set_rule_season=Mock(), set_client_id=Mock(), trigger_estop=Mock())
        self.control = NS(release_all=Mock(), clear_pending=Mock())
        self.reject_pending_configuration_edit = lambda: False
        self.toast = Mock()
        self.close_hero_deploy_interface = Mock()
        self.hero_deploy_ui = NS(active=False)
        self.config_loading = False

    def setting_mode(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return str(setting.value) if setting else default

    def alliance_side(self):
        return 'Red'

    def select(self, year, mode):
        self.registry.get('MatchMode').get_setting('Season').value = str(year)
        self.apply_match_mode(mode, False, False)


class AnnualFrontendTests(unittest.TestCase):
    def test_runtime_switch_uses_new_roles_defaults_and_restores_old_draft(self):
        host = Host()
        module = host.registry.get('RobotProfile')
        module.get_setting('Role').value = 'Infantry1'
        module.get_setting('Level').value = 8
        module.get_setting('Infantry Chassis').value = 'Power'
        module.get_setting('Infantry Shooter').value = 'Burst'
        host.select(2027, 'RMUL3v3')
        self.assertEqual(module.get_setting('Role').options, ['Heavy', 'Infantry1', 'Sentinel'])
        self.assertEqual(module.get_setting('Infantry Chassis').value, 'Health')
        self.assertEqual(module.get_setting('Infantry Shooter').value, 'Cooling')
        self.assertEqual(host.state.rules_season, 2027)
        self.assertEqual(host.state.control_score_max, 600)
        self.assertEqual(len(host.state.control_zones), 3)
        self.assertTrue(all(not zone['observed'] and zone['owner'] is None for zone in host.state.control_zones))
        self.assertEqual(control_zone_display(host.state), '3区待同步')
        host.select(2026, 'RMUL3v3')
        self.assertEqual(module.get_setting('Role').value, 'Infantry1')
        self.assertEqual(module.get_setting('Level').value, 8)
        self.assertEqual(module.get_setting('Infantry Shooter').value, 'Burst')
        self.assertEqual(host.state.control_score_max, 200)
        self.assertFalse(host.state.control_zones)
        host.backend.set_rule_season.assert_any_call(2027)
        host.backend.set_rule_season.assert_any_call(2026)
        host.backend.trigger_estop.assert_not_called()  # No running transport.
        host.backend.lock_control.assert_called()
        host.control.clear_pending.assert_called()

    def test_return_to_26_does_not_retain_27_base_maxima(self):
        host = Host()
        host.select(2027, 'RMUC7v7')
        self.assertEqual((host.state.base_max_health, host.state.outpost_max_health), (10000, 1000))
        self.assertEqual(len(host.state.control_zones), 4)
        host.select(2026, 'RMUC7v7')
        self.assertEqual((host.state.base_max_health, host.state.outpost_max_health), (5000, 1500))
        self.assertFalse(host.state.control_zones)

    def test_27_top_strip_cannot_present_old_base_race_progress(self):
        controller = TopMatchBarController.__new__(TopMatchBarController)
        controller.owner = NS(state=NS(rules_season=2027, match_mode='RMUC7v7'))
        controller._setting = lambda *args: True
        # Must return before touching a progress renderer, painter, or base HP.
        controller._paint_progress(None, None, 1280, 0, 0, 0, 0, 0)

    def test_switch_with_live_owner_latches_estop_even_if_same_robot_id(self):
        host = Host()
        host.backend.mqtt._started = True
        host.backend.mqtt.client_id = '1'
        host.state.robot_id = 1
        host.registry.get('RobotProfile').get_setting('Role').value = 'Hero'
        host.select(2027, 'RMUL3v3')
        host.backend.trigger_estop.assert_called_once()
        self.assertEqual(host.state.robot_profile, 'Heavy')

    def test_seed_has_no_legacy_target_shield_demo_or_match_authority(self):
        for mode in ('RMUC7v7', 'RMUL3v3', 'RMUL1v1'):
            with self.subTest(mode=mode):
                host = Host()
                host.seed_match_state(match_mode_config(mode, 2027))
                self.assertEqual(host.state.current_stage, 'NOT_STARTED')
                self.assertFalse(host.state.target_locked or host.state.lock_state or host.state.energy_target_locked)
                self.assertEqual((host.state.target_id, host.state.target_health, host.state.target_max_health), (0, 0, 0))
                self.assertEqual(host.state.base_status, 'UNKNOWN')
                self.assertFalse(host.state.robot_rows or host.state.buff_rows or host.state.map_markers)
                self.assertEqual(host.state.base_shield, 0)
                host.state.tick(.016)
                self.assertFalse(host.state.robot_rows or host.state.buff_rows or host.state.map_markers)

    def test_one_on_one_does_not_expose_three_on_three_branch_knobs(self):
        host = Host()
        host.select(2027, 'RMUL1v1')
        self.assertEqual([s.name for s in visible_rule_settings(host.registry, host.registry.get('RobotProfile'))], ['Role'])
        self.assertEqual(host.state.remaining_ammo, 200)
        self.assertEqual(host.state.projectile_allowance_17mm, 200)
        self.assertEqual(host.state.projectile_allowance_42mm, 0)
        self.assertEqual(host.state.match_duration_sec, 120)

    def test_heavy_cannot_borrow_infantry_level_or_free_select_assembly(self):
        host = Host()
        host.select(2027, 'RMUC7v7')
        module = host.registry.get('RobotProfile')
        module.get_setting('Level').value = 9
        host.apply_robot_profile('Heavy', False, False)
        self.assertEqual([s.name for s in visible_rule_settings(host.registry, module)], ['Role'])
        self.assertEqual((host.state.level, host.state.max_health, host.state.projectile_type), (1, 400, 'None'))
        # Switching back restores only the infantry draft, never Heavy upgrades.
        host.apply_robot_profile('Infantry1', False, False)
        self.assertEqual(host.state.level, 9)

    def test_top_strip_projects_heavy_not_old_hero_and_retains_2026_labels(self):
        for year, expected in ((2027, 'HEAVY'), (2026, 'HERO')):
            controller = TopMatchBarController.__new__(TopMatchBarController)
            controller.owner = NS(state=NS(robot_id=1, rules_season=year))
            controller._context = (year,)
            controller._custom_rosters = None
            controller._frame_cache_key = controller._frame_cache = None
            frame = controller._snapshot_frame(TopMatchBarFeed((1, 3), (101, 103)), 1, True)
            self.assertEqual(frame.left.cards[0].label, expected)
            if year == 2027:
                self.assertEqual(match_role_text(frame.left.cards[0], True), '重装')
            self.assertEqual(frame.left.alive_text, '?')  # Rules are not life telemetry.

    def test_27_mock_targets_do_not_draw_even_after_model_state_is_cleared(self):
        from rm_client.ui.polar.renderers.esp_wireframe import EspWireframeMixin
        from rm_client.ui.polar.renderers.combat_target_hud import CombatTargetHudMixin
        host = NS(state=NS(rules_season=2027), _vision_source='Mock')
        # No painter/font/glass access is permitted for synthetic observations.
        EspWireframeMixin.draw_target_overlay(host, None, None)
        CombatTargetHudMixin.draw_target_card(host, None, None, None, 'Target')
        # This is not a ban on independently sourced Local/RMCS detections.
        host._vision_source = 'Local'
        host.lock_indicator_visible = Mock(return_value=False)
        EspWireframeMixin.draw_target_overlay(host, None, None)
        host.lock_indicator_visible.assert_called_once()


if __name__ == '__main__':
    unittest.main()
