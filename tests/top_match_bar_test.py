"""Standard-library checks; run with python -m unittest discover -s tests -p top_match_bar_test.py."""
import ast
import pathlib
import unittest

from rm_client.top_match_bar import LifeState as Life, MatchBarFrame, RobotCard, TeamStrip, TopMatchBarFeed, compute_layout


class DataTests(unittest.TestCase):
    def setUp(self):
        self.feed = TopMatchBarFeed([1, 3, 7], [101, 103, 107], score_label="RM SCORE")

    def send(self, name, data, at=10, alliance="Red", local=3):
        self.feed.consume_referee(name, data, received_at=at, own_alliance=alliance, local_robot_id=local)

    def cards(self, at=10):
        f = self.feed.snapshot(at)
        return {c.robot_id: c for t in (f.left, f.right) for c in t.cards}

    def test_initial_is_unknown_not_default_robot_state(self):
        frame = self.feed.snapshot(10)
        self.assertEqual(frame.clock_text, "—:——")
        self.assertEqual(frame.left.alive_text, "?")
        self.assertIsNone(frame.left.score)
        self.assertTrue(all(c.life == Life.UNKNOWN for c in self.cards().values()))

    def test_global_wire_roles_are_not_display_roster(self):
        self.send("GlobalUnitStatus", {"robot_health": [100, 80, 0, 90, 5, 0, 22, 88, 40, 0]})
        cards = self.cards()
        self.assertEqual(cards[3].life, Life.DEAD)
        self.assertEqual(cards[7].life, Life.ALIVE)
        self.assertEqual(cards[101].life, Life.DEAD)
        self.assertEqual(cards[103].life, Life.ALIVE)
        self.assertEqual(len(cards), 6)

    def test_blue_own_vector_flips_ids_not_labels(self):
        self.send("GlobalUnitStatus", {"robot_health": [100, 80, 0, 90, 5]}, alliance="Blue", local=103)
        self.assertEqual(self.cards()[103].life, Life.DEAD)
        self.assertEqual(self.cards()[3].life, Life.UNKNOWN)

    def test_short_vector_does_not_forge_enemy_deaths(self):
        self.send("GlobalUnitStatus", {"robot_health": [50, 50, 50, 50, 50]})
        self.assertTrue(all(self.cards()[i].life == Life.UNKNOWN for i in (101, 103, 107)))
        self.assertEqual(self.feed.snapshot(10).left.alive_text, "?")

    def test_partial_vector_invalidates_removed_slots(self):
        self.send("GlobalUnitStatus", {"robot_health": [50] * 10})
        self.send("GlobalUnitStatus", {"robot_health": [50]}, at=11)
        self.assertEqual(self.cards(11)[103].life, Life.UNKNOWN)

    def test_bad_vector_entry_keeps_indices(self):
        self.send("GlobalUnitStatus", {"robot_health": [50, "bad", 0, False, 80]})
        self.assertEqual(self.cards()[3].life, Life.DEAD)
        self.assertEqual(self.cards()[7].life, Life.ALIVE)

    def test_optional_absence_never_becomes_zero(self):
        self.send("GameStatus", {"stage_countdown_sec": 0, "red_score": 0, "current_stage": 4, "__present__": (5,)})
        frame = self.feed.snapshot(10)
        self.assertIsNone(frame.countdown)
        self.assertIsNone(frame.right.score)
        self.assertEqual(frame.phase, "MATCH")

    def test_true_zero_is_preserved(self):
        self.send("GameStatus", {"stage_countdown_sec": 0, "red_score": 0, "blue_score": 0})
        frame = self.feed.snapshot(10)
        self.assertEqual(frame.clock_text, "0:00")
        self.assertEqual(frame.right.score, 0)

    def test_score_requires_explicit_metric(self):
        f = TopMatchBarFeed([1], [101])
        f.consume_referee("GameStatus", {"red_score": 3, "blue_score": 4}, received_at=10, own_alliance="Red", local_robot_id=1)
        self.assertIsNone(f.snapshot(10).left.score)

    def test_unrelated_packet_does_not_refresh_health_or_timer(self):
        self.send("GlobalUnitStatus", {"robot_health": [50] * 10})
        self.send("GameStatus", {"stage_countdown_sec": 85})
        self.send("GameStatus", {"red_score": 9}, at=12)
        self.send("Buff", {"something": 1}, at=13)
        frame = self.feed.snapshot(13)
        self.assertIsNone(frame.countdown)
        self.assertEqual(frame.right.score, 9)
        self.assertEqual(frame.right.alive_text, "?")

    def test_local_zero_override_and_resurrection(self):
        self.send("GlobalUnitStatus", {"robot_health": [50] * 10})
        self.send("RobotDynamicStatus", {"current_health": 0}, at=11)
        self.assertEqual(self.cards(11)[3].life, Life.DEAD)
        self.send("RobotDynamicStatus", {"current_health": 15}, at=12)
        self.assertEqual(self.cards(12)[3].life, Life.ALIVE)

    def test_older_packets_do_not_override_newer_observation(self):
        self.send("RobotDynamicStatus", {"current_health": 0}, at=11)
        self.send("GlobalUnitStatus", {"robot_health": [50] * 10}, at=10)
        self.assertEqual(self.cards(11)[3].life, Life.DEAD)
        self.send("GameStatus", {"stage_countdown_sec": 85}, at=11)
        self.send("GameStatus", {"stage_countdown_sec": 90}, at=10)
        self.assertEqual(self.feed.snapshot(11).clock_text, "1:25")

    def test_invalid_values_fail_unknown(self):
        self.send("GameStatus", {"stage_countdown_sec": -1, "red_score": True})
        self.send("RobotDynamicStatus", {"current_health": float("nan")})
        self.assertIsNone(self.feed.snapshot(10).countdown)
        self.assertIsNone(self.feed.snapshot(10).right.score)
        self.assertEqual(self.cards()[3].life, Life.UNKNOWN)

    def test_future_observations_hidden(self):
        self.send("GameStatus", {"stage_countdown_sec": 85}, at=15)
        self.assertIsNone(self.feed.snapshot(10).countdown)

    def test_alliance_change_resets_old_projection(self):
        self.send("GlobalUnitStatus", {"robot_health": [50] * 10})
        self.send("Buff", {}, at=11, alliance="Blue", local=103)
        self.assertEqual(self.cards(11)[3].life, Life.UNKNOWN)

    def test_kills_require_identity_attribution_dedup_and_reset(self):
        event = dict(event_id="round1-event1", killer_id=3, victim_id=103, confirmed=True, source="referee")
        self.assertTrue(self.feed.record_confirmed_elimination(**event))
        self.assertFalse(self.feed.record_confirmed_elimination(**event))
        self.assertFalse(self.feed.record_confirmed_elimination(**dict(event, event_id="visual", source="vision")))
        self.assertFalse(self.feed.record_confirmed_elimination(**dict(event, event_id="no_killer", killer_id=0)))
        self.assertEqual(self.cards()[3].kills, 1)
        self.send("GameStatus", {"current_round": 1})
        self.send("GameStatus", {"current_round": 2}, at=11)
        self.assertIsNone(self.cards(11)[3].kills)
        self.feed.reset()
        self.assertIsNone(self.cards(11)[3].kills)

    def test_kill_marker_rejects_truthy_strings_and_boolean_ids(self):
        event = dict(event_id="round1-event1", killer_id=3, victim_id=103, confirmed=True, source="referee")
        self.assertFalse(self.feed.record_confirmed_elimination(**dict(event, confirmed="false")))
        self.assertFalse(self.feed.record_confirmed_elimination(**dict(event, killer_id=True)))
        self.assertFalse(self.feed.record_confirmed_elimination(**dict(event, event_id="x" * 161)))

    def test_new_round_clears_old_deaths(self):
        self.send("GameStatus", {"current_round": 1, "stage_countdown_sec": 1})
        self.send("RobotDynamicStatus", {"current_health": 0})
        self.send("GameStatus", {"current_round": 2}, at=11)
        self.assertEqual(self.cards(11)[3].life, Life.UNKNOWN)
        self.assertIsNone(self.feed.snapshot(11).countdown)

    def test_static_requires_present_life_field(self):
        self.send("RobotStaticStatus", {"alive_state": 2, "robot_id": 3, "__present__": (4,)})
        self.assertEqual(self.cards()[3].life, Life.UNKNOWN)
        self.send("RobotStaticStatus", {"alive_state": 2, "robot_id": 3, "__present__": (3, 4)})
        self.assertEqual(self.cards()[3].life, Life.DEAD)

    def test_late_previous_round_packet_cannot_restore_cleared_state(self):
        self.send("GameStatus", {"current_round": 1}, at=10)
        self.send("GameStatus", {"current_round": 2}, at=12)
        self.send("RobotDynamicStatus", {"current_health": 0}, at=11)
        self.send("GlobalUnitStatus", {"robot_health": [0] * 10}, at=11)
        self.send("GameStatus", {"stage_countdown_sec": 7}, at=11)
        frame = self.feed.snapshot(12)
        self.assertTrue(all(card.life == Life.UNKNOWN for team in (frame.left, frame.right) for card in team.cards))
        self.assertIsNone(frame.countdown)
        self.send("RobotDynamicStatus", {"current_health": 50}, at=12.1)
        self.assertEqual(self.cards(12.1)[3].life, Life.ALIVE)

    def test_no_roster_is_not_zero_alive(self):
        self.assertEqual(TeamStrip("Blue").alive_text, "—")

    def test_alive_count_with_unknown_is_explicit_lower_bound(self):
        team = TeamStrip("Blue", (RobotCard(101, "H", Life.ALIVE), RobotCard(103, "3", Life.UNKNOWN)))
        self.assertEqual(team.alive_text, "1+?")

    def test_input_dictionary_never_mutated(self):
        data = {"robot_health": [0, 1, 2], "__present__": (11,)}
        before = repr(data)
        self.send("GlobalUnitStatus", data)
        self.assertEqual(repr(data), before)

    def test_bad_static_robot_id_cannot_become_local_death_or_grow_cache(self):
        self.send("RobotStaticStatus", {"alive_state": 2, "robot_id": 99999})
        self.assertEqual(self.cards()[3].life, Life.UNKNOWN)
        self.assertFalse(self.feed._health)
        with self.assertRaises(ValueError):
            self.send("GameStatus", {}, local=99999)

    def test_invalid_rosters_and_timestamps_rejected(self):
        for red, blue in [([1, 1], [101]), ([101], [1]), ([True], [101])]:
            with self.assertRaises(ValueError):
                TopMatchBarFeed(red, blue)
        with self.assertRaises(ValueError):
            self.feed.snapshot(float("nan"))


