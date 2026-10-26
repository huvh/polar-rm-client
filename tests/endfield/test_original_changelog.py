"""实际运行原公告组件，核对字体、动效、分页、模态输入及离线资源。"""
from pathlib import Path
import json
import os
import sys
import time
from types import SimpleNamespace as NS
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from PySide6.QtCore import QEvent, QEventLoop, QTimer, QUrl, Qt
from PySide6.QtTest import QTest
from test_escape_menu import APP, Host
from rm_client.ui.endfield.changelog.dialog import ChangelogDialog, LocalResourcesOnly
from tools.endfield.changelog.check_assets import validate


def javascript(page, code):
    result = []
    loop = QEventLoop()
    page.runJavaScript(code, lambda value: (result.append(value), loop.quit()))
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    if not result:
        raise AssertionError("公告页面脚本未返回")
    return result[0]


class OriginalChangelogTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.resize(1920, 1080)
        self.host.registry = NS(get=lambda name: NS(
            enabled=False, get_setting=lambda _: NS(value="简体中文")))
        self.dialog = ChangelogDialog(self.host)
        self.dialog.show()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            APP.processEvents()
            if javascript(self.dialog.page, "!!document.querySelector('.ej1XT0 p')"):
                break
            QTest.qWait(30)
        else:
            self.fail("原版页面没有显示日志：" + str(self.dialog.page.errors))
        QTest.qWait(350)

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        self.host.hide()
        self.host.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def click_text(self, text):
        javascript(self.dialog.page, "Array.from(document.querySelectorAll('*')).find("
                   "e=>e.children.length===0&&e.textContent===" + json.dumps(text) + ").click()")
        QTest.qWait(420)

    def test_original_geometry_fonts_and_css_motion(self):
        actual = json.loads(javascript(self.dialog.page, "JSON.stringify((()=>{"
            "const e=document.querySelector('.HW7qtE'),r=e.getBoundingClientRect();"
            "return {rect:[r.x,r.y,r.width,r.height],font:getComputedStyle(document.documentElement).fontFamily,"
            "motion:getComputedStyle(document.querySelector('.ziE87l')).transitionDuration,"
            "faces:Array.from(document.fonts).filter(f=>f.status==='loaded').map(f=>f.family)}})())"))
        self.assertEqual(actual["rect"], [92, 68, 1736, 900])
        self.assertIn("HarmonyOS_Sans_SC", actual["font"])
        self.assertIn("HarmonyOS_Sans_SC", actual["faces"])
        self.assertEqual(actual["motion"], "0.3s")
        self.assertEqual(self.dialog.page.errors, [])
        self.assertEqual(self.dialog.page.profile().resources.blocked, [])

    def test_cold_page_stays_transparent_until_content_is_presentable(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.dialog = ChangelogDialog(self.host)
        self.assertFalse(self.dialog.content_ready)
        self.assertEqual(self.dialog.windowOpacity(), 0.0)
        self.dialog.show()
        for _ in range(160):
            if self.dialog.content_ready:
                break
            QTest.qWait(30)
        self.assertTrue(self.dialog.content_ready, self.dialog.page.errors)
        self.assertEqual(self.dialog.windowOpacity(), 1.0)
        self.assertFalse(self.dialog._load_deadline.isActive())

    def test_closed_loading_page_cannot_reveal_or_report_a_late_failure(self):
        self.dialog.reject()
        self.dialog._reveal_content()
        self.dialog._load_failed(self.host)
        self.assertFalse(self.dialog.isVisible())
        self.host.toast.assert_not_called()

    def test_escape_can_close_the_web_view_before_page_scripts_are_ready(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.dialog = ChangelogDialog(self.host)
        self.dialog.show()
        self.assertFalse(self.dialog.content_ready)
        QTest.keyClick(self.dialog.view.focusProxy() or self.dialog, Qt.Key.Key_Escape)
        self.assertFalse(self.dialog.isVisible())
        self.assertTrue(self.dialog._dismissed)

    def test_tabs_date_selection_and_independent_content_scroll(self):
        self.click_text("场地预览")
        text = javascript(self.dialog.page, "document.querySelector('.ej1XT0').innerText")
        self.assertIn("2026.10.21", text)
        self.assertIn("7v7", text)
        self.click_text("功能变更")
        text = javascript(self.dialog.page, "document.querySelector('.ej1XT0').innerText")
        self.assertIn("原版公告界面", text)
        self.click_text("使用说明")
        text = javascript(self.dialog.page, "document.querySelector('.ej1XT0').innerText")
        self.assertIn("F12", text)
        self.dialog.resize(640, 360)
        QTest.qWait(400)
        javascript(self.dialog.page, "document.querySelector('.ltibWR').innerHTML += '<p>Long content</p>'.repeat(50)")
        QTest.qWait(200)
        overflow = javascript(self.dialog.page, "Array.from(document.querySelectorAll('.ej1XT0 *')).some("
                              "e=>e.scrollHeight>e.clientHeight&&getComputedStyle(e).overflowY==='auto')")
        self.assertLessEqual(self.dialog.width(), 640)
        self.assertTrue(overflow)

    def test_close_button_and_f12_keep_host_ownership(self):
        QTest.keyClick(self.dialog.view.focusProxy(), Qt.Key.Key_F12)
        self.host.backend.trigger_estop.assert_called_once_with()
        self.host.control.reset_inputs.assert_called_once_with()
        self.host.backend.arm_match_control.assert_not_called()
        javascript(self.dialog.page, "document.querySelector('.jArhWq').click()")
        QTest.qWait(100)
        self.assertFalse(self.dialog.isVisible())

    def test_pack_is_complete_and_resource_policy_blocks_remote_and_outside_files(self):
        root = ROOT / "rm_client/ui/endfield/changelog/assets"
        self.assertEqual(validate(root)["status"], "PASS")
        policy = LocalResourcesOnly(root)
        for target, blocked in ((QUrl.fromLocalFile(str(root / "index.html")), False),
                                (QUrl("https://example.invalid/"), True),
                                (QUrl.fromLocalFile(str(ROOT / "main.py")), True)):
            calls = []
            policy.interceptRequest(NS(requestUrl=lambda: target, block=calls.append))
            self.assertEqual(calls, [True] if blocked else [])

    def test_english_uses_original_latin_face_and_local_content(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.host.registry = NS(get=lambda name: NS(
            enabled=False, get_setting=lambda _: NS(value="English")))
        self.dialog = ChangelogDialog(self.host)
        self.dialog.show()
        for _ in range(120):
            if javascript(self.dialog.page, "document.fonts.status==='loaded'&&!!document.querySelector('.ej1XT0 p')"):
                break
            QTest.qWait(30)
        self.assertEqual(javascript(self.dialog.page,
            "getComputedStyle(document.documentElement).fontFamily"), "HarmonyOS_Sans")
        text = javascript(self.dialog.page, "document.querySelector('.ej1XT0').innerText")
        self.assertTrue(any(value in text for value in (
            "Local changes", "Esc menu cleanup", "Original bulletin UI", "Client controls")))
        self.assertNotIn("界面调整", text)
        self.assertEqual(javascript(self.dialog.page, "document.documentElement.lang"), "en-us")


if __name__ == "__main__":
    unittest.main()
