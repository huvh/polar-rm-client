"""Annual facts/selection/migration regression; not 2027 wire qualification."""
from pathlib import Path
import hashlib
import json
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_client.rules import competition_rules,match_modes_for_season,validate_season,UnsupportedRules
from rm_client.rules.presentation import visible_rule_settings
from rm_client.match_modes import MatchModeManager,match_mode_config
from rm_client.robot_profiles import profiles_for_match,resolve_performance,apply_profile_to_state
from rm_client.model import RobotState,build_default_registry
from rm_client.economy import available_actions,EconomyCommandBridge
from rm_client.economy_values import EconomyOffer
from rm_client.configuration.migrations import migrated_modules
from rm_client.configuration.effects import effects_for_setting,SettingEffect
from rm_client.configuration.registry import SettingId


class RulesRuntimeTests(unittest.TestCase):
    def test_year_is_explicit_not_current_date_or_v2_alias(self):
        for value in (True,2028,'rm2026-v2.0.0',2027.0,None):
            with self.subTest(value=value),self.assertRaises(UnsupportedRules):validate_season(value)
        self.assertEqual(validate_season('2027'),2027)
        self.assertEqual(match_modes_for_season(2026),('RMUC7v7','RMUL3v3'))
        self.assertIn('RMUL1v1',match_modes_for_season(2027))

    def test_2027_sources_and_facts_are_immutable(self):
        rules=competition_rules(2027,'RMUL3v3')
        self.assertEqual(rules.version,'1.0.0')
        self.assertEqual(len(rules.sources[0]['sha256']),64)
        with self.assertRaises(TypeError):rules.facts['duration_sec']=999
        with self.assertRaises(TypeError):rules.roles[0]['robot_id']=2

    def test_original_field_illustrations_have_hashes_and_no_projection_claim(self):
        root=Path(__file__).resolve().parents[1]
        for filename in ('rmul_2027_rules_provenance.json','rmuc_2027_rules_provenance.json'):
            doc=json.loads((root/'assets/maps'/filename).read_text(encoding='utf8'))
            self.assertFalse(doc['calibration']['tactical_projection_ready'])
            for asset in doc['assets']:
                payload=(root/asset['repo_path']).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(),asset['sha256'])
                self.assertFalse(match_mode_config(asset['mode'],2027).field.positions_calibrated)

    def test_3v3_control_and_roles_are_not_old_hero_or_200_points(self):
        rules=competition_rules(2027,'RMUL3v3')
        self.assertEqual(rules.facts['victory_points'],600)
        roles=profiles_for_match('RMUL3v3',season=2027)
        self.assertEqual([r.key for r in roles],['Heavy','Infantry1','Sentinel'])
        self.assertEqual([r.robot_id for r in roles],[1,3,7])
        self.assertFalse(roles[-1].operator_role)

    def test_rmuc_new_roster_and_base_values(self):
        rules=competition_rules(2027,'RMUC7v7')
        keys={r.key for r in profiles_for_match('RMUC7v7',season=2027)}
        self.assertNotIn('Engineer',keys)
        self.assertNotIn('Hero',keys)
        self.assertIn('Heavy',keys)
        self.assertEqual(rules.facts['base_max_health'],10000)
        self.assertEqual(rules.facts['outpost_max_health'],1000)
        self.assertFalse(rules.features['hero_deploy'])
        self.assertEqual(rules.facts['control']['zone_count'],4)
        self.assertIsNone(rules.facts['control']['fixed_winning_threshold'])
        self.assertEqual(rules.facts['control']['both_base_positions_score_per_sec'],3)

    def test_new_1v1_is_fixed_120_seconds_and_5m_not_3v3_fallback(self):
        config=match_mode_config('RMUL1v1',2027)
        self.assertEqual(config.duration_sec,120)
        self.assertEqual((config.field.width_m,config.field.height_m),(5,5))
        self.assertIn('VictoryPointStatus',config.disabled_modules)
        with self.assertRaises(ValueError):match_mode_config('RMUL1v1',2026)

    def test_no_old_map_or_hot_zones_relabelled_2027(self):
        for key in match_modes_for_season(2027):
            config=match_mode_config(key,2027)
            self.assertNotIn('rmuc_7v7_official.png',config.field.asset_path)
            self.assertNotIn('rmul_3v3_official.png',config.field.asset_path)
            self.assertFalse(config.field.zones)
            self.assertFalse(config.field.mirror_for_blue)

    def test_heavy_opening_does_not_unlock_installed_shooter(self):
        perf=resolve_performance('RMUL3v3','Heavy',season=2027)
        self.assertEqual((perf.max_health,perf.power_limit_w),(100,50))
        self.assertEqual(perf.projectile,'None')
        self.assertEqual((perf.heat_limit,perf.cooling_rate),(0,0))
        self.assertNotEqual(perf.max_health,450)
        rmuc=resolve_performance('RMUC7v7','Heavy',season=2027)
        self.assertEqual((rmuc.max_health,rmuc.power_limit_w,rmuc.projectile),(400,50,'None'))

    def test_27_infantry_branch_and_initial_ammo_do_not_use_26_capacity(self):
        perf=resolve_performance('RMUL3v3','Infantry1',season=2027,
            infantry_chassis='Health',infantry_shooter='Cooling')
        self.assertEqual((perf.max_health,perf.power_limit_w,perf.heat_limit,perf.cooling_rate),(350,75,88,24))
        state=RobotState(rules_season=2027)
        apply_profile_to_state(state,profiles_for_match('RMUL3v3',season=2027)[1],perf,1)
        self.assertEqual(state.remaining_ammo,0)
        sentinel=resolve_performance('RMUL3v3','Sentinel',season=2027)
        self.assertEqual(sentinel.initial_ammo,750)

    def test_1v1_performance_and_ammo_are_independent(self):
        perf=resolve_performance('RMUL1v1','Infantry1',season=2027)
        self.assertEqual((perf.max_health,perf.power_limit_w,perf.heat_limit,perf.cooling_rate),(200,120,80,12))
        self.assertEqual(perf.initial_ammo,200)

    def test_rmuc_level_nine_uses_2027_104_not_old_114_heat(self):
        perf=resolve_performance('RMUC7v7','Infantry1',season=2027,
            level=9,infantry_chassis='Health',infantry_shooter='Cooling')
        self.assertEqual(perf.heat_limit,104)
        self.assertTrue(perf.verified)
        with self.assertRaises(ValueError):resolve_performance('RMUC7v7','Infantry1',season=2027,level=11)

    def test_unknown_27_role_performance_never_falls_back_to_26(self):
        perf=resolve_performance('RMUC7v7','Engineer',season=2027)
        self.assertFalse(perf.verified)
        self.assertEqual(perf.max_health,0)
        self.assertEqual(perf.power_limit_w,0)
        bogus=resolve_performance('RMUC7v7','InfantryBogus',season=2027)
        self.assertFalse(bogus.verified)
        self.assertEqual(bogus.max_health,0)

    def test_unselected_27_branches_use_formal_defaults_and_unknown_branch_is_rejected(self):
        perf=resolve_performance('RMUL3v3','Infantry1',season=2027)
        self.assertEqual((perf.max_health,perf.power_limit_w,perf.heat_limit,perf.cooling_rate),(350,75,88,24))
        with self.assertRaises(ValueError):
            resolve_performance('RMUL3v3','Infantry1',season=2027,infantry_shooter='Unknown')
        old=resolve_performance('RMUL3v3','Infantry1',season=2026)
        self.assertEqual((old.max_health,old.power_limit_w,old.heat_limit,old.cooling_rate),(300,90,230,14))

    def test_27_never_runs_26_demo_tick(self):
        state=RobotState(rules_season=2027)
        state.ally_victory_points=600;state.remaining_economy=200
        state.map_robots=[];state.buff_rows=[];state.robot_rows=[]
        state.tick(.016)
        self.assertEqual(state.ally_victory_points,600)
        self.assertEqual(state.remaining_economy,200)
        self.assertFalse(state.map_robots or state.buff_rows or state.robot_rows)
        self.assertEqual(state.current_stage,'NOT_STARTED')

    def test_economy_cards_are_source_facts_not_invented_old_commands(self):
        state=RobotState(rules_season=2027,match_mode='RMUL3v3',robot_profile='Infantry1')
        cards=available_actions(state)
        self.assertTrue(cards)
        self.assertTrue(all(not row.enabled and row.status_only for row in cards))
        self.assertTrue(all(row.command_type==row.command_param==0 for row in cards))
        forged=EconomyOffer('x','ammo','x','x','x','x',1,1,1,10,True)
        with self.assertRaisesRegex(ValueError,'2027'):EconomyCommandBridge().submit(state,forged,mock=True)

    def test_rule_formula_is_not_displayed_as_zero_coin_quote(self):
        from rm_client.ui.economy_presentation import offer_price_text,offer_detail_price_text
        state=RobotState(rules_season=2027,match_mode='RMUC7v7',robot_profile='Heavy')
        cards=available_actions(state)
        formula=next(card for card in cards if card.category=='recovery')
        self.assertNotIn('0 金币',offer_detail_price_text(formula,True))
        self.assertIn('未报价',offer_price_text(formula))
        self.assertIn('未接入2027裁判',offer_detail_price_text(formula,True))

    def test_old_config_stays_2026_without_touching_original(self):
        source={'modules':{'MatchMode':{'settings':{'Mode':'RMUL3v3'}}}}
        result=migrated_modules(source)
        self.assertEqual(result['MatchMode']['settings']['Season'],'2026')
        self.assertNotIn('Season',source['modules']['MatchMode']['settings'])
        source['modules']['MatchMode']['settings']['Season']='2027'
        self.assertEqual(migrated_modules(source)['MatchMode']['settings']['Season'],'2027')
        self.assertNotIn('MatchMode',migrated_modules({'modules':{'HUD':{'enabled':True}}}))

    def test_saved_27_role_and_duel_are_not_lost_against_26_enum_options(self):
        from rm_client.config_store import apply_registry_config
        for mode,role in (('RMUL1v1','Infantry1'),('RMUL3v3','Heavy')):
            registry=build_default_registry()
            # Role intentionally precedes season in the serialized document.
            apply_registry_config(registry,{'modules':{
                'RobotProfile':{'settings':{'Role':role}},
                'MatchMode':{'settings':{'Season':'2027','Mode':mode}}}})
            self.assertEqual(registry.get('MatchMode').get_setting('Mode').value,mode)
            self.assertEqual(registry.get('RobotProfile').get_setting('Role').value,role)
            self.assertEqual(registry.get('RobotProfile').get_setting('Infantry Chassis').value,'Health')
            self.assertEqual(registry.get('RobotProfile').get_setting('Infantry Shooter').value,'Cooling')

    def test_registry_season_effect_uses_normal_quiesced_mode_path(self):
        registry=build_default_registry();manager=MatchModeManager(season=2027)
        manager.set_mode('RMUL3v3');manager.apply_to_registry(registry)
        module=registry.get('MatchMode')
        self.assertEqual(module.get_setting('Season').value,'2027')
        self.assertIn('RMUL1v1',module.get_setting('Mode').options)
        self.assertIn(SettingEffect.APPLY_MATCH_MODE,effects_for_setting(SettingId('MatchMode','Season'),'2027').effects)
        names={s.name for s in visible_rule_settings(registry,registry.get('RobotProfile'))}
        self.assertNotIn('Hero Type',names)
        self.assertIn('Infantry Chassis',names)


if __name__=='__main__':unittest.main()
