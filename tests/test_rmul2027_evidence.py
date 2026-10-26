"""Offline evidence regression tests: no annual facade, PDF or GUI dependency."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import re
import unittest


LEAF = Path(__file__).resolve().parents[1] / 'rm_client' / 'rules' / 'rmul2027.py'
SPEC = importlib.util.spec_from_file_location('rmul2027_evidence_leaf', LEAF)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DATA = MODULE.DATA


def resolve(path):
    value = DATA
    for part in path.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def numeric_paths(item, path):
    if isinstance(item, dict):
        for key, value in item.items():
            yield from numeric_paths(value, f'{path}.{key}')
    elif isinstance(item, list):
        for index, value in enumerate(item):
            yield from numeric_paths(value, f'{path}.{index}')
    elif type(item) in (int, float):
        yield path


class RMUL2027EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.three = deepcopy(DATA['modes']['RMUL3v3'])
        self.one = deepcopy(DATA['modes']['RMUL1v1'])

    def test_formal_book_identity_not_preview_or_2026(self):
        self.assertEqual((DATA['season'], DATA['competition'], DATA['rule_version'], DATA['published']),
                         (2027, 'RMUL', '1.0.0', '2026-10-15'))
        self.assertEqual(len(DATA['sources']), 1)
        source = DATA['sources'][0]
        self.assertEqual(source['kind'], 'official_rules')
        self.assertRegex(source['sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(source['sha256'], 'a8fd7b7f6ea5212b9e4dfa590b478827992598d91912ed671653c8bdd9727fd6')
        self.assertIn('2027', source['title'])
        self.assertNotIn('前瞻', source['title'])

    def test_durations_dimensions_and_control_not_base_hp(self):
        self.assertEqual((self.three['duration_sec'], self.one['duration_sec']), (300, 120))
        self.assertEqual(self.three['field_size_m'], [12.0, 8.0])
        self.assertEqual(self.one['field_size_m'], [5.0, 5.0])
        self.assertEqual(self.three['victory_points'], 600)
        self.assertEqual(self.three['score_title'], '控制度')
        self.assertIsNone(self.one['victory_points'])
        for mode in (self.three, self.one):
            self.assertFalse(mode['features']['base'])
            self.assertFalse(mode['features']['rune'])
            self.assertFalse(mode['features']['hero_deploy'])
            self.assertFalse(any('base_health' in key or 'outpost_health' in key for key in mode))

    def test_official_role_ids_and_no_hero_alias(self):
        self.assertEqual([(r['key'], r['robot_id'], r['operator']) for r in self.three['roles']],
                         [('Heavy', 1, True), ('Infantry1', 3, True), ('Sentinel', 7, False)])
        self.assertEqual([(r['key'], r['robot_id']) for r in self.one['roles']], [('Infantry1', 3)])
        self.assertNotIn('Hero', self.three['performance'])
        self.assertNotIn('Engineer', [r['key'] for r in self.three['roles']])

    def test_heavy_opening_and_armed_are_separate(self):
        opening = self.three['performance']['Heavy']
        self.assertEqual(opening, {'max_health': 100, 'power_limit_w': 50,
                                  'heat_limit': None, 'cooling_rate': None, 'projectile': 'None'})
        self.assertEqual(self.three['performance']['Heavy:Armed'],
                         {'max_health': 450, 'power_limit_w': 50, 'heat_limit': 250,
                          'cooling_rate': 66, 'projectile': '42mm'})
        self.assertEqual(self.three['projectile_speed_limit_mps']['Heavy:Armed'], 16.5)
        self.assertIsNone(self.three['projectile_speed_limit_mps']['Heavy'])
        self.assertTrue(self.three['heavy_mechanism']['upgrade_requires_installed_module_and_detected_42mm_shot'])

    def test_infantry_variants_and_sentinel(self):
        variants = self.three['performance_variants']
        self.assertEqual(len(variants), 4)
        for key, profile in variants.items():
            _, chassis, shooter = key.split(':')
            self.assertEqual((profile['max_health'], profile['power_limit_w']),
                             (300, 90) if chassis == 'Power' else (350, 75))
            self.assertEqual((profile['heat_limit'], profile['cooling_rate']),
                             (230, 14) if shooter == 'Burst' else (88, 24))
        self.assertEqual(self.three['performance']['Infantry1'], variants['Infantry1:Health:Cooling'])
        self.assertEqual(self.three['performance']['Sentinel'],
                         {'max_health': 400, 'power_limit_w': 100, 'heat_limit': 260,
                          'cooling_rate': 30, 'projectile': '17mm'})

    def test_allowance_is_not_physical_loaded_ammo(self):
        self.assertEqual(self.three['initial_ammo'], {'Heavy': 0, 'Infantry1': 0, 'Sentinel': 750})
        self.assertEqual(self.one['initial_ammo'], {'Infantry1': 200})
        self.assertFalse(self.three['economy']['sentinel_can_increase_ammo'])
        self.assertFalse(self.one['economy']['can_increase_ammo'])

    def test_gold_schedule_and_only_formally_priced_cards(self):
        economy = self.three['economy']
        self.assertEqual(economy['initial_gold'], 200)
        self.assertEqual([(r['remaining_sec'], r['gold']) for r in economy['gold_schedule']],
                         [(299, 200), (239, 200), (179, 200), (119, 300), (59, 300)])
        self.assertEqual(economy['comeback_gap_thresholds'], [200, 400])
        self.assertEqual(economy['comeback_gold_cap_per_team'], 400)
        self.assertTrue(economy['gold_only_for_ammo'])
        cards = self.three['economy_catalogue']
        self.assertEqual([(c['key'], c['quantity'], c['cost'], c['roles']) for c in cards],
                         [('ammo_17mm', 10, 10, ['Infantry1']), ('ammo_42mm', 1, 10, ['Heavy'])])
        for card in cards:
            self.assertNotIn('command_type', card)
            self.assertNotIn('param', card)
            self.assertEqual(card['category'], 'ammo')
        self.assertEqual(self.one['economy_catalogue'], [])

    def test_respawn_is_progress_based_not_coin_purchase(self):
        economy = self.three['economy']
        self.assertEqual((economy['respawn_first_progress'], economy['respawn_progress_increment_per_death'],
                          economy['respawn_progress_per_sec']), (5, 5, 1))
        self.assertEqual((economy['respawn_health_fraction'], economy['respawn_invulnerability_sec']), (0.2, 30))
        self.assertTrue(economy['respawn_weak_shooter_locked'])
        self.assertTrue(economy['respawn_weak_cannot_activate_control'])
        self.assertEqual(economy['comeback_recovery'], [
            {'control_gap_at_least': 200, 'respawn_progress_reduction_fraction': 0.33,
             'supply_heal_max_health_fraction_per_sec': 0.33},
            {'control_gap_at_least': 400, 'respawn_progress_reduction_fraction': 0.5,
             'supply_heal_max_health_fraction_per_sec': 0.5}])
        self.assertFalse(any(c['category'] == 'revive' for c in self.three['economy_catalogue']))

    def test_three_independent_contested_control_zones_and_buffs(self):
        control = self.three['control']
        self.assertEqual((control['zone_count'], control['initial_score'], control['capture_progress_max']), (3, 600, 5))
        self.assertEqual(control['own_score_loss_per_death'], 10)
        self.assertTrue(control['contested_progress_pauses'])
        self.assertEqual(self.three['buffs']['highland_defense_fraction'], 0.25)
        self.assertEqual(self.three['buffs']['tunnel_cooling_multiplier'], 1.5)
        self.assertEqual(self.three['buffs']['tunnel_cooling_duration_sec'], 60)

    def test_one_on_one_new_lifesteal_without_respawn(self):
        self.assertEqual(self.one['performance']['Infantry1'],
                         {'max_health': 200, 'power_limit_w': 120, 'heat_limit': 80,
                          'cooling_rate': 12, 'projectile': '17mm'})
        self.assertEqual(self.one['economy']['projectile_damage_heal_fraction'], 0.5)
        self.assertFalse(self.one['economy']['automatic_respawn'])
        self.assertNotIn('performance_variants', self.one)
        self.assertNotIn('initial_gold', self.one['economy'])

    def test_every_numeric_fact_has_resolving_exact_page_citation(self):
        citations = DATA['field_citations']
        paths = list(numeric_paths(DATA['modes'], 'modes')) + ['season']
        self.assertGreater(len(paths), 100)
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(path, citations)
        for path, citation in citations.items():
            with self.subTest(citation=path):
                resolve(path)
                self.assertEqual(citation['source'], 0)
                self.assertTrue(1 <= citation['pdf_page'] <= 68)
                self.assertEqual(citation['printed_page'], citation['pdf_page'] - 1)
                self.assertTrue(citation['section'])
        self.assertEqual(citations['modes.RMUL1v1.economy.projectile_damage_heal_fraction']['pdf_page'], 45)
        self.assertEqual(citations['modes.RMUL3v3.roles.0.robot_id']['pdf_page'], 17)

    def test_leaf_does_not_import_facade_old_season_or_transport(self):
        text = LEAF.read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'^\s*(?:from|import)\s+', text, flags=re.MULTILINE))
        self.assertNotIn('command_type', DATA)


if __name__ == '__main__':
    unittest.main()
