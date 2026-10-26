"""Compare reviewed render helpers with a local pre-change checkout/snapshot.

No app startup, GL context, devices, network, dependency install, or subprocess.
Example: python tools/benchmark_render_caches.py --baseline-root ../baseline
Use --qt5 explicitly for raster-only verification when PySide6 is unavailable.
This reports CPU helper costs, not application frame time or achieved FPS.
"""
from __future__ import annotations

import argparse
from collections import namedtuple
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.ui.jello.resources import FONTS, JelloResources


def time_pair(before, after, *, iterations=200, samples=9):
    for _ in range(20):
        before()
        after()
    values = {"before": [], "after": []}
    gc_enabled = gc.isenabled()
    gc.disable()
    try:
        for sample in range(samples):
            order = (("before", before), ("after", after))
            if sample % 2:
                order = tuple(reversed(order))
            for name, callback in order:
                start = time.perf_counter_ns()
                for _ in range(iterations):
                    callback()
                values[name].append((time.perf_counter_ns() - start) / iterations / 1000.0)
    finally:
        if gc_enabled:
            gc.enable()
    result = {name: {"median_us": statistics.median(v), "min_us": min(v), "max_us": max(v)} for name, v in values.items()}
    result["speedup"] = result["before"]["median_us"] / result["after"]["median_us"]
    result["iterations_per_sample"] = iterations
    result["samples"] = samples
    return result


def image_bytes(image):
    bits = image.constBits()
    size = image.sizeInBytes()
    if hasattr(bits, "setsize"):
        bits.setsize(size)  # PyQt5's sip.voidptr, not PySide6's memoryview.
    return bytes(bits)[:size]


