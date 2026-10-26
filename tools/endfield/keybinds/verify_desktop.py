"""真实Windows原生Esc菜单与独立快捷键/设置往返；只捕获客户端自有画面。"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT),str(ROOT/"tests")]


def run(output, fullscreen=False):
    os.environ.update(QT_QPA_PLATFORM="windows",CI="true",POLAR_DISABLE_LOCAL_CAPTURE="1",POLAR_DISABLE_MEDIA_PRELOAD="1")
    from PySide6.QtCore import Qt, QTimer, QPoint, QEvent, QEventLoop
    from PySide6.QtGui import QSurfaceFormat, QImage, QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    surface = QSurfaceFormat()
    surface.setVersion(3,3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from test_window_economy_commands import WindowEconomyCommands
    from rm_client.ui.endfield.keybinds.capture import KeyCapturePopup
    from rm_client.ui.window_shortcuts import set_fullscreen
    case = WindowEconomyCommands()
    case.setUp()
    host = case.window
    host.economy_visible = False
    host.economy_island.progress = host.economy_island.target = 0
    host.resize(1225,704)
    host.show()
    if fullscreen:
        set_fullscreen(host,True)
    host.ui_audio_enabled = False
    host.set_escape_menu_visible(True)
    host.timer.start(8)
    menu = host._endfield_menu
    menu.request = Mock(wraps=menu.request)
    output.mkdir(parents=True,exist_ok=True)
    cases = [(code,close) for code in (2,5) for close in ("back","close","escape")]
    state = {"stage":"open","index":0,"busy":False,"changed":time.perf_counter()}
    started = time.perf_counter()
    cursor = QCursor.pos()
    errors, samples = [], []
    timer = QTimer()
    loop = QEventLoop()
    timer.setInterval(20)

    def probe():
        if state["busy"]:
            return
        state["busy"] = True
        try:
            now = time.perf_counter()
            if now-started > 75:
                raise TimeoutError(str(state))
            assert not menu.error,menu.error
            assert host.escape_menu_visible and menu.requested,"Esc disappeared during child dialog"
            code,close = cases[state["index"]]
            modal = app.activeModalWidget() or getattr(host, "_settings_session", None)
            if state["stage"] == "open" and menu.ready and menu.phase == 1 and now-state["changed"] > 1:
                state.update(stage="modal",changed=now)
                # 注入原生动作队列返回值，随后完整走advance与生产模态；D3D仍实际呈现。
                with patch.object(menu.api,"action",return_value=code):
                    host.advance_endfield_menu()
            elif state["stage"] == "modal" and modal is not None and now-state["changed"] > .8:
                expected = "EndfieldKeybindManager" if code == 5 else "JelloSettingsCenter"
                assert modal.objectName() == expected,modal.objectName()
                print("Modal",state["index"],expected,close,flush=True)
                assert menu.phase == 1
                assert modal.grab().save(str(output/f"{state['index']}_{expected}.png"))
                if code == 5 and close == "back":
                    for key in modal.keyboard.keys:
                        rect = modal.keyboard.key_rect(key)
                        assert modal.keyboard.rect().contains(rect.toAlignedRect()),key
                        assert modal.keyboard.key_at(rect.center()) == key
                    entry = next(entry for entry in modal.session.entries if entry.identity == ("module","TacticalMap"))
                    failures = []
                    def capture_key():
                        popup = app.activeModalWidget()
                        try:
                            assert isinstance(popup,KeyCapturePopup)
                            assert popup.grab().save(str(output/"key_capture.png"))
                            with patch.object(host.backend,"trigger_estop",return_value=(True,"verification")) as stop:
                                QTest.keyClick(popup,Qt.Key.Key_F12)
                                stop.assert_called_once()
                            QTest.keyClick(popup,Qt.Key.Key_F10)
                        except BaseException as error:
                            failures.append(error)
                            popup.reject()
                    QTimer.singleShot(450,capture_key)
                    modal.select_entry(entry)
                    QTest.qWait(60)
                    QTest.mouseClick(modal.change_button,Qt.MouseButton.LeftButton)
                    assert not failures,failures
                    assert modal.session.values[entry.identity] == "F10"
                    assert host.registry.get("TacticalMap").keybind == "Tab"
                    QTest.mouseClick(modal.bound_buttons[entry.identity],Qt.MouseButton.LeftButton)
                    assert modal.session.values[entry.identity] == "None"
                    QTest.mouseClick(modal.keyboard,Qt.MouseButton.LeftButton,
                                     pos=modal.keyboard.key_rect("F10").center().toPoint())
                    QTest.mouseClick(modal.bind_button,Qt.MouseButton.LeftButton)
                    assert modal.session.values[entry.identity] == "F10"
                    modal.search.setText("战术地图")
                    assert "F10" in modal.keyboard.matches
                    assert modal.grab().save(str(output/"keyboard_search.png"))
                    modal.search.clear()
                    initial_fullscreen = host.isFullScreen()
                    for _ in range(2):
                        QTest.keyClick(modal.keyboard,Qt.Key.Key_F11)
                        QTest.qWait(250)
                        assert modal.size() == host.size()
                    assert host.isFullScreen() == initial_fullscreen
                state.update(stage="return",changed=time.perf_counter())
                if close == "escape":
                    QTest.keyClick(modal,Qt.Key.Key_Escape)
                else:
                    button = modal.close_button if close == "close" else next(
                        button for button in modal.panel.findChildren(QPushButton,options=Qt.FindChildOption.FindDirectChildrenOnly)
                        if button.text() == "返回")
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            elif state["stage"] == "return" and modal is None and now-state["changed"] > .3:
                assert menu.phase == 1
                assert not host._endfield_settings_pending
                raw = output/f"return_{state['index']}.bgra"
                menu.api.capture(menu.handle,os.fsencode(raw))
                state.update(stage="capture",raw=raw)
            elif state["stage"] == "capture" and menu.api.captured(menu.handle):
                assert menu.api.captured(menu.handle) == 1
                width,height = menu._size
                raw = state["raw"]
                pixels = QImage(raw.read_bytes(),width,height,width*4,QImage.Format.Format_ARGB32)
                assert pixels.save(str(raw.with_suffix(".png")))
                raw.unlink()
                samples.append({"action":code,"close":close,"escape":host.escape_menu_visible,
                                "requested":menu.requested,"phase":menu.phase})
                print("Returned",state["index"],flush=True)
                state["index"] += 1
                if state["index"] == len(cases):
                    assert all(call.args[0] for call in menu.request.call_args_list),"Esc received close request"
                    timer.stop()
                    loop.quit()
                else:
                    state.update(stage="open",changed=now)
        except BaseException as error:
            errors.append(str(error))
            timer.stop()
            if app.activeModalWidget() is not None:
                app.activeModalWidget().reject()
            QTimer.singleShot(300,loop.quit)
        finally:
            state["busy"] = False

    timer.timeout.connect(probe)
    timer.start()
    try:
        loop.exec()
        assert not errors,errors
        assert len(samples) == len(cases),samples
        report = {"status":"PASS","fullscreen":fullscreen,"dpr":host.devicePixelRatioF(),"cases":samples,
                  "scope":"real D3D menu and production modals; source semantic actions injected; Qt control clicks; inert transports; owned renderer capture"}
        (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print("PASS settings/keybinds return to native Esc:",len(samples))
    finally:
        timer.stop()
        host.timer.stop()
        QCursor.setPos(cursor)
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        case.doCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--fullscreen",action="store_true")
    args = parser.parse_args()
    run(args.out.resolve(),args.fullscreen)
