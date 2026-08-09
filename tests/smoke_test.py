import os
from pathlib import Path
import socket
import threading
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.config_store import ClientConfigStore, apply_registry_config, export_client_config
from rm_client.combat_events import CombatEvent, OfficialMatchFeed, VisionKillDetector
from rm_client.combat_hud import (
    CombatHudAnimator,
    aim_target,
    approach_bar,
    approach_jar,
    ghost_follow,
    meter_settled,
    stage_drop_pct,
    HEAT_PER_SHOT,
    MockHeatStageSimulator,
    ring_end,
)
from rm_client.kill_fx import KillFxLayout, KillFxRenderer, PRESET_ELEMENTS, VALORANT_STYLES
from rm_client.match_chat import ChatEventAdapter, MatchChatController
from rm_client.match_modes import MATCH_MODES, MatchModeManager
from rm_client.model import GUI_MODES, HUD_MODES, MODULE_LIST_RENDERER_KEYS, MODULE_LIST_STYLES, TACTICAL_MAP_STATUS_DISPLAYS, RobotState, build_default_registry
from rm_client.economy import (
    EconomyCommandBridge,
    available_actions,
    encode_air_support_command,
    encode_common_command,
)
from rm_client.robot_profiles import apply_profile_to_state, profile_by_key, profiles_for_match, resolve_performance
from rm_client.protocol import RefereeFrameCodec
from rm_client.scenarios import ScenarioManager
from rm_client.startup_wallpaper import PkgVirtualFileSystem, StartupWallpaperManager
from rm_client.transports import FrameAssembler, OfficialMqttBridge, SerialBridgeStub, UDPVideoReceiver, VideoPipeline
from rm_client.tongji_bridge import DEFAULT_PORT, TongjiVisionReceiver, build_tongji_packet
from rm_client.ui_audio import UiAudioManager
from rm_client.ui.animation import (
    AnimationBank,
    Easings,
    GuiMotionController,
    GuiTransitionTimeline,
    IslandContainerState,
    MapIslandState,
    ReversibleExpoTimeline,
)
from rm_client.ui.gui_cache import ClickGuiLayerCache
from rm_client.ui.gpu_frame_compositor import compose_combined_backdrop_pixel
from rm_client.ui.clickgui_gpu import SmallTextPolicy
from rm_client.ui.island_icon_gpu import island_icon_coverage
from rm_client.ui.layout import HudAnchorStack
from rm_client.ui.overlay_coordinator import OverlayCoordinator, OverlayKind
from rm_client.ui.quick_action_wheel import DEFAULT_ACTIONS, QuickActionWheelState
from rm_client.ui.economy_workspace import EconomyIslandState, EconomyWorkspaceLayer, adaptive_backdrop_dim
from rm_client.ui.startup_gl import TextureOrigin, normalize_image_for_texture
from rm_client.ui.vision_motion import (
    AngleRenderTrack,
    ScalarRenderTrack,
    TargetHudPresenceState,
    VisionRenderInterpolator,
)
from rm_client.vision import ArmorObservation, VisionLossEvidence, VisionResult, PACKET_FRAME, PACKET_HEADER, PACKET_RESULT, PROTOCOL_MAGIC, PROTOCOL_VERSION, TongjiVisionBridge


def test_registry() -> None:
    registry = build_default_registry()
    click_gui = registry.get("ClickGui")
    assert click_gui is not None
    mode = click_gui.get_setting("Mode")
    assert mode is not None
    assert mode.options == GUI_MODES
    assert click_gui.get_setting("Render Backend").options == ["Unified GPU", "Compatibility Painter"]
    assert click_gui.get_setting("Render Backend").value == "Unified GPU"
    assert registry.get("ArmorAutoAim") is not None
    assert registry.get("EnergyAutoAim") is not None
    assert registry.get("ArmorAutoAim").get_setting("Lock Style") is not None
    assert registry.get("EnergyAutoAim").get_setting("Rune Type") is not None
    assert registry.get("EnergyAutoAim").get_setting("Lock Style") is not None
    assert registry.get("SpinMode") is not None
    assert registry.get("RobotOverlay") is not None
    direction_indicator = registry.get("ChassisGimbalIndicator")
    assert direction_indicator is not None
    assert direction_indicator.enabled is True
    assert direction_indicator.get_setting("Style").options == ["Minimal", "Tank", "Compass"]
    assert direction_indicator.get_setting("Show Angle") is not None
    assert direction_indicator.get_setting("Show Mode") is not None
    assert direction_indicator.get_setting("Size") is not None
    assert direction_indicator.get_setting("Size").value == 56
    assert direction_indicator.get_setting("Smooth") is not None
    combat_target_hud = registry.get("CombatTargetHUD")
    assert combat_target_hud is not None and combat_target_hud.enabled is True
    assert combat_target_hud.category == "Render"
    assert combat_target_hud.get_setting("Visual").value == "Clear"
    assert combat_target_hud.get_setting("Visual").options == ["Classic", "Clear", "Enhanced"]
    assert combat_target_hud.get_setting("Show Bars").value is False
    assert combat_target_hud.get_setting("Show Status Line").value is True
    ui_scale = registry.get("UIScale")
    assert ui_scale is not None
    assert ui_scale.get_setting("Auto Scale") is not None
    assert ui_scale.get_setting("High Res Optimize") is not None
    assert ui_scale.get_setting("HUD Scale") is not None
    assert ui_scale.get_setting("GUI Scale") is not None
    assert ui_scale.get_setting("Animation Speed") is not None
    assert all(hasattr(module, "keybind") for module in registry.modules)
    scenario = registry.get("Scenario")
    assert scenario is not None
    assert scenario.get_setting("Mode").value == "LabDebug"
    assert scenario.get_setting("Startup Style").options == ["LiquidMenu", "PolarLauncher"]
    assert scenario.get_setting("Startup Style").value == "LiquidMenu"
    startup_visual = registry.get("StartupVisual")
    assert startup_visual is not None
    assert startup_visual.enabled is True
    assert startup_visual.get_setting("Background Mode").options == ["PkgScene", "VideoParallax", "ParticleGrid", "Static"]
    assert startup_visual.get_setting("Background Mode").value == "VideoParallax"
    assert startup_visual.get_setting("Wallpaper Profile").value == "TexasMP4"
    assert startup_visual.get_setting("Wallpaper Profile").options == ["TexasMP4", "VendingMachine4K", "Default3000925581Pkg", "ParticleGrid"]
    assert startup_visual.get_setting("Motion Quality").options == ["Smooth60", "Balanced30", "Source"]
    assert startup_visual.get_setting("Motion Quality").value == "Smooth60"
    assert startup_visual.get_setting("Glass Style").options == ["LiquidGlass", "Legacy"]
    assert startup_visual.get_setting("Glass Style").value == "LiquidGlass"
    assert startup_visual.get_setting("Glass Strength").value == 1.0
    assert startup_visual.get_setting("Import Wallpaper").kind == "action"
    assert startup_visual.get_setting("Reset Wallpaper").kind == "action"
    match_mode = registry.get("MatchMode")
    assert match_mode is not None
    assert match_mode.get_setting("Mode").value == "RMUC7v7"
    assert match_mode.get_setting("Alliance") is not None
    alliance = registry.get("AllianceProfile")
    assert alliance is not None
    assert alliance.get_setting("Side").value == "Red"
    tactical_map = registry.get("TacticalMap")
    assert tactical_map is not None
    assert tactical_map.keybind == "Tab"
    assert tactical_map.get_setting("Map Size") is not None
    assert tactical_map.get_setting("Chrome").options == ["Minimal", "Thin", "Full"]
    assert tactical_map.get_setting("Status Display").options == TACTICAL_MAP_STATUS_DISPLAYS
    assert tactical_map.get_setting("Status Display").value == "LiquidAuto"
    assert tactical_map.get_setting("Palette").options == ["RM Tactical", "Liquid Neutral"]
    for display in ("LiquidAuto", "LiquidBars", "LiquidCards"):
        assert display in TACTICAL_MAP_STATUS_DISPLAYS
    assert tactical_map.get_setting("Official Map") is not None
    hud = registry.get("HUD")
    assert hud is not None
    assert hud.get_setting("Restore Compact HUD").kind == "action"
    liquid_map = registry.get("LiquidTacticalMap")
    assert liquid_map is not None
    assert liquid_map.enabled is True
    assert liquid_map.get_setting("Pointer Style").options == ["Triangle", "Wedge", "Dot"]
    assert liquid_map.get_setting("Entity Color").options == ["Team", "Distance", "Health"]
    assert liquid_map.get_setting("Show Labels") is not None
    assert liquid_map.get_setting("Show Values") is not None
    assert liquid_map.get_setting("Dock Animation").options == ["Fly", "Flip", "Fade"]
    tongji = registry.get("TongjiVisionBridge")
    assert tongji is not None and tongji.enabled is True
    assert tongji.get_setting("Vision Source").options == ["Local", "Tongji", "Auto", "Mock"]
    assert tongji.get_setting("Vision Kill Sensitivity").options == ["Lab Responsive", "Balanced", "Match Reliable"]
    assert tongji.get_setting("Vision Kill Sensitivity").value == "Lab Responsive"
    assert tongji.get_setting("UDP Port").value == DEFAULT_PORT
    assert tongji.get_setting("Local Device").options == ["AUTO", "GPU", "CPU"]
    assert registry.get("CameraCalibration").get_setting("Capture Chessboard").kind == "action"
    armor_esp = registry.get("Armor3DESP")
    assert armor_esp is not None
    assert armor_esp.get_setting("Style").value == "PolarMechanicalWire"
    assert armor_esp.get_setting("Style").options == ["PolarMechanicalWire", "Wireframe3D", "PolarOutline2D", "Prediction Rack"]
    assert armor_esp.get_setting("Prediction Labels").value is False
    assert armor_esp.get_setting("Renderer").options == ["GPU Auto", "CPU"]
    config_manager = registry.get("ConfigManager")
    assert config_manager is not None
    assert config_manager.get_setting("Profile").value == "default"
    assert config_manager.get_setting("Save Current").kind == "action"
    kill_fx = registry.get("EliminationFX")
    assert kill_fx is not None and kill_fx.enabled is True
    assert kill_fx.get_setting("Preset").value == "Default Scrolling"
    assert "Valorant Prime" in kill_fx.get_setting("Preset").options
    assert "Valorant RGX V3" in kill_fx.get_setting("Preset").options
    assert kill_fx.get_setting("Element Visibility").options == ["Preset", "Full HUD", "Icons Only"]
    assert kill_fx.get_setting("Anchor Policy").options == ["Combat Focus", "Original Bottom", "Manual"]
    assert kill_fx.get_setting("Anchor Policy").value == "Combat Focus"
    assert kill_fx.get_setting("Responsive Scale").options == ["Auto", "Fixed"]
    assert kill_fx.get_setting("Scale").max_value == 2.0
    assert kill_fx.get_setting("Evidence Mode").value == "Auto"
    audio = registry.get("AudioFeedback")
    assert audio is not None and audio.enabled is True
    assert audio.get_setting("Enabled").value is True
    assert audio.get_setting("Module Toggle Sounds").value is True
    assert audio.get_setting("Sound Theme").value == "Polar UI"
    assert audio.get_setting("Sound Theme").options == ["Custom", "Polar UI", "Polar Classic", "LiquidBounce"]
    for name in ("Custom Enable Sound", "Custom Disable Sound", "Custom Invalid Sound"):
        assert audio.get_setting(name).value == "No Sound"
    for name in ("Import Enable Sound", "Import Disable Sound", "Import Invalid Sound"):
        assert audio.get_setting(name).kind == "action"
    assert audio.get_setting("UI Volume").value == 45


