"""Runtime smoke test for the startup wallpaper OpenGL compositor."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QColor, QImage, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

from rm_client.ui.startup_gl import StartupGpuCompositor


class StartupGpuSmokeWidget(QOpenGLWidget):
    def __init__(self) -> None:
        super().__init__()
        self.renderer = StartupGpuCompositor()
        self.result = False
        self.frame_index = 0
        self.resize(420, 210)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(12)

    def initializeGL(self) -> None:
        self.result = self.renderer.initialize()

    def paintGL(self) -> None:
        # Regression coverage for profile/DPR switches: the source dimensions
        # deliberately vary so a stale texture cannot be resized in-place.
        source_sizes = ((420, 210), (640, 360), (512, 288))
        source_w, source_h = source_sizes[self.frame_index % len(source_sizes)]
        image = QImage(source_w, source_h, QImage.Format.Format_RGBA8888)
        image.fill(QColor("#315f87") if self.frame_index % 2 else QColor("#875f31"))
        self.frame_index += 1
        self.renderer.update_frame(image, QRectF(0, 0, 420, 210), self.frame_index, 1.0 / 30.0, 0.12)
        context = self.context()
        self.result = bool(
            self.result
            and context
            and self.renderer.render(context.functions(), QRectF(0, 0, self.width(), self.height()))
        )

    def closeEvent(self, event) -> None:
        self.makeCurrent()
        self.renderer.release()
        self.doneCurrent()
        super().closeEvent(event)


def main() -> int:
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(sys.argv)
    widget = StartupGpuSmokeWidget()
    widget.show()
    QTimer.singleShot(350, lambda: (widget.close(), app.quit()))
    app.exec()
    if not widget.result:
        print(widget.renderer.last_error or "Startup GPU compositor failed")
        return 1
    print(f"Startup GPU compositor runtime smoke passed at {time.perf_counter():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
