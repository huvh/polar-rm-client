"""在真实客户端主循环中调用生产设置入口，检查首次快照、模态布局和导航。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT),str(ROOT/"tests")]


def run(out, sizes, *, scroll_probe=False, record=False, geometry_probe=False, warm_all=False):
    os.environ.update(QT_QPA_PLATFORM="windows",POLAR_AUTOSTART="0",CI="true",
                      POLAR_DISABLE_LOCAL_CAPTURE="1",POLAR_DISABLE_MEDIA_PRELOAD="1")
    from PySide6.QtCore import Qt, QTimer, QPoint, QRect
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from rm_client.backend.mqtt_backend import RmMqttBackend
    from rm_client.backend.serial_backend import RmSerialBackend
    from rm_client.backend.video_backend import RmVideoBackend
    from rm_client.ui.polar_app import PolarRMWindow
    from rm_client.ui import cs2_settings_center as settings
    from rm_client.ui.cs2_video_settings import configure_surface
    from rm_client.ui.endfield.settings.widgets import SettingsRow
    from rm_client.ui.window_shortcuts import set_fullscreen
    from window_lifecycle_helpers import close_window_safely,settle_window_lifecycle

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    surface = QSurfaceFormat()
    surface.setVersion(3,3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setDepthBufferSize(0)
    surface.setStencilBufferSize(0)
    configure_surface(surface)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication([])
    out.mkdir(parents=True,exist_ok=True)
    report = {"scope":"actual PolarRMWindow, shared GL contexts, active QApplication.exec and production open_settings_center; inert transports",
              "cases":[],"modal_loop_level":None}
    failures = []
    original = settings.build_settings_center

    def check_geometry(dialog,phase):
        video = dialog.tabs.widget(0)
        rows = video.findChildren(SettingsRow)
        for row in rows:
            assert row.width()>video.width()*.9, (phase,row.label.text(),row.width(),video.width())
            assert row.rect().contains(row.control.geometry()), (phase,row.label.text(),"field clipped")
            assert row.label.width()>100, (phase,row.label.text(),"vertical label")
        close = QRect(dialog.close_button.mapTo(dialog,QPoint()),dialog.close_button.size())
        assert dialog.rect().contains(close), "Close button escaped dialog"
        return {"phase":phase,"dialog":list(dialog.size().toTuple()),"minimum_row_width":min(row.width() for row in rows),
                "controls":len(rows),"snapshot":dialog._surface is not None,"close":list(close.getRect())}

    with tempfile.TemporaryDirectory() as profile, patch.dict(os.environ,POLAR_USER_DATA_ROOT=profile), \
         patch.object(RmMqttBackend,"start"),patch.object(RmSerialBackend,"start"),patch.object(RmVideoBackend,"start"):
        window = PolarRMWindow()
        report["dpr"] = window.devicePixelRatioF()
        window.resize(*sizes[0])
        window.show()
        QTest.qWait(600)
        settle_window_lifecycle(window,app)
        window.home_visible = False
        window.ui_audio_enabled = False
        iterator = iter(sizes)

        def next_case():
            try:
                width,height = next(iterator)
            except StopIteration:
                app.quit()
                return
            window.resize(width,height)
            case = {"size":[width,height],"samples":[],"pages":[]}
            if geometry_probe and report["cases"]:
                set_fullscreen(window,True)
                QTest.qWait(300)
            case["opened_fullscreen"] = window.isFullScreen()

            def build(host):
                dialog = original(host)
                capture = dialog._capture

                def snapshot():
                    capture()
                    try:
                        case["samples"].append(check_geometry(dialog,"snapshot"))
                    except BaseException as error:
                        failures.append(str(error))
                dialog._capture = snapshot

                def inspect_pages():
                    try:
                        report["modal_loop_level"] = app.thread().loopLevel()
                        case["samples"].append(check_geometry(dialog,"settled"))
                        assert dialog.size() == window.size()
                        for index in range(1 if geometry_probe and not warm_all else dialog.tabs.count()):
                            QTest.mouseClick(dialog.navigation,Qt.MouseButton.LeftButton,
                                             pos=dialog.navigation.tabRect(index).center())
                            page = dialog.tabs.currentWidget()
                            builder = getattr(page,"builder",None)
                            elapsed = 0
                            while builder is not None and not builder.ready and not builder.error and elapsed<8000:
                                QTest.qWait(10)
                                elapsed += 10
                            if builder is not None:
                                assert builder.ready,builder.error
                            QTest.qWait(380)
                            rows = page.findChildren(SettingsRow)
                            assert rows
                            for row in rows:
                                assert row.rect().contains(row.control.geometry()),row.label.text()
                            name = f"{width}x{height}_page_{index}.png"
                            assert dialog.grab().save(str(out/name))
                            case["pages"].append({"page":dialog.tabs.tabText(index),"capture":name,"rows":len(rows)})
                        if scroll_probe:
                            from tools.endfield.settings.scroll_probe import exercise_scroll
                            case["scroll"] = exercise_scroll(dialog,out,record=record)
                        if geometry_probe:
                            from tools.endfield.settings.geometry_probe import exercise_geometry
                            case["geometry"] = exercise_geometry(dialog,window,out,f"case_{len(report['cases'])}")
                        with patch.object(window.backend,"trigger_estop",return_value=(True,"verification")) as stop:
                            QTest.keyClick(dialog.search,Qt.Key.Key_F12)
                            stop.assert_called_once()
                    except BaseException as error:
                        failures.append(str(error))
                    finally:
                        dialog.reject()
                QTimer.singleShot(600,dialog,inspect_pages)
                return dialog

            with patch.object(settings,"build_settings_center",side_effect=build):
                settings.open_settings_center(window)
            report["cases"].append(case)
            if failures:
                app.quit()
            else:
                QTimer.singleShot(0,next_case)
        try:
            QTimer.singleShot(0,next_case)
            app.exec()
            assert not failures,failures
            assert report["modal_loop_level"] == 2
            report["status"] = "PASS"
        finally:
            close_window_safely(window,app)
            (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--compact",action="store_true")
    parser.add_argument("--scroll",action="store_true")
    parser.add_argument("--record",action="store_true")
    parser.add_argument("--geometry",action="store_true")
    parser.add_argument("--warm-all",action="store_true")
    args = parser.parse_args()
    sizes = ((1225,704),) if args.compact else ((1225,704),(1000,620),(1920,1080))
    if args.geometry:
        sizes = ((1225,704),(1225,704))
    print(json.dumps(run(args.out,sizes,scroll_probe=args.scroll,record=args.record,geometry_probe=args.geometry,warm_all=args.warm_all),ensure_ascii=True))
