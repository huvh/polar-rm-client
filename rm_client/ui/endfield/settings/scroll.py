"""设置页滚轮缓动、拖动惯性和弹性回边；不修改业务控件的设置值。"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QLineEdit, QScrollArea, QWidget,
)

from .resources import source
from .scroll_motion import ScrollMotion, rubber_distance
from .scroll_mask import ScrollMask

_INPUT_EVENTS = frozenset((QEvent.Type.Wheel,QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,
                          QEvent.Type.MouseButtonRelease,QEvent.Type.WindowDeactivate))


class EndfieldScrollArea(QScrollArea):
    def __init__(self, parent=None, *, clock=None):
        super().__init__(parent)
        self.clock = clock or time.perf_counter
        self.motion = ScrollMotion(source()["scroll"])
        self._pressed = None
        self._dragging = False
        self._writing = False
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._external_scroll)
        bar.rangeChanged.connect(self._range_changed)
        bar.sliderPressed.connect(self._cancel)
        self._mask = ScrollMask(self)
        # 标签和行背景也接收拖动；交互控件独立拥有点击和数值拖动。
        QApplication.instance().installEventFilter(self)

    def _sync_bounds(self):
        self.motion.maximum = self.verticalScrollBar().maximum()
        self.motion.extent = max(1,self.viewport().height())
        self.motion.scale = min(self.window().width()/1920,self.window().height()/1080)

    def _cancel(self):
        self._timer.stop()
        self._pressed = None
        if self._dragging and QWidget.mouseGrabber() is self.viewport():
            self.viewport().releaseMouse()
        self._dragging = False
        self._sync_bounds()
        self.motion.stop(clamp=True)
        self._apply_position()

    def _external_scroll(self, value):
        if self._writing:
            return
        self._timer.stop()
        self.motion.position = float(value)
        self.motion.stop()
        self._place_content()
        self._mask.refresh()

    def _range_changed(self, minimum, maximum):
        self.motion.maximum = maximum
        if self.motion.mode == "idle":
            self.motion.position = float(self.verticalScrollBar().value())
            self.motion.stop(clamp=True)

    def _start(self):
        if not self._timer.isActive():
            self._last = self.clock()
            self._timer.start()

    def _tick(self):
        now = self.clock()
        dt, self._last = now-self._last, now
        self._sync_bounds()
        self.motion.advance(dt)
        self._apply_position()
        if self.motion.mode == "idle":
            self._timer.stop()

    def _place_content(self):
        widget = self.widget()
        if widget is not None:
            edge = self.motion.position-self.motion.bound(self.motion.position)
            widget.move(widget.x(),-self.verticalScrollBar().value()-round(edge))

    def _apply_position(self):
        self._writing = True
        try:
            self.verticalScrollBar().setValue(round(self.motion.bound(self.motion.position)))
        finally:
            self._writing = False
        self._place_content()
        self._mask.refresh()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx,dy)
        if self._writing:
            self._place_content()

    def smooth_scroll_to(self, value):
        self._sync_bounds()
        self.motion.smooth_to(value)
        self._start()

    def _wheel(self, event):
        if event.modifiers() or (not event.angleDelta().y() and not event.pixelDelta().y()
                                 and event.phase() != Qt.ScrollPhase.ScrollEnd):
            return False
        self._sync_bounds()
        if self.motion.maximum <= 0:
            return False
        pixels = event.pixelDelta().y()
        if pixels:
            # 触控板像素流已包含设备惯性，不再叠加滚轮缓动。
            self.motion.stop()
            raw = self.motion.position-pixels
            bound = self.motion.bound(raw)
            self.motion.position = bound+rubber_distance(raw-bound,self.motion.extent)
            self._apply_position()
            if event.phase() == Qt.ScrollPhase.NoScrollPhase and raw != bound:
                self.motion.release()
                self._start()
        elif event.angleDelta().y():
            delta = -event.angleDelta().y()/120*self.motion.config["m_ScrollSensitivity"]*self.motion.scale
            self.motion.wheel(delta)
            self._start()
        if event.phase() == Qt.ScrollPhase.ScrollEnd and self.motion.position != self.motion.bound(self.motion.position):
            self.motion.release()
            self._start()
        event.accept()
        return True

    def wheelEvent(self, event):
        if not self._wheel(event):
            super().wheelEvent(event)

    def _owns(self, widget):
        current = widget
        while isinstance(current,QWidget):
            if isinstance(current,QAbstractScrollArea):
                return current is self
            current = current.parentWidget()
        return False

    def _interactive(self, widget):
        while widget is not None and widget is not self.viewport():
            if isinstance(widget,(QAbstractButton,QAbstractSlider,QAbstractSpinBox,QComboBox,QLineEdit)):
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in _INPUT_EVENTS:
            return False
        if kind == QEvent.Type.WindowDeactivate and watched is self.window():
            self._cancel()
            return False
        if kind == QEvent.Type.WindowDeactivate:
            return False
        if not self.isVisible() or not isinstance(watched,QWidget) or not self._owns(watched):
            return False
        if kind == QEvent.Type.Wheel:
            return self._wheel(event)
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._timer.stop()
            self.motion.stop()
            if not self._interactive(watched):
                self._sync_bounds()
                self._pressed = event.globalPosition().y()
                self.motion.begin_drag()
                self._start()
            elif self.motion.position != self.motion.bound(self.motion.position):
                self.motion.release()
                self._start()
            return False
        if self._pressed is None:
            return False
        if kind == QEvent.Type.MouseMove:
            distance = self._pressed-event.globalPosition().y()
            if not self._dragging and abs(distance)<QApplication.startDragDistance():
                return False
            if not self._dragging:
                self._dragging = True
                self.viewport().grabMouse()
            self.motion.drag(distance)
            self._apply_position()
            event.accept()
            return True
        if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            dragging = self._dragging
            self._pressed = None
            self._dragging = False
            if QWidget.mouseGrabber() is self.viewport():
                self.viewport().releaseMouse()
            self._tick()
            self.motion.release()
            self._start()
            return dragging
        return False

    def ensureWidgetVisible(self, widget, xmargin=50, ymargin=50):
        before = self.verticalScrollBar().value()
        self._writing = True
        try:
            super().ensureWidgetVisible(widget,xmargin,ymargin)
            target = self.verticalScrollBar().value()
            self.verticalScrollBar().setValue(before)
        finally:
            self._writing = False
        self._place_content()
        self.smooth_scroll_to(target)

    def keyPressEvent(self, event):
        bar = self.verticalScrollBar()
        steps = {Qt.Key.Key_Up:-bar.singleStep(),Qt.Key.Key_Down:bar.singleStep(),
                 Qt.Key.Key_PageUp:-bar.pageStep(),Qt.Key.Key_PageDown:bar.pageStep()}
        if event.key() in steps:
            self.smooth_scroll_to(self.motion.target+steps[event.key()])
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self,"motion"):
            self._cancel()
            self._mask.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_bounds()
        self._mask.refresh()

    def hideEvent(self, event):
        self._cancel()
        super().hideEvent(event)
