"""Real Qt ModList layout regressions; no app, GL, device or backend startup.

Run: .venv/Scripts/python.exe -X utf8 tests/test_module_list_cjk_layout.py
GPU commands and the production Jello shaper are exercised without uploading
textures. CPU tests rasterize into QImage, never capture a desktop window.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Windows' offscreen plugin does not enumerate the installed CJK fonts. A
# QApplication on the native platform is safe here: no widget is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import build_default_registry
from rm_client.ui.clickgui_gpu import ClickGuiDrawList, ClickGuiGpuRenderer
from rm_client.ui.fonts import FontBook
from rm_client.ui.hud_locale import hud_module_name
from rm_client.ui.polar.text_metrics import TextMetricsMixin
from rm_client.ui.polar.renderers import module_list as ml


NAMES = (
    "ArmorAutoAim", "EnergyAutoAim", "AutoSpinOnHit", "Armor3DESP",
    "RobotOverlay", "RadarOverlay", "FrictionWheel", "MapMarker", "SpinMode",
)
PIXELS = {"Normal": 20.0, "Small": 18.0, "Tiny": 14.0}


class Host(ml.ModuleListMixin, TextMetricsMixin):
    def __init__(self, fonts, *, gpu=True):
        self.fonts = fonts
        self.registry = build_default_registry()
        for module in self.registry.modules:
            module.enabled = module.name in NAMES
        self.registry.get("HUD").get_setting("Jello List Animations").value = False
        self.gui_motion = NS(now=1.0)
        self.frame_dt = 0.025
        self._ui_frame_index = 1
        self._jello_active_mods_frame_index = -1
        self._collect_gpu_hud_commands = gpu
        self.clickgui_gpu = ClickGuiGpuRenderer()
        self.clickgui_gpu.available = gpu  # Submit commands only; no GL init.
        self._gpu_hud_commands = ClickGuiDrawList()
        self._jello_hud_shadow = QImage()  # Keep CPU ink tests free of shadows.

    def font(self, key, size):
        return self.fonts.font(key, size)

    def font_line_height(self, font):
        return QFontMetricsF(font).height()

    def setting_mode(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return str(setting.value) if setting else default

    def setting_bool(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return bool(setting.value) if setting else default

    def _client_asset_path(self, *parts):
        return ROOT.joinpath(*parts)

    def height(self):
        return 2000

    def language(self, value):
        self.registry.get("ClickGui").get_setting("Language").value = value

    def size(self, value):
        self.registry.get("HUD").get_setting("Jello List Size").value = value

    def progress(self, value):
        self.registry.get("HUD").get_setting("Jello List Animations").value = True
        self._jello_active_mods_rows = {
            name: {"module": self.registry.get(name), "progress": value, "target": 1.0}
            for name in NAMES
        }
        # Repaint in the same frame: do not advance the animation under test.
        self._jello_active_mods_frame_index = self._ui_frame_index


def draw(host, *, width=1920, height=1080, dpr=1.0, scale=1.0, dpi=96):
    # Command-only tests need a paint device for DPI, not a full framebuffer.
    image = QImage(
        round((8 if host._collect_gpu_hud_commands else width) * dpr),
        round((8 if host._collect_gpu_hud_commands else height) * dpr),
        QImage.Format.Format_RGBA8888,
    )
    image.setDevicePixelRatio(dpr)
    image.setDotsPerMeterX(round(dpi / 0.0254))
    image.setDotsPerMeterY(round(dpi / 0.0254))
    image.fill(0)
    host.clickgui_gpu._pixel_ratio = dpr
    host._gpu_hud_commands = ClickGuiDrawList()
    painter = QPainter(image)
    painter.scale(scale, scale)
    try:
        host.draw_module_list_debug_white(painter, width / scale, available_height=height / scale)
    finally:
        painter.end()
    return image, host._gpu_hud_commands.texts


def shaped_advance(renderer, command):
    """Physical advance from the exact font preparation used by the GPU atlas."""
    font = command.font
    pixels = font.pointSizeF() * 96.0 / 72.0 if font.pointSizeF() > 0 else font.pixelSize()
    physical = pixels * renderer._pixel_ratio * command.raster_scale
    sample = renderer.small_text_policy.sample_scale_for(physical, preserve_weight=command.preserve_weight)
    raster_font = renderer.small_text_policy.prepare_font(
        font, physical, sample, preserve_weight=command.preserve_weight,
    )
    advance = renderer._jello_text_layout(command.text, raster_font)[1]
    return advance / (sample * command.raster_scale)


class ModuleListCjkLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.fonts = FontBook()
        cls.fonts.load_from_project_assets(ROOT)
        # Enable real installed YaHei when a caller explicitly chose offscreen.
        if os.name == "nt" and "Microsoft YaHei UI" not in QFontDatabase.families():
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
        cls.shaper = ClickGuiGpuRenderer()
        cjk = QFont(cls.shaper._jello_cjk_family())
        if not QFontMetricsF(cjk).inFontUcs4(ord("受")):
            raise unittest.SkipTest("No CJK-capable installed font; real glyph layout not verified")

    def host(self, *, gpu=True, language="简体中文", size="Normal"):
        host = Host(self.fonts, gpu=gpu)
        host.language(language)
        host.size(size)
        return host

    def test_translated_rows_share_true_advance_right_edge_at_every_size(self):
        for size in PIXELS:
            host = self.host(size=size)
            _, commands = draw(host)
            self.assertEqual({c.text for c in commands}, {hud_module_name(n, True) for n in NAMES})
            margin = 7.0 if size == "Tiny" else 10.0
            for command in commands:
                with self.subTest(size=size, label=command.text):
                    right = command.rect.left() + shaped_advance(host.clickgui_gpu, command)
                    self.assertAlmostEqual(right, 1920 - margin, delta=1.0)

    def test_1080p_2k_dpr_scale_and_fade_never_cross_right_margin(self):
        for width, height in ((1920, 1080), (2560, 1440)):
            for dpr in (1.0, 1.25, 1.5, 2.0):
                for scale in (0.55, 1.0, 1.35, 2.0):
                    for size in PIXELS:
                        host = self.host(size=size)
                        margin = 7.0 if size == "Tiny" else 10.0
                        for progress in (0.0, 0.15, 0.5, 0.85, 1.0):
                            host.progress(progress)
                            _, commands = draw(host, width=width, height=height, dpr=dpr, scale=scale)
                            for command in commands:
                                with self.subTest(width=width, dpr=dpr, scale=scale, size=size, progress=progress, label=command.text):
                                    left = command.rect.left() * dpr
                                    if command.device_pixel_snap:
                                        left = round(left)
                                    right = left + shaped_advance(host.clickgui_gpu, command) * command.render_scale
                                    self.assertLessEqual(right, (width - margin * scale) * dpr + 1.0)
                                    self.assertEqual(command.text_profile, "jello")
                                    self.assertTrue(command.preserve_weight)
                                    self.assertFalse(command.shadow)
                                    self.assertEqual(command.raster_scale, 1.0)
                                    self.assertAlmostEqual(command.color.alphaF(), 0.95 * progress, delta=1/255)

    def test_switch_language_in_same_host_invalidates_width_and_sort_cache(self):
        host = self.host(language="English")
        _, english = draw(host)
        original = [(c.text, c.rect.getRect(), c.font.key()) for c in english]
        cache = host._jello_active_mods_width_cache
        host.language("简体中文")
        _, chinese = draw(host)
        self.assertIs(cache, host._jello_active_mods_width_cache)
        self.assertNotEqual(english[0].rect.width(), chinese[0].rect.width())
        self.assertEqual(chinese[0].text, "受击自动小陀螺")
        # Sorting stays at the Normal/20px comparator even in Small and Tiny.
        for size in PIXELS:
            host.size(size)
            _, commands = draw(host)
            self.assertEqual(commands[0].text, "受击自动小陀螺")
            lengths = [len(c.text) for c in commands]
            self.assertEqual(lengths, sorted(lengths, reverse=True))
        host.size("Normal")
        host.language("English")
        _, english_again = draw(host)
        self.assertEqual(original, [(c.text, c.rect.getRect(), c.font.key()) for c in english_again])

    def test_cache_keys_include_final_label_not_only_registry_identifier(self):
        host = self.host()
        draw(host)
        longer = "受击自动小陀螺宽度回归测试"
        original = ml.hud_module_name
        with patch.object(ml, "hud_module_name", side_effect=lambda name, chinese: longer if name == "AutoSpinOnHit" and chinese else original(name, chinese)):
            _, commands = draw(host)
        command = next(c for c in commands if c.text == longer)
        self.assertAlmostEqual(command.rect.left() + shaped_advance(host.clickgui_gpu, command), 1910, delta=1.0)
        self.assertEqual(commands[0].text, longer)

    def test_mixed_cjk_ascii_uses_actual_atlas_advance_at_fractional_dpr(self):
        label = "装甲3D透视HUD（锁定）"
        original = ml.hud_module_name
        with patch.object(ml, "hud_module_name", side_effect=lambda name, chinese: label if name == "Armor3DESP" and chinese else original(name, chinese)):
            for size in PIXELS:
                host = self.host(size=size)
                for dpr in (1.0, 1.25, 1.5, 2.0):
                    _, commands = draw(host, dpr=dpr)
                    command = next(c for c in commands if c.text == label)
                    right = command.rect.left() * dpr + shaped_advance(host.clickgui_gpu, command)
                    margin = 7.0 if size == "Tiny" else 10.0
                    with self.subTest(size=size, dpr=dpr):
                        self.assertAlmostEqual(right, (1920 - margin) * dpr, delta=1.0)

    def test_warm_gpu_labels_do_not_reshape_every_frame(self):
        host = self.host()
        with patch.object(host, "text_advance", wraps=host.text_advance) as shape:
            draw(host)
            self.assertGreater(shape.call_count, 0)
            shape.reset_mock()
            for _ in range(3):
                draw(host)
            shape.assert_not_called()

    def test_dpr_change_on_warm_host_matches_cold_host(self):
        host = self.host()
        draw(host, dpr=1.0)
        for dpr in (1.25, 1.5, 2.0, 1.0):
            _, warm = draw(host, dpr=dpr)
            _, cold = draw(self.host(), dpr=dpr)
            self.assertEqual([(c.text, c.rect.getRect()) for c in warm], [(c.text, c.rect.getRect()) for c in cold])

    def test_warm_frames_do_not_resolve_the_immutable_shadow_file_again(self):
        host = self.host()
        with patch.object(host, "_client_asset_path", wraps=host._client_asset_path) as resolver:
            draw(host)
            for _ in range(100):
                draw(host)
            self.assertEqual(resolver.call_count, 1)

    def test_cpu_gpu_and_paint_device_dpi_switch_do_not_reuse_wrong_widths(self):
        host = self.host()
        draw(host)
        for gpu, dpi in ((False, 120), (True, 144), (False, 192), (True, 96)):
            host._collect_gpu_hud_commands = gpu
            host.clickgui_gpu.available = gpu
            image, warm = draw(host, dpr=1.5, scale=1.35, dpi=dpi)
            image_cold, cold = draw(self.host(gpu=gpu), dpr=1.5, scale=1.35, dpi=dpi)
            if gpu:
                self.assertEqual([(c.text, c.rect.getRect()) for c in warm], [(c.text, c.rect.getRect()) for c in cold])
            else:
                self.assertEqual(image, image_cold)

    def test_150ms_animation_and_same_frame_repaint_remain_unchanged(self):
        for language in ("English", "简体中文"):
            host = self.host(language=language)
            host.registry.get("HUD").get_setting("Jello List Animations").value = True
            for index in range(6):
                host._ui_frame_index += 1
                host.gui_motion.now += host.frame_dt
                _, commands = draw(host)
                progress = min(1.0, (index + 1) * host.frame_dt / 0.150)
                for command in commands:
                    self.assertAlmostEqual(command.render_scale, 0.86 + 0.14 * progress)
                    self.assertAlmostEqual(command.color.alphaF(), 0.95 * progress, delta=1/255)
                _, repaint = draw(host)
                self.assertEqual([(c.rect.getRect(), c.color.rgba()) for c in commands], [(c.rect.getRect(), c.color.rgba()) for c in repaint])
            for name in NAMES:
                host.registry.get(name).enabled = False
            for _ in range(6):
                host._ui_frame_index += 1
                host.gui_motion.now += host.frame_dt
                _, commands = draw(host)
            self.assertEqual(commands, [])
            self.assertEqual(host._jello_active_mods_rows, {})

    def test_english_sigma_font_geometry_and_comparator_are_unchanged(self):
        for size, pixels in PIXELS.items():
            host = self.host(language="English", size=size)
            _, commands = draw(host)
            font = self.fonts.font("jello_light", pixels * 72 / 96)
            metrics = QFontMetricsF(font)
            comparator = QFontMetricsF(self.fonts.font("jello_light", 20 * 72 / 96))
            expected = sorted(NAMES, key=lambda name: -comparator.horizontalAdvance(name))
            self.assertEqual([c.text for c in commands], expected)
            margin = 7.0 if size == "Tiny" else 10.0
            for command in commands:
                self.assertEqual(command.font.key(), font.key())
                self.assertAlmostEqual(command.rect.left(), 1920 - margin - metrics.horizontalAdvance(command.text))
                self.assertAlmostEqual(command.rect.width(), metrics.horizontalAdvance(command.text) + 4.0)

    def test_cpu_raster_complete_chinese_lines_stay_inside_margin(self):
        for size in PIXELS:
            margin = 7.0 if size == "Tiny" else 10.0
            for dpr, scale in ((1.0, 1.0), (1.25, 0.55), (1.5, 1.35), (2.0, 2.0)):
                for progress in (0.15, 0.5, 1.0):
                    host = self.host(gpu=False, size=size)
                    host.progress(progress)
                    image, _ = draw(host, dpr=dpr, scale=scale)
                    safe_right = math.ceil((1920 - margin * scale) * dpr) + 1
                    strip = image.copy(safe_right, 0, image.width() - safe_right, image.height())
                    with self.subTest(size=size, dpr=dpr, scale=scale, progress=progress):
                        self.assertEqual(max(bytes(strip.constBits())[3::4], default=0), 0)
                        self.assertGreater(max(bytes(image.constBits())[3::4]), 0)

    def test_api_frozen_qualnames_are_preserved(self):
        for name in ("draw_module_list_debug_white", "module_list_entries", "build_gpu_module_list"):
            self.assertEqual(getattr(ml.ModuleListMixin, name).__qualname__, f"PolarRMWindow.{name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
