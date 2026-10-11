"""Offline actual-renderer coverage for status surfaces, languages and caches.

Inventory: island toast/event/rune/idle branches and five title kinds;
watermark CAM/SYN, three scenes, two matches, both MQTT/serial/CC states,
all seven KM states, DT7 mock/real/unopened/pressed/pending/error/conflict;
compact/full compass SPIN/FOLLOW/FIELD/FREE, REL and N.  POLAR-RM, FPS,
protocol names, ports, custom names and unknown diagnostics stay recognizable.
"""
import ast
import copy
import itertools
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication
from rm_client.backend.dt7_link import status_token
from rm_client.match_modes import MATCH_MODES
from rm_client.model import build_default_registry
from rm_client.scenarios import SCENARIOS
from rm_client.ui.animation import Easings
from rm_client.ui.jello_locale import chinese_enabled, TOAST_ZH
from rm_client.ui.paint import with_alpha
from rm_client.ui.polar.renderers.dynamic_island import DynamicIslandMixin
from rm_client.ui.status_locale import STATUS_ZH, dt7_display_token, status_event_text, status_text
from rm_client.ui.theme import THEME, color

APP = QApplication.instance() or QApplication([])


def app_methods():
    """Compile exact app methods without constructing hardware/GL/audio owners."""
    source = (ROOT / "rm_client/ui/polar_app.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PolarRMWindow")
    names = {"draw_watermark", "draw_chassis_gimbal_indicator", "draw_chassis_gimbal_compass_base", "chassis_follow_mode"}
    selected = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == names
    compiled = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name="WindowMethods", bases=[], keywords=[], body=selected, decorator_list=[])], type_ignores=[])
    scope = dict(QPointF=QPointF, QRectF=QRectF, Qt=Qt, QBrush=QBrush, QFont=QFont,
                 QImage=QImage, QPainter=QPainter, QPen=QPen, QLinearGradient=QLinearGradient,
                 math=math, time=NS(perf_counter=lambda: 100.0), THEME=THEME, color=color,
                 Easings=Easings, with_alpha=with_alpha, glow_text=lambda *args: None,
                 glow_rect=lambda *args: None, chinese_enabled=chinese_enabled,
                 status_text=status_text, dt7_display_token=dt7_display_token, _dt7_status_token=status_token,
                 normalize_angle_deg=lambda value: (value + 180) % 360 - 180)
    exec(compile(ast.fix_missing_locations(compiled), "status_display_methods", "exec"), scope)
    return scope["WindowMethods"]


class Host(DynamicIslandMixin, app_methods()):
    def __init__(self, language="简体中文"):
        self.registry = build_default_registry()
        self.language(language)
        self.registry.get("RuneRingStatus").enabled = False
        self.registry.get("ChassisGimbalIndicator").enabled = True
        self.registry.get("SpinMode").enabled = False
        self.registry.get("ChassisGimbalIndicator").get_setting("Style").value = "Compass"
        self.state = NS(last_event="", match_duration_sec=420, stage_countdown_sec=210,
                        fps=120.0, mqtt_connected=False, serial_connected=False,
                        camera_connected=False, polar_spin_note="", rune_status={},
                        chassis_yaw_deg=20.0, gimbal_yaw_deg=35.0)
        self.scenario_manager = NS(current=SCENARIOS["LabDebug"])
        self.match_mode_manager = NS(current=MATCH_MODES["RMUC7v7"])
        self.toasts = []
        self.dynamic_island_last_event = ""
        self.dynamic_island_event_started = 0.0
        self.mqtt = NS(mock_output=True)
        self.control = NS(mock_output=True, radio_km_link_state="off", radio_km_robot_rx=17,
                          cc_enabled=False, dt7_enabled=False, dt7_link=NS(mock_output=True,
                          resolved_port="", wire_neutral=True), dt7_release_pending=False,
                          dt7_last_error="", dt7_mouse_note="", km_source_conflict="")
        self._watermark_title_cache = QImage()
        self._watermark_title_static_key = None
        self._watermark_title_cache_key = None
        self._watermark_cache_next_refresh_at = 0.0
        self.texts = []
        self.scratch_keys = []
        self.density = "CombatCompact"
        self.anim = NS(value=lambda *args, **kwargs: args[1])
        self.island_targets = []
        self.dynamic_island_state = NS(content=NS(progress=1.0))
        def target(x, y, w, h, radius, **kwargs):
            self.island_targets.append((x, y, w, h, radius, kwargs))
            self.dynamic_island_state.x=x; self.dynamic_island_state.y=y
            self.dynamic_island_state.width=w; self.dynamic_island_state.height=h
        self.dynamic_island_state.set_target_geometry = target
        self.dynamic_island_morph = NS(set_target=lambda *args, **kwargs: None, update=lambda **kwargs: self.dynamic_island_state.content.progress)

    def language(self, value):
        self.registry.get("ClickGui").get_setting("Language").value = value

    def font(self, family, size, *args):
        font = QFont("Sans Serif"); font.setPointSizeF(size); return font

    def draw_text(self, painter, rect, text, *args):
        self.texts.append((rect.getRect(), str(text)))

    draw_glass_text = draw_text
    devicePixelRatioF = lambda self: 1.0
    hud_accent = lambda self: QColor("#55ccff")
    hud_warning = lambda self: QColor("#ffcc00")
    hud_danger = lambda self: QColor("#ff0000")
    hud_success = lambda self: QColor("#00ff00")
    hud_clean = lambda self: True
    hud_density = lambda self: self.density
    anim_duration = lambda self, value: value
    animated_angle = lambda self, key, value, smooth: value
    text_advance = lambda self, font, text: len(text) * 5.0
    draw_hud_liquid_glass = lambda *args, **kwargs: None
    draw_chassis_body_direction = lambda *args: None
    draw_gimbal_turret_direction = lambda *args: None
    draw_dynamic_island_icon = lambda *args: None
    direction_point = lambda self, center, angle, radius: QPointF(center.x() + radius * math.sin(math.radians(angle)), center.y() - radius * math.cos(math.radians(angle)))

    def setting_bool(self, module, name, default=True):
        setting = module.get_setting(name) if module else None
        return bool(setting.value) if setting else default

    def get_setting_number(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return float(setting.value) if setting else default

    def _gimbal_scratch_image(self, key, width, height, dpr):
        self.scratch_keys.append(key)
        return QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)

    def render(self, method, *args):
        self.texts = []
        image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            getattr(self, method)(painter, *args)
        finally:
            painter.end()
        return [text for _, text in self.texts]

    def raw_snapshot(self):
        return copy.deepcopy((self.state.__dict__, self.control.__dict__, self.toasts,
                              [(m.name, m.enabled, [(s.name, s.value) for s in m.settings]) for m in self.registry.modules]))


