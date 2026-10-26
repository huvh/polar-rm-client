"""Owned Windows GL/settings input and lifetime probe; no device/game interaction."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]


def run(out,cycles):
    if sys.platform!='win32':raise RuntimeError('Real Windows desktop required')
    os.environ.update(QT_QPA_PLATFORM='windows',POLAR_AUTOSTART='0',CI='true',
        POLAR_DISABLE_LOCAL_CAPTURE='1',POLAR_DISABLE_MEDIA_PRELOAD='1')
    from PySide6.QtCore import QPoint, Qt, QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from rm_client.backend.mqtt_backend import RmMqttBackend
    from rm_client.backend.serial_backend import RmSerialBackend
    from rm_client.backend.video_backend import RmVideoBackend
    from rm_client.ui.polar_app import PolarRMWindow
    from rm_client.ui.cs2_settings_center import build_settings_center
    from rm_client.ui.endfield_settings_theme import EndfieldSettingRow, tinted_sprite, capture_settings_backdrop
    from rm_client.ui.window_shortcuts import set_fullscreen
    from window_lifecycle_helpers import close_window_safely,settle_window_lifecycle
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    out.mkdir(parents=True,exist_ok=False)
    report={'scope':'Owned Windows GL/Qt only; inert transports; not field qualification','cases':[]}
    def until(predicate,timeout=12):
        end=time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>end:raise TimeoutError('Endfield settings transition/build')
            app.processEvents();time.sleep(.003)
    with tempfile.TemporaryDirectory() as profile,patch.dict(os.environ,POLAR_USER_DATA_ROOT=profile), \
         patch.object(RmMqttBackend,'start'),patch.object(RmSerialBackend,'start'),patch.object(RmVideoBackend,'start'):
        window=PolarRMWindow();dialog=None
        try:
            window.resize(1280,720);window.show()
            assert QTest.qWaitForWindowExposed(window,5000)
            settle_window_lifecycle(window,app)
            until(lambda:window.gpu_compositor.available)
            report['gl_available']=True
            window.home_visible=False
            window.set_clickgui_visible(False,announce=False)
            window.set_escape_menu_visible(True)
            until(lambda:window.gpu_compositor._treated_blur_valid and
                window.gpu_compositor._backdrop_treatment.blur_kernel=='endfield_gaussian')
            # Same scene-boundary order as the real Esc settings action.
            capture_settings_backdrop(window)
            window.set_escape_menu_visible(False)
            dialog=build_settings_center(window)
            assert dialog._world_backdrop is not None, 'Source settings lost Esc Gaussian'
            dialog.show();until(lambda:not dialog.timeline.active())
            dialog.grab().save(str(out/'settings_world_backdrop.png'))
            report['esc_world_gaussian_reused']=True
            dialog.close_for_shutdown();dialog.deleteLater();dialog=None
            app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            for width,height in ((1280,720),(1600,900),(1920,1080),(2560,1440)):
                window.resize(width,height);app.processEvents()
                dialog=build_settings_center(window);window._settings_session=dialog
                dialog.show();until(lambda:not dialog.timeline.active())
                assert dialog._surface is None
                assert all(r.width()>720*dialog.theme_scale for r in dialog.tabs.widget(0).findChildren(EndfieldSettingRow))
                dialog.grab().save(str(out/f'settings_{width}x{height}.png'))
                audio=dialog.pages['音频'];bar=dialog.tabs.tabBar()
                QTest.mouseClick(bar,Qt.MouseButton.LeftButton,pos=bar.tabRect(1).center())
                until(lambda:audio.builder.ready or bool(audio.builder.error))
                assert not audio.builder.error
                combo=audio.audio_controls['device_id']
                QTest.mouseClick(combo,Qt.MouseButton.LeftButton,pos=QPoint(combo.width()-18,combo.height()//2))
                until(lambda:combo.view().isVisible())
                combo.hidePopup();QTest.qWait(240)
                dialog.grab().save(str(out/f'audio_{width}x{height}.png'))
                report['cases'].append({'size':[width,height],'dpr':window.devicePixelRatioF(),
                    'source_tabs_clickable':True,'dropdown_arrow_clickable':True})
                dialog.close_for_shutdown();window._settings_session=None;dialog.deleteLater();dialog=None
                app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            set_fullscreen(window,True);QTest.qWait(100)
            dialog=build_settings_center(window);window._settings_session=dialog
            dialog.show();until(lambda:not dialog.timeline.active())
            assert window.isFullScreen()
            with patch.object(window.backend,'trigger_estop',return_value=(True,'test-only')) as stop:
                QTest.keyClick(dialog,Qt.Key.Key_F12);assert stop.call_count==1
            audio=dialog.pages['音频'];dialog.tabs.setCurrentWidget(audio)
            until(lambda:audio.builder.ready)
            combo=audio.audio_controls['device_id'];combo.showPopup();until(lambda:combo.view().isVisible())
            combo.hidePopup();QTest.qWait(240)
            dialog.reject();until(lambda:not dialog.isVisible())
            assert window.isFullScreen()
            window._settings_session=None;dialog.deleteLater();dialog=None
            set_fullscreen(window,False);QTest.qWait(100)
            # Real source entrance/exit, not a toggle of fake visibility flags.
            baseline=None
            for i in range(cycles):
                dialog=build_settings_center(window);window._settings_session=dialog;dialog.show()
                until(lambda:not dialog.timeline.active())
                dialog.reject();until(lambda:not dialog.isVisible())
                window._settings_session=None;dialog.deleteLater();dialog=None
                app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
                if baseline is None:baseline=tinted_sprite.cache_info().currsize
            assert tinted_sprite.cache_info().currsize==baseline
            report.update(result='PASS',cycles=cycles,fullscreen_retained=True,fullscreen_dropdown=True,
                          f12_live=True,tint_cache_entries=baseline)
        except BaseException as error:
            report.update(result='FAIL',error=type(error).__name__+': '+str(error));raise
        finally:
            if dialog is not None:dialog.close_for_shutdown();dialog.deleteLater()
            window._settings_session=None
            close_window_safely(window,app);window.deleteLater();app.processEvents()
            (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print('Endfield settings Windows presentation/input PASS')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=10)
    args=parser.parse_args()
    if not 1<=args.cycles<=1000:parser.error('cycles must be 1..1000')
    run(args.out,args.cycles)
