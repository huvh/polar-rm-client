"""Offline composition of the real RM CS controller and BF6 progress renderer.

Island/map/module-list are explicitly labeled layout fixtures. No client,
OpenGL context, audio, backend, camera, socket, or hardware is started.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qt5-compat-preview", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp_rm_top_hud")
    args = parser.parse_args()
    if args.qt5_compat_preview:
        import PyQt5
        from PyQt5 import QtCore, QtGui, QtWidgets
        for key, value in (("PySide6", PyQt5), ("PySide6.QtCore", QtCore), ("PySide6.QtGui", QtGui)):
            sys.modules[key] = value
        binding = "Qt5 / PyQt5 compatibility preview; Qt6/PySide6 NOT verified"
    else:
        from PySide6 import QtCore, QtGui, QtWidgets
        binding = "Qt6 / PySide6 offscreen component preview"
    from rm_client.model import build_default_registry
    from rm_client.ui.top_match_bar_controller import TopMatchBarController
    from tools.topbar_preview_support import load_progress_renderer
    Progress = load_progress_renderer(QtCore, QtGui)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    args.output.mkdir(parents=True, exist_ok=True)

    def host():
        registry = build_default_registry()
        mqtt = NS(host="offline.synthetic", port=3333, disconnected_at=0.0,
                  connected=True, receive_generation=1)
        owner = NS(registry=registry,
                   state=NS(match_mode="RMUC7v7", alliance_color="Blue", robot_id=103),
                   backend=NS(mqtt=mqtt, scenario_key="OfficialEvent", referee=NS(profile_id="rm2026-v1.3.1")),
                   home_visible=False, hero_deploy_ui=NS(active=False), overlay_coordinator=NS(modal=None),
                   dynamic_island_state=NS(y=17.0, height=30.0),
                   minecraft_hud_active=lambda: False, menu_overlay_active=lambda: False,
                   tactical_map_rect=lambda w, h: QtCore.QRectF(12, 58, 220, 156),
                   setting_bool=lambda mod, key, default=False: bool(mod.get_setting(key).value) if mod and mod.get_setting(key) else default,
                   setting_mode=lambda mod, key, default: str(mod.get_setting(key).value) if mod and mod.get_setting(key) else default,
                   kill_fx=NS(match_progress=Progress()))
        return owner, TopMatchBarController(owner)

    def observe(controller, short=False):
        controller.observe_referee("GameStatus", {"current_round": 1, "stage_countdown_sec": 185,
                                                 "red_score": 1, "blue_score": 2, "current_stage": 4,
                                                 "__present__": (1, 3, 4, 5, 6)}, 10)
        hp = [150, 250, 180, 0, 400]
        if not short:
            hp += [0, 250, 90, 150, 400]
        controller.observe_referee("GlobalUnitStatus", {"robot_health": hp, "base_health": 4200,
                                                       "enemy_base_health": 2750,
                                                       "__present__": (1, 6, 11)}, 10)
        controller.observe_referee("RobotStaticStatus", {"robot_id": 103, "max_health": 400,
                                                        "__present__": (4, 9)}, 10)
        controller.observe_referee("RobotDynamicStatus", {"current_health": 180,
                                                         "__present__": (1,)}, 10)

    def label(p, rect, text, size=12, color="#d4dce0", align=None):
        f = QtGui.QFont("DejaVu Sans")
        f.setPixelSize(size)
        p.setFont(f)
        p.setPen(QtGui.QColor(color))
        p.drawText(rect, align or (QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter), text)

    images, records = [], []
    cases = [("rmuc-live-1920", 1920, 1080, "full"),
             ("rmuc-live-1280", 1280, 720, "full"),
             ("rmuc-partial-1280", 1280, 720, "partial"),
             ("rmuc-disconnected-1280", 1280, 720, "disconnected")]
    for name, width, height, kind in cases:
        owner, controller = host()
        observe(controller, short=kind == "partial")
        if kind == "disconnected":
            owner.backend.mqtt.connected = False
            owner.backend.mqtt.receive_generation += 1
        image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtGui.QColor("#151a20"))
        p = QtGui.QPainter(image)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # Neutral spatial background; never presented as a camera/live frame.
        gradient = QtGui.QLinearGradient(0, 0, width, height)
        gradient.setColorAt(0, QtGui.QColor("#2b313a"))
        gradient.setColorAt(.65, QtGui.QColor("#151e26"))
        gradient.setColorAt(1, QtGui.QColor("#303a3f"))
        p.fillRect(image.rect(), gradient)
        p.setPen(QtGui.QPen(QtGui.QColor(200, 220, 230, 12), 1))
        for x in range(0, width, 80):
            p.drawLine(x, 260, x, height)
        for y in range(260, height, 80):
            p.drawLine(0, y, width, y)
        label(p, QtCore.QRectF(18, 8, 235, 24), "POLAR-RM", 20, "#f0f4f7")
        label(p, QtCore.QRectF(18, 34, 245, 17), "RMUC 7v7 / 2026  •  SYNTHETIC", 10)
        map_rect = owner.tactical_map_rect(width, height)
        p.fillRect(map_rect, QtGui.QColor(6, 12, 17, 190))
        map_image = QtGui.QImage(str(ROOT / "assets/maps/rmuc_7v7_official.png"))
        if not map_image.isNull():
            p.setOpacity(.60)
            p.drawImage(map_rect.adjusted(6, 6, -6, -24), map_image)
            p.setOpacity(1)
        label(p, QtCore.QRectF(20, 190, 210, 20), "MAP LAYOUT FIXTURE", 10)
        island = QtCore.QRectF(width / 2 - 235, 17, 470, 30)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 35), 1))
        p.setBrush(QtGui.QColor(6, 9, 12, 210))
        p.drawRoundedRect(island, 15, 15)
        label(p, island, "POLAR-RM    •    Island layout fixture", 11, align=QtCore.Qt.AlignCenter)
        for i, name_text in enumerate(("HUD", "CS / RM TOP MATCH", "TACTICAL MAP", "BASE / OUTPOST")):
            label(p, QtCore.QRectF(width - 246, 12 + i * 24, 226, 22), name_text, 11,
                  "#afbad1", QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        # The same monotonic timestamp and repeated paint calls settle existing
        # BF6 damping without changing the authoritative synthetic observations.
        for step in range(180):
            controller.paint(p, width, height, 10 + step / 120)
        p.end()
        if controller._last_error:
            raise RuntimeError(controller._last_error)
        # Repaint once onto a clean copy: repeated compositing above would make
        # translucent portraits opaque. Context is redrawn by restoring its
        # captured background before actual final pixels are evaluated.
        # Generate a pristine context by masking the reserved center corridor.
        p = QtGui.QPainter(image)
        p.fillRect(QtCore.QRectF(270, 54, width - 540, 185), gradient)
        controller.paint(p, width, height, 11.5)
        label(p, QtCore.QRectF(24, height - 136, width - 48, 24),
              "CS VEHICLE HUD + EXISTING BF6 BASE-LOSS BARS", 17, "#ecf1f3")
        label(p, QtCore.QRectF(24, height - 105, width - 48, 20),
              "6 vehicle roles • ground HP/life from referee • UAV has no HP • DART/RADAR are separate systems", 12)
        label(p, QtCore.QRectF(24, height - 81, width - 48, 20),
              "Only local 103 has an observed max HP. Remote HP is numeric; an unknown denominator never becomes a filled HP bar.", 11)
        label(p, QtCore.QRectF(24, height - 55, width - 48, 20), binding, 11, "#e8c88a")
        label(p, QtCore.QRectF(24, height - 32, width - 48, 20),
              "Offline QPainter composition / synthetic telemetry / context fixtures / NOT a full-app or GPU screenshot", 11, "#e8c88a")
        p.end()
        path = args.output / f"{name}.png"
        if not image.save(str(path)):
            raise RuntimeError("PNG save failed")
        crop = image.copy(0, 0, width, 255)
        crop.save(str(args.output / f"{name}-top.png"))
        images.append(crop.scaledToWidth(1280, QtCore.Qt.SmoothTransformation))
        frame = controller.feed.snapshot(11.5)
        records.append({"file": path.name, "viewport": [width, height], "fixture": kind,
                        "left_ids": [c.robot_id for c in frame.left.cards],
                        "right_ids": [c.robot_id for c in frame.right.cards],
                        "support_ids": [c.robot_id for c in frame.left.systems + frame.right.systems],
                        "local_hp": next((c.health_text for c in frame.left.cards if c.local), None),
                        "base_hp": [frame.own_base_health, frame.enemy_base_health]})
    sheet = QtGui.QImage(1280, sum(im.height() + 30 for im in images), QtGui.QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QtGui.QColor("#141b22"))
    p = QtGui.QPainter(sheet)
    y = 0
    for record, image in zip(records, images):
        label(p, QtCore.QRectF(14, y, 1250, 30), record["file"] + "  /  SYNTHETIC OFFLINE COMPONENT PREVIEW", 11)
        p.drawImage(0, y + 30, image)
        y += image.height() + 30
    p.end()
    sheet.save(str(args.output / "rmuc-top-hud-contact-sheet.png"))
    manifest = {"binding": binding, "qt_version": QtCore.qVersion(), "full_app_verified": False,
                "real_gpu_verified": False, "hardware_or_network_started": False,
                "production_renderers": ["TopMatchBarController", "TopMatchBarRenderer", "MatchProgressRenderer"],
                "bf6_class_loading": "actual AST definitions from production kill_fx.py; no copied draw implementation",
                "kill_fx_sha256": hashlib.sha256((ROOT / "rm_client/kill_fx.py").read_bytes()).hexdigest(),
                "telemetry": "explicitly synthetic, no inferred enemy maximum HP", "outputs": records}
    (args.output / "rmuc-preview-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