class StatusLocaleTests(unittest.TestCase):
    def test_exact_inventory_and_opaque_strings(self):
        for text, translation in STATUS_ZH.items():
            self.assertEqual(status_text(text, False), text)
            self.assertEqual(status_text(text, True), translation)
            self.assertNotEqual(text, translation)
        for text in ("POLAR-RM", "FPS", "COM4", "Custom Warning", "my live mock failure", "Small"):
            self.assertEqual(status_text(text, True), text)
            self.assertEqual(status_event_text(text, True), text)
        self.assertEqual(status_text("REL {angle}", True, angle="+15°"), "相对 +15°")

    def test_island_classifies_original_messages_before_display(self):
        for message in ("ArmorAutoAim enabled", "ClickGUI closed", "Calibration solve failed", "Scenario: 校内模拟", "Radar highlight refreshed"):
            w = Host(); w.toasts = [{"message": message, "created": 99.0, "kind": "raw-kind"}]
            before = w.raw_snapshot()
            expected_kind, expected_color = w.dynamic_message_kind(message)
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                payload = w.dynamic_island_payload()
            self.assertEqual(payload["description"], status_event_text(message, True))
            self.assertNotEqual(payload["description"], message)
            self.assertEqual((payload["kind"], payload["color"]), (expected_kind, expected_color))
            self.assertAlmostEqual(payload["progress"], 2/3)
            self.assertEqual(w.raw_snapshot(), before)
            w.language("English")
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                english = w.dynamic_island_payload()
            self.assertEqual(english["description"], message)
            self.assertEqual(english["kind"], payload["kind"])

    def test_island_titles_both_languages_and_unknown_events(self):
        cases = [("anything", "warning", "Warning"), ("anything", "success", "Success"),
                 ("anything", "module", "Client State"), ("Radar online", "info", "Radar"),
                 ("Custom diagnostic", "info", "POLAR-RM")]
        for language in ("English", "简体中文"):
            w = Host(language)
            for message, kind, title in cases:
                self.assertEqual(w.dynamic_message_title(message, kind), status_text(title, language != "English"))
            w.state.last_event = "Custom error: Small @COM8"
            before = w.raw_snapshot()
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                payload = w.dynamic_island_payload()
            self.assertEqual(payload["description"], w.state.last_event)
            self.assertEqual(payload["title"], status_text("RMUC 7v7", language != "English"))
            self.assertEqual(payload["progress"], .5)
            self.assertEqual(w.dynamic_island_last_event, w.state.last_event)
            self.assertEqual(w.raw_snapshot(), before)

    def test_all_known_toast_events_are_localized_without_mutation(self):
        w = Host()
        for message in TOAST_ZH:
            w.state.last_event = message
            before = w.raw_snapshot()
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                payload = w.dynamic_island_payload()
            self.assertEqual(payload["description"], status_event_text(message, True))
            self.assertEqual(w.raw_snapshot(), before)
        for message in ("Wallpaper loaded: Small", "Import failed: READY", "Scenario: My Custom Scene"):
            rendered = status_event_text(message, True)
            self.assertTrue(rendered.endswith(message.split(": ", 1)[1]))

    def test_island_idle_session_all_connections_and_titles(self):
        for language, mqtt, serial, scene, match in itertools.product(("English", "简体中文"), (False, True), (False, True), SCENARIOS.values(), MATCH_MODES.values()):
            w = Host(language); w.state.mqtt_connected=mqtt; w.state.serial_connected=serial
            w.scenario_manager.current=scene; w.match_mode_manager.current=match
            before = w.raw_snapshot()
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                payload = w.dynamic_island_payload()
            expected = f'{scene.title} | {status_text(match.title, language != "English")} | 120 FPS | {status_text("MQTT live" if mqtt else "MQTT mock", language != "English")} | {status_text("SERIAL live" if serial else "SERIAL mock", language != "English")}'
            self.assertEqual(payload["description"], expected)
            self.assertEqual((payload["active"], payload["kind"], payload["title"], payload["progress"]), (False, "info", "POLAR-RM", 1.0))
            self.assertEqual(w.raw_snapshot(), before)

    def test_island_rune_branch_remains_numeric_and_source_unchanged(self):
        for language in ("English", "简体中文"):
            w=Host(language); w.registry.get("RuneRingStatus").enabled=True
            w.state.rune_status={"average_rings": 5.5, "activated_arms": 3}
            before=w.raw_snapshot()
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                payload=w.dynamic_island_payload()
            self.assertEqual(payload["title"], "能量机关")
            self.assertEqual(payload["description"], "平均环数 5.5 / 灯臂 3  ·  推算总环 16.5")
            self.assertEqual(w.raw_snapshot(), before)

    def test_island_painter_both_states_and_live_language_switch(self):
        w=Host(); w.toasts=[{"created": 99.0, "message": "Calibration solve failed"}]
        for method, content in itertools.product(("draw_dynamic_island", "_draw_dynamic_island_legacy"), (0.0, 1.0)):
            w.dynamic_island_state.content.progress=content
            with patch("rm_client.ui.polar.renderers.dynamic_island.time.perf_counter", return_value=100.0):
                w.language("简体中文"); zh=w.render(method, 1280)
                w.language("English"); en=w.render(method, 1280)
            self.assertEqual(zh, ["警告", "标定计算失败"])
            self.assertEqual(en, ["Warning", "Calibration solve failed"])
            self.assertEqual(w.toasts[0]["message"], "Calibration solve failed")

    def test_watermark_all_connection_and_km_states(self):
        km_formats={"off":"KM off", "blocked":"KM blocked", "no-readback":"KM on(?)", "live":"KM live↑{count}", "silent":"KM NO-RX!!", "stalled":"KM stall@{count}", "unknown":"KM ?"}
        for language, connected, km, scene, match in itertools.product(("English", "简体中文"), (False, True), km_formats, SCENARIOS.values(), MATCH_MODES.values()):
            w=Host(language); w.state.camera_connected=connected; w.mqtt.mock_output=not connected
            w.scenario_manager.current=scene; w.match_mode_manager.current=match
            w.control.mock_output=not connected; w.control.cc_enabled=connected; w.control.radio_km_link_state=km
            before=w.raw_snapshot(); output=w.render("draw_watermark")
            chinese=language != "English"
            self.assertEqual(output[0], "120 FPS")
            self.assertEqual(output[1].split(" | "), [status_text("CAM" if connected else "SYN",chinese), scene.title, status_text(match.title,chinese), status_text("MQTT live" if connected else "MQTT mock",chinese), status_text("SERIAL live" if connected else "SERIAL mock",chinese), status_text(km_formats[km],chinese,count=17), status_text("CC on" if connected else "CC off",chinese)])
            self.assertEqual(w.raw_snapshot(),before)

    def test_watermark_cache_reuses_and_invalidates_on_language_immediately(self):
        w=Host("English")
        english=w.render("draw_watermark"); key=w._watermark_title_cache.cacheKey()
        self.assertEqual(w.render("draw_watermark"), [])
        self.assertEqual(w._watermark_title_cache.cacheKey(),key)
        w.language("简体中文"); chinese=w.render("draw_watermark")
        self.assertNotEqual(chinese,english)
        self.assertNotEqual(w._watermark_title_cache.cacheKey(),key)
        self.assertIs(w._watermark_title_static_key[0],True)
        w.language("English")
        self.assertEqual(w.render("draw_watermark"),english)
        self.assertIs(w._watermark_title_static_key[0],False)

    def test_dt7_all_envelopes_keep_exact_raw_diagnostics_and_ports(self):
        for language, mock, port, neutral, pending, error in itertools.product(("English", "简体中文"), (False,True), ("", "COM9", "/dev/real(mock)@端口"), (False,True), (False,True), ("", "mock real(线上仍带按键) READY error_42")):
            args=dict(mock_output=mock,resolved_port=port,wire_neutral=neutral,release_pending=pending,last_error=error)
            raw=status_token(**args)
            translated=dt7_display_token(raw,language != "English",resolved_port=port)
            if language == "English": self.assertEqual(translated,raw)
            else: self.assertTrue(translated.startswith("DT7:模拟" if mock else "DT7:真实输出"))
            if not mock and port: self.assertIn("@"+port,translated)
            if not neutral: self.assertIn("(线上仍带按键)",translated)
            if pending: self.assertIn("(松手帧未送达!)",translated)
            if error: self.assertTrue(translated.endswith("(!"+error[:40]+")"))
            self.assertEqual(status_token(**args),raw)
            # Exercise the exact app method too, including resolved-port forwarding.
            w=Host(language); w.control.dt7_enabled=True
            w.control.dt7_link=NS(mock_output=mock, resolved_port=port, wire_neutral=neutral)
            w.control.dt7_release_pending=pending; w.control.dt7_last_error=error
            before=w.raw_snapshot()
            self.assertTrue(w.render("draw_watermark")[-1].endswith(" | " + translated))
            self.assertEqual(w.raw_snapshot(),before)
        for raw in ("DT7:future(!mock)","DT7:mock custom text","DT7:real@unknown"):
            self.assertEqual(dt7_display_token(raw,True),raw)

    def test_watermark_dt7_annotations_preserve_state_and_unknown_conflict(self):
        w=Host(); w.control.dt7_enabled=True
        w.control.dt7_link=NS(mock_output=False,resolved_port="COM18",wire_neutral=False)
        w.control.dt7_release_pending=True; w.control.dt7_last_error="permission denied: mock@Small"
        w.control.dt7_mouse_note="raw arbitration"; w.state.polar_spin_note="raw spin"
        before=w.raw_snapshot(); output=w.render("draw_watermark")[-1]
        self.assertIn("DT7:真实输出@COM18(线上仍带按键)(松手帧未送达!)(!permission denied: mock@Small)",output)
        self.assertIn("(鼠标被上位机云台顶掉)(自转没发·详见日志)", output.replace(" ",""))
        self.assertEqual(w.raw_snapshot(),before)
        w.control.km_source_conflict="opaque mock conflict Small"
        before=w.raw_snapshot(); output=w.render("draw_watermark")[-1]
        self.assertTrue(output.endswith("KM冲突(!)opaque mock conflict Small"))
        self.assertEqual(w.raw_snapshot(),before)

    def test_compact_full_compass_modes_geometry_and_values(self):
        for density, follow, spin in itertools.product(("CombatCompact","Full"),("Gimbal","Field","Free"),(False,True)):
            w=Host("English"); w.density=density
            w.registry.get("ChassisAssist").get_setting("Follow").value=follow
            w.registry.get("SpinMode").enabled=spin
            mode="SPIN" if spin else {"Gimbal":"FOLLOW","Field":"FIELD","Free":"FREE"}[follow]
            before=w.raw_snapshot(); en=w.render("draw_chassis_gimbal_indicator",1280,720)
            en_rects=[rect for rect,_ in w.texts]
            self.assertIn(mode,en); self.assertIn("N",en)
            self.assertIn("+15°" if density=="CombatCompact" else "REL +15°",en)
            self.assertEqual(w.raw_snapshot(),before)
            w.language("简体中文"); before=w.raw_snapshot()
            zh=w.render("draw_chassis_gimbal_indicator",1280,720)
            self.assertIn(status_text(mode,True),zh); self.assertIn("北",zh)
            self.assertIn("+15°" if density=="CombatCompact" else "相对 +15°",zh)
            self.assertEqual([rect for rect,_ in w.texts],en_rects)
            self.assertEqual(w.scratch_keys[0],w.scratch_keys[1])  # reused buffer is fully repainted
            self.assertEqual(w.raw_snapshot(),before)
            w.language("English")
            self.assertEqual(w.render("draw_chassis_gimbal_indicator",1280,720),en)

    def test_compass_visibility_flags_still_control_labels(self):
        w=Host(); module=w.registry.get("ChassisGimbalIndicator")
        module.get_setting("Show Angle").value=False; module.get_setting("Show Mode").value=False
        for density in ("CombatCompact","Full"):
            w.density=density
            self.assertEqual(w.render("draw_chassis_gimbal_indicator",1280,720),["北"])
        module.enabled=False
        self.assertEqual(w.render("draw_chassis_gimbal_indicator",1280,720),[])


if __name__ == "__main__":
    unittest.main()
