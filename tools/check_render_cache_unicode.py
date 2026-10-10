"""Offline Unicode/direction atlas comparison; no application/GL/device startup.

python tools/check_render_cache_unicode.py --baseline-root ../baseline
Add --qt5 only when deliberately using Qt5 raster output as a partial check.
Missing script fonts may render as fallback/tofu; this checks baseline equality.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--qt5", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    helpers = load("render_unicode_helpers", ROOT / "tests/test_render_performance_regressions.py")
    bench = load("render_unicode_bench", ROOT / "tools/benchmark_render_caches.py")
    qt = helpers.QT_GUI
    if qt is None:
        raise SystemExit("PySide6 unavailable; --qt5 explicitly opts into partial raster verification.")
    app = helpers.initialize_qt()
    core = __import__(qt.__name__.split(".")[0]+".QtCore", fromlist=["Qt"])
    font = qt.QFont("DejaVu Sans")
    font.setPointSizeF(12.75)
    texts = ["POLAR e\u0301 fi العربية אבג 😀", "POLAR e\u0301 fi العربية אבג 😀 目标 상태 カナ"]
    texts.append(texts[-1])
    comparisons = 0
    digest = hashlib.sha256()
    original_direction = app.layoutDirection()
    try:
        for direction in (core.Qt.LayoutDirection.LeftToRight, core.Qt.LayoutDirection.RightToLeft):
            app.setLayoutDirection(direction)
            for dpr in (1.0, 1.5, 2.0):
                for scale in (0.75, 1.3):
                    for preserve in (False, True):
                        for shaped in (False, True):
                            renderers = [bench.raster_renderer(helpers, root, qt, core) for root in (args.baseline_root, ROOT)]
                            for renderer in renderers:
                                renderer._pixel_ratio = dpr
                            previous = None
                            for index, text in enumerate(texts):
                                pages = [(r._ensure_shaped_atlas(font, [text], raster_scale=scale, preserve_weight=preserve) if shaped
                                          else r._ensure_atlas(font, text, raster_scale=scale, preserve_weight=preserve)) for r in renderers]
                                before, after = (bench.image_bytes(page.texture.image) for page in pages)
                                case = (int(direction), dpr, scale, preserve, shaped, index)
                                assert before == after and any(after), case
                                assert pages[0][1:] == pages[1][1:], case
                                assert [(r.atlas_generation, r.atlas_hits, r.atlas_misses) for r in renderers][0] == [(r.atlas_generation, r.atlas_hits, r.atlas_misses) for r in renderers][1], case
                                if index == 1:
                                    assert all(old.texture.destroyed for old in previous), case
                                elif index == 2:
                                    assert all(page is old and not page.texture.destroyed for page, old in zip(pages, previous)), case
                                previous = pages
                                digest.update(repr(case).encode("ascii"))
                                digest.update(after)
                                comparisons += 1
    finally:
        app.setLayoutDirection(original_direction)
    result = {"binding": qt.__name__, "comparisons_passed": comparisons, "changed_bytes": 0,
              "checks": ["pixels", "metrics", "generation", "hits", "misses", "texture retirement", "warm object identity"],
              "layout_directions": ["LTR", "RTL"], "dpr": [1.0, 1.5, 2.0], "raster_scales": [0.75, 1.3],
              "aggregate_pixels_sha256": digest.hexdigest(),
              "limit": "Relative CPU raster equality only; does not verify script-font coverage, PySide6/GL, full-screen animation or FPS."}
    payload = json.dumps(result, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
