"""Native Minecraft CJK raster/metrics regressions; no window or device startup.

Run with .venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests
         -p test_minecraft_cjk_readability.py
"""
from __future__ import annotations

import os
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import RobotState, build_default_registry
from rm_client.ui.hud_locale import HudDisplayText
from rm_client.ui import minecraft_hud as hud
from rm_client.ui.minecraft_presentation import MinecraftStyledFont

ASSETS = ROOT / "assets/minecraft_hud"
APP = QApplication.instance() or QApplication([])


def canvas(width: int, height: int, dpr: float = 1.0) -> QImage:
    image = QImage(round(width*dpr), round(height*dpr), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    return image


def pixels(image: QImage) -> bytes:
    return bytes(image.constBits())


def ink(image: QImage, color: QColor) -> set[tuple[int, int]]:
    return {(x, y) for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y) == color}


def hex_ink(bits: bytes) -> set[tuple[int, int]]:
    """Independent decoding, so a decimated eight-row raster cannot pass."""
    width = len(bits)//2
    stride = width//8
    return {(x, y) for y in range(16) for x in range(width)
            if int.from_bytes(bits[y*stride:(y+1)*stride], "big") & (1 << (width-x-1))}


class MinecraftCjkReadabilityTests(unittest.TestCase):
    def setUp(self):
        self.renderer = hud.MinecraftCombatHudRenderer(ASSETS)
        self.font = self.renderer.styled_font
        self.assertTrue(self.renderer.available)

    def render(self, width=2560, height=1440, dpr=1.0, multiplier=1.0, language="简体中文", gui="2"):
        registry = build_default_registry()
        registry.get("ClickGui").get_setting("Language").value = language
        registry.get("TacticalMap").enabled = False
        module = registry.get("MinecraftCombatHUD")
        module.get_setting("GUI Scale").value = gui
        module.get_setting("Scale Multiplier").value = multiplier
        state = RobotState()
        state.current_stage = "MATCH"
        state.current_heat = 40
        state.max_heat = 200
        state.heat_cooldown_rate = 16
        state.chassis_power_w = 55
        state.power_limit = 70
        state.stage_countdown_sec = 366
        image = canvas(width, height, dpr)
        painter = QPainter(image)
        labels = []
        draw_text = hud._draw_display_text

        def capture(renderer, p, x, y, raw, tint, scale):
            labels.append((x, y, raw, QColor(tint), scale))
            return draw_text(renderer, p, x, y, raw, tint, scale)

        try:
            with patch.object(hud, "_draw_display_text", side_effect=capture):
                layout = self.renderer.draw(painter, width, height, state, registry, module)
        finally:
            painter.end()
        if labels:
            self.last_labels = tuple(labels)
        return image, layout, self.last_labels

    def test_bundled_cjk_preserves_all_sixteen_bitmap_rows_and_true_advance(self):
        for char in "冷却功率剩余时间我方基地护盾弹药":
            with self.subTest(char=char):
                glyph, advance = self.font.glyph(char)
                self.assertEqual((glyph.width(), glyph.height(), advance), (16, 16, 9))
                expected = hex_ink(self.font.hex_data[ord(char)])
                self.assertEqual(ink(glyph, QColor("white")), expected)
                text = self.font.image(char, shadow=False)
                self.assertEqual(text.devicePixelRatio(), 2)
                self.assertEqual(ink(text, QColor("white")), expected)
        self.assertEqual(self.font.width("伤害"), 18)
        self.assertEqual(self.font.width("功率 55/70W"),
                         18 + self.renderer.font.logical_width(" 55/70W"))
        self.assertEqual(self.font.width("§l功率§r 55/70W"), self.font.width("功率 55/70W") + 2)

    def test_ascii_numbers_and_shadows_are_byte_exact_original_sprites(self):
        text = "RM 01:23 COOL 80% -16/S PWR 55/70W"
        for shadow in (False, True):
            for color in (QColor("#55ffff"), QColor(255, 255, 85, 180)):
                with self.subTest(shadow=shadow, color=color.rgba()):
                    original = self.renderer.font.image(text, color, 2, shadow)
                    styled = self.font.image(text, base=color, shadow=shadow)
                    self.assertEqual(styled.size(), original.size())
                    self.assertEqual(pixels(styled), pixels(original))
        self.assertEqual(self.font.width(text), self.renderer.font.logical_width(text))

    def test_provider_ascent_and_rectangular_cells_share_a_mixed_text_baseline(self):
        glyph, advance = self.font.glyph("À")
        self.assertEqual((glyph.width(), glyph.height(), advance), (18, 24, 6))
        self.assertEqual(self.font._glyph_tops["À"], -3)
        self.assertEqual(self.font.height("AÀ汉"), 13)
        image = self.font.image("AÀ汉", shadow=False)
        self.assertEqual(image.height(), 24)
        # ASCII and CJK retain top=0 relative to baseline=7, even when a taller
        # accented provider expands the run upward. No descender is cropped.
        ascii_glyph, ascii_advance = self.font.glyph("A")
        self.assertEqual(ink(image.copy(0, 6, round(ascii_advance*2), 16), QColor("white")),
                         ink(ascii_glyph.copy(0, 0, round(ascii_advance*2), 16), QColor("white")))
        cjk_x = round((ascii_advance + advance)*2)
        self.assertEqual(ink(image.copy(cjk_x, 6, 16, 16), QColor("white")),
                         hex_ink(self.font.hex_data[ord("汉")]))

    def test_complete_formatted_and_missing_glyph_runs_are_cached_and_bounded(self):
        text = "§b功率 §l55§r/70W \U0010ffff"
        base = QColor("#ff5555")
        image = self.font.image(text, base=base)
        width = self.font.width(text)
        self.assertIs(self.font.image(text, base=base), image)
        self.assertIn("\U0010ffff", self.font._glyphs)
        self.assertEqual(self.font.glyph("\U0010ffff")[1], self.font.glyph("?")[1])
        with patch.object(self.font, "glyph", side_effect=AssertionError("cached run rescanned glyphs")):
            self.assertEqual(self.font.width(text), width)
            self.assertIs(self.font.image(text, base=base), image)
            self.font.image(text, base=base, shadow=False)
        colors = {image.pixelColor(x, y).name() for y in range(image.height())
                  for x in range(image.width()) if image.pixelColor(x, y).alpha()}
        self.assertTrue({"#55ffff", "#ff5555"}.issubset(colors))
        for number in range(270):
            self.font.image(f"冷却 {number}")
        self.assertLessEqual(len(self.font._images), 256)
        self.assertLessEqual(len(self.font._layouts), 256)
        self.assertLessEqual(len(self.font._glyphs), 512)

    def test_missing_optional_resources_fall_back_without_recursive_question_mark(self):
        with TemporaryDirectory() as root:
            font = MinecraftStyledFont(self.renderer.font, Path(root))
            text = "A汉\U0010ffff"
            image = font.image(text)
            self.assertFalse(image.isNull())
            self.assertEqual(font.width(text), self.renderer.font.logical_width("A??"))
            self.assertIs(font.image(text), image)
            # Lack of a provider JSON cannot replace ASCII with Unihex shapes.
            self.assertEqual(pixels(font.image("A?", shadow=False)),
                             pixels(self.renderer.font.image("A?", QColor("white"), 2, False)))
            empty = hud.MinecraftBitmapFont(Path(root) / "absent.png")
            unavailable = MinecraftStyledFont(empty, Path(root))
            self.assertFalse(unavailable.image("汉?").isNull())

    def test_display_translation_uses_full_width_and_does_not_crop_to_raw_english(self):
        raw = HudDisplayText("PWR", "底盘功率 55/70W")
        image = canvas(160, 30, 2)
        painter = QPainter(image)
        try:
            width = hud._draw_display_text(self.renderer, painter, 5, 7, raw, QColor("#55aaff"), 1)
        finally:
            painter.end()
        expected = self.font.image(raw.display, base=QColor("#55aaff"))
        self.assertEqual(width, expected.width()/2)
        self.assertGreater(width, self.renderer.font.logical_width(raw))
        self.assertEqual(pixels(image.copy(10, 14, expected.width(), expected.height())), pixels(expected))

    def test_draw_crops_only_at_explicit_rect_and_restores_painter_state(self):
        text = "§a汉字功率 55/70W"
        source = self.font.image(text)
        for align in (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight):
            with self.subTest(align=align):
                image = canvas(80, 30, 2)
                painter = QPainter(image)
                rect = QRectF(10, 7, 22, 9)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                try:
                    self.font.draw(painter, rect, text, align=align)
                    self.assertTrue(painter.testRenderHint(QPainter.SmoothPixmapTransform))
                    self.assertFalse(painter.hasClipping())
                finally:
                    painter.end()
                w = source.width()/2
                x = rect.right()-w if align & Qt.AlignRight else rect.center().x()-w/2 if align & Qt.AlignHCenter else rect.left()
                offset = round((rect.left()-x)*2)
                self.assertEqual(pixels(image.copy(20, 14, 44, 18)), pixels(source.copy(offset, 0, 44, 18)))
                for y in range(image.height()):
                    for x in range(image.width()):
                        if not (20 <= x < 64 and 14 <= y < 32):
                            self.assertEqual(image.pixelColor(x, y).alpha(), 0)

    def test_native_cjk_survives_full_hud_layer_and_scoreboard_at_2k(self):
        image, layout, labels = self.render()
        layer = self.renderer._layer_image
        self.assertEqual(layer.devicePixelRatio(), 2)
        self.assertEqual((layer.width(), layer.height()), tuple(v*2 for v in layout.logical_size))
        for x, y, raw, tint, scale in labels[:2]:
            with self.subTest(label=raw.display):
                expected = self.font.image(raw.display, base=tint)
                self.assertEqual(scale, 1)
                self.assertEqual(pixels(layer.copy(round(x*2), round(y*2), expected.width(), expected.height())), pixels(expected))
                char = raw.display[0]
                self.assertEqual(ink(layer.copy(round(x*2), round(y*2), 16, 16), tint), hex_ink(self.font.hex_data[ord(char)]))
                self.assertEqual(ink(image.copy(round(x*2), round(y*2), 16, 16), tint), hex_ink(self.font.hex_data[ord(char)]))
        logical = self.renderer._logical_layout(*layout.logical_size)
        power = labels[1]
        self.assertAlmostEqual(power[0] + self.renderer._display_text_width(power[2]), logical.hotbar.right())
        self.assertLessEqual(labels[0][1] + self.font.height(labels[0][2].display), logical.armor[0].top()-1)
        self.assertLessEqual(power[1] + self.font.height(power[2].display), logical.food[-1].top()-1)
        # Actual side-panel Chinese, not an isolated glyph-only preview.
        lines = tuple(text for text, _ in self.renderer.scoreboard_lines(RobotState()))
        score = self.renderer._logical_layout(*layout.logical_size, lines).scoreboard
        first_x = round((score.left()+3)*2)
        first_y = round((score.top()+2+3*9)*2)
        self.assertEqual(ink(layer.copy(first_x, first_y, 16, 16), QColor("white")),
                         hex_ink(self.font.hex_data[ord("剩")]))

    def test_fractional_multiplier_and_host_dpr_keep_native_raster_and_nearest_transform(self):
        for multiplier in (0.5, 0.75, 1.0, 1.25, 2.0):
            builds = None
            for dpr in (1.0, 1.5, 2.0):
                with self.subTest(multiplier=multiplier, dpr=dpr):
                    image, layout, labels = self.render(dpr=dpr, multiplier=multiplier)
                    x, y, raw, tint, scale = labels[0]
                    text = self.font.image(raw.display, base=tint)
                    native = self.renderer._layer_image.copy(round(x*2), round(y*2), text.width(), text.height())
                    self.assertEqual(pixels(native), pixels(text))
                    if builds is not None:
                        self.assertEqual(self.renderer.layer_rebuilds, builds)
                    builds = self.renderer.layer_rebuilds
                    target = QRectF(layout.origin[0]+x*layout.scale, layout.origin[1]+y*layout.scale,
                                    text.width()/2*layout.scale, text.height()/2*layout.scale)
                    # Reference the whole-canvas nearest sampling phase. Qt's
                    # fixed-point sampling of a fractional full-size blit can
                    # differ from a separately blitted small text rectangle.
                    # Native source integrity is checked above independently.
                    reference = canvas(*layout.logical_size, 2)
                    painter = QPainter(reference)
                    try:
                        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                        painter.drawImage(x, y, text)
                    finally:
                        painter.end()
                    expected = canvas(2560, 1440, dpr)
                    painter = QPainter(expected)
                    try:
                        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                        painter.drawImage(QRectF(*layout.origin, layout.logical_size[0]*layout.scale,
                                          layout.logical_size[1]*layout.scale), reference, QRectF(reference.rect()))
                    finally:
                        painter.end()
                    crop = QRectF(target.left()*dpr-2, target.top()*dpr-2,
                                  target.width()*dpr+4, target.height()*dpr+4).toAlignedRect()
                    self.assertEqual(ink(image.copy(crop), tint), ink(expected.copy(crop), tint))
                    screen = QRectF(0, 0, 2560, 1440)
                    self.assertTrue(screen.contains(layout.hotbar))
                    self.assertTrue(screen.contains(layout.scoreboard))
                    for index, rect in enumerate(layout.slots):
                        self.assertEqual(layout.slot_at(rect.center()), index)

    def test_scoreboard_reserves_real_translated_width_height_and_shadow(self):
        lines = ("§e§lÀ汉", "§f" + "Time left "*4 + "55/70W", "§7footer")
        width, height = self.renderer._scoreboard_metrics(lines)
        translated = tuple(hud._scoreboard_display(text, True) if index == 1 else text
                           for index, text in enumerate(lines))
        self.assertGreaterEqual(width-6, max(self.font.width(text)+1 for text in translated))
        self.assertGreaterEqual(height-4, sum(self.font.height(text) for text in translated))
        layout = self.renderer.layout(2560, 1440, "Auto", lines, 2)
        self.assertTrue(QRectF(0, 0, 2560, 1440).contains(layout.scoreboard))
        _, en, _ = self.render(language="English")
        _, zh, _ = self.render(language="简体中文")
        self.assertEqual(en, zh)

    def test_2k_auto_gui_retains_every_cjk_stroke_at_all_user_multipliers(self):
        expected = hex_ink(self.font.hex_data[ord("冷")])
        for multiplier in (0.5, 0.75, 1.0, 1.25, 2.0):
            for dpr in (1.0, 1.5, 2.0):
                with self.subTest(multiplier=multiplier, dpr=dpr):
                    image, layout, labels = self.render(gui="Auto", multiplier=multiplier, dpr=dpr)
                    self.assertEqual(layout.base_scale, 6)
                    x, y, _, tint, _ = labels[0]
                    pixel_scale = layout.scale*dpr/2
                    self.assertGreaterEqual(pixel_scale, 1)
                    left = (layout.origin[0] + x*layout.scale)*dpr
                    top = (layout.origin[1] + y*layout.scale)*dpr
                    # Sample each original Unihex cell's physical centre. At
                    # Auto on a 2K display not one native stroke may disappear.
                    actual = {(gx, gy) for gy in range(16) for gx in range(16)
                              if image.pixelColor(math.floor(left+(gx+0.5)*pixel_scale),
                                                  math.floor(top+(gy+0.5)*pixel_scale)) == tint}
                    self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