def test_audio_feedback_and_kill_sound_mapping() -> None:
    sound_root = ROOT / "assets" / "ui_sounds" / "liquidbounce"
    for name in ("click-1.ogg", "click-2.ogg", "click-3.ogg"):
        assert (sound_root / name).stat().st_size > 0
    polar_root = ROOT / "assets" / "ui_sounds" / "polar_classic"
    for name in ("module_on.wav", "module_off.wav"):
        assert (polar_root / name).stat().st_size > 0
    polar_ui_root = ROOT / "assets" / "ui_sounds" / "polar_ui"
    for name in ("module_toggle.wav", "action_success.wav", "panel_transition.wav"):
        assert (polar_ui_root / name).stat().st_size > 0

    class FakePool:
        def __init__(self) -> None:
            self.played: list[tuple[str, float]] = []

        def play(self, name: str, volume: float) -> None:
            self.played.append((name, volume))

        def preload(self, _names) -> None:
            pass

    manager = object.__new__(UiAudioManager)
    manager.pool = FakePool()
    manager.root = ROOT / "assets" / "ui_sounds"
    manager.custom_dir = manager.root / "custom"
    manager.module_toggled(True, "config", active=True, volume=45)
    assert manager.pool.played == []
    manager.module_toggled(True, "clickgui", active=True, volume=45, theme="Custom")
    assert manager.pool.played == []
    manager.module_toggled(
        True, "clickgui", active=True, volume=45, theme="Custom",
        custom_sounds={"enable": "custom/enable.wav"},
    )
    assert manager.pool.played[-1] == ("custom/enable.wav", 45)
    manager.module_toggled(True, "clickgui", active=True, volume=45, theme="Polar Classic")
    manager.module_toggled(False, "keybind", active=True, volume=45, theme="Polar Classic")
    assert manager.pool.played[-2:] == [("polar_classic/module_on.wav", 45), ("polar_classic/module_off.wav", 45)]
    manager.preview("invalid", 30, theme="Polar Classic")
    assert manager.pool.played[-1] == ("polar_classic/module_off.wav", 18)
    manager.module_toggled(True, "clickgui", active=True, volume=45, theme="LiquidBounce")
    assert manager.pool.played[-1] == ("liquidbounce/click-2.ogg", 45)
    manager.module_toggled(False, "clickgui", active=True, volume=45, theme="Polar UI")
    assert manager.pool.played[-1] == ("polar_ui/module_toggle.wav", 45)
    manager.gui_feedback("expand", 45, "Polar UI")
    assert manager.pool.played[-1] == ("polar_ui/panel_transition.wav", 45)
    with TemporaryDirectory() as temp:
        source = Path(temp) / "my-toggle.wav"
        source.write_bytes(b"RIFF-demo")
        manager.root = Path(temp) / "sounds"
        manager.custom_dir = manager.root / "custom"
        manager.custom_dir.mkdir(parents=True)
        imported = manager.import_custom_sound(source, "disable")
        assert imported.startswith("custom/disable-my-toggle")
        assert (manager.root / imported).is_file()

    registry = build_default_registry()
    toggles: list[tuple[str, bool, str]] = []
    registry.add_toggle_listener(lambda module, enabled, source: toggles.append((module.name, enabled, source)))
    target = registry.get("SpeedLimit")
    assert target is not None
    registry.toggle_module(target, source="clickgui")
    assert toggles == [("SpeedLimit", target.enabled, "clickgui")]

    renderer = KillFxRenderer(ROOT / "assets" / "kill_fx" / "gd656")
    assert renderer._sound_name("NORMAL", 1, "Default Scrolling") == "killsound_df.ogg"
    assert renderer._sound_name("HEADSHOT", 1, "Battlefield 1") == "headshotkillsound_bf1.ogg"
    assert renderer._sound_name("NORMAL", 6, "Combo") == "combokillsound_6_cf.ogg"
    assert (renderer.sound_root / renderer._sound_name("NORMAL", 1, "Valorant Prime")).exists()


def test_gui_motion_reversal_and_layer_cache() -> None:
    bank = AnimationBank()
    motion = GuiMotionController(bank)
    motion.begin_frame(1.0)
    assert motion.value("reverse", 1.0, 0.30, Easings.ease_out_expo, initial=0.0) == 0.0
    motion.begin_frame(1.12)
    forward = motion.value("reverse", 1.0, 0.30, Easings.ease_out_expo)
    assert 0.0 < forward < 1.0
    motion.begin_frame(1.12)
    reversed_at_start = motion.value("reverse", 0.0, 0.30, Easings.ease_out_expo)
    assert abs(reversed_at_start - forward) < 0.001
    motion.begin_frame(1.28)
    reversed_later = motion.value("reverse", 0.0, 0.30, Easings.ease_out_expo)
    assert 0.0 <= reversed_later < forward
    assert motion.waterfall(0.45, 2, 6) < motion.waterfall(0.45, 0, 6)

    # 慢帧跨过动画终点时必须直接落到目标，不能从旧值重新启动。
    motion.begin_frame(2.0)
    assert motion.value("dropped_frame", 1.0, 0.20, initial=0.0) == 0.0
    motion.begin_frame(2.35)
    assert motion.value("dropped_frame", 1.0, 0.20) == 1.0

    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    cache = ClickGuiLayerCache()
    target = QImage(320, 160, QImage.Format.Format_ARGB32_Premultiplied)
    target.fill(QColor(0, 0, 0, 0))
    painter = QPainter(target)
    builds = [0]

    def build(layer: QPainter, rect: QRectF) -> None:
        builds[0] += 1
        layer.fillRect(rect, QColor(40, 80, 120, 180))

    rect = QRectF(30, 20, 160, 90)
    cache.draw(painter, rect, ("smoke",), build)
    cache.draw(painter, rect, ("smoke",), build)
    painter.end()
    assert builds == [1]


def test_vision_render_interpolation_and_presence() -> None:
    def armor(x: float) -> ArmorObservation:
        return ArmorObservation(
            armor_id=3,
            label="three",
            color="blue",
            confidence=0.95,
            points=((x, 80.0), (x + 40.0, 80.0), (x + 40.0, 104.0), (x, 104.0)),
            distance_m=2.0,
            depth_m=2.0,
            plate_id=0,
            target_id=103,
        )

    interpolator = VisionRenderInterpolator(max_extrapolation=0.05)
    first = VisionResult(
        sequence=1,
        timestamp_ns=1,
        source_width=640,
        source_height=360,
        detections=(armor(100.0),),
        aim_armor=armor(100.0),
        tracking_state="tracking",
    )
    second = VisionResult(
        sequence=2,
        timestamp_ns=2,
        source_width=640,
        source_height=360,
        detections=(armor(160.0),),
        aim_armor=armor(160.0),
        tracking_state="tracking",
    )
    assert interpolator.push(first, source="local", received_at=10.0)
    assert interpolator.push(second, source="local", received_at=10.1)
    sampled = interpolator.sample(10.1)
    assert sampled is not None and sampled.aim_armor is not None
    assert 100.0 < sampled.aim_armor.points[0][0] < 160.0

    lost = VisionResult(
        sequence=3,
        timestamp_ns=3,
        source_width=640,
        source_height=360,
        tracking_state="lost",
    )
    interpolator.push(lost, source="local", received_at=10.2)
    hidden = interpolator.sample(10.2)
    assert hidden is not None and not hidden.detections and hidden.aim_armor is None

    presence = TargetHudPresenceState(hold_seconds=10.0, appear_seconds=0.18, fade_seconds=0.26)
    assert presence.update(0.0, False).phase == "Hidden"
    assert presence.update(0.0, True).phase == "Appearing"
    assert presence.update(0.2, True).phase == "Visible"
    assert presence.update(0.21, False).phase == "Grace10s"
    assert presence.update(10.20, False).phase == "Grace10s"
    assert presence.update(10.22, False).phase == "Fading"
    assert presence.update(10.50, False).phase == "Hidden"
    recovered = presence.update(10.51, True)
    assert recovered.phase == "Appearing" and recovered.opacity >= 0.0

    angle = AngleRenderTrack()
    assert angle.sample(0.0, 179.0) == 179.0
    wrapped = angle.sample(0.05, -179.0, response=20.0)
    assert abs(wrapped) > 170.0

    scalar = ScalarRenderTrack()
    assert scalar.sample(0.0, 0.0) == 0.0
    value = scalar.sample(0.05, 100.0, response=20.0)
    assert 0.0 < value < 100.0


def test_kill_fx_combat_focus_layout_and_migration() -> None:
    layout_1080 = KillFxLayout.create(
        1920, 1080, policy="Combat Focus", user_scale=1.0, responsive=True,
        device_pixel_ratio=1.0, x_offset=0, y_offset=0,
    )
    assert abs(layout_1080.anchor.x() - 960.0) < 0.01
    assert abs(layout_1080.anchor.y() - 799.2) < 0.01
    assert abs(layout_1080.scale - 1.0) < 0.01

    layout_2k = KillFxLayout.create(
        2560, 1440, policy="Combat Focus", user_scale=1.0, responsive=True,
        device_pixel_ratio=1.0, x_offset=0, y_offset=0,
    )
    assert abs(layout_2k.anchor.x() - 1280.0) < 0.01
    assert abs(layout_2k.anchor.y() - 1065.6) < 0.01
    assert 1.49 <= layout_2k.scale <= 1.51

    native_2048 = KillFxLayout.create(
        2048, 1152, policy="Combat Focus", user_scale=1.0, responsive=True,
        device_pixel_ratio=1.0, x_offset=0, y_offset=0,
    )
    assert 1.49 <= native_2048.scale <= 1.51

    scaled_desktop = KillFxLayout.create(
        2048, 1152, policy="Combat Focus", user_scale=1.0, responsive=True,
        device_pixel_ratio=1.25, x_offset=0, y_offset=0,
    )
    assert 1.49 <= scaled_desktop.scale <= 1.51

    registry = build_default_registry()
    apply_registry_config(registry, {
        "modules": {
            "EliminationFX": {
                "settings": {
                    "Anchor Policy": "Safe Area",
                    "X Offset": -275,
                    "Y Offset": -20,
                }
            }
        }
    })
    effect = registry.get("EliminationFX")
    assert effect.get_setting("Anchor Policy").value == "Combat Focus"
    assert effect.get_setting("Responsive Scale").value == "Auto"
    assert effect.get_setting("X Offset").value == 0
    assert effect.get_setting("Y Offset").value == 0


def test_kill_fx_assets_and_dual_evidence() -> None:
    assets = ROOT / "assets" / "kill_fx" / "gd656"
    assert (assets / "textures" / "killicon_card_default_t.png").exists()
    assert (assets / "sounds" / "killsound_df.ogg").exists()
    renderer = KillFxRenderer(assets)
    assert renderer.texture_root.exists()
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.8, light_state="lit", target_id=7)
    # 近距离反光可让像素采样仍偏亮；模型明确报 extinguish 时不应被阻塞。
    extinguish = ArmorObservation(103, "three", "extinguish", 0.94, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.88, light_state="extinguished", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0)
    # 亮灯记录已经超过两秒，仍应保留；重复消费同一视觉帧不能累计确认次数。
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.4, frame_token=2, now=3.2) == []
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.4, frame_token=2, now=3.5) == []
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.4, frame_token=3, now=3.6) == []
    event = detector.process([extinguish], alliance="Red", frame_luminance=0.4, frame_token=4, now=3.8)
    assert len(event) == 1 and event[0].source == "vision"
    assert event[0].detail == "vision_confirmed_lamp_off"
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.4, frame_token=5, now=3.9) == []
    assert detector.is_suppressed(extinguish) is True
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=6, now=4.0)
    assert detector.is_suppressed(extinguish) is False
    feed = OfficialMatchFeed()
    feed.consume("GameStatus", b"\x08\x01", alliance="Red", local_robot_id=3)
    assert feed.is_fresh() is True
    assert feed.is_kill_data_fresh() is False
    events, _updates = feed.consume("Event", b"\x08\x01", alliance="Red", local_robot_id=3)
    assert len(events) == 1 and events[0].source == "referee"
    assert feed.is_kill_data_fresh() is True


def test_vision_kill_miss_after_lit() -> None:
    """灯灭后框消失：曾亮灯 + 短时丢检应确认击杀。"""
    detector = VisionKillDetector()
    dark_loss = lambda sequence: VisionLossEvidence(7, "three", 0.10, 0.80, True, False, False, sequence)
    lit = ArmorObservation(103, "three", "blue", 0.92, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.8, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0)
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=2, loss_evidence=dark_loss(2), now=1.20) == []
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=2, now=1.25) == []  # 同帧不重复计 miss
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=3, loss_evidence=dark_loss(3), now=1.30) == []
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=4, loss_evidence=dark_loss(4), now=1.35) == []
    events = detector.process([], alliance="Red", frame_luminance=0.4, frame_token=5, loss_evidence=dark_loss(5), now=1.50)
    assert events == []
    assert detector.last_status == "LOSS_NEEDS_DIM_HISTORY"
    assert detector.is_suppressed(lit) is False


def test_vision_kill_same_empty_snapshot_never_times_out() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (108.0, 100.0), (108.0, 104.0), (100.0, 104.0)), light_strength=0.8, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0)
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=2, now=1.2) == []
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=2, now=1.8) == []
    assert detector.is_suppressed(lit) is False


