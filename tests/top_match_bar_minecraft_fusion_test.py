"""Actual MC/CS/BF6 painter composition through the production HUD dispatcher.

No application, video, transport, audio or actuator startup. The opt-in Qt5
bootstrap is a compatibility preview only; production uses PySide6.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import ast
import time
import unittest
from unittest.mock import Mock, patch

from rm_client.model import RobotState, build_default_registry
from rm_client.config_store import apply_registry_config
from rm_client.ui.overlay_coordinator import OverlayCoordinator
from top_match_bar_qt_test import QT_AVAILABLE

ROOT = Path(__file__).resolve().parents[1]


def production_methods(path, class_name, names):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in methods} == set(names)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + methods, type_ignores=[])
    scope = {"time": time, "HUD_MODES": ["ModuleListHud"]}
    exec(compile(ast.fix_missing_locations(module), path, "exec"), scope)
    return scope


class SafeAreaTests(unittest.TestCase):
    def test_nonfinite_or_negative_geometry_is_rejected(self):
        for key in ("width", "height", "hud_scale", "top", "inset"):
            for value in (float("nan"), float("inf"), -1, True):
                values = dict(width=1280, height=720, hud_scale=1, top=62, inset=270)
                values[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    OverlayCoordinator.top_hud_safe_area(**values)

    def test_default_corridor_does_not_change_modal_ownership(self):
        coordinator = OverlayCoordinator(modal="economy", chat_input=True)
        area = coordinator.top_hud_safe_area(1280, 720, top=62, inset=270)
        self.assertEqual((area.top, area.inset), (62, 270))
        self.assertAlmostEqual(area.bottom, 345.6)
        self.assertEqual(coordinator.modal, "economy")
        self.assertTrue(coordinator.chat_input)


if QT_AVAILABLE:
    from top_match_bar_qt_test import QtCore, QtGui, QtWidgets
    from rm_client.ui.minecraft_hud import MinecraftCombatHudRenderer
    from rm_client.ui.top_match_bar_controller import TopMatchBarController
    from rm_client.top_match_bar import LifeState
    from tools.topbar_preview_support import load_progress_renderer
    Progress = load_progress_renderer(QtCore, QtGui)


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable; no native composition verified")
class MinecraftFusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.methods = production_methods("rm_client/ui/polar_app.py", "PolarRMWindow",
            {"minecraft_hud_active", "combat_hud_preset", "paint_hud_motion_overlay"})
        cls.elim = production_methods("rm_client/ui/polar/mixins/video_backend_mixin.py", "VideoBackendMixin",
            {"draw_elimination_fx"})["draw_elimination_fx"]

    def setUp(self):
        registry = build_default_registry()
        registry.get("MinecraftCombatHUD").enabled = True
        registry.get("EliminationFX").enabled = True
        registry.get("ArmorAutoAim").enabled = False
        registry.get("EnergyAutoAim").enabled = False
        state = RobotState()
        state.match_mode, state.alliance_color, state.robot_id = "RMUC7v7", "Blue", 103
        self.hud_scale = 1.0
        self.dpr = 1
        owner = NS(registry=registry, state=state, home_visible=False,
            hero_deploy_ui=NS(active=False), overlay_coordinator=OverlayCoordinator(),
            backend=NS(mqtt=NS(host="offline-fixture", port=3333, disconnected_at=0.0,
                connected=True, receive_generation=0), scenario_key="OfficialEvent",
                referee=NS(profile_id="rm2026-v1.3.1")),
            dynamic_island_state=NS(x=490, y=17, width=300, height=30),
            gui_motion=NS(now=10.0), student_ui=NS(visible=False, panel=""),
            minecraft_hud=MinecraftCombatHudRenderer(ROOT / "assets/minecraft_hud"),
            _last_minecraft_hud_layout=None, _vision_source="Mock",
            menu_overlay_active=lambda: False, interpolated_vision_result=lambda now: None,
            tactical_map_rect=lambda w, h: QtCore.QRectF(12, 58, 170, 118),
            get_hud_scale=lambda w, h: self.hud_scale, devicePixelRatioF=lambda: self.dpr,
            setting_bool=lambda mod, key, default=False: bool(mod.get_setting(key).value) if mod and mod.get_setting(key) else default,
            setting_mode=lambda mod, key, default: str(mod.get_setting(key).value) if mod and mod.get_setting(key) else default,
            get_setting_number=lambda mod, key, default: float(mod.get_setting(key).value) if mod and mod.get_setting(key) else default,
            alliance_side=lambda: "Blue", dynamic_island_bottom_anchor=lambda w,h: 47,
            elimination_element_toggles=lambda effect: {"match_progress": True, "hit_info": True},
            kill_fx=NS(match_progress=Progress(), draw=Mock()))
        self.owner = owner
        for name in ("minecraft_hud_active", "combat_hud_preset"):
            setattr(owner, name, self.methods[name].__get__(owner))
        owner.draw_elimination_fx = type(self).elim.__get__(owner)
        for name in ("draw_watermark", "paint_combat_target_overlay", "draw_dynamic_island",
                     "draw_tactical_map_hud", "draw_buff_timeline_hud", "draw_minecraft_module_list",
                     "draw_module_list_hud", "draw_keybinds_strip", "draw_chassis_gimbal_indicator",
                     "draw_telemetry_strip", "draw_student_status", "draw_match_chat",
                     "draw_quick_action_wheel", "draw_hero_deploy_interface"):
            setattr(owner, name, Mock())
        owner.top_match_bar = self.controller = TopMatchBarController(owner)
        self.assertTrue(owner.minecraft_hud.available)

    def draw(self, width=1280, height=720, include_map=None):
        image = QtGui.QImage(round(width*self.dpr), round(height*self.dpr), QtGui.QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.dpr)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        try:
            self.methods["paint_hud_motion_overlay"](self.owner, painter, width, height, include_map=include_map)
        finally:
            painter.end()
        self.assertEqual(self.controller._last_error, "")
        return image

    def screen_rect(self, rect):
        if isinstance(rect, QtCore.QRectF):
            return QtCore.QRectF(rect.x()*self.hud_scale, rect.y()*self.hud_scale,
                                 rect.width()*self.hud_scale, rect.height()*self.hud_scale)
        return QtCore.QRectF(rect.x*self.hud_scale, rect.y*self.hud_scale,
                             rect.width*self.hud_scale, rect.height*self.hud_scale)

    def assert_drawn(self, image, rect):
        crop = image.copy(round(rect.x()*self.dpr), round(rect.y()*self.dpr),
                          max(1,round(rect.width()*self.dpr)), max(1,round(rect.height()*self.dpr)))
        self.assertTrue(any(crop.pixelColor(x,y).alpha() for x in range(crop.width()) for y in range(crop.height())))

    def test_production_dispatch_draws_mc_cs_and_progress_once(self):
        with patch.object(self.owner.kill_fx.match_progress, "draw", wraps=self.owner.kill_fx.match_progress.draw) as progress:
            image = self.draw()
        self.assertEqual(progress.call_count, 1)
        self.assertFalse(self.owner.kill_fx.draw.call_args.kwargs["element_toggles"]["match_progress"])
        self.assertTrue(self.owner.kill_fx.draw.call_args.kwargs["element_toggles"]["hit_info"])
        mc = self.owner._last_minecraft_hud_layout
        cs = self.controller.last_layout
        self.assertIsNotNone(cs)
        self.assertEqual(len(cs.left_cards), 6)
        for rect in (mc.hotbar, mc.hearts[0], mc.armor[0], mc.scoreboard,
                     self.screen_rect(cs.bounds), self.screen_rect(self.controller.last_progress_bounds)):
            self.assert_drawn(image, rect)
        self.owner.draw_chassis_gimbal_indicator.assert_not_called()
        self.owner.draw_telemetry_strip.assert_not_called()

    def test_actual_activation_precedence_and_saved_config_need_no_migration(self):
        for module_on, preset, expected in ((True,"Polar",True),(False,"Minecraft 1.21.11",True),
                                          (True,"Minecraft 1.21.11",True),(False,"Polar",False)):
            apply_registry_config(self.owner.registry, {"version":1,"modules":{
                "MinecraftCombatHUD":{"enabled":module_on},
                "HUD":{"settings":{"Combat Preset":preset}}, "TopMatchBar":{"enabled":True}}})
            self.assertEqual(self.owner.registry.get("HUD").get_setting("Combat Preset").value, preset)
            self.assertEqual(self.owner.minecraft_hud_active(), expected)
            self.draw()
            self.assertIsNotNone(self.controller.last_layout)
            self.assertEqual(self.owner._last_minecraft_hud_layout is not None, expected)
            self.assertTrue(self.controller.owns_progress())

    def test_real_combined_bounds_resolution_dpi_scale_and_bossbar_modes(self):
        for width,height,scale in ((800,600,.8),(1000,620,1.0),(1280,720,1.0),(1920,1080,1.2),(2560,1440,1.34)):
            for dpr in (1,2):
                for island in (False,True):
                    with self.subTest(width=width,hud_scale=scale,dpr=dpr,island=island):
                        self.hud_scale,self.dpr = scale,dpr
                        self.owner.registry.get("HUD").get_setting("Dynamic Island").value=island
                        self.draw(width,height)
                        mc=self.owner._last_minecraft_hud_layout
                        cs=self.controller.last_layout
                        self.assertIsNotNone(cs)
                        rects=(self.screen_rect(cs.bounds), self.screen_rect(self.controller.last_progress_bounds))
                        for rect in rects:
                            self.assertTrue(QtCore.QRectF(0,0,width,height).contains(rect))
                            self.assertFalse(rect.intersects(mc.scoreboard))
                            self.assertFalse(rect.intersects(mc.hotbar))
                            self.assertFalse(rect.intersects(self.screen_rect(self.owner.tactical_map_rect(width/scale,height/scale))))
                            if not island:
                                for boss in mc.boss_bars:
                                    self.assertFalse(rect.intersects(boss.adjusted(0,-9*mc.scale,0,0)))
                            else:
                                self.assertGreaterEqual(rect.top(),47*scale+8*scale)
                        self.assertGreater(self.controller.last_progress_bounds.top(), cs.bounds.bottom)
                        self.assertAlmostEqual(cs.center.x+cs.center.width/2, int(width/scale)/2)

    def test_lower_map_uses_final_bossbar_shifted_top(self):
        self.owner.registry.get("HUD").get_setting("Dynamic Island").value=False
        self.owner.tactical_map_rect=lambda w,h: QtCore.QRectF(12,200,400,110)
        self.draw()
        self.assertIsNotNone(self.controller.last_layout)
        map_rect=self.owner.tactical_map_rect(1280,720)
        self.assertFalse(self.screen_rect(self.controller.last_layout.bounds).intersects(map_rect))
        self.assertFalse(self.screen_rect(self.controller.last_progress_bounds).intersects(map_rect))

    def test_map_off_reserves_actual_mc_effect_tiles(self):
        self.owner.registry.get("TacticalMap").enabled=False
        self.owner.registry.get("HUD").get_setting("Dynamic Island").value=False
        self.draw()
        mc=self.owner._last_minecraft_hud_layout
        effects=QtCore.QRectF(mc.effects_origin.x(),mc.effects_origin.y(),154*mc.scale,24*mc.scale)
        self.assertIsNotNone(self.controller.last_layout)
        self.assertFalse(self.screen_rect(self.controller.last_layout.bounds).intersects(effects))
        self.assertFalse(self.screen_rect(self.controller.last_progress_bounds).intersects(effects))

    def test_unknown_state_remains_unknown_in_fused_frame(self):
        self.draw()
        frame=self.controller.feed.snapshot(10)
        self.assertTrue(all(c.life==LifeState.UNKNOWN and c.health is None for team in (frame.left,frame.right) for c in team.cards))
        self.assertIsNone(frame.own_base_health)
        self.assertEqual(self.owner.kill_fx.match_progress.shown_own,0)

    def test_rmul_default_and_opt_out_remain_unchanged(self):
        self.owner.state.match_mode="RMUL3v3"
        self.draw()
        self.assertIsNotNone(self.owner._last_minecraft_hud_layout)
        self.assertIsNone(self.controller.last_layout)
        self.assertFalse(self.controller.owns_progress())
        self.assertTrue(self.owner.kill_fx.draw.call_args.kwargs["element_toggles"]["match_progress"])
        self.owner.state.match_mode="RMUC7v7"
        self.owner.registry.get("TopMatchBar").enabled=False
        self.draw()
        self.assertIsNone(self.controller.last_layout)
        self.assertFalse(self.controller.owns_progress())

    def test_repeated_toggle_keeps_mc_cache_and_clears_old_geometry(self):
        self.draw()
        builds=self.owner.minecraft_hud.layer_rebuilds
        self.draw()
        self.assertEqual(self.owner.minecraft_hud.layer_rebuilds,builds)
        self.owner.registry.get("MinecraftCombatHUD").enabled=False
        self.draw()
        self.assertIsNone(self.owner._last_minecraft_hud_layout)
        self.owner.registry.get("MinecraftCombatHUD").enabled=True
        self.draw()
        self.assertIsNotNone(self.owner._last_minecraft_hud_layout)
        self.assertEqual(self.owner.minecraft_hud.layer_rebuilds,builds)

    def test_hidden_tab_menu_and_large_map_never_leak_a_legacy_strip(self):
        self.draw()
        self.owner.student_ui.visible=True
        self.owner.student_ui.panel="damage"
        self.draw()
        self.assertIsNone(self.controller.last_layout)
        self.assertIsNone(self.controller.last_progress_bounds)
        self.assertTrue(self.controller.owns_progress())
        self.assertFalse(self.owner.kill_fx.draw.call_args.kwargs["element_toggles"]["match_progress"])
        self.owner.student_ui.visible=False
        self.owner.menu_overlay_active=lambda: True
        self.draw()
        self.assertIsNone(self.controller.last_layout)
        self.owner.menu_overlay_active=lambda: False
        self.owner.tactical_map_rect=lambda w,h: QtCore.QRectF(12,58,800,600)
        self.draw()
        self.assertIsNone(self.controller.last_layout)
        self.assertIsNone(self.controller.last_progress_bounds)
        self.assertTrue(self.controller.owns_progress())

    def test_mc_module_list_uses_right_reservation_without_polar_left_penalty(self):
        self.owner.registry.get("TacticalMap").enabled=False
        self.owner.registry.get("MinecraftCombatHUD").get_setting("Scale Multiplier").value=.5
        hud=self.owner.registry.get("HUD")
        hud.get_setting("ModuleList Style").value="PolarTextList"
        for enabled in (False,True):
            hud.get_setting("Module List").value=enabled
            self.draw()
            self.assertIsNotNone(self.controller.last_layout)
            self.assertLess(self.controller.last_layout.bounds.x,288)
            if enabled:
                self.assertGreaterEqual(self.controller.last_layout.bounds.x,270)

    def test_no_space_hides_both_strips_without_releasing_ownership(self):
        self.draw(520,340)
        self.assertIsNone(self.controller.last_layout)
        self.assertIsNone(self.controller.last_progress_bounds)
        self.assertTrue(self.controller.owns_progress())
        self.assertFalse(self.owner.kill_fx.draw.call_args.kwargs["element_toggles"]["match_progress"])
        self.draw()
        self.assertIsNotNone(self.controller.last_layout)
        self.assertIsNotNone(self.controller.last_progress_bounds)

    def test_extreme_user_scales_stay_bounded_or_hide_safely(self):
        for scale in (.55,.6,1,2,2.4):
            for multiplier in (.5,1,2):
                for island in (False,True):
                    with self.subTest(scale=scale,multiplier=multiplier,island=island):
                        self.hud_scale=scale
                        self.owner.registry.get("MinecraftCombatHUD").get_setting("Scale Multiplier").value=multiplier
                        self.owner.registry.get("HUD").get_setting("Dynamic Island").value=island
                        self.draw()
                        self.assertTrue(self.controller.owns_progress())
                        mc=self.owner._last_minecraft_hud_layout
                        if self.controller.last_layout is None:
                            self.assertIsNone(self.controller.last_progress_bounds)
                            continue
                        for rect in (self.screen_rect(self.controller.last_layout.bounds), self.screen_rect(self.controller.last_progress_bounds)):
                            self.assertTrue(QtCore.QRectF(0,0,1280,720).contains(rect))
                            self.assertFalse(rect.intersects(mc.scoreboard))
                            self.assertFalse(rect.intersects(mc.hotbar))
                            if not island:
                                self.assertGreaterEqual(rect.top()+1e-7,max(b.bottom() for b in mc.boss_bars)+8*scale)

    def test_island_resize_clamps_eased_progress_inside_reserved_band(self):
        self.owner.dynamic_island_state.height=150
        self.draw(1920,1080)
        self.owner.dynamic_island_state.height=30
        self.draw(1000,620)
        self.assertIsNotNone(self.controller.last_progress_bounds)
        self.assertLessEqual(self.controller.last_progress_bounds.bottom(),620*.48)
        self.assertFalse(self.screen_rect(self.controller.last_progress_bounds).intersects(self.owner._last_minecraft_hud_layout.scoreboard))


if __name__ == "__main__":
    unittest.main()
