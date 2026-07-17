from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.ui.polar_app import PolarRMWindow


VISUALS = ("Classic", "Clear", "Enhanced")
RESOLUTIONS = ((1920, 1080), (2560, 1440), (3840, 2160))
SCENARIOS = {
    "full_cool": (1.0, 0.0, 1.0, "idle", False),
    "health_drop": (0.55, 0.18, 0.82, "tracking", False),
    "continuous_fire": (0.82, 0.88, 0.46, "tracking", False),
    "health_zero": (0.0, 0.34, 0.20, "idle", False),
    "cooling": (0.72, 0.35, 0.62, "locked", True),
}


def render(window: PolarRMWindow, visual: str, scenario: str, width: int, height: int, output: Path) -> None:
    health_ratio, heat_ratio, ammo_ratio, tracking, locked = SCENARIOS[scenario]
    module = window.registry.get("CombatTargetHUD")
    module.get_setting("Visual").value = visual
    state = window.state
    state.current_health = round(state.max_health * health_ratio)
    state.current_heat = state.max_heat * heat_ratio
    state.remaining_ammo = round(state.ammo_capacity * ammo_ratio)
    state.vision_tracking_state = tracking
    state.vision_detection_count = 1 if tracking in ("tracking", "locked") else 0
    state.target_locked = locked

    window.combat_hud_animator.reset(state)
    if visual == "Enhanced" and scenario in ("health_drop", "cooling"):
        frame = window.combat_hud_animator.frame
        frame.self_ghost = 100.0
        frame.heat_ghost = 95.0
        frame.ammo_ghost = 100.0
        for _ in range(8):
            window.combat_hud_animator.update(state, 1.0 / 144.0, visual)

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#111827"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    hud_scale = window.get_hud_scale(width, height)
    painter.scale(hud_scale, hud_scale)
    window.draw_combat_target_hud(
        painter,
        max(1, int(width / hud_scale)),
        max(1, int(height / hud_scale)),
        module,
    )
    painter.end()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output), "PNG"):
        raise RuntimeError(f"无法写入基线图：{output}")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    output_root = ROOT / "tests" / "baselines" / "combat_target_hud"
    try:
        for visual in VISUALS:
            for scenario in SCENARIOS:
                render(window, visual, scenario, 1920, 1080, output_root / f"1080p_{visual.lower()}_{scenario}.png")
            for width, height in RESOLUTIONS[1:]:
                label = "2k" if width == 2560 else "4k"
                render(window, visual, "continuous_fire", width, height, output_root / f"{label}_{visual.lower()}_continuous_fire.png")
    finally:
        window.close()
    app.processEvents()
    print(f"TargetHUD 基线已生成：{output_root}")


if __name__ == "__main__":
    main()
