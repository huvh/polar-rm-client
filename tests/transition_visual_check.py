"""Capture real OpenGL frames across startup-page transitions."""

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


def main() -> int:
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(sys.argv)
    window = PolarRMWindow()
    # Exercise the actual 2K transition path.  Directly assigning
    # ``startup_step`` used to skip the GPU island timeline and could not
    # reproduce the high-DPI corruption reported by users.
    window.resize(2560, 1440)
    camera = window.registry.get("CameraFeed")
    if camera and camera.get_setting("Source"):
        camera.get_setting("Source").value = "Synthetic"
    output = Path("tmp_render_checks")
    output.mkdir(exist_ok=True)
    window.show()

    def capture_start() -> None:
        window.grabFramebuffer().save(str(output / "transition_start.png"))
        window.begin_startup_page_transition("match")
        window.update()
        QTimer.singleShot(180, capture_mid)

    def capture_mid() -> None:
        window.grabFramebuffer().save(str(output / "transition_mid_2k.png"))
        QTimer.singleShot(280, capture_match)

    def capture_match() -> None:
        window.grabFramebuffer().save(str(output / "transition_match.png"))
        window.begin_startup_page_transition("robot")
        window.update()
        QTimer.singleShot(360, capture_robot)

    def capture_robot() -> None:
        window.grabFramebuffer().save(str(output / "transition_robot.png"))
        window.home_visible = False
        window.startup_step = "done"
        frame = QImage(1280, 720, QImage.Format.Format_RGB888)
        frame.fill(QColor("#172638"))
        painter = QPainter(frame)
        gradient = QLinearGradient(0, 0, frame.width(), frame.height())
        gradient.setColorAt(0.0, QColor("#245f75"))
        gradient.setColorAt(0.55, QColor("#4b3f69"))
        gradient.setColorAt(1.0, QColor("#9a5448"))
        painter.fillRect(frame.rect(), gradient)
        painter.end()
        window.frame_image = frame
        window.frame_pixmap = QPixmap.fromImage(frame)
        window._last_capture_sequence += 1
        window._gpu_background_key = None
        # Keep the center HUD visible without fabricating a vision target.  A
        # lost target remains in its documented ten-second grace phase, which
        # lets this check exercise the exact runtime dynamic-FBO path.
        presence = window.target_hud_presence
        presence.phase = "Visible"
        presence.opacity = 1.0
        presence.scale = 1.0
        presence._last_now = time.perf_counter()
        target_hud = window.registry.get("CombatTargetHUD")
        if target_hud is not None:
            target_hud.get_setting("Show Bars").value = False
        window.update()
        QTimer.singleShot(450, capture_hud)

    def capture_hud() -> None:
        window.grabFramebuffer().save(str(output / "transition_hud.png"))
        window.makeCurrent()
        if window.gpu_compositor.target_fbo is not None:
            target_image = window.gpu_compositor.target_fbo.toImage()
            target_image.save(str(output / "transition_hud_target.png"))
            ratio = max(1.0, float(window.devicePixelRatioF()))
            hud_scale = window.get_hud_scale(window.width(), window.height())
            outer_radius = (16.0 * 2.35 + (5.0 * 2.35 + 1.0) * 0.5) * hud_scale * ratio
            offset = outer_radius * 0.82
            center_x = target_image.width() * 0.5
            center_y = target_image.height() * 0.5
            corners = tuple(
                (int(round(center_x + dx * offset)), int(round(center_y + dy * offset)))
                for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1))
            )
            window._target_box_regression_failed = any(
                target_image.pixelColor(x, y).alpha() > 2
                for x, y in corners
                if 0 <= x < target_image.width() and 0 <= y < target_image.height()
            )
        window.doneCurrent()
        window.gui_visible = True
        window.frame_scheduler.force()
        window.update()
        QTimer.singleShot(450, capture_clickgui)

    def capture_clickgui() -> None:
        window.grabFramebuffer().save(str(output / "transition_clickgui.png"))
        backend = window.registry.get("ClickGui").get_setting("Render Backend").value
        print(f"clickgui visible={window.gui_visible} progress={window.gui_timeline.progress:.3f} backend={backend} gpu={window.clickgui_gpu.available} error={window.clickgui_gpu.last_error}")
        compositor = window.gpu_compositor
        print(
            "frame timings ms "
            f"background={compositor.last_background_ms:.2f} "
            f"blur={compositor.last_blur_ms:.2f} "
            f"glass={compositor.last_glass_ms:.2f} "
            f"overlay={compositor.last_overlay_ms:.2f} "
            f"dynamic={compositor.last_dynamic_ms:.2f} "
            f"present={compositor.last_present_ms:.2f} "
            f"ema={window.render_frame_ms_ema:.2f} target={window.render_fps_target:.0f}"
        )
        window.close()
        app.quit()

    QTimer.singleShot(500, capture_start)
    app.exec()
    files = [output / name for name in ("transition_start.png", "transition_mid_2k.png", "transition_match.png", "transition_robot.png", "transition_hud.png", "transition_clickgui.png")]
    if not all(path.exists() and path.stat().st_size > 1000 for path in files):
        return 1
    hud = QImage(str(output / "transition_hud.png"))
    center = hud.pixelColor(hud.width() // 2, hud.height() // 2)
    if center.red() + center.green() + center.blue() < 60:
        print("HUD background FBO did not reach the final composition")
        return 1
    if getattr(window, "_target_box_regression_failed", False):
        print("CombatTargetHUD transparent bounding box became visible")
        return 1
    print("Transition visual frames captured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
