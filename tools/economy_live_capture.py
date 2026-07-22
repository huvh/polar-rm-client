"""Real-device validation of EconomyPanel via QScreen.grabWindow.

Captures the actual on-screen pixels of a live PolarRMWindow at multiple
resolutions.  Does NOT use grabFramebuffer() or offscreen platforms.
Screenshots are written to C:\\tmp\\polar-rm-validation\\.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from rm_client.ui.polar_app import PolarRMWindow

OUT = Path(r"C:\tmp\polar-rm-validation")
OUT.mkdir(parents=True, exist_ok=True)

RESOLUTIONS = [
    ("1280x720", 1280, 720),
    ("1600x900", 1600, 900),
    ("1920x1080", 1920, 1080),
    ("2560x1440", 2560, 1440),
]


def make_scene(w: int, h: int) -> QImage:
    """Synthetic camera frame with bright strips for glass refraction visibility."""
    frame = QImage(w, h, QImage.Format.Format_RGB888)
    p = QPainter(frame)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor("#1a5f78"))
    g.setColorAt(0.45, QColor("#3d4a6e"))
    g.setColorAt(1.0, QColor("#8a4a3a"))
    p.fillRect(frame.rect(), g)
    p.fillRect(int(w * 0.15), int(h * 0.2), int(w * 0.12), int(h * 0.55), QColor("#4fd0c8"))
    p.fillRect(int(w * 0.72), int(h * 0.25), int(w * 0.14), int(h * 0.45), QColor("#f0a04b"))
    p.end()
    return frame


def grab_window(window: PolarRMWindow) -> QPixmap:
    """Capture real on-screen pixels via QScreen.grabWindow (NOT grabFramebuffer)."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return QPixmap()
    return screen.grabWindow(int(window.winId()))


def main() -> int:
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)

    app = QApplication(sys.argv)
    window = PolarRMWindow()
    cam = window.registry.get("CameraFeed")
    if cam and cam.get_setting("Source"):
        cam.get_setting("Source").value = "Synthetic"
    eco = window.registry.get("EconomyPanel")
    if eco and eco.get_setting("Open Style"):
        eco.get_setting("Open Style").value = "Dynamic Island"
    window.show()

    state = {"i": 0, "phase": "open"}

    def run_job() -> None:
        idx = state["i"]
        if idx >= len(RESOLUTIONS):
            print(f"\nAll captures done. Output: {OUT}")
            window.close()
            app.quit()
            return

        name, w, h = RESOLUTIONS[idx]
        phase = state["phase"]

        if phase == "open":
            # Resize and prepare scene
            window.resize(w, h)
            window.home_visible = False
            window.startup_step = "done"
            window.gui_visible = False
            frame = make_scene(w, h)
            window.frame_image = frame
            window.frame_pixmap = QPixmap.fromImage(frame)
            window._last_capture_sequence += 1
            window._gpu_background_key = None
            window._gpu_static_ui_key = None
            # Open economy workspace
            window.open_economy_workspace("ammo")
            window.economy_island.progress = 1.0
            window.economy_island.target = 1.0
            window.economy_island.velocity = 0.0
            window.frame_scheduler.force()
            window.update()
            # Wait for animation to settle, then capture
            QTimer.singleShot(800, lambda: capture(name, w, h, "open"))

        elif phase == "close":
            # Close economy workspace
            window.close_economy_workspace()
            window.economy_island.progress = 0.0
            window.economy_island.target = 0.0
            window.economy_island.velocity = 0.0
            window.frame_scheduler.force()
            window.update()
            QTimer.singleShot(600, lambda: capture(name, w, h, "closed"))

    def capture(name: str, w: int, h: int, phase: str) -> None:
        pixmap = grab_window(window)
        if pixmap.isNull():
            print(f"  WARN: grabWindow returned null for {name}_{phase}")
        else:
            path = OUT / f"economy_{name}_{phase}.png"
            pixmap.save(str(path))
            print(f"  saved {path.name} ({pixmap.width()}x{pixmap.height()})")

        print(
            f"  gpu={window.gpu_compositor.available} "
            f"island={window.economy_island.progress:.2f} "
            f"hotspots={len([h for h in window.hotspots if str(h.action).startswith('economy')])}"
        )

        if phase == "open":
            # Transition to close phase
            state["phase"] = "close"
            QTimer.singleShot(200, run_job)
        else:
            # Move to next resolution
            state["phase"] = "open"
            state["i"] += 1
            QTimer.singleShot(200, run_job)

    QTimer.singleShot(600, run_job)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
