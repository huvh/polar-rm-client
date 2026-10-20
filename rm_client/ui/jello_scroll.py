"""Continuous, reversible wheel scrolling for native Jello settings pages.

Only scrollbar positions change; children, fonts and the glass renderer are not
rebuilt during a gesture. Trackpad pixel deltas remain direct manipulation.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QScrollArea

from .animation import step_damped_spring


class JelloScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._position = 0.0
        self._velocity = 0.0
        self._target = 0.0
        self._last_time = 0.0
        self._writing = False
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._scroll_timer.setInterval(7)
        self._scroll_timer.timeout.connect(self._tick_scroll)
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._external_scroll)
        bar.rangeChanged.connect(self._clamp_target)
        bar.sliderPressed.connect(self._stop_scroll)

    def _stop_scroll(self):
        self._scroll_timer.stop()
        self._position = self._target = float(self.verticalScrollBar().value())
        self._velocity = 0.0

    def _external_scroll(self, _value):
        if not self._writing:
            self._stop_scroll()

    def _clamp_target(self, minimum, maximum):
        self._target = max(float(minimum), min(float(maximum), self._target))

    def scroll_by(self, delta: float, *, direct=False):
        bar = self.verticalScrollBar()
        if not self._scroll_timer.isActive():
            self._position = float(bar.value())
            self._target = self._position
            self._velocity = 0.0
        self._target = max(float(bar.minimum()), min(float(bar.maximum()), self._target + delta))
        if direct:
            self._stop_scroll()
            bar.setValue(round(max(bar.minimum(), min(bar.maximum(), bar.value() + delta))))
        else:
            if not self._scroll_timer.isActive():
                self._last_time = time.perf_counter()
                self._scroll_timer.start()

    def _tick_scroll(self):
        now = time.perf_counter()
        dt = now - self._last_time
        self._last_time = now
        bar = self.verticalScrollBar()
        self._position, self._velocity = step_damped_spring(
            self._position, self._velocity, self._target, dt,
            stiffness=300.0, damping_ratio=1.0,
        )
        self._position = max(float(bar.minimum()), min(float(bar.maximum()), self._position))
        settled = abs(self._target - self._position) < .02 and abs(self._velocity) < .08
        self._writing = True
        try:
            bar.setValue(round(self._target if settled else self._position))
        finally:
            self._writing = False
        if settled:
            self._stop_scroll()

    def wheelEvent(self, event):
        if event.modifiers() or (not event.angleDelta().y() and not event.pixelDelta().y()):
            return super().wheelEvent(event)
        pixels = event.pixelDelta().y()
        self.scroll_by(-float(pixels) if pixels else -event.angleDelta().y() / 120.0 * 70.0,
                       direct=bool(pixels))
        event.accept()

    def hideEvent(self, event):
        self._stop_scroll()
        super().hideEvent(event)