def raster_renderer(helpers, root, qt, core):
    """Actual atlas layout/raster methods with an inert texture publisher.

    This verifies CPU-generated atlas bytes, never OpenGL driver behavior.
    """
    class Texture:
        MipMapGeneration = SimpleNamespace(DontGenerateMipMaps=0)
        Filter = SimpleNamespace(Linear=1)
        WrapMode = SimpleNamespace(ClampToEdge=2)

        def __init__(self, image, _mips):
            self.image = image.copy()
            self.destroyed = False

        def setMinificationFilter(self, value):
            self.min_filter = value

        def setMagnificationFilter(self, value):
            self.mag_filter = value

        def setWrapMode(self, value):
            self.wrap = value

        def destroy(self):
            self.destroyed = True

    namespace = {name: getattr(qt, name) for name in ("QFont", "QFontMetricsF", "QImage", "QPainter", "QColor", "QTextLayout", "QTextOption", "QTextCharFormat")}
    namespace.update({"QPointF": core.QPointF, "QRectF": core.QRectF, "Qt": core.Qt, "math": math,
                      "QOpenGLTexture": Texture, "dataclass": lambda **_: lambda cls: cls,
                      "QFontDatabase": SimpleNamespace(
                          families=lambda: qt.QFontDatabase().families() if qt.__name__.startswith("PyQt5") else qt.QFontDatabase.families(),
                          systemFont=qt.QFontDatabase.systemFont, SystemFont=qt.QFontDatabase.SystemFont),
                      "GpuText": SimpleNamespace,
                      "GlyphAtlasSnapshot": namedtuple("GlyphAtlasSnapshot", "generation keys")})
    for name, fields in (("_Glyph", "u0 v0 u1 v1 advance offset_x offset_y width height"),
                         ("_ShapedLine", "u0 v0 u1 v1 advance offset_x offset_y width height line_height ascent"),
                         ("_GlyphAtlas", "texture glyphs raster_font ratio sample_scale raster_scale"),
                         ("_ShapedTextAtlas", "texture lines raster_font ratio sample_scale raster_scale")):
        namespace[name] = namedtuple(name, fields)
    policy = helpers.isolated_class(root, "rm_client/ui/clickgui_gpu.py", "SmallTextPolicy", namespace=namespace)
    cls = helpers.isolated_class(root, "rm_client/ui/clickgui_gpu.py", "ClickGuiGpuRenderer", {
        "_font_key", "_ensure_atlas", "_ensure_shaped_atlas", "_jello_text_layout", "_jello_cjk_family", "_is_cjk_character", "_prepare_atlases",
    }, namespace=namespace)
    r = cls()
    r._pixel_ratio = 1.0
    r._atlas_chars, r._shaped_texts, r._shaped_layouts = {}, {}, {}
    r.atlases, r.shaped_atlases = {}, {}
    r.atlas_hits = r.atlas_misses = r.atlas_generation = 0
    r._atlas_locked = False
    r._jello_cjk_family_cache = ""
    r.small_text_policy = policy()
    return r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", required=True, type=Path)
    parser.add_argument("--qt5", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("render_cache_test_helpers", ROOT / "tests/test_render_performance_regressions.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    qt = helpers.QT_GUI
    if qt is None:
        raise SystemExit("PySide6 unavailable; --qt5 explicitly enables raster-only verification.")
    helpers.initialize_qt()

    cls = lambda root: helpers.isolated_class(root, "rm_client/ui/fonts.py", "FontBook", namespace={
        "Path": Path, "QFont": qt.QFont, "QFontDatabase": qt.QFontDatabase,
    })
    books = [cls(args.baseline_root)(), cls(ROOT)()]
    # Only register the bundled font files explicitly, with no recursive scan.
    families = {}
    for key, filename in (("jello_light", "Jello-Helvetica-Neue-Light.ttf"),
                          ("jello_medium", "Jello-Helvetica-Neue-Medium.ttf"),
                          ("poppins_regular", "Poppins-Regular.ttf"),
                          ("tahoma", "tahoma.ttf")):
        font_path = (JelloResources.for_workspace(ROOT).font(filename) if filename in FONTS
                     else ROOT / 'assets/fonts' / filename)
        font_id = qt.QFontDatabase.addApplicationFont(str(font_path))
        names = qt.QFontDatabase.applicationFontFamilies(font_id)
        if names:
            families[key] = names[0]
    for book in books:
        book.loaded.update(families)
    requests = [
        ("jello_light", 15.0, None), ("jello_medium", 18.75, None),
        ("poppins_regular", 12.0, None), ("pingfang", 14.25, qt.QFont.Weight.Bold),
        ("tahoma", 16.0, None), ("material", 17.0, None),
        ("jello_light", 12.0001, None), ("jello_light", 12.0002, None),
    ] * 16
    def fonts(book):
        for key, size, weight in requests:
            book.font(key, size, weight)

    result = {"python": sys.version, "platform": platform.platform(), "binding": qt.__name__,
              "scope": "CPU helper microbenchmarks and QImage raster output only; no application FPS or OpenGL validation",
              "font_requests_per_batch": len(requests), "bundled_families": families,
              "font_batch": time_pair(lambda: fonts(books[0]), lambda: fonts(books[1]))}
    font_checks = 0
    for key, size, weight in requests:
        a, b = (book.font(key, size, weight) for book in books)
        assert a == b, (key, size, weight, a.key(), b.key())
        font_checks += 1

    # Verify complete QImage buffers at different DPRs and DPI settings,
    # including anti-aliased/CJK/fallback/light/medium/Tahoma text and clipping.
    from importlib import import_module
    core = import_module("PyQt5.QtCore" if args.qt5 else "PySide6.QtCore")
    pixel_checks = []
    for dpr in (1.0, 1.5, 2.0):
        for dpi in (96, 120, 144):
            images = []
            for book in books:
                image = qt.QImage(round(720*dpr), round(480*dpr), qt.QImage.Format.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.setDotsPerMeterX(round(dpi/0.0254))
                image.setDotsPerMeterY(round(dpi/0.0254))
                image.fill(qt.QColor("#20252b"))
                painter = qt.QPainter(image)
                painter.setRenderHint(qt.QPainter.RenderHint.TextAntialiasing, True)
                painter.setPen(qt.QColor("#fefefe"))
                for index, (key, size, weight) in enumerate(requests[:8]):
                    painter.setFont(book.font(key, size, weight))
                    painter.drawText(core.QRectF(13.25, 12.75+index*54, 675.5, 49.0),
                                     int(core.Qt.AlignmentFlag.AlignLeft | core.Qt.AlignmentFlag.AlignVCenter),
                                     "POLAR-RM 144 FPS 目标状态 / ABC abc 0123456789")
                painter.end()
                images.append(image)
            before, after = map(image_bytes, images)
            assert before == after, (dpr, dpi)
            pixel_checks.append({"dpr": dpr, "dpi": dpi, "changed_bytes": 0, "sha256": hashlib.sha256(after).hexdigest()})
    result["equal_font_values"] = font_checks
    result["pixel_comparisons"] = pixel_checks

    result["atlas_cases"] = []
    for kind, count, requested_count in (("glyph", 95, 40), ("glyph", 512, 80), ("glyph", 1024, 250),
                                         ("glyph", 95, 95), ("glyph", 512, 512),
                                         ("shaped", 128, 45), ("shaped", 512, 45), ("shaped", 2048, 45),
                                         ("shaped", 128, 128), ("shaped", 512, 512)):
        renderers = [helpers.atlas_renderer(root) for root in (args.baseline_root, ROOT)]
        font = helpers.fake_font()
        if kind == "glyph":
            known = {chr(0x400+index) for index in range(count)}
            requested = "".join(sorted(known)[:requested_count])
        else:
            known = {f"Module {index:04} · 参数" for index in range(count)}
            requested = sorted(known)[:requested_count]
        page = object()
        for r in renderers:
            key = r._font_key(font)
            (r._atlas_chars if kind == "glyph" else r._shaped_texts)[key] = set(known)
            (r.atlases if kind == "glyph" else r.shaped_atlases)[key] = page
        methods = [(r._ensure_atlas if kind == "glyph" else r._ensure_shaped_atlas) for r in renderers]
        measured = time_pair(lambda: methods[0](font, requested), lambda: methods[1](font, requested), iterations=2000)
        for method in methods:
            assert method(font, requested) is page
        assert all(r.atlas_generation == 7 and r.atlas_misses == 0 for r in renderers)
        result["atlas_cases"].append({"kind": kind, "known_count": count, "requested_count": requested_count, **measured})

    # Font-size churn deliberately misses the cache. Measure its overhead
    # separately so the warm-cache win does not conceal the tradeoff.
    def cold_fonts(book):
        if hasattr(book, "_font_cache"):
            book._font_cache.clear()
        for index in range(128):
            book.font("jello_light", 12 + index / 1000)
    result["cold_font_batch"] = time_pair(lambda: cold_fonts(books[0]), lambda: cold_fonts(books[1]))

    # Cold and incrementally rebuilt atlases must retain exact pixels,
    # placement/metrics, generation and texture disposal behavior.
    renderers = [raster_renderer(helpers, root, qt, core) for root in (args.baseline_root, ROOT)]
    atlas_pixels = []
    previous_pages = {}
    font = books[0].font("jello_light", 15.0)
    for dpr in (1.0, 1.5, 2.0):
        for kind in ("glyph", "shaped"):
            for step, text in enumerate(("POLAR 144 FPS", "POLAR 144 FPS 目标状态", "POLAR 144 FPS 目标状态")):
                pages = []
                for renderer in renderers:
                    renderer._pixel_ratio = dpr
                    method = renderer._ensure_atlas if kind == "glyph" else renderer._ensure_shaped_atlas
                    page = method(font, text if kind == "glyph" else [text], preserve_weight=True)
                    pages.append(page)
                a, b = pages
                before_pixels, after_pixels = image_bytes(a.texture.image), image_bytes(b.texture.image)
                assert any(after_pixels), "Atlas must contain painted glyph pixels"
                assert before_pixels == after_pixels
                assert (a.glyphs if kind == "glyph" else a.lines) == (b.glyphs if kind == "glyph" else b.lines)
                assert a.raster_font == b.raster_font and a[3:] == b[3:]
                assert [(r.atlas_generation, r.atlas_hits, r.atlas_misses) for r in renderers][0] == [(r.atlas_generation, r.atlas_hits, r.atlas_misses) for r in renderers][1]
                previous = previous_pages.get((kind, dpr))
                if step == 1:
                    assert all(old.texture.destroyed for old in previous)
                    assert all(new is not old for new, old in zip(pages, previous))
                elif step == 2:
                    assert all(new is old and not new.texture.destroyed for new, old in zip(pages, previous))
                previous_pages[kind, dpr] = pages
                atlas_pixels.append({"kind": kind, "dpr": dpr, "step": step, "changed_bytes": 0,
                                     "sha256": hashlib.sha256(image_bytes(b.texture.image)).hexdigest()})
    result["atlas_raster_comparisons"] = atlas_pixels

    # Exercise the actual per-frame grouping + preparation method as well as
    # individual cache lookups, using 80 commands over four resident pages.
    renderers = [raster_renderer(helpers, root, qt, core) for root in (args.baseline_root, ROOT)]
    texts = []
    for index in range(80):
        font_index = index % 4
        cmd_font = books[0].font("jello_light", 12.0 + font_index)
        texts.append(SimpleNamespace(font=cmd_font, text=f"Module {index:04} · 参数", raster_scale=1.0,
                                     preserve_weight=True, text_profile="jello" if font_index % 2 else ""))
    draw_list = SimpleNamespace(commands=[SimpleNamespace(payload=text) for text in texts])
    for renderer in renderers:
        for text in texts:
            key = renderer._font_key(text.font, text.raster_scale, text.preserve_weight)
            if text.text_profile == "jello":
                renderer._shaped_texts[key] = {f"Module {index:04} · 参数" for index in range(512)}
                renderer.shaped_atlases[key] = object()
            else:
                renderer._atlas_chars[key] = set("Module 0123456789 · 参数") | {chr(0x400+index) for index in range(480)}
                renderer.atlases[key] = object()
        renderer._atlas_locked = True
    result["warm_prepare_80_commands_4_pages"] = time_pair(
        lambda: renderers[0]._prepare_atlases(draw_list), lambda: renderers[1]._prepare_atlases(draw_list), iterations=500)
    assert renderers[0].atlas_snapshot == renderers[1].atlas_snapshot

    result["production_source_sha256"] = {
        label: {relative: hashlib.sha256((root/relative).read_bytes()).hexdigest()
                for relative in ("rm_client/ui/fonts.py", "rm_client/ui/clickgui_gpu.py")}
        for label, root in (("before", args.baseline_root), ("after", ROOT))
    }
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