def test_vision_kill_dark_loss_requires_prior_dimming() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (180.0, 100.0), (180.0, 140.0), (100.0, 140.0)), light_strength=0.8, light_state="lit", target_id=7)
    dim = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (180.0, 100.0), (180.0, 140.0), (100.0, 140.0)), light_strength=0.1, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0)
    assert detector.process([dim], alliance="Red", frame_luminance=0.4, frame_token=2, now=1.1) == []
    assert detector.process([dim], alliance="Red", frame_luminance=0.4, frame_token=3, now=1.2) == []
    for token, now in ((4, 1.3), (5, 1.4), (6, 1.5)):
        assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=token, loss_evidence=VisionLossEvidence(7, "three", 0.1, 0.8, True, False, False, token), now=now) == []
    events = detector.process([], alliance="Red", frame_luminance=0.4, frame_token=7, loss_evidence=VisionLossEvidence(7, "three", 0.1, 0.8, True, False, False, 7), now=1.65)
    assert len(events) == 1 and events[0].detail == "vision_confirmed_dark_loss_probe"


def test_vision_kill_bright_or_exiting_loss_never_eliminates() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((300.0, 120.0), (360.0, 120.0), (360.0, 150.0), (300.0, 150.0)), light_strength=0.8, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, frame_size=(640, 360), now=1.0)
    bright_exit = VisionLossEvidence(7, "three", 0.78, 0.80, False, True, False, 2)
    for token, now in ((2, 1.2), (3, 1.3), (4, 1.4), (5, 1.5)):
        assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=token, frame_size=(640, 360), loss_evidence=bright_exit, now=now) == []
    assert detector.last_status == "EXITING_BRIGHT"
    assert detector.is_suppressed(lit) is False


def test_vision_kill_external_missing_data_never_eliminates() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (180.0, 100.0), (180.0, 140.0), (100.0, 140.0)), light_strength=0.8, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0)
    for token, now in ((2, 1.2), (3, 1.3), (4, 1.4), (5, 1.5)):
        assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=token, now=now) == []
    assert detector.last_status == "LOSS_UNCERTAIN"


def test_vision_kill_exposure_hold_blocks_missing_path() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (108.0, 100.0), (108.0, 104.0), (100.0, 104.0)), light_strength=0.8, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.50, frame_token=1, now=0.80)
    for token, now in ((2, 1.00), (3, 1.05), (4, 1.10), (5, 1.15)):
        assert detector.process([], alliance="Red", frame_luminance=0.10, frame_token=token, now=now) == []
    assert detector.is_suppressed(lit) is False


def test_vision_kill_reliable_mode_rejects_missing_path() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (108.0, 100.0), (108.0, 104.0), (100.0, 104.0)), light_strength=0.8, light_state="lit", target_id=7)
    off = ArmorObservation(103, "three", "extinguish", 0.94, ((100.0, 100.0), (108.0, 100.0), (108.0, 104.0), (100.0, 104.0)), light_strength=0.7, light_state="extinguished", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0, sensitivity="Match Reliable")
    for token, now in ((2, 1.2), (3, 1.3), (4, 1.5), (5, 1.6)):
        assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=token, now=now, sensitivity="Match Reliable") == []
    assert detector.process([off], alliance="Red", frame_luminance=0.4, frame_token=6, now=1.7, sensitivity="Match Reliable") == []
    assert detector.process([off], alliance="Red", frame_luminance=0.4, frame_token=7, now=1.8, sensitivity="Match Reliable") == []
    events = detector.process([off], alliance="Red", frame_luminance=0.4, frame_token=8, now=2.0, sensitivity="Match Reliable")
    assert len(events) == 1 and events[0].detail == "vision_confirmed_lamp_off"


def test_vision_kill_dim_uses_target_baseline() -> None:
    detector = VisionKillDetector()
    dark_blue = ArmorObservation(103, "three", "blue", 0.92, ((100.0, 100.0), (108.0, 100.0), (108.0, 104.0), (100.0, 104.0)), light_strength=0.12, light_state="lit", target_id=7)
    for token, now in ((1, 1.0), (2, 1.2), (3, 1.4), (4, 1.6)):
        assert detector.process([dark_blue], alliance="Red", frame_luminance=0.4, frame_token=token, now=now) == []
    assert detector.is_suppressed(dark_blue) is False


def test_vision_kill_no_lit_history_no_miss() -> None:
    detector = VisionKillDetector()
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0) == []
    assert detector.process([], alliance="Red", frame_luminance=0.4, frame_token=2, now=1.5) == []


def test_vision_kill_exposure_pauses_not_clears() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.8, light_state="lit", target_id=7)
    extinguish = ArmorObservation(103, "three", "extinguish", 0.94, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.1, light_state="extinguished", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.50, frame_token=1, now=1.0)
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.50, frame_token=2, now=1.12) == []
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.50, frame_token=3, now=1.18) == []
    # 全局亮度突变：hold 期间暂停累计，但不应清零已有 frames
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.10, frame_token=4, now=1.22) == []
    assert detector.last_status == "EXPOSURE_HOLD"
    assert detector.process([extinguish], alliance="Red", frame_luminance=0.10, frame_token=5, now=1.28) == []
    # hold 结束后再累计一帧即可满 3 帧并确认
    events = detector.process([extinguish], alliance="Red", frame_luminance=0.10, frame_token=6, now=1.50)
    assert len(events) == 1 and events[0].detail == "vision_confirmed_lamp_off"


def test_vision_kill_dim_lamp() -> None:
    detector = VisionKillDetector()
    lit = ArmorObservation(103, "three", "blue", 0.92, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.8, light_state="lit", target_id=7)
    dim = ArmorObservation(103, "three", "blue", 0.90, ((1.0, 1.0), (8.0, 1.0), (8.0, 4.0), (1.0, 4.0)), light_strength=0.12, light_state="lit", target_id=7)
    detector.process([lit], alliance="Red", frame_luminance=0.4, frame_token=1, now=1.0)
    assert detector.process([dim], alliance="Red", frame_luminance=0.4, frame_token=2, now=1.10) == []
    assert detector.process([dim], alliance="Red", frame_luminance=0.4, frame_token=3, now=1.18) == []
    events = detector.process([dim], alliance="Red", frame_luminance=0.4, frame_token=4, now=1.35)
    assert len(events) == 1 and events[0].detail == "vision_confirmed_dim_lamp"


def test_local_target_identity_survives_extinguish() -> None:
    from rm_client.tongji_yolo import LocalDetection, LocalTargetSelector

    selector = LocalTargetSelector()
    lit = LocalDetection("three", "blue", 0.92, (100.0, 80.0, 60.0, 30.0), ((100.0, 80.0), (160.0, 80.0), (160.0, 110.0), (100.0, 110.0)), 0.8)
    extinguished = LocalDetection("three", "extinguish", 0.94, (102.0, 81.0, 60.0, 30.0), ((102.0, 81.0), (162.0, 81.0), (162.0, 111.0), (102.0, 111.0)), 0.12)
    first = selector.select([lit], 640, 360)
    assert selector.select([], 640, 360) is None
    assert selector.select([], 640, 360) is None
    second = selector.select([extinguished], 640, 360)
    assert first is not None and second is not None
    assert first[1] == second[1]

    # 超过延长后的关联窗才换新 track_id
    selector.last_seen_at -= 0.80
    replacement = selector.select([lit], 640, 360)
    assert replacement is not None and replacement[1] != second[1]


def test_gd656_renderer_presets() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    assets = ROOT / "assets" / "kill_fx" / "gd656"
    presets = list(PRESET_ELEMENTS) + [f"Valorant {name}" for name in VALORANT_STYLES]
    assert len(VALORANT_STYLES) == 26
    for preset in presets:
        renderer = KillFxRenderer(assets)
        event = CombatEvent(
            "elimination", "preview", True, 10.0,
            victim_id=103, kill_type="HEADSHOT", combo=5,
            victim_name="ROBOT 103", score_delta=100, tags=("ELIMINATION", "ARMOR HIT"),
        )
        renderer.trigger(event, combo_window=5.0, sound_enabled=False, volume=0, preset=preset, visibility="Full HUD", now_override=10.0)
        image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        renderer.draw(
            painter, 1280, 720, preset=preset, visibility="Full HUD", team="CT Blue",
            scale=1.0, anchor_policy="Original Position", x_offset=0.0, y_offset=0.0,
            now_override=10.18,
        )
        painter.end()
        assert any(bytes(image.constBits())), preset
    app.processEvents()


def test_wallpaper_pkg_index_reader() -> None:
    package = ROOT.parent / "3000925581" / "scene.pkg"
    if not package.exists():
        return
    vfs = PkgVirtualFileSystem(package)
    vfs.load_index()
    assert "scene.json" in vfs.entries
    assert len(vfs.entries) > 20
    scene_text = vfs.read_text("scene.json")
    assert '"objects"' in scene_text


def test_wallpaper_profiles_and_user_import() -> None:
    with TemporaryDirectory() as temp:
        workspace = Path(temp)
        builtin = workspace / "rm_custom_client" / "assets" / "wallpapers" / "builtin"
        builtin.mkdir(parents=True)
        (builtin / "texas.mp4").write_bytes(b"texas")
        (builtin / "vending-machine.mp4").write_bytes(b"vending")
        source = workspace / "custom-wallpaper.mp4"
        source.write_bytes(b"custom")
        manager = StartupWallpaperManager(workspace)
        try:
            assert manager.profile_names()[:4] == ["TexasMP4", "VendingMachine4K", "Default3000925581Pkg", "ParticleGrid"]
            assert manager.resolve_media_profile("VendingMachine4K") == builtin / "vending-machine.mp4"
            profile = manager.import_wallpaper(source)
            assert profile == "User:custom-wallpaper"
            assert profile in manager.profile_names()
            assert manager.can_remove(profile) is True
            assert manager.remove_wallpaper(profile) is True
            assert profile not in manager.profile_names()
            assert manager.can_remove("TexasMP4") is False
        finally:
            manager.release()


def test_hud_modes_and_rmui_modules() -> None:
    registry = build_default_registry()
    hud = registry.get("HUD")
    assert hud is not None
    right_display = hud.get_setting("Right Display")
    assert right_display is not None
    assert right_display.options == HUD_MODES
    assert "TacticalMapHud" in HUD_MODES
    assert hud.get_setting("Density").options == ["CombatCompact", "Balanced", "DebugFull"]
    assert hud.get_setting("Visual Tone").options == ["LiquidClean", "PolarLegacy"]
    assert hud.get_setting("Target Style").options == ["RoundCompact", "BarOnly", "FullCard"]
    assert hud.get_setting("Density").value == "CombatCompact"
    assert hud.get_setting("Visual Tone").value == "LiquidClean"
    assert hud.get_setting("Target Style").value == "RoundCompact"
    module_list_style = hud.get_setting("ModuleList Style")
    assert module_list_style is not None
    assert module_list_style.options == MODULE_LIST_STYLES
    assert "PolarTextList" in MODULE_LIST_STYLES
    assert "PolarRainbowRight" in MODULE_LIST_STYLES
    assert "DebugWhiteList" in MODULE_LIST_STYLES
    assert "PolarLegacy" not in MODULE_LIST_STYLES
    assert "RainbowRight" not in MODULE_LIST_STYLES
    assert set(MODULE_LIST_RENDERER_KEYS) == set(MODULE_LIST_STYLES)
    assert len(set(MODULE_LIST_RENDERER_KEYS.values())) == len(MODULE_LIST_STYLES)
    assert MODULE_LIST_RENDERER_KEYS["DebugWhiteList"] == "debug_white_list"
    for style in ("LiquidArrayList", "LiquidArrayTags", "LiquidArrayCompact", "LiquidArrayDock"):
        assert style in MODULE_LIST_STYLES
    assert hud.get_setting("ModuleList Surface").options == ["Native", "LiquidGlass"]
    assert hud.get_setting("ModuleList Alignment").options == ["Right", "Left"]
    assert hud.get_setting("ModuleList Order").options == ["Descending", "Ascending"]
    assert hud.get_setting("Module Tags").options == ["Category", "Keybind", "Off"]
    assert hud.get_setting("Module Animation").options == ["FlyFlip", "Slide", "Fade"]
    for name in (
        "GimbalPower",
        "ChassisGimbalIndicator",
        "PowerLimit",
        "SpeedLimit",
        "Capacitor",
        "FrictionWheel",
        "LockState",
        "BuffStatus",
        "ProjectileAllowance",
        "JumpPTEWheelLES",
        "TacticalMap",
        "LiquidTacticalMap",
        "MatchTimer",
        "BaseOutpostStatus",
        "VictoryPointStatus",
        "EconomyPanel",
        "ProjectileShop",
        "ThermalPowerPanel",
        "BuffTimeline",
    ):
        assert registry.get(name) is not None


