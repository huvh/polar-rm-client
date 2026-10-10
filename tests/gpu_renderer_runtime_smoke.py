"""需要桌面 OpenGL 上下文的 ClickGUI GPU 运行时自检。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

from rm_client.ui.clickgui_gpu import ClickGuiDrawList, ClickGuiGpuRenderer


class GpuSmokeWidget(QOpenGLWidget):
    def __init__(self) -> None:
        super().__init__()
        self.renderer = ClickGuiGpuRenderer()
        self.result = False
        self.error = ""
        self.draw_call_count = 0
        self.resize(720, 300)

    def initializeGL(self) -> None:
        self.result = self.renderer.initialize()
        self.error = self.renderer.last_error

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0c0e15"))
        commands = ClickGuiDrawList()
        commands.rect(QRectF(24, 28, 672, 224), 14, QColor(24, 28, 42, 224), QColor(255, 255, 255, 42), 1.0)
        commands.image(
            QRectF(636, 38, 42, 31),
            Path(__file__).resolve().parents[1] / "assets" / "jello" / "options.png",
            QColor(255, 255, 255, 180),
        )
        commands.text(
            QRectF(48, 54, 624, 64),
            "POLAR-RM 字体 GPU 144 FPS",
            QFont("Microsoft YaHei UI", 28),
            QColor("#f7f9ff"),
            Qt.AlignmentFlag.AlignCenter,
            text_profile="jello",
            preserve_weight=True,
        )
        commands.text(
            QRectF(646, 54, 22, 28),
            ">",
            QFont("Microsoft YaHei UI", 18),
            QColor("#f7f9ff"),
            Qt.AlignmentFlag.AlignCenter,
            rotation_degrees=90.0,
            render_scale=0.85,
        )
        for index in range(24):
            commands.text(
                QRectF(48 + (index % 6) * 102, 132 + (index // 6) * 26, 94, 22),
                f"模块 {index:02d}",
                QFont("Microsoft YaHei UI", 10),
                QColor("#b9d9ef"),
                Qt.AlignmentFlag.AlignCenter,
            )
        context = self.context()
        if context and self.result:
            # Publish glyph pages before native painting. The render pass is
            # read-only and cannot replace atlas textures halfway through.
            self.renderer.prepare_frame(commands, self.devicePixelRatioF())
            stable_generation = self.renderer.atlas_generation
            stable_pages = (
                len(self.renderer.atlases),
                len(self.renderer.shaped_atlases),
            )
            for _ in range(100):
                self.renderer.prepare_frame(commands, self.devicePixelRatioF())
            self.result = bool(
                self.result
                and self.renderer.atlas_generation == stable_generation
                and stable_pages
                == (
                    len(self.renderer.atlases),
                    len(self.renderer.shaped_atlases),
                )
            )
        painter.beginNativePainting()
        self.result = bool(
            self.result
            and context
            and self.renderer.render(
                context.extraFunctions(),
                commands,
                self.width(),
                self.height(),
                self.devicePixelRatioF(),
                atlas_prepared=True,
            )
        )
        self.error = self.renderer.last_error
        self.draw_call_count = self.renderer.draw_calls
        self.result = self.result and self.draw_call_count <= 8
        painter.endNativePainting()
        painter.end()

    def finish(self, app: QApplication) -> None:
        artifact_name = __import__("os").environ.get("POLAR_GPU_SMOKE_ARTIFACT", "").strip()
        if artifact_name:
            self.grabFramebuffer().save(artifact_name)
        self.close()
        app.quit()

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
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(sys.argv)
    widget = GpuSmokeWidget()
    widget.show()
    QTimer.singleShot(450, lambda: widget.finish(app))
    app.exec()
    if not widget.result:
        print(widget.error or f"GPU renderer failed (draw_calls={widget.draw_call_count})")
        return 1
    print("GPU renderer runtime smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
