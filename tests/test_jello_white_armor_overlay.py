"""Armor-only pixels: white bloom, hollow quads, and display projection.

Run with --require-gpu on Windows to exercise real private OpenGL FBOs.
No client window, device, inference runtime, or persisted config is started.
"""
from __future__ import annotations

from dataclasses import replace
import math
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

if sys.platform != "win32" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REQUIRE_GPU = "--require-gpu" in sys.argv
if REQUIRE_GPU:
    sys.argv.remove("--require-gpu")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QOffscreenSurface, QOpenGLContext, QPainter, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtWidgets import QApplication

from rm_client.model import build_default_registry
from rm_client.ui.gpu_frame_compositor import GpuFrameCompositor
from rm_client.ui.polar.renderers.esp_wireframe import EspWireframeMixin
from rm_client.ui.vision_wire_gpu import VisionWireBatch, VisionWireGpuRenderer, armor_corner_segments
from rm_client.vision import ArmorObservation, VisionResult, VisionTarget

APP = QApplication.instance() or QApplication([])
SIZE = (960, 640)
POINTS = ((160.0, 100.0), (460.0, 115.0), (450.0, 300.0), (150.0, 285.0))


class ArmorHost(EspWireframeMixin):
    ROBOT_OVERLAY_COLOR_DEFAULT = "White"

    def __init__(self, *, locked=True, letterbox=False, mirror=False):
        self.registry = build_default_registry()
        self.state = SimpleNamespace(target_locked=locked, energy_target_locked=locked,
                                     target_distance_m=5.0, vision_kill_status="IDLE",
                                     energy_target_distance_m=8.0, energy_rune_progress=37,
                                     energy_rune_rotation="CCW")
        self._vision_snapshot = None
        self._armor_geometry_smooth = {}
        self._bottom_left_diagnostics = []
        self.letterbox = letterbox
        self.pills = []
        self.registry.get("CameraFeed").get_setting("Mirror").value = mirror
        self.registry.get("Armor3DESP").get_setting("Show Labels").value = False
        self.registry.get("LockState").get_setting("Pulse Locked").value = False

    def setting_bool(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return bool(setting.value) if setting else default

    def setting_mode(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return str(setting.value) if setting else default

    def get_setting_number(self, module, name, default):
        setting = module.get_setting(name) if module else None
        return float(setting.value) if setting else default

    def get_hud_scale(self, width, height):
        return 1.0

    def hero_deploy_video_cut_active(self):
        return self.letterbox

    def vision_result_calibrated(self, result):
        return result.calibrated

    def hud_accent(self):
        return QColor("#00ff66")

    def hud_danger(self):
        return QColor("#ff0000")

    def hud_warning(self):
        return QColor("#ffaa00")

    def font(self, name, size):
        font = QFont("Arial")
        font.setPointSizeF(size)
        return font

    def draw_pill(self, painter, point, text, tint):
        # Pills are outside the armor silhouette; isolate geometry pixels.
        self.pills.append((point, text, QColor(tint)))

    def draw_text(self, *args, **kwargs):
        pass

    def _client_asset_path(self, *parts):
        return ROOT.joinpath(*parts)


def result_fixture(*, aim=True):
    armor = ArmorObservation(1, "armor", "red", 0.93, POINTS, 5.0, aim=aim,
                             back_points=tuple((x - 7, y - 9) for x, y in POINTS), plate_id=1)
    return VisionResult(1, 1, 640, 480, detections=(armor,),
                        aim_armor=armor if aim else None, calibrated=True, tracking_state="locked")


class GeometryHost(ArmorHost):
    """Capture real CPU stroke geometry, not a replacement drawing algorithm."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.strokes = []

    def draw_fluorescent_white_segments(self, painter, segments, **kwargs):
        self.strokes.append((list(segments), kwargs))


def projected(points, result, *, letterbox=False, mirror=False, size=SIZE):
    width, height = size
    if letterbox:
        sx = sy = min(width / result.source_width, height / result.source_height)
        ox, oy = (width - result.source_width * sx) / 2, (height - result.source_height * sy) / 2
    else:
        sx, sy = width / result.source_width, height / result.source_height
        ox = oy = 0.0
    # Native Hero video bypasses the CameraFeed mirror setting.
    return [QPointF(ox + (result.source_width - x if mirror and not letterbox else x) * sx, oy + y * sy)
            for x, y in points]


def segment_key(start, end):
    return tuple(round(value, 5) for value in (start.x(), start.y(), end.x(), end.y()))


def raster(draw, ratio=1.0):
    image = QImage(round(SIZE[0] * ratio), round(SIZE[1] * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(0)
    painter = QPainter(image)
    # Deliberately dirty brush: geometry must not inherit a solid fill.
    painter.setBrush(QColor("#ff0000"))
    try:
        draw(painter)
    finally:
        painter.end()
    return image


def visible(image):
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha():
                yield x, y, pixel


class ArmorPixelAssertions:
    def assert_quad_edges_visible(self, image, points, ratio=1.0):
        # Corner-only/empty images must not pass as a continuous white outline.
        for index, start in enumerate(points):
            end = points[(index + 1) % 4]
            for step in range(1, 20):
                point = start + (end - start) * (step / 20)
                x, y = round(point.x() * ratio), round(point.y() * ratio)
                self.assertTrue(any(image.pixelColor(x + dx, y + dy).alpha() > 0
                                    for dx in (-1, 0, 1) for dy in (-1, 0, 1)),
                                f"Missing solid edge near {x},{y}")

    def assert_white_hollow(self, image, center, ratio=1.0):
        pixels = list(visible(image))
        self.assertGreater(len(pixels), 50, "An empty image is not a valid hollow frame")
        self.assertLess(len(pixels), image.width() * image.height() * 0.12)
        self.assertTrue(all(p.red() == p.green() == p.blue() and p.red() >= 250
                            for _, _, p in pixels), "Every visible geometry pixel must be neutral white")
        self.assertGreater(max(p.alpha() for _, _, p in pixels), 150, "Keep the bright core")
        self.assertTrue(any(0 < p.alpha() < 65 for _, _, p in pixels), "Keep the soft glow")
        cx, cy = round(center.x() * ratio), round(center.y() * ratio)
        for y in range(cy - 3, cy + 4):
            for x in range(cx - 3, cx + 4):
                self.assertEqual(image.pixelColor(x, y).alpha(), 0, f"Filled interior at {x},{y}")


class RasterArmorPixels(ArmorPixelAssertions, unittest.TestCase):
    def test_armor_lock_styles_are_white_for_locked_and_unlocked(self):
        rect = QRectF(200, 160, 300, 200)
        target = VisionTarget(rect.x(), rect.y(), rect.width(), rect.height(), 0.9, "armor")
        for style in ("White Outline", "Minimal Bracket", "Polar Corner"):
            for locked in (False, True):
                for ratio in (1.0, 1.5):
                    with self.subTest(style=style, locked=locked, dpr=ratio):
                        host = ArmorHost(locked=locked)
                        module = host.registry.get("ArmorAutoAim")
                        module.get_setting("Lock Style").value = style
                        image = raster(lambda p: host.draw_target_overlay(p, target, module), ratio)
                        self.assert_white_hollow(image, rect.center(), ratio)

    def test_armor_quad_uses_white_edges_and_corner_markers(self):
        host = ArmorHost()
        points = [QPointF(x, y) for x, y in POINTS]
        for aim in (False, True):
            with self.subTest(aim=aim):
                image = raster(lambda p: host.draw_armor_quad(p, points, QColor("#ff0000"), 2.0, aim=aim))
                self.assert_white_hollow(image, QPointF(305, 200))
                self.assert_quad_edges_visible(image, points)
                for point in points:
                    self.assertGreater(image.pixelColor(round(point.x()), round(point.y())).alpha(), 0)

    def test_jello_shadow_is_a_quad_glow_not_a_billboard(self):
        host = ArmorHost()
        module = host.registry.get("Armor3DESP")
        module.get_setting("Style").value = "JelloShadow"
        result = result_fixture(aim=False)
        image = raster(lambda p: host.draw_armor_3d_esp(p, *SIZE, result, module))
        self.assert_white_hollow(image, QPointF(457.5, 266.7))
        self.assertIsNone(getattr(host, "_jello_esp_shadow", None), "Do not load a HUD shadow texture for armor")

    def test_zero_opacity_jello_and_empty_results_leave_no_pixels(self):
        host = ArmorHost()
        module = host.registry.get("Armor3DESP")
        module.get_setting("Opacity").value = 0.0
        image = raster(lambda p: host.draw_armor_3d_esp(p, *SIZE, result_fixture(), module))
        self.assertFalse(list(visible(image)))
        result = replace(result_fixture(), detections=(), predicted_armors=(), aim_armor=None, tracking_state="lost")
        self.assertFalse(host.build_vision_wire_batch(*SIZE, result, module).lines)
        image = raster(lambda p: host.draw_armor_3d_esp(p, *SIZE, result, module))
        self.assertFalse(list(visible(image)))

    def test_display_batch_preserves_source_quad_and_input_result(self):
        result = result_fixture()
        for letterbox in (False, True):
            for mirror in (False, True):
                with self.subTest(letterbox=letterbox, mirror=mirror):
                    host = ArmorHost(letterbox=letterbox, mirror=mirror)
                    module = host.registry.get("Armor3DESP")
                    batch = host.build_vision_wire_batch(*SIZE, result, module)
                    for expected in projected(POINTS, result, letterbox=letterbox, mirror=mirror):
                        self.assertTrue(any(math.hypot(line.start.x() - expected.x(), line.start.y() - expected.y()) < 0.01
                                            for line in batch.lines), f"Missing projected quad vertex {expected}")
                    # Selection/FOV projection stays on its original coordinate contract.
                    gate_points = host.armor_esp_points(POINTS, result, *SIZE)
                    self.assertEqual(gate_points[0], QPointF((640 - 160 if mirror else 160) * 1.5, 100 * (640 / 480)))
                    self.assertEqual(result, result_fixture(), "Display drawing must never alter lock/detection data")
                    self.assertTrue(all(line.color.red() == line.color.green() == line.color.blue() == 255 for line in batch.lines))

    def test_cpu_and_gpu_front_back_projection_match_for_both_letterbox_axes(self):
        for source_size in ((640, 480), (1280, 360)):
            result = replace(result_fixture(), source_width=source_size[0], source_height=source_size[1])
            for letterbox in (False, True):
                for mirror in (False, True):
                    with self.subTest(source=source_size, letterbox=letterbox, mirror=mirror):
                        host = GeometryHost(letterbox=letterbox, mirror=mirror)
                        module = host.registry.get("Armor3DESP")
                        module.get_setting("Style").value = "JelloShadow"
                        host.draw_armor_3d_esp(None, *SIZE, result, module)
                        front = projected(POINTS, result, letterbox=letterbox, mirror=mirror)
                        self.assertEqual(host.strokes[0][0], [(front[i], front[(i + 1) % 4]) for i in range(4)])
                        back = host.armor_esp_back_points(result.aim_armor, result, *SIZE, 0.22)
                        self.assertEqual(back, projected(result.aim_armor.back_points, result, letterbox=letterbox, mirror=mirror))
                        batch = host.build_vision_wire_batch(*SIZE, result, module)
                        for point in front + back:
                            self.assertTrue(any(line.start == point for line in batch.lines))

    def test_corner_ticks_follow_short_and_degenerate_quad_edges(self):
        points = [QPointF(100, 100), QPointF(130, 105), QPointF(120, 115), QPointF(100, 110)]
        segments = armor_corner_segments(points)
        self.assertEqual(len(segments), 8)
        for index, (start, end) in enumerate(segments):
            neighbor = points[(index // 2 + (-1 if index % 2 == 0 else 1)) % 4]
            edge, tick = neighbor - start, end - start
            self.assertAlmostEqual(edge.x() * tick.y() - edge.y() * tick.x(), 0.0)
            self.assertAlmostEqual(math.hypot(tick.x(), tick.y()), math.hypot(edge.x(), edge.y()) * 0.24)
        self.assertFalse(armor_corner_segments(points[:3]))
        self.assertFalse(armor_corner_segments([QPointF(100, 100)] * 4))

    def test_show_depth_preserves_the_same_cpu_gpu_edge_set(self):
        result = result_fixture()
        for depth_on in (False, True):
            with self.subTest(show_depth=depth_on):
                host = GeometryHost()
                module = host.registry.get("Armor3DESP")
                module.get_setting("Show Depth").value = depth_on
                front = projected(POINTS, result)
                back = host.armor_esp_back_points(result.aim_armor, result, *SIZE, 0.22)
                host.draw_polar_mechanical_wire(None, front, back, QColor("red"), 2.0, predicted=False)
                cpu = {segment_key(a, b) for segments, _ in host.strokes for a, b in segments}
                batch = VisionWireBatch()
                host._append_vision_wire_armor(batch, front, back, width=2, alpha=1, predicted=False)
                gpu = {segment_key(line.start, line.end) for line in batch.lines}
                self.assertEqual(cpu, gpu)
                self.assertEqual(len(cpu), 22 if depth_on else 14)

    def test_prediction_is_dashed_without_observed_corner_ticks(self):
        host = GeometryHost()
        front = [QPointF(x, y) for x, y in POINTS]
        host.draw_polar_mechanical_wire(None, front, [], QColor("red"), 2, predicted=True)
        self.assertEqual(sum(len(segments) for segments, _ in host.strokes), 6)
        self.assertTrue(all(options["dashed"] for _, options in host.strokes))
        batch = VisionWireBatch()
        host._append_vision_wire_armor(batch, front, [], width=2, alpha=0.46, predicted=True)
        self.assertEqual(len({segment_key(line.start, line.end) for line in batch.lines}), 6)
        self.assertTrue(all(line.dash_length > 0 and line.gap_length > 0 for line in batch.lines))
        result = result_fixture(aim=False)
        predicted = replace(result.detections[0], predicted=True)
        prediction_only = replace(result, detections=(), predicted_armors=(predicted,))
        module = host.registry.get("Armor3DESP")
        module.get_setting("Style").value = "JelloShadow"
        host.strokes.clear()
        host.draw_armor_3d_esp(None, *SIZE, prediction_only, module)
        self.assertFalse(host.strokes, "Jello detection silhouette must not invent a detected armor from prediction")
        module.get_setting("Show Prediction").value = False
        self.assertFalse(host.build_vision_wire_batch(*SIZE, prediction_only, module).lines)
        module.get_setting("Show Prediction").value = True
        self.assertTrue(host.build_vision_wire_batch(*SIZE, prediction_only, module).lines)
        self.assertFalse(host.build_vision_wire_batch(*SIZE, replace(prediction_only, calibrated=False), module).lines)

    def test_lock_gate_pulse_and_energy_state_are_not_repurposed(self):
        host = GeometryHost(locked=False)
        rect = QRectF(200, 160, 80, 24)
        armor = VisionTarget(200, 160, 80, 24, 0.9, "armor")
        module = host.registry.get("ArmorAutoAim")
        gate = host.registry.get("LockState")
        gate.enabled = True
        gate.get_setting("Show Lock").value = False
        image = raster(lambda p: host.draw_target_overlay(p, armor, module))
        self.assertFalse(list(visible(image)))
        self.assertFalse(host.strokes)
        self.assertFalse(host.pills)
        gate.get_setting("Show Lock").value = True
        gate.get_setting("Pulse Locked").value = True
        with patch("rm_client.ui.polar.renderers.esp_wireframe.time.perf_counter", return_value=math.pi / 8):
            self.assertEqual(host.lock_pulse_strength(False), 0.0)
            self.assertEqual(host.lock_pulse_strength(True), 1.0)
        # Energy still uses its own lock bit and original accent/danger check.
        energy = replace(armor, label="energy", kind="energy")
        module = host.registry.get("EnergyAutoAim")
        module.get_setting("Lock Style").value = "White Outline"
        gate.get_setting("Pulse Locked").value = False
        for locked in (False, True):
            host.state.target_locked = not locked
            host.state.energy_target_locked = locked
            host.strokes.clear()
            image = raster(lambda p: host.draw_target_overlay(p, energy, module))
            self.assertAlmostEqual(host.strokes[0][1]["alpha"], 0.94 if locked else 0.62)
            ticks = host.strokes[1][0]
            self.assertEqual(ticks[0], (rect.topLeft(), rect.topLeft() + QPointF(17.6, 0)))
            self.assertTrue(any((p.green() > p.red() if locked else p.red() > p.green()) for _, _, p in visible(image)))
            self.assertIn("37%", host.pills[-1][1])

    def test_all_esp_styles_leave_white_hollow_geometry(self):
        for style in ("Wireframe3D", "Prediction Rack", "PolarOutline2D", "PolarMechanicalWire"):
            with self.subTest(style=style):
                host = ArmorHost()
                module = host.registry.get("Armor3DESP")
                module.get_setting("Style").value = style
                image = raster(lambda p: host.draw_armor_3d_esp(p, *SIZE, result_fixture(), module))
                self.assert_white_hollow(image, QPointF(457.5, 266.7))

    def test_zero_alpha_white_commands_produce_no_geometry(self):
        batch = VisionWireBatch()
        batch.fluorescent_line(QPointF(1, 2), QPointF(30, 40), width=1, alpha=0)
        batch.fluorescent_polyline([QPointF(1, 2), QPointF(30, 40)], width=1, alpha=0)
        self.assertFalse(batch.lines)

    def test_gpu_payload_stays_line_sized_and_scales_once(self):
        host = ArmorHost()
        batch = host.build_vision_wire_batch(*SIZE, result_fixture(), host.registry.get("Armor3DESP"))
        renderer = VisionWireGpuRenderer()
        try:
            payload = renderer._vertices(batch, 1.5)
            vertices = list(struct.iter_unpack("8f", payload))
            self.assertLess(len(payload), 200_000, "No framebuffer-sized CPU texture")
            self.assertGreater(len(vertices), 0)
            self.assertTrue(all(v[2] == v[3] == v[4] == 1.0 for v in vertices))
            self.assertTrue(all(math.isfinite(value) for vertex in vertices for value in vertex))
            first = batch.lines[0]
            self.assertAlmostEqual((vertices[0][0] + vertices[1][0]) / 2, first.start.x() * 1.5, places=4)
            self.assertAlmostEqual((vertices[0][1] + vertices[1][1]) / 2, first.start.y() * 1.5, places=4)
            self.assertFalse(batch.labels.commands)
            self.assertFalse(hasattr(batch, "fill"))
            self.assertFalse(hasattr(batch, "polygon"))
        finally:
            renderer.release()


class GpuArmorPixels(ArmorPixelAssertions, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        cls.context = QOpenGLContext()
        cls.context.setFormat(fmt)
        if not cls.context.create():
            cls.no_gpu("Qt cannot create a hidden OpenGL context")
        cls.surface = QOffscreenSurface()
        cls.surface.setFormat(cls.context.format())
        cls.surface.create()
        if not cls.surface.isValid() or not cls.context.makeCurrent(cls.surface):
            cls.no_gpu("Hidden desktop OpenGL surface unavailable")
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

    def render(self, draw, ratio=1.0, *, native=False, clear_after=False):
        self.assertTrue(self.context.makeCurrent(self.surface))
        compositor = GpuFrameCompositor()
        compositor.available = True
        renderer = None
        try:
            self.assertTrue(compositor.ensure_size(*SIZE, ratio), compositor.last_error)
            if native:
                self.assertTrue(compositor.begin_vision_layer(self.functions))
                renderer = VisionWireGpuRenderer()
                self.assertTrue(renderer.initialize(), renderer.last_error)
                self.assertTrue(renderer.render(self.functions, draw, *SIZE, ratio), renderer.last_error)
                self.assertEqual(renderer.draw_calls, 1 if draw.lines else 0)
                image = compositor.vision_fbo.toImage()
                compositor.end_vision_layer()
                if clear_after:
                    self.assertTrue(compositor.begin_vision_layer(self.functions))
                    self.assertTrue(renderer.render(self.functions, VisionWireBatch(), *SIZE, ratio))
                    self.assertEqual(renderer.draw_calls, 0)
                    image = compositor.vision_fbo.toImage()
                    compositor.end_vision_layer()
            else:
                device = compositor.paint_device("dynamic")
                self.assertIsNotNone(device)
                self.assertEqual(compositor.dynamic_fbo.attachment(), QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
                device.setDevicePixelRatio(ratio)
                compositor.clear_current(self.functions, transparent=True)
                painter = QPainter(device)
                painter.setBrush(QColor("#ff0000"))
                try:
                    self.assertTrue(painter.isActive())
                    draw(painter)
                finally:
                    painter.end()
                image = compositor.dynamic_fbo.toImage()
                compositor.release_layer("dynamic")
            return image
        finally:
            if renderer is not None:
                renderer.release()
            compositor._destroy_fbos()

    def test_private_qt_fbo_lock_is_hollow_white_not_red_rect(self):
        rect = QRectF(200, 160, 300, 200)
        target = VisionTarget(rect.x(), rect.y(), rect.width(), rect.height(), 0.9, "armor")
        for style in ("White Outline", "Minimal Bracket", "Polar Corner"):
            for locked in (False, True):
                with self.subTest(style=style, locked=locked):
                    host = ArmorHost(locked=locked)
                    module = host.registry.get("ArmorAutoAim")
                    module.get_setting("Lock Style").value = style
                    image = self.render(lambda p: host.draw_target_overlay(p, target, module), 1.5)
                    self.assert_white_hollow(image, rect.center(), 1.5)

    def test_native_gpu_quad_is_hollow_white_with_soft_edge(self):
        for ratio in (1.0, 1.5, 2.0):
            with self.subTest(dpr=ratio):
                host = ArmorHost()
                batch = host.build_vision_wire_batch(*SIZE, result_fixture(), host.registry.get("Armor3DESP"))
                image = self.render(batch, ratio, native=True)
                self.assert_white_hollow(image, QPointF(457.5, 266.7), ratio)
                self.assertEqual(image.pixelColor(round(240 * ratio), round(100 * (640 / 480) * ratio)).alpha() > 0, True)

    def test_real_qt_and_native_gpu_projection_keep_the_same_quad(self):
        result = result_fixture()
        for letterbox, mirror in ((False, True), (True, False), (True, True)):
            with self.subTest(letterbox=letterbox, mirror=mirror):
                host = ArmorHost(letterbox=letterbox, mirror=mirror)
                module = host.registry.get("Armor3DESP")
                module.get_setting("Style").value = "PolarMechanicalWire"
                front = projected(POINTS, result, letterbox=letterbox, mirror=mirror)
                center = QPointF(sum(p.x() for p in front) / 4, sum(p.y() for p in front) / 4)
                cpu = self.render(lambda p: host.draw_armor_3d_esp(p, *SIZE, result, module))
                gpu = self.render(host.build_vision_wire_batch(*SIZE, result, module), native=True)
                for image in (cpu, gpu):
                    self.assert_white_hollow(image, center)
                    self.assert_quad_edges_visible(image, front)
                    for point in front:
                        x, y = round(point.x()), round(point.y())
                        self.assertTrue(any(image.pixelColor(x + dx, y + dy).alpha() > 0
                                            for dx in (-1, 0, 1) for dy in (-1, 0, 1)))

    def test_real_qt_jello_silhouette_is_not_a_shadow_texture(self):
        host = ArmorHost()
        module = host.registry.get("Armor3DESP")
        image = self.render(lambda p: host.draw_armor_3d_esp(p, *SIZE, result_fixture(), module))
        self.assert_white_hollow(image, QPointF(457.5, 266.7))
        self.assert_quad_edges_visible(image, projected(POINTS, result_fixture()))
        self.assertIsNone(getattr(host, "_jello_esp_shadow", None))

    def test_empty_next_frame_clears_previous_native_geometry(self):
        host = ArmorHost()
        batch = host.build_vision_wire_batch(*SIZE, result_fixture(), host.registry.get("Armor3DESP"))
        image = self.render(batch, native=True, clear_after=True)
        self.assertFalse(list(visible(image)), "A lost target must not leave stale GL linework")


if __name__ == "__main__":
    unittest.main(verbosity=2)
