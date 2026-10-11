"""Real Qt raster tests of kill texture minification; these do not validate a GPU."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication
from rm_client.kill_fx import AssetBank

APP = QApplication.instance() or QApplication([])


def checker():
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.black)
    p = QPainter(image)
    for x in range(1, 1024, 2):
        p.fillRect(x, 0, 1, 1024, Qt.GlobalColor.white)
    p.end()
    return image


def canvas(dpr=1):
    image = QImage(round(64*dpr), round(64*dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    return image


class AssetFilteringTests(unittest.TestCase):
    def setUp(self):
        self.bank = AssetBank(Path("/nonexistent"))
        self.bank.images["checker"] = checker()

    def test_checker_detail_is_averaged_without_aliasing(self):
        result = canvas()
        p = QPainter(result)
        self.bank.draw_centered(p, "checker", QPointF(32, 32), 48)
        self.assertFalse(p.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform))
        p.end()
        pixels = [result.pixelColor(x, y).red() for x in range(10, 54) for y in range(10, 54)]
        self.assertLess(max(pixels)-min(pixels), 3)
        self.assertTrue(126 <= sum(pixels)/len(pixels) <= 129)
        self.assertEqual(result.pixelColor(0, 0).alpha(), 0)
        baseline = canvas()
        p = QPainter(baseline)
        p.drawImage(QRectF(8, 8, 48, 48), self.bank.images["checker"])
        p.end()
        before_error = sum(abs(baseline.pixelColor(x, 32).red()-127.5) for x in range(10, 54))
        after_error = sum(abs(result.pixelColor(x, 32).red()-127.5) for x in range(10, 54))
        self.assertGreater(before_error, after_error * 20)

    def test_device_transform_dpr_and_rotation_select_physical_resolution(self):
        result = canvas(2)
        p = QPainter(result)
        p.rotate(27)
        self.assertEqual(self.bank._filtered_image(p, self.bank.images["checker"], 48, 48).width(), 128)
        p.scale(2, 2)
        self.assertEqual(self.bank._filtered_image(p, self.bank.images["checker"], 48, 48).width(), 256)
        p.end()

    def test_animation_reuses_stable_images_and_bounded_levels(self):
        result = canvas()
        p = QPainter(result)
        original = self.bank.images["checker"]
        a = self.bank._filtered_image(p, original, 40, 40)
        key = a.cacheKey()
        for size in [38+i/100 for i in range(1000)]:
            self.assertEqual(self.bank._filtered_image(p, original, size, size).cacheKey(), key)
        self.assertEqual(len(self.bank._minified), 1)
        for power in range(40):
            self.bank._filtered_image(p, original, 2**power, 2**power)
        self.assertLessEqual(len(self.bank._minified), 12)
        self.assertEqual(original.width(), 1024)
        p.end()

    def test_alpha_and_color_are_preserved(self):
        source = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor(220, 80, 40, 128))
        self.bank.images["alpha"] = source
        result = canvas()
        p = QPainter(result)
        self.bank.draw_centered(p, "alpha", QPointF(32, 32), 48)
        p.end()
        color = result.pixelColor(32, 32)
        self.assertEqual(color.alpha(), 128)
        self.assertLessEqual(abs(color.red()-220), 1)
        self.assertLessEqual(abs(color.green()-80), 1)
        self.assertLessEqual(abs(color.blue()-40), 1)

    def test_sprite_frames_filter_separately_without_neighbor_bleed(self):
        source = QImage(1024, 2048, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(Qt.GlobalColor.red)
        p = QPainter(source)
        p.fillRect(0, 1024, 1024, 1024, Qt.GlobalColor.blue)
        p.end()
        self.bank.images["sheet"] = source
        result = canvas()
        p = QPainter(result)
        self.bank.draw_vertical_frame(p, "sheet", 1, 2, QPointF(32, 32), 48, 1, additive=False)
        p.end()
        self.assertEqual(result.pixelColor(32, 32), QColor(Qt.GlobalColor.blue))
        self.assertEqual(len(self.bank.frames), 1)
        self.assertEqual(len(self.bank._minified), 1)

    def test_bottom_anchored_uses_same_filter_and_restores_hint(self):
        result = canvas()
        p = QPainter(result)
        self.bank.draw_bottom_anchored(p, "checker", QPointF(32, 56), 48, 1, 0, 1)
        self.assertFalse(p.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform))
        p.end()
        self.assertTrue(126 <= result.pixelColor(32, 32).red() <= 129)

if __name__ == "__main__":
    unittest.main()
