"""Real Qt pixels/geometry and live-value caching for the compact CS2 strip.

No application/backend startup, downloaded avatars or fabricated live telemetry.
write_evidence() exports explicitly synthetic Qt fixtures for visual inspection.
"""
from dataclasses import asdict, replace
import os
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import build_default_registry
from rm_client.top_match_bar import LifeState as L, MatchBarFrame, RobotCard, TeamStrip
from rm_client.ui import top_match_bar as strip
from rm_client.ui import top_match_bar_controller as controller_module
from rm_client.ui.top_match_bar import TopMatchBarOptions, TopMatchBarRenderer
from rm_client.ui.top_match_bar_controller import TopMatchBarController


def ensure_qt_fonts():
    # Windows' offscreen plugin exposes no system faces until explicitly loaded.
    # A tofu square per character is not a genuine readability/pixel regression.
    root = Path(__file__).resolve().parents[1]
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont(str(root / "assets/fonts/tahoma.ttf")) >= 0
    system_cjk = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    if system_cjk.exists() and "Microsoft YaHei" not in QFontDatabase.families():
        assert QFontDatabase.addApplicationFont(str(system_cjk)) >= 0


def fixture_frame(*, unknown=False, seven=False):
    ids = (1, 2, 3, 4, 5, 6, 7) if seven else (1, 2, 3, 4, 6, 7)
    names = {1: "HERO", 2: "ENG", 3: "INF-1", 4: "INF-2", 5: "INF-3", 6: "UAV", 7: "SENTRY"}
    def team(alliance, offset, score):
        cards = tuple(RobotCard(
            rid + offset, names[rid],
            L.UNKNOWN if unknown or rid == 6 else L.DEAD if rid == 4 else L.ALIVE,
            kills=None if unknown else 2 if rid == 2 else None,
            avatar_key=str(rid + offset), health=None if unknown or rid == 6 else 0 if rid == 4 else 150,
            max_health=200 if not unknown and rid in (3, 4) else None,
            health_applicable=rid != 6) for rid in ids)
        return TeamStrip(alliance, cards, None if unknown else score)
    return MatchBarFrame(team("Blue", 100, 0), team("Red", 0, 3),
                         None if unknown else 83, "RM SCORE", roster_label="GROUND ALIVE")


