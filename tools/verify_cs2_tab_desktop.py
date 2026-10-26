"""Owned Windows OpenGL Tab/map probe; all transport acquisition is inert."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]


def run(out):
    if sys.platform != 'win32':
        raise RuntimeError('Native Windows is required')
    os.environ.update(QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1',
                      QT_SCREEN_SCALE_FACTORS='1;1;1;1', POLAR_AUTOSTART='0',
                      CI='true', POLAR_DISABLE_LOCAL_CAPTURE='1', POLAR_DISABLE_MEDIA_PRELOAD='1')
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from rm_client.backend.mqtt_backend import RmMqttBackend
    from rm_client.backend.serial_backend import RmSerialBackend
    from rm_client.backend.video_backend import RmVideoBackend
    from rm_client.ui.jello_locale import LANGUAGE_CHINESE
    from rm_client.ui.polar_app import PolarRMWindow
    from window_lifecycle_helpers import close_window_safely, settle_window_lifecycle

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'Windows native GL, Qt DPR=1, no devices/broker; NOT field or FPS certification', 'cases': []}

    def until(predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError('Native Tab presentation did not settle')
            app.processEvents()
            time.sleep(.005)

    with tempfile.TemporaryDirectory() as profile, patch.dict(os.environ, POLAR_USER_DATA_ROOT=profile), \
            patch.object(RmMqttBackend, 'start'), patch.object(RmSerialBackend, 'start'), \
            patch.object(RmVideoBackend, 'start'):
        window = PolarRMWindow()
        try:
            window.move(0, 0)
            window.resize(1280, 720)
            window.show()
            assert QTest.qWaitForWindowExposed(window, 5000)
            settle_window_lifecycle(window, app)
            until(lambda: window.gpu_compositor.available)
            with patch.object(window, 'auto_save_config'):
                window.registry.get('ClickGui').get_setting('Language').value = LANGUAGE_CHINESE
                season = window.registry.get('MatchMode').get_setting('Season')
                for year in (2026, 2027):
                    season.value = str(year)
                    window.after_setting_changed(season)
                    window.apply_match_mode('RMUC7v7', close_home=False, announce=False)
                    window.home_visible = False
                    window.set_clickgui_visible(False, announce=False)
                    window.registry.get('TacticalMap').enabled = True
                    until(lambda: not window.menu_overlay_active())
                    for width, height in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440)):
                        window.resize(width, height)
                        app.processEvents()
                        QTest.qWait(150)  # Complete the native resize/focus epoch before input.
                        window.setFocus(Qt.FocusReason.OtherFocusReason)
                        before = {m.name: m.enabled for m in window.registry.modules}
                        QTest.keyPress(window, Qt.Key.Key_Tab)
                        until(lambda: window.tactical_map_hold_amount() >= .999)
                        QTest.qWait(80)
                        image = window.grabFramebuffer()
                        assert (image.width(), image.height()) == (width, height)
                        bounds = window._tab_scoreboard_bounds
                        assert bounds is not None
                        assert QRectF(0, 0, width, height).contains(bounds)
                        assert window.top_match_bar.last_layout is None
                        image.save(str(out / f'tab_{year}_{width}x{height}.png'))
                        report['cases'].append({'year': year, 'requested': [width, height],
                                                'framebuffer': [image.width(), image.height()],
                                                'dpr': window.devicePixelRatioF(), 'board': list(bounds.getRect())})
                        QTest.keyRelease(window, Qt.Key.Key_Tab)
                        until(lambda: window.tactical_map_hold_amount() == 0)
                        window.grabFramebuffer()
                        assert window._tab_scoreboard_bounds is None
                        assert before == {m.name: m.enabled for m in window.registry.modules}
                renderer = window._tab_scoreboard_renderer
                for _ in range(100):
                    QTest.keyPress(window, Qt.Key.Key_Tab)
                    QTest.qWait(12)
                    QTest.keyRelease(window, Qt.Key.Key_Tab)
                    QTest.qWait(12)
                until(lambda: window.tactical_map_hold_amount() == 0)
                assert len(renderer._layers) <= 6
                assert not window.backend.mqtt.messages_sent
                report.update(result='PASS', rapid_reversals=100, cached_layers=len(renderer._layers),
                              real_messages_sent=0, module_settings_restored=True)
        except BaseException as exc:
            report.update(result='FAIL', error=f'{type(exc).__name__}: {exc}')
            report['input_at_failure'] = {
                'held': window.tactical_map_hold, 'progress': window.tactical_map_hold_amount(),
                'target': window.tactical_map_state.container.content.target,
                'menu': window.menu_overlay_active(), 'focus': window.hasFocus(),
                'active': window.isActiveWindow(), 'home': window.home_visible,
            }
            raise
        finally:
            close_window_safely(window, app)
            window.deleteLater()
            app.processEvents()
            (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Windows CS2 Tab/map native GL PASS; no field/FPS qualification')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