def test_match_modes_and_official_map_assets() -> None:
    assert MATCH_MODES["RMUC7v7"].field.width_m == 28.0
    assert MATCH_MODES["RMUC7v7"].field.height_m == 15.0
    assert MATCH_MODES["RMUL3v3"].field.width_m == 12.0
    assert MATCH_MODES["RMUL3v3"].field.height_m == 8.0
    for config in MATCH_MODES.values():
        asset = ROOT / config.field.asset_path
        assert asset.exists(), asset
        assert asset.stat().st_size > 1000


def test_match_mode_manager() -> None:
    registry = build_default_registry()
    manager = MatchModeManager("RMUC7v7")
    manager.apply_to_registry(registry)
    assert registry.get("HUD").get_setting("Right Display").value == "ModuleListHud"
    assert registry.get("TacticalMap").get_setting("Map Size").value == "Compact"
    assert registry.get("EnergyAutoAim").enabled is True
    assert registry.get("BaseOutpostStatus").enabled is True
    manager.set_mode("RMUL3v3")
    manager.apply_to_registry(registry)
    assert registry.get("MatchMode").get_setting("Mode").value == "RMUL3v3"
    assert registry.get("TacticalMap").get_setting("Official Map").value == "RMUL 3v3 Official Map"
    assert registry.get("EnergyAutoAim").enabled is False
    assert registry.get("VictoryPointStatus").enabled is True


def test_config_store_roundtrip() -> None:
    registry = build_default_registry()
    registry.get("ArmorAutoAim").keybind = "J"
    registry.get("ArmorAutoAim").get_setting("Fov").value = 72
    with TemporaryDirectory() as temp_dir:
        store = ClientConfigStore(Path(temp_dir))
        data = export_client_config(
            registry,
            gui_mode="PolarNew",
            selected_category="Combat",
            selected_module="ArmorAutoAim",
            module_expanded={"ArmorAutoAim"},
            old_panels={},
            new_panels={},
            dropdown_panels={},
            polar_windows={"Combat": {"x": 80, "y": 100, "scroll": 0}},
            quick_action_wheel={
                "sectors": 6,
                "radius": 132.0,
                "dead_zone": 42.0,
                "actions": list(DEFAULT_ACTIONS),
                "labels": ["Economy", "", "", "", "", "", "", ""],
                "icons": ["EC", "", "", "", "", "", "", ""],
            },
        )
        store.save("practice", data)
        assert "practice" in store.profile_names()
        loaded = store.load("practice")
        assert loaded is not None
        assert loaded["polar_windows"]["Combat"]["x"] == 80
        assert loaded["quick_action_wheel"]["sectors"] == 6
        assert loaded["quick_action_wheel"]["labels"][0] == "Economy"
        fresh = build_default_registry()
        apply_registry_config(fresh, loaded)
        assert fresh.get("ArmorAutoAim").keybind == "J"
        assert fresh.get("ArmorAutoAim").get_setting("Fov").value == 72.0
        apply_registry_config(fresh, {
            "modules": {
                "StartupVisual": {"settings": {"Glass Style": "ReGlass"}},
                "HUD": {"settings": {"ModuleList Surface": "ReGlass"}},
                "TacticalMap": {"settings": {"Status Display": "ReGlassCards"}},
            }
        })
        assert fresh.get("StartupVisual").get_setting("Glass Style").value == "LiquidGlass"
        assert fresh.get("HUD").get_setting("ModuleList Surface").value == "LiquidGlass"
        assert fresh.get("TacticalMap").get_setting("Status Display").value == "LiquidCards"
        apply_registry_config(fresh, {
            "modules": {"HUD": {"settings": {"ModuleList Style": "PolarLegacy"}}}
        })
        assert fresh.get("HUD").get_setting("ModuleList Style").value == "PolarTextList"
        apply_registry_config(fresh, {
            "modules": {"HUD": {"settings": {"ModuleList Style": "RainbowRight"}}}
        })
        assert fresh.get("HUD").get_setting("ModuleList Style").value == "PolarRainbowRight"
        apply_registry_config(fresh, {"modules": {"MatchMode": {"settings": {"Alliance": "Blue"}}}})
        assert fresh.get("AllianceProfile").get_setting("Side").value == "Blue"


def test_tongji_bridge_protocol() -> None:
    ready = threading.Event()
    finished = threading.Event()
    port_box: list[int] = []

    def server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port_box.append(listener.getsockname()[1])
            ready.set()
            client, _address = listener.accept()
            with client:
                header = client.recv(PACKET_HEADER.size)
                magic, version, packet_type, sequence, timestamp_ns, payload_size = PACKET_HEADER.unpack(header)
                assert magic == PROTOCOL_MAGIC
                assert version == PROTOCOL_VERSION
                assert packet_type == PACKET_FRAME
                payload = bytearray()
                while len(payload) < payload_size:
                    payload.extend(client.recv(payload_size - len(payload)))
                assert b"source_width" in payload
                result = b'{"source_width":640,"source_height":360,"tracking_state":"tracking","calibrated":true,"inference_device":"GPU","inference_fps":88.0,"latency_ms":12.5,"detections":[{"id":3,"label":"three","color":"blue","confidence":0.93,"points":[[1,2],[3,2],[3,4],[1,4]],"distance_m":5.2}],"predicted_armors":[{"id":0,"label":"three","color":"predicted","confidence":1.0,"points":[[10,20],[30,20],[30,40],[10,40]],"predicted":true}],"aim_yaw_deg":1.5,"aim_pitch_deg":-0.5}'
                response = PACKET_HEADER.pack(PROTOCOL_MAGIC, PROTOCOL_VERSION, PACKET_RESULT, sequence, timestamp_ns, len(result))
                client.sendall(response + result)
        finished.set()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(1.0)
    bridge = TongjiVisionBridge("127.0.0.1", port_box[0])
    bridge.start()
    bridge.submit_jpeg(7, time.time_ns(), 640, 360, b"jpeg")
    deadline = time.perf_counter() + 2.0
    result = None
    while time.perf_counter() < deadline:
        result = bridge.latest_result(10_000)
        if result is not None:
            break
        time.sleep(0.01)
    bridge.stop()
    assert finished.wait(1.0)
    assert result is not None
    assert result.sequence == 7
    assert result.is_tracking is True
    assert result.inference_device == "GPU"
    assert len(result.detections) == 1
    assert len(result.predicted_armors) == 1


def test_tongji_udp_protocol() -> None:
    receiver = TongjiVisionReceiver(0)
    receiver.start()
    deadline = time.perf_counter() + 1.0
    while receiver._socket is None and time.perf_counter() < deadline:
        time.sleep(0.01)
    assert receiver._socket is not None
    port = receiver._socket.getsockname()[1]
    packet = build_tongji_packet(
        640,
        360,
        [{"name": "three", "color": "blue", "confidence": 0.91, "points": [[1, 2], [30, 2], [30, 20], [1, 20]], "locked": True}],
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as publisher:
        publisher.sendto(packet, ("127.0.0.1", port))
    received = None
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        received = receiver.latest(1_000)
        if received is not None:
            break
        time.sleep(0.01)
    receiver.stop()
    assert received is not None
    assert received.primary is not None and received.primary["name"] == "three"


def test_local_prediction_snapshot() -> None:
    from rm_client.vision import snapshot_from_local_result

    armors = [
        {"id": 0, "plate_id": 0, "name": "three", "color": "blue", "confidence": 0.92, "points": [[100, 100], [160, 100], [160, 130], [100, 130]], "back_points": [[104, 104], [156, 104], [156, 132], [104, 132]], "locked": True, "predicted": False, "depth_m": 4.0},
        {"id": 1, "plate_id": 1, "name": "three", "color": "blue", "confidence": 0.62, "points": [[220, 100], [270, 100], [270, 130], [220, 130]], "back_points": [[224, 104], [266, 104], [266, 132], [224, 132]], "predicted": True, "depth_m": 4.2},
        {"id": 2, "plate_id": 2, "name": "three", "color": "blue", "confidence": 0.62, "points": [[300, 180], [350, 180], [350, 210], [300, 210]], "back_points": [[304, 184], [346, 184], [346, 212], [304, 212]], "predicted": True, "depth_m": 4.5},
        {"id": 3, "plate_id": 3, "name": "three", "color": "blue", "confidence": 0.62, "points": [[200, 250], [250, 250], [250, 280], [200, 280]], "back_points": [[204, 254], [246, 254], [246, 282], [204, 282]], "predicted": True, "depth_m": 4.3},
    ]
    snapshot = snapshot_from_local_result(time.time_ns(), 5, 640, 360, armors, 45.0, 22.0, "CPU")
    assert len(snapshot.result.detections) == 1
    assert len(snapshot.result.predicted_armors) == 3
    assert all(len(armor.back_points) == 4 for armor in snapshot.result.predicted_armors)


def test_tongji_local_yolo_demo() -> None:
    """用同济自带 demo 验证 Windows/OpenVINO 路径真的能加载 XML/BIN 并完成一帧推理。"""
    model = ROOT.parent / "同济自瞄" / "sp_vision_25" / "assets" / "yolov5.xml"
    demo = ROOT.parent / "同济自瞄" / "sp_vision_25" / "assets" / "demo" / "demo.avi"
    if not model.exists() or not demo.exists():
        return
    import cv2
    from rm_client.tongji_yolo import TongjiYoloV5

    capture = cv2.VideoCapture(str(demo))
    ok, frame = capture.read()
    capture.release()
    assert ok and frame is not None
    detector = TongjiYoloV5(model, "CPU")
    result = detector.detect(frame)
    assert isinstance(result, list)


def test_calibration_export() -> None:
    from rm_client.calibration import CalibrationProfile, CameraCalibrationManager

    with TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        config_dir = workspace / "同济自瞄" / "sp_vision_25" / "configs"
        config_dir.mkdir(parents=True)
        (config_dir / "demo.yaml").write_text("camera_matrix: [1, 0, 2, 0, 3, 4, 0, 0, 1]\ndistort_coeffs: [0, 0, 0, 0, 0]\nR_camera2gimbal: [1, 0, 0, 0, 1, 0, 0, 0, 1]\nt_camera2gimbal: [0, 0, 0]\n", encoding="utf-8")
        manager = CameraCalibrationManager(workspace)
        manager.profile = CalibrationProfile("polar_webcam", 960, 540, 9, 6, 25.0, [800.0, 0.0, 480.0, 0.0, 800.0, 270.0, 0.0, 0.0, 1.0], [0.0] * 5, 0.42, 12)
        exported = manager.export_tongji_yaml("polar_webcam")
        assert exported is not None and exported.exists()
        text = exported.read_text(encoding="utf-8")
        assert "800" in text
        assert manager.is_valid_for(960, 540) is True


def test_armor_3d_esp_render() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from rm_client.ui.polar_app import PolarRMWindow
    from rm_client.vision import ArmorObservation, VisionResult

    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    window.resize(640, 360)
    # 桌面 smoke 用同尺寸 profile 模拟完成标定，确保预测绘制只依赖桥接结果而非 mock 框。
    from rm_client.calibration import CalibrationProfile

    window.calibration.profile = CalibrationProfile(
        "smoke", 640, 360, 9, 6, 25.0, [500.0] * 9, [0.0] * 5, 0.4, 10
    )
    result = VisionResult(
        sequence=1,
        timestamp_ns=time.time_ns(),
        source_width=640,
        source_height=360,
        calibrated=True,
        tracking_state="tracking",
        detections=(ArmorObservation(3, "three", "blue", 0.93, ((210, 120), (270, 120), (270, 150), (210, 150))),),
        predicted_armors=(
            ArmorObservation(0, "three", "predicted", 1.0, ((310, 112), (365, 116), (365, 146), (310, 142)), 6.0, True, False, 5.6),
            ArmorObservation(1, "three", "predicted", 1.0, ((340, 180), (390, 184), (390, 212), (340, 208)), 8.4, True, False, 7.9),
        ),
        aim_armor=ArmorObservation(-1, "aim", "predicted", 1.0, ((310, 112), (365, 116), (365, 146), (310, 142)), 6.0, True, True, 5.6),
    )
    module = window.registry.get("Armor3DESP")
    assert module is not None
    module.get_setting("Style").value = "PolarMechanicalWire"
    module.get_setting("Prediction Labels").value = False
    image = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    window.draw_armor_3d_esp(painter, 640, 360, result, module)
    painter.end()
    try:
        visible_pixels = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        )
        fluorescent_white_pixels = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if (
                image.pixelColor(x, y).alpha() > 150
                and image.pixelColor(x, y).red() > 225
                and image.pixelColor(x, y).green() > 225
                and image.pixelColor(x, y).blue() > 225
            )
        )
        saturated_green_pixels = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if (
                image.pixelColor(x, y).alpha() > 120
                and image.pixelColor(x, y).green() > image.pixelColor(x, y).red() + 36
                and image.pixelColor(x, y).green() > image.pixelColor(x, y).blue() + 18
            )
        )
        assert 20 < visible_pixels < 9000
        assert fluorescent_white_pixels > 20
        assert saturated_green_pixels == 0
    finally:
        window.close()
    app.processEvents()


