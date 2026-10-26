"""真实 Windows 窗口中核对公告页；使用无设备输出的主窗口测试夹具。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/endfield")]


def javascript(page, source):
    from PySide6.QtCore import QEventLoop, QTimer
    loop, result = QEventLoop(), []
    page.runJavaScript(source, lambda value: (result.append(value), loop.quit()))
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    if not result:
        raise RuntimeError("公告页脚本超时")
    return result[0]


def run(output: Path):
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM", "windows") != "windows":
        raise RuntimeError("此验收必须使用真实 Windows 平台，不能用 offscreen 代替")
    output.mkdir(parents=True, exist_ok=False)
    from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
    from PySide6.QtGui import QSurfaceFormat
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
    from tools.endfield.changelog.check_assets import validate
    case = fixtures.WindowEconomyCommands()
    case.setUp()
    dialog = None
    try:
        host = case.window
        host.resize(1920, 1080)
        host.show()
        host.registry.get("ClickGui").get_setting("Language").value = "简体中文"
        dialog = ChangelogDialog(host)
        dialog.show()
        failures = []
        loop = QEventLoop()

        def capture():
            try:
                state = json.loads(javascript(dialog.page, "JSON.stringify({"
                    "title:document.title,language:document.documentElement.lang,"
                    "text:document.querySelector('.ej1XT0').innerText,"
                    "font:getComputedStyle(document.documentElement).fontFamily,"
                    "faces:Array.from(document.fonts).filter(f=>f.status==='loaded').map(f=>f.family),"
                    "motion:getComputedStyle(document.querySelector('.ziE87l')).transitionDuration})"))
                assert "HarmonyOS_Sans_SC" in state["faces"]
                assert "菜单精简" in state["text"]
                assert state["motion"] == "0.3s"
                assert not dialog.page.errors, dialog.page.errors
                assert not dialog.page.profile().resources.blocked
                assert dialog.grab().save(str(output / "changelog_zh.png"))
                state.update(status="PASS", platform=QApplication.platformName(),
                             assets=validate(host.paths.endfield_changelog_pack),
                             errors=dialog.page.errors,
                             network_requests=dialog.page.profile().resources.blocked)
                (output / "report.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            except BaseException as error:
                failures.append(error)
            finally:
                dialog.reject()
                loop.quit()

        QTimer.singleShot(2500, capture)
        loop.exec()
        if failures:
            raise failures[0]
    finally:
        if dialog is not None:
            dialog.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        case.doCleanups()
    print("Windows original changelog PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.out.resolve())
