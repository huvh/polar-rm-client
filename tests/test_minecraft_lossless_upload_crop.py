"""Native-density MC texture crops must preserve every visible pixel and hit rect."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
import unittest
from itertools import product

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rm_client.model import RobotState, build_default_registry
from rm_client.ui.minecraft_hud import MinecraftCombatHudRenderer

APP = QApplication.instance() or QApplication([])


class LosslessCropTests(unittest.TestCase):
    def test_cropped_native_image_equals_full_composition(self):
        cases = product(("English", "简体中文"),
                ((1280, 720, "2x", .5), (1920, 1080, "2x", 1),
                 (2560, 1440, "2x", 1.5), (1280, 720, "Auto", 2)),
                (True, False), (1.0, 1.25, 1.5, 2.0))
        for language, (width, height, scale, multiplier), map_enabled, dpr in cases:
            with self.subTest(language=language, resolution=(width, height), multiplier=multiplier, map=map_enabled, dpr=dpr):
                registry = build_default_registry()
                registry.get("ClickGui").get_setting("Language").value = language
                registry.get("TacticalMap").enabled = map_enabled
                module = registry.get("MinecraftCombatHUD")
                module.get_setting("GUI Scale").value = scale
                module.get_setting("Scale Multiplier").value = multiplier
                state = RobotState()
                state.current_heat = 137
                state.chassis_power_w = 67
                renderer = MinecraftCombatHudRenderer(ROOT / "assets/minecraft_hud")
                cropped = QImage(round(width*dpr), round(height*dpr), QImage.Format.Format_ARGB32_Premultiplied)
                cropped.setDevicePixelRatio(dpr)
                cropped.fill(0)
                painter = QPainter(cropped)
                layout = renderer.draw(painter, width, height, state, registry, module)
                painter.end()
                full = QImage(cropped.size(), cropped.format())
                full.setDevicePixelRatio(dpr)
                full.fill(0)
                painter = QPainter(full)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                painter.drawImage(QRectF(*layout.origin, layout.logical_size[0] * layout.scale,
                                         layout.logical_size[1] * layout.scale),
                                  renderer._layer_image, QRectF(renderer._layer_image.rect()))
                painter.end()
                self.assertEqual(cropped, full, "A texture crop removed or moved visible pixels")
                self.assertEqual(layout.slot_at(layout.slots[4].center()), 4)
                if map_enabled and abs(layout.scale - round(layout.scale)) < 1e-9 and abs(layout.scale*dpr-round(layout.scale*dpr)) < 1e-9:
                    self.assertLess(renderer._present_image.sizeInBytes(), renderer._layer_image.sizeInBytes())
                else:
                    self.assertEqual(renderer._present_image.sizeInBytes(), renderer._layer_image.sizeInBytes())


if __name__ == "__main__":
    unittest.main()
