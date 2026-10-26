"""Wiki 的完整模块可达性、原控件写入与模态输入回归。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
import json
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QFontMetricsF, QImage, QInputMethodEvent, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from test_clickgui_background_dismiss import Host as InputHost, APP
from rm_client.model import CATEGORIES
from rm_client.ui.endfield.wiki import EndfieldWikiRenderer
from rm_client.ui.endfield.wiki import EndfieldWikiState
from rm_client.ui.endfield.wiki.query import wiki_modules
from rm_client.ui.endfield.wiki.motion import sample_keys
from rm_client.ui.clickgui_gpu import ClickGuiDrawList, ClickGuiGpuRenderer


class Host(InputHost):
    def __init__(self):
        super().__init__()
        self.resize(1280, 720)
        self.search_query = ""
        self._startup_last_hover_action = ""
        self.jello_state = EndfieldWikiState()
        self.jello_state.page_time = 1.0
        self.now = 100.0
        self.jello_state.clock = lambda: self.now
        self.renderer = EndfieldWikiRenderer(ROOT / "rm_client/ui/endfield/wiki/assets", ROOT / "assets/jello")
        self.renderer.clock = lambda: self.now

    def settle(self):
        self.now += 1.0
        self.jello_state.update(1.0)

    def add_hotspot(self, rect, action, payload=None, button=None, tooltip=""):
        super().add_hotspot(rect,action,payload,button,tooltip)
        self.hotspots[-1].tooltip = tooltip

    def build(self):
        # 普通可达性测试使用稳定帧；中间帧测试直接使用可控时钟构建。
        for _ in range(2):
            self.settle()
            super().build()


class WikiTests(unittest.TestCase):
    def setUp(self):
        self.w = Host()
        self.w.build()

    def tearDown(self):
        self.w.hide()
        self.w.deleteLater()
        APP.processEvents()

    def activate(self, action, payload=None):
        self.w.build()
        target = next(h for h in self.w.hotspots if h.action == action
                      and (payload is None or h.payload == payload))
        self.w.dispatch(target.action, target.payload, target.rect.center(), 1, target.rect)
        self.w.settle()

    def render_at(self, delta=0):
        self.w.now += delta
        self.w.jello_state.advance_visuals()
        self.w.hotspots = []
        self.w.gui_scroll_viewports = []
        return self.w.renderer.build(self.w, self.w.jello_state, self.w.width(), self.w.height(), 1)

    def test_page_exit_precedes_category_entry_and_back_uses_source_motion(self):
        self.w.dispatch("wiki_category", "Movement", QPointF(), 1, self.w.rect())
        commands = self.render_at(.08)
        self.assertEqual(self.w.jello_state.category, "Movement")
        self.assertFalse(any(t.text == "小陀螺" for t in commands.texts))
        self.assertTrue(all(h.action == "jello_noop" for h in self.w.hotspots))
        commands = self.render_at(.17)
        title = next(t for t in commands.texts if t.text == "小陀螺" and t.font.pointSizeF() > 25)
        self.assertGreater(title.rect.left(), 515 * self.w.renderer.s)
        self.assertLess(title.color.alphaF(), .99)
        self.render_at(.6)
        self.w.dispatch("wiki_back", None, QPointF(), 1, self.w.rect())
        commands = self.render_at(.08)
        self.assertTrue(any(t.text == "小陀螺" for t in commands.texts))
        self.assertTrue(all(h.action == "jello_noop" for h in self.w.hotspots))
        self.render_at(.8)
        self.assertEqual([h.payload for h in self.w.hotspots if h.action == "wiki_category"], CATEGORIES)

    def test_directory_hover_uses_animator_darkening_and_selection_delayed_reveal(self):
        self.activate("wiki_category", "Movement")
        self.w.build()
        target = next(h for h in self.w.hotspots if h.action == "jello_open_settings" and h.payload == "ChassisAssist")
        self.w.hover_point = target.rect.center()
        commands = self.render_at()
        row = next(r for r in commands.rects if r.rect == target.rect)
        self.assertAlmostEqual(row.fill.redF(), .62, places=3)
        self.assertAlmostEqual(row.fill.alphaF(), 1, places=3)
        self.w.hover_point = QPointF(-1, -1)
        self.render_at()
        commands = self.render_at(.05)
        row = next(r for r in commands.rects if r.rect == target.rect)
        self.assertAlmostEqual(row.fill.redF(), (.62 + .698) / 2, places=3)
        self.w.dispatch("jello_open_settings", "ChassisAssist", target.rect.center(), 1, target.rect)
        selected = str(self.w.renderer.wiki_images[self.w.renderer.pack["module_icons"]["ChassisAssist"] + "_selected"])
        commands = self.render_at(.05)
        self.assertEqual(next(i for i in commands.images if i.source == selected).tint.alpha(), 0)
        commands = self.render_at(.24)
        icon = next(i for i in commands.images if i.source == selected)
        self.assertGreater(icon.tint.alphaF(), 0)
        self.assertLess(icon.tint.alphaF(), 1)
        before = self.w.jello_state.module_changed_at
        self.w.jello_state.dropdown_key = "ChassisAssist:Follow"
        self.w.dispatch("jello_open_settings", "ChassisAssist", QPointF(), 1, self.w.rect())
        self.assertEqual(self.w.jello_state.module_changed_at, before)
        self.assertEqual(self.w.jello_state.dropdown_key, "ChassisAssist:Follow")

    def test_module_switch_crossfades_without_large_slide_or_old_control_targets(self):
        self.activate("wiki_category", "Movement")
        old = self.w.registry.get("SpinMode")
        new = self.w.registry.get("AutoSpinOnHit")
        before = [(m.name, m.enabled, [s.value for s in m.settings]) for m in (old, new)]
        self.w.dispatch("jello_open_settings", new.name, QPointF(), 1, self.w.rect())
        commands = self.render_at(.08)
        old_title = next(t for t in commands.texts if t.text == "小陀螺" and t.font.pointSizeF() > 25)
        new_title = next(t for t in commands.texts if t.text == "受击自动小陀螺" and t.font.pointSizeF() > 25)
        self.assertGreater(old_title.color.alphaF(), 0)
        self.assertLess(old_title.color.alphaF(), 1)
        self.assertGreater(new_title.color.alphaF(), 0)
        self.assertLess(new_title.color.alphaF(), 1)
        self.assertGreaterEqual(new_title.rect.left() / self.w.renderer.s, 495)
        self.assertLess(new_title.rect.left() / self.w.renderer.s, 515)
        self.assertFalse(any(h.action in ("jello_module_press", "module_bind") and h.payload == old.name
                             for h in self.w.hotspots))
        self.assertFalse(any(h.payload is setting for h in self.w.hotspots for setting in old.settings))
        self.assertEqual([v["key"] for v in self.w.gui_scroll_viewports if v["mode"] == "jello_settings"], [new.name])
        commands = self.render_at(.26)
        self.assertFalse(any(t.text == "小陀螺" and t.font.pointSizeF() > 25 for t in commands.texts))
        title = next(t for t in commands.texts if t.text == "受击自动小陀螺" and t.font.pointSizeF() > 25)
        self.assertEqual(title.color.alpha(), 255)
        self.assertAlmostEqual(title.rect.left() / self.w.renderer.s, 515)
        self.assertEqual(before, [(m.name, m.enabled, [s.value for s in m.settings]) for m in (old, new)])

    def test_rapid_module_selection_keeps_fading_source_and_latest_settings(self):
        self.activate("wiki_category", "Movement")
        self.w.dispatch("jello_open_settings", "AutoSpinOnHit", QPointF(), 1, self.w.rect())
        self.render_at(.06)
        started = self.w.jello_state.module_changed_at
        self.w.dispatch("jello_open_settings", "ChassisAssist", QPointF(), 1, self.w.rect())
        commands = self.render_at(.02)
        self.assertEqual(self.w.jello_state.module_from, "SpinMode")
        self.assertEqual(self.w.jello_state.module_changed_at, started)
        self.assertFalse(any(t.text == "受击自动小陀螺" and t.font.pointSizeF() > 25 for t in commands.texts))
        self.render_at(.26)
        self.assertEqual(self.w.jello_state.settings_module, "ChassisAssist")
        self.assertEqual([v["key"] for v in self.w.gui_scroll_viewports if v["mode"] == "jello_settings"], ["ChassisAssist"])
        self.w.dispatch("jello_open_settings", "PowerGuard", QPointF(), 1, self.w.rect())
        self.assertEqual(self.w.jello_state.module_from, "ChassisAssist")

    def test_search_frosts_current_page_and_restores_its_module_and_scroll(self):
        self.activate("wiki_category", "Movement")
        self.w.jello_state.panel_scroll["wiki:Movement"] = 0
        self.activate("wiki_search")
        commands = self.render_at(.5)
        self.assertIsNotNone(commands.frosted_background)
        self.assertTrue(any(t.text == "小陀螺" for t in commands.frosted_background.texts))
        self.assertTrue(any(t.text == "请输入文字" for t in commands.texts))
        self.assertFalse(any(h.action in ("setting_slider", "setting_toggle", "module_bind") for h in self.w.hotspots))
        field = next(h for h in self.w.hotspots if h.action == "wiki_search")
        self.assertAlmostEqual(field.rect.height() / self.w.renderer.s, 50 * .8)
        self.assertAlmostEqual(field.rect.width() / self.w.renderer.s, 498 * .8)
        self.w.dispatch("wiki_back", None, QPointF(), 1, self.w.rect())
        self.assertIsNotNone(self.render_at(.08).frosted_background)
        self.assertTrue(all(h.action == "jello_noop" for h in self.w.hotspots))
        self.assertIsNone(self.render_at(.15).frosted_background)
        self.assertEqual(self.w.jello_state.settings_module, "SpinMode")
        self.assertEqual(self.w.jello_state.panel_scroll["wiki:Movement"], 0)

    def test_search_detail_waits_for_exit_and_top_button_returns_one_level(self):
        self.activate("wiki_category", "Movement")
        self.w.build()
        self.assertFalse(any(h.action == "wiki_close" for h in self.w.hotspots))
        self.assertTrue(any(i.source == str(self.w.renderer.wiki_images["back"]) for i in self.w.renderer.commands.images))
        self.activate("wiki_search")
        self.w.search_query = "ArmorAutoAim"
        self.render_at(.5)
        self.w.dispatch("jello_open_settings", "ArmorAutoAim", QPointF(), 1, self.w.rect())
        self.assertEqual(self.w.jello_state.settings_module, "SpinMode")
        self.render_at(.08)
        self.assertEqual(self.w.jello_state.settings_module, "SpinMode")
        self.render_at(.15)
        self.assertEqual(self.w.jello_state.settings_module, "ArmorAutoAim")
        self.w.build()
        self.activate("wiki_back")
        self.w.build()
        self.assertTrue(any(h.action == "wiki_close" for h in self.w.hotspots))
        self.activate("wiki_close")
        self.assertFalse(self.w.gui_visible)

    def test_raster_fallback_blurs_page_and_keeps_foreground_text(self):
        self.activate("wiki_category", "Movement")
        self.activate("wiki_search")
        commands = self.render_at(.5)
        image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#ff00ff"))
        painter = QPainter(image)
        self.w.renderer.paint_commands_compat(painter, commands, 1280, 720)
        painter.end()
        self.assertNotEqual(image.pixelColor(10, 100), QColor("#ff00ff"))
        from rm_client.ui.clickgui_frost import raster_frost
        sharp = QImage(100, 60, QImage.Format.Format_ARGB32_Premultiplied)
        sharp.fill(QColor("black"))
        painter = QPainter(sharp)
        painter.fillRect(50, 0, 50, 60, QColor("white"))
        painter.end()
        blurred = raster_frost(sharp, 18)
        self.assertGreater(blurred.pixelColor(48, 30).red(), sharp.pixelColor(48, 30).red())

    def test_searching_current_module_closes_overlay_and_closing_cancels_pending_navigation(self):
        self.activate("wiki_category", "Movement")
        self.activate("wiki_search")
        self.w.search_query = "SpinMode"
        self.render_at(.5)
        self.w.dispatch("jello_open_settings", "SpinMode", QPointF(), 1, self.w.rect())
        commands = self.render_at(.2)
        self.assertIsNone(commands.frosted_background)
        self.assertEqual(self.w.search_query, "")
        self.activate("wiki_search")
        self.w.search_query = "ArmorAutoAim"
        self.w.dispatch("jello_open_settings", "ArmorAutoAim", QPointF(), 1, self.w.rect())
        self.assertIsNotNone(self.w.jello_state.search_on_closed)
        QTest.keyClick(self.w, Qt.Key.Key_F8)
        self.assertIsNone(self.w.jello_state.search_on_closed)
        self.w.settle()
        self.assertNotEqual(self.w.jello_state.settings_module, "ArmorAutoAim")
        self.assertFalse(self.w.gui_visible)

    def test_home_has_exactly_six_categories_and_no_module_toggles(self):
        self.assertEqual([h.payload for h in self.w.hotspots if h.action == "wiki_category"], CATEGORIES)
        self.assertFalse(any(h.action == "jello_module_press" for h in self.w.hotspots))

    def test_all_modules_reachable_through_categories_and_search(self):
        registry = self.w.registry
        reached = []
        for category in CATEGORIES:
            self.activate("wiki_category", category)
            modules = wiki_modules(registry, category, "")
            reached.extend(m.name for m in modules)
            for module in modules:
                self.w.dispatch("jello_open_settings", module.name, QPointF(), 1, self.w.rect())
                self.assertIs(self.w.selected_module, module)
                self.assertEqual(self.w.jello_state.settings_module, module.name)
                self.w.build()
                self.assertTrue(any(h.action == "module_bind" and h.payload == module.name
                                    for h in self.w.hotspots))
                self.assertTrue(any(h.action == "jello_module_press" and h.payload == module.name
                                    for h in self.w.hotspots))
                self.assertEqual(next(v for v in self.w.gui_scroll_viewports
                                      if v["mode"] == "jello_settings")["key"], module.name)
            self.activate("wiki_home")
        self.assertCountEqual(reached, [m.name for m in registry.modules])
        for module in registry.modules:
            self.assertIn(module, wiki_modules(registry, None, module.name))

    def test_all_setting_controls_survive_with_original_setting_identity(self):
        covered = set()
        for module in self.w.registry.modules:
            self.w.jello_state.category = module.category
            self.w.jello_state.open_settings(module.name)
            self.w.jello_state.settings_panel_animation.reset(1)
            for scroll in range(0, len(module.settings) * 78 + 500, 300):
                self.w.jello_state.settings_scroll[module.name] = scroll * (2 / 3)
                self.w.build()
                for hotspot in self.w.hotspots:
                    value = hotspot.payload
                    if hotspot.action in ("setting_toggle", "setting_slider"):
                        covered.add(id(value))
                    elif hotspot.action == "jello_mode_dropdown":
                        covered.add(id(value[1]))
                    elif hotspot.action == "config_action":
                        covered.update(id(s) for s in module.settings if s.kind == "action" and s.name == value)
                    elif hotspot.action == "jello_toggle_old_group":
                        covered.update(id(s) for s in module.settings if value == f"{module.name}:{s.name}")
                    elif hotspot.action == "wiki_copy_text":
                        covered.update(id(s) for s in module.settings if s.kind == "text" and s.value == value)
        missing = [(m.name, s.name, s.kind) for m in self.w.registry.modules
                   for s in m.settings if id(s) not in covered]
        self.assertEqual(missing, [])

    def test_back_tracks_search_then_category_split_then_home(self):
        self.activate("wiki_category", "Combat")
        self.activate("jello_open_settings", "ArmorAutoAim")
        self.w.search_focus = True
        self.w.search_query = "视觉"
        for expected in ("category", "root", "closed"):
            QTest.keyClick(self.w, Qt.Key.Key_Escape)
            self.w.settle()
            if expected == "category":
                self.assertFalse(self.w.search_focus)
                self.assertEqual(self.w.jello_state.settings_module, "ArmorAutoAim")
                self.assertEqual(self.w.jello_state.category, "Combat")
            elif expected == "root":
                self.assertIsNone(self.w.jello_state.settings_module)
                self.assertIsNone(self.w.jello_state.category)
                self.assertTrue(self.w.gui_visible)
            else:
                self.assertFalse(self.w.gui_visible)

    def test_category_shows_its_modules_on_left_and_selected_settings_on_right(self):
        before = [(m.enabled, [s.value for s in m.settings]) for m in self.w.registry.modules]
        self.activate("wiki_category", "Movement")
        self.assertEqual(self.w.jello_state.settings_module, "SpinMode")
        self.w.build()
        modules = wiki_modules(self.w.registry, "Movement", "")
        sidebar = next(v for v in self.w.gui_scroll_viewports if v["key"] == "wiki:Movement")
        entries = [h for h in self.w.hotspots if h.action == "jello_open_settings"
                   and sidebar["rect"].contains(h.rect.center())]
        self.assertEqual([h.payload for h in entries], [m.name for m in modules])
        self.assertEqual([h.payload for h in self.w.hotspots if h.action == "wiki_category"], [])
        self.activate("jello_open_settings", "ChassisAssist")
        self.w.build()
        settings = next(v for v in self.w.gui_scroll_viewports if v["mode"] == "jello_settings")
        self.assertEqual(settings["key"], "ChassisAssist")
        self.assertGreater(settings["rect"].left(), sidebar["rect"].right())
        self.assertEqual(before, [(m.enabled, [s.value for s in m.settings]) for m in self.w.registry.modules])
        self.activate("wiki_home")
        self.activate("wiki_category", "Movement")
        self.assertEqual(self.w.jello_state.settings_module, "ChassisAssist")

    def test_keyboard_changes_module_in_place_and_reveals_scrolled_selection(self):
        self.activate("wiki_category", "System")
        modules = wiki_modules(self.w.registry, "System", "")
        for _ in range(len(modules) - 1):
            QTest.keyClick(self.w, Qt.Key.Key_Down)
        self.assertEqual(self.w.jello_state.settings_module, modules[-1].name)
        self.w.build()
        sidebar = next(v for v in self.w.gui_scroll_viewports if v["key"] == "wiki:System")
        self.assertGreater(self.w.jello_state.panel_scroll["wiki:System"], 0)
        selected = next(h for h in self.w.hotspots if h.action == "jello_open_settings"
                        and h.payload == modules[-1].name and sidebar["rect"].contains(h.rect.center()))
        self.assertTrue(sidebar["rect"].contains(selected.rect))
        # 左侧滚回顶部仍保留右侧模块及其设置滚动位置。
        self.w.jello_state.panel_scroll["wiki:System"] = 0
        self.w.build()
        self.assertEqual(self.w.jello_state.panel_scroll["wiki:System"], 0)
        self.assertEqual(self.w.jello_state.settings_module, modules[-1].name)
        QTest.keyClick(self.w, Qt.Key.Key_Escape)
        self.assertIsNone(self.w.jello_state.category)

    def test_home_keyboard_enters_category_with_settings_immediately(self):
        QTest.keyClick(self.w, Qt.Key.Key_Right)
        QTest.keyClick(self.w, Qt.Key.Key_Return)
        self.w.settle()
        self.assertEqual(self.w.jello_state.category, CATEGORIES[0])
        self.assertEqual(self.w.jello_state.settings_module,
                         wiki_modules(self.w.registry, CATEGORIES[0], "")[0].name)

    def test_native_menu_shortcuts_enter_same_category_with_back_button(self):
        for action, name in ((9, "TacticalMap"), (12, "MatchReadiness"), (13, "HUD"),
                             (15, "MinecraftCombatHUD"), (16, "AudioFeedback"), (17, "CameraFeed"),
                             (18, "MatchTimer"), (20, "Scenario")):
            self.w.set_clickgui_visible(False, announce=False)
            self.w.dispatch_endfield_action(action)
            self.w.build()
            self.assertEqual(self.w.jello_state.settings_module, name)
            self.assertEqual(self.w.jello_state.category, self.w.registry.get(name).category)
            self.assertTrue(any(h.action == "wiki_back" for h in self.w.hotspots))
            self.assertFalse(any(h.action == "wiki_close" for h in self.w.hotspots))
            self.activate("wiki_back")
            self.w.build()
            self.assertIsNone(self.w.jello_state.category)
            self.assertIsNone(self.w.jello_state.settings_module)

    def test_launcher_config_shortcut_sets_system_navigation_and_keeps_original_module(self):
        self.w.set_clickgui_visible(False, announce=False)
        self.w.home_visible = True
        self.w.reject_pending_configuration_edit = Mock(return_value=False)
        self.w.capture_pending_scenario_configuration = Mock()
        self.w.scenario_manager = SimpleNamespace(current=SimpleNamespace(key="preview"))
        self.w.dispatch("startup_open_config", None, QPointF(), 1, self.w.rect())
        self.w.build()
        self.assertFalse(self.w.home_visible)
        self.assertIs(self.w.selected_module, self.w.registry.get("ConfigManager"))
        self.assertEqual(self.w.jello_state.category, "System")
        self.assertTrue(any(h.action == "wiki_back" for h in self.w.hotspots))
        self.assertFalse(any(h.action == "wiki_close" for h in self.w.hotspots))

    def test_reselecting_module_repairs_missing_category_context(self):
        self.w.jello_state.open_settings("SpinMode")
        self.assertIsNone(self.w.jello_state.category)
        self.w.dispatch("jello_open_settings", "SpinMode", QPointF(), 1, self.w.rect())
        self.w.build()
        self.assertEqual(self.w.jello_state.category, "Movement")
        self.assertTrue(any(h.action == "wiki_back" for h in self.w.hotspots))

    def test_root_close_opens_escape_and_consumes_the_mouse_release(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_close")
        QTest.mouseClick(self.w, Qt.MouseButton.LeftButton, pos=target.rect.center().toPoint())
        self.assertFalse(self.w.gui_visible)
        self.assertTrue(self.w.escape_menu_visible)
        self.assertFalse(self.w.home_visible)
        self.w.control.set_mouse_button.assert_not_called()
        self.w.backend.shutdown.assert_not_called()

    def test_hover_hides_plain_gray_icon_on_first_frame_without_duplicate_overlay(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        self.w.hover_point = target.rect.center()
        image = str(self.w.renderer.wiki_images[target.payload])
        for delta in (0, .001, .016, .033, .05, .1, .2, .3):
            commands = self.render_at(delta)
            plain = [i for i in commands.images if i.source == image]
            self.assertEqual(len(plain), 1)
            self.assertEqual(plain[0].tint.alpha(), 0)
        self.w.hover_point = QPointF(0, 0)
        self.render_at()
        restored = self.render_at(.2)
        self.assertGreater(next(i for i in restored.images if i.source == image).tint.alpha(), 0)

    def test_category_drag_scrolls_vertically_without_selecting_or_toggling(self):
        self.activate("wiki_category", "System")
        self.w.build()
        viewport = next(v for v in self.w.gui_scroll_viewports if v["key"] == "wiki:System")
        old = self.w.jello_state.settings_module
        before = [m.enabled for m in self.w.registry.modules]
        row = next(h for h in self.w.hotspots if h.action == "jello_open_settings" and h.payload != old)
        start = row.rect.center().toPoint()
        QTest.mousePress(self.w,Qt.MouseButton.LeftButton,pos=start)
        self.assertEqual(self.w.jello_state.settings_module,old)
        self.w.now += .05
        from PySide6.QtGui import QMouseEvent
        destination = QPointF(start.x(),start.y()-90)
        APP.sendEvent(self.w,QMouseEvent(QMouseEvent.Type.MouseMove,destination,QPointF(self.w.mapToGlobal(destination.toPoint())),
                      Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(self.w,Qt.MouseButton.LeftButton,pos=destination.toPoint())
        self.assertAlmostEqual(self.w.jello_state.panel_scroll["wiki:System"],90)
        self.assertEqual(self.w.jello_state.settings_module,old)
        self.assertEqual([m.enabled for m in self.w.registry.modules],before)
        self.render_at(.1)
        self.assertGreater(self.w.jello_state.panel_scroll["wiki:System"],90)
        self.w.control.set_mouse_button.assert_not_called()
        self.w.control.add_mouse_motion.assert_not_called()

    def test_category_soft_mask_has_translucent_edge_bands_and_keeps_click_selection(self):
        self.activate("wiki_category", "System")
        self.w.build()
        viewport = next(v for v in self.w.gui_scroll_viewports if v["key"] == "wiki:System")
        edges = [c for c in self.w.renderer.commands.commands if c.payload.clip is not None
                 and c.payload.clip.top() == viewport["rect"].top() and c.opacity < 1]
        self.assertTrue(edges)
        self.assertTrue(any(0 < c.opacity < .2 for c in edges))
        row = next(h for h in self.w.hotspots if h.action == "jello_open_settings"
                   and h.payload != self.w.jello_state.settings_module)
        QTest.mouseClick(self.w,Qt.MouseButton.LeftButton,pos=row.rect.center().toPoint())
        self.assertEqual(self.w.jello_state.settings_module,row.payload)

    def test_drag_past_both_edges_has_resistance_and_returns_without_selection(self):
        from PySide6.QtGui import QMouseEvent
        from rm_client.ui.endfield.wiki.scroll import edge_offset
        self.activate("wiki_category","System")
        self.w.build()
        state = self.w.jello_state
        selected = state.settings_module
        viewport = next(v for v in self.w.gui_scroll_viewports if v["key"]=="wiki:System")
        for boundary,direction in ((0,1),(viewport["maximum"],-1)):
            state.panel_scroll["wiki:System"] = boundary
            self.render_at()
            start = viewport["rect"].center().toPoint()
            end = QPointF(start.x(),start.y()+150*direction)
            QTest.mousePress(self.w,Qt.MouseButton.LeftButton,pos=start)
            self.w.now += .05
            APP.sendEvent(self.w,QMouseEvent(QMouseEvent.Type.MouseMove,end,QPointF(self.w.mapToGlobal(end.toPoint())),
                          Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
            self.assertAlmostEqual(state.panel_scroll["wiki:System"],boundary)
            pulled = edge_offset(state,"wiki:System")
            self.assertLess(pulled*direction,0)
            self.assertLess(abs(pulled),150)
            commands = self.render_at()
            self.assertTrue(commands.images)
            QTest.mouseRelease(self.w,Qt.MouseButton.LeftButton,pos=end.toPoint())
            self.render_at(.1)
            self.assertLess(abs(edge_offset(state,"wiki:System")),abs(pulled))
            self.render_at(.7)
            self.assertEqual(edge_offset(state,"wiki:System"),0)
            self.assertEqual(state.settings_module,selected)
            self.assertAlmostEqual(state.panel_scroll["wiki:System"],boundary)
        self.w.control.set_mouse_button.assert_not_called()

    def test_wheel_boundary_feedback_applies_to_directory_and_original_settings(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QWheelEvent
        from rm_client.ui.endfield.wiki.scroll import edge_offset
        self.activate("wiki_category","System")
        self.w.build()
        viewport = next(v for v in self.w.gui_scroll_viewports if v["key"]=="wiki:System")
        point = viewport["rect"].center()
        event = QWheelEvent(point,point,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        self.w.wheelEvent(event)
        self.assertLess(edge_offset(self.w.jello_state,"wiki:System"),0)
        self.assertEqual(self.w.jello_state.panel_scroll["wiki:System"],0)
        self.render_at(.8)
        self.assertEqual(edge_offset(self.w.jello_state,"wiki:System"),0)
        module = max(self.w.registry.modules,key=lambda m:len(m.settings))
        self.w.dispatch("jello_open_settings",module.name,QPointF(),1,self.w.rect())
        self.w.build()
        viewport = next(v for v in self.w.gui_scroll_viewports if v["key"]==module.name and v["mode"]=="jello_settings")
        self.assertGreater(viewport["maximum"],0)
        point = viewport["rect"].center()
        self.w.wheelEvent(QWheelEvent(point,point,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False))
        self.assertLess(edge_offset(self.w.jello_state,module.name),0)
        self.w.control.add_wheel.assert_not_called()

    def test_background_text_and_ground_frames_flow_on_their_source_clock(self):
        layers = self.w.renderer.pack["layers"]
        text = next(n for n in layers["frame"]["children"] if n.get("uv_scroll"))
        self.assertAlmostEqual(text["uv_scroll"][1],-.1,places=6)
        self.assertEqual(layers["ground"]["instance_transform"]["m_LocalPosition"]["y"],-1.600000023841858)
        self.w.jello_state.session_time = 3
        first = self.render_at()
        self.w.jello_state.session_time = 3.06
        second = self.render_at()
        source = str(self.w.renderer.wiki_images[text["image"]])
        self.assertNotEqual([i.rect for i in first.images if i.source==source],[i.rect for i in second.images if i.source==source])
        self.assertLess(len([i for i in second.images if Path(i.source).parent.name=="waves"]),4)
        self.assertNotEqual((self.w.renderer.wiki_root/"waves/000.png").read_bytes(),
                            (self.w.renderer.wiki_root/"waves/040.png").read_bytes())

    def test_home_text_stream_is_removed_on_group_page_and_restored_on_return(self):
        text = next(n for n in self.w.renderer.pack["layers"]["frame"]["children"] if n.get("uv_scroll"))
        source = str(self.w.renderer.wiki_images[text["image"]])
        self.assertTrue(any(i.source==source for i in self.render_at().images))
        self.activate("wiki_category","Movement")
        self.assertFalse(any(i.source==source for i in self.render_at().images))
        self.activate("wiki_home")
        self.assertTrue(any(i.source==source for i in self.render_at().images))

    def test_large_viewport_scales_whole_canvas_and_hotspots_without_one_x_cap(self):
        for width,height in ((1280,720),(1920,1080),(2560,1440),(3840,2160)):
            self.w.resize(width,height)
            self.render_at()
            renderer = self.w.renderer
            self.assertAlmostEqual(renderer.s,width/1920)
            self.assertAlmostEqual(renderer.ox,0)
            self.assertAlmostEqual(renderer.oy,0)
            targets = [h.rect for h in self.w.hotspots if h.action=="wiki_category"]
            self.assertEqual(len(targets),6)
            self.assertTrue(all(self.w.rect().contains(r.toRect()) for r in targets))

    def test_radial_background_uses_two_source_arcs_with_empty_remainder(self):
        ring = next(n for n in self.w.renderer.pack["background_nodes"]["children"] if n["path"].endswith("/DecoDecoRing"))
        for node,amount in ((ring,.25),(ring["children"][0],.12)):
            self.assertAlmostEqual(node["radial_fill"]["amount"],amount,places=6)
            image = QImage(str(self.w.renderer.wiki_images[node["image"]]))
            # 原起点在下方，顺时针到左侧；右上四分之一应透明。
            self.assertEqual(image.pixelColor(round(image.width()*.85),round(image.height()*.15)).alpha(),0)
            self.assertIsNotNone(image.createAlphaMask())

    def test_search_result_selection_and_hover_share_group_colors_and_radius(self):
        self.activate("wiki_search")
        self.w.search_query = "小陀螺"
        self.render_at()
        commands = self.render_at(1)
        renderer = self.w.renderer
        targets = [h for h in self.w.hotspots if h.action=="wiki_search_select"]
        self.assertGreaterEqual(len(targets),2)
        def surface(commands,target):
            return next(r for r in commands.rects if r.rect==target.rect and r.radius>0 and r.fill.alphaF()>.001)
        chosen,normal = (surface(commands,t) for t in targets[:2])
        self.assertAlmostEqual(chosen.fill.redF(),renderer.pack["tab_button"]["states"]["Normal"]["selected_bg"][0],places=3)
        self.assertEqual(chosen.radius,4*renderer.s)
        self.w.hover_point = targets[1].rect.center()
        hovered = surface(self.render_at(),targets[1])
        self.assertLess(hovered.fill.red(),normal.fill.red())
        self.assertAlmostEqual(hovered.fill.redF(),renderer.pack["tab_button"]["states"]["Highlighted"]["normal_bg"][0],places=3)

    def test_search_click_release_keeps_hover_live_without_scrolling(self):
        self.activate("wiki_search")
        self.w.search_query = "小陀螺"
        self.render_at()
        self.render_at(1)
        rows = [h for h in self.w.hotspots if h.action=="wiki_search_select"]
        for target in (rows[1],rows[0],rows[1]):
            QTest.mouseClick(self.w,Qt.MouseButton.LeftButton,pos=target.rect.center().toPoint())
            self.assertFalse(self.w.pointer_interaction.background_release_owned)
            self.assertIsNone(self.w.pointer_interaction.drag)
            other = rows[0] if target is rows[1] else rows[1]
            point = other.rect.center()
            self.w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove,point,point,Qt.MouseButton.NoButton,
                                              Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
            self.assertEqual(self.w.hover_point,point)
            commands = self.render_at(.4)
            surface = next(r for r in commands.rects if r.rect==other.rect and r.radius>0)
            self.assertAlmostEqual(surface.fill.redF(),.62,places=3)
        self.assertEqual(self.w.jello_state.panel_scroll.get("wiki:search",0),0)
        self.w.control.set_mouse_button.assert_not_called()

    def test_search_switch_reuses_group_crossfade_and_only_latest_detail_target(self):
        self.activate("wiki_search")
        self.w.search_query = "小陀螺"
        self.render_at()
        self.render_at(1)
        previous_module = self.w.jello_state.settings_module
        self.w.dispatch("wiki_search_select","AutoSpinOnHit",QPointF(),1,self.w.rect())
        commands = self.render_at(.08)
        old = next(t for t in commands.texts if t.text=="小陀螺" and t.font.pointSizeF()>25)
        new = next(t for t in commands.texts if t.text=="受击自动小陀螺" and t.font.pointSizeF()>25)
        self.assertGreater(old.color.alphaF(),0)
        self.assertLess(old.color.alphaF(),1)
        self.assertGreater(new.color.alphaF(),0)
        self.assertLess(new.color.alphaF(),1)
        self.assertGreater(new.rect.left()/self.w.renderer.s,1090)
        self.assertLess(new.rect.left()/self.w.renderer.s,1110)
        self.assertEqual([h.payload for h in self.w.hotspots if h.action=="jello_open_settings"],["AutoSpinOnHit"])
        self.assertEqual(self.w.jello_state.settings_module,previous_module)
        commands = self.render_at(.3)
        self.assertFalse(any(t.text=="小陀螺" and t.font.pointSizeF()>25 for t in commands.texts))
        new = next(t for t in commands.texts if t.text=="受击自动小陀螺" and t.font.pointSizeF()>25)
        self.assertEqual(new.color.alpha(),255)
        self.assertAlmostEqual(new.rect.left()/self.w.renderer.s,1110)

    def test_search_keyboard_and_rapid_selection_share_clock_and_query_reset(self):
        self.activate("wiki_search")
        self.w.search_query = "小陀螺"
        self.render_at()
        self.render_at(1)
        self.w.dispatch("wiki_search_select","AutoSpinOnHit",QPointF(),1,self.w.rect())
        self.render_at(.06)
        state = self.w.jello_state
        started = state.search_changed_at
        QTest.keyClick(self.w,Qt.Key.Key_Down)
        self.assertEqual(state.search_selection,"RobotLink")
        self.assertEqual(state.search_from,"SpinMode")
        self.assertEqual(state.search_changed_at,started)
        commands = self.render_at(.02)
        self.assertFalse(any(t.text=="受击自动小陀螺" and t.font.pointSizeF()>25 for t in commands.texts))
        self.w.dispatch("wiki_search_select","RobotLink",QPointF(),1,self.w.rect())
        self.assertEqual(state.search_changed_at,started)
        self.w.search_query = "ChassisAssist"
        state.focus_index = -1
        commands = self.render_at(.02)
        self.assertIsNone(state.search_from)
        self.assertEqual(state.search_selection,"ChassisAssist")
        self.assertFalse(any(t.text=="小陀螺" and t.font.pointSizeF()>25 for t in commands.texts))

    def test_horizontal_drag_does_not_select_and_escape_cancels_pending_click(self):
        self.activate("wiki_category", "System")
        self.w.build()
        row = next(h for h in self.w.hotspots if h.action == "jello_open_settings"
                   and h.payload != self.w.jello_state.settings_module)
        old = self.w.jello_state.settings_module
        start = row.rect.center().toPoint()
        QTest.mousePress(self.w,Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseRelease(self.w,Qt.MouseButton.LeftButton,pos=start+QPointF(20,0).toPoint())
        self.assertEqual(self.w.jello_state.settings_module,old)
        self.assertEqual(self.w.jello_state.panel_scroll.get("wiki:System",0),0)
        QTest.mousePress(self.w,Qt.MouseButton.LeftButton,pos=start)
        QTest.keyClick(self.w,Qt.Key.Key_Escape)
        QTest.mouseRelease(self.w,Qt.MouseButton.LeftButton,pos=start)
        self.assertIsNone(self.w.jello_state.category)
        self.assertIsNone(self.w.pointer_interaction.drag)
        self.assertIsNone(self.w.jello_state.list_fling)
        self.w.control.set_mouse_button.assert_not_called()

    def test_recent_search_uses_source_title_and_three_column_history_grid(self):
        self.w.jello_state.search_history[:] = ["小陀螺","功率保护","战术地图"]
        self.activate("wiki_search")
        commands = self.render_at(.6)
        title = next(t for t in commands.texts if t.text == "最近搜索")
        self.assertLess(title.rect.left(),100*self.w.renderer.s)
        self.assertLess(title.rect.top(),160*self.w.renderer.s)
        cards = [h for h in self.w.hotspots if h.action == "wiki_history"]
        self.assertEqual(len(cards),3)
        self.assertEqual(len({round(h.rect.y(),2) for h in cards}),1)
        self.assertAlmostEqual(cards[0].rect.x(),99.2*self.w.renderer.s)
        self.assertAlmostEqual(cards[0].rect.width(),440.8*self.w.renderer.s)
        self.assertAlmostEqual(commands.frost_radius,72*self.w.renderer.s)
        search = next(h for h in self.w.hotspots if h.action == "wiki_search")
        self.assertAlmostEqual(search.rect.width(),498*.8*self.w.renderer.s)
        self.assertAlmostEqual(search.rect.height(),50*.8*self.w.renderer.s)
        self.assertAlmostEqual(search.rect.right(),1800.8*self.w.renderer.s)
        top = self.w.renderer.pack["layers"]["top"]["children"][0]
        stripes = self.w.renderer.pack["layers"]["history"]["children"][0]["children"][0]["children"][1]["children"][0]
        for node in (top,stripes):
            source = str(self.w.renderer.wiki_images[node["image"]])
            tiles = [i for i in commands.images if i.source == source]
            self.assertGreater(len(tiles),10)
            self.assertTrue(all(i.rect.width() <= node["tile"][0]*.8*self.w.renderer.s+.01 for i in tiles))

    def test_top_separator_and_scene_waves_run_their_source_tracks(self):
        self.w.jello_state.session_time = 5
        first = self.render_at()
        self.w.jello_state.session_time = 5.4
        later = self.render_at()
        layers = self.w.renderer.pack["layers"]
        source = str(self.w.renderer.wiki_images["scene_white_ground"])
        a = [i for i in first.images if i.source == source]
        b = [i for i in later.images if i.source == source]
        self.assertTrue(a and b)
        self.assertNotEqual([(i.rect,i.tint) for i in a],[(i.rect,i.tint) for i in b])
        top = layers["top"]["children"][0]["image"]
        source = str(self.w.renderer.wiki_images[top])
        self.assertNotEqual(next(i.rect for i in first.images if i.source==source),
                            next(i.rect for i in later.images if i.source==source))

    def test_breadcrumb_uses_source_arrows_and_text_sized_parent_targets(self):
        self.activate("wiki_category", "Movement")
        for language in ("中文", "English"):
            self.w.registry.get("ClickGui").get_setting("Language").value = language
            self.w.build()
            commands = self.w.renderer.commands
            root = next(t for t in commands.texts if t.text in ("POLAR 终端", "POLAR TERMINAL"))
            target = next(h for h in self.w.hotspots if h.action == "wiki_home"
                          and h.rect.contains(root.rect.center()))
            preferred = QFontMetricsF(root.font).horizontalAdvance(root.text)
            self.assertAlmostEqual(target.rect.width() / self.w.renderer.s, preferred + 40)
            arrows = [i for i in commands.images
                      if i.source == str(self.w.renderer.wiki_images["path_arrow"])]
            self.assertEqual(len(arrows), 2)  # 文件夹后和根目录后各一枚，当前页面后无箭头。
            self.assertLess(arrows[0].rect.right(), target.rect.left())
            category = next(t for t in commands.texts if t.text in ("移动", "Movement") and t.rect.top() < 60)
            self.assertLess(target.rect.right(), category.rect.left())
            self.assertFalse(any(h.action == "wiki_category" for h in self.w.hotspots))
            self.assertFalse(any(t.text == "›" and t.rect.y() < 60 for t in commands.texts))

    def test_all_modules_have_original_group_icons_and_dark_selected_rows(self):
        pack = self.w.renderer.pack
        self.assertEqual(set(pack["module_icons"]), {m.name for m in self.w.registry.modules})
        provenance = json.loads((ROOT / "rm_client/ui/endfield/wiki/assets/PROVENANCE.json").read_text(encoding="utf-8"))
        sources = {row["output"]: row for row in provenance["files"]}
        self.assertTrue(provenance["verified_game_bundles"])
        for icon in set(pack["module_icons"].values()):
            for suffix in ("", "_selected"):
                source = sources[pack["images"][icon + suffix]]
                self.assertTrue(source["texture_name"].startswith("icon_wiki_group_"))
        self.activate("wiki_category", "Movement")
        self.w.build()
        commands = self.w.renderer.commands
        expected = str(self.w.renderer.wiki_images[pack["module_icons"]["SpinMode"] + "_selected"])
        self.assertTrue(any(i.source == expected for i in commands.images))
        self.assertTrue(any(i.source == str(self.w.renderer.wiki_images["module_selected_bg"])
                            for i in commands.images))
        sidebar = next(v["rect"] for v in self.w.gui_scroll_viewports if v["key"] == "wiki:Movement")
        self.assertFalse(any(t.text in ("01", "02", "03", "04") and sidebar.contains(t.rect.center())
                             for t in commands.texts))

    def test_breadcrumb_black_background_counts_pages_not_selected_modules(self):
        def backgrounds():
            return [i for i in self.w.renderer.commands.images if Path(i.source).name.startswith("path_bg_")]
        self.assertEqual(backgrounds(), [])
        self.activate("wiki_category", "Movement")
        for name in ("SpinMode", "AutoSpinOnHit", "ChassisAssist", "PowerGuard"):
            self.w.dispatch("jello_open_settings", name, QPointF(), 1, self.w.rect())
            self.w.hover_point = QPointF(0, 0)
            self.w.build()
            self.assertEqual(len(backgrounds()), 9)  # 一个祖先底框，由原图九宫格绘制。
            labels = [t for t in self.w.renderer.commands.texts
                      if t.rect.top() == 25 * self.w.renderer.s and t.rect.left() < 1000 * self.w.renderer.s]
            self.assertEqual([t.text for t in labels], ["POLAR 终端", "移动"])
            self.assertEqual(labels[-1].color.name(), "#393838")
        self.activate("wiki_home")
        self.w.build()
        self.assertEqual(backgrounds(), [])

    def test_breadcrumb_current_has_no_padding_or_hover_bg_and_parent_keeps_source_corners(self):
        self.activate("wiki_category", "Movement")
        root = next(t for t in self.w.renderer.commands.texts if t.text == "POLAR 终端")
        self.w.hover_point = root.rect.center()
        self.w.build()
        commands, scale = self.w.renderer.commands, self.w.renderer.s
        patches = [i for i in commands.images if Path(i.source).name.startswith("path_bg_")]
        self.assertEqual(len(patches), 18)
        self.assertEqual(self.w.renderer.pack["breadcrumbs"]["border"], [7, 8, 8, 7])
        self.assertAlmostEqual(patches[0].rect.width(), 7 * scale)
        self.assertAlmostEqual(patches[0].rect.height(), 8 * scale)
        self.assertAlmostEqual(patches[0].rect.top(), 31 * scale)
        self.assertAlmostEqual(patches[9].rect.top(), 28 * scale)
        self.assertAlmostEqual(patches[9].tint.alphaF(), 64 / 255, places=3)
        corner, center = QImage(patches[0].source), QImage(patches[4].source)
        self.assertLess(corner.pixelColor(0, 0).alpha(), 5)
        self.assertEqual(center.pixelColor(0, 0).alpha(), 255)
        current = next(t for t in commands.texts if t.text == "移动" and t.rect.top() < 60)
        self.assertAlmostEqual(current.rect.width(), QFontMetricsF(current.font).horizontalAdvance(current.text) * scale)
        self.w.hover_point = current.rect.center()
        self.w.build()
        self.assertEqual(len([i for i in self.w.renderer.commands.images if Path(i.source).name.startswith("path_bg_")]), 9)

    def test_long_english_breadcrumbs_fit_without_overlapping_search(self):
        self.w.jello_state.session_time = 1.0
        self.w.registry.get("ClickGui").get_setting("Language").value = "English"
        for module in self.w.registry.modules:
            self.w.dispatch("jello_open_settings", module.name, QPointF(), 1, self.w.rect())
            self.w.build()
            commands = self.w.renderer.commands
            search = next(h for h in self.w.hotspots if h.action == "wiki_search")
            labels = [t for t in commands.texts if t.rect.top() == 25 * self.w.renderer.s
                      and t.rect.right() < search.rect.left()
                      and t.font.pointSizeF() == self.w.renderer._wiki_font(26).pointSizeF()]
            self.assertEqual(len(labels), 2)
            for previous, current in zip(labels, labels[1:]):
                self.assertLess(previous.rect.right(), current.rect.left())
            self.assertLess(labels[-1].rect.right(), search.rect.left())

    def test_chinese_and_setting_name_search_does_not_change_module_values(self):
        before = [(m.name, m.enabled, [s.value for s in m.settings]) for m in self.w.registry.modules]
        self.assertIn("ArmorAutoAim", [m.name for m in wiki_modules(self.w.registry, None, "装甲自瞄")])
        self.assertIn("CameraFeed", [m.name for m in wiki_modules(self.w.registry, None, "Capture Width")])
        self.assertEqual(wiki_modules(self.w.registry, None, "不存在的模块xyz"), ())
        self.w.search_focus = True
        event = QInputMethodEvent()
        event.setCommitString("装甲自瞄")
        APP.sendEvent(self.w, event)
        self.assertEqual(self.w.search_query, "装甲自瞄")
        QTest.keyClick(self.w, Qt.Key.Key_Return)
        self.assertIsNone(self.w.jello_state.settings_module)
        self.w.settle()
        self.assertEqual(self.w.jello_state.settings_module, "ArmorAutoAim")
        self.assertEqual(self.w.jello_state.category, "Combat")
        self.assertEqual(before, [(m.name, m.enabled, [s.value for s in m.settings]) for m in self.w.registry.modules])

    def test_plain_shortcuts_are_owned_and_f12_keeps_emergency_priority(self):
        for key in (Qt.Key.Key_W, Qt.Key.Key_B, Qt.Key.Key_K, Qt.Key.Key_E, Qt.Key.Key_Space):
            QTest.keyClick(self.w, key)
        self.w.control.set_mouse_button.assert_not_called()
        self.w.handle_control_key_event.assert_not_called()
        self.w.toggle_bound_module_for_event.assert_not_called()
        QTest.keyClick(self.w, Qt.Key.Key_F12)
        self.w.backend.trigger_estop.assert_called_once()

    def test_controls_reuse_the_original_setting_mutation_callbacks(self):
        self.activate("wiki_category", "Movement")
        self.activate("jello_open_settings", "ChassisAssist")
        self.w.build()
        toggle = next(h for h in self.w.hotspots if h.action == "setting_toggle")
        old = toggle.payload.value
        self.w.dispatch(toggle.action, toggle.payload, toggle.rect.center(), 1, toggle.rect)
        self.assertEqual(toggle.payload.value, not old)
        self.w.after_setting_changed.assert_called_with(toggle.payload)

    def test_close_publishes_no_targets_and_empty_click_does_not_close(self):
        self.w.click(self.w.rect().center())
        self.assertTrue(self.w.gui_visible)
        QTest.keyClick(self.w, Qt.Key.Key_F8)
        self.w.build()
        self.assertEqual(self.w.hotspots, [])
        self.assertEqual(self.w.gui_scroll_viewports, [])

    def test_search_selects_preview_before_entering_details(self):
        self.activate("wiki_search")
        self.w.search_query = "CameraFeed"
        self.activate("wiki_search_select", "CameraFeed")
        self.assertIsNone(self.w.jello_state.settings_module)
        self.w.build()
        self.assertTrue(any(h.action == "jello_open_settings" and h.payload == "CameraFeed"
                            for h in self.w.hotspots))
        self.activate("jello_open_settings", "CameraFeed")
        self.assertEqual(self.w.jello_state.settings_module, "CameraFeed")
        self.assertFalse(self.w.search_focus)

    def test_close_while_searching_clears_editor_and_owns_late_release(self):
        self.activate("wiki_search")
        self.w.search_query = "vision"
        self.w.build()
        close = next(h for h in self.w.hotspots if h.action == "wiki_back")
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton, pos=close.rect.center().toPoint())
        self.assertTrue(self.w.gui_visible)
        self.assertFalse(self.w.search_focus)
        self.w.settle()
        self.assertFalse(self.w.jello_state.search_open)
        QTest.keyClick(self.w, Qt.Key.Key_F8)
        self.w.gui_timeline.progress = 0
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton, pos=close.rect.center().toPoint())
        self.w.control.set_mouse_button.assert_not_called()
        QTest.keyClick(self.w, Qt.Key.Key_F8)
        self.assertTrue(self.w.gui_visible)

    def test_source_curve_keyframes_and_font_sizes_are_preserved(self):
        motion = self.w.renderer.motion
        self.assertGreaterEqual(len(motion.durations), 15)
        for (name, path, attribute), keys in motion.tracks.items():
            for key in keys:
                if isinstance(key["value"], (int, float)):
                    self.assertAlmostEqual(motion.sample(name, path, attribute, key["time"]),
                                           key["value"], places=4)
        small, large = self.w.renderer._wiki_font(16), self.w.renderer._wiki_font(40)
        self.assertGreater(small.pointSizeF(), 0)
        self.assertGreater(large.pointSizeF(), small.pointSizeF() * 2)
        self.assertTrue(all(clip["m_SampleRate"] == 60 for clip in self.w.renderer.pack["clips"].values()))

    def test_curve_sampling_uses_tangents_instead_of_linear_interpolation(self):
        keys = [{"time": 0, "value": 0, "inSlope": 0, "outSlope": 0},
                {"time": 1, "value": 1, "inSlope": 0, "outSlope": 0}]
        self.assertAlmostEqual(sample_keys(keys, .25), .15625)
        self.assertEqual(sample_keys(keys, -1), 0)
        self.assertEqual(sample_keys(keys, 2), 1)

    def test_keyboard_dropdown_commits_the_highlighted_original_option(self):
        self.activate("wiki_category", "Movement")
        self.activate("jello_open_settings", "ChassisAssist")
        self.w.build()
        target = next(h for h in self.w.hotspots if h.action == "jello_mode_dropdown")
        setting = target.payload[1]
        previous = setting.options.index(setting.value)
        self.w.dispatch(target.action, target.payload, target.rect.center(), 1, target.rect)
        QTest.keyClick(self.w, Qt.Key.Key_Down)
        QTest.keyClick(self.w, Qt.Key.Key_Return)
        self.assertEqual(setting.value, setting.options[(previous+1) % len(setting.options)])
        self.w.after_setting_changed.assert_called_with(setting)

    def test_hover_background_is_dark_within_100ms_and_switches_without_a_trail(self):
        targets = [h for h in self.w.hotspots if h.action == "wiki_category"]
        background = str(self.w.renderer.wiki_images["home_blackmask"])
        clock = [1.0]
        self.w.renderer.clock = lambda: clock[0]
        self.w.hover_point = targets[0].rect.center()
        self.w.build()
        for _ in range(2):
            clock[0] += .05
            commands = self.w.renderer.build(self.w, self.w.jello_state, 1280, 720, 1)
        panels = [image for image in commands.images if image.source == background and image.softness_y > 0]
        self.assertGreater(panels[0].tint.alphaF(), .95)
        self.w.hover_point = targets[1].rect.center()
        self.w.build()
        for _ in range(4):
            clock[0] += .05
            commands = self.w.renderer.build(self.w, self.w.jello_state, 1280, 720, 1)
        panels = [image for image in commands.images if image.source == background and image.softness_y > 0]
        self.assertEqual(len(panels), 1)
        self.assertGreater(panels[0].tint.alphaF(), .95)
        self.assertAlmostEqual(panels[0].rect.center().x(), targets[1].rect.center().x())

    def test_home_soft_mask_expands_while_top_points_and_corner_markers_move(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        self.w.hover_point = target.rect.center()
        self.render_at()
        early = self.render_at(.1)
        later = self.render_at(.4)
        def mask(commands):
            return next(i for i in commands.images if i.softness_y > 0)
        self.assertGreater(mask(early).softness_y, mask(later).softness_y * 3)
        self.assertEqual(mask(early).rect, mask(later).rect)
        def points(commands):
            return [v for v in commands.rects if v.fill.name() == "#060606"]
        a, b = points(early), points(later)
        self.assertEqual(len(a), 2)
        self.assertLess(abs(a[0].rect.center().x() - a[1].rect.center().x()),
                        abs(b[0].rect.center().x() - b[1].rect.center().x()))
        gray = [v for v in later.rects if v.fill.name() == "#727272" and v.fill.alpha() > 0]
        self.assertEqual(len(gray), 2)
        self.assertLess(gray[0].rect.top(), gray[1].rect.top())
        self.assertLess(gray[0].rect.left(), gray[1].rect.left())

    def test_home_selected_icon_flashes_and_yellow_triangles_are_staggered_below_it(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        self.w.hover_point = target.rect.center()
        self.render_at()
        first = self.render_at(.2)
        second = self.render_at(.533333333)
        third = self.render_at(.11)
        image_path = str(self.w.renderer.wiki_images[target.payload + "Selected"])
        a = next(i for i in first.images if i.source == image_path)
        b = next(i for i in second.images if i.source == image_path)
        self.assertLess(a.tint.redF(), .01)
        self.assertGreater(b.tint.redF(), .95)
        triangle_path = str(self.w.renderer.wiki_images["triangle"])
        triangles = [i for i in second.images if i.source == triangle_path]
        self.assertGreater(triangles[0].tint.alpha(), 250)
        self.assertEqual(triangles[1].tint.alpha(), 0)
        self.assertTrue(all(i.tint.redF() > .95 and i.tint.greenF() > .95 and i.tint.blueF() < .15
                            for i in triangles))
        self.assertLess(triangles[0].rect.top(), triangles[1].rect.top())
        self.assertGreater(triangles[0].rect.top(), b.rect.center().y())
        self.assertEqual([i.tint.alpha() for i in third.images if i.source == triangle_path], [255, 255])

    def test_top_points_share_source_center_then_finish_at_parent_corners(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        self.w.hover_point = target.rect.center()
        first = self.render_at()
        points = [v.rect for v in first.rects if v.fill.name() == "#060606"]
        unit = 257 / 321.5 * self.w.renderer.s
        # 源父宽324，初始两点分别为[-6,2]与[-2,6]，先重合成中心黑块。
        self.assertAlmostEqual(points[0].left(), target.rect.center().x() - 6 * unit)
        self.assertAlmostEqual(points[1].left(), target.rect.center().x() - 2 * unit)
        self.assertTrue(points[0].intersects(points[1]))
        final = self.render_at(.5)
        points = [v.rect for v in final.rects if v.fill.name() == "#060606"]
        self.assertAlmostEqual(points[0].right(), target.rect.center().x() + 162 * unit)
        self.assertAlmostEqual(points[1].left(), target.rect.center().x() - 162 * unit)
        self.assertAlmostEqual(points[0].height(), 8 * unit)
        mask = next(i for i in final.images if i.softness_y > 0)
        self.assertAlmostEqual(points[0].bottom(), mask.rect.top() - 3 * unit)

    def test_gray_blocks_follow_source_width_then_vertical_split_keyframes(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        self.w.hover_point = target.rect.center()
        self.render_at()
        unit = 257 / 321.5 * self.w.renderer.s
        for delta, width, left_y, right_y in ((.1, 50, 84, 84), (.35, 14, 84, 84), (.3, 14, 199, -91)):
            commands = self.render_at(delta)
            gray = [v.rect for v in commands.rects if v.fill.name() in ("#4a4a4a", "#727272")]
            self.assertEqual(len(gray), 2)
            parent = next(i.rect for i in commands.images if i.softness_y > 0)
            for rect, y in zip(gray, (left_y, right_y)):
                self.assertAlmostEqual(rect.width(), width * unit, places=4)
                self.assertAlmostEqual(rect.height(), 12 * unit)
                self.assertAlmostEqual(rect.center().y(), parent.center().y() - y * unit, places=4)
            # 左块以左边为枢轴，右块以右边为枢轴；宽度收缩不能带动外侧边缘。
            self.assertAlmostEqual(gray[0].left(), parent.center().x() - 125 * unit)
            self.assertAlmostEqual(gray[1].right(), parent.center().x() + 131 * unit)

    def test_hover_out_fades_without_moving_unbound_block_geometry(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        self.w.hover_point = target.rect.center()
        self.render_at()
        before = self.render_at(.2)
        colors = ("#060606", "#727272")
        markers = lambda commands: [v for v in commands.rects if v.fill.name() in colors]
        self.assertEqual(len(markers(before)), 4)
        self.w.hover_point = QPointF(0, 0)
        self.render_at()
        during = self.render_at(.08)
        self.assertEqual([v.rect for v in markers(before)], [v.rect for v in markers(during)])
        self.assertTrue(all(a.fill.alpha() > b.fill.alpha() for a, b in zip(markers(before), markers(during))))

    def test_fresh_hover_replays_identical_block_geometry_after_complete_exit(self):
        target = next(h for h in self.w.hotspots if h.action == "wiki_category")
        frames = []
        for _ in range(2):
            self.w.hover_point = target.rect.center()
            self.render_at()
            cycle = []
            for delta in (.1, .3, .35):
                commands = self.render_at(delta)
                cycle.append([(v.rect, v.fill) for v in commands.rects
                              if v.fill.name() in ("#060606", "#4a4a4a", "#727272")])
            frames.append(cycle)
            self.w.hover_point = QPointF(0, 0)
            self.render_at()
            self.render_at(.2)
        self.assertEqual(frames[0], frames[1])

    def test_background_has_source_layers_and_continues_rotating_after_entry(self):
        self.w.jello_state.session_time = 5
        first = self.render_at()
        self.w.jello_state.session_time = 15
        second = self.render_at()
        key = str(self.w.renderer.wiki_images["scene_DecoDot1"])
        a = next(i for i in first.images if i.source == key)
        b = next(i for i in second.images if i.source == key)
        self.assertGreater(a.tint.alphaF(), .1)
        self.assertGreater(abs(a.rotation_degrees - b.rotation_degrees), 20)
        self.assertEqual(a.rect, b.rect)
        self.assertTrue(any(i.source.endswith("scene_DecoDecoMap.png") for i in first.images))
        self.assertTrue(any(i.source.endswith("scene_DecoDeco1.png") for i in first.images))

    def test_category_background_uses_group_fade_scale_and_vertical_tracks(self):
        home = self.render_at()
        source = str(self.w.renderer.wiki_images["scene_DecoDecoMap"])
        before = next(i for i in home.images if i.source==source)
        self.w.dispatch("wiki_category","Movement",QPointF(),1,self.w.rect())
        early = self.render_at(.08)
        background = self.w.renderer.background
        self.assertEqual(background.clip,"wiki_uideco_grouppanel_in")
        alpha = background.sample(self.w.renderer.motion,"HudNode/BgDecoLayout","m_Alpha",self.w.now)
        self.assertGreater(alpha,0)
        self.assertLess(alpha,.6)
        late = self.render_at(.85)
        after = next(i for i in late.images if i.source==source)
        self.assertAlmostEqual(after.rect.width()/before.rect.width(),5/6,places=5)
        self.assertGreater(after.rect.center().y()-before.rect.center().y(),40*self.w.renderer.s)
        self.assertAlmostEqual(background.sample(self.w.renderer.motion,"HudNode/ButtomDecoLayout ","m_Alpha",self.w.now),1)
        line = self.w.renderer.pack["layers"]["bottom"]["children"][0]
        image = QImage(str(self.w.renderer.wiki_images[line["image"]]))
        self.assertLessEqual(max(image.pixelColor(50,y).alpha() for y in range(image.height())),12)

    def test_back_plays_group_exit_then_restarts_home_background_entry(self):
        self.activate("wiki_category","Movement")
        self.w.build()
        self.w.dispatch("wiki_back",None,QPointF(),1,self.w.rect())
        self.render_at(.08)
        self.assertEqual(self.w.renderer.background.clip,"wiki_uideco_grouppanel_out")
        self.render_at(.15)
        self.assertEqual(self.w.renderer.background.clip,"wiki_uideco_in")
        self.assertAlmostEqual(self.w.renderer.background.started_at,self.w.jello_state.background_changed_at+1/6)
        self.render_at(3)
        cx,cy,scale,alpha = self.w.renderer.background_projection
        self.assertAlmostEqual(cx,960,places=4)
        self.assertAlmostEqual(cy,540,places=4)
        self.assertAlmostEqual(scale,1,places=5)
        self.assertEqual(alpha,1)

    def test_module_switch_and_search_do_not_restart_background_or_loop(self):
        self.activate("wiki_category","Movement")
        self.w.build()
        started = self.w.renderer.background.started_at
        serial = self.w.jello_state.background_serial
        self.activate("jello_open_settings","ChassisAssist")
        self.activate("wiki_search")
        self.w.build()
        self.assertEqual(self.w.renderer.background.started_at,started)
        self.assertEqual(self.w.jello_state.background_serial,serial)
        self.activate("wiki_back")
        self.w.build()
        self.assertEqual(self.w.renderer.background.started_at,started)
        self.assertGreater(self.w.jello_state.session_time,3)

    def test_direct_entry_gets_group_background_and_close_fades_the_hud(self):
        self.w.dispatch("jello_open_settings","SpinMode",QPointF(),1,self.w.rect())
        self.render_at(.9)
        self.assertEqual(self.w.renderer.background.clip,"wiki_uideco_grouppanel_in")
        self.assertAlmostEqual(self.w.renderer.background_projection[2],5/6,places=5)
        QTest.keyClick(self.w,Qt.Key.Key_F8)
        self.render_at()
        self.assertEqual(self.w.renderer.background.clip,"wiki_uideco_out")
        self.render_at(.08)
        self.assertGreater(self.w.renderer.background_projection[3],0)
        self.assertLess(self.w.renderer.background_projection[3],1)

    def test_compat_soft_mask_and_rotation_match_the_image_command_contract(self):
        commands = ClickGuiDrawList()
        source = self.w.renderer.wiki_images["home_blackmask"]
        commands.image(QRectF(50, 20, 20, 100), source, QColor("black"), softness_y=80)
        commands.image(QRectF(10, 115, 60, 10), source, QColor("black"), rotation_degrees=-90)
        frame = QImage(140, 140, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(QColor("white"))
        painter = QPainter(frame)
        self.w.renderer.paint_commands_compat(painter, commands, 140, 140)
        painter.end()
        self.assertGreater(frame.pixelColor(60, 22).red(), 220)
        self.assertLess(frame.pixelColor(60, 70).red(), 10)
        self.assertLess(frame.pixelColor(40, 95).red(), 10)
        self.assertGreater(frame.pixelColor(15, 120).red(), 250)
        faded = ClickGuiGpuRenderer._apply_opacity(commands.images[1], .5)
        self.assertEqual(faded.rotation_degrees, -90)
        faded = ClickGuiGpuRenderer._apply_opacity(commands.images[0], .5)
        self.assertEqual(faded.softness_y, 80)

    def test_all_six_hover_states_use_source_detailed_images_and_hide_normal_symbols(self):
        provenance = json.loads((ROOT / "rm_client/ui/endfield/wiki/assets/PROVENANCE.json").read_text(encoding="utf-8"))
        sources = {row["output"]: row["texture_name"] for row in provenance["files"]}
        targets = [h for h in self.w.hotspots if h.action == "wiki_category"]
        clock = [1.0]
        self.w.renderer.clock = lambda: clock[0]
        for target in targets:
            with self.subTest(category=target.payload):
                state = self.w.jello_state
                state.home_hovers.clear()
                self.w.hover_point = target.rect.center()
                self.w.build()
                for _ in range(6):
                    clock[0] += .05
                commands = self.w.renderer.build(self.w, state, 1280, 720, 1)
                selected = self.w.renderer.wiki_images[target.payload + "Selected"]
                self.assertIn("deco_wiki_select_icon_", sources[selected.name])
                detailed = next(image for image in commands.images if image.source == str(selected))
                normal = next(image for image in commands.images
                              if image.source == str(self.w.renderer.wiki_images[target.payload]))
                self.assertGreater(detailed.tint.alphaF(), .95)
                self.assertGreater(detailed.rect.height(), normal.rect.height() * 1.5)
                self.assertEqual(normal.tint.alpha(), 0)


if __name__ == "__main__":
    unittest.main()
