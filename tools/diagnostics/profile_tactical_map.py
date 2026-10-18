"""Finite offscreen map CPU-raster elapsed-time diagnostic; never a native GPU/FPS benchmark.

Run with the repository test dependencies installed:
    python tools/diagnostics/profile_tactical_map.py

Uses the existing actual-window test host (including its inert device settings
and lifecycle cleanup), real map PNGs, production painters, fixed 1920x1080
geometry, DPR 1 and a 24-frame transition repeated once with warm caches.
No live telemetry, network, capture, playback or native GL presentation is used.
Qt multimedia initialization is possible. JSON summaries go to stdout only.
The finite workload has no internal timeout; use an external process watchdog.
Setup inherits the test host's partial-construction cleanup limitations.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
# This diagnostic always uses offscreen, even with a desktop platform inherited.
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
# The test host establishes the remaining device-isolation settings before Qt starts.
from test_tactical_map_contract import TacticalMapContractTests
from tactical_map_contract_fixture import scene, pixels
from PySide6 import __version__ as QT_BINDING_VERSION
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from rm_client.ui.tactical_map_geometry import MapExtent

SEQUENCE = (0., 0., *(i / 10 for i in range(1, 11)), 1.,
            *(i / 10 for i in range(9, -1, -1)), 0.)


def summarize(frames):
    paint = [frame['paint_ms'] for frame in frames]
    rounded = [sample for frame in frames for sample in frame['rounded']]
    return {
        'frames': len(frames), 'first_ms': paint[0],
        'median_ms': statistics.median(paint), 'max_ms': max(paint),
        'total_ms': sum(paint), 'rounded_calls': len(rounded),
        'rounded_hits': sum(sample['hit'] for sample in rounded),
        'rounded_misses': sum(not sample['hit'] for sample in rounded),
        'rounded_allocated_bytes': sum(sample['bytes'] for sample in rounded),
        'rounded_total_ms': sum(sample['ms'] for sample in rounded),
    }


def measure(window, mode, liquid):
    with scene(window, mode=mode, liquid=liquid, hold=True, progress=0):
        path = window.paths.resource_root / window.match_mode_manager.current.field.asset_path
        started = time.perf_counter_ns()
        image = QImage(str(path))
        decode_ms = (time.perf_counter_ns() - started) / 1e6
        if image.isNull():
            raise RuntimeError(f'Map asset could not be decoded: {path}')
        window.map_images = {str(path): image}
        base = MapExtent.collapsed(1920, 1080, 'Wide', 'CombatCompact', False)
        target = base.target(1920, 1080, True)
        original = window._rounded_map_layer
        records, samples = [], []

        def rounded(*args):
            previous = list(window._map_round_cache.values())
            started = time.perf_counter_ns()
            result = original(*args)
            elapsed = (time.perf_counter_ns() - started) / 1e6
            hit = any(result is entry for entry in previous)
            samples.append({'hit': hit, 'ms': elapsed,
                            'bytes': 0 if hit or result is None else result.sizeInBytes()})
            return result

        surface = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
        with patch.object(window, '_rounded_map_layer', side_effect=rounded):
            for progress in SEQUENCE * 2:
                window.tactical_map_state.container.content.progress = progress
                rect = QRectF(12, 58, base.width + (target.width - base.width) * progress,
                              base.height + (target.height - base.height) * progress)
                samples.clear()
                window.hotspots.clear()
                surface.fill(Qt.GlobalColor.transparent)
                painter = QPainter(surface)
                try:
                    with patch.object(window, 'tactical_map_rect', return_value=rect):
                        started = time.perf_counter_ns()
                        window.draw_tactical_map_hud(painter, 1920, 1080)
                        elapsed = (time.perf_counter_ns() - started) / 1e6
                finally:
                    painter.end()
                records.append({'paint_ms': elapsed, 'rounded': list(samples),
                                'pixels': pixels(surface),
                                'hotspots': [(h.action, repr(h.payload), h.rect.getRect())
                                             for h in window.hotspots]})
        cold, warm = records[:24], records[24:]
        equal = lambda a, b: a['pixels'] == b['pixels'] and a['hotspots'] == b['hotspots']
        return {
            'mode': mode, 'liquid': liquid,
            'asset_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'image_size': [image.width(), image.height()], 'decode_ms': decode_ms,
            # Only the first scene in this process is cold to shared Qt/font state.
            'first_cycle': summarize(cold), 'warm_cycle': summarize(warm),
            'cycle_pixels_hotspots_equal': all(equal(a, b) for a, b in zip(cold, warm)),
            'repeated_endpoints_equal': all(equal(cycle[a], cycle[b])
                for cycle in (cold, warm) for a, b in ((0, 1), (11, 12), (22, 23))),
        }


def main():
    TacticalMapContractTests.setUpClass()
    try:
        results = [measure(TacticalMapContractTests.window, mode, liquid)
                   for mode in ('RMUC7v7', 'RMUL3v3') for liquid in (False, True)]
    finally:
        TacticalMapContractTests.tearDownClass()
    report = {
        'source_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'renderer_sha256': hashlib.sha256((ROOT / 'rm_client/ui/polar/renderers/tactical_map.py').read_bytes()).hexdigest(),
        'platform': platform.platform(), 'python': platform.python_version(),
        'pyside6': QT_BINDING_VERSION, 'sequence': SEQUENCE, 'results': results,
        'scope': 'Instrumented CPU-raster elapsed time, not process CPU time; includes observer overhead. No native GPU/FPS qualification. HEAD and renderer/asset hashes are not a full clean dependency snapshot.',
    }
    print(json.dumps(report, indent=2))
    return 0 if all(r['cycle_pixels_hotspots_equal'] and r['repeated_endpoints_equal']
                    for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
