"""原版公告 Web 页面适配；Qt 只管理模态、输入清空、关闭与急停。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QUrl, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from rm_client.runtime_paths import RuntimePaths
from rm_client.ui.emergency_shortcut import install_estop_shortcut
from rm_client.ui.jello_locale import chinese_enabled
from .content import changelog_entries

_profile = None


class LocalResourcesOnly(QWebEngineUrlRequestInterceptor):
    """浏览器仅可读取资源包内部文件；禁止远程访问与任意本地文件读取。"""
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root.resolve()
        self.blocked = []

    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.scheme() in {"data", "blob", "about"}
        if url.isLocalFile() and not url.host():
            try:
                Path(url.toLocalFile()).resolve().relative_to(self.root)
                allowed = True
            except ValueError:
                allowed = False
        if not allowed:
            # 仅记录来源类别，避免记录外部 URL 参数或无限增长。
            if len(self.blocked) < 16:
                self.blocked.append(url.scheme() + ":" + url.host())
            info.block(True)


def local_profile(root: Path):
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile(QApplication.instance())
        _profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        _profile.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36")
        _profile.resources = LocalResourcesOnly(root, _profile)
        _profile.setUrlRequestInterceptor(_profile.resources)
    return _profile


class ChangelogPage(QWebEnginePage):
    ready = Signal()

    def __init__(self, profile, dialog):
        super().__init__(profile, dialog)
        self.dialog = dialog
        self.errors = []
        self.setBackgroundColor(QColor("#000000"))

    def acceptNavigationRequest(self, url, kind, main_frame):
        if main_frame and url.isLocalFile() and url.fileName() == "close.local":
            self.dialog.reject()
            return False
        return url.isLocalFile() or url.toString() == "about:blank"

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message == "POLAR_CHANGELOG_READY":
            self.ready.emit()
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            if len(self.errors) < 16:
                self.errors.append(message[:300])


class ChangelogCloseFilter(QObject):
    """网页加载和透明窗口阶段也由当前模态接收 Esc。"""
    def eventFilter(self, watched, event):
        if event.type() not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        dialog = self.parent()
        if event.key() != Qt.Key.Key_Escape or QApplication.activeModalWidget() is not dialog:
            return False
        event.accept()
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            dialog.reject()
        return True


class ChangelogDialog(QDialog):
    def __init__(self, host):
        super().__init__(host, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        chinese = chinese_enabled(host.registry)
        self.setWindowTitle("POLAR-RM · 更新日志" if chinese else "POLAR-RM · Changelog")
        self.setModal(True)
        # WebEngine 创建原生子窗口时不能把 WA_NativeWindow 沿 QObject 父链
        # 传播到主 OpenGL 窗口；否则 Qt 会替换 HWND，原生 Esc 仍合成到旧句柄。
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        from rm_client.ui.fullscreen_composition import FullscreenDialogGuard
        self._fullscreen_guard = FullscreenDialogGuard(host.window(), self)
        # WebEngine 冷启动尚未提交页面时保持透明，不用空黑窗口盖住 Esc。
        self.setWindowOpacity(0.0)
        self.content_ready = False
        self._dismissed = False
        self._load_deadline = QTimer(self)
        self._load_deadline.setSingleShot(True)
        self._load_deadline.setInterval(10000)
        self._load_deadline.timeout.connect(lambda: self._load_failed(host))
        self.resize(host.size())
        self.move(host.mapToGlobal(QPoint(0, 0)))
        paths = getattr(host, "paths", None) or RuntimePaths.discover()
        root = paths.endfield_changelog_pack
        if not (root / "index.html").is_file():
            raise FileNotFoundError("原版公告资源包缺失：" + str(root))
        self.view = QWebEngineView(self)
        self.view.setObjectName("ChangelogBody")
        self.page = ChangelogPage(local_profile(root), self)
        self.page.ready.connect(self._reveal_content)
        self.page.loadFinished.connect(lambda loaded: None if loaded else self._load_failed(host))
        self.view.setPage(self.page)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        script = QWebEngineScript()
        script.setName("POLAR local changelog data")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode("window.POLAR_CHANGELOG=" + json.dumps(
            {"entries": changelog_entries(chinese), "title": self.windowTitle()},
            ensure_ascii=False) + ";")
        self.page.scripts().insert(script)
        audio = host.registry.get("AudioFeedback")
        enabled = audio.get_setting("Enabled") if audio else None
        volume = audio.get_setting("UI Volume") if audio else None
        self.page.setAudioMuted(not bool(
            audio and getattr(audio, "enabled", False)
            and (enabled is None or enabled.value)
            and (volume is None or float(volume.value) > 0)
        ))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.estop_shortcut = install_estop_shortcut(self, host)
        # 页面脚本未加载时也能退出；快捷键由当前模态窗口消费，不传回 Esc 菜单。
        self.close_filter = ChangelogCloseFilter(self)
        app = QApplication.instance()
        app.installEventFilter(self.close_filter)
        self.finished.connect(lambda _result: app.removeEventFilter(self.close_filter))
        url = QUrl.fromLocalFile(str(root / "index.html"))
        url.setQuery("lang=" + ("zh-cn" if chinese else "en-us") + "&platform=Windows&channel=1")
        self.view.load(url)

    def _reveal_content(self):
        if self._dismissed:
            return
        self.content_ready = True
        self._load_deadline.stop()
        self.setWindowOpacity(1.0)

    def _load_failed(self, host):
        if self.content_ready or self._dismissed:
            return
        self.reject()
        host.toast("更新日志加载失败，请重试", kind="warning")

    def showEvent(self, event):
        super().showEvent(event)
        if not self.content_ready:
            self._load_deadline.start()

    def done(self, result):
        self._dismissed = True
        self._load_deadline.stop()
        super().done(result)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 210))


def show_changelog(host):
    host.backend.lock_control("menu dialog opened")
    host._neutralize_modal_inputs()
    dialog = None
    try:
        dialog = ChangelogDialog(host)
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        if dialog is not None:
            dialog.deleteLater()
        host._neutralize_modal_inputs()
        host.invalidate_transient_overlay_scene()
        host.frame_scheduler.force()
        host.update()
