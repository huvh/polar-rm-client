"""Evidence regression tests: import the reviewed leaf only, no app/rules API."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rmuc2027_evidence_leaf", ROOT / "rm_client" / "rules" / "rmuc2027.py")
LEAF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEAF)
DATA = LEAF.DATA
MODE = DATA["modes"]["RMUC7v7"]


class RMUC2027EvidenceTests(unittest.TestCase):
    def test_document_identity_and_optional_local_integrity(self):
        self.assertEqual((DATA["season"], DATA["competition"], DATA["rule_version"], DATA["published"]),
                         (2027, "RMUC", "1.0.0", "2026-10-15"))
        source = DATA["sources"][0]
        self.assertEqual(source["kind"], "official_rules")
        self.assertRegex(source["sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(source["sha256"],
                         "9e2eed9295536c6fd547b62d634df1d5e70a2e1e2250e5dff3521d557e5d54be")
        pdf = ROOT / "tmp_rule_2027" / "rmuc" / "rmuc2027_v1.0.0.pdf"
        if pdf.exists():
            self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), source["sha256"])

    def test_duration_dimensions_and_real_2027_roster(self):
        self.assertEqual(MODE["duration_sec"], 420)
        self.assertEqual(MODE["field_size_m"], [28.0, 15.0])
        self.assertIsNone(MODE["victory_points"])
        roles = {row["key"]: row for row in MODE["roles"]}
        self.assertEqual({key: row["robot_id"] for key, row in roles.items()},
                         {"Heavy": 1, "Infantry1": 3, "Infantry2": 4,
                          "Aerial": 6, "Sentinel": 7, "Dart": 8, "Radar": 9})
        self.assertEqual(roles["Heavy"]["title"], "重装机器人")
        self.assertNotIn("Hero", roles)
        self.assertNotIn("Engineer", roles)
        self.assertEqual(roles["Aerial"]["projectile"], "None")
        self.assertFalse(roles["Sentinel"]["operator"])

    def test_default_base_attributes_are_not_armed_heavy_or_stance_buffs(self):
        heavy = MODE["performance"]["Heavy"]
        self.assertEqual((heavy["max_health"], heavy["power_limit_w"]), (400, 50))
        self.assertIsNone(heavy["heat_limit"])
        self.assertIsNone(heavy["cooling_rate"])
        armed = MODE["heavy_stages"]["assembly_3_or_shooter_installed"]
        self.assertEqual(tuple(armed[key] for key in
                               ("max_health", "power_limit_w", "heat_limit", "cooling_rate")),
                         (600, 50, 300, 100))
        self.assertEqual(armed["projectile_speed_limit_mps"], 16.5)
        infantry = MODE["performance"]["Infantry1"]
        self.assertEqual(tuple(infantry[key] for key in
                               ("max_health", "power_limit_w", "heat_limit", "cooling_rate")),
                         (200, 45, 40, 12))
        self.assertEqual(MODE["performance"]["Sentinel"]["power_limit_w"], 100)
        for key in ("Aerial", "Dart", "Radar"):
            for field in ("max_health", "power_limit_w", "heat_limit", "cooling_rate"):
                self.assertIsNone(MODE["performance"][key][field])

    def test_all_infantry_levels_match_2027_full_tables(self):
        tables = MODE["infantry_levels"]
        self.assertEqual(tables, {
            "chassis": {
                "Power": {"max_health": [150, 175, 200, 225, 250, 275, 300, 325, 350, 400],
                          "power_limit_w": [60, 65, 70, 75, 80, 85, 90, 95, 100, 100]},
                "Health": {"max_health": [200, 225, 250, 275, 300, 325, 350, 375, 400, 400],
                           "power_limit_w": [45, 50, 55, 60, 65, 70, 75, 80, 90, 100]},
            },
            "shooter": {
                "Burst": {"heat_limit": [170, 180, 190, 200, 210, 220, 230, 240, 250, 260],
                          "cooling_rate": [5, 7, 9, 11, 12, 13, 14, 16, 18, 20]},
                "Cooling": {"heat_limit": [40, 48, 56, 64, 72, 80, 88, 96, 104, 120],
                            "cooling_rate": [12, 14, 16, 18, 20, 22, 24, 26, 28, 30]},
            },
        })
        self.assertNotIn("Rate", tables["shooter"])
        self.assertEqual(MODE["sentinel_control_modes"], {
            "Automatic": {"max_health": 400, "power_limit_w": 100, "heat_limit": 260,
                          "cooling_rate": 30, "projectile": "17mm"},
            "SemiAuto": {"max_health": 200, "power_limit_w": 60, "heat_limit": 100,
                         "cooling_rate": 10, "projectile": "17mm"},
        })

    def test_base_economy_and_initial_ammo_are_not_2026_fallbacks(self):
        for key in ("base_health", "base_max_health", "enemy_base_health", "enemy_base_max_health"):
            self.assertEqual(MODE[key], 10000)
        for key in ("outpost_health", "outpost_max_health", "enemy_outpost_health", "enemy_outpost_max_health"):
            self.assertEqual(MODE[key], 1000)
        self.assertIsNone(MODE["base_virtual_shield"])
        self.assertEqual(MODE["economy"]["initial_coins"], 800)
        self.assertEqual([row["coins"] for row in MODE["economy"]["periodic_coin_grants"]],
                         [100, 100, 100, 100, 100, 300])
        self.assertEqual(MODE["initial_ammo"],
                         {"Heavy": 0, "Infantry1": 0, "Infantry2": 0, "Sentinel": 300})
        self.assertNotIn("Aerial", MODE["initial_ammo"])
        respawn = MODE["economy"]["respawn"]
        self.assertEqual(respawn["accelerate_base_health_below"], 4000)
        self.assertEqual(respawn["paid_weak_and_invulnerable_sec"], 3)
        self.assertEqual(respawn["paid_cost_formula"],
                         "ceil((420 - remaining_sec) / 60) * 80 + robot_level * 20")

    def test_catalogue_is_offline_semantics_not_old_wire_commands(self):
        cards = {row["key"]: row for row in MODE["economy_catalogue"]}
        for key, quantity, cost in (("ammo17_local", 10, 10), ("ammo17_remote", 100, 150),
                                    ("ammo42_local", 1, 10), ("ammo42_remote", 10, 150)):
            self.assertEqual((cards[key]["quantity"], cards[key]["cost"]), (quantity, cost))
        self.assertIsNone(cards["heal_remote"]["cost"])
        self.assertIsNone(cards["revive_paid"]["cost"])
        valid_roles = {row["key"] for row in MODE["roles"]}
        for card in cards.values():
            self.assertTrue(set(card["roles"]) <= valid_roles)
            self.assertNotIn("command_type", card)
            self.assertNotIn("param", card)
        self.assertFalse(MODE["features"]["hero_deploy"])
        self.assertTrue(MODE["features"]["control_points"])

    def test_each_numeric_fact_has_a_page_locator(self):
        citations = DATA["field_citations"]
        for citation in citations.values():
            self.assertEqual(citation["source"], 0)
            self.assertTrue(1 <= citation["pdf_page"] <= 144)
            self.assertEqual(citation["printed_page"], citation["pdf_page"] - 1)
            self.assertTrue(citation["section"])

        def check(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    check(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    check(item, f"{path}.{index}")
            elif type(value) in (int, float):
                parts = path.split(".")
                self.assertTrue(any(".".join(parts[:length]) in citations
                                    for length in range(3, len(parts) + 1)), path)

        check(MODE, "modes.RMUC7v7")
        self.assertEqual(citations["modes.RMUC7v7.infantry_levels.chassis.Health.max_health.2"]["pdf_page"], 94)
        self.assertEqual(citations["modes.RMUC7v7.infantry_levels.shooter.Cooling.heat_limit.9"]["pdf_page"], 95)


if __name__ == "__main__":
    unittest.main()
