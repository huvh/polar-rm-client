"""Frozen draw-command/interaction traces for category-list reuse, no GPU calls."""
from dataclasses import fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_cs2_buy_matrix import Host
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from rm_client.ui import cs2_buy_menu as menu
from rm_client.ui import fonts

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / 'fixtures/buy_grid_category_baseline.json'
CASES = ('uneven', 'empty', 'unknown', 'supplier', 'interleaved', 'scrolled')


def normalize(value):
    if isinstance(value, QRectF): return [value.x(), value.y(), value.width(), value.height()]
    if isinstance(value, QPointF): return [value.x(), value.y()]
    if isinstance(value, QColor): return list(value.getRgb())
    if isinstance(value, QFont): return value.toString()
    if isinstance(value, Enum): return value.value
    if is_dataclass(value): return {f.name: normalize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict): return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [normalize(v) for v in value]
    if isinstance(value, str): return value.replace(str(ROOT), '<ROOT>')
    if value is None or isinstance(value, (int, float, bool)): return value
    raise TypeError(type(value))


def trace(case, width, height, progress):
    host = Host()
    original = host.offers
    if case == 'empty': host.offers = []
    elif case == 'unknown':
        host.offers = [replace(original[0], key=f'unknown{i}', category='unknown') for i in range(11)] + original
    elif case == 'supplier':
        host.offers = [replace(original[0], key=f'supplier{i}', category='supplier') for i in range(10)]
    elif case == 'interleaved': host.offers = original[::2] + original[1::2]
    elif case == 'scrolled':
        host.economy_offers_scroll.position = host.economy_offers_scroll.target = 125.
        host.economy_detail_scroll.position = host.economy_detail_scroll.target = 33.
    host.reconcile_economy_selection = lambda: next((o for o in host.offers if o.key == 'ammo0'), None)
    host.economy_island.progress = progress
    hotspots = []
    host.add_hotspot = lambda rect, action, payload=None, tooltip='': hotspots.append((QRectF(rect), action, payload, tooltip))
    # Keep requested font metadata stable across machines; no font rasterization.
    with patch.object(menu.time, 'perf_counter', return_value=100.), \
         patch.object(fonts._ui_fonts, '_cjk_families', return_value=('Sans Serif',)):
        commands = menu.build_grid(host, width, height)
    content = normalize({'commands': commands, 'glass': host.glass, 'hotspots': hotspots,
                         'offers_scroll': vars(host.economy_offers_scroll),
                         'detail_scroll': vars(host.economy_detail_scroll)})
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    return {'sha256': hashlib.sha256(encoded).hexdigest(),
            'command_count': len(commands.commands),
            'hotspot_actions_payloads': [[h[1], h[2]] for h in hotspots],
            'offers_scroll': content['offers_scroll'], 'detail_scroll': content['detail_scroll']}


class BuyGridCategoryCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_complete_baseline_draw_and_interaction_traces(self):
        expected = json.loads(FIXTURE.read_text())
        for case in CASES:
            for width, height, progress in ((1280, 720, 1.), (1920, 1080, 1.), (1280, 720, .35)):
                key = f'{case}:{width}:{height}:{progress}'
                with self.subTest(key=key):
                    self.assertEqual(trace(case, width, height, progress), expected['cases'][key])


if __name__ == '__main__': unittest.main()
