"""Isolated ClickGUI draw-list contracts; no window/backend or aggregate runner.

Real Qt/font/image decoding, with GL upload replaced only in the prewarm test.
These tests validate assembly, not hardware GPU pixel output.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import CATEGORIES, Module, ModuleRegistry, Setting, build_default_registry
from rm_client.ui import clickgui_gpu as gpu
from rm_client.ui.endfield_clickgui import EndfieldClickGuiRenderer, IndustrialDrawList
from rm_client.ui.fonts import FontBook
from rm_client.ui.jello_clickgui import (
    JelloClickGuiRenderer, JelloClickGuiState, JelloMainTimeline,
    JELLO_MODULE_ROW, JELLO_PANEL_HEADER, _DropdownRequest,
)
from rm_client.ui.jello_locale import category_label

APP = QApplication.instance() or QApplication([])


def rect_key(rect):
    return None if rect is None else rect.getRect()


def geometry(payload):
    if isinstance(payload, gpu.GpuRect):
        return ("rect", rect_key(payload.rect), payload.radius, payload.outline_width,
                rect_key(payload.clip), payload.clip_radius)
    if isinstance(payload, gpu.GpuText):
        origin = payload.rotation_origin
        return ("text", rect_key(payload.rect), payload.text, payload.font.toString(),
                payload.alignment, rect_key(payload.clip), payload.shadow,
                payload.rotation_degrees, payload.render_scale,
                None if origin is None else (origin.x(), origin.y()),
                payload.raster_scale, payload.preserve_weight, payload.text_profile,
                payload.device_pixel_snap)
    return ("image", rect_key(payload.rect), payload.source, payload.tint.rgba(),
            rect_key(payload.clip), payload.nearest)


def registry_fixture():
    modules = [Module(f"{category} module {i}", category, enabled=i % 2 == 0)
               for category in CATEGORIES for i in range(14)]
    modules.append(Module("ClickGui", "System", description="ClickGUI description", settings=[
        Setting("Scale", "number", 1.0, .5, 2., .05),
        Setting("Language", "mode", "English", options=["English", "简体中文"]),
        Setting("Enabled", "bool", True),
        Setting("Mode", "mode", "Option 0", options=[f"Option {i}" for i in range(24)]),
        Setting("Action", "action", "Run"),
    ]))
    return ModuleRegistry(modules)


class Host:
    """Only renderer input ports: no services, native windows or output adapters."""
    def __init__(self, fonts, registry=None):
        self.fonts = fonts
        self.registry = registry if registry is not None else registry_fixture()
        self.hover_point = QPointF(-1, -1)
        self.gui_visible = True
        self.gui_timeline = JelloMainTimeline()
        self.gui_timeline.reset(1)
        self.hotspots = []
        self.gui_scroll_viewports = []

    def font(self, key, size):
        return self.fonts.font(key, size)

    def current_profile(self):
        return "theme-contract"

    def add_hotspot(self, rect, action, payload=None, button=None, tooltip=""):
        self.hotspots.append((rect_key(rect), action, payload, button, tooltip))


class EndfieldClickGuiThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = FontBook()
        cls.fonts.load_from_project_assets(ROOT, keys={"jello_light", "jello_medium"})

    def setUp(self):
        self.host = Host(self.fonts)
        self.plain = JelloClickGuiRenderer(ROOT / "assets/jello")
        self.themed = EndfieldClickGuiRenderer(ROOT / "assets/jello")

    def frame(self, renderer, state, width=1920, height=1080):
        self.host.hotspots = []
        self.host.gui_scroll_viewports = []
        # Both renderers see independent copies of the same animation state.
        with patch("rm_client.ui.jello_clickgui.time.perf_counter", return_value=10.):
            commands = renderer.build(self.host, deepcopy(state), width, height,
                                      self.host.gui_timeline.progress)
        viewports = [(v["mode"], v["key"], v["maximum"], rect_key(v["rect"]))
                     for v in self.host.gui_scroll_viewports]
        return commands, list(self.host.hotspots), viewports

    def assert_original_geometry(self, plain, themed):
        # Every original primitive must occur in order, with all geometry and
        # text sampling unchanged. Only extra chrome and colours are allowed.
        remaining = iter(geometry(c.payload) for c in themed.commands)
        for command in plain.commands:
            expected = geometry(command.payload)
            self.assertTrue(any(actual == expected for actual in remaining), expected)
        self.assertEqual([c.sequence for c in themed.commands], list(range(len(themed.commands))))
        for kind, items in ((gpu.GpuRect, themed.rects), (gpu.GpuText, themed.texts),
                            (gpu.GpuImage, themed.images)):
            self.assertEqual([c.payload for c in themed.commands if isinstance(c.payload, kind)], items)

    def test_hotspots_geometry_and_text_sampling_across_scales_and_timelines(self):
        for width, height, requested in ((960, 540, .5), (1280, 720, 1.),
                                         (1920, 1080, 1.35), (2560, 1440, 2.)):
            self.host.registry.get("ClickGui").get_setting("Scale").value = requested
            for language in ("English", "简体中文"):
                self.host.registry.get("ClickGui").get_setting("Language").value = language
                for target, progress in ((1, 0), (1, .19), (1, 1), (0, .4)):
                    with self.subTest(size=(width, height), scale=requested,
                                      language=language, target=target, progress=progress):
                        self.host.gui_timeline.progress = progress
                        self.host.gui_timeline.target = target
                        state = JelloClickGuiState()
                        state.panel_scroll = {category: 37.5 for category in CATEGORIES}
                        plain, hits, views = self.frame(self.plain, state, width, height)
                        themed, new_hits, new_views = self.frame(self.themed, state, width, height)
                        self.assertEqual(hits, new_hits)
                        self.assertEqual(views, new_views)
                        self.assert_original_geometry(plain, themed)
                        original_text = [geometry(t) for t in plain.texts]
                        themed_text = [geometry(t) for t in themed.texts if not t.text.startswith("/")]
                        self.assertEqual(original_text, themed_text)
                        self.assertIsNone(themed._before_panel_title)
        self.assertEqual((self.host.gui_timeline.forward_duration,
                          self.host.gui_timeline.reverse_duration), (.450, .125))

    def test_default_catalog_modal_dropdown_and_closing_hotspots_match(self):
        self.host.registry = build_default_registry()
        for module_name in (None, "HUD", "ClickGui"):
            state = JelloClickGuiState()
            if module_name:
                state.open_settings(module_name)
                state.update(.5)
            for visible in (True, False):
                self.host.gui_visible = visible
                with self.subTest(module=module_name, visible=visible):
                    plain, hits, views = self.frame(self.plain, state)
                    themed, new_hits, new_views = self.frame(self.themed, state)
                    self.assertEqual(hits, new_hits)
                    self.assertEqual(views, new_views)
                    self.assert_original_geometry(plain, themed)
                    if not visible:
                        self.assertEqual(new_hits, [])
                        self.assertEqual(new_views, [])

    def test_original_sprites_are_clipped_inside_cards_and_below_their_labels(self):
        commands, _, _ = self.frame(self.themed, JelloClickGuiState())
        layout = self.themed.layout(1920, 1080)
        theme_paths = {str(p) for p in (self.themed.terrain_image, self.themed.contour_image,
                                       self.themed.texture_image)}
        decorations = [c for c in commands.commands if isinstance(c.payload, gpu.GpuImage)
                       and c.payload.source in theme_paths]
        self.assertEqual(len(decorations), len(CATEGORIES) * 3)
        for category, panel in layout.panels.items():
            title = next(c for c in commands.commands if isinstance(c.payload, gpu.GpuText)
                         and c.payload.text == category_label(category, False))
            self.assertEqual(title.payload.color.name(), "#212121")
            own = [c for c in decorations if panel.contains(c.payload.clip)]
            self.assertEqual(len(own), 3)
            self.assertTrue(all(c.sequence < title.sequence for c in own))
            terrain = next(c.payload for c in own if c.payload.source == str(self.themed.terrain_image))
            self.assertLessEqual(terrain.clip.bottom(), panel.top() + JELLO_PANEL_HEADER)
            self.assertEqual(terrain.tint, QColor(255, 255, 255))
            source = self.themed._compat_images[terrain.source]
            self.assertAlmostEqual(terrain.rect.width() / terrain.rect.height(),
                                   source.width() / source.height())

    def test_modal_and_popup_stay_above_all_decoration_during_open_and_close(self):
        for raw, closing in ((.25, False), (1., False), (.45, True)):
            with self.subTest(raw=raw, closing=closing):
                state = JelloClickGuiState()
                state.open_settings("ClickGui")
                state.update(.5)
                state.toggle_dropdown("ClickGui:Language")
                state.dropdown_animation.reset(.6)
                state.dropdown_animation.set_target(0 if closing else 1)
                if closing:
                    state.close_settings()
                state.settings_panel_animation.progress = raw
                state.settings_background_animation.progress = raw
                plain, hits, views = self.frame(self.plain, state)
                themed, new_hits, new_views = self.frame(self.themed, state)
                self.assertEqual(hits, new_hits)
                self.assertEqual(views, new_views)
                self.assert_original_geometry(plain, themed)
                self.assertTrue(any(hit[1] == "jello_mode_select" for hit in new_hits))
                first_modal = next(c.sequence for c in themed.commands
                                   if isinstance(c.payload, gpu.GpuRect)
                                   and c.payload.rect == QRectF(0, 0, 1920, 1080)
                                   and c.sequence > 0)
                self.assertTrue(all(c.sequence < first_modal for c in themed.commands
                                    if isinstance(c.payload, gpu.GpuImage)
                                    and "endfield_settings" in c.payload.source))

    def test_dropdown_reveal_scroll_direction_and_seal_clips_are_unchanged(self):
        setting = self.host.registry.get("ClickGui").get_setting("Mode")
        for scale in (.5, 1., 2.):
            for opens_up in (False, True):
                for raw, target in ((.15, 1), (1., 1), (.6, 0)):
                    with self.subTest(scale=scale, up=opens_up, raw=raw, target=target):
                        state = JelloClickGuiState()
                        state.dropdown_animation.reset(raw)
                        state.dropdown_animation.set_target(target)
                        state.dropdown_scroll = 41.5
                        request = _DropdownRequest("ClickGui:Mode", setting,
                                                   QRectF(100, 220, 123 * scale, 27 * scale),
                                                   QRectF(80, 60, 400 * scale, 400 * scale),
                                                   .8, scale, opens_up)
                        plain, themed = gpu.ClickGuiDrawList(), IndustrialDrawList()
                        self.host.hotspots = []; self.host.gui_scroll_viewports = []
                        self.plain._build_dropdown_popup(self.host, deepcopy(state), plain, request)
                        hits = list(self.host.hotspots)
                        views = deepcopy(self.host.gui_scroll_viewports)
                        self.host.hotspots = []; self.host.gui_scroll_viewports = []
                        self.themed._build_dropdown_popup(self.host, deepcopy(state), themed, request)
                        self.assertEqual(hits, self.host.hotspots)
                        self.assertEqual(views, self.host.gui_scroll_viewports)
                        self.assertTrue(hits)
                        self.assertEqual([geometry(c.payload) for c in plain.commands],
                                         [geometry(c.payload) for c in themed.commands])

    def test_enabled_markers_follow_clamped_scroll_and_panel_mask(self):
        for requested_scroll in (-100., 37.5, 1.e6):
            with self.subTest(scroll=requested_scroll):
                state = JelloClickGuiState()
                state.panel_scroll = {category: requested_scroll for category in CATEGORIES}
                commands, _, viewports = self.frame(self.themed, state)
                markers = [r for r in commands.rects
                           if r.fill.name() == "#fff100" and r.rect.width() == 2]
                expected = []
                for category, panel in self.themed.layout(1920, 1080).panels.items():
                    view = next(v for v in viewports if v[1] == category)
                    viewport = QRectF(*view[3])
                    scroll = max(0., min(view[2], requested_scroll))
                    for i, module in enumerate(self.themed._modules_for(self.host, category)):
                        rect = QRectF(panel.left() + 3,
                                      viewport.top() + i * JELLO_MODULE_ROW - scroll + 7,
                                      2, 16).intersected(viewport)
                        if module.enabled and not rect.isEmpty():
                            expected.append((rect_key(rect), rect_key(panel), 10.))
                self.assertEqual([(rect_key(r.rect), rect_key(r.clip), r.clip_radius)
                                  for r in markers], expected)

    def test_images_prewarm_once_and_frame_builds_do_not_read_files_or_grow_caches(self):
        real_texture = gpu.QOpenGLTexture

        class Texture:
            MipMapGeneration = real_texture.MipMapGeneration
            Filter = real_texture.Filter
            WrapMode = real_texture.WrapMode
            def __init__(self, image, *args):
                self.image = QImage(image)
            def setMinificationFilter(self, value): pass
            def setMagnificationFilter(self, value): pass
            def setWrapMode(self, value): pass

        with patch.object(gpu, "QOpenGLTexture", Texture):
            uploads = gpu.ClickGuiGpuRenderer()
            uploads.available = True
            uploads.prewarm_images(self.themed.image_assets)
            keys = set(uploads.image_textures)
            self.assertEqual(keys, {str(p) for p in self.themed.image_assets})
            self.assertTrue(all(not t.image.isNull() for t in uploads.image_textures.values()))
            compat_keys = set(self.themed._compat_images)
            aspects = dict(self.themed._theme_aspects)
            state = JelloClickGuiState()
            self.frame(self.themed, state)  # Populate the finite font/name caches.
            font_keys = set(self.themed._font_cache)
            with ExitStack() as stack:
                for method in ("resolve", "is_file", "stat", "open", "read_bytes", "read_text"):
                    stack.enter_context(patch.object(Path, method, side_effect=AssertionError(method)))
                stack.enter_context(patch("rm_client.ui.endfield_clickgui.QImage",
                                          side_effect=AssertionError("frame image decode")))
                stack.enter_context(patch.object(gpu, "QImage", side_effect=AssertionError("GPU decode")))
                uploads._atlas_locked = True
                for i in range(60):
                    self.host.gui_timeline.progress = (i % 10) / 9
                    commands, _, _ = self.frame(self.themed, state, 1280 + i * 3, 720 + i * 2)
                    uploads._prepare_images(commands)
                self.assertEqual(set(uploads.image_textures), keys)
                self.assertEqual(set(self.themed._compat_images), compat_keys)
                self.assertEqual(self.themed._theme_aspects, aspects)
                self.assertEqual(set(self.themed._font_cache), font_keys)

    def test_base_renderer_remains_standalone_and_unmodified(self):
        state = JelloClickGuiState()
        before, hits, _ = self.frame(self.plain, state)
        self.frame(self.themed, state)
        after, new_hits, _ = self.frame(self.plain, state)
        self.assertEqual(before, after)
        self.assertEqual(hits, new_hits)
        self.assertIs(type(after), gpu.ClickGuiDrawList)
        self.assertFalse(any("endfield_settings" in image.source for image in after.images))
        self.assertTrue(any(r.fill.name() == "#29a6ff" for r in after.rects))

    def test_missing_assets_fall_back_and_chrome_hook_is_exception_safe(self):
        renderer = EndfieldClickGuiRenderer(ROOT / "missing-theme-assets/jello")
        commands, _, _ = self.frame(renderer, JelloClickGuiState())
        self.assertEqual(commands.images, [])
        title = next(t for t in commands.texts if t.text == "Combat")
        self.assertEqual(title.color.name(), "#eeeeee")
        self.assertIsNone(commands._before_panel_title)
        with self.assertRaisesRegex(RuntimeError, "panel failed"):
            with commands.panel_chrome(lambda: True):
                raise RuntimeError("panel failed")
        self.assertIsNone(commands._before_panel_title)

    def test_preloaded_raster_diagnostic_path_does_not_reload_sprites(self):
        image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#202224"))
        painter = QPainter(image)
        try:
            with patch("rm_client.ui.jello_clickgui.QImage", side_effect=AssertionError("paint decode")):
                self.themed.paint_compat(self.host, JelloClickGuiState(), painter, 1280, 720, 1.)
        finally:
            painter.end()
        # A quiet topographic-yellow area, not just the registration underline.
        pixel = image.pixelColor(65, 40)
        self.assertGreater(pixel.red(), 180)
        self.assertGreater(pixel.green(), 180)
        self.assertLess(pixel.blue(), 80)


if __name__ == "__main__":
    unittest.main()
