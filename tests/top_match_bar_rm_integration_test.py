"""2026 RMUC roles/HP authority and real BF6 progress integration regressions."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import ast
import unittest
from unittest.mock import patch

from rm_client.model import build_default_registry
from rm_client.top_match_bar import LifeState as L, RobotCard, TopMatchBarFeed
from top_match_bar_qt_test import QT_AVAILABLE
from top_match_bar_integration_test import ControllerIntegrationTests


class RmHealthTests(unittest.TestCase):
    def setUp(self):
        self.feed = TopMatchBarFeed([1, 2, 3, 4, 6, 7, 8, 9], [101, 102, 103, 104, 106, 107, 108, 109],
                                    left_alliance="Red", score_label="RM SCORE")

    def send(self, name, data, at=10):
        self.feed.consume_referee(name, data, received_at=at, own_alliance="Red", local_robot_id=3)

    def card(self, rid=3, at=10):
        return next(c for t in (self.feed.snapshot(at).left, self.feed.snapshot(at).right)
                    for c in t.cards + t.systems if c.robot_id == rid)

    def test_official_2026_six_vehicles_and_two_support_systems(self):
        frame = self.feed.snapshot(10)
        self.assertEqual([c.robot_id for c in frame.left.cards], [1, 2, 3, 4, 6, 7])
        self.assertEqual([c.robot_id for c in frame.left.systems], [8, 9])
        self.assertEqual(frame.left.unknown_count, 5)
        self.assertEqual(self.card(6).health_text, "NO HP")

    def test_current_hp_uses_wire_order_and_does_not_invent_remote_max(self):
        self.send("GlobalUnitStatus", {"robot_health": [150, 250, 180, 90, 400, 200, 250, 40, 0, 400]})
        self.assertEqual(self.card(3).health, 180)
        self.assertEqual(self.card(104).health, 0)
        self.assertIsNone(self.card(103).max_health)
        self.assertIsNone(self.card(103).health_ratio)
        self.assertEqual(self.card(104).life, L.DEAD)
        self.assertEqual(self.feed.snapshot(10).left.alive_text, "5")

    def test_authoritative_local_max_enables_ratio_and_true_zero(self):
        self.send("RobotStaticStatus", {"robot_id": 3, "max_health": 400, "__present__": (4, 9)})
        self.send("RobotDynamicStatus", {"current_health": 180, "__present__": (1,)})
        self.assertEqual(self.card().health_ratio, .45)
        self.assertEqual(self.card().health_text, "180/400")
        self.send("RobotDynamicStatus", {"current_health": 0}, 11)
        self.assertEqual(self.card(at=11).health_ratio, 0.0)

    def test_missing_optional_max_or_bad_denominator_is_not_a_full_bar(self):
        self.send("RobotStaticStatus", {"max_health": 400, "__present__": ()})
        self.send("RobotDynamicStatus", {"current_health": 180})
        self.assertIsNone(self.card().max_health)
        for maximum in (0, -1, True, "400"):
            self.send("RobotStaticStatus", {"max_health": maximum})
            self.assertIsNone(self.card().health_ratio)

    def test_expired_max_is_not_refreshed_by_current_hp(self):
        self.send("RobotStaticStatus", {"max_health": 400})
        self.send("RobotDynamicStatus", {"current_health": 180}, 13)
        self.assertIsNone(self.card(at=13).max_health)
        self.assertEqual(self.card(at=13).health, 180)
        self.assertEqual(self.card(at=13).health_text, "HP 180 / ?")

    def test_max_cannot_be_assigned_to_arbitrary_enemy(self):
        self.send("RobotStaticStatus", {"robot_id": 103, "max_health": 400, "alive_state": 1})
        self.assertIsNone(self.card(103).max_health)
        self.assertEqual(self.card(103).life, L.UNKNOWN)

    def test_over_max_current_hp_has_no_misleading_clamped_bar(self):
        self.send("RobotStaticStatus", {"max_health": 150})
        self.send("RobotDynamicStatus", {"current_health": 180})
        self.assertIsNone(self.card().health_ratio)
        self.assertEqual(self.card().health, 180)

    def test_static_transition_clears_contradictory_hp(self):
        self.send("RobotDynamicStatus", {"current_health": 180})
        self.send("RobotStaticStatus", {"alive_state": 2}, 11)
        self.assertEqual(self.card(at=11).life, L.DEAD)
        self.assertIsNone(self.card(at=11).health)
        self.send("RobotDynamicStatus", {"current_health": 0}, 11.1)
        self.send("RobotStaticStatus", {"alive_state": 1}, 12)
        self.assertEqual(self.card(at=12).life, L.ALIVE)
        self.assertIsNone(self.card(at=12).health)

    def test_base_partial_missing_and_stale_remain_unknown(self):
        self.send("GlobalUnitStatus", {"base_health": 0, "enemy_base_health": 5000, "__present__": (1,)})
        frame = self.feed.snapshot(10)
        self.assertEqual(frame.own_base_health, 0)
        self.assertIsNone(frame.enemy_base_health)
        self.send("GameStatus", {"stage_countdown_sec": 80}, 13)
        self.assertIsNone(self.feed.snapshot(13).own_base_health)

    def test_round_reset_clears_base_hp_current_and_max(self):
        self.send("GameStatus", {"current_round": 1})
        self.send("GlobalUnitStatus", {"base_health": 1000})
        self.send("RobotStaticStatus", {"max_health": 400})
        self.send("RobotDynamicStatus", {"current_health": 180})
        self.send("GameStatus", {"current_round": 2}, 11)
        self.assertIsNone(self.feed.snapshot(11).own_base_health)
        self.assertIsNone(self.card(at=11).health)
        self.assertIsNone(self.card(at=11).max_health)

    def test_local_dynamic_death_beats_newer_slow_global_snapshot(self):
        self.send("RobotDynamicStatus", {"current_health": 0}, 10)
        self.send("GlobalUnitStatus", {"robot_health": [150, 250, 180, 90, 400]}, 11)
        self.assertEqual(self.card(at=11).health, 0)
        self.assertEqual(self.card(at=11).life, L.DEAD)
        self.send("GlobalUnitStatus", {"robot_health": [150, 250, 180, 90, 400]}, 13)
        self.assertEqual(self.card(at=13).health, 180)

    def test_saved_opt_out_survives_new_default(self):
        from rm_client.config_store import apply_registry_config
        registry = build_default_registry()
        apply_registry_config(registry, {"version": 1, "modules": {"TopMatchBar": {"enabled": False}}})
        self.assertFalse(registry.get("TopMatchBar").enabled)


if QT_AVAILABLE:
    from top_match_bar_qt_test import QtCore, QtGui, QtWidgets
    from tools.topbar_preview_support import load_progress_renderer
    Progress = load_progress_renderer(QtCore, QtGui)


@unittest.skipUnless(QT_AVAILABLE, "Qt absent")
class RmCompositionTests(ControllerIntegrationTests):
    # Deliberately reuse the fake-host controller setup; no app/backend startup.
    def setUp(self):
        super().setUp()
        self.state.match_mode = "RMUC7v7"
        self.owner.kill_fx = NS(match_progress=Progress())

    # Inherited original tests assume RMUL, so only collect new tests here.
    def test_bf6_real_renderer_is_below_cs_systems_and_island(self):
        self.controller.observe_referee("GlobalUnitStatus", {"base_health": 4000, "enemy_base_health": 2500}, 10)
        self.controller.observe_referee("GameStatus", {"blue_score": 2, "red_score": 1}, 10)
        image = self.paint()
        self.assertEqual(self.controller._last_error, "")
        self.assertIsNotNone(self.controller.last_progress_bounds)
        self.assertGreaterEqual(self.controller.last_progress_bounds.y(), self.controller.last_layout.bounds.bottom + 18)
        self.assertGreater(self.owner.kill_fx.match_progress.shown_own, 0)
        self.assertGreater(self.owner.kill_fx.match_progress.shown_enemy, self.owner.kill_fx.match_progress.shown_own)

    def test_expansion_never_eases_progress_through_cards(self):
        for height in (30, 46, 110, 46, 30):
            self.owner.dynamic_island_state.height = height
            self.paint()
            if self.controller.last_progress_bounds is not None:
                self.assertGreaterEqual(self.controller.last_progress_bounds.y(), self.controller.last_layout.bounds.bottom + 18)

    def test_disconnection_clears_bf6_fills_and_scores(self):
        self.controller.observe_referee("GlobalUnitStatus", {"base_health": 0, "enemy_base_health": 0}, 10)
        self.controller.observe_referee("GameStatus", {"blue_score": 9, "red_score": 8}, 10)
        self.paint()
        self.mqtt.connected = False
        self.paint(10.1)
        progress = self.owner.kill_fx.match_progress
        self.assertEqual(progress.shown_own, 0)
        self.assertEqual(progress.shown_enemy, 0)
        self.assertEqual(progress.own_score_scroll._target, 0)

    def test_fast_reconnect_invalidates_max_hp_and_base(self):
        self.controller.observe_referee("GlobalUnitStatus", {"base_health": 0}, 10)
        self.controller.observe_referee("RobotStaticStatus", {"max_health": 400}, 10)
        self.controller.observe_referee("RobotDynamicStatus", {"current_health": 180}, 10)
        self.paint()
        self.mqtt.receive_generation += 1
        self.paint(10.1)
        frame = self.controller.feed.snapshot(10.1)
        self.assertIsNone(frame.own_base_health)
        self.assertTrue(all(c.health is None and c.max_health is None for c in frame.left.cards))

    def test_progress_disabled_setting_and_rmul_do_not_draw_bases(self):
        self.registry.get("TopMatchBar").get_setting("BF6 Progress").value = False
        self.paint()
        self.assertIsNone(self.controller.last_progress_bounds)
        self.registry.get("TopMatchBar").get_setting("BF6 Progress").value = True
        self.state.match_mode = "RMUL3v3"
        self.paint()
        self.assertIsNone(self.controller.last_progress_bounds)

    def test_own_alliance_rows_and_progress_have_same_order(self):
        self.state.alliance_color = "Red"
        self.state.robot_id = 3
        self.paint()
        frame = self.controller.feed.snapshot(10)
        self.assertEqual(frame.left.alliance, "Red")
        self.assertEqual(frame.right.alliance, "Blue")

    def test_large_map_hides_both_strips_without_legacy_duplicate(self):
        self.owner.tactical_map_rect = lambda w, h: QtCore.QRectF(12, 58, 800, 600)
        self.paint()
        self.assertIsNone(self.controller.last_layout)
        self.assertIsNone(self.controller.last_progress_bounds)
        self.assertTrue(self.controller.owns_progress())

    def test_bf6_exception_restores_painter(self):
        with patch.object(self.owner.kill_fx.match_progress, "draw", side_effect=RuntimeError("test")):
            self.paint()
        self.assertIn("test", self.controller._last_error)
        self.assertIsNone(self.controller.last_layout)

    def test_combined_corridor_is_centered_and_reserved_at_all_sizes(self):
        for width, height in ((1000, 620), (1280, 720), (1920, 1080), (2560, 1440)):
            image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
            image.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(image)
            self.controller.paint(p, width, height, 10)
            p.end()
            layout = self.controller.last_layout
            self.assertIsNotNone(layout, (width, self.controller._last_error))
            self.assertAlmostEqual(layout.center.x + layout.center.width / 2, width / 2)
            self.assertGreaterEqual(layout.bounds.x, 192)
            self.assertLessEqual(layout.bounds.right, width - min(270, width * .25))

    def test_identity_conflict_never_assigns_own_hp_to_enemy(self):
        self.state.alliance_color = "Red"
        self.state.robot_id = 103
        self.controller.observe_referee("GlobalUnitStatus", {"robot_health": [200] * 10}, 10)
        frame = self.controller.feed.snapshot(10)
        self.assertTrue(all(c.health is None for t in (frame.left, frame.right) for c in t.cards))

    def test_actual_elimination_dispatch_suppresses_only_duplicate_progress(self):
        source = Path(__file__).resolve().parents[1] / "rm_client/ui/polar/mixins/video_backend_mixin.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VideoBackendMixin")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "draw_elimination_fx")
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method], type_ignores=[])
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
        captured = []
        toggles = {"match_progress": True, "scrolling_bf6": True, "hit_info": True}
        host = NS(registry=self.registry, top_match_bar=self.controller,
                  setting_mode=lambda m, key, default: default,
                  alliance_side=lambda: "Blue", state=self.state,
                  elimination_element_toggles=lambda effect: dict(toggles),
                  dynamic_island_bottom_anchor=lambda w, h: 47,
                  get_setting_number=lambda m, key, default: default,
                  devicePixelRatioF=lambda: 1, kill_fx=NS(draw=lambda *a, **kw: captured.append(kw)))
        self.registry.get("EliminationFX").enabled = True
        namespace["draw_elimination_fx"](host, None, 1280, 720)
        self.assertFalse(captured[-1]["element_toggles"]["match_progress"])
        self.assertTrue(captured[-1]["element_toggles"]["scrolling_bf6"])
        self.assertTrue(captured[-1]["element_toggles"]["hit_info"])
        self.registry.get("TopMatchBar").enabled = False
        namespace["draw_elimination_fx"](host, None, 1280, 720)
        self.assertTrue(captured[-1]["element_toggles"]["match_progress"])

    def test_bf6_invalid_hp_is_unknown_and_never_reuses_old_fill(self):
        image = QtGui.QImage(1280, 300, QtGui.QImage.Format_ARGB32_Premultiplied)
        p = QtGui.QPainter(image)
        progress = self.owner.kill_fx.match_progress
        progress.shown_own = progress.shown_enemy = .6
        try:
            progress.draw(p, 1280, 10, 1, own_base_health=5001, own_base_max=5000,
                          enemy_base_health=float("nan"), enemy_base_max=5000,
                          red_score=None, blue_score=None, own_blue=True)
        finally:
            p.end()
        self.assertEqual(progress.shown_own, 0)
        self.assertEqual(progress.shown_enemy, 0)

    def test_default_rmuc_scope_leaves_rmul_header_and_progress_ownership_alone(self):
        module = self.registry.get("TopMatchBar")
        module.get_setting("Match Scope").value = "RMUC Only"
        self.state.match_mode = "RMUL3v3"
        self.assertFalse(self.controller.enabled())
        self.assertFalse(self.controller.owns_progress())
        self.paint()
        self.assertIsNone(self.controller.last_layout)
        self.assertIsNone(self.controller.last_progress_bounds)
        self.assertIsNone(self.controller.feed)
        self.state.match_mode = "RMUC7v7"
        self.assertTrue(self.controller.enabled())
        self.paint()
        self.assertIsNotNone(self.controller.last_layout)

    def test_show_scores_hides_bf6_numbers_and_resets_old_scroll(self):
        self.controller.observe_referee("GameStatus", {"blue_score": 2, "red_score": 1}, 10)
        self.paint()
        progress = self.owner.kill_fx.match_progress
        self.assertEqual(progress.own_score_scroll._target, 2)
        self.registry.get("TopMatchBar").get_setting("Show Scores").value = False
        self.paint(10.1)
        self.assertEqual(progress.own_score_scroll._target, 0)
        self.assertEqual(progress.enemy_score_scroll._target, 0)
        self.registry.get("TopMatchBar").get_setting("Show Scores").value = True
        self.paint(10.2)
        self.assertEqual(progress.own_score_scroll._target, 2)

    def test_non_list_right_panels_reserve_fixed_bounds_with_module_list_off(self):
        hud = self.registry.get("HUD")
        hud.get_setting("Module List").value = False
        self.registry.get("TopMatchBar").get_setting("Scale").value = 1.4
        panels = {"KeyBindsHud": 236, "RobotListHud": 264, "TargetHud": 258,
                  "StatusCardsHud": 204, "RMIndicatorsHud": 254}
        for width, height in ((1000, 620), (1280, 720)):
            for mode, inset in panels.items():
                with self.subTest(width=width, mode=mode):
                    hud.get_setting("Right Display").value = mode
                    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
                    p = QtGui.QPainter(image)
                    self.controller.paint(p, width, height, 10)
                    p.end()
                    self.assertIsNotNone(self.controller.last_layout)
                    self.assertLessEqual(self.controller.last_layout.bounds.right, width - inset)
                    self.assertLessEqual(self.controller.last_progress_bounds.right(), width - inset)

    def test_left_bare_module_list_has_its_own_inset_when_map_is_off(self):
        self.registry.get("TacticalMap").enabled = False
        self.registry.get("HUD").get_setting("ModuleList Style").value = "PolarTextList"
        self.paint()
        self.assertGreaterEqual(self.controller.last_layout.bounds.x, 288)

    def test_island_collapse_keeps_easing_bf6_visible_in_clip(self):
        self.owner.dynamic_island_state.height = 150
        self.paint()
        self.assertIsNotNone(self.controller.last_progress_bounds)
        self.owner.dynamic_island_state.height = 30
        image = self.paint(10.1)
        bounds = self.controller.last_progress_bounds
        self.assertGreater(bounds.y(), self.controller.last_layout.bounds.bottom + 80)
        # Actual track pixels at its currently eased position must survive.
        self.assertGreater(image.pixelColor(400, round(bounds.y() + 3)).alpha(), 0)


# Do not accidentally collect the imported old suite a second time. Keep only
# newly declared tests; reuse its setup helpers with normal unittest semantics.
for _name in unittest.defaultTestLoader.getTestCaseNames(ControllerIntegrationTests):
    if _name not in RmCompositionTests.__dict__:
        setattr(RmCompositionTests, _name, None)
del ControllerIntegrationTests

if __name__ == "__main__":
    unittest.main()
