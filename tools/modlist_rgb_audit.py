"""Raster ModuleList styles (DebugWhite + RGB modes) for visual check.

Run:
  .\\.venv\\Scripts\\python.exe tools\\modlist_rgb_audit.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from rm_client.model import MODULE_LIST_STYLES
from rm_client.ui.polar_app import PolarRMWindow
from rm_client.ui.paint import rainbow_color_index


OUT = ROOT / "tmp_render_checks" / "audit"
OUT.mkdir(parents=True, exist_ok=True)


def make_bg(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0.0, QColor("#2a6a9a"))
    grad.setColorAt(0.45, QColor("#2f7a5a"))
    grad.setColorAt(1.0, QColor("#1a3a28"))
    p.fillRect(0, 0, w, h, grad)
    p.end()
    return img


def enable_many(window: PolarRMWindow) -> None:
    keep_off = {"ClickGui", "HUD"}
    for module in window.registry.modules:
        if module.name in keep_off:
            continue
        # Enable a dense list so ArrayList width-sort is visible.
        if module.category in ("Combat", "Render", "Player", "Movement", "Misc", "Client"):
            module.enabled = True
        if module.name in (
            "ArmorAutoAim",
            "Armor3DESP",
            "CombatTargetHUD",
            "ChassisGimbalIndicator",
            "Crosshair",
            "MatchTimer",
            "SpeedLimit",
            "PowerLimit",
            "BuffStatus",
            "SpinMode",
            "CameraFeed",
            "GimbalPower",
            "RobotOverlay",
            "EliminationFX",
            "ThermalPowerPanel",
        ):
            module.enabled = True


def render_style(window: PolarRMWindow, style: str, w: int = 1280, h: int = 720) -> QImage:
    hud = window.registry.get("HUD")
    if hud and hud.get_setting("ModuleList Style"):
        hud.get_setting("ModuleList Style").value = style
    if hud and hud.get_setting("Right Display"):
        hud.get_setting("Right Display").value = "ModuleListHud"
    if hud and hud.get_setting("Module List"):
        hud.get_setting("Module List").value = True
    # Advance enter animations so rows settle to full alpha/height.
    t0 = time.perf_counter()
    for step in range(24):
        window.anim.begin_frame(t0 + step * (1.0 / 60.0))
        probe = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
        pp = QPainter(probe)
        window.draw_module_list_hud(pp, 320, 180)
        pp.end()

    bg = make_bg(w, h)
    p = QPainter(bg)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    # Match production: logical HUD under scale transform.
    scale = window.get_hud_scale(w, h)
    logical_w = max(1, int(w / scale))
    logical_h = max(1, int(h / scale))
    window.anim.begin_frame(time.perf_counter())
    p.scale(scale, scale)
    window.draw_module_list_hud(p, logical_w, logical_h)
    p.end()
    return bg


def main() -> int:
    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(surface)

    app = QApplication(sys.argv)
    window = PolarRMWindow()
    window.resize(1280, 720)
    window.home_visible = False
    enable_many(window)

    # Prove rainbow helper is animated / stepped.
    samples = [rainbow_color_index(i, 10, 8).name() for i in range(6)]
    print("rainbow samples:", samples)

    styles = [
        "DebugWhiteList",
        "PolarRainbowRight",
        "PolarTextList",
        "GlowRows",
        "LiquidArrayList",
        "StatusBars",
        "RobotCards",
    ]
    for style in styles:
        if style not in MODULE_LIST_STYLES:
            print("skip missing", style)
            continue
        # Two frames a bit apart to show RGB motion for animated styles.
        img0 = render_style(window, style)
        path0 = OUT / f"modlist_{style}_t0.png"
        img0.save(str(path0), "PNG")
        print("saved", path0.name, img0.width(), "x", img0.height())
        # Crop right strip for readability.
        crop = img0.copy(img0.width() - 360, 0, 360, min(520, img0.height()))
        crop_path = OUT / f"modlist_{style}_t0_crop.png"
        crop.save(str(crop_path), "PNG")
        print("saved", crop_path.name)

        time.sleep(0.35)
        img1 = render_style(window, style)
        crop1 = img1.copy(img1.width() - 360, 0, 360, min(520, img1.height()))
        crop1.save(str(OUT / f"modlist_{style}_t1_crop.png"), "PNG")

    # Left crop for PolarTextList
    left = render_style(window, "PolarTextList")
    left_crop = left.copy(0, 0, 320, min(420, left.height()))
    left_crop.save(str(OUT / "modlist_PolarTextList_left_crop.png"), "PNG")
    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
