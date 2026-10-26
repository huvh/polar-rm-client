"""真实 Windows Esc -> 公告 -> Esc 往返，记录菜单与网页呈现时序。"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def run(output: Path, *, fullscreen=False, rounds=6, cancel_loading=False):
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM", "windows") != "windows":
        raise RuntimeError("公告往返验收需要真实 Windows 呈现窗口")
    output.mkdir(parents=True, exist_ok=False)
    from PySide6.QtCore import QEvent, QEventLoop, QPoint, QTimer, Qt
    from PySide6.QtGui import QCursor, QImage, QSurfaceFormat
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    import test_window_economy_commands as fixtures
    from rm_client.ui.endfield.changelog.dialog import ChangelogDialog
    from tools.endfield.changelog.verify_desktop import javascript
    case = fixtures.WindowEconomyCommands()
    case.setUp()
    host = case.window
    menu = host._endfield_menu
    native_parents = []
    prepare = menu.prepare
    def record_prepare(parent, *args, **kwargs):
        native_parents.append(parent)
        return prepare(parent, *args, **kwargs)
    menu.prepare = record_prepare
    requests = Mock(wraps=menu.request)
    menu.request = requests
    host.economy_visible = False
    host.economy_island.progress = host.economy_island.target = 0.0
    host.resize(1600, 900)
    host.show()
    if fullscreen:
        from rm_client.ui.window_shortcuts import set_fullscreen
        set_fullscreen(host, True)
    host.raise_()
    host.activateWindow()
    QTest.qWaitForWindowExposed(host, 5000)
    original_cursor = QCursor.pos()
    host.set_escape_menu_visible(True)
    host.timer.start(8)
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(15)
    started = time.monotonic()
    state = {"stage": "open", "round": 0, "closed_at": 0.0, "busy": False}
    samples, errors, display_checks = [], [], []

    def capture_display(widget, name):
        # HWND 单独读取会漏掉 DirectComposition；读取最终屏幕上的窗口区域。
        point = widget.mapToGlobal(QPoint(0, 0))
        pixels = widget.screen().grabWindow(0, point.x(), point.y(), widget.width(), widget.height()).toImage()
        pixels.save(str(output / name))
        return pixels

    def menu_brightness(pixels):
        # 检查左侧真实按钮的明亮区域；纯背景或丢失的合成图层不能通过。
        width, height = pixels.width(), pixels.height()
        return sum(min(pixels.pixelColor(x, y).getRgb()[:3]) > 120
                   for x in range(round(width * .14), round(width * .29), 5)
                   for y in range(round(height * .22), round(height * .70), 5))

    def check():
        if state["busy"]:
            return
        state["busy"] = True
        try:
            now = time.monotonic()
            if now - started > 15 + rounds * 10:
                raise TimeoutError("公告往返状态超时：" + str(state))
            if menu.error:
                raise RuntimeError(menu.error)
            modal = app.activeModalWidget()
            is_log = isinstance(modal, ChangelogDialog)
            samples.append({"t": round(now - started, 3), "stage": state["stage"],
                            "escape": host.escape_menu_visible, "requested": menu.requested,
                            "native_phase": menu.phase,
                            "hwnd": int(host.winId()), "native_parents": list(native_parents),
                            "pending": bool(getattr(host, "_endfield_changelog_pending", False)),
                            "log": is_log, "ready": modal.content_ready if is_log else False,
                            "opacity": modal.windowOpacity() if is_log else None})
            assert menu.requested and host.escape_menu_visible, "Esc 在公告往返中被关闭"
            if native_parents:
                assert int(host.winId()) == native_parents[0], "公告创建过程替换了原生菜单绑定的主窗口句柄"
            if is_log:
                assert modal.windowOpacity() == 0.0 or modal.content_ready, "空页面提前显示"
            if state["stage"] == "open" and now - started > 1.5 and menu.ready and menu.phase == 1:
                host.raise_()
                host.activateWindow()
                pixels = capture_display(host, f"desktop_before_{state['round']}.png")
                state["baseline_brightness"] = menu_brightness(pixels)
                assert state["baseline_brightness"] > 200, "进入公告前屏幕上没有呈现完整菜单"
                rect = (ctypes.c_double * 4)()
                if menu.api.button(menu.handle, 7, rect):
                    dpr = host.devicePixelRatioF()
                    pos = QPoint(round((rect[0] + rect[2] / 2) / dpr),
                                 round((rect[1] + rect[3] / 2) / dpr))
                    QCursor.setPos(host.mapToGlobal(pos))
                    menu.pointer(1, rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
                    state.update(stage="hover", hover_at=now)
            elif state["stage"] == "hover" and now - state["hover_at"] > .7:
                rect = (ctypes.c_double * 4)()
                if menu.api.button(menu.handle, 7, rect):
                    dpr = host.devicePixelRatioF()
                    pos = QPoint(round((rect[0] + rect[2] / 2) / dpr),
                                 round((rect[1] + rect[3] / 2) / dpr))
                    QCursor.setPos(host.mapToGlobal(pos))
                    QTest.mouseClick(host, Qt.MouseButton.LeftButton, pos=pos)
                    state["stage"] = "log"
            elif state["stage"] == "log" and is_log and cancel_loading:
                assert not modal.content_ready, "加载取消用例未能覆盖未就绪页面"
                QTest.keyClick(modal.view.focusProxy() or modal, Qt.Key.Key_Escape)
                state.update(stage="return", closed_at=now)
            elif state["stage"] == "log" and is_log and modal.content_ready:
                if not state.get("ready_at"):
                    state["ready_at"] = now
                if now - state["ready_at"] < .4:
                    return
                modal.grab().save(str(output / f"log_{state['round']}.png"))
                capture_display(modal, f"desktop_log_{state['round']}.png")
                assert not modal.page.errors, modal.page.errors
                if state["round"] % 2 == 0:
                    QTest.keyClick(modal.view.focusProxy(), Qt.Key.Key_Escape)
                else:
                    javascript(modal.page, "document.querySelector('.jArhWq').click()")
                state.update(stage="return", closed_at=now)
            elif state["stage"] == "return" and not is_log and now - state["closed_at"] > .25:
                host.raise_()
                host.activateWindow()
                pixels = capture_display(host, f"desktop_return_{state['round']}.png")
                brightness = menu_brightness(pixels)
                display_checks.append({"round": state["round"], "before": state["baseline_brightness"],
                                       "after": brightness})
                assert brightness > state["baseline_brightness"] * .65, "关闭公告后实际屏幕上的 Esc 菜单图层丢失"
                assert not host._endfield_changelog_pending
                assert menu.phase == 1
                state["round"] += 1
                state.pop("ready_at", None)
                state["stage"] = "open" if state["round"] < rounds else "capture"
                if state["stage"] == "capture":
                    menu.api.capture(menu.handle, os.fsencode(output / "escape_return.bgra"))
            elif state["stage"] == "capture" and menu.api.captured(menu.handle):
                assert menu.api.captured(menu.handle) == 1
                width, height = menu._size
                data = (output / "escape_return.bgra").read_bytes()
                assert QImage(data, width, height, width * 4, QImage.Format.Format_ARGB32).save(
                    str(output / "escape_return.png"))
                assert all(call.args[0] for call in requests.call_args_list), "原生菜单收到关闭请求"
                (output / "report.json").write_text(json.dumps({"status": "PASS", "roundtrips": rounds,
                    "fullscreen": fullscreen, "cancel_loading": cancel_loading, "display_checks": display_checks,
                    "native_requests": [call.args[0] for call in requests.call_args_list],
                    "samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
                loop.quit()
        except BaseException as error:
            errors.append(error)
            if isinstance(app.activeModalWidget(), ChangelogDialog):
                app.activeModalWidget().reject()
            loop.quit()
        finally:
            state["busy"] = False

    timer.timeout.connect(check)
    timer.start()
    try:
        loop.exec()
        if errors:
            (output / "failed-samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
            raise errors[0]
    finally:
        timer.stop()
        host.timer.stop()
        QCursor.setPos(original_cursor)
        if isinstance(app.activeModalWidget(), ChangelogDialog):
            app.activeModalWidget().reject()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        case.doCleanups()
    print("Windows Esc/changelog roundtrips PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--rounds", type=int, default=6, choices=range(1, 21))
    parser.add_argument("--cancel-loading", action="store_true")
    args = parser.parse_args()
    run(args.out.resolve(), fullscreen=args.fullscreen, rounds=args.rounds, cancel_loading=args.cancel_loading)
