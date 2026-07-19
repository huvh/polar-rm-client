"""Real OpenGL framebuffer capture of EconomyPanel at 1K / 2K."""

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

OUT = ROOT / "tmp_render_checks" / "audit"
OUT.mkdir(parents=True, exist_ok=True)


def make_scene(w: int, h: int) -> QImage:
    frame = QImage(w, h, QImage.Format.Format_RGB888)
    p = QPainter(frame)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor("#1a5f78"))
    g.setColorAt(0.45, QColor("#3d4a6e"))
    g.setColorAt(1.0, QColor("#8a4a3a"))
    p.fillRect(frame.rect(), g)
    # bright strips so glass refraction is obvious
    p.fillRect(int(w * 0.15), int(h * 0.2), int(w * 0.12), int(h * 0.55), QColor("#4fd0c8"))
    p.fillRect(int(w * 0.72), int(h * 0.25), int(w * 0.14), int(h * 0.45), QColor("#f0a04b"))
    p.end()
    return frame


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

    jobs = [("1k", 1920, 1080), ("2k", 2560, 1440)]
    state = {"i": 0}

    def run_job() -> None:
        if state["i"] >= len(jobs):
            window.close()
            app.quit()
            return
        name, w, h = jobs[state["i"]]
        state["i"] += 1
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
        window.open_economy_workspace("ammo")
        window.economy_morph.progress = 1.0
        window.economy_morph.target = 1.0
        window.frame_scheduler.force()
        window.update()
        QTimer.singleShot(700, lambda n=name: capture(n))

    def capture(name: str) -> None:
        path = OUT / f"economy_live_{name}.png"
        ok = window.grabFramebuffer().save(str(path))
        print(f"saved {path.name} ok={ok} size={path.stat().st_size if path.exists() else 0}")
        print(
            f"  gpu={window.gpu_compositor.available} glass_ms={window.gpu_compositor.last_glass_ms:.2f} "
            f"dynamic_ms={window.gpu_compositor.last_dynamic_ms:.2f} "
            f"morph={window.economy_morph.progress:.2f} hotspots="
            f"{len([h for h in window.hotspots if str(h.action).startswith('economy')])}"
        )
        # Also dump dynamic FBO if present
        window.makeCurrent()
        if window.gpu_compositor.dynamic_fbo is not None:
            window.gpu_compositor.dynamic_fbo.toImage().save(str(OUT / f"economy_live_{name}_dynamic.png"))
        if window.gpu_compositor.overlay_fbo is not None:
            window.gpu_compositor.overlay_fbo.toImage().save(str(OUT / f"economy_live_{name}_overlay.png"))
        window.doneCurrent()
        QTimer.singleShot(200, run_job)

    QTimer.singleShot(600, run_job)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