def test_setting_clamp() -> None:
    registry = build_default_registry()
    armor_aim = registry.get("ArmorAutoAim")
    fov = armor_aim.get_setting("Fov")
    fov.set_from_ratio(2.0)
    assert fov.value == fov.max_value
    fov.set_from_ratio(-1.0)
    assert fov.value == fov.min_value


def test_udp_reassembly() -> None:
    assembler = FrameAssembler()
    payload = b"abcdefghi"
    p0 = (7).to_bytes(2, "big") + (0).to_bytes(2, "big") + len(payload).to_bytes(4, "big") + payload[:4]
    p1 = (7).to_bytes(2, "big") + (1).to_bytes(2, "big") + len(payload).to_bytes(4, "big") + payload[4:]
    assert assembler.push_packet(p0) is None
    assert assembler.push_packet(p1) == payload


def test_video_pipeline_reassembly() -> None:
    pipeline = VideoPipeline()
    payload = b"hevc-frame"
    p0 = (11).to_bytes(2, "big") + (0).to_bytes(2, "big") + len(payload).to_bytes(4, "big") + payload[:4]
    p1 = (11).to_bytes(2, "big") + (1).to_bytes(2, "big") + len(payload).to_bytes(4, "big") + payload[4:]
    assert pipeline.push_udp_packet(p0) is None
    assert pipeline.push_udp_packet(p1) == payload
    assert pipeline.frames_received == 1


def test_referee_frame_codec() -> None:
    codec = RefereeFrameCodec()
    frame = codec.encode(0x0311, b"abc", seq=7)
    decoded = codec.decode(b"\x00" + frame + b"\xff")
    assert len(decoded) == 1
    assert decoded[0].cmd_id == 0x0311
    assert decoded[0].seq == 7
    assert decoded[0].data == b"abc"
    broken = bytearray(frame)
    broken[-1] ^= 0x55
    assert codec.decode(bytes(broken)) == []


def test_keyboard_control_bridge() -> None:
    from rm_client.control import KeyboardControlBridge

    registry = build_default_registry()
    state = RobotState()
    serial = SerialBridgeStub()
    bridge = KeyboardControlBridge(serial, mock_output=True)
    command = bridge.set_key("W", True, state, registry)
    assert command is not None
    assert command.vx == 1.0
    assert command.vy == 0.0
    assert b"rm_control.chassis.v1" in bridge.last_payload
    assert len(command.to_custom_control()) == 30
    assert serial.last_write == b""

    bridge.mock_output = False
    command = bridge.set_key("W", False, state, registry)
    assert command is not None
    assert command.vx == 0.0
    assert serial.last_write == bridge.last_payload


def test_scenario_manager() -> None:
    registry = build_default_registry()
    manager = ScenarioManager()
    manager.set_scenario("OfficialEvent")
    mqtt = OfficialMqttBridge()
    udp = UDPVideoReceiver()
    serial = SerialBridgeStub()
    from rm_client.control import KeyboardControlBridge

    control = KeyboardControlBridge(serial, mock_output=False)
    manager.apply_to_registry(registry)
    manager.apply_to_runtime(mqtt, udp, control)
    assert registry.get("Scenario").get_setting("Mode").value == "OfficialEvent"
    assert registry.get("TongjiVisionBridge").get_setting("Vision Kill Sensitivity").value == "Match Reliable"
    assert registry.get("MQTTLink").get_setting("Host").value == "192.168.12.1"
    assert registry.get("SerialBridge").get_setting("Mock Writes").value is True
    assert mqtt.host == "192.168.12.1"
    assert mqtt.mock_output is False
    assert udp.port == 3334
    assert control.mock_output is True
    manager.set_scenario("CampusSimulation")
    manager.apply_to_registry(registry)
    assert registry.get("TongjiVisionBridge").get_setting("Vision Kill Sensitivity").value == "Balanced"
    manager.set_scenario("LabDebug")
    manager.apply_to_registry(registry)
    assert registry.get("TongjiVisionBridge").get_setting("Vision Kill Sensitivity").value == "Lab Responsive"


def test_official_mqtt_bridge_mock_publish() -> None:
    bridge = OfficialMqttBridge()
    bridge.publish_custom_control(b"abc")
    assert bridge.publish_records[-1].topic == "CustomControl"
    assert bridge.publish_records[-1].mock_output is True
    assert bridge.publish_common_command(b"one", now=10.0) is True
    assert bridge.publish_records[-1].topic == "CommonCommand"
    assert bridge.publish_records[-1].qos == 1
    record_count = len(bridge.publish_records)
    assert bridge.publish_common_command(b"too-fast", now=10.05) is False
    assert len(bridge.publish_records) == record_count
    assert "10Hz" in bridge.last_error
    assert bridge.publish_common_command(b"two", now=10.101) is True
    assert bridge.publish_air_support_command(b"air", now=10.0) is True
    assert bridge.publish_records[-1].topic == "AirSupportCommand"
    assert bridge.publish_records[-1].qos == 1


def test_robot_state_tick() -> None:
    state = RobotState()
    state.tick(0.016)
    assert state.current_health <= state.max_health
    assert state.stage_countdown_sec >= 0
    assert -180.0 <= state.chassis_yaw_deg <= 180.0
    assert -180.0 <= state.gimbal_yaw_deg <= 180.0
    assert -180.0 <= state.relative_yaw_deg <= 180.0
    assert state.robot_rows
    assert state.map_robots
    assert state.map_markers
    assert 0 <= state.capacitor_percent <= 100
    state.match_mode = "RMUL3v3"
    state.match_duration_sec = 300
    state.tick(0.016)
    assert state.match_title == "RMUL 3v3"
    assert 0 <= state.ally_victory_points <= 200


def test_pyside_animation_import() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter
    from PySide6.QtWidgets import QApplication

    from rm_client.ui.animation import AnimationBank, Easings
    from rm_client.ui.polar_app import PolarRMWindow

    bank = AnimationBank()
    value = bank.value("smoke", 1.0, 0.01, Easings.linear, initial=0.0)
    assert 0.0 <= value <= 1.0
    assert PolarRMWindow.__name__ == "PolarRMWindow"
    timeline = GuiTransitionTimeline()
    timeline.set_target(1.0)
    for _ in range(12):
        timeline.update(1.0 / 60.0)
    current = timeline.progress
    timeline.reverse_from_current()
    timeline.update(1.0 / 60.0)
    assert 0.0 <= timeline.progress <= current
    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    layout = window.module_list_layout(1920, 1080)
    assert layout.anchor_x == 1902.0
    assert layout.anchor_y == 18.0
    assert layout.available_height == 1044.0
    assert "VendingMachine4K" in window.startup_wallpaper.profile_names()
    vending = ROOT / "assets" / "wallpapers" / "builtin" / "vending-machine.mp4"
    assert vending.exists() and vending.stat().st_size > 1_000_000
    window.startup_wallpaper.video_player.configure((1280, 720), "Smooth60")
    assert window.startup_wallpaper.video_player.load(vending) is True
    deadline = time.perf_counter() + 3.0
    snapshot = window.startup_wallpaper.video_player.snapshot()
    while snapshot.path != vending.resolve() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
        snapshot = window.startup_wallpaper.video_player.snapshot()
    assert snapshot.path == vending.resolve()
    assert not snapshot.image.isNull()
    assert not snapshot.soft_glass.isNull()
    assert not snapshot.glass.isNull()
    window.wallpaper_picker_visible = True
    rendered = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(0)
    window.resize(1280, 720)
    window.render(rendered)
    assert not rendered.isNull()
    visual = window.registry.get("StartupVisual")
    assert visual is not None
    glass_style = visual.get_setting("Glass Style")
    assert glass_style is not None
    glass_style.value = "Legacy"
    window.render(rendered)
    glass_style.value = "LiquidGlass"
    tactical_map = window.registry.get("TacticalMap")
    assert tactical_map is not None
    tactical_map.set_enabled(True)
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier, "", False, 1)
    repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier, "", True, 1)
    release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier, "", False, 1)
    assert window.handle_tactical_map_hold_event(press, True) is True
    assert window.tactical_map_hold is True
    assert window.handle_tactical_map_hold_event(repeat, True) is True
    assert tactical_map.enabled is True
    assert window.tactical_map_hold is True
    assert window.handle_tactical_map_hold_event(release, False) is True
    assert window.tactical_map_hold is False
    window.home_visible = False
    source = QImage(640, 360, QImage.Format.Format_RGB32)
    source.fill(QColor("#295a76"))
    source_painter = QPainter(source)
    source_painter.fillRect(0, 0, 320, 360, QColor("#193544"))
    source_painter.fillRect(320, 0, 320, 360, QColor("#537f6d"))
    source_painter.end()
    window.update_hud_liquid_source(source)
    assert "hud" in window.liquid_glass.snapshots
    tactical_map.get_setting("Status Display").value = "LiquidCards"
    hud = window.registry.get("HUD")
    assert hud is not None
    hud.get_setting("ModuleList Style").value = "LiquidArrayDock"
    rendered.fill(0)
    window.render(rendered)
    assert any(bytes(rendered.constBits()))
    window.close()


def test_liquid_glass_snapshot_stability() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from rm_client.ui.liquid_glass import LiquidGlassRenderer

    app = QApplication.instance() or QApplication([])
    background = QImage(320, 180, QImage.Format.Format_RGB32)
    background.fill(QColor("#245a83"))

    def render() -> bytes:
        renderer = LiquidGlassRenderer()
        renderer.update("startup", background, QRectF(0, 0, 320, 180))
        image = QImage(320, 180, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#101820"))
        painter = QPainter(image)
        renderer.draw(painter, QRectF(40, 30, 180, 100), 14, source="startup", mode="prominent")
        painter.end()
        return bytes(image.constBits())

    assert render() == render()
    app.processEvents()


def test_gpu_glass_commands_do_not_accumulate_between_frames() -> None:
    from PySide6.QtCore import QRectF

    from rm_client.ui.gpu_frame_compositor import GpuFrameCompositor

    compositor = GpuFrameCompositor()
    compositor.begin_frame(rebuild_static_ui=True)
    compositor.begin_static_glass()
    compositor.add_glass(QRectF(10, 10, 120, 40), 20, surface="main")
    compositor.end_static_glass()
    compositor.add_glass(QRectF(200, 10, 160, 30), 15, surface="sub")
    assert len(compositor._static_glass_commands) == 1
    assert len(compositor._frame_glass_commands) == 1

    compositor.begin_frame(rebuild_static_ui=False)
    assert len(compositor._static_glass_commands) == 1
    assert len(compositor._frame_glass_commands) == 0
    compositor.add_glass(QRectF(220, 10, 160, 30), 15, surface="sub")
    assert len(compositor._frame_glass_commands) == 1

    compositor.begin_frame(rebuild_static_ui=True)
    assert len(compositor._static_glass_commands) == 0
    assert len(compositor._frame_glass_commands) == 0


def test_dynamic_texture_upload_restores_qt_text_pixel_store_state() -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage

    from rm_client.ui import gpu_frame_compositor as compositor_module

    class FakeFramebuffer:
        @staticmethod
        def texture() -> int:
            return 73

    class FakeFunctions:
        def __init__(self) -> None:
            self.active_units: list[int] = []
            self.texture_bindings: list[int] = []
            self.pixel_store: list[tuple[int, int]] = []
            self.upload_count = 0

        def glActiveTexture(self, unit: int) -> None:
            self.active_units.append(unit)

        def glBindTexture(self, _target: int, texture: int) -> None:
            self.texture_bindings.append(texture)

        def glPixelStorei(self, name: int, value: int) -> None:
            self.pixel_store.append((name, value))

        def glTexSubImage2D(self, *_args) -> None:
            self.upload_count += 1

    compositor = compositor_module.GpuFrameCompositor()
    compositor.dynamic_fbo = FakeFramebuffer()
    compositor._size = QSize(64, 64)
    image = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255, 128))
    functions = FakeFunctions()

    assert compositor.upload_dynamic_image(functions, image, 4, 5)
    assert functions.upload_count == 1
    assert functions.texture_bindings[-1] == 0
    assert functions.active_units[-1] == compositor_module._GL_TEXTURE0
    assert functions.pixel_store[-2:] == [
        (compositor_module._GL_UNPACK_ALIGNMENT, 4),
        (compositor_module._GL_PACK_ALIGNMENT, 4),
    ]


