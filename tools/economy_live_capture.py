"""Real-device validation of EconomyPanel via QScreen.grabWindow.

Requirements (audit):
- MUST use QScreen.grabWindow(window.winId()), NOT grabFramebuffer().
- MUST capture animation mid-frames (not just force progress=1.0).
- MUST verify economy panel pixels are actually present in the screenshot.
- MUST report actual window size and DPR.
- Output: C:\\tmp\\polar-rm-validation\\
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, QRectF
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

FAILURES: list[str] = []
SKIPPED: list[str] = []


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


def check_size(pixmap: QPixmap, window: PolarRMWindow, req_w: int, req_h: int, name: str) -> bool:
    """Verify grab size matches window_size * DPR. Flag SKIPPED if screen too small."""
    if pixmap.isNull():
        FAILURES.append(f"{name}: grabWindow returned null")
        return False
    dpr = window.devicePixelRatioF()
    actual_w = window.width()
    actual_h = window.height()
    expected_pw = int(actual_w * dpr)
    expected_ph = int(actual_h * dpr)
    grab_w, grab_h = pixmap.width(), pixmap.height()
    # Get physical screen geometry
    screen = QApplication.primaryScreen()
    screen_geo = screen.geometry() if screen else None
    screen_pw = int(screen_geo.width() * dpr) if screen_geo else 99999
    screen_ph = int(screen_geo.height() * dpr) if screen_geo else 99999
    # Window could not be resized to requested (logical screen too small)
    if actual_w < req_w - 2 or actual_h < req_h - 2:
        SKIPPED.append(
            f"{name}: window clipped to {actual_w}x{actual_h} "
            f"(requested {req_w}x{req_h}, screen too small)"
        )
        return False
    # Window extends beyond physical screen — grab will be clipped
    if expected_pw > screen_pw + 4 or expected_ph > screen_ph + 4:
        SKIPPED.append(
            f"{name}: window {actual_w}x{actual_h} (physical {expected_pw}x{expected_ph}) "
            f"exceeds screen physical {screen_pw}x{screen_ph}"
        )
        return False
    # Grab size should match window * DPR (allow +-4px for WM decorations)
    if abs(grab_w - expected_pw) > 4 or abs(grab_h - expected_ph) > 4:
        FAILURES.append(
            f"{name}: grab size {grab_w}x{grab_h} != expected {expected_pw}x{expected_ph} "
            f"(window={actual_w}x{actual_h} dpr={dpr:.2f})"
        )
        return False
    return True


def check_economy_pixels(pixmap: QPixmap, name: str) -> bool:
    """Verify economy panel rendered real content (not just a dim overlay).

    Checks for THREE distinct pixel classes that a dim-only layer cannot produce:
    1. White/bright text pixels (title, labels) — high R+G+B, low saturation
    2. Teal/cyan accent pixels (category capsules, card borders, button)
    3. Dark panel body pixels (pane fills)

    A mere full-screen dim would only produce class 3 (darkened background),
    so we require class 1 OR class 2 to be present.
    """
    if pixmap.isNull():
        FAILURES.append(f"{name}: grabWindow returned null")
        return False
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    # Sample a grid in the center 60% of the image
    x0, x1 = int(w * 0.2), int(w * 0.8)
    y0, y1 = int(h * 0.2), int(h * 0.8)
    dark_count = 0
    teal_count = 0
    white_text_count = 0
    total = 0
    step = max(1, min((x1 - x0), (y1 - y0)) // 50)
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            total += 1
            # Dark panel body: very low brightness, bluish tint
            if r < 50 and g < 55 and b < 75:
                dark_count += 1
            # Teal/cyan accent: green+blue high, red low
            if g > 140 and b > 140 and r < 130 and (g + b) > (r * 3):
                teal_count += 1
            # White/bright text: all channels high, low saturation
            if r > 180 and g > 180 and b > 180:
                white_text_count += 1
    dark_ratio = dark_count / max(1, total)
    teal_ratio = teal_count / max(1, total)
    text_ratio = white_text_count / max(1, total)

    # Liquid glass style: panels are transparent, so "dark body" pixels are rare.
    # Instead verify glass edges (teal) and text are present.
    if teal_ratio < 0.005 and text_ratio < 0.001:
        FAILURES.append(
            f"{name}: no glass/content pixels (dark={dark_ratio:.3f}, teal={teal_ratio:.4f}, "
            f"text={text_ratio:.4f}, sampled={total}). Panel not rendered."
        )
        return False
    if teal_ratio < 0.002 and text_ratio < 0.002:
        FAILURES.append(
            f"{name}: no UI content pixels (teal={teal_ratio:.4f}, text={text_ratio:.4f}). "
            f"Only dim overlay detected — panel content not rendered."
        )
        return False
    print(f"    pixel check OK: dark={dark_ratio:.3f} teal={teal_ratio:.4f} "
          f"text={text_ratio:.4f} ({total} samples)")
    return True


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

    state = {"i": 0, "phase": "mid_open", "frame": 0}

    def run_job() -> None:
        idx = state["i"]
        if idx >= len(RESOLUTIONS):
            print(f"\n{'='*60}")
            if SKIPPED:
                print(f"SKIPPED ({len(SKIPPED)}):")
                for s in SKIPPED:
                    print(f"  ~ {s}")
            if FAILURES:
                print(f"FAILURES ({len(FAILURES)}):")
                for f in FAILURES:
                    print(f"  - {f}")
            else:
                print("ALL CHECKS PASSED")
            print(f"Output: {OUT}")
            window.close()
            app.quit()
            return

        name, w, h = RESOLUTIONS[idx]
        phase = state["phase"]

        if phase == "mid_open":
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
            # Open economy workspace — let animation run naturally
            window.open_economy_workspace("ammo")
            window.frame_scheduler.force()
            window.update()
            # Capture mid-animation frame (~200ms in)
            state["phase"] = "mid_capture"
            QTimer.singleShot(200, run_job)

        elif phase == "mid_capture":
            # Capture animation mid-frame
            pixmap = grab_window(window)
            dpr = window.devicePixelRatioF()
            actual_w = window.width()
            actual_h = window.height()
            path = OUT / f"economy_{name}_mid_open.png"
            if not pixmap.isNull():
                pixmap.save(str(path))
            print(f"  [{name}] mid_open: window={actual_w}x{actual_h} dpr={dpr:.2f} "
                  f"island={window.economy_island.progress:.3f} "
                  f"grab={pixmap.width()}x{pixmap.height()}")
            # Wait for animation to settle
            state["phase"] = "settled"
            QTimer.singleShot(700, run_job)

        elif phase == "settled":
            # Capture settled open state
            pixmap = grab_window(window)
            path = OUT / f"economy_{name}_open.png"
            if not pixmap.isNull():
                pixmap.save(str(path))
            progress = window.economy_island.progress
            hotspots = len([h for h in window.hotspots if str(h.action).startswith("economy")])
            print(f"  [{name}] open: island={progress:.3f} hotspots={hotspots} "
                  f"grab={pixmap.width()}x{pixmap.height()}")
            # Size validation (flags SKIPPED if screen too small)
            size_ok = check_size(pixmap, window, w, h, f"{name}_open")
            if size_ok:
                # Pixel verification (requires text OR teal, not just dim)
                check_economy_pixels(pixmap, f"{name}_open")
            # Verify animation actually settled
            if progress < 0.95:
                FAILURES.append(f"{name}_open: animation did not settle (progress={progress:.3f})")
            # Verify hotspots exist
            if hotspots < 3:
                FAILURES.append(f"{name}_open: too few hotspots ({hotspots})")
            state["phase"] = "close"
            QTimer.singleShot(100, run_job)

        elif phase == "close":
            # Close economy workspace — let animation run naturally
            window.close_economy_workspace()
            window.frame_scheduler.force()
            window.update()
            state["phase"] = "close_capture"
            QTimer.singleShot(200, run_job)

        elif phase == "close_capture":
            # Capture mid-close frame
            pixmap = grab_window(window)
            path = OUT / f"economy_{name}_mid_close.png"
            if not pixmap.isNull():
                pixmap.save(str(path))
            print(f"  [{name}] mid_close: island={window.economy_island.progress:.3f}")
            state["phase"] = "closed"
            QTimer.singleShot(600, run_job)

        elif phase == "closed":
            # Capture fully closed state
            pixmap = grab_window(window)
            path = OUT / f"economy_{name}_closed.png"
            if not pixmap.isNull():
                pixmap.save(str(path))
            progress = window.economy_island.progress
            print(f"  [{name}] closed: island={progress:.3f}")
            if progress > 0.05:
                FAILURES.append(f"{name}_closed: animation did not close (progress={progress:.3f})")
            # Move to next resolution
            state["phase"] = "mid_open"
            state["i"] += 1
            QTimer.singleShot(200, run_job)

    QTimer.singleShot(600, run_job)
    app.exec()

    if FAILURES:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
