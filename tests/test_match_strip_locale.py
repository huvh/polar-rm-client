"""Offscreen display-only locale coverage; no app, hardware or transport startup."""
from dataclasses import asdict, replace
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import build_default_registry
from rm_client.top_match_bar import LifeState as L, MatchBarFrame, RobotCard, TeamStrip, compute_layout
from rm_client.ui.match_strip_locale import (
    MATCH_STRIP_ZH, match_alliance_text, match_health_text, match_role_text, match_strip_text,
)
from rm_client.ui.top_match_bar import TopMatchBarOptions, TopMatchBarRenderer
from rm_client.ui.top_match_bar_controller import TopMatchBarController


class MatchStripLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def frame(self):
        return MatchBarFrame(
            TeamStrip("Red", (
                RobotCard(1, "HERO", L.ALIVE, health=150, max_health=200),
                RobotCard(2, "ENG", L.UNKNOWN),
                RobotCard(3, "INF-1", L.ALIVE, health=90),
                RobotCard(6, "UAV", L.UNKNOWN, health_applicable=False),
            ), 2),
            TeamStrip("Blue", (RobotCard(107, "SENTRY", L.DEAD, health=0),), 0),
            85, "RM SCORE", "MATCH", roster_label="GROUND ALIVE",
        )

    def render(self, frame, *, chinese=False, renderer=None, options=None, hide_text=False):
        image = QImage(1280, 220, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        options = options or TopMatchBarOptions(scale=1, show_health=True, chinese=chinese)
        renderer = renderer or TopMatchBarRenderer()
        from rm_client.ui import top_match_bar as module
        original = module._text
        text_calls = []

        def record(p, rect, text, font, color, **kwargs):
            text_calls.append((rect.getRect(), text, font.toString(), color.name(), kwargs))
            if not hide_text:
                original(p, rect, text, font, color, **kwargs)

        try:
            with patch.object(module, "_text", side_effect=record):
                layout = renderer.paint(painter, frame, 1280, now=10, options=options)
        finally:
            painter.end()
        return image, layout, text_calls

    def test_builtin_vocabulary_and_role_health_text_keep_raw_models(self):
        frame = self.frame()
        raw = asdict(frame)
        en_image, en_layout, en_calls = self.render(frame)
        zh_image, zh_layout, zh_calls = self.render(frame, chinese=True)
        en = [call[1] for call in en_calls]
        zh = [call[1] for call in zh_calls]
        for english, chinese in (
            ("HER", "英雄"), ("HERO 1", "英雄 1"), ("ENG 2", "工程 2"),
            ("INF-1 3", "步兵1 3"), ("UAV 6", "空中 6"), ("SENTRY 107", "哨兵 107"),
            ("HP —", "血量 —"), ("HP 90 / ?", "血量 90 / ?"), ("NO HP", "无血量属性"),
            ("HP 0 / ?", "血量 0 / ?"), ("RM SCORE", "裁判比分"),
            ("GROUND ALIVE", "地面存活"), ("RED", "红方"), ("BLUE", "蓝方"),
        ):
            self.assertIn(english, en)
            self.assertIn(chinese, zh)
            self.assertNotIn(english, zh)
        for neutral in ("150/200", "1:25", "2", "0", "?"):
            self.assertIn(neutral, en)
            self.assertIn(neutral, zh)
        self.assertEqual(en_layout, zh_layout)
        # Text rectangles, font metrics and colours are all unchanged.
        self.assertEqual([(c[0], *c[2:]) for c in en_calls], [(c[0], *c[2:]) for c in zh_calls])
        self.assertNotEqual(en_image, zh_image)
        self.assertEqual(asdict(frame), raw)
        self.assertEqual(frame.left.cards[1].health_text, "HP —")
        self.assertEqual(frame.left.cards[-1].health_text, "NO HP")

    def test_status_states_and_scoreless_fallback_are_localized(self):
        frame = self.frame()
        for sample, options, english, chinese in (
            (replace(frame, paused=True), {}, "PAUSED", "已暂停"),
            (replace(frame, countdown=None, score_label="", roster_label=""),
             {"show_health": False}, "NO DATA", "无数据"),
            (replace(frame, score_label=""), {}, "SCORE —", "比分 —"),
            (frame, {"show_health": False}, "RM SCORE", "裁判比分"),
            (frame, {"show_health": False, "show_scores": False}, "GROUND ALIVE", "地面存活"),
        ):
            for enabled, expected in ((False, english), (True, chinese)):
                with self.subTest(expected=expected):
                    settings = dict(scale=1, show_health=True, chinese=enabled)
                    settings.update(options)
                    _, _, calls = self.render(sample, options=TopMatchBarOptions(**settings))
                    self.assertIn(expected, [call[1] for call in calls])

    def test_all_known_roles_translate_and_custom_labels_are_opaque(self):
        names = ("HERO", "ENG", "INF-1", "INF-2", "INF-3", "UAV", "SENTRY", "DART", "RADAR")
        expected = ("英雄", "工程", "步兵1", "步兵2", "步兵3", "空中", "哨兵", "飞镖", "雷达")
        for offset in (0, 100):
            for role, (name, zh) in enumerate(zip(names, expected), 1):
                card = RobotCard(role + offset, name)
                self.assertEqual(match_role_text(card, True), zh)
                self.assertEqual(match_role_text(card, False), name)
        for label in ("HERO custom", "Blue_HP_{x}", "HERO", "PAUSED"):
            self.assertEqual(match_role_text(RobotCard(9, label), True), label)
        for alias in ("Team Red", "BLUE_MIX", "Blue {x}", "PAUSED", "Redbirds"):
            for chinese in (False, True):
                self.assertEqual(match_alliance_text(alias, chinese), alias)
        for text, translated in MATCH_STRIP_ZH.items():
            self.assertEqual(match_strip_text(text, False), text)
            self.assertEqual(match_strip_text(text, True), translated)
        card = RobotCard(1, "custom", L.ALIVE, health=81, max_health=120)
        self.assertEqual(match_health_text(card, True), "81/120")

    def test_custom_frame_labels_and_aliases_survive_renderer(self):
        for label in ("League HP {x}", "PAUSED", "SCORE —", "GROUND ALIVE"):
            with self.subTest(label=label):
                frame = replace(self.frame(), score_label=label, roster_label=label,
                                left=TeamStrip("Redbirds", (RobotCard(1, "My HERO"),), 8))
                raw = asdict(frame)
                _, _, calls = self.render(frame, options=TopMatchBarOptions(
                    chinese=True, show_health=True, custom_roster_label=True))
                texts = [call[1] for call in calls]
                self.assertIn(label, texts)
                self.assertIn("Redbirds", texts)
                self.assertIn("My HERO 1", texts)
                self.assertEqual(asdict(frame), raw)

    def test_language_switch_rebuilds_cached_portrait_and_restores_english(self):
        renderer = TopMatchBarRenderer()
        card = RobotCard(1, "HERO", L.ALIVE)
        en, en_gray = renderer._portrait(card, None)
        zh, zh_gray = renderer._portrait(card, None, chinese=True)
        self.assertNotEqual(en, zh)
        self.assertNotEqual(en_gray, zh_gray)
        self.assertEqual(len(renderer._portraits), 2)
        restored, _ = renderer._portrait(card, None, chinese=False)
        self.assertIs(restored, en)
        self.assertIs(renderer._portrait(card, None, chinese=True)[0], zh)
        self.assertTrue(all(len(key) == 4 for key in renderer._portraits))

    def test_authorized_avatar_and_all_nontext_pixels_are_unchanged(self):
        renderer = TopMatchBarRenderer()
        avatar = QImage(140, 140, QImage.Format_ARGB32_Premultiplied)
        avatar.fill(Qt.red)
        self.assertEqual(renderer._portrait(self.frame().left.cards[0], avatar),
                         renderer._portrait(self.frame().left.cards[0], avatar, chinese=True))
        en, en_layout, _ = self.render(self.frame(), hide_text=True)
        zh, zh_layout, _ = self.render(self.frame(), chinese=True, hide_text=True)
        self.assertEqual(en, zh)
        self.assertEqual(en_layout, zh_layout)

    def test_support_system_rows_translate_without_geometry_or_state_changes(self):
        frame = MatchBarFrame(
            TeamStrip("Red", systems=(RobotCard(8, "DART", L.ALIVE), RobotCard(9, "RADAR", L.DEAD))),
            TeamStrip("Blue", systems=(RobotCard(108, "DART", L.UNKNOWN), RobotCard(109, "My RADAR", L.ALIVE))),
        )
        before = asdict(frame)
        layout = compute_layout(1280, 0, 0)
        en, zh = Mock(), Mock()
        en_bottom = TopMatchBarController._paint_systems(en, frame, layout)
        zh_bottom = TopMatchBarController._paint_systems(zh, frame, layout, chinese=True)
        self.assertEqual(en_bottom, zh_bottom)
        en_calls = [c.args for c in en.drawText.call_args_list]
        zh_calls = [c.args for c in zh.drawText.call_args_list]
        self.assertEqual([c[:2] for c in en_calls], [c[:2] for c in zh_calls])
        self.assertEqual(en_calls[0][2], "DART 8: ALIVE  ·  RADAR 9: DOWN")
        self.assertEqual(zh_calls[0][2], "飞镖 8: 存活  ·  雷达 9: 已毁")
        self.assertEqual(zh_calls[1][2], "飞镖 108: —  ·  My RADAR 109: 存活")
        self.assertEqual(asdict(frame), before)


class MatchStripControllerLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.registry = build_default_registry()
        self.registry.get("TopMatchBar").enabled = True
        self.owner = NS(
            registry=self.registry, state=NS(match_mode="RMUC7v7", alliance_color="Red", robot_id=3),
            backend=NS(mqtt=NS(host="local.invalid", port=3333, disconnected_at=0.0,
                              connected=True, receive_generation=0),
                       scenario_key="OfficialEvent", referee=NS(profile_id="rm2026-v1.3.1")),
            home_visible=False, hero_deploy_ui=NS(active=False), overlay_coordinator=NS(modal=None),
            dynamic_island_state=NS(y=12.0, height=42.0), menu_overlay_active=lambda: False,
            tactical_map_rect=lambda w, h: QRectF(12, 58, 170, 118),
            setting_bool=lambda mod, key, default=False: bool(mod.get_setting(key).value)
                         if mod and mod.get_setting(key) else default,
            setting_mode=lambda mod, key, default: str(mod.get_setting(key).value)
                         if mod and mod.get_setting(key) else default,
        )
        self.controller = TopMatchBarController(self.owner)

    def paint(self):
        image = QImage(1280, 720, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            with patch.object(self.controller.renderer, "paint", wraps=self.controller.renderer.paint) as draw, \
                 patch.object(self.controller, "_paint_systems", wraps=self.controller._paint_systems) as systems:
                self.controller.paint(painter, 1280, 720, 10)
                self.assertEqual(self.controller._last_error, "")
                self.assertIsNotNone(self.controller.last_layout)
                return image, draw.call_args.kwargs["options"], systems.call_args
        finally:
            painter.end()

    def test_live_setting_flows_to_all_renderers_without_resetting_feed(self):
        self.controller.observe_referee("GameStatus", {"stage_countdown_sec": 85, "red_score": 3}, 10)
        feed = self.controller.feed
        snapshot = asdict(feed.snapshot(10))
        state = vars(self.owner.state).copy()
        results = []
        for language, chinese in (("English", False), ("简体中文", True), ("English", False)):
            self.registry.get("ClickGui").get_setting("Language").value = language
            image, options, systems = self.paint()
            self.assertEqual(options.chinese, chinese)
            self.assertEqual(systems.kwargs["chinese"], chinese)
            self.assertFalse(options.custom_roster_label)
            self.assertIs(self.controller.feed, feed)
            self.assertEqual(asdict(feed.snapshot(10)), snapshot)
            results.append((image, self.controller.last_layout))
        self.assertNotEqual(results[0][0], results[1][0])
        self.assertEqual(results[0][0], results[2][0])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(vars(self.owner.state), state)

    def test_explicit_custom_roster_collision_stays_verbatim(self):
        self.controller.configure_rosters([1, 8], [101, 108], label="GROUND ALIVE")
        self.registry.get("ClickGui").get_setting("Language").value = "简体中文"
        from rm_client.ui import top_match_bar as module
        with patch.object(module, "_text", wraps=module._text) as text:
            _, options, _ = self.paint()
        self.assertTrue(options.custom_roster_label)
        strings = [c.args[2] for c in text.call_args_list]
        self.assertIn("GROUND ALIVE", strings)
        self.assertNotIn("地面存活", strings)


if __name__ == "__main__":
    unittest.main()
