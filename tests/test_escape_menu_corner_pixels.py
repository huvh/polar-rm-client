"""Real menu pixels on raster Qt and the production private OpenGL FBO.

Run directly with --require-gpu on Windows to require the hidden GL probe.
Headless/offscreen Qt still runs the raster tests, and explicitly skips GL
when that platform cannot create a context. No client, devices, or windows
are started; FBO readback is confined to this regression test.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import unittest

if sys.platform != "win32" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REQUIRE_GPU = "--require-gpu" in sys.argv
if REQUIRE_GPU:
    sys.argv.remove("--require-gpu")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QImage, QOffscreenSurface, QOpenGLContext, QPainter,
    QPainterPath, QPen, QSurfaceFormat,
)
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtWidgets import QApplication

from rm_client.ui.gpu_frame_compositor import GpuFrameCompositor
from rm_client.ui.polar.mixins.escape_menu_mixin import EscapeMenuMixin


APP = QApplication.instance() or QApplication([])


class MenuHost(EscapeMenuMixin):
    def __init__(self, *, confirm=False, selected=0):
        self._escape_menu_visible = True
        self._escape_menu_confirm_exit = confirm
        self._escape_menu_selected = selected


def prepare_painter(painter, host, width, height, *, clip_to_panel=False):
    # Match paint_priority_interaction_layer: no inherited AA setup. Menu
    # quality must not depend on the static HUD's separate painter.
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    if clip_to_panel:
        panel, _, scale = host.escape_menu_layout(width, height)
        path = QPainterPath()
        path.addRoundedRect(panel, 12 * scale, 12 * scale)
        painter.setClipPath(path)


def raster_menu(host, width, height, ratio=1.0, *, clip_to_panel=False):
    image = QImage(round(width * ratio), round(height * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(0)
    painter = QPainter(image)
    try:
        prepare_painter(painter, host, width, height, clip_to_panel=clip_to_panel)
        host.draw_escape_menu(painter, width, height)
    finally:
        painter.end()
    return image


def corner_pixels(rect, ratio, patch=3):
    """Inspect all four square bounds, including pixels outside each arc."""
    left = math.floor(rect.left() * ratio)
    right = math.ceil(rect.right() * ratio) - 1
    top = math.floor(rect.top() * ratio)
    bottom = math.ceil(rect.bottom() * ratio) - 1
    return {
        (x + dx * sx, y + dy * sy)
        for x, sx in ((left, 1), (right, -1))
        for y, sy in ((top, 1), (bottom, -1))
        for dx in range(patch) for dy in range(patch)
    }


class RasterMenuPixels(unittest.TestCase):
    def test_all_card_corners_only_contain_the_dim_layer(self):
        for width, height, ratio in ((1000, 620, 1.0), (640, 400, 1.25), (1000, 620, 2.0)):
            with self.subTest(size=(width, height), dpr=ratio):
                host = MenuHost()
                image = raster_menu(host, width, height, ratio)
                panel, _, _ = host.escape_menu_layout(width, height)
                for x, y in corner_pixels(panel, ratio, patch=1):
                    self.assertEqual(image.pixelColor(x, y).getRgb(), (0, 0, 0, 100))

    def test_row_corner_matches_card_not_rectangular_white_fill(self):
        host = MenuHost()
        image = raster_menu(host, 1000, 620)
        panel, rows, _ = host.escape_menu_layout(1000, 620)
        card = image.pixelColor(round(panel.left() + 20), round(panel.top() + 20))
        for row in rows:
            for x, y in corner_pixels(row, 1.0, patch=1):
                self.assertEqual(image.pixelColor(x, y), card)
            # Keep the selected/unselected translucent fills, not a solution
            # that merely suppresses all button geometry.
            interior = image.pixelColor(round(row.left() + 16), round(row.center().y()))
            self.assertGreater(interior.red(), card.red())

    def test_menu_owns_antialiasing_and_source_over_and_restores_state(self):
        image = QImage(1000, 620, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.setPen(QPen(QColor(12, 23, 34, 45), 3))
            painter.setBrush(QColor(65, 76, 87, 98))
            painter.setFont(QFont("Arial", 9))
            painter.setClipRect(QRectF(10, 10, 980, 600))
            before = (painter.renderHints(), painter.compositionMode(), painter.pen(),
                      painter.brush(), painter.font(), painter.clipPath(), painter.transform(), painter.opacity())
            MenuHost().draw_escape_menu(painter, 1000, 620)
            after = (painter.renderHints(), painter.compositionMode(), painter.pen(),
                     painter.brush(), painter.font(), painter.clipPath(), painter.transform(), painter.opacity())
            self.assertEqual(after, before)
        finally:
            painter.end()
        self.assertEqual(image.pixelColor(20, 20).getRgb(), (0, 0, 0, 100))
        expected = raster_menu(MenuHost(), 1000, 620)
        panel, rows, _ = MenuHost().escape_menu_layout(1000, 620)
        for rect in (panel, *rows):
            for x, y in corner_pixels(rect, 1.0, patch=6):
                self.assertEqual(image.pixelColor(x, y), expected.pixelColor(x, y))
        # This also detects loss of curved-edge AA, rather than just absence
        # of white rectangles. SourceOver(alpha=220) over dim(alpha=100) has
        # alpha=234 inside; genuinely AA edge pixels lie in between.
        edge_alphas = {image.pixelColor(x, y).alpha() for x, y in corner_pixels(panel, 1.0, patch=12)}
        self.assertTrue(any(100 < alpha < 234 for alpha in edge_alphas))

    def test_invisible_menu_leaves_pixels_and_painter_state_untouched(self):
        host = MenuHost()
        host._escape_menu_visible = False
        image = QImage(1000, 620, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(31, 42, 53, 180))
        before = image.copy()
        painter = QPainter(image)
        painter.setOpacity(0.5)
        try:
            host.draw_escape_menu(painter, 1000, 620)
            self.assertEqual(painter.opacity(), 0.5)
        finally:
            painter.end()
        self.assertEqual(image, before)


class GpuMenuPixels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        # Private FBO stencil must work even if the window surface requests
        # no depth/stencil. A context's default framebuffer is not this FBO.
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        cls.context = QOpenGLContext()
        cls.context.setFormat(fmt)
        if not cls.context.create():
            cls.no_gpu("Qt platform cannot create a hidden OpenGL context")
        cls.surface = QOffscreenSurface()
        cls.surface.setFormat(cls.context.format())
        cls.surface.create()
        if not cls.surface.isValid() or not cls.context.makeCurrent(cls.surface):
            cls.no_gpu("Hidden OpenGL surface unavailable")
        cls.functions = cls.context.extraFunctions()

    @classmethod
    def no_gpu(cls, reason):
        if REQUIRE_GPU:
            raise AssertionError(reason)
        raise unittest.SkipTest(reason + "; rerun on desktop Qt with --require-gpu")

    @classmethod
    def tearDownClass(cls):
        cls.context.doneCurrent()
        cls.surface.destroy()

    def render_menu(self, host, width, height, ratio=1.0, *, clip_to_panel=False):
        self.assertTrue(self.context.makeCurrent(self.surface))
        compositor = GpuFrameCompositor()
        # Isolate production FBO allocation/Qt drawing; no glass shader or
        # full client initialization is needed to exercise the bad stencil.
        compositor.available = True
        try:
            self.assertTrue(compositor.ensure_size(width, height, ratio), compositor.last_error)
            device = compositor.paint_device("target")
            self.assertIsNotNone(device)
            self.assertEqual(compositor.target_fbo.attachment(), QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            device.setDevicePixelRatio(ratio)
            compositor.clear_current(self.functions, transparent=True)
            painter = QPainter(device)
            try:
                self.assertTrue(painter.isActive())
                prepare_painter(painter, host, width, height, clip_to_panel=clip_to_panel)
                before = (painter.renderHints(), painter.compositionMode(), painter.clipPath())
                host.draw_escape_menu(painter, width, height)
                self.assertEqual((painter.renderHints(), painter.compositionMode(), painter.clipPath()), before)
            finally:
                painter.end()
            image = compositor.target_fbo.toImage()
            compositor.release_layer("target")
            return image
        finally:
            compositor._destroy_fbos()

    def assert_corner_reference(self, actual, reference, host, width, height, ratio):
        panel, rows, scale = host.escape_menu_layout(width, height)
        for rect, radius in ((panel, 12 * scale), *((row, 5 * scale) for row in rows)):
            checked = 0
            for x, y in corner_pixels(rect, ratio, patch=max(3, round(6 * ratio))):
                # Qt's GL and raster engines use different edge coverage.
                # Exclude only the one-pixel stroke/AA transition, not the
                # square corner outside the silhouette or the filled interior.
                qx = abs((x + 0.5) / ratio - rect.center().x()) - rect.width() / 2 + radius
                qy = abs((y + 0.5) / ratio - rect.center().y()) - rect.height() / 2 + radius
                distance = min(max(qx, qy), 0.0) + math.hypot(max(qx, 0.0), max(qy, 0.0)) - radius
                if -1.5 <= distance <= 1.25:
                    continue
                pixel = actual.pixelColor(x, y).getRgb()
                expected = reference.pixelColor(x, y).getRgb()
                # Compare premultiplied channels so zero-alpha RGB isn't
                # amplified, while allowing only 8-bit rounding differences.
                actual_pm = tuple(round(c * pixel[3] / 255) for c in pixel[:3]) + (pixel[3],)
                expected_pm = tuple(round(c * expected[3] / 255) for c in expected[:3]) + (expected[3],)
                self.assertLessEqual(max(abs(a - b) for a, b in zip(actual_pm, expected_pm)), 3,
                                     f"corner ({x},{y}), GL={pixel}, raster={expected}")
                checked += 1
            self.assertGreaterEqual(checked, 4, "Must inspect real corner pixels on every surface")

    def test_production_fbo_card_and_row_corners_match_raster(self):
        for width, height, ratio in ((1000, 620, 1.0), (640, 400, 1.25), (1000, 620, 1.5), (1000, 620, 2.0), (2560, 1440, 1.0)):
            for confirm, selected in ((False, 0), (False, 2), (True, 1)):
                with self.subTest(size=(width, height), dpr=ratio, confirm=confirm, selected=selected):
                    host = MenuHost(confirm=confirm, selected=selected)
                    actual = self.render_menu(host, width, height, ratio)
                    reference = raster_menu(host, width, height, ratio)
                    self.assert_corner_reference(actual, reference, host, width, height, ratio)
                    panel, rows, _ = host.escape_menu_layout(width, height)
                    for x, y in corner_pixels(panel, ratio, patch=1):
                        self.assertEqual(actual.pixelColor(x, y).getRgb(), (0, 0, 0, 100))
                    # No rectangle-wide white stroke in the card or row
                    # interiors either (the other half of this regression).
                    for rect in (panel, *rows):
                        x = round((rect.left() + 20) * ratio)
                        y = round((rect.top() + 16) * ratio)
                        self.assertEqual(actual.pixelColor(x, y), reference.pixelColor(x, y))

    def test_inherited_rounded_clip_keeps_corner_alpha_zero(self):
        host = MenuHost()
        for ratio in (1.0, 2.0):
            with self.subTest(dpr=ratio):
                actual = self.render_menu(host, 1000, 620, ratio, clip_to_panel=True)
                panel, _, _ = host.escape_menu_layout(1000, 620)
                for x, y in corner_pixels(panel, ratio, patch=1):
                    self.assertEqual(actual.pixelColor(x, y).getRgb(), (0, 0, 0, 0))
                    # Inspect raw premultiplied bytes as well: pixelColor's
                    # unpremultiplication can hide RGB residue at alpha zero.
                    self.assertEqual(actual.format(), QImage.Format.Format_ARGB32_Premultiplied)
                    offset = y * actual.bytesPerLine() + x * 4
                    self.assertEqual(bytes(actual.constBits()[offset:offset + 4]), b"\0\0\0\0")
                self.assertEqual(actual.pixelColor(20, 20).alpha(), 0)
                self.assertGreater(actual.pixelColor(round(panel.center().x() * ratio), round((panel.top() + 20) * ratio)).alpha(), 0)

    def test_stencil_attachment_survives_resize_without_changing_shader_fbos(self):
        self.assertTrue(self.context.makeCurrent(self.surface))
        compositor = GpuFrameCompositor()
        compositor.available = True
        painter_layers = ("background", "control", "overlay", "dynamic", "target")
        shader_layers = ("blur_temp", "blur", "treated_blur_temp", "treated_blur", "hud_glass", "glass", "vision")
        try:
            for width, height, ratio in ((64, 48, 1.0), (96, 72, 2.0), (64, 48, 1.0)):
                with self.subTest(size=(width, height), dpr=ratio):
                    self.assertTrue(compositor.ensure_size(width, height, ratio), compositor.last_error)
                    for layer in painter_layers:
                        fbo = getattr(compositor, layer + "_fbo")
                        self.assertTrue(fbo.isValid())
                        self.assertEqual(fbo.attachment(), QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
                        self.assertEqual((fbo.width(), fbo.height()), (round(width * ratio), round(height * ratio)))
                    for layer in shader_layers:
                        self.assertEqual(getattr(compositor, layer + "_fbo").attachment(), QOpenGLFramebufferObject.Attachment.NoAttachment)
        finally:
            compositor._destroy_fbos()


if __name__ == "__main__":
    unittest.main()
