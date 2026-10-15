"""Bounded inventory and real offscreen Hero rendering, without live I/O.

Translated: headers, subtitle, phase/countdown, six control labels and their
confirmations/tooltips, chart title/invalid message/footer/stock target enums,
seven telemetry row labels and status words, first readiness/timeout/backend
safety reason, all rule lines, closed-console banner/close tooltip, native
video waiting/lost and general video-lost copy. All static copy is HERO_ZH.

Intentionally unchanged: H/check/cross/warning icons, numeric telemetry and
units, 42 mm/16.5 m/s/25% values, RM2026/0x0310/MQTT/QoS and protocol/profile
identifiers, raw internal phases/readiness/errors, action IDs, confirm/pending
state, user-defined targets and unrecognized external error/exception text.
Only known backend diagnostic templates translate, with opaque details intact.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("POLAR_DISABLE_LOCAL_CAPTURE", "1")
os.environ.setdefault("POLAR_DISABLE_MEDIA_PRELOAD", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import build_default_registry
from rm_client.ui.hero_deploy import HeroDeployInterfaceState, HeroDeployRenderer
from rm_client.ui.hero_locale import (
    HERO_DIAGNOSTIC_ZH, HERO_READINESS_REASONS, HERO_ZH,
    hero_diagnostic, hero_phase, hero_target, hero_text,
)
from rm_client.ui.jello_locale import chinese_enabled

MIXIN = ROOT / "rm_client/ui/polar/mixins/video_backend_mixin.py"
ACTIONS = ("hero_deploy_enter", "hero_deploy_exit", "hero_lob_preview",
           "hero_lob_arm", "hero_lob_disarm", "hero_deploy_close")
BUTTONS = ("ENTER DEPLOY", "EXIT DEPLOY", "PREVIEW", "ARM ASSIST", "DISARM", "CLOSE")


def display_methods():
    """Compile the production display methods, avoiding window/device setup."""
    tree = ast.parse(MIXIN.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    names = {"draw_hero_deploy_interface", "draw_hero_native_background", "draw_backend_video_lost"}
    body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                             ast.ClassDef(name="Window", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
    scope = dict(QRectF=QRectF, Qt=Qt, QColor=QColor, QPainter=QPainter,
                 hero_text=hero_text, chinese_enabled=chinese_enabled,
                 rounded_rect=lambda *args: None, color=lambda *args: None,
                 GlassOwner=NS(HERO_DEPLOY="hero"),
                 HeroLobPlanner=NS(preview_from_state=lambda *args, **kwargs: (
                     NS(reachable=True, yaw_deg=2, pitch_deg=45, flight_time_s=2),
                     NS(ready=True, reasons=()))))
    exec(compile(ast.fix_missing_locations(module), str(MIXIN), "exec"), scope)
    return scope["Window"]


class HeroDisplayLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def inputs(self, language="English", *, status=0, pending=None, confirm=None,
               progress=1.0, visible=True, reachable=True, ready=True, online=True,
               reason="", error="", target="Enemy Base"):
        registry = build_default_registry()
        if language is not None:
            registry.get("ClickGui").get_setting("Language").value = language
        module = registry.get("HeroLob")
        module.get_setting("Target").value = target
        module.get_setting("Distance").value = 18.5
        interface = HeroDeployInterfaceState()
        interface.visible = visible
        interface.presentation.progress = progress
        interface.pending_mode = pending
        interface.pending_at = 9.0 if pending is not None else 0.0
        interface.confirm_mode = confirm
        interface.confirm_until = 12.0 if confirm is not None else 0.0
        interface.last_error = error
        state = NS(deploy_mode=status, native_gimbal_online=online, native_bullet_speed=16.5,
                   current_heat=3, max_heat=200, remaining_ammo=12, hero_lob_armed=True)
        solution = NS(reachable=reachable, yaw_deg=-2.25, pitch_deg=45.5, flight_time_s=2.35)
        readiness = NS(ready=ready, reasons=(reason,) if reason else ())
        return dict(registry=registry, module=module, interface=interface, state=state,
                    solution=solution, readiness=readiness, now=10.0)

    def draw(self, inputs, width=1280, height=720, *, fallback=False):
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        texts = []
        def text_drawer(p, rect, text, font, colour, align):
            texts.append((rect.getRect(), text, font.toString(), colour.rgba(), int(align)))
        try:
            hits = HeroDeployRenderer().draw(painter, width, height,
                                            text_drawer=None if fallback else text_drawer, **inputs)
        finally:
            painter.end()
        return texts, hits, bytes(image.constBits())

    def assert_same_geometry_actions(self, en, zh):
        self.assertEqual([(r, f, c, a) for r, _, f, c, a in en[0]],
                         [(r, f, c, a) for r, _, f, c, a in zh[0]])
        self.assertEqual([(h.rect.getRect(), h.action, h.enabled) for h in en[1]],
                         [(h.rect.getRect(), h.action, h.enabled) for h in zh[1]])
        # Text is captured, while the real painter still draws every shape,
        # trajectory and glass fallback. All non-text pixels must be identical.
        self.assertEqual(en[2], zh[2])

    def test_real_draw_all_phases_sizes_preserves_geometry_colours_and_actions(self):
        cases = (
            {}, dict(status=1), dict(pending=1), dict(status=1, pending=0),
            dict(confirm=1), dict(status=1, confirm=0),
            dict(reachable=False, ready=False, online=False, reason="gimbal offline"),
            dict(error="DeployModeStatusSync timeout"), dict(progress=.1),
            dict(progress=.7), dict(progress=.9, visible=False),
            dict(progress=0, visible=False),
        )
        for size in ((640, 360), (1000, 620), (1280, 720), (1920, 1080)):
            for case in cases:
                with self.subTest(size=size, case=case):
                    english = self.draw(self.inputs("English", **case), *size)
                    chinese = self.draw(self.inputs("简体中文", **case), *size)
                    self.assert_same_geometry_actions(english, chinese)
                    if english[1]:
                        self.assertEqual(tuple(h.action for h in english[1]), ACTIONS)
                        self.assertIn("HERO LOB", [t[1] for t in english[0]])
                        self.assertIn("英雄吊射", [t[1] for t in chinese[0]])
                        self.assertTrue(all(en.tooltip != zh.tooltip for en, zh in zip(english[1], chinese[1])))

    def test_static_inventory_is_covered_by_real_renderer_and_english_is_unchanged(self):
        seen = set()
        for case in ({}, dict(status=1), dict(reachable=False, ready=False, online=False),
                     dict(pending=1), dict(status=1, pending=0), dict(confirm=1), dict(status=1, confirm=0)):
            en = self.draw(self.inputs("English", **case))[0]
            zh = self.draw(self.inputs("简体中文", **case))[0]
            for before, after in zip(en, zh):
                seen.add(before[1])
                if before[1] in HERO_ZH:
                    self.assertEqual(after[1], HERO_ZH[before[1]])
                    self.assertNotEqual(before[1], after[1])
                elif before[1].startswith(("ENTERING", "EXITING")):
                    self.assertEqual(after[1], hero_phase(before[1], True))
                elif before[1].startswith("CONFIRM "):
                    self.assertEqual(after[1], "确认" + HERO_ZH[before[1][8:]])
                elif before[1].startswith("TARGET "):
                    self.assertEqual(after[1], "目标 敌方基地  ·  距离 18.5 m")
                else:
                    self.assertIn(before[1], {"H", "✓", "!", "×", "-2.25 / +45.50°",
                                              "2.35 s", "16.50 m/s", "3/200 · 12"})
                    self.assertEqual(before[1], after[1])
        # The complete static map must be exercised, except declared templates
        # and window-owned banner/video copy covered by tests below.
        window_owned = {"DEPLOYED · VIDEO CUT · K TO OPEN", "Open Hero deploy console",
                        "Close Hero deploy controls", "VIDEO SIGNAL LOST · WAITING FOR FRESH DECODED FRAME",
                        "WAITING FOR NATIVE 0x0310 COMPRESSED VIDEO", "NATIVE 0x0310 VIDEO LOST · NO CAMERA FALLBACK"}
        self.assertEqual(set(HERO_ZH) - seen, window_owned | {key for key in HERO_ZH if "{" in key})
        self.assertIn("-2.25 / +45.50°", seen)
        self.assertIn("16.50 m/s", seen)
        self.assertIn("2.35 s", seen)
        self.assertIn("3/200 · 12", seen)

    def test_all_readiness_and_backend_diagnostics_translate_without_mutating_sources(self):
        dynamic = (
            "HeroDeployModeEventCommand exceeds 10 Hz",
            "rm2026-v1.1.0-student-readonly: READ ONLY; no control/economy uplink",
            "rm2026-v1.3.1: not an official uplink topic: HeroDeployModeEventCommand",
            "rm2026-v1.3.1: QoS must be 0..1",
            "invalid HeroDeployModeEventCommand: custom schema CHECK",
        )
        for reason in (*HERO_READINESS_REASONS, *HERO_DIAGNOSTIC_ZH, *dynamic):
            for error in (False, True):
                with self.subTest(reason=reason, error=error):
                    inputs = self.inputs("简体中文", reason="gimbal offline" if error else reason,
                                         error=reason if error else "")
                    raw = (deepcopy(vars(inputs["state"])), deepcopy(vars(inputs["readiness"])),
                           deepcopy(vars(inputs["solution"])), inputs["interface"].last_error)
                    texts, _, _ = self.draw(inputs, 640, 360)
                    self.assertIn(hero_diagnostic(reason, True), [t[1] for t in texts])
                    self.assertNotEqual(hero_diagnostic(reason, True), reason)
                    self.assertEqual(hero_diagnostic(reason, False), reason)
                    self.assertEqual(raw, (vars(inputs["state"]), vars(inputs["readiness"]),
                                           vars(inputs["solution"]), inputs["interface"].last_error))
        # Tie the readiness inventory to every reason currently generated by
        # the planner; newly added safety copy must be consciously classified.
        tree = ast.parse((ROOT / "rm_client/hero_lob.py").read_text())
        emitted = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                emitted.update(kw.value.value for kw in node.keywords
                               if kw.arg == "reason" and isinstance(kw.value, ast.Constant))
                if isinstance(node.func, ast.Attribute) and node.func.attr == "append" and isinstance(node.func.value, ast.Name) and node.func.value.id == "reasons":
                    emitted.add(node.args[0].value)
        self.assertEqual(emitted, set(HERO_READINESS_REASONS))

    def test_custom_text_and_technical_data_are_opaque(self):
        for language in ("English", "简体中文"):
            for text in ("Back", "READY custom", "hero_lob_arm", "ZERO OBSERVED", "Case Sensitive {target}"):
                self.assertEqual(hero_target(text, language != "English"), text)
                self.assertEqual(hero_diagnostic(text, language != "English"), text)
                inputs = self.inputs(language, target=text, error=text)
                texts, _, _ = self.draw(inputs, 640, 360)
                self.assertIn(text, [t[1] for t in texts])
                self.assertTrue(any(text in t[1] for t in texts if "18.5 m" in t[1]))
                self.assertEqual(inputs["module"].get_setting("Target").value, text)
        for target in ("Enemy Base", "Enemy Outpost", "Manual"):
            en = self.draw(self.inputs("English", target=target))[0]
            zh = self.draw(self.inputs("简体中文", target=target))[0]
            self.assertIn(f"TARGET {target.upper()}  ·  RANGE 18.5 m", [t[1] for t in en])
            self.assertIn(f"目标 {hero_target(target, True)}  ·  距离 18.5 m", [t[1] for t in zh])

    def test_language_switch_is_live_and_does_not_advance_confirm_or_pending_state(self):
        inputs = self.inputs("English", confirm=1, pending=1)
        interface = inputs["interface"]
        raw = (interface.phase(0, 10), interface.confirm_mode, interface.confirm_until,
               interface.pending_mode, interface.pending_at, interface.progress)
        english = self.draw(inputs)
        inputs["registry"].get("ClickGui").get_setting("Language").value = "简体中文"
        chinese = self.draw(inputs)
        inputs["registry"].get("ClickGui").get_setting("Language").value = "English"
        self.assertEqual(self.draw(inputs), english)
        self.assert_same_geometry_actions(english, chinese)
        self.assertEqual(raw, (interface.phase(0, 10), interface.confirm_mode, interface.confirm_until,
                               interface.pending_mode, interface.pending_at, interface.progress))
        self.assertEqual(raw[0], "ENTERING 1.0s")
        defaults = self.draw(self.inputs(None))[0]
        self.assertIn("英雄吊射", [t[1] for t in defaults])
        no_registry = self.inputs("English"); del no_registry["registry"]
        self.assertIn("英雄吊射", [t[1] for t in self.draw(no_registry)[0]])

    def test_fallback_qpainter_renders_each_language(self):
        en = self.draw(self.inputs("English"), fallback=True)
        zh = self.draw(self.inputs("简体中文"), fallback=True)
        self.assertNotEqual(en[2], zh[2])
        self.assertEqual([(h.rect, h.action, h.enabled) for h in en[1]],
                         [(h.rect, h.action, h.enabled) for h in zh[1]])

    def test_critical_chinese_copy_fits_at_supported_minimum_window_size(self):
        # PolarRMWindow.setMinimumSize(1000, 620). The smaller 640x360 draw
        # above is a geometry/action stress case, not a supported UI size.
        for reason in (*HERO_DIAGNOSTIC_ZH, *HERO_READINESS_REASONS):
            texts, _, _ = self.draw(self.inputs("简体中文", status=1, confirm=0,
                                               ready=False, online=False, error=reason), 1000, 620)
            for rect, text, font_string, *_ in texts:
                with self.subTest(reason=reason, text=text):
                    font = QFont()
                    font.fromString(font_string)
                    metrics = QFontMetricsF(font)
                    self.assertLessEqual(metrics.horizontalAdvance(text), rect[2])
                    self.assertLessEqual(metrics.height(), rect[3])

    def window(self, language, visible=True):
        window = display_methods()()
        inputs = self.inputs(language, visible=visible, progress=1 if visible else 0)
        window.registry, window.state = inputs["registry"], inputs["state"]
        window.hero_deploy_ui = inputs["interface"]
        window.hero_deploy_renderer = HeroDeployRenderer()
        window.hero_deploy_video_cut_active = lambda: not visible
        window.hero_range_profile_selected = lambda: True
        window.gpu_compositor = NS(push_glass_owner=lambda *args: None, pop_glass_owner=lambda: None)
        window.font = lambda name, size: QFont("Sans", int(size))
        window.draw_hud_liquid_glass = lambda *args, **kwargs: None
        window.draw_dynamic_island_icon = lambda *args: None
        window.hover_point = QPointF(-1, -1)
        window.texts, window.hits = [], []
        window.draw_glass_text = lambda p, rect, text, *args: window.texts.append((rect.getRect(), text))
        window.add_hotspot = lambda rect, action, **kwargs: window.hits.append((rect.getRect(), action, kwargs["tooltip"]))
        return window

    def test_actual_window_callsite_passes_registry_and_localizes_tooltips_and_banner(self):
        for visible in (True, False):
            outputs = {}
            for language in ("English", "简体中文", None):
                window = self.window(language, visible)
                image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
                painter = QPainter(image)
                try:
                    window.draw_hero_deploy_interface(painter, 1280, 720, 10)
                finally:
                    painter.end()
                outputs[language] = (window.texts, window.hits)
            en, zh = outputs["English"], outputs["简体中文"]
            self.assertEqual(outputs[None], zh)
            self.assertEqual([r for r, _ in en[0]], [r for r, _ in zh[0]])
            self.assertEqual([(r, a) for r, a, _ in en[1]], [(r, a) for r, a, _ in zh[1]])
            expected = "HERO LOB" if visible else "DEPLOYED · VIDEO CUT · K TO OPEN"
            self.assertIn(expected, [s for _, s in en[0]])
            self.assertIn(HERO_ZH[expected], [s for _, s in zh[0]])
            tooltip = "Close Hero deploy controls" if visible else "Open Hero deploy console"
            self.assertIn(tooltip, [s for _, _, s in en[1]])
            self.assertIn(HERO_ZH[tooltip], [s for _, _, s in zh[1]])

    def test_video_loss_copy_preserves_internal_states_and_rectangles(self):
        for state, message in (("waiting", "WAITING FOR NATIVE 0x0310 COMPRESSED VIDEO"),
                               ("lost", "NATIVE 0x0310 VIDEO LOST · NO CAMERA FALLBACK"),
                               ("backend", "VIDEO SIGNAL LOST · WAITING FOR FRESH DECODED FRAME")):
            output = {}
            for language in ("English", "简体中文"):
                window = self.window(language)
                window.hero_native_frame_state = lambda now: state
                window.hero_native_image = None
                texts = []
                painter = NS(fillRect=lambda *args: None, setPen=lambda *args: None, setFont=lambda *args: None,
                             drawText=lambda rect, align, text: texts.append((rect.getRect(), int(align), text)))
                if state == "backend":
                    window.draw_backend_video_lost(painter, 1280, 720)
                else:
                    self.assertEqual(window.draw_hero_native_background(painter, 1280, 720), state)
                output[language] = texts
            self.assertEqual(output["English"][0][:2], output["简体中文"][0][:2])
            self.assertEqual(output["English"][0][2], message)
            self.assertEqual(output["简体中文"][0][2], HERO_ZH[message])


if __name__ == "__main__":
    unittest.main()
