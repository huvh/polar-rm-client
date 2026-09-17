"""Real OpenGL frontend captures. Synthetic display data, never match evidence.

Run on Windows without QT_QPA_PLATFORM=offscreen. Saves into tmp_*/ only.
Captures the live compositor, not a substitute QPainter mock of the HUD.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ["POLAR_DISABLE_LOCAL_CAPTURE"]="1"
os.environ["POLAR_DISABLE_MEDIA_PRELOAD"]="1"
DATA=TemporaryDirectory(prefix="polar_student_gl_")
os.environ["POLAR_USER_DATA_ROOT"]=DATA.name
if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage,QPixmap,QSurfaceFormat
from PySide6.QtWidgets import QApplication
from rm_client.ui.polar_app import PolarRMWindow
from rm_client.ui.polar.primitives import EconomyScenePhase


def main():
    if os.environ.get("QT_QPA_PLATFORM")=="offscreen":
        raise RuntimeError("real Windows OpenGL is required")
    surface=QSurfaceFormat();surface.setVersion(3,3);surface.setProfile(QSurfaceFormat.CoreProfile)
    surface.setSwapInterval(0);QSurfaceFormat.setDefaultFormat(surface)
    app=QApplication([]);w=PolarRMWindow();w.timer.stop();w.auto_save_config=lambda:None
    w.state.mock_simulation_enabled=False;w.home_visible=False;w.startup_step="done"
    w.registry.get("CameraFeed").get_setting("Source").value="Synthetic"
    w.registry.get("HUD").get_setting("Combat Preset").value="Minecraft"
    w.registry.get("ArmorAutoAim").get_setting("Draw Fov").value=False
    w.hover_point=QPointF(-100,-100)
    bg=QImage(1280,720,QImage.Format_ARGB32);bg.fill("#273b4a")
    w.frame_image=bg;w.frame_pixmap=QPixmap.fromImage(bg);w._last_capture_sequence+=1
    w.state.injury_stats={101:{"total_damage":280,"small_projectile_damage":160,"large_projectile_damage":100,"collision_damage":20}}
    w.state.rune_status={"average_rings":8.5,"activated_arms":4}
    w.state.dart_status={"target_id":1,"open":2}
    w.state.buffs=[{"robot_id":w.state.robot_id,"buff_type":3,"buff_level":2,"buff_left_time":28},
                   {"robot_id":w.state.robot_id,"buff_type":2,"buff_level":-2,"buff_left_time":12}]
    w.registry.get("ArmorStatus").enabled=True;w.state.robot_module_status={"armor":1}
    w.match_chat.add("§6§lDOUBLE KILL! §r§e双杀 · 机器人 1",source="referee")
    w.match_chat.add("§c[裁判] §e黄牌警告 · 累计 1",source="referee")
    out=ROOT/"tmp_student_frontend"/"opengl";out.mkdir(parents=True,exist_ok=True)
    captures=[]
    def grab(name):
        for _ in range(15):
            w._ui_frame_index+=1;w.frame_dt=1/60
            payload=w.dynamic_island_payload()
            w.dynamic_island_state.set_content_target(1.0 if payload["active"] else 0.0,
                0.30 if payload["kind"]=="module" else (0.80 if payload["active"] else 0.22))
            w.dynamic_island_state.update(1/60)
            w.frame_scheduler.force();w.update();app.processEvents()
        im=w.grabFramebuffer()
        assert not im.isNull() and w.gpu_compositor.available,"live GPU compositor failed"
        assert not w.gpu_compositor.last_error,w.gpu_compositor.last_error
        im.save(str(out/f"{name}.png"));captures.append({"name":name,"width":im.width(),"height":im.height(),"dpr":w.devicePixelRatioF()})
        print(f"[GL PASS] {name} {im.width()}x{im.height()}",flush=True)
    try:
        w.resize(1280,720);w.show();app.processEvents()
        # Allow the actual ActiveMods introduction to settle before freezing
        # the HUD backdrop in a modal. Stopped timers otherwise capture every
        # initial zero-height row at the same y (not a live UI layout).
        for _ in range(20):
            w._ui_frame_index+=1;w.frame_dt=1/60
            w.invalidate_transient_overlay_scene()
            w.frame_scheduler.force();w.update();app.processEvents()
        for width,height in ((1280,720),(1600,900),(1920,1080),(2560,1440)):
            w.resize(width,height);app.processEvents()
            for panel in ("inventory","damage","settlement","darts","skills"):
                w.open_student_panel(panel);w.student_ui.progress=1;grab(f"{width}x{height}_{panel}")
            w.close_student_panel(immediate=True);grab(f"{width}x{height}_hud")
        w.resize(1600,900);w.open_student_panel("reload");w.economy_island.progress=1;w.economy_island.target=1
        w.economy_phase=EconomyScenePhase.OPEN;grab("reload_existing_economy")
        # Full restore/present regression with the new ammo detail extension.
        for _ in range(100):
            w.open_economy_workspace("ammo");w.economy_island.progress=1;w.economy_phase=EconomyScenePhase.OPEN
            w.close_economy_workspace(play_sound=False);w.economy_island.progress=0
            w._economy_restore_pending_generation=w._economy_generation
            for _ in range(3):w.frame_scheduler.force();w.update();app.processEvents()
            assert w.economy_phase==EconomyScenePhase.CLOSED,"economy restore did not present"
            assert w.overlay_coordinator.modal is None,"economy left modal locked"
        grab("after_100_economy_restores")
        (out/"report.json").write_text(json.dumps({"captures":captures,"economy_cycles":100,"match_evidence":False},indent=2),encoding="utf-8")
    finally:w.close()
    return 0

if __name__=="__main__":raise SystemExit(main())