def test_hud_liquid_glass_snapshot_stability() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from rm_client.ui.polar_app import PolarRMWindow

    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    window.resize(640, 360)
    source = QImage(640, 360, QImage.Format.Format_RGB32)
    source.fill(QColor("#234c68"))
    window.update_hud_liquid_source(source)

    def render() -> bytes:
        image = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#0d1520"))
        painter = QPainter(image)
        window.draw_hud_liquid_glass(painter, QRectF(30, 40, 180, 82), 8.0, surface="MainGlass")
        painter.end()
        return bytes(image.constBits())

    try:
        assert render() == render()
    finally:
        window.close()
    app.processEvents()


def test_clickgui_offscreen_modes() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from rm_client.ui.polar_app import PolarRMWindow

    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    window.resize(1280, 720)
    window.home_visible = False
    window.gui_visible = True
    try:
        for mode, draw in (
            ("PolarPanel", window.draw_panel_gui),
            ("PolarOld", window.draw_old_gui),
            ("PolarNew", window.draw_new_gui),
            ("PolarDropdown", window.draw_dropdown_gui),
        ):
            window.mode_manager.set_mode(mode)
            window.gui_motion.begin_frame()
            image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor(0, 0, 0, 0))
            painter = QPainter(image)
            window.hotspots.clear()
            draw(painter, 1280, 720, 1.0)
            painter.end()
            assert any(bytes(image.constBits())), mode
            assert window.hotspots, mode
        for mode in GUI_MODES:
            window.mode_manager.set_mode(mode)
            window.gui_motion.begin_frame()
            window.hotspots.clear()
            draw_list = window.build_gpu_clickgui(1280, 720, 1.0)
            assert draw_list.rects, mode
            assert draw_list.texts, mode
            assert window.hotspots, mode
    finally:
        window.close()
    app.processEvents()


def test_prediction_geometry_is_bounded() -> None:
    """未标定 PnP 的异常投影不能重新变成横跨画面的色块。"""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    from rm_client.ui.polar_app import PolarRMWindow

    reference = [
        QPointF(100, 100), QPointF(180, 104),
        QPointF(178, 142), QPointF(102, 138),
    ]
    oversized = [
        QPointF(-240, 80), QPointF(520, 84),
        QPointF(510, 178), QPointF(-230, 174),
    ]
    oversized_back = [point + QPointF(8, 7) for point in oversized]
    front, back = PolarRMWindow.constrain_prediction_geometry(oversized, oversized_back, reference)
    front_box = QPolygonF(front).boundingRect()
    reference_box = QPolygonF(reference).boundingRect()
    assert front_box.width() <= reference_box.width() * 1.35 + 0.01
    assert front_box.height() <= reference_box.height() * 1.45 + 0.01
    assert len(back) == 4


def test_robot_profiles_and_economy_rules() -> None:
    assert [profile.key for profile in profiles_for_match("RMUL3v3")] == ["Hero", "Infantry1", "Sentinel"]
    assert len(profiles_for_match("RMUC7v7")) == 8
    hero = resolve_performance("RMUC7v7", "Hero", level=10, hero_type="Melee")
    assert (hero.max_health, hero.power_limit_w, hero.heat_limit, hero.cooling_rate) == (450, 120, 240, 30)
    infantry = resolve_performance(
        "RMUL3v3", "Infantry1", infantry_chassis="Health", infantry_shooter="Cooling"
    )
    assert (infantry.max_health, infantry.power_limit_w, infantry.heat_limit, infantry.cooling_rate) == (350, 75, 88, 24)

    state = RobotState()
    profile = profile_by_key("RMUC7v7", "Infantry2")
    apply_profile_to_state(state, profile, resolve_performance("RMUC7v7", "Infantry2"), 1)
    assert state.robot_id == 4
    assert state.projectile_type == "17mm"
    assert state.ammo_capacity == 180
    assert state.remaining_ammo == 180
    state.remaining_economy = 500
    state.total_economy_obtained = 700
    state.stage_countdown_sec = 300
    state.in_supply_zone = True
    state.out_of_combat = True
    state.can_remote_ammo = True
    state.can_remote_heal = True
    state.economy_mock_mode = True

    state.match_mode = "RMUL3v3"
    state.robot_profile = "Hero"
    rmul_hero = {offer.key: offer for offer in available_actions(state)}
    assert (rmul_hero["rmul_hero_42_1"].minimum, rmul_hero["rmul_hero_42_1"].cost) == (1, 10)
    assert (rmul_hero["rmul_hero_42_10"].minimum, rmul_hero["rmul_hero_42_10"].cost) == (10, 100)

    state.robot_profile = "Infantry1"
    rmul_infantry = {offer.key: offer for offer in available_actions(state)}
    assert (rmul_infantry["rmul_infantry_17_10"].minimum, rmul_infantry["rmul_infantry_17_10"].cost) == (10, 10)
    assert (rmul_infantry["rmul_infantry_17_100"].minimum, rmul_infantry["rmul_infantry_17_100"].cost) == (100, 100)

    state.robot_profile = "Sentinel"
    rmul_sentinel = available_actions(state)
    # In mock mode, revive offer is visible even when alive (disabled).
    assert len(rmul_sentinel) == 2
    sentinel_map = {offer.key: offer for offer in rmul_sentinel}
    assert sentinel_map["rmul_sentinel_ammo_status"].status_only is True
    assert sentinel_map["rmul_sentinel_ammo_status"].enabled is False
    assert sentinel_map["rmul_auto_respawn"].status_only is True
    assert sentinel_map["rmul_auto_respawn"].enabled is False

    state.match_mode = "RMUC7v7"
    state.robot_profile = "Hero"
    state.current_health = state.max_health
    rmuc_hero = {offer.key: offer for offer in available_actions(state)}
    assert (rmuc_hero["rmuc_hero_42_1"].minimum, rmuc_hero["rmuc_hero_42_1"].cost) == (1, 10)
    assert (rmuc_hero["rmuc_hero_42_10"].minimum, rmuc_hero["rmuc_hero_42_10"].cost) == (10, 100)
    assert (rmuc_hero["rmuc_hero_remote_42_10"].minimum, rmuc_hero["rmuc_hero_remote_42_10"].cost) == (10, 150)
    assert rmuc_hero["rmuc_remote_heal"].confirmation == "hold"

    state.robot_profile = "Infantry2"
    rmuc_infantry = {offer.key: offer for offer in available_actions(state)}
    assert (rmuc_infantry["rmuc_infantry_17_10"].minimum, rmuc_infantry["rmuc_infantry_17_10"].cost) == (10, 10)
    assert (rmuc_infantry["rmuc_infantry_17_100"].minimum, rmuc_infantry["rmuc_infantry_17_100"].cost) == (100, 100)
    assert (rmuc_infantry["rmuc_infantry_remote_17_100"].minimum, rmuc_infantry["rmuc_infantry_remote_17_100"].cost) == (100, 150)

    state.robot_profile = "Engineer"
    state.current_health = state.max_health
    # In mock mode, revive offers are visible even when alive (but disabled).
    engineer_alive = {offer.key: offer for offer in available_actions(state)}
    assert set(engineer_alive) == {"rmuc_confirm_respawn", "rmuc_gold_respawn"}
    assert all(not offer.enabled for offer in engineer_alive.values())
    state.current_health = 0
    state.respawn_can_free = True
    state.respawn_can_pay = True
    state.respawn_gold_cost = 137
    engineer_revive = {offer.key: offer for offer in available_actions(state)}
    assert set(engineer_revive) == {"rmuc_confirm_respawn", "rmuc_gold_respawn"}
    assert engineer_revive["rmuc_gold_respawn"].cost == 137
    assert engineer_revive["rmuc_gold_respawn"].estimated is False

    state.robot_profile = "Aerial"
    state.current_health = state.max_health
    state.air_support_active = False
    state.air_support_can_free = True
    air_support = {offer.key: offer for offer in available_actions(state)}
    assert set(air_support) == {"rmuc_air_support_paid", "rmuc_air_support_free"}
    assert all(offer.topic == "AirSupportCommand" for offer in air_support.values())

    assert encode_common_command(1, 10) == b"\x08\x01\x10\x0a"
    assert encode_common_command(5, 150) == b"\x08\x05\x10\x96\x01"
    assert encode_air_support_command(2) == b"\x08\x02"

    state.robot_profile = "Infantry2"
    state.current_health = state.max_health
    state.remaining_economy = 500
    state.remaining_ammo = 180
    state.ammo_capacity = 180
    state.economy_status_revision = 0
    state.economy_command_status = ""
    mock_offer = {offer.key: offer for offer in available_actions(state)}["rmuc_infantry_17_10"]
    bridge = EconomyCommandBridge()
    transaction = bridge.submit(state, mock_offer, mock=True, now=10.0)
    assert transaction.request.mock is True
    assert transaction.request.command_type == 1
    assert transaction.request.command_param == 10
    assert state.remaining_economy == 500
    assert state.remaining_ammo == 180
    assert bridge.update(state, now=10.20).status == "pending"
    assert bridge.update(state, now=10.40).status == "succeeded"
    assert state.remaining_economy == 490
    assert state.remaining_ammo == 190

    state.remaining_economy = 500
    state.remaining_ammo = 180
    state.economy_status_revision = 5
    state.economy_command_status = "rejected"
    sent = []
    official = EconomyCommandBridge()
    official.sender = lambda request: sent.append(request) is None
    official_transaction = official.submit(state, mock_offer, mock=False, now=20.0)
    assert len(sent) == 1
    assert state.remaining_economy == 500
    assert state.remaining_ammo == 180
    assert official.update(state, now=20.10).status == "pending"
    state.economy_status_revision += 1
    assert official.update(state, now=20.20).status == "rejected"

    state.economy_command_status = ""
    state.economy_status_revision += 1
    accepted = EconomyCommandBridge()
    accepted.sender = lambda _request: True
    accepted_transaction = accepted.submit(state, mock_offer, mock=False, now=30.0)
    state.economy_status_revision += 1
    assert accepted.update(state, now=30.10).status == "pending"
    state.remaining_economy -= 10
    state.remaining_ammo += 10
    state.economy_status_revision += 1
    assert accepted.update(state, now=30.20).status == "succeeded"

    hero_profile = profile_by_key("RMUC7v7", "Hero")
    apply_profile_to_state(state, hero_profile, resolve_performance("RMUC7v7", "Hero"), 1)
    assert state.projectile_type == "42mm"
    assert state.ammo_capacity == 12
    assert state.remaining_ammo == 12

    registry = build_default_registry()
    robot_module = registry.get("RobotProfile")
    economy_module = registry.get("EconomyPanel")
    assert robot_module is not None and robot_module.get_setting("Role") is not None
    assert economy_module is not None and economy_module.keybind == "B"
    assert economy_module.get_setting("Mock Requests").value is True
    assert registry.get("ProjectileShop") is not None
    assert registry.get("UIScale").get_setting("HUD Refresh Rate").value == "144"


