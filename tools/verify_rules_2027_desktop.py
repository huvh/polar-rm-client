"""Owned Windows OpenGL rule-preview probe; no broker, serial or robot I/O."""
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


def run(out):
    if sys.platform!='win32':raise RuntimeError('Real Windows desktop required')
    os.environ.update(QT_QPA_PLATFORM='windows',POLAR_AUTOSTART='0',CI='true',
        POLAR_DISABLE_LOCAL_CAPTURE='1',POLAR_DISABLE_MEDIA_PRELOAD='1',
        QT_SCALE_FACTOR='1',QT_SCREEN_SCALE_FACTORS='1;1;1;1')
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from rm_client.backend.mqtt_backend import RmMqttBackend
    from rm_client.backend.serial_backend import RmSerialBackend
    from rm_client.backend.video_backend import RmVideoBackend
    from rm_client.ui.polar_app import PolarRMWindow
    from rm_client.ui.cs2_settings_center import build_settings_center
    from rm_client.ui.minecraft_hud import MinecraftCombatHudRenderer
    from window_lifecycle_helpers import close_window_safely,settle_window_lifecycle
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    out.mkdir(parents=True,exist_ok=False)
    report={'scope':'Windows owned GL preview at explicit Qt DPR=1; inert transports; NOT multi-DPI, wire or field validation','cases':[]}
    def until(predicate,timeout=12):
        deadline=time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError('Annual preview scene did not settle')
            app.processEvents();time.sleep(.005)
    with tempfile.TemporaryDirectory() as profile,patch.dict(os.environ,POLAR_USER_DATA_ROOT=profile), \
         patch.object(RmMqttBackend,'start'),patch.object(RmSerialBackend,'start'), \
         patch.object(RmVideoBackend,'start'):
        window=PolarRMWindow();dialog=None
        try:
            window.move(0,0);window.resize(1280,720);window.show()
            assert QTest.qWaitForWindowExposed(window,5000)
            settle_window_lifecycle(window,app)
            until(lambda:window.gpu_compositor.available)
            with patch.object(window,'auto_save_config'):
                season=window.registry.get('MatchMode').get_setting('Season')
                season.value='2027';window.after_setting_changed(season)
                assert window.state.rules_season==window.backend.rule_season==2027
                assert not window.backend.mqtt.official_rules_admission()[0]
                window.home_visible=True;window.startup_step='match'
                for width,height in ((1280,720),(1600,900),(1920,1080),(2560,1440)):
                    window.resize(width,height);app.processEvents()
                    window.hotspots=[]
                    window.build_gpu_startup_launcher(width,height,page='match')
                    modes=[hit for hit in window.hotspots if hit.action=='select_match_mode']
                    assert len(modes)==3,[h.payload for h in modes]
                    assert all(window.rect().contains(hit.rect.toAlignedRect()) for hit in modes)
                    backs=[hit for hit in window.hotspots if hit.action=='startup_back']
                    assert backs and all(not h.rect.intersects(backs[0].rect) for h in modes)
                    QTest.qWait(450)
                    native=window.grabFramebuffer()
                    assert (window.width(),window.height())==(width,height),'OS clamped requested viewport'
                    assert (native.width(),native.height())==(width,height),'Native framebuffer did not match target resolution'
                    native.save(str(out/f'startup_{width}x{height}.png'))
                    report['cases'].append({'size':[width,height],'dpr':window.devicePixelRatioF(),
                        'actual_widget_size':[window.width(),window.height()],
                        'actual_framebuffer_size':[native.width(),native.height()],
                        'three_modes_fit_without_back_overlap':True})
                for key in window.match_mode_manager.mode_keys:
                    window.apply_match_mode(key,close_home=False,announce=False)
                    window.home_visible=False;window.set_clickgui_visible(False,announce=False)
                    QTest.qWait(250)
                    assert window.state.current_stage=='NOT_STARTED'
                    assert not window.state.target_locked and window.state.target_id==0
                    assert all(not card.enabled and card.status_only for card in window.economy_offers())
                    assert window.state.match_duration_sec==({'RMUC7v7':420,'RMUL3v3':300,'RMUL1v1':120}[key])
                    assert not window.match_mode_manager.current.field.positions_calibrated
                    assert window.official_map_image(window.match_mode_manager.current) is not None
                    assert not hasattr(window, "open_hero_deploy_interface")
                    text=' '.join(line for line,_ in MinecraftCombatHudRenderer.scoreboard_lines(window.state))
                    if key.startswith('RMUL'):assert 'Base:' not in text and 'Shield:' not in text
                    if key=='RMUL3v3':
                        assert window.state.ally_victory_points==window.state.control_score_max==600
                    if key=='RMUC7v7':
                        assert len(window.state.control_zones)==4
                        assert window.state.control_score_max==0  # No invented winning ceiling.
                    window.grabFramebuffer().save(str(out/f'hud_{key}.png'))
                dialog=build_settings_center(window);window._settings_session=dialog;dialog.show()
                until(lambda:not dialog.timeline.active())
                dialog.grab().save(str(out/'settings_2027.png'))
                dialog.close_for_shutdown();window._settings_session=None;dialog.deleteLater();dialog=None
                app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
                season.value='2026';window.after_setting_changed(season)
                assert window.backend.rule_season==window.state.rules_season==2026
                assert window.match_mode_manager.mode_keys==('RMUC7v7','RMUL3v3')
                assert window.state.match_mode=='RMUL3v3'
                assert window.state.control_score_max==200
                assert not window.backend.mqtt.messages_sent
                report.update(result='PASS',back_to_2026_without_arm=True,
                    official_2027_wire_locked=True,old_hero_deploy_blocked=True,
                    uncalibrated_positions_not_projected=True,real_messages_sent=0)
        except BaseException as error:
            report.update(result='FAIL',error=type(error).__name__+': '+str(error));raise
        finally:
            if dialog is not None:dialog.close_for_shutdown();dialog.deleteLater()
            window._settings_session=None
            close_window_safely(window,app);window.deleteLater();app.processEvents()
            (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('Windows 2027 rule preview PASS; not field qualification')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
