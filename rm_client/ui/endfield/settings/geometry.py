"""让独立模态设置窗始终贴合其客户端父窗口的逻辑内容区。"""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer


class SettingsGeometryGuard(QObject):
    def __init__(self, host, dialog):
        super().__init__(dialog)
        self.host = host
        self.dialog = dialog
        self.active = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync)
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(32)
        self.settle_timer.timeout.connect(self.sync)
        host.installEventFilter(self)
        dialog.installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.dialog:
            if kind == QEvent.Type.Show:
                self.active = True
                self.timer.start(0)
                self.settle_timer.start()
            elif kind == QEvent.Type.Hide:
                self.active = False
                self.timer.stop()
                self.settle_timer.stop()
        elif self.active and kind in (
            QEvent.Type.Resize,QEvent.Type.Move,QEvent.Type.WindowStateChange,
            QEvent.Type.ScreenChangeInternal,QEvent.Type.DevicePixelRatioChange,QEvent.Type.WinIdChange,
        ):
            # Resize过滤器先于QOpenGLWidget重建FBO和paintGL执行，必须先覆盖新客户区。
            if kind in (QEvent.Type.Resize,QEvent.Type.Move,QEvent.Type.WindowStateChange):
                self.sync()
            self.timer.start(0)
            # Windows全屏合成边框在后续原生通知中才改变客户区原点，高DPI下再核对一次。
            self.settle_timer.start()
        return False

    def sync(self):
        if not self.active or not self.dialog.isVisible() or not self.host.isVisible() or self.host.isMinimized():
            return
        target = QRect(self.host.mapToGlobal(QPoint()),self.host.size())
        if self.dialog.geometry() != target:
            self.dialog.fit_client_geometry(target)