def render(frame, *, renderer=None, width=1280, dpr=1, options=None, avatars=None):
    renderer = renderer or TopMatchBarRenderer()
    image = QImage(round(width * dpr), round(180 * dpr), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        layout = renderer.paint(painter, frame, width, now=10, avatars=avatars,
                                options=options or TopMatchBarOptions(scale=1, show_health=True))
    finally:
        painter.end()
    return image, layout


def render_card(card, *, renderer=None, supplied=None, dpr=1, show_health=True, show_kills=False):
    renderer = renderer or TopMatchBarRenderer()
    image = QImage(round(80 * dpr), round(125 * dpr), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        renderer._paint_card(painter, card, 10, TopMatchBarOptions(
            show_health=show_health, show_kills=show_kills), supplied)
    finally:
        painter.end()
    return image


class Cs2MatchStripStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_qt_fonts()

    def test_unknown_border_is_visibly_continuous_not_dashed(self):
        image = render_card(RobotCard(1, "HERO"))
        # Actual horizontal AND vertical edge pixels: dashed frames leave gaps.
        self.assertEqual(len({image.pixelColor(x, 1).rgba() for x in range(5, 65)}), 1)
        self.assertEqual(len({image.pixelColor(1, y).rgba() for y in range(5, 65)}), 1)
        self.assertGreater(image.pixelColor(30, 1).alpha(), 240)
        self.assertGreater(image.pixelColor(1, 30).alpha(), 240)
        self.assertNotIn("DashLine", Path(strip.__file__).read_text(encoding="utf-8"))

    def test_no_label_stack_or_thick_panel_below_avatar(self):
        card = RobotCard(1, "HERO", L.ALIVE, health=100, max_health=200)
        with patch.object(strip, "_text", wraps=strip._text) as text:
            image = render_card(card)
        strings = [call.args[2] for call in text.call_args_list]
        self.assertFalse(any("HP" in value or "HERO 1" in value or "血量" in value for value in strings))
        self.assertTrue(all(image.pixelColor(x, y).alpha() == 0
                            for x in range(70) for y in range(77, 120)))

    def test_real_hp_is_a_three_pixel_proportional_underline(self):
        image = render_card(RobotCard(1, "HERO", L.ALIVE, health=50, max_health=100))
        self.assertEqual(image.pixelColor(10, 74).name(), "#c7eab7")
        self.assertEqual(image.pixelColor(50, 74).alpha(), 36)
        self.assertEqual(image.pixelColor(10, 72).alpha(), 0)
        self.assertEqual(image.pixelColor(10, 76).alpha(), 0)
        self.assertTrue(all(image.pixelColor(10, y).alpha() > 0 for y in (73, 74, 75)))

    def test_no_denominator_no_hp_track_even_for_local_or_dead(self):
        for card in (RobotCard(3, "INF-1", L.ALIVE, health=90),
                     RobotCard(3, "INF-1", L.ALIVE, local=True, health=90),
                     RobotCard(3, "INF-1", L.DEAD, health=0),
                     RobotCard(3, "INF-1", L.ALIVE, health=90, max_health=0),
                     RobotCard(3, "INF-1", L.ALIVE, health=110, max_health=100)):
            with self.subTest(card=card):
                image = render_card(card)
                self.assertTrue(all(image.pixelColor(x, 74).alpha() == 0 for x in range(70)))
        with patch.object(strip, "_text", wraps=strip._text) as text:
            render_card(RobotCard(3, "INF-1", L.ALIVE, health=90))
        self.assertIn("90", [call.args[2] for call in text.call_args_list])

    def test_unknown_and_non_hp_roles_cannot_acquire_a_ratio(self):
        for card in (RobotCard(3, "INF-1", L.UNKNOWN, health=90, max_health=100),
                     RobotCard(6, "UAV", L.ALIVE, health=90, max_health=100, health_applicable=False)):
            image = render_card(card)
            self.assertTrue(all(image.pixelColor(x, 74).alpha() == 0 for x in range(70)))

    def test_dead_grayscale_and_skull_are_independent_of_show_kills(self):
        avatar = QImage(140, 140, QImage.Format_ARGB32_Premultiplied)
        avatar.fill(QColor("#ed38a0"))
        with patch.object(strip, "_skull", wraps=strip._skull) as skull:
            dead = render_card(RobotCard(3, "INF-1", L.DEAD), supplied=avatar)
        self.assertEqual([call.args[3] for call in skull.call_args_list], [16])
        gray = dead.pixelColor(30, 30)
        self.assertLessEqual(max(gray.red(), gray.green(), gray.blue()) - min(gray.red(), gray.green(), gray.blue()), 1)
        self.assertGreater(dead.pixelColor(55, 8).alpha(), gray.alpha())
        self.assertLess(gray.alpha(), 128)
        with patch.object(strip, "_skull", wraps=strip._skull) as skull:
            unknown = render_card(RobotCard(3, "INF-1", L.UNKNOWN), supplied=avatar)
        skull.assert_not_called()
        color = unknown.pixelColor(15, 25)
        self.assertGreater(max(color.red(), color.green(), color.blue()) - min(color.red(), color.green(), color.blue()), 50)
        self.assertNotEqual(dead, unknown)

    def test_model_scores_timer_and_unknown_counts_are_not_reinterpreted(self):
        frame = fixture_frame(unknown=True)
        before = asdict(frame)
        with patch.object(strip, "_text", wraps=strip._text) as text:
            image, layout = render(frame)
        values = [call.args[2] for call in text.call_args_list]
        self.assertIn(frame.clock_text, values)
        self.assertIn("?", values)
        self.assertIn("—", values)
        self.assertNotIn("0", values)
        self.assertEqual(asdict(frame), before)
        self.assertFalse(layout.compact)
        self.assertGreater(image.pixelColor(round(layout.center.x + 54), 25).alpha(), 0)
        known = fixture_frame()
        with patch.object(strip, "_text", wraps=strip._text) as text:
            render(known)
        values = [call.args[2] for call in text.call_args_list]
        for value in ("1:23", "0", "3", "4", "RM SCORE", "GROUND ALIVE"):
            self.assertIn(value, values)

    def test_3v3_12_and_14_vehicles_and_uneven_rosters_fit_at_dpi(self):
        for left_count, right_count in ((3, 3), (6, 6), (7, 7), (2, 7), (12, 14)):
            cards = tuple(RobotCard(i, str(i), L.ALIVE) for i in range(1, left_count + 1))
            other = tuple(RobotCard(i + 100, str(i), L.UNKNOWN) for i in range(1, right_count + 1))
            frame = MatchBarFrame(TeamStrip("Red", cards), TeamStrip("Blue", other), 420)
            for width in (800, 1280, 2560):
                for dpr in (1, 1.5, 2):
                    with self.subTest(rosters=(left_count, right_count), width=width, dpr=dpr):
                        image, layout = render(frame, width=width, dpr=dpr, options=TopMatchBarOptions(
                            scale=1, safe_left=190, safe_right=190, show_health=True))
                        self.assertGreaterEqual(layout.bounds.x, 190 - 1e-6)
                        self.assertLessEqual(layout.bounds.right, width - 190 + 1e-6)
                        self.assertAlmostEqual(layout.center.x + layout.center.width / 2, width / 2)
                        self.assertTrue(QRectF(0, 0, width, 180).contains(strip._qr(layout.bounds)))
                        if not layout.compact:
                            self.assertEqual(len(layout.left_cards), left_count)
                            self.assertEqual(len(layout.right_cards), right_count)
                            for rect in layout.left_cards + layout.right_cards:
                                self.assertAlmostEqual(rect.width, rect.height)
                                self.assertFalse(strip._qr(rect).intersects(strip._qr(layout.center)))
                        self.assertEqual(image.pixelColor(5, 5).alpha(), 0)

    def test_static_avatar_and_all_text_layers_are_reused_but_values_update(self):
        renderer, frame = TopMatchBarRenderer(), fixture_frame()
        first, layout = render(frame, renderer=renderer)
        avatars = tuple(renderer._avatar_layers.values())
        with patch.object(strip, "_text", wraps=strip._text) as text:
            repeat, repeated_layout = render(frame, renderer=renderer)
        text.assert_not_called()
        self.assertEqual(first, repeat)
        self.assertIs(layout, repeated_layout)
        changed = replace(frame, countdown=82, left=replace(frame.left, score=7, cards=(
            replace(frame.left.cards[0], health=70, kills=3), *frame.left.cards[1:])))
        with patch.object(strip, "_text", wraps=strip._text) as text:
            live, _ = render(changed, renderer=renderer)
        self.assertNotEqual(live, first)
        self.assertEqual(tuple(renderer._avatar_layers.values()), avatars)
        for value in ("1:22", "7", "70"):
            self.assertIn(value, [call.args[2] for call in text.call_args_list])

    def test_authorized_avatar_changes_and_language_and_density_refresh_layers(self):
        renderer = TopMatchBarRenderer()
        avatar = QImage(140, 140, QImage.Format_ARGB32_Premultiplied)
        avatar.fill(Qt.red)
        frame = fixture_frame()
        first, _ = render(frame, renderer=renderer, avatars={"101": avatar})
        avatar.fill(Qt.blue)
        second, _ = render(frame, renderer=renderer, avatars={"101": avatar})
        self.assertNotEqual(first, second)
        en, _ = render(frame, renderer=renderer)
        zh, _ = render(frame, renderer=renderer, options=TopMatchBarOptions(scale=1, show_health=True, chinese=True))
        self.assertNotEqual(en, zh)
        restored, _ = render(frame, renderer=renderer)
        self.assertEqual(en, restored)
        render(frame, renderer=renderer, dpr=2)
        self.assertTrue(any(image.width() >= 140 for image in renderer._avatar_layers.values()))

    def test_small_cjk_labels_keep_ink_inside_their_rows_at_real_dpi(self):
        for dpr in (1, 1.5, 2):
            for text in ("裁判比分", "地面存活", "无数据", "已暂停"):
                image = QImage(round(128*dpr), round(30*dpr), QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                try:
                    TopMatchBarRenderer()._paint_cached_text(painter, QRectF(10, 8, 108, 14), text,
                        strip._label_font("DejaVu Sans", 12, text), QColor("white"))
                finally:
                    painter.end()
                ink = [(x,y) for y in range(image.height()) for x in range(image.width())
                       if image.pixelColor(x,y).alpha() > 0]
                self.assertGreater(len(ink), 60)
                self.assertGreater(min(y for _,y in ink), round(7*dpr))
                self.assertLess(max(y for _,y in ink), round(24*dpr))
                self.assertGreater(min(x for x,_ in ink), 0)
                self.assertLess(max(x for x,_ in ink), image.width()-1)

    def test_static_caches_are_bounded(self):
        renderer = TopMatchBarRenderer()
        for n in range(150):
            render(replace(fixture_frame(), countdown=n), renderer=renderer)
        self.assertLessEqual(len(renderer._text_layers), 128)
        self.assertLessEqual(len(renderer._avatar_layers), 64)
        self.assertLessEqual(len(renderer._portraits), 64)

    def test_six_digit_scores_and_partial_unknown_counts_are_complete(self):
        frame = fixture_frame()
        frame = replace(frame, left=replace(frame.left, score=999999, cards=(
            replace(frame.left.cards[0], life=L.UNKNOWN), *frame.left.cards[1:])))
        with patch.object(strip, "_text", wraps=strip._text) as text:
            render(frame)
        values = [call.args[2] for call in text.call_args_list]
        self.assertIn("999999", values)
        self.assertIn("3+?", values)
        self.assertFalse(any("…" in value for value in values))


class Cs2ControllerLiveCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_qt_fonts()

    def setUp(self):
        registry = build_default_registry()
        self.owner = NS(registry=registry,
            state=NS(match_mode="RMUC7v7", alliance_color="Blue", robot_id=103),
            backend=NS(mqtt=NS(host="offline-fixture", port=3333, disconnected_at=0.0,
                connected=True, receive_generation=0), scenario_key="OfficialEvent",
                referee=NS(profile_id="rm2026-v1.3.1")),
            home_visible=False, hero_deploy_ui=NS(active=False), menu_overlay_active=lambda: False,
            overlay_coordinator=NS(modal=None), dynamic_island_state=NS(y=17, height=30),
            tactical_map_rect=lambda w,h: QRectF(12,58,170,118),
            setting_bool=lambda mod,key,default=False: bool(mod.get_setting(key).value) if mod and mod.get_setting(key) else default,
            setting_mode=lambda mod,key,default: str(mod.get_setting(key).value) if mod and mod.get_setting(key) else default)
        self.controller = TopMatchBarController(self.owner)

    def paint(self, now=10, width=1280):
        image = QImage(width,720,QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            self.controller.paint(painter,width,720,now)
        finally:
            painter.end()
        self.assertEqual(self.controller._last_error, "")
        return image

    def test_exact_expiry_new_packets_and_kills_cannot_freeze(self):
        controller = self.controller
        controller.observe_referee("GameStatus", {"stage_countdown_sec":83,"blue_score":0,"red_score":3}, 10)
        controller.observe_referee("RobotDynamicStatus", {"current_health":90}, 10)
        controller.observe_referee("RobotStaticStatus", {"robot_id":103,"max_health":100}, 10)
        self.paint()
        fresh = controller._frame_cache
        self.paint(now=12.5)
        self.assertIs(controller._frame_cache, fresh)
        self.paint(now=12.50001)
        expired = controller._frame_cache
        self.assertIsNone(expired.countdown)
        self.assertIsNone(expired.left.score)
        self.assertTrue(all(card.life == L.UNKNOWN for card in expired.left.cards))
        controller.observe_referee("GameStatus", {"stage_countdown_sec":82,"blue_score":4}, 13)
        self.paint(now=13)
        self.assertEqual(controller._frame_cache.left.score,4)
        self.assertEqual(controller._frame_cache.countdown,82)
        controller.feed._kills[103] = 2
        self.paint(now=13)
        self.assertEqual(next(c.kills for c in controller._frame_cache.left.cards if c.robot_id==103),2)
        self.owner.backend.mqtt.connected=False
        self.paint(now=13)
        self.assertIsNone(controller._frame_cache.countdown)

    def test_hot_controller_has_no_text_layout_or_drawtext_work(self):
        self.paint()
        with patch.object(strip,"_text",wraps=strip._text) as text, \
             patch.object(controller_module,"draw_ui_text",wraps=controller_module.draw_ui_text) as systems:
            self.paint(now=10.01)
        text.assert_not_called()
        systems.assert_not_called()
        self.assertGreaterEqual(self.controller.last_layout.bounds.y, 62)

    def test_narrow_corridor_still_keeps_timer_and_count_strip(self):
        self.owner.registry.get("TacticalMap").enabled=False
        self.owner.registry.get("HUD").get_setting("Right Display").value="ModuleListHud"
        self.owner.registry.get("HUD").get_setting("ModuleList Style").value="PolarTextList"
        self.paint(width=650)
        layout=self.controller.last_layout
        self.assertIsNotNone(layout)
        self.assertTrue(layout.compact)
        self.assertGreaterEqual(layout.bounds.x,288)
        self.assertLessEqual(layout.bounds.right,650-288)

    def test_host_owned_avatars_flow_into_the_integrated_strip(self):
        avatar=QImage(140,140,QImage.Format_ARGB32_Premultiplied)
        avatar.fill(Qt.red)
        self.owner.top_match_bar_avatars={"103":avatar}
        first=self.paint()
        avatar.fill(Qt.blue)
        second=self.paint()
        self.assertNotEqual(first,second)

    def test_real_support_system_pixels_and_locale_cache_follow_live_state(self):
        frame = replace(fixture_frame(),
            left=replace(fixture_frame().left, systems=(RobotCard(108,"DART",L.ALIVE),RobotCard(109,"RADAR",L.DEAD))),
            right=replace(fixture_frame().right, systems=(RobotCard(8,"DART",L.UNKNOWN),RobotCard(9,"RADAR",L.ALIVE))))
        before=asdict(frame)
        layout=strip._strip_layout(1280,6,6,1,5,12,12)
        def systems_image(sample,chinese=False):
            image=QImage(1280,180,QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter=QPainter(image)
            try:
                bottom=TopMatchBarController._paint_systems(painter,sample,layout,chinese=chinese)
            finally:
                painter.end()
            self.assertEqual(bottom,layout.bounds.bottom+18)
            return image
        controller_module._systems_layer.cache_clear()
        with patch.object(controller_module,"draw_ui_text",wraps=controller_module.draw_ui_text) as text:
            en=systems_image(frame)
        self.assertEqual(text.call_count,2)
        self.assertIn("DART 108: ALIVE  ·  RADAR 109: DOWN", [call.args[2] for call in text.call_args_list])
        with patch.object(controller_module,"draw_ui_text",wraps=controller_module.draw_ui_text) as text:
            again=systems_image(frame)
        text.assert_not_called()
        self.assertEqual(en,again)
        with patch.object(controller_module,"draw_ui_text",wraps=controller_module.draw_ui_text) as text:
            zh=systems_image(frame,True)
        self.assertIn("飞镖 108: 存活  ·  雷达 109: 已毁",[call.args[2] for call in text.call_args_list])
        self.assertNotEqual(zh,en)
        changed=replace(frame,left=replace(frame.left,systems=(RobotCard(108,"DART",L.UNKNOWN),RobotCard(109,"RADAR",L.DEAD))))
        self.assertNotEqual(systems_image(changed),en)
        self.assertEqual(asdict(frame),before)


def write_evidence(destination):
    """Synthetic data, actual QPainter pixels; not a live-match screenshot."""
    app=QApplication.instance() or QApplication([])
    ensure_qt_fonts()
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    for name,frame in (("known-12",fixture_frame()),("unknown-12",fixture_frame(unknown=True)),
                       ("known-14",fixture_frame(seven=True))):
        image,_=render(frame,dpr=2,options=TopMatchBarOptions(scale=1,show_health=True,chinese=True))
        background=QImage(image.size(),QImage.Format_ARGB32_Premultiplied)
        background.setDevicePixelRatio(2)
        background.fill(QColor("#495350"))
        painter=QPainter(background)
        painter.drawImage(0,0,image)
        painter.end()
        path=destination/f"cs2-{name}-qt.png"
        if not background.save(str(path)):
            raise OSError(f"Could not save {path}")
    return destination


if __name__=="__main__":
    unittest.main()
