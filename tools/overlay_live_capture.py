"""Real-window validation for QuickActionWheel, MatchChat, and ClickGUI.

The script drives the actual key paths on PolarRMWindow and captures desktop
pixels with QScreen.grabWindow(). It does not save configuration.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QPixmap, QSurfaceFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rm_client.ui.overlay_coordinator import OverlayKind
from rm_client.ui.polar_app import PolarRMWindow


OUT = Path(r"C:\tmp\polar-rm-validation")
OUT.mkdir(parents=True, exist_ok=True)


def grab(window: PolarRMWindow, name: str) -> QPixmap:
    screen = window.screen() or QApplication.primaryScreen()
    pixmap = screen.grabWindow(int(window.winId())) if screen else QPixmap()
    if pixmap.isNull():
        raise RuntimeError(f"{name}: QScreen.grabWindow returned a null image")
    path = OUT / f"overlay_{name}.png"
    if not pixmap.save(str(path)):
        # Windows image viewers can keep the previous validation PNG open.
        # Preserve that evidence and write this run to a unique sibling.
        path = OUT / f"overlay_{name}_{time.time_ns()}.png"
        if not pixmap.save(str(path)):
            raise RuntimeError(f"{name}: could not save {path}")
    return pixmap


def reset_frame_samples(window: PolarRMWindow) -> None:
    window.fps_samples.clear()
    window._last_present_time = time.perf_counter()


def frame_report(window: PolarRMWindow, label: str) -> str:
    samples = [float(value) for value in window.fps_samples if float(value) > 0.0]
    if not samples:
        return f"{label}: no present samples"
    frame_ms = sorted(1000.0 / value for value in samples)
    p95_index = min(len(frame_ms) - 1, max(0, int(len(frame_ms) * 0.95)))
    median_ms = statistics.median(frame_ms)
    p95_ms = frame_ms[p95_index]
    compositor = getattr(window, "gpu_compositor", None)
    stage_text = ""
    if compositor is not None:
        timing_names = ("background", "blur", "glass", "overlay", "dynamic", "present")
        timings = {
            name: float(getattr(compositor, f"last_{name}_ms", 0.0))
            for name in timing_names
        }
        stage_text = ", stages=" + "/".join(
            f"{name}:{value:.2f}"
            for name, value in timings.items()
            if value > 0.0
        )
    click_submit = float(getattr(window.clickgui_gpu, "last_submit_ms", 0.0))
    hud_paint = float(getattr(window, "dynamic_hud_ms", 0.0))
    frame_ema = float(getattr(window, "render_frame_ms_ema", 0.0))
    return (
        f"{label}: samples={len(samples)}, median={median_ms:.2f}ms, "
        f"p95={p95_ms:.2f}ms, frame_ema={frame_ema:.2f}ms, "
        f"hud_paint={hud_paint:.2f}ms, text_submit={click_submit:.2f}ms"
        f"{stage_text}"
    )


def main() -> int:
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)

    app = QApplication(sys.argv)
    window = PolarRMWindow()
    wheel_module = window.registry.get("QuickActionWheel")
    chat_module = window.registry.get("MatchChat")
    armor_module = window.registry.get("ArmorAutoAim")
    if wheel_module is None or chat_module is None:
        raise RuntimeError("QuickActionWheel or MatchChat is not registered")
    wheel_module.enabled = True
    wheel_module.keybind = "Q"
    chat_module.enabled = True
    chat_module.keybind = "T"
    if armor_module is not None:
        draw_fov = armor_module.get_setting("Draw Fov")
        if draw_fov is not None:
            # Keep the validation focused on the radial overlay. The FOV ring
            # is a separate, intentionally large HUD element.
            draw_fov.value = False

    window.resize(1280, 720)
    window.home_visible = False
    window.startup_step = "done"
    window.show()
    window.ensure_camera_started()
    QTest.qWait(700)

    center = QPoint(window.width() // 2, window.height() // 2)
    QCursor.setPos(window.mapToGlobal(center))
    QTest.mouseMove(window, center)
    QTest.keyPress(window, Qt.Key.Key_Q)
    QTest.qWait(260)
    reset_frame_samples(window)
    top = QPoint(center.x(), center.y() - 92)
    QCursor.setPos(window.mapToGlobal(top))
    QTest.mouseMove(window, top)
    # Native QOpenGLWidget windows do not consistently receive synthetic
    # hover moves on every Windows/Qt combination. Exercise the same state
    # update directly after placing the real desktop cursor.
    window.quick_action_wheel.update_pointer(top.x(), top.y())
    window.update()
    QTest.qWait(900)
    wheel_capture = grab(window, "quick_action_wheel")
    wheel_report = frame_report(window, "wheel")
    if not window.quick_action_wheel.visible:
        raise RuntimeError("Q press did not open QuickActionWheel")
    if window.quick_action_wheel.selected_index < 0:
        raise RuntimeError("QuickActionWheel did not select a sector")
    if not window.overlay_coordinator.radial_active:
        raise RuntimeError("OverlayCoordinator did not own radial input")

    QTest.keyPress(window, Qt.Key.Key_Escape)
    QTest.keyRelease(window, Qt.Key.Key_Q)
    QTest.qWait(420)
    if window.overlay_coordinator.radial_active:
        raise RuntimeError("QuickActionWheel retained input ownership after cancel")

    window.match_chat.add(
        "Robot 3 eliminated Robot 4",
        source="referee",
        level="success",
        dedupe_key="live:elimination",
    )
    window.match_chat.add(
        "Dart window: 15s",
        source="referee",
        level="warning",
        dedupe_key="live:dart",
    )
    QTest.keyClick(window, Qt.Key.Key_T)
    QTest.keyClicks(window, "ready")
    reset_frame_samples(window)
    QTest.qWait(900)
    chat_capture = grab(window, "match_chat")
    chat_report = frame_report(window, "chat")
    if not window.match_chat.input_open:
        raise RuntimeError("T press did not open MatchChat input")
    if window.match_chat.input_text != "ready":
        raise RuntimeError("MatchChat did not receive typed input")
    if not window.overlay_coordinator.chat_input:
        raise RuntimeError("OverlayCoordinator did not own chat input")

    QTest.keyClick(window, Qt.Key.Key_Escape)
    QTest.qWait(120)
    if window.match_chat.input_open or window.overlay_coordinator.chat_input:
        raise RuntimeError("Esc did not release MatchChat input")

    window.set_clickgui_visible(True, announce=False, play_sound=False)
    reset_frame_samples(window)
    QTest.qWait(900)
    clickgui_capture = grab(window, "clickgui")
    clickgui_report = frame_report(window, "clickgui")
    if not window.gui_visible or window.gui_timeline.progress < 0.95:
        raise RuntimeError(
            "ClickGUI did not settle open "
            f"(visible={window.gui_visible}, progress={window.gui_timeline.progress:.3f})"
        )
    if window.overlay_coordinator.modal is not OverlayKind.CLICKGUI:
        raise RuntimeError("OverlayCoordinator did not give ClickGUI modal ownership")

    window.set_clickgui_visible(False, announce=False, play_sound=False)
    QTest.qWait(650)
    if window.gui_visible or window.gui_timeline.progress > 0.05:
        raise RuntimeError(
            "ClickGUI did not settle closed "
            f"(visible={window.gui_visible}, progress={window.gui_timeline.progress:.3f})"
        )

    print(
        "real-window overlays passed "
        f"(wheel={wheel_capture.width()}x{wheel_capture.height()}, "
        f"chat={chat_capture.width()}x{chat_capture.height()}, "
        f"clickgui={clickgui_capture.width()}x{clickgui_capture.height()}, "
        f"dpr={window.devicePixelRatioF():.2f})"
    )
    print(wheel_report)
    print(chat_report)
    print(clickgui_report)
    print(f"Output: {OUT}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