def test_economy_workspace_top_anchor_and_reversal() -> None:
    layer = EconomyWorkspaceLayer()
    compact_start = layer.layout(1280, 720, 0.0)
    compact_island = layer.layout(1280, 720, 0.15)
    compact_reveal = layer.layout(1280, 720, 0.48)
    compact_categories = layer.layout(1280, 720, 0.62)
    compact_offers = layer.layout(1280, 720, 0.72)
    compact_detail = layer.layout(1280, 720, 0.84)
    compact_open = layer.layout(1280, 720, 1.0)
    desktop_open = layer.layout(1600, 900, 1.0)

    # The sheet grows from a top island rather than drifting into a centered
    # modal. The source control-center layer starts 48dp above its resting
    # position, so the presentation geometry moves down continuously before
    # settling at the shared top anchor.
    assert compact_start.collapsed.top() == compact_open.target_panel.top()
    assert compact_start.panel.top() < compact_island.panel.top() < compact_open.panel.top()
    assert abs(compact_open.panel.top() - compact_open.target_panel.top()) < 0.01
    assert compact_island.panel.height() < compact_reveal.panel.height() < compact_open.panel.height()
    assert compact_island.body_progress < compact_reveal.body_progress < compact_open.body_progress
    # The sheet forms before its final-size content appears.  Categories,
    # offers, and detail deliberately reveal in that order instead of being
    # squeezed into the intermediate island geometry.
    assert compact_reveal.content_alpha == 0.0
    assert 0.0 < compact_categories.category_alpha <= 1.0
    assert compact_categories.offers_alpha == 0.0
    assert compact_offers.offers_alpha > 0.0
    assert compact_detail.detail_alpha > 0.0
    assert compact_categories.category_alpha >= compact_categories.offers_alpha >= compact_categories.detail_alpha
    assert compact_island.body_clip.height() < compact_reveal.body_clip.height() < compact_open.body_clip.height()
    assert compact_island.header_alpha > compact_island.content_alpha
    assert compact_open.grab_handle.width() == 36.0
    assert compact_open.compact is True
    assert desktop_open.compact is False
    # Control Center modules use the 56dp inner-control height. Keeping these
    # surfaces at that height prevents a 24/48dp lens from collapsing into a
    # long horizontal smear at compact resolutions.
    assert compact_open.status_strip.height() == 56.0
    assert compact_open.tab_bar.height() == 56.0
    assert desktop_open.status_strip.height() == 56.0
    assert desktop_open.tab_bar.height() == 56.0
    for pane in (
        compact_open.offers_pane,
        compact_open.detail_pane,
        compact_open.tab_bar,
        compact_open.status_strip,
        desktop_open.offers_pane,
        desktop_open.detail_pane,
        desktop_open.tab_bar,
        desktop_open.status_strip,
    ):
        assert pane.width() > 0.0 and pane.height() > 0.0

    state = EconomyIslandState()
    state._last_time = 0.0
    state.set_target(1.0, duration=0.62, now=0.0)
    for tick in range(1, 31):
        state.update(now=tick / 120.0)
    opening_progress = state.progress
    assert 0.15 < opening_progress <= 1.12

    # Reversing from the in-flight value preserves a continuous trajectory.
    state.set_target(0.0, duration=0.48, now=30 / 120.0)
    state.update(now=31 / 120.0)
    # A critically damped state may advance for a few display frames while it
    # dissipates opening velocity. It must remain bounded, then contract.
    assert -0.02 <= state.progress <= 1.12
    for tick in range(32, 62):
        state.update(now=tick / 120.0)
    assert state.progress < opening_progress
    for tick in range(62, 200):
        state.update(now=tick / 120.0)
    assert state.progress == 0.0
    assert state.velocity == 0.0

    # A second open at the same viewport must rebase the spring clock and
    # advance without relying on a resize to invalidate renderer state.
    state.set_target(1.0, duration=0.62, now=200 / 120.0)
    state.update(now=201 / 120.0)
    assert state.progress > 0.0
    for tick in range(202, 360):
        state.update(now=tick / 120.0)
    assert state.progress == 1.0
    assert state.velocity == 0.0

    # The reference Control Center applies one fixed 40% dim layer to the
    # complete backdrop, independently of the scene luminance.
    assert adaptive_backdrop_dim(0.22, 1.0) == 0.40
    assert adaptive_backdrop_dim(0.90, 0.5) == 0.20
    assert adaptive_backdrop_dim(0.90, 0.0) == 0.0


def test_control_center_backdrop_treatment_only_invalidates_blur_when_needed() -> None:
    from PySide6.QtCore import QRectF

    from rm_client.ui.gpu_frame_compositor import GpuFrameCompositor

    compositor = GpuFrameCompositor()
    assert compositor.set_backdrop_treatment(
        active=True,
        progress=0.1,
        blur_radius_px=4.0,
        dim_alpha=0.4,
        include_overlay=True,
    )
    full_rect = QRectF(20.0, 30.0, 152.0, 152.0)
    reveal_clip = QRectF(20.0, 80.0, 152.0, 102.0)
    compositor.add_glass(
        full_rect,
        34.0,
        material="LensStrong",
        refraction_height_px=24.0,
        refraction_amount_px=-48.0,
        chromatic_aberration=0.0,
        depth_effect=1.0,
        frost_amount=0.0,
        vibrancy_amount=1.0,
        clip_rect=reveal_clip,
    )
    command = compositor._frame_glass_commands[-1]
    # Reveal clipping must only become a scissor. Mutating the lens geometry
    # changes its SDF and makes the rounded module visibly jump while opening.
    assert command.rect == full_rect
    assert command.clip_rect == reveal_clip
    assert command.refraction_height_px == 24.0
    assert command.refraction_amount_px == -48.0
    assert command.chromatic_aberration == 0.0
    assert command.depth_effect == 1.0
    assert command.frost_amount == 0.0
    assert not compositor.set_backdrop_treatment(
        active=True,
        progress=0.8,
        blur_radius_px=4.0,
        dim_alpha=0.4,
        include_overlay=True,
    )
    assert compositor._backdrop_treatment.progress == 0.8
    assert compositor.set_backdrop_treatment(
        active=True,
        progress=0.8,
        blur_radius_px=6.0,
        dim_alpha=0.4,
        include_overlay=True,
    )


def test_official_economy_status_decode() -> None:
    import struct

    def varint(value: int) -> bytes:
        output = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                output.append(byte | 0x80)
            else:
                output.append(byte)
                return bytes(output)

    def field(number: int, value: int) -> bytes:
        return varint(number << 3) + varint(value)

    feed = OfficialMatchFeed()
    _events, logistics = feed.consume(
        "GlobalLogisticsStatus",
        field(1, 320) + field(2, 780) + field(3, 2) + field(4, 1),
        alliance="Red",
        local_robot_id=3,
    )
    assert logistics["remaining_economy"] == 320
    assert logistics["total_economy_obtained"] == 780
    assert logistics["_economy_revision_increment"] == 1

    _events, respawn = feed.consume(
        "RobotRespawnStatus",
        field(1, 1) + field(2, 100) + field(3, 35) + field(4, 1) + field(5, 140) + field(6, 1),
        alliance="Red",
        local_robot_id=3,
    )
    assert respawn["respawn_pending"] is True
    assert respawn["respawn_progress"] == 0.35
    assert respawn["respawn_gold_cost"] == 140

    dynamic_payload = (
        field(1, 275)
        + varint((2 << 3) | 5)
        + struct.pack("<f", 42.5)
        + field(4, 63)
        + field(5, 88)
        + field(8, 24)
        + field(9, 156)
        + field(10, 1)
        + field(12, 1)
        + field(13, 1)
    )
    _events, dynamic = feed.consume(
        "RobotDynamicStatus",
        dynamic_payload,
        alliance="Red",
        local_robot_id=3,
    )
    assert dynamic["current_health"] == 275
    assert abs(dynamic["current_heat"] - 42.5) < 0.001
    assert dynamic["remaining_ammo"] == 156
    assert dynamic["out_of_combat"] is True
    assert dynamic["can_remote_heal"] is True
    assert dynamic["can_remote_ammo"] is True

    _events, air = feed.consume(
        "AirSupportStatusSync",
        field(1, 1) + field(2, 18) + field(3, 7),
        alliance="Red",
        local_robot_id=3,
    )
    assert air["air_support_active"] is True
    assert air["air_support_can_free"] is True
    assert air["air_support_cost_coins"] == 7


def test_robot_launcher_and_polar_inertial_scroll() -> None:
    from PySide6.QtWidgets import QApplication
    from rm_client.ui.polar_app import InertialScroll, PolarRMWindow

    motion = InertialScroll()
    motion.set_bounds(180.0)
    motion.add_wheel(72.0)
    samples = [motion.update(1.0 / 144.0) for _ in range(60)]
    assert samples[0] >= 0.0
    assert samples[-1] > samples[0]
    assert 0.0 <= motion.position <= 180.0

    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    window.resize(1280, 720)
    try:
        window.hotspots.clear()
        launcher = window.build_gpu_robot_profile_launcher(1280, 720, 1.0)
        assert launcher.rects and launcher.texts
        assert any(hotspot.action == "select_robot_profile" for hotspot in window.hotspots)

        window.mode_manager.set_mode("PolarUnified")
        window.gui_visible = True
        window.polar_unified_morph.reset(1.0)
        window.selected_category = "Render"
        window.selected_module = window.registry.get("EliminationFX")
        started = time.perf_counter()
        for index in range(8):
            window.gui_motion.begin_frame(started + index * 0.10)
            window.build_gpu_clickgui(1280, 720, 1.0)
        window.gui_motion.begin_frame(started + 0.81)
        window.gui_scroll_viewports.clear()
        window.build_gpu_clickgui(1280, 720, 1.0)
        modes = {str(viewport["mode"]) for viewport in window.gui_scroll_viewports}
        assert "polar_unified" in modes
        assert "polar_settings" in modes
    finally:
        window.close()
    app.processEvents()


def test_small_text_policy_and_island_icon_alpha() -> None:
    policy = SmallTextPolicy()
    assert policy.sample_scale_for(12.0) == 2.0
    assert policy.sample_scale_for(18.0) == 2.0
    assert policy.sample_scale_for(19.0) == 1.0
    assert island_icon_coverage(0.5, 0.5) == 1.0
    assert island_icon_coverage(0.0, 0.0) == 0.0
    assert island_icon_coverage(1.0, 0.0) == 0.0
    assert island_icon_coverage(0.0, 1.0) == 0.0
    assert island_icon_coverage(1.0, 1.0) == 0.0


def test_texture_origin_and_combined_backdrop() -> None:
    from PySide6.QtGui import QColor, QImage

    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    image.setPixelColor(0, 0, QColor("#ff0000"))
    image.setPixelColor(1, 0, QColor("#00ff00"))
    image.setPixelColor(0, 1, QColor("#0000ff"))
    image.setPixelColor(1, 1, QColor("#ffffff"))
    uploaded = normalize_image_for_texture(image, TextureOrigin.TOP_LEFT_IMAGE)
    assert uploaded.pixelColor(0, 0) == QColor("#0000ff")
    assert uploaded.pixelColor(1, 0) == QColor("#ffffff")
    assert uploaded.pixelColor(0, 1) == QColor("#ff0000")
    preserved = normalize_image_for_texture(image, TextureOrigin.BOTTOM_LEFT_FBO)
    assert preserved.pixelColor(0, 0) == QColor("#ff0000")

    combined = compose_combined_backdrop_pixel((0.2, 0.4, 0.6), (0.4, 0.1, 0.0, 0.5))
    assert combined == (0.5, 0.30000000000000004, 0.3)


def test_island_animation_reversal_and_hud_stack() -> None:
    timeline = ReversibleExpoTimeline(duration=0.22)
    timeline.set_target(1.0)
    for _ in range(7):
        timeline.update(1.0 / 120.0)
    before_reverse = timeline.progress
    assert 0.0 < before_reverse < 1.0
    timeline.set_target(0.0)
    first_reverse = timeline.update(1.0 / 120.0)
    assert 0.0 <= first_reverse < before_reverse
    assert before_reverse - first_reverse < 0.25

    island = IslandContainerState(response_per_60hz_frame=0.20)
    island.set_target_geometry(10.0, 20.0, 220.0, 42.0)
    island.update(1.0 / 60.0)
    island.set_target_geometry(30.0, 40.0, 520.0, 280.0)
    island.set_content_target(1.0, 0.22)
    island.update(1.0 / 60.0)
    assert 220.0 < island.width < 520.0
    assert 42.0 < island.height < 280.0
    assert island.radius == island.target_radius or island.radius < island.target_radius

    tactical = MapIslandState()
    tactical.set_target(12.0, 58.0, 220.0, 170.0, False)
    tactical.update(1.0 / 60.0)
    tactical.set_target(12.0, 58.0, 520.0, 380.0, True)
    tactical.update(1.0 / 60.0)
    expanded_progress = tactical.progress
    tactical.set_target(12.0, 58.0, 220.0, 170.0, False)
    tactical.update(1.0 / 120.0)
    assert 0.0 <= tactical.progress < expanded_progress

    stack = HudAnchorStack(22.0, 680.0, 8.0)
    target = stack.take(160.0, 42.0)
    calibration = stack.take(180.0, 18.0)
    kill_vision = stack.take(190.0, 18.0)
    assert calibration.bottom() + 8.0 <= target.top()
    assert kill_vision.bottom() + 8.0 <= calibration.top()


