"""Slow, frame-by-frame visual audit for ClickGUI text and vision-kill flow.

Run:
  .\\.venv\\Scripts\\python.exe tools\\visual_audit.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from rm_client.combat_events import VisionKillDetector
from rm_client.ui.polar_app import PolarRMWindow
from rm_client.vision import ArmorObservation, VisionLossEvidence


OUT = ROOT / "tmp_render_checks" / "audit"
OUT.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


def save(img: QImage, name: str) -> Path:
    path = OUT / name
    img.save(str(path), "PNG")
    log(f"saved {path.name} ({img.width()}x{img.height()})")
    return path


def crop(img: QImage, x: float, y: float, w: float, h: float, name: str) -> Path:
    cx = int(img.width() * x)
    cy = int(img.height() * y)
    cw = max(1, int(img.width() * w))
    ch = max(1, int(img.height() * h))
    return save(img.copy(cx, cy, cw, ch), name)


def make_bg(w: int = 1280, h: int = 720) -> QImage:
    image = QImage(w, h, QImage.Format.Format_RGB888)
    p = QPainter(image)
    p.fillRect(0, 0, w, h, QColor("#1c2c3a"))
    p.fillRect(0, 0, w // 2, h, QColor("#152432"))
    # fake armor plate region contrast
    p.fillRect(560, 300, 160, 80, QColor("#3a4a5a"))
    p.setPen(QColor("#66aadd"))
    p.drawRect(560, 300, 160, 80)
    p.end()
    return image


def lit_armor(token: int = 0) -> ArmorObservation:
    return ArmorObservation(
        103,
        "three",
        "blue",
        0.93,
        ((560.0, 300.0), (720.0, 300.0), (720.0, 380.0), (560.0, 380.0)),
        light_strength=0.82,
        light_state="lit",
        target_id=7,
    )


def extinguish_armor() -> ArmorObservation:
    return ArmorObservation(
        103,
        "three",
        "extinguish",
        0.91,
        ((562.0, 302.0), (718.0, 302.0), (718.0, 378.0), (562.0, 378.0)),
        light_strength=0.12,
        light_state="extinguished",
        target_id=7,
    )


def main() -> int:
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)

    app = QApplication(sys.argv)
    window = PolarRMWindow()
    window.resize(1920, 1080)
    cam = window.registry.get("CameraFeed")
    if cam and cam.get_setting("Source"):
        cam.get_setting("Source").value = "Synthetic"
    window.home_visible = False
    window.startup_step = "done"
    bg = make_bg()
    window.frame_image = bg
    window.frame_pixmap = QPixmap.fromImage(bg)
    window._last_capture_sequence += 1
    window.show()

    state = {"step": 0}
    detector_log: list[str] = []

    # ---- pure detector timeline (no UI) also written to log ----
    det = VisionKillDetector()
    now = 10.0
    steps = [
        ("LIT", [lit_armor()], None),
        ("LIT2", [lit_armor()], None),
        ("OFF1", [extinguish_armor()], None),
        ("OFF2", [extinguish_armor()], None),
        ("OFF3", [extinguish_armor()], None),
        ("OFF4", [extinguish_armor()], None),
        ("MISS1", [], VisionLossEvidence(7, "three", 0.10, 0.75, True, False, False, 10)),
        ("MISS2", [], VisionLossEvidence(7, "three", 0.10, 0.75, True, False, False, 11)),
        ("MISS3", [], VisionLossEvidence(7, "three", 0.10, 0.75, True, False, False, 12)),
        ("MISS4", [], VisionLossEvidence(7, "three", 0.10, 0.75, True, False, False, 13)),
    ]
    for index, (label, obs, loss) in enumerate(steps):
        now += 0.12 if index else 0.0
        if index == 0:
            now = 10.0
        elif index == 1:
            now = 10.25
        elif index == 2:
            now = 10.45
        else:
            now = 10.45 + (index - 2) * 0.12
        events = det.process(
            obs,
            alliance="Red",
            frame_luminance=0.42,
            frame_token=index + 1,
            frame_size=(1280, 720),
            sensitivity="Lab Responsive",
            loss_evidence=loss,
            now=now,
        )
        detail = events[0].detail if events else "-"
        detector_log.append(
            f"[{index}] {label:5} t={now:.2f} status={det.last_status:22} events={len(events)} detail={detail}"
        )
    log("=== VisionKillDetector Lab Responsive timeline ===")
    for line in detector_log:
        log(line)

    def grab(name: str) -> QImage:
        window.frame_scheduler.force()
        window.update()
        app.processEvents()
        img = window.grabFramebuffer()
        save(img, name)
        return img

    def settle_gui(mode: str) -> None:
        window.mode_manager.set_mode(mode)
        window.gui_visible = True
        now_t = time.perf_counter()
        window.polar_unified_morph.set_target(1.0, 0.01, now=now_t)
        window.polar_unified_morph.update(now=now_t + 1.0)
        window.gui_timeline.progress = 1.0
        window.gui_timeline.target = 1.0
        window.gui_timeline.velocity = 0.0
        for _ in range(12):
            window.gui_motion.begin_frame()
            window.frame_scheduler.force()
            window.update()
            app.processEvents()
            time.sleep(0.05)

    def phase_hud() -> None:
        log("=== phase HUD idle ===")
        window.gui_visible = False
        window.gui_timeline.progress = 0.0
        window.gui_timeline.target = 0.0
        for _ in range(8):
            window.update()
            app.processEvents()
            time.sleep(0.06)
        img = grab("01_hud_idle.png")
        crop(img, 0.35, 0.30, 0.30, 0.40, "01_hud_idle_center.png")

    def phase_clickgui() -> None:
        log("=== phase ClickGUI modes (slow) ===")
        for mode, tag in (
            ("PolarUnified", "unified"),
            ("PolarPanel", "panel"),
            ("PolarNew", "new"),
            ("PolarDropdown", "dropdown"),
        ):
            log(f"-- open {mode} --")
            settle_gui(mode)
            time.sleep(0.35)
            img = grab(f"02_clickgui_{tag}_full.png")
            # panel body
            crop(img, 0.20, 0.15, 0.60, 0.70, f"02_clickgui_{tag}_panel.png")
            # left module names (unified)
            crop(img, 0.22, 0.28, 0.28, 0.50, f"02_clickgui_{tag}_modules.png")
            # right settings labels
            crop(img, 0.50, 0.28, 0.28, 0.50, f"02_clickgui_{tag}_settings.png")
            # mode chips bottom
            crop(img, 0.25, 0.88, 0.50, 0.10, f"02_clickgui_{tag}_modechips.png")
            backend = window.registry.get("ClickGui").get_setting("Render Backend").value
            log(f"   backend={backend} hotspots={len(window.hotspots)} err={window.clickgui_gpu.last_error!r}")
            time.sleep(0.25)

    def phase_kill_ui() -> None:
        log("=== phase EliminationFX + vision kill through UI ===")
        window.gui_visible = False
        window.gui_timeline.progress = 0.0
        window.gui_timeline.target = 0.0
        effect = window.registry.get("EliminationFX")
        if effect:
            effect.enabled = True
        bridge = window.registry.get("TongjiVisionBridge")
        if bridge and bridge.get_setting("Vision Kill Sensitivity"):
            bridge.get_setting("Vision Kill Sensitivity").value = "Lab Responsive"
        # drive detector via accept path simulation using process_vision_kill style
        # by feeding combat events after detector confirms
        det2 = VisionKillDetector()
        timeline = []
        t = 20.0
        # warm lit
        for i in range(3):
            t = 20.0 + i * 0.15
            events = det2.process([lit_armor()], alliance="Red", frame_luminance=0.4, frame_token=100 + i, frame_size=(1280, 720), now=t)
            timeline.append((t, "LIT", det2.last_status, events))
        # extinguish sequence
        for i in range(6):
            t = 20.6 + i * 0.10
            events = det2.process([extinguish_armor()], alliance="Red", frame_luminance=0.4, frame_token=200 + i, frame_size=(1280, 720), now=t)
            timeline.append((t, "EXT", det2.last_status, events))
            if events:
                for ev in events:
                    window.accept_combat_event(ev)
                break
        for row in timeline:
            log(f"ui-kill t={row[0]:.2f} {row[1]} status={row[2]} events={len(row[3])}")
        # animate kill fx frames
        for i in range(8):
            window.frame_scheduler.force()
            window.update()
            app.processEvents()
            img = grab(f"03_kill_frame_{i:02d}.png")
            crop(img, 0.35, 0.45, 0.30, 0.40, f"03_kill_frame_{i:02d}_crop.png")
            time.sleep(0.12)

    def finish() -> None:
        (OUT / "AUDIT_LOG.txt").write_text("\n".join(LOG), encoding="utf-8")
        log(f"log written {OUT / 'AUDIT_LOG.txt'}")
        window.close()
        app.quit()

    def run() -> None:
        phase_hud()
        time.sleep(0.4)
        phase_clickgui()
        time.sleep(0.4)
        phase_kill_ui()
        time.sleep(0.3)
        finish()

    QTimer.singleShot(600, run)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
