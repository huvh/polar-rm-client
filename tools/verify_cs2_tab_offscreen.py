"""Background raster preview of the production combined Tab path, never a game.

Does not show/activate windows. All final transports/audio are inert and user
data is temporary. Preview data is explicitly synthetic, not match evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ.update(QT_QPA_PLATFORM='offscreen', CI='true', POLAR_DISABLE_LOCAL_CAPTURE='1',
                  POLAR_DISABLE_MEDIA_PRELOAD='1', POLAR_AUTOSTART='0')


def run(out):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
    from test_modal_input_epoch import window_fixture
    from test_cs2_tab_scoreboard import frame
    from rm_client.ui.cs2_scoreboard import prepare_tab_layout
    from rm_client.ui.jello_locale import LANGUAGE_CHINESE

    # The offscreen QPA does not enumerate Windows' installed font database.
    # Load a READ-ONLY system font for the preview only (never redistribute it).
    system_cjk = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if system_cjk.is_file():
        assert QFontDatabase.addApplicationFont(str(system_cjk)) >= 0

    out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'OFFSCREEN RASTER ONLY; synthetic UI preview, NOT GPU FPS/field evidence', 'cases': []}
    with window_fixture() as (_, w, _):
        w.economy_island.progress = 0
        w.registry.get('TacticalMap').enabled = True
        w.registry.get('ClickGui').get_setting('Language').value = LANGUAGE_CHINESE
        w.state.rules_season = 2026
        w.apply_match_mode('RMUC7v7', close_home=False, announce=False)
        w.home_visible = False
        w.tactical_map_hold = True
        w.tactical_map_state.container.content.progress = 1
        for width, height in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440)):
            w.resize(width, height)
            for dpr in (1., 1.25, 1.5, 2.):
                image = QImage(round(width*dpr), round(height*dpr), QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.fill(QColor('#474d4e'))
                p = QPainter(image)
                try:
                    with patch.object(w.top_match_bar, 'scoreboard_snapshot', return_value=frame()):
                        prepare_tab_layout(w, width, height, 10)
                        scale = w.get_hud_scale(width, height)
                        w.tactical_map_rect(int(width/scale), int(height/scale))
                        for _ in range(240):
                            w.tactical_map_state.update(1/120)
                        w.paint_hud_motion_overlay(p, width, height)
                    p.setPen(Qt.white)
                    p.drawText(20, height-24, 'UI DEMO / SYNTHETIC VALUES / OFFSCREEN ONLY')
                finally:
                    p.end()
                bounds = w._tab_scoreboard_bounds
                assert bounds is not None and QRectF(0, 0, width, height).contains(bounds)
                rect = w.tactical_map_rect(int(width/scale), int(height/scale))
                physical = QRectF(rect.x()*scale, rect.y()*scale, rect.width()*scale, rect.height()*scale)
                assert not bounds.intersects(physical)
                # DPR is raster-only. Hit geometry continues to use Qt logical coordinates.
                hit = w._tactical_map_hit_geometry
                centre = w.tactical_map_field_rect.center() * scale
                assert hit.normalized_point(centre) is not None, (width, height, dpr, centre, hit)
                assert hit.normalized_point(bounds.center()) is None
                if dpr in (1., 2.):
                    image.save(str(out / f'tab_{width}x{height}_dpr{dpr:g}.png'))
                report['cases'].append({'size': [width, height], 'dpr': dpr,
                                        'board': list(bounds.getRect()), 'map': list(physical.getRect())})
        renderer = w._tab_scoreboard_renderer
        report['bounded_caches'] = {'panels': len(renderer._layers), 'rows': len(renderer._row_images)}
        assert len(renderer._layers) <= 6 and len(renderer._row_images) <= 64
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'PASS: {len(report["cases"])} combined raster/DPR/hit cases; no native window or match claims')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