def test_combat_target_hud_math_and_rendering() -> None:
    assert ring_end(0.0) == 180.0
    assert ring_end(50.0) == 360.0
    assert ring_end(100.0) == 540.0
    assert abs(approach_jar(100.0, 0.0, 1.0 / 60.0) - 85.0) < 1e-9
    assert abs(approach_bar(50.0, 52.0, 1.0 / 60.0) - 50.8) < 1e-9
    assert abs(ghost_follow(100.0, 80.0, 1.0 / 60.0, 12.0) - 98.8) < 1e-9
    assert meter_settled(50.0, 50.2)
    assert not meter_settled(50.0, 60.0)
    # visual-demo: max=20 → stage drop 10% (SELF_HIT_HP=2)
    assert abs(stage_drop_pct(20.0) - 10.0) < 1e-9
    sim = MockHeatStageSimulator()
    sim.reset(48.0)
    assert sim.heat_pct >= 36.0
    # Instant fire jump
    before = sim.heat_pct
    sim.heat_pct = min(100.0, before + HEAT_PER_SHOT)
    assert sim.heat_pct == before + HEAT_PER_SHOT
    # Stage cool after settle + delay (10% demo-style steps, floor 12%)
    sim.heat_anim = sim.heat_pct
    sim.last_fire_at = 0.0
    sim._started_at = 1.0
    cooled = sim.tick(0.1, now=1.0, self_max_hp=20.0, ammo=100)
    assert cooled < before + HEAT_PER_SHOT
    assert cooled >= 12.0

    state = RobotState()
    state.current_health = 450
    state.max_health = 600
    state.current_heat = 60.0
    state.max_heat = 240.0
    state.remaining_ammo = 90
    state.ammo_capacity = 180
    state.target_locked = False
    state.vision_detection_count = 0
    state.vision_tracking_state = "idle"
    assert aim_target(state) == 0.0
    state.vision_tracking_state = "tracking"
    assert aim_target(state) == 60.0
    state.target_locked = True
    assert aim_target(state) == 100.0

    animator = CombatHudAnimator()
    frame = animator.reset(state)
    assert frame.self_anim == 75.0
    assert frame.heat_anim == 25.0
    assert frame.aim_anim == 100.0
    assert frame.ammo_anim == 50.0
    state.current_health = 300
    updated = animator.update(state, 1.0 / 60.0, "Enhanced")
    assert 50.0 < updated.self_anim < 75.0
    assert updated.self_ghost > updated.self_anim

    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from rm_client.ui.polar_app import PolarRMWindow

    app = QApplication.instance() or QApplication([])
    window = PolarRMWindow()
    window.resize(1280, 720)
    module = window.registry.get("CombatTargetHUD")
    assert module is not None
    try:
        signatures: set[tuple[int, int, int, int]] = set()
        for visual in ("Classic", "Clear", "Enhanced"):
            module.get_setting("Visual").value = visual
            window.combat_hud_animator.reset(window.state)
            image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            window.draw_combat_target_hud(painter, 1280, 720, module)
            painter.end()
            visible = 0
            red = green = blue = 0
            for y in range(315, 485, 3):
                for x in range(520, 760, 3):
                    pixel = image.pixelColor(x, y)
                    if pixel.alpha() > 0:
                        visible += 1
                        red += pixel.red()
                        green += pixel.green()
                        blue += pixel.blue()
            assert visible > 20
            signatures.add((visible, red, green, blue))
        assert len(signatures) == 3

        module.get_setting("Visual").value = "Clear"
        module.get_setting("Show Bars").value = False
        no_bars = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        no_bars.fill(0)
        painter = QPainter(no_bars)
        window.draw_combat_target_hud(painter, 1280, 720, module)
        painter.end()
        assert any(no_bars.pixelColor(x, y).alpha() > 0 for y in range(315, 405, 4) for x in range(590, 690, 4))
        assert not any(no_bars.pixelColor(x, y).alpha() > 0 for y in range(425, 490, 4) for x in range(540, 740, 4))
        for x, y in ((585, 305), (697, 305), (585, 417), (697, 417)):
            assert no_bars.pixelColor(x, y).rgba() == 0

        premultiplied = no_bars.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        payload = bytes(premultiplied.constBits())
        for offset in range(0, len(payload), 4):
            if payload[offset + 3] == 0:
                assert payload[offset : offset + 3] == b"\x00\x00\x00"

        # The compatibility paint path must not clear or tint the rectangular
        # bounds of the raster layer around the circular HUD.
        base_color = QColor("#315577")
        compat = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        compat.fill(base_color)
        painter = QPainter(compat)
        window.draw_combat_target_hud_layer(painter, 1280, 720, module)
        painter.end()
        for x, y in ((535, 225), (745, 225), (535, 495), (745, 495)):
            assert compat.pixelColor(x, y).rgba() == base_color.rgba()

        from rm_client.ui.gpu_frame_compositor import GpuFrameCompositor

        assert not hasattr(window, "build_combat_target_hud_upload")
        assert not hasattr(GpuFrameCompositor, "upload_target_image")
    finally:
        window.close()
    app.processEvents()


def test_ordered_gpu_commands_and_line_only_vision_batch() -> None:
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QFont

    from rm_client.ui.clickgui_gpu import ClickGuiDrawList, GpuRect, GpuText
    from rm_client.ui.vision_wire_gpu import VisionWireBatch

    commands = ClickGuiDrawList()
    commands.rect(QRectF(0, 0, 100, 40), 12, QColor(12, 20, 30, 180))
    commands.text(QRectF(8, 4, 84, 24), "POLAR-RM", QFont("Arial", 12), QColor("white"))
    commands.rect(QRectF(8, 32, 32, 2), 1, QColor(90, 160, 255, 255))
    assert [command.sequence for command in commands.commands] == [0, 1, 2]
    assert [type(command.payload) for command in commands.commands] == [GpuRect, GpuText, GpuRect]

    wire = VisionWireBatch()
    assert not hasattr(wire, "fill")
    assert not hasattr(wire, "rect")
    assert not hasattr(wire, "polygon")
    wire.fluorescent_polyline(
        [QPointF(10, 10), QPointF(70, 10), QPointF(70, 40), QPointF(10, 40)],
        width=1.4,
        alpha=0.82,
        closed=True,
    )
    # Three glow passes plus the white core are emitted for each edge.
    assert len(wire.lines) == 16
    assert not wire.labels.commands
    for line in wire.lines:
        assert line.color.red() == line.color.green() == line.color.blue() == 255
        assert line.color.alpha() > 0


def test_overlay_coordinator_wheel_and_match_chat() -> None:
    registry = build_default_registry()
    chat_module = registry.get("MatchChat")
    wheel_module = registry.get("QuickActionWheel")
    assert chat_module is not None and chat_module.enabled and chat_module.keybind == "T"
    assert wheel_module is not None and wheel_module.enabled and wheel_module.keybind == "Q"

    coordinator = OverlayCoordinator()
    assert coordinator.begin_radial()
    assert coordinator.blocks_combat_input
    coordinator.end_radial()
    assert coordinator.request_modal(OverlayKind.ECONOMY) is None
    assert not coordinator.begin_radial()
    assert coordinator.request_modal(OverlayKind.CLICKGUI) == OverlayKind.ECONOMY
    assert coordinator.begin_chat() == OverlayKind.CLICKGUI
    assert coordinator.chat_input and coordinator.modal is None
    assert not coordinator.begin_radial()
    coordinator.end_chat()
    assert not coordinator.blocks_combat_input

    wheel = QuickActionWheelState()
    wheel.open(4.0, 4.0, 800.0, 600.0, now=1.0)
    assert wheel.center_x >= wheel.radius + 18.0
    assert wheel.center_y >= wheel.radius + 18.0
    assert wheel.update_pointer(wheel.center_x, wheel.center_y) == -1
    assert wheel.update_pointer(wheel.center_x, wheel.center_y - wheel.radius) == 0
    assert wheel.release() == "economy"
    wheel.configure(
        sector_count=4,
        custom_labels=["Top action", "", "Right action", "", "Bottom action", "", "Left action", ""],
        custom_icons=["UP", "", "RT", "", "DN", "", "LT", ""],
    )
    assert [sector.action for sector in wheel.sectors()] == [
        DEFAULT_ACTIONS[0],
        DEFAULT_ACTIONS[2],
        DEFAULT_ACTIONS[4],
        DEFAULT_ACTIONS[6],
    ]
    exported = wheel.export_config()
    restored = QuickActionWheelState()
    restored.load_config(exported)
    assert restored.export_config() == exported

    chat = MatchChatController()
    chat.open_input()
    chat.insert("x" * 300)
    assert len(chat.input_text) == 256
    assert chat.send_input(now=2.0)
    assert chat.messages[-1].source == "you"
    chat.history_older()
    assert chat.input_text == "x" * 256
    chat.history_newer()
    assert chat.input_text == ""
    assert chat.add("Radar online", dedupe_key="radar", now=3.0)
    assert not chat.add("Radar online", dedupe_key="radar", now=3.5)
    chat.close_input()
    assert chat.visible_messages(now=12.0)
    assert not chat.visible_messages(now=14.1)
    for index in range(205):
        chat.add(f"line {index}", now=20.0 + index)
    assert len(chat.messages) == 200

    event_chat = MatchChatController()
    adapter = ChatEventAdapter(event_chat)
    state = RobotState()
    state.stage_countdown_sec = 61
    adapter.poll(state, now=100.0)
    state.stage_countdown_sec = 59
    adapter.poll(state, now=101.0)
    assert [message.text for message in event_chat.messages] == [
        "Match ends in 60 seconds"
    ]
    state.stage_countdown_sec = 60
    adapter.poll(state, now=102.0)
    state.stage_countdown_sec = 59
    adapter.poll(state, now=103.0)
    assert [message.text for message in event_chat.messages].count(
        "Match ends in 60 seconds"
    ) == 1
    state.stage_countdown_sec = 300
    adapter.poll(state, now=104.0)
    state.stage_countdown_sec = 59
    adapter.poll(state, now=105.0)
    assert [message.text for message in event_chat.messages].count(
        "Match ends in 60 seconds"
    ) == 2
    state.air_support_active = True
    adapter.poll(state, now=106.0)
    state.air_support_active = False
    adapter.poll(state, now=107.0)
    assert event_chat.messages[-2].text == "Air support activated"
    assert event_chat.messages[-1].text == "Air support ended"


if __name__ == "__main__":
    test_registry()
    test_audio_feedback_and_kill_sound_mapping()
    test_gui_motion_reversal_and_layer_cache()
    test_vision_render_interpolation_and_presence()
    test_kill_fx_combat_focus_layout_and_migration()
    test_kill_fx_assets_and_dual_evidence()
    test_vision_kill_miss_after_lit()
    test_vision_kill_dark_loss_requires_prior_dimming()
    test_vision_kill_bright_or_exiting_loss_never_eliminates()
    test_vision_kill_external_missing_data_never_eliminates()
    test_gd656_renderer_presets()
    test_wallpaper_pkg_index_reader()
    test_wallpaper_profiles_and_user_import()
    test_hud_modes_and_rmui_modules()
    test_match_modes_and_official_map_assets()
    test_match_mode_manager()
    test_config_store_roundtrip()
    test_tongji_bridge_protocol()
    test_tongji_udp_protocol()
    test_local_prediction_snapshot()
    test_tongji_local_yolo_demo()
    test_calibration_export()
    test_armor_3d_esp_render()
    test_setting_clamp()
    test_udp_reassembly()
    test_video_pipeline_reassembly()
    test_referee_frame_codec()
    test_keyboard_control_bridge()
    test_scenario_manager()
    test_official_mqtt_bridge_mock_publish()
    test_robot_state_tick()
    test_pyside_animation_import()
    test_clickgui_offscreen_modes()
    test_prediction_geometry_is_bounded()
    test_robot_profiles_and_economy_rules()
    test_economy_workspace_top_anchor_and_reversal()
    test_official_economy_status_decode()
    test_robot_launcher_and_polar_inertial_scroll()
    test_small_text_policy_and_island_icon_alpha()
    test_texture_origin_and_combined_backdrop()
    test_island_animation_reversal_and_hud_stack()
    test_combat_target_hud_math_and_rendering()
    test_ordered_gpu_commands_and_line_only_vision_batch()
    test_overlay_coordinator_wheel_and_match_chat()
    test_liquid_glass_snapshot_stability()
    test_gpu_glass_commands_do_not_accumulate_between_frames()
    test_hud_liquid_glass_snapshot_stability()
    print("smoke tests passed")