class LayoutTests(unittest.TestCase):
    def test_reference_geometry(self):
        layout = compute_layout(1024, 5, 5)
        self.assertEqual(layout.center.width, 108)
        self.assertEqual(layout.left_cards[0].width, 70)
        self.assertEqual(layout.left_cards[1].x - layout.left_cards[0].x, 78)
        self.assertEqual(layout.right_cards[0].x - layout.center.right, 6)
        self.assertEqual(layout.bounds.width, 884)

    def test_dynamic_roster_symmetry_and_fit(self):
        for width in (240, 480, 640, 1024, 1920, 2560):
            for left, right in ((0, 0), (3, 3), (5, 5), (7, 7), (3, 7), (8, 2), (9, 9)):
                with self.subTest(width=width, left=left, right=right):
                    layout = compute_layout(width, left, right)
                    self.assertAlmostEqual(layout.center.x + layout.center.width / 2, width / 2)
                    self.assertGreaterEqual(layout.bounds.x, 12 - 1e-8)
                    self.assertLessEqual(layout.bounds.right, width - 12 + 1e-8)
                    if not layout.compact:
                        self.assertEqual(len(layout.left_cards), left)
                        self.assertEqual(len(layout.right_cards), right)
                        rects = list(layout.left_cards) + [layout.center] + list(layout.right_cards)
                        for a, b in zip(rects, rects[1:]):
                            self.assertLessEqual(a.right, b.x + 1e-8)

    def test_compact_keeps_center_and_elides_portraits(self):
        layout = compute_layout(300, 9, 9)
        self.assertTrue(layout.compact)
        self.assertFalse(layout.left_cards)
        self.assertFalse(layout.right_cards)
        self.assertGreater(layout.center.width, 100)

    def test_safe_insets_reserve_existing_hud(self):
        layout = compute_layout(1280, 5, 5, safe_left=240, safe_right=210, top=94)
        self.assertGreaterEqual(layout.bounds.x, 240)
        self.assertLessEqual(layout.bounds.right, 1070)
        self.assertEqual(layout.bounds.y, 94)

    def test_bad_dimensions_rejected(self):
        for args in ((float("nan"), 5, 5), (0, 5, 5), (100, -1, 3), (100, 17, 3)):
            with self.assertRaises(ValueError):
                compute_layout(*args)

    def test_new_modules_have_no_io_or_control_imports(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        for path in (root / "rm_client/top_match_bar.py", root / "rm_client/ui/top_match_bar.py"):
            tree = ast.parse(path.read_text())
            names = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
            self.assertFalse(any(any(word in name for word in ("socket", "serial", "mqtt", "control", "vision", "backend")) for name in names))


if __name__ == "__main__":
    unittest.main()
