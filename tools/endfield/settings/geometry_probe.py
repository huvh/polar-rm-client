"""在生产模态循环内验证窗口切换后的逻辑坐标、布局和未提交草稿。"""
import time

from PySide6.QtCore import QPoint, QRect, Qt, QObject, QEvent
from PySide6.QtTest import QTest

from rm_client.ui.cs2_video_settings import VideoPreferences, apply_window_settings
from rm_client.ui.endfield.settings.widgets import SettingsRow


class TransitionRecorder(QObject):
    """记录原生主窗口重绘前，设置是否已覆盖客户区，并测量同步阻塞。"""
    def __init__(self, dialog, host):
        super().__init__(dialog)
        self.dialog, self.host = dialog, host
        self.started = None
        self.samples = []
        self.calls = []
        self.originals = {}
        for name in ("apply_layout_scale","settle_layout"):
            original = getattr(dialog,name)
            self.originals[name] = original
            def measured(*args, method=original, label=name, **kwargs):
                start = time.perf_counter()
                result = method(*args,**kwargs)
                if self.started is not None:
                    self.calls.append({"method":label,"ms":round((time.perf_counter()-start)*1000,2)})
                return result
            setattr(dialog,name,measured)
        host.installEventFilter(self)
        dialog.installEventFilter(self)

    def begin(self):
        self.samples.clear()
        self.calls.clear()
        self.started = time.perf_counter()

    def eventFilter(self, watched, event):
        if self.started is not None and event.type() == QEvent.Type.Paint:
            target = QRect(self.host.mapToGlobal(QPoint()),self.host.size())
            self.samples.append({"window":"host" if watched is self.host else "settings",
                                 "ms":round((time.perf_counter()-self.started)*1000,2),
                                 "covered":self.dialog.geometry().adjusted(-1,-1,1,1).contains(target)})
        return False

    def finish(self, dispatch_ms):
        self.started = None
        host_paints = [sample for sample in self.samples if sample["window"] == "host"]
        assert host_paints,"Missing native host paints during transition"
        assert all(sample["covered"] for sample in host_paints),host_paints
        first_cover = next(sample["ms"] for sample in self.samples
                           if sample["window"] == "settings" and sample["covered"])
        assert first_cover <= host_paints[0]["ms"],(first_cover,host_paints[0])
        return {"dispatch_ms":round(dispatch_ms,2),"calls":list(self.calls),"paints":list(self.samples)}

    def detach(self):
        self.host.removeEventFilter(self)
        self.dialog.removeEventFilter(self)
        for name,original in self.originals.items():
            setattr(self.dialog,name,original)
        self.deleteLater()


def exercise_geometry(dialog, host, out, prefix):
    samples = []
    dialog.tabs.setCurrentIndex(3)
    page = dialog.tabs.currentWidget()
    builder = getattr(page,"builder",None)
    elapsed = 0
    while builder is not None and not builder.ready and not builder.error and elapsed < 8000:
        QTest.qWait(10)
        elapsed += 10
    if builder is not None:
        assert builder.ready,builder.error
    field = page.controls[("RobotLink","Mouse Sensitivity")]
    field.spin.setValue(1.75)
    recorder = TransitionRecorder(dialog,host)

    def inspect(phase):
        QTest.qWait(500)
        expected = QRect(host.mapToGlobal(QPoint()),host.size())
        assert dialog.geometry() == expected,(phase,dialog.geometry(),expected)
        assert dialog.panel.size() == host.size(),phase
        assert page.controls[("RobotLink","Mouse Sensitivity")] is field
        assert field.spin.value() == 1.75,phase
        filename = f"{prefix}_{phase}.png"
        assert dialog.grab().save(str(out/filename))
        for row in page.findChildren(SettingsRow):
            assert row.rect().contains(row.control.geometry()),(phase,row.label.text(),row.size(),row.control.geometry(),row.isVisible())
        samples.append({"phase":phase,"fullscreen":host.isFullScreen(),
                        "host":list(expected.getRect()),"settings":list(dialog.geometry().getRect()),
                        "dpr":dialog.devicePixelRatioF(),"capture":filename})

    inspect("opened")
    for phase in ("f11_once","f11_twice"):
        recorder.begin()
        QTest.keyClick(field.spin,Qt.Key.Key_F11)
        dispatch_ms = (time.perf_counter()-recorder.started)*1000
        inspect(phase)
        samples[-1]["transition"] = recorder.finish(dispatch_ms)
    recorder.begin()
    for _ in range(4):
        QTest.keyClick(dialog,Qt.Key.Key_F11)
    dispatch_ms = (time.perf_counter()-recorder.started)*1000
    inspect("rapid_four_toggles")
    samples[-1]["transition"] = recorder.finish(dispatch_ms)
    apply_window_settings(host,VideoPreferences(window_mode="Borderless"))
    inspect("applied_fullscreen")
    dpr = host.devicePixelRatioF()
    resolution = f"{round(1280*dpr)}×{round(720*dpr)}"
    apply_window_settings(host,VideoPreferences(window_mode="Windowed",resolution=resolution))
    inspect("applied_windowed")
    recorder.detach()
    dialog.tabs.setCurrentIndex(0)
    return samples
