"""对实际模态设置窗口投递Qt滚轮/拖动事件并记录原始时间点的画面。"""
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rm_client.ui.endfield.settings.scroll import EndfieldScrollArea
from rm_client.ui.endfield.settings.widgets import SettingsRow


def exercise_scroll(dialog, out, *, record=False):
    app = QApplication.instance()
    report = {"wheel":[],"drag":{},"edge":{}}
    dialog.tabs.setCurrentIndex(0)
    QTest.qWait(400)
    video = dialog.tabs.widget(0)
    scroll = video.findChild(EndfieldScrollArea)
    scroll.verticalScrollBar().setValue(0)
    combo = video.controls["window_mode"]
    original_value = combo.currentIndex()
    real_clock = scroll.clock
    frozen = [100.0]
    scroll.clock = lambda:frozen[0]
    try:
        center = combo.rect().center()
        event = QWheelEvent(QPointF(center),QPointF(combo.mapToGlobal(center)),QPoint(),QPoint(0,-360),
                            Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        app.sendEvent(combo,event)
        assert scroll.motion.mode == "tween"
        assert scroll.verticalScrollBar().value() == 0
        for at in (.02,.06,.16):
            frozen[0] = 100+at
            QTest.qWait(16)
            scroll._tick()
            position = scroll.motion.position
            report["wheel"].append({"at":at,"position":position,"target":scroll.motion.target})
            dialog.grab().save(str(out/f"scroll_wheel_{round(at*1000)}ms.png"))
        assert 0<report["wheel"][0]["position"]<report["wheel"][1]["position"]<=report["wheel"][2]["position"]
        assert combo.currentIndex() == original_value
        if record:
            frames = out/"frames"
            frames.mkdir(exist_ok=True)
            scroll.verticalScrollBar().setValue(0)
            for frame in range(60):
                frozen[0] = 101+frame/30
                scroll._tick()
                if frame%6 == 0:
                    delta = -360 if frame<30 else 360
                    app.sendEvent(combo,QWheelEvent(QPointF(center),QPointF(combo.mapToGlobal(center)),QPoint(),QPoint(0,delta),
                        Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False))
                QTest.qWait(8)
                dialog.grab().save(str(frames/f"frame_{frame:03}.png"))
            report["recording"] = "60 actual QWidget frames; scroll clock sampled at 30 Hz"
    finally:
        scroll._cancel()
        scroll.clock = real_clock

    page = dialog.pages["界面 / HUD"]
    dialog.tabs.setCurrentWidget(page)
    QTest.qWait(400)
    scroll = page
    scroll.verticalScrollBar().setValue(200)

    def gesture(distance):
        row = next(row for row in page.findChildren(SettingsRow) if 30<row.label.mapTo(scroll.viewport(),QPoint()).y()<scroll.viewport().height()-100)
        start = QPointF(row.label.mapToGlobal(row.label.rect().center()))
        def mouse(widget,kind,global_point,button,buttons):
            local = widget.mapFromGlobal(global_point.toPoint())
            app.sendEvent(widget,QMouseEvent(kind,QPointF(local),global_point,button,buttons,Qt.KeyboardModifier.NoModifier))
        mouse(row.label,QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton)
        for i in range(1,9):
            point = start+QPointF(0,distance*i/8)
            mouse(scroll.viewport(),QEvent.Type.MouseMove,point,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton)
            QTest.qWait(16)
        mouse(scroll.viewport(),QEvent.Type.MouseButtonRelease,start+QPointF(0,distance),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)
    gesture(-96)
    released, velocity = scroll.motion.position,scroll.motion.velocity
    QTest.qWait(80)
    report["drag"] = {"released":released,"coasting":scroll.motion.position,"initial_velocity":velocity,"velocity":scroll.motion.velocity}
    assert scroll.motion.position>released and 0<scroll.motion.velocity<velocity
    dialog.grab().save(str(out/"scroll_inertia.png"))
    scroll.verticalScrollBar().setValue(0)
    gesture(100)
    edge = scroll.motion.position
    assert edge<0 and scroll.widget().y()>0
    dialog.grab().save(str(out/"scroll_edge_release.png"))
    QTest.qWait(250)
    returning = scroll.motion.position
    QTest.qWait(700)
    report["edge"] = {"released":edge,"at_250ms":returning,"settled":scroll.motion.position}
    assert abs(returning)<abs(edge) and abs(scroll.motion.position)<.1
    scroll.motion.wheel(120)
    scroll._start()
    dialog.tabs.setCurrentIndex(0)
    assert not scroll._timer.isActive()
    assert scroll.widget().y() == -scroll.verticalScrollBar().value()
    report["lifecycle"] = "page switch cancelled motion and restored content transform"
    return report
