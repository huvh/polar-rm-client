from __future__ import annotations

from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QBrush,
    QCloseEvent,
    QFont,
    QFontMetricsF,
    QImage,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QSurfaceFormat,
    QWheelEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from ..calibration import CameraCalibrationManager
from ..combat_hud import CombatHudAnimator, VALID_COMBAT_HUD_VISUALS, ring_end
from ..combat_events import CombatEvent, OfficialMatchFeed, VisionKillDetector
from ..config_store import ClientConfigStore, apply_registry_config, export_client_config
from ..control import KeyboardControlBridge
from ..economy import EconomyAction, EconomyCommandBridge, available_actions
from ..model import (
    CATEGORIES,
    GUI_MODES,
    HUD_MODES,
    MODULE_LIST_STYLES,
    GuiModeManager,
    Module,
    RobotState,
    normalize_gui_mode,
    Setting,
    build_default_registry,
    normalize_angle_deg,
)
from ..match_modes import MATCH_MODES, MATCH_MODE_KEYS, FieldLayout, MatchModeConfig, MatchModeManager
from ..robot_profiles import (
    apply_profile_to_state,
    profile_by_key,
    profiles_for_match,
    resolve_performance,
)
from ..kill_fx import KillFxRenderer
from ..scenarios import SCENARIOS, ScenarioManager
from ..startup_wallpaper import StartupWallpaperManager
from ..tongji_bridge import GimbalCommandBridge, TongjiVisionReceiver
from ..tongji_yolo import LocalAlignedVision
from ..transports import OfficialMqttBridge, SerialBridgeStub, UDPVideoReceiver, VideoPipeline
from ..ui_audio import UiAudioManager
from ..vision import (
    CameraCaptureWorker,
    CapturedFrame,
    CompositeVisionPipeline,
    MockVisionPipeline,
    TongjiVisionBridge,
    VisionResult,
    VisionSnapshot,
    VisionTarget,
    snapshot_from_local_result,
    snapshot_from_tongji_packet,
)
from .animation import AnimationBank, Easings, GuiMotionController, GuiTransitionTimeline, IslandContainerState, MapIslandState, MorphState
from .fonts import FontBook
from .gui_cache import ClickGuiLayerCache
from .clickgui_gpu import ClickGuiDrawList, ClickGuiGpuRenderer
from .gpu_frame_compositor import GpuFrameCompositor, LensMaterial
from .liquid_glass import LiquidGlassRenderer
from .layout import HudAnchorStack
from .startup_gl import StartupGpuCompositor, TextureOrigin
from .vision_wire_gpu import VisionWireBatch, VisionWireGpuRenderer
from .paint import accent_color, cap_center_y, draw_bar, glow_rect, glow_text, rounded_rect, text_width, with_alpha
from .theme import THEME, color
from .vision_motion import (
    AngleRenderTrack,
    ScalarRenderTrack,
    TargetHudPresenceFrame,
    TargetHudPresenceState,
    VisionRenderInterpolator,
)


@dataclass
class Hotspot:
    rect: QRectF
    action: str
    payload: Any = None
    button: int | None = None
    tooltip: str = ""


@dataclass(frozen=True)
class ModuleListLayout:
    """ModuleList 使用的统一逻辑像素安全区。"""

    anchor_x: float
    anchor_y: float
    available_height: float
    row_height: float
    row_gap: float
    right_margin: float
    top_margin: float
    clip_rect: QRectF


class StartupLayerCache:
    def __init__(self) -> None:
        self._vignettes: dict[tuple[int, int], QImage] = {}

    def vignette(self, width: int, height: int) -> QImage:
        key = (width, height)
        image = self._vignettes.get(key)
        if image is not None:
            return image
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.fillRect(QRectF(0, 0, width, height), color("#56fff0", 0.018))
        center_glow = QLinearGradient(width * 0.5, height * 0.18, width * 0.5, height * 0.78)
        center_glow.setColorAt(0.0, color("#56fff0", 0.10))
        center_glow.setColorAt(0.45, color("#ff65df", 0.045))
        center_glow.setColorAt(1.0, color("#000000", 0.0))
        painter.fillRect(QRectF(0, 0, width, height), center_glow)
        painter.fillRect(QRectF(0, 0, width, height), color("#000000", 0.08))
        painter.end()
        if len(self._vignettes) > 4:
            self._vignettes.clear()
        self._vignettes[key] = image
        return image


class FrameScheduler:
    def __init__(self) -> None:
        self.last_request = 0.0

    def should_request(self, now: float, high_rate: bool, target_fps: float = 60.0) -> bool:
        interval = 1.0 / (max(30.0, target_fps) if high_rate else 15.0)
        if now - self.last_request < interval * 0.86:
            return False
        self.last_request = now
        return True

    def force(self) -> None:
        self.last_request = 0.0


class InertialScroll:
    """单调时钟驱动的临界阻尼滚动，不依赖视频源帧率。"""

    def __init__(self) -> None:
        self.position = 0.0
        self.target = 0.0
        self.velocity = 0.0
        self.maximum = 0.0

    def set_bounds(self, maximum: float) -> None:
        self.maximum = max(0.0, float(maximum))
        self.target = max(0.0, min(self.maximum, self.target))
        self.position = max(0.0, min(self.maximum, self.position))

    def add_wheel(self, delta: float) -> None:
        self.target = max(0.0, min(self.maximum, self.target + float(delta)))

    def update(self, dt: float) -> float:
        dt = max(0.001, min(0.032, float(dt)))
        # DynamicIsland 风格的快速临界阻尼：滚轮停止后约 220 ms 收敛。
        stiffness = 235.0
        damping = 2.0 * math.sqrt(stiffness)
        acceleration = (self.target - self.position) * stiffness - self.velocity * damping
        self.velocity += acceleration * dt
        self.position += self.velocity * dt
        if abs(self.target - self.position) < 0.03 and abs(self.velocity) < 0.1:
            self.position = self.target
            self.velocity = 0.0
        return self.position

    @property
    def active(self) -> bool:
        return abs(self.target - self.position) > 0.03 or abs(self.velocity) > 0.1


class VisionViewport(QOpenGLWidget):
    """战斗视频与预测装甲的 GPU 合成层；上下文不可用时由主窗口回退到 CPU。"""

    def __init__(self, owner: "PolarRMWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.gpu_ready = False
        self.frame: QImage | None = None
        self.result: VisionResult | None = None
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.NoPartialUpdate)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_payload(self, frame: QImage | None, result: VisionResult | None) -> None:
        self.frame = frame
        self.result = result
        self.update()

    def initializeGL(self) -> None:
        self.gpu_ready = self.context() is not None

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), color("#0b121b"))
        if self.frame is not None and not self.frame.isNull():
            painter.drawImage(QRectF(0, 0, self.width(), self.height()), self.frame)
        else:
            self.owner.draw_synthetic_video_scene(painter, self.width(), self.height(), lite=True)
        painter.end()


class PolarHudOverlay(QWidget):
    """覆盖 GPU 战斗底图的交互与 HUD 图层。"""

    def __init__(self, owner: "PolarRMWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event: QPaintEvent) -> None:
        self.owner.paint_overlay(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.owner.mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.owner.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.owner.mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.owner.wheelEvent(event)


class PolarRMWindow(QOpenGLWidget):
    """主窗口直接使用 Qt OpenGL 表面，所有 QPainter UI 都由 OpenGL 合成呈现。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("POLAR-RM Custom Client")
        self.resize(1280, 720)
        self.setMinimumSize(1000, 620)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.NoPartialUpdate)

        self.workspace = Path(__file__).resolve().parents[3]
        self.registry = build_default_registry()
        self.state = RobotState()
        self.combat_hud_animator = CombatHudAnimator()
        # CPU fluorescent FOV ring cache: (radius_px, line_w, glow) → (image, half_extent).
        self._fluorescent_circle_cache: dict[tuple[int, int, int], tuple[QImage, float]] = {}
        self._combat_hud_last_time = time.perf_counter()
        self.scenario_manager = ScenarioManager("LabDebug")
        self.match_mode_manager = MatchModeManager("RMUC7v7")
        self.mode_manager = GuiModeManager("PolarPanel")
        self.vision = MockVisionPipeline()
        self.camera_worker = CameraCaptureWorker()
        self.camera_started = False
        self._camera_config: tuple[int, int, int] | None = None
        self.mqtt = OfficialMqttBridge()
        self.official_feed = OfficialMatchFeed()
        self.vision_kill_detector = VisionKillDetector()
        self._official_state_updates: dict[str, Any] = {}
        self.kill_fx = KillFxRenderer(self.workspace / "rm_custom_client" / "assets" / "kill_fx" / "gd656")
        self.ui_audio = UiAudioManager(
            self.workspace / "rm_custom_client" / "assets" / "ui_sounds"
        )
        self.registry.add_toggle_listener(self.on_module_toggled)
        self._vision_scene_luminance = 0.0
        self.udp = UDPVideoReceiver()
        self.video_pipeline = VideoPipeline()
        self.serial = SerialBridgeStub()
        self.control = KeyboardControlBridge(self.serial, mock_output=True)
        self.economy_bridge = EconomyCommandBridge()
        self.config_store = ClientConfigStore(self.workspace / "rm_custom_client" / "configs")
        self.calibration = CameraCalibrationManager(self.workspace)
        self.calibration.load("polar_webcam")
        self.tongji_receiver = TongjiVisionReceiver()
        self.gimbal_command_bridge = GimbalCommandBridge()
        self.composite_vision = CompositeVisionPipeline()
        self.local_vision = LocalAlignedVision(
            self.workspace / "同济自瞄" / "sp_vision_25" / "assets" / "yolov5.xml"
        )
        self.tongji_bridge = TongjiVisionBridge()
        self._vision_source = "Mock"
        self._tongji_enabled = False
        self._vision_snapshot: VisionSnapshot | None = None
        self._last_capture_sequence = 0
        self._last_vision_result: VisionResult | None = None
        self.vision_render_interpolator = VisionRenderInterpolator()
        self.target_hud_presence = TargetHudPresenceState()
        self.hud_angle_tracks: dict[str, AngleRenderTrack] = {}
        self.telemetry_render_tracks: dict[str, ScalarRenderTrack] = {}
        self._vision_render_result: VisionResult | None = None
        self._dynamic_hud_started_at = time.perf_counter()
        self.dynamic_hud_ms = 0.0
        self._armor_geometry_smooth: dict[tuple[int, int, bool, str], tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...]]] = {}
        self.startup_wallpaper = StartupWallpaperManager(self.workspace)
        self.scenario_manager.apply_to_registry(self.registry)
        self.scenario_manager.apply_to_runtime(self.mqtt, self.udp, self.control)
        self.match_mode_manager.apply_to_registry(self.registry)
        self.fonts = FontBook()
        self.fonts.load_from_project_assets(self.workspace)
        self.anim = AnimationBank()
        self.gui_motion = GuiMotionController(self.anim)
        self.gui_cache = ClickGuiLayerCache()
        self.clickgui_gpu = ClickGuiGpuRenderer()
        self.vision_wire_gpu = VisionWireGpuRenderer()
        self.gpu_compositor = GpuFrameCompositor()
        self._gpu_frame_recording = False
        self._gpu_background_key: tuple[object, ...] | None = None
        self._gpu_background_transform_key: tuple[object, ...] | None = None
        self._gpu_control_backdrop_key: tuple[object, ...] | None = None
        self._gpu_blur_source_key: tuple[object, ...] | None = None
        self._gpu_static_ui_key: tuple[object, ...] | None = None
        self._startup_static_page_key: tuple[object, ...] | None = None
        self._gpu_background_changed = True
        self.clickgui_gpu_layout_ms = 0.0
        self.startup_cache = StartupLayerCache()
        self.frame_scheduler = FrameScheduler()
        self.liquid_glass = LiquidGlassRenderer()
        self.startup_gpu = StartupGpuCompositor()
        self.hud_video_gpu = StartupGpuCompositor()
        # 部分 Windows 驱动会在 QPainter 与自定义纹理 shader 连续切页时
        # 损坏 QOpenGLWidget 的帧缓冲。Qt 自身仍负责 OpenGL 合成；先禁用
        # 这条原生视频 shader 路径，保证一级/二级页面切换绝不花屏。
        self.startup_gpu_enabled = False
        self.dynamic_smooth_values: dict[str, float] = {}
        self.dynamic_island_last_event = ""
        self.dynamic_island_event_started = time.perf_counter()
        self.frame_dt = 1.0 / 60.0
        # HUD 刷新与 24/30/60 FPS 的图传解耦。媒体纹理只在新源帧到达时上传，
        # 地图、灵动岛和交互动画继续使用独立的高刷新率 UI 时钟。
        self.render_fps_cap = 240.0
        self.render_fps_target = 144.0
        self.render_frame_ms_ema = 0.0
        self._last_render_tune = time.perf_counter()
        self._last_logic_time = time.perf_counter()

        scenario_module = self.registry.get("Scenario")
        self.home_visible = self.setting_bool(scenario_module, "Show Startup", True)
        self.startup_step = "scenario" if self.home_visible else "done"
        self.startup_transition_started = time.perf_counter()
        # The launcher transition is deliberately independent from the card
        # entrance animation.  It retains the old page until the new one has a
        # complete GPU draw list, which prevents a half-initialised 2K frame.
        self.startup_transition_from: str | None = None
        self.startup_transition_to: str | None = None
        self._startup_page_epoch = 0
        self._startup_static_ready_at = self.startup_transition_started + self.anim_duration(0.42)
        self._startup_last_hover_action = ""
        self.gui_visible = False
        self.gui_timeline = GuiTransitionTimeline()
        self.startup_page_morph = MorphState(progress=1.0, target=1.0, duration=0.42)
        self.dynamic_island_state = IslandContainerState(response_per_60hz_frame=0.20)
        self._bottom_left_diagnostics: list[tuple[str, QColor, int]] = []
        self.polar_unified_morph = MorphState(progress=0.0, target=0.0, duration=0.62)
        self.tactical_map_state = MapIslandState()
        self.selected_category = "Combat"
        self.selected_module = self.registry.get("ArmorAutoAim") or self.registry.modules[0]
        self.search_query = ""
        self.search_focus = False
        self.hotspots: list[Hotspot] = []
        self.hover_tooltip = ""
        self.hover_point = QPointF(0.0, 0.0)
        self.liquid_press_point = QPointF(-1000.0, -1000.0)
        self.liquid_press_until = 0.0
        self.drag: dict[str, Any] | None = None
        self.binding_module: Module | None = None
        self.toasts: list[dict[str, Any]] = []
        # Inline settings start collapsed.  The previous pre-expanded set made
        # Old/New/Dropdown measure every settings block on first open.
        self.module_expanded: set[str] = set()
        self.module_list_rows: dict[str, dict[str, Any]] = {}
        self.settings_scroll: dict[str, float] = {}
        self.panel_module_scroll: dict[str, float] = {}
        # Each GPU scene publishes its own visible scroll region.  Input never
        # guesses from headers, which was the reason long lists bled below
        # their panels in Old/New/Dropdown.
        self.gui_scroll_viewports: list[dict[str, Any]] = []
        self.panel_settings_rect = QRectF()
        self.panel_modules_rect = QRectF()
        self.map_images: dict[str, QImage] = {}
        # Official maps are large source images. Keep their filtered, display-size
        # versions around so the HUD does not resample a PDF-derived field map on
        # every paint while the camera is running.
        self.map_display_cache: dict[tuple[str, int, int], QImage] = {}
        self.synthetic_video_cache: QImage | None = None
        self.synthetic_video_cache_key: tuple[int, int] | None = None
        self.synthetic_video_cache_time = 0.0
        self.frame_image: QImage | None = None
        self.frame_pixmap: QPixmap | None = None
        # 主 HUD 独立保存图传的低分辨率玻璃快照，绝不读取启动页壁纸。
        self.fps_samples: list[float] = []
        self._last_present_time = time.perf_counter()
        self.last_frame_time = time.perf_counter()
        self.last_control_toast = 0.0
        self.tactical_map_hold = False
        self.config_loading = False
        self.wallpaper_picker_visible = False
        self.wallpaper_picker_page = 0
        # The launch surface is a complete native GPU pass. The battle viewport
        # still has a Qt HUD overlay and must not enter the old mixed framebuffer
        # experiment until it can use the same private-FBO final composite.
        # Keeping it off avoids trading stutter for intermittent corruption.
        self.gpu_viewport_enabled = False

        self.old_panels = {
            # Polar Old starts each 140px panel at (20, 20) with a
            # 20px gap.  Stored positions remain logical pixels when dragged.
            category: {"x": 20.0 + i * 160.0, "y": 20.0, "expanded": category in ("Combat", "Vision", "Render"), "dragged": False}
            for i, category in enumerate(CATEGORIES)
        }
        self.new_panels = {category: {"scroll": 0.0} for category in CATEGORIES}
        self.dropdown_panels = {category: {"expanded": True, "scroll": 0.0} for category in CATEGORIES}
        self.polar_windows = {
            category: {"x": 80.0 + (index % 4) * 230.0, "y": 100.0 + (index // 4) * 330.0, "scroll": 0.0}
            for index, category in enumerate([*CATEGORIES, "Profile"])
        }
        self.polar_unified_scroll = 0.0
        self.polar_unified_scroll_motion = InertialScroll()
        self.polar_settings_scroll_motion: dict[str, InertialScroll] = {}
        self.economy_visible = False
        self.economy_selected = 0
        self.economy_quantity = 1
        self.economy_opened_at = 0.0
        self._gpu_warm_pending = True

        self.apply_match_mode(self.match_mode_manager.current.key, close_home=False, announce=False)
        self.apply_robot_profile(self.current_robot_profile_key(), close_home=False, announce=False)
        self.refresh_config_profiles()
        self.refresh_wallpaper_profiles()
        self.refresh_custom_ui_sound_options()
        self.config_store.ensure_default(self.current_config_data())
        self.load_startup_config()
        elimination_fx = self.registry.get("EliminationFX")
        self.kill_fx.preload_preset_sounds(
            self.setting_mode(elimination_fx, "Preset", "Default Scrolling")
        )
        if os.environ.get("POLAR_AUTOSTART", "").lower() in ("1", "true", "yes"):
            self.home_visible = False
            self.startup_step = "done"
        self.sync_mode_setting()
        if not self.home_visible:
            self.refresh_vision_runtime()
        self.toast("ClickGUI 已就绪：PolarPanel")

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(max(5, int(1000.0 / self.render_fps_cap)))

    def on_tick(self) -> None:
        now = time.perf_counter()
        self.gui_motion.begin_frame(now)
        dt = max(0.001, min(0.05, now - self.last_frame_time))
        self.last_frame_time = now
        self.frame_dt = dt
        ui_scale_module = self.registry.get("UIScale")
        refresh_setting = ui_scale_module.get_setting("HUD Refresh Rate") if ui_scale_module else None
        try:
            requested_hz = float(refresh_setting.value) if refresh_setting else 144.0
        except (TypeError, ValueError):
            requested_hz = 144.0
        self.render_fps_target = max(120.0, min(self.render_fps_cap, requested_hz))
        self.polar_unified_scroll = self.polar_unified_scroll_motion.update(dt)
        for motion in self.polar_settings_scroll_motion.values():
            motion.update(dt)
        self.gui_timeline.set_target(1.0 if self.gui_visible else 0.0)
        self.gui_timeline.update(dt)
        gui_mode = self.setting_mode(self.registry.get("ClickGui"), "Mode", "PolarPanel")
        self.polar_unified_morph.set_target(
            1.0 if self.gui_visible and gui_mode == "PolarUnified" else 0.0,
            self.anim_duration(0.62 if self.gui_visible else 0.48),
            now=now,
        )
        self.polar_unified_morph.update(now=now)
        self.tactical_map_state.update(dt)
        dynamic_payload = self.dynamic_island_payload()
        content_duration = 0.30 if dynamic_payload["kind"] == "module" else 0.80
        if not dynamic_payload["active"]:
            content_duration = 0.22
        self.dynamic_island_state.set_content_target(
            1.0 if dynamic_payload["active"] else 0.0,
            content_duration,
        )
        self.dynamic_island_state.update(dt)
        logic_interval = 1.0 / 60.0
        if now - self._last_logic_time >= logic_interval * 0.92:
            logic_dt = max(0.001, min(0.05, now - self._last_logic_time))
            self._last_logic_time = now
            if not self.home_visible:
                self.ensure_camera_started()
            self.startup_wallpaper.set_active(self.home_visible)
            if not self.home_visible:
                self.refresh_vision_runtime()
            self.consume_capture_frame()
            self.state.camera_connected = self.camera_worker.connected
            self.state.mqtt_connected = self.mqtt.connected
            self.state.udp_video_connected = self.udp.frames_received > 0
            self.state.serial_connected = self.serial.connected
            self.state.tick(logic_dt)
            self.consume_official_messages()
            self.apply_official_state()
            self.sync_tongji_vision_state()
            self.process_vision_kill_events()
            self.registry.tick(self.state, logic_dt)
        high_rate = (
            not self.home_visible
            or self.startup_needs_high_rate()
            or self.polar_unified_scroll_motion.active
            or self.tactical_map_state.active()
            or self.dynamic_island_state.active()
            or self.economy_visible
        )
        if self.frame_scheduler.should_request(now, high_rate, self.render_fps_target):
            self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.gui_cache.clear()
        self.map_display_cache.clear()
        self._gpu_background_key = None
        self._gpu_background_transform_key = None
        self._gpu_static_ui_key = None

    def initializeGL(self) -> None:
        self.gpu_compositor.initialize()
        self.vision_wire_gpu.initialize()
        if not self.clickgui_gpu.initialize():
            click_gui = self.registry.get("ClickGui")
            backend = click_gui.get_setting("Render Backend") if click_gui else None
            if backend is not None:
                backend.value = "Compatibility Painter"
        self.startup_gpu.initialize()
        self.hud_video_gpu.initialize()
        # Native passes only draw into private FBOs. The window framebuffer is
        # touched once by GpuFrameCompositor, avoiding Qt/GL state collisions.

    def paintGL(self) -> None:
        started = time.perf_counter()
        if self._gpu_warm_pending and self.clickgui_gpu.available:
            self.prewarm_gpu_clickgui_resources()
            self._gpu_warm_pending = False
        if not self.paint_gpu_frame():
            self.paint_overlay(None)
        presented = time.perf_counter()
        present_dt = max(0.001, min(0.25, presented - self._last_present_time))
        self._last_present_time = presented
        self.fps_samples.append(1.0 / present_dt)
        if len(self.fps_samples) > 90:
            self.fps_samples.pop(0)
        self.state.fps = sum(self.fps_samples) / len(self.fps_samples)
        elapsed_ms = (presented - started) * 1000.0
        self.render_frame_ms_ema = elapsed_ms if self.render_frame_ms_ema <= 0.0 else self.render_frame_ms_ema * 0.90 + elapsed_ms * 0.10
        # 不再依据视频或偶发纹理上传耗时自动降档。摄像头保持源帧率，
        # HUD 呈现频率由 UIScale.HUD Refresh Rate 独立控制。

    def prewarm_gpu_clickgui_resources(self) -> None:
        """Allocate shaders and glyph atlases while the launcher is idle.

        Right Shift must only change animation uniforms.  It must not compile a
        shader, allocate an atlas, or rasterise every module label on its first
        press.
        """
        if not self.clickgui_gpu.available:
            return
        labels = {
            "POLAR-RM", "Search modules...", "Keybind", "None", "KEY", "--", "POLAR VIEW",
            "Combat", "Movement", "Vision", "Strategy", "System", "Render",
            "Profile", "Settings", "Module", "Enable", "Disable",
            "SCENE SELECT", "MATCH MODE", "ROBOT PROFILE", "SESSION",
            "DJI Official", "Campus Sim", "Lab Debug", "RMUC 7v7", "RMUL 3v3",
            "Config", "Import", "Wallpaper", "ClickGUI", "Exit", "Back",
            "CUSTOM CLIENT", "Choose runtime environment", "Press 1/2/3 to select. Enter continues.",
            # Chinese panel subtitle glyphs (配置 / 缩放) + common toast fragments.
            "配置", "缩放", "已就绪", "已保存", "已加载", "导入",
        }
        for module in self.registry.modules:
            labels.add(module.name)
            labels.add(module.category)
            labels.add(module.keybind)
            for setting in module.settings:
                labels.add(setting.name)
                labels.add(setting.display_value())
        fonts = (
            self.font("poppins_regular", 8.0),
            self.font("poppins_medium", 8.0),
            self.font("poppins_bold", 9.0),
            self.font("poppins_regular", 7.2),
            self.font("poppins_medium", 8.2),
            self.font("poppins_bold", 18.0),
            self.font("museo", 28.0, QFont.Weight.Bold),
            self.font("material", 12.0, QFont.Weight.Bold),
        )
        self.clickgui_gpu.prewarm(fonts, labels, self.devicePixelRatioF())

    def paint_gpu_startup(self) -> bool:
        """GPU-only launcher path. No QPainter touches the window framebuffer."""
        if not self.home_visible or self.wallpaper_picker_visible or not self.clickgui_gpu.available or not self.startup_gpu.available:
            return False
        context = self.context()
        if context is None:
            return False
        module = self.registry.get("StartupVisual")
        mode = self.setting_mode(module, "Background Mode", "VideoParallax")
        profile = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
        if mode in ("ParticleGrid", "PkgScene") or profile in ("ParticleGrid", "Default3000925581Pkg"):
            return False
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return False
        snapshot = self.startup_wallpaper.prepare_gpu_video(
            QRectF(0, 0, width, height),
            self.hover_point,
            self.frame_dt,
            mode=mode,
            profile=profile,
            parallax=self.get_setting_number(module, "Parallax Strength", 22.0),
            zoom=self.get_setting_number(module, "Background Zoom", 1.0),
            high_res=self.high_res_optimize(width, height),
            motion_quality=self.setting_mode(module, "Motion Quality", "Smooth60"),
        )
        if snapshot is None:
            return False
        functions = context.extraFunctions()
        try:
            ratio = self.devicePixelRatioF()
            self.hotspots.clear()
            commands = self.build_gpu_startup_transition(width, height)
            if self.hover_tooltip:
                self.build_gpu_tooltip(commands, self.hover_point, self.hover_tooltip)
            self.build_gpu_toasts(commands, width, height)
            self.clickgui_gpu.prepare_frame(commands, ratio)
            functions.glViewport(0, 0, max(1, round(width * ratio)), max(1, round(height * ratio)))
            functions.glClearColor(0.0, 0.0, 0.0, 1.0)
            functions.glClear(0x00004000)
            self.startup_gpu.update_frame(
                snapshot.image,
                self.startup_wallpaper.last_draw_rect,
                snapshot.sequence,
                snapshot.frame_interval,
                self.get_setting_number(module, "Dim Overlay", 0.28),
                origin=TextureOrigin.TOP_LEFT_IMAGE,
            )
            if not self.startup_gpu.render(functions, QRectF(0, 0, width, height)):
                return False
            return self.clickgui_gpu.render(
                functions,
                commands,
                width,
                height,
                ratio,
                atlas_prepared=True,
            )
        except Exception:
            return False

    def begin_startup_page_transition(self, page: str) -> None:
        """Switch launcher pages through one reversible GPU-only timeline."""
        if page not in ("scenario", "match", "robot") or page == self.startup_step:
            return
        self.startup_gpu.discard_interpolation_history()
        self.startup_transition_from = self.startup_step
        self.startup_transition_to = page
        self.startup_transition_started = time.perf_counter()
        self.startup_page_morph.reset(0.0)
        self.startup_page_morph.set_target(
            1.0,
            self.anim_duration(0.42),
            now=self.startup_transition_started,
        )
        self.startup_step = page
        self._startup_page_epoch += 1
        self._startup_static_page_key = None
        self._startup_static_ready_at = self.startup_transition_started + self.anim_duration(0.42)
        self.frame_scheduler.force()

    def finish_startup_page_transition(self) -> None:
        """原子提交新启动页，禁止旧页面纹理继续参与后续合成。"""
        if self.startup_transition_from is not None or self.startup_transition_to is not None:
            self.startup_transition_from = None
            self.startup_transition_to = None
            self._startup_page_epoch += 1
            self._gpu_static_ui_key = None
            self._startup_static_page_key = None
            self.gpu_compositor.clear_static_glass()
            self.gpu_compositor.clear_frame_glass()

    def build_gpu_startup_transition(self, width: int, height: int) -> ClickGuiDrawList:
        """Compose launcher pages in one draw list, never between GL passes.

        The first half contracts the outgoing scene into a DynamicIsland-like
        capsule.  The second half reveals the incoming page.  Both scene lists
        are generated before one renderer submission, so page changes cannot
        expose an uninitialised framebuffer on high-DPR displays.
        """
        outgoing = self.startup_transition_from
        incoming = self.startup_transition_to
        progress = self.startup_page_morph.update(now=time.perf_counter())
        if not outgoing or not incoming or progress >= 1.0:
            self.finish_startup_page_transition()
            return self.build_gpu_startup_launcher(width, height, page=self.startup_step)

        commands = ClickGuiDrawList()
        # Keep the old draw list visual-only: its hotspots must never win a
        # click while the incoming page is already interactive.
        old_commands = self.build_gpu_startup_launcher(
            width,
            height,
            page=outgoing,
            visual_alpha=(1.0 - Easings.ease_out_expo(min(1.0, progress / 0.40))),
        )
        self.hotspots.clear()
        # Leave a short island-only interval instead of cross-fading two full
        # glass pages.  Overlapping their translucent panels was perceived as
        # a bright flash on 2K displays.
        reveal = Easings.ease_out_expo(max(0.0, min(1.0, (progress - 0.58) / 0.42)))
        new_commands = self.build_gpu_startup_launcher(width, height, page=incoming, visual_alpha=reveal)
        commands.extend(old_commands)
        commands.extend(new_commands)

        # A restrained island replaces the old full-page flash.  It stays in
        # the same top anchor used by the launcher title and is GPU geometry.
        island_t = 1.0 - abs(progress * 2.0 - 1.0)
        island_w = 108.0 + 268.0 * Easings.ease_out_expo(island_t)
        island_h = 14.0 + 25.0 * Easings.ease_out_expo(island_t)
        island = QRectF(width / 2.0 - island_w / 2.0, 28.0, island_w, island_h)
        if self._gpu_frame_recording:
            self.gpu_compositor.add_glass(
                island,
                island_h / 2.0,
                strength=1.02,
                surface="clear",
                hover=0.0,
                opacity=1.0,
                material=LensMaterial.ISLAND,
            )
        if island_t > 0.24:
            commands.text(island, "POLAR-RM", self.font("poppins_bold", 7.2), color("#ffffff", island_t), Qt.AlignmentFlag.AlignCenter)
        return commands

    def paint_direct_gpu_background(self) -> bool:
        """Use native GL only for the opaque source image, then hand the UI to Qt."""
        context = self.context()
        if context is None:
            return False
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return False
        functions = context.extraFunctions()
        ratio = self.devicePixelRatioF()
        canvas = QRectF(0, 0, width, height)
        try:
            functions.glViewport(0, 0, max(1, round(width * ratio)), max(1, round(height * ratio)))
            functions.glClearColor(0.0, 0.0, 0.0, 1.0)
            functions.glClear(0x00004000)
            if self.home_visible:
                module = self.registry.get("StartupVisual")
                mode = self.setting_mode(module, "Background Mode", "VideoParallax")
                profile = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
                if mode in ("ParticleGrid", "PkgScene") or profile in ("ParticleGrid", "Default3000925581Pkg") or not self.startup_gpu.available:
                    return False
                snapshot = self.startup_wallpaper.prepare_gpu_video(
                    canvas,
                    self.hover_point,
                    self.frame_dt,
                    mode=mode,
                    profile=profile,
                    parallax=self.get_setting_number(module, "Parallax Strength", 22.0),
                    zoom=self.get_setting_number(module, "Background Zoom", 1.0),
                    high_res=self.high_res_optimize(width, height),
                    motion_quality=self.setting_mode(module, "Motion Quality", "Smooth60"),
                )
                if snapshot is None:
                    return False
                self.startup_gpu.update_frame(
                    snapshot.image,
                    self.startup_wallpaper.last_draw_rect,
                    snapshot.sequence,
                    snapshot.frame_interval,
                    self.get_setting_number(module, "Dim Overlay", 0.28),
                    origin=TextureOrigin.TOP_LEFT_IMAGE,
                )
                if not self.startup_gpu.render(functions, canvas):
                    return False
                self.liquid_glass.update(
                    "startup",
                    snapshot.image,
                    self.startup_wallpaper.last_draw_rect,
                    soft=snapshot.soft_glass,
                    lens=snapshot.glass,
                )
                self.paint_overlay(None, startup_background_ready=True)
                return True
            if self.frame_image is None or self.frame_image.isNull() or not self.hud_video_gpu.available:
                return False
            self.hud_video_gpu.update_frame(self.frame_image, canvas, self._last_capture_sequence, 1.0 / 30.0, 0.0)
            if not self.hud_video_gpu.render(functions, canvas):
                return False
            self.paint_overlay(None, hud_background_ready=True)
            return True
        except Exception:
            return False

    def _paint_gpu_frame_cached(self) -> bool:
        """在稳定启动页复用静态 GPU 层，hover 只提交一张小动态图层。"""
        if not self.gpu_compositor.available:
            return False
        context = self.context()
        if context is None:
            return False
        width, height = self.width(), self.height()
        ratio = self.devicePixelRatioF()
        if width <= 0 or height <= 0 or not self.gpu_compositor.ensure_size(width, height, ratio):
            return False
        functions = context.extraFunctions()
        try:
            startup_scene = self.home_visible and not self.wallpaper_picker_visible and self.clickgui_gpu.available
            static_key = self.gpu_static_ui_key(width, height, ratio)
            rebuild_hud_static = not startup_scene and static_key != self._gpu_static_ui_key
            self.gpu_compositor.begin_frame(rebuild_static_ui=rebuild_hud_static)
            if not self.gpu_compositor.clear_target_layer(functions):
                return False
            self._gpu_frame_recording = True
            if not self.paint_gpu_background(functions, width, height, ratio):
                return False
            control_changed = self.paint_gpu_control_backdrop(
                functions,
                width,
                height,
                ratio,
                startup_scene=startup_scene,
            )
            # Clear this isolated layer on every page so an ESP frame cannot
            # survive a HUD-to-launcher transition.
            native_vision_owner = self.paint_gpu_vision_layer(functions, width, height, ratio)

            if startup_scene:
                transition_active = (
                    self.startup_transition_from is not None
                    and self.startup_transition_to is not None
                    and time.perf_counter() - self.startup_transition_started < self.anim_duration(0.42)
                )
                # The stable page can be cached as soon as a transition ends.
                # Waiting for a timer here left a transparent dynamic layer on
                # 2K displays and exposed the previous page for one more frame.
                cache_ready = not transition_active
                if cache_ready:
                    launcher_key = (*static_key, self.scenario_manager.current.key, self.match_mode_manager.current.key)
                    if launcher_key != self._startup_static_page_key:
                        self.hotspots.clear()
                        self.gpu_compositor.clear_static_glass()
                        self.gpu_compositor.begin_static_glass()
                        commands = self.build_gpu_startup_launcher(width, height, page=self.startup_step, settled=True)
                        self.gpu_compositor.end_static_glass()
                        self.clickgui_gpu.prepare_frame(commands, ratio)
                        device = self.gpu_compositor.paint_device("overlay")
                        if device is None:
                            return False
                        self.gpu_compositor.clear_current(functions, transparent=True)
                        if not self.clickgui_gpu.render(
                            functions,
                            commands,
                            width,
                            height,
                            ratio,
                            atlas_prepared=True,
                        ):
                            return False
                        self.gpu_compositor.release_layer("overlay")
                        self._startup_static_page_key = launcher_key
                    if not self.paint_gpu_startup_interaction_layer(functions, width, height, ratio, cached_static=True):
                        return False
                else:
                    self.gpu_compositor.clear_static_glass()
                    self._startup_static_page_key = None
                    device = self.gpu_compositor.paint_device("overlay")
                    if device is None:
                        return False
                    self.gpu_compositor.clear_current(functions, transparent=True)
                    self.gpu_compositor.release_layer("overlay")
                    if not self.paint_gpu_startup_interaction_layer(functions, width, height, ratio):
                        return False
                self._gpu_static_ui_key = static_key
            else:
                if rebuild_hud_static:
                    device = self.gpu_compositor.paint_device("overlay")
                    if device is None:
                        return False
                    device.setDevicePixelRatio(ratio)
                    self.gpu_compositor.clear_current(functions, transparent=True)
                    self.gpu_compositor.begin_static_glass()
                    painter = QPainter(device)
                    self.paint_overlay(
                        None,
                        startup_background_ready=True,
                        hud_background_ready=True,
                        painter=painter,
                        logical_size=(width, height),
                        include_interactive=False,
                        split_motion_layer=True,
                    )
                    painter.end()
                    self.gpu_compositor.end_static_glass()
                    self.gpu_compositor.release_layer("overlay")
                    self._gpu_static_ui_key = static_key
                prepared_clickgui_commands: ClickGuiDrawList | None = None
                prepared_clickgui_hotspots: list[Hotspot] | None = None
                prepared_clickgui_atlas = False
                click_gui = self.registry.get("ClickGui")
                gui_alpha = self.gui_timeline.progress
                if (
                    gui_alpha > 0.01
                    and self.setting_mode(click_gui, "Render Backend", "Unified GPU") == "Unified GPU"
                    and self.clickgui_gpu.available
                ):
                    prepared_clickgui_commands = self.build_gpu_clickgui(width, height, gui_alpha)
                    # Snapshot hit targets before motion overlay / overlay clear
                    # wipes them.  Layout runs once; present reuses this list.
                    prepared_clickgui_hotspots = list(self.hotspots)
                    self.clickgui_gpu.prepare_frame(prepared_clickgui_commands, ratio)
                    prepared_clickgui_atlas = True

                device = self.gpu_compositor.paint_device("dynamic")
                if device is None:
                    return False
                device.setDevicePixelRatio(ratio)
                self.gpu_compositor.clear_current(functions, transparent=True)
                painter = QPainter(device)
                if not self.home_visible:
                    self.paint_hud_motion_overlay(
                        painter,
                        width,
                        height,
                        include_vision=not native_vision_owner,
                        include_target_hud=False,
                    )
                    self.paint_clickgui_overlay(
                        painter,
                        width,
                        height,
                        gpu_commands=prepared_clickgui_commands,
                        gpu_hotspots=prepared_clickgui_hotspots,
                        gpu_atlas_prepared=prepared_clickgui_atlas,
                    )
                painter.end()
                self.gpu_compositor.release_layer("dynamic")
                if not self.paint_gpu_target_hud_layer(functions, width, height, ratio):
                    return False

            if not self.gpu_compositor.prepare_blur(
                functions,
                background_changed=self._gpu_background_changed or control_changed,
            ):
                return False
            if not self.gpu_compositor.render_glass(functions):
                return False
            return self.gpu_compositor.present(functions, self.defaultFramebufferObject())
        except Exception as exc:
            self.gpu_compositor.last_error = str(exc)
            try:
                self.gpu_compositor.release_layer("background")
                self.gpu_compositor.release_layer("overlay")
                self.gpu_compositor.end_vision_layer()
                self.gpu_compositor.release_layer("dynamic")
            except Exception:
                pass
            return False
        finally:
            self._gpu_frame_recording = False

    def paint_gpu_control_backdrop(
        self,
        functions,
        width: int,
        height: int,
        ratio: float,
        *,
        startup_scene: bool,
    ) -> bool:
        """绘制位于镜片下方的控件轨道，并返回本次是否更新。"""
        key = (
            "startup" if startup_scene else "hud",
            self.startup_step if startup_scene else "battle",
            self._startup_page_epoch if startup_scene else 0,
            width,
            height,
            round(ratio, 3),
        )
        if key == self._gpu_control_backdrop_key:
            return False
        device = self.gpu_compositor.paint_device("control")
        if device is None:
            return False
        device.setDevicePixelRatio(ratio)
        self.gpu_compositor.clear_current(functions, transparent=True)
        if startup_scene and self.startup_step in {"scenario", "match"}:
            painter = QPainter(device)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            scale = max(0.74, min(1.14, self.get_auto_ui_scale(width, height, strength=0.45)))
            menu_x, menu_y, button_w, button_h, gap = self.liquid_menu_layout(width, height, 3, scale)
            accents = (
                [self.startup_menu_accent(index + 2) for index in range(2)] + [color("#ec5ad9")]
                if self.startup_step == "match"
                else [self.startup_menu_accent(index) for index in range(3)]
            )
            for index, accent in enumerate(accents):
                rect = QRectF(menu_x, menu_y + index * (button_h + gap), button_w, button_h)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(with_alpha(accent, 0.34))
                painter.drawRoundedRect(
                    QRectF(
                        rect.left() + 22.0 * scale,
                        rect.center().y() - 2.0 * scale,
                        min(94.0 * scale, rect.width() * 0.24),
                        4.0 * scale,
                    ),
                    2.0 * scale,
                    2.0 * scale,
                )
                painter.setBrush(with_alpha(accent, 0.88))
                painter.drawRoundedRect(
                    QRectF(rect.left(), rect.top(), 4.0 * scale, rect.height()),
                    2.0 * scale,
                    2.0 * scale,
                )
            painter.end()
        self.gpu_compositor.release_layer("control")
        self._gpu_control_backdrop_key = key
        return True

    def paint_gpu_frame(self) -> bool:
        """Render the scene into private FBOs, then make one native GL present."""
        return self._paint_gpu_frame_cached()

        if not self.gpu_compositor.available:
            return False
        context = self.context()
        if context is None:
            return False
        width, height = self.width(), self.height()
        ratio = self.devicePixelRatioF()
        if width <= 0 or height <= 0 or not self.gpu_compositor.ensure_size(width, height, ratio):
            return False
        functions = context.extraFunctions()
        try:
            startup_gpu_scene = (
                self.home_visible
                and not self.wallpaper_picker_visible
                and self.clickgui_gpu.available
            )
            static_key = self.gpu_static_ui_key(width, height, ratio)
            rebuild_static_ui = not startup_gpu_scene and static_key != self._gpu_static_ui_key
            self.gpu_compositor.begin_frame(rebuild_static_ui=rebuild_static_ui)
            self._gpu_frame_recording = True
            if not self.paint_gpu_background(functions, width, height, ratio):
                return False
            if not self.gpu_compositor.prepare_blur(
                functions,
                background_changed=self._gpu_background_changed,
            ):
                return False
            if startup_gpu_scene:
                # 启动页完全由动态 GPU 场景接管；切页后不保留任何旧
                # QPainter 覆盖层或静态玻璃命令，避免残影重现。
                self.gpu_compositor.clear_static_glass()
                overlay_device = self.gpu_compositor.paint_device("overlay")
                if overlay_device is None:
                    return False
                self.gpu_compositor.clear_current(functions, transparent=True)
                self.gpu_compositor.release_layer("overlay")
                if not self.paint_gpu_startup_interaction_layer(functions, width, height, ratio):
                    return False
                self._gpu_static_ui_key = static_key
            elif rebuild_static_ui:
                overlay_device = self.gpu_compositor.paint_device("overlay")
                if overlay_device is None:
                    return False
                overlay_device.setDevicePixelRatio(ratio)
                self.gpu_compositor.clear_current(functions, transparent=True)
                overlay_started = time.perf_counter()
                self.gpu_compositor.begin_static_glass()
                painter = QPainter(overlay_device)
                self.paint_overlay(
                    None,
                    startup_background_ready=True,
                    hud_background_ready=True,
                    painter=painter,
                    logical_size=(width, height),
                    include_interactive=False,
                    split_motion_layer=True,
                )
                painter.end()
                self.gpu_compositor.end_static_glass()
                self.gpu_compositor.last_overlay_ms = (time.perf_counter() - overlay_started) * 1000.0
                self.gpu_compositor.release_layer("overlay")
                self._gpu_static_ui_key = static_key

            if not startup_gpu_scene:
                dynamic_device = self.gpu_compositor.paint_device("dynamic")
                if dynamic_device is None:
                    return False
                dynamic_device.setDevicePixelRatio(ratio)
                self.gpu_compositor.clear_current(functions, transparent=True)
                dynamic_started = time.perf_counter()
                dynamic_painter = QPainter(dynamic_device)
                if not self.home_visible:
                    self.paint_hud_motion_overlay(
                        dynamic_painter,
                        width,
                        height,
                    )
                    self.paint_clickgui_overlay(dynamic_painter, width, height)
                dynamic_painter.end()
                self.gpu_compositor.last_dynamic_ms = (time.perf_counter() - dynamic_started) * 1000.0
                self.gpu_compositor.release_layer("dynamic")
            if not self.gpu_compositor.render_glass(functions):
                return False
            if not self.gpu_compositor.present(functions, self.defaultFramebufferObject()):
                return False
            return True
        except Exception as exc:
            self.gpu_compositor.last_error = str(exc)
            try:
                self.gpu_compositor.release_layer("background")
                self.gpu_compositor.release_layer("overlay")
                self.gpu_compositor.release_layer("dynamic")
            except Exception:
                pass
            return False
        finally:
            self._gpu_frame_recording = False

    def paint_gpu_startup_interaction_layer(self, functions, width: int, height: int, ratio: float, *, cached_static: bool = False) -> bool:
        """Submit only the launcher's high-frequency interaction layer."""
        if not cached_static:
            self.hotspots.clear()
        started = time.perf_counter()
        commands = self.build_gpu_startup_hover_layer(width, height) if cached_static else self.build_gpu_startup_transition(width, height)
        if self.hover_tooltip:
            self.build_gpu_tooltip(commands, self.hover_point, self.hover_tooltip)
        self.build_gpu_toasts(commands, width, height)
        # Glyph page publication may allocate textures. Do it before binding
        # the destination FBO; the following render pass is strictly read-only.
        self.clickgui_gpu.prepare_frame(commands, ratio)
        device = self.gpu_compositor.paint_device("dynamic")
        if device is None:
            return False
        try:
            self.gpu_compositor.clear_current(functions, transparent=True)
            rendered = self.clickgui_gpu.render(
                functions,
                commands,
                width,
                height,
                ratio,
                atlas_prepared=True,
            )
            self.gpu_compositor.last_dynamic_ms = (time.perf_counter() - started) * 1000.0
            return rendered
        finally:
            self.gpu_compositor.release_layer("dynamic")

    def gpu_static_ui_key(self, width: int, height: int, ratio: float) -> tuple[object, ...]:
        """Return the low-frequency identity of the stable UI layer.

        摄像头数据可以保持源帧率，但 HUD 的几何动画必须跟随显示刷新率。
        过去这里把整个战斗 HUD 固定在 30 Hz，导致 FPS 计数很高时小地图和
        灵动岛仍然只有 30 帧观感。
        """
        if self.home_visible:
            key: tuple[object, ...] = (
                "startup-ui",
                width,
                height,
                round(ratio, 3),
                self.startup_step,
                self.wallpaper_picker_visible,
                self._startup_page_epoch,
            )
            # Compatibility Painter still paints the launcher into the static
            # FBO, so it needs a modest animation cadence. The Direct GPU
            # path above deliberately never includes time in its static key.
            if not self.clickgui_gpu.available or self.wallpaper_picker_visible:
                return (*key, int(time.perf_counter() * 60.0))
            return key
        enabled_state = tuple((module.name, module.enabled) for module in self.registry.modules)
        return (
            "battle-ui",
            width,
            height,
            round(ratio, 3),
            self.match_mode_manager.current.key,
            self.state.current_stage,
            self.state.stage_countdown_sec,
            self.state.last_event,
            enabled_state,
        )

    def paint_gpu_background(self, functions, width: int, height: int, ratio: float) -> bool:
        blur_source_key: tuple[object, ...]
        canvas = QRectF(0, 0, width, height)
        startup_snapshot = None
        if self.home_visible:
            module = self.registry.get("StartupVisual")
            mode = self.setting_mode(module, "Background Mode", "VideoParallax")
            profile = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
            if (
                mode not in ("ParticleGrid", "PkgScene")
                and profile not in ("ParticleGrid", "Default3000925581Pkg")
                and self.startup_gpu.available
            ):
                # Advance only the inexpensive parallax transform before the
                # cache decision.  Decoded media and blur snapshots retain
                # their own content sequence and are never rebuilt by mouse
                # movement.
                startup_snapshot = self.startup_wallpaper.prepare_gpu_video(
                    canvas,
                    self.hover_point,
                    self.frame_dt,
                    mode=mode,
                    profile=profile,
                    parallax=self.get_setting_number(module, "Parallax Strength", 22.0),
                    zoom=self.get_setting_number(module, "Background Zoom", 1.0),
                    high_res=self.high_res_optimize(width, height),
                    motion_quality=self.setting_mode(module, "Motion Quality", "Smooth60"),
                )
            content_sequence = int(startup_snapshot.sequence) if startup_snapshot is not None else int(getattr(self.startup_wallpaper.video_player, "_sequence", 0))
            background_key: tuple[object, ...] = (
                "startup",
                width,
                height,
                round(ratio, 3),
                mode,
                profile,
                content_sequence,
            )
            transform_key: tuple[object, ...] = (
                "startup-transform",
                round(float(self.startup_wallpaper.parallax_x), 2),
                round(float(self.startup_wallpaper.parallax_y), 2),
            )
            self.gpu_compositor.set_scene_uv_offset(
                -float(self.startup_wallpaper.parallax_x) / max(1.0, float(width)),
                float(self.startup_wallpaper.parallax_y) / max(1.0, float(height)),
            )
            blur_source_key = ("startup-blur", mode, profile, content_sequence, width, height, round(ratio, 3))
        elif self.frame_pixmap is not None and not self.frame_pixmap.isNull():
            background_key = (
                "camera",
                self._last_capture_sequence,
                width,
                height,
                round(ratio, 3),
            )
            transform_key = ("camera-transform", width, height)
            self.gpu_compositor.set_scene_uv_offset(0.0, 0.0)
            blur_source_key = ("camera-blur", self._last_capture_sequence, width, height, round(ratio, 3))
        else:
            background_key = (
                "synthetic",
                width,
                height,
                round(ratio, 3),
            )
            transform_key = ("synthetic-transform", width, height)
            self.gpu_compositor.set_scene_uv_offset(0.0, 0.0)
            blur_source_key = ("synthetic-blur", width, height, round(ratio, 3))
        if (
            background_key == self._gpu_background_key
            and self.gpu_compositor.background_fbo is not None
        ):
            self._gpu_background_transform_key = transform_key
            self._gpu_background_changed = False
            return True

        started = time.perf_counter()
        device = self.gpu_compositor.paint_device("background")
        if device is None:
            return False
        device.setDevicePixelRatio(ratio)
        self.gpu_compositor.clear_current(functions, transparent=False)
        # Some Windows drivers corrupt a QOpenGLTexture fed from a changing
        # QImage while an FBO is resized at 2K/DPR boundaries.  The raw video
        # shader stays available for explicit diagnostics, but the production
        # path paints the decoded frame into our *private* scene FBO and still
        # presents it through the single GPU compositor.  This removes the
        # striped/repeated-frame failure without falling back to the window's
        # mixed QPainter/default-framebuffer path.
        # The launcher has one production background path: texture -> private
        # background FBO.  The painter branch remains a GPU-init fallback only.
        raw_video_path = True
        raw_drawn = False
        if self.home_visible:
            if raw_video_path and mode not in ("ParticleGrid", "PkgScene") and profile not in ("ParticleGrid", "Default3000925581Pkg") and self.startup_gpu.available:
                snapshot = startup_snapshot
                if snapshot is not None:
                    stable_draw_rect = self.startup_wallpaper.last_draw_rect.translated(
                        -float(self.startup_wallpaper.parallax_x),
                        -float(self.startup_wallpaper.parallax_y),
                    )
                    self.startup_gpu.update_frame(
                        snapshot.image,
                        stable_draw_rect,
                        snapshot.sequence,
                        snapshot.frame_interval,
                        self.get_setting_number(module, "Dim Overlay", 0.28),
                        origin=TextureOrigin.TOP_LEFT_IMAGE,
                    )
                    raw_drawn = self.startup_gpu.render(functions, canvas, interpolate=False)
                    if raw_drawn:
                        self.liquid_glass.update(
                            "startup",
                            snapshot.image,
                            stable_draw_rect,
                            soft=snapshot.soft_glass,
                            lens=snapshot.glass,
                        )
        elif raw_video_path and self.frame_image is not None and not self.frame_image.isNull() and self.hud_video_gpu.available:
            self.hud_video_gpu.update_frame(self.frame_image, canvas, self._last_capture_sequence, 1.0 / 30.0, 0.0)
            raw_drawn = self.hud_video_gpu.render(functions, canvas)
        if not raw_drawn:
            painter = QPainter(device)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not self.high_res_optimize(width, height))
            if self.home_visible:
                self.draw_startup_background(painter, width, height)
            elif self.frame_pixmap is not None and not self.frame_pixmap.isNull():
                painter.drawPixmap(canvas, self.frame_pixmap, QRectF(self.frame_pixmap.rect()))
            else:
                self.draw_synthetic_video(painter, width, height)
            painter.end()
        self.gpu_compositor.release_layer("background")
        self._gpu_background_key = background_key
        self._gpu_background_transform_key = transform_key
        self._gpu_background_changed = blur_source_key != self._gpu_blur_source_key
        self._gpu_blur_source_key = blur_source_key
        self.gpu_compositor.last_background_ms = (time.perf_counter() - started) * 1000.0
        return True

    def tune_render_rate(self, now: float) -> None:
        if now - self._last_render_tune < 0.35 or self.render_frame_ms_ema <= 0.0:
            return
        self._last_render_tune = now
        levels = [60.0, 72.0, 90.0, 120.0, 144.0]
        allowed = [level for level in levels if level <= self.render_fps_cap + 0.5]
        if not allowed:
            allowed = [60.0]
        current = min(range(len(allowed)), key=lambda index: abs(allowed[index] - self.render_fps_target))
        budget_ms = 1000.0 / max(1.0, allowed[current])
        measured_ms = self.render_frame_ms_ema
        if self.gpu_compositor.available:
            compositor = self.gpu_compositor
            media_reuse = max(1.0, self.render_fps_target / 30.0)
            ui_reuse = max(
                1.0,
                self.render_fps_target / 30.0,
            ) if not self.home_visible and self.gui_timeline.progress > 0.01 else 1.0
            measured_ms = (
                compositor.last_dynamic_ms
                + compositor.last_glass_ms
                + compositor.last_present_ms
                + compositor.last_overlay_ms / ui_reuse
                + (compositor.last_background_ms + compositor.last_blur_ms) / media_reuse
            )
        # Do not get stranded at 60/72 after a one-off atlas or wallpaper upload.
        # Descend only when a frame is genuinely missing its present budget; climb
        # promptly when the current tier has comfortable headroom.
        if measured_ms > budget_ms * 1.05 and current > 0:
            current -= 1
        elif measured_ms < budget_ms * 0.90 and current + 1 < len(allowed):
            # 资源预热完成后直接回到当前帧耗时能够承受的最高档，避免每
            # 350ms 只爬一级而让用户长时间停留在 60/72 Hz。
            for candidate in range(len(allowed) - 1, current, -1):
                if measured_ms <= (1000.0 / allowed[candidate]) * 0.94:
                    current = candidate
                    break
        self.render_fps_target = allowed[current]

    def paint_overlay(
        self,
        _event: QPaintEvent | None,
        *,
        startup_background_ready: bool = False,
        hud_background_ready: bool = False,
        painter: QPainter | None = None,
        logical_size: tuple[int, int] | None = None,
        include_interactive: bool = True,
        split_motion_layer: bool = False,
    ) -> None:
        owns_painter = painter is None
        p = painter or QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.hotspots.clear()
        width, height = logical_size or (self.width(), self.height())
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not self.high_res_optimize(width, height))

        if self.home_visible:
            if not startup_background_ready:
                self.draw_startup_background(p, width, height)
            if self.wallpaper_picker_visible:
                self.draw_wallpaper_picker(p, width, height)
            else:
                self.draw_startup_page_transition(p, width, height)
            if self.hover_tooltip:
                self.draw_tooltip(p, self.hover_point, self.hover_tooltip)
            if owns_painter:
                p.end()
            return

        if not hud_background_ready:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(QRectF(0, 0, width, height), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # 原始结果必须继续传给击杀检测，以便目标重新亮灯时解除屏蔽；
        # 画面层使用过滤后的结果，确认战亡后不再绘制 ESP、预测板和自瞄框。
        raw_tongji_result = self._vision_snapshot.result if self._vision_snapshot is not None else None
        tongji_result = self.vision_result_for_display(raw_tongji_result)
        if not hud_background_ready:
            self.draw_video(p, width, height)
        armor_target = self.tongji_target(width, height, tongji_result) if tongji_result is not None else None
        if armor_target is None:
            # 选择真实桥接后绝不拿 mock 框伪装成检测结果；断链状态只保留 HUD 提示。
            armor_target = (
                VisionTarget(-160.0, -160.0, 1.0, 1.0, 0.0, "BRIDGE OFFLINE")
                if self._vision_source != "Mock"
                else self.vision.process(width, height, self.state, "armor")
            )
        energy_target = self.vision.process(width, height, self.state, "energy")
        self.draw_rm_hud(
            p,
            width,
            height,
            armor_target,
            energy_target,
            tongji_result,
            draw_motion=not split_motion_layer,
        )
        # EliminationFX is always drawn from paint_hud_motion_overlay so the
        # GPU static-layer cache cannot freeze kill-icon timelines.
        if self.hover_tooltip and not self.gui_visible:
            self.draw_tooltip(p, self.hover_point, self.hover_tooltip)

        if not include_interactive:
            if owns_painter:
                p.end()
            return

        self.paint_clickgui_overlay(p, width, height)
        if owns_painter:
            p.end()

    def draw_startup_page_content(self, p: QPainter, width: int, height: int, page: str) -> None:
        if page == "robot":
            self.draw_robot_profile_screen(p, width, height)
        elif page == "match":
            self.draw_match_mode_screen(p, width, height)
        else:
            self.draw_startup_screen(p, width, height)

    def draw_startup_page_transition(self, p: QPainter, width: int, height: int) -> None:
        """用单时间线把启动页面收进顶部胶囊，再从胶囊展开新页面。"""
        outgoing = self.startup_transition_from
        incoming = self.startup_transition_to
        duration = self.anim_duration(0.42)
        elapsed = time.perf_counter() - self.startup_transition_started
        progress = max(0.0, min(1.0, elapsed / max(0.001, duration)))
        if not outgoing or not incoming or progress >= 1.0:
            self.finish_startup_page_transition()
            self.draw_startup_page_content(p, width, height, self.startup_step)
            return

        collapse = Easings.ease_out_expo(min(1.0, progress / 0.43))
        reveal = Easings.ease_out_expo(max(0.0, min(1.0, (progress - 0.57) / 0.43)))

        p.save()
        p.setOpacity(1.0 - collapse)
        old_scale = 1.0 - collapse * 0.018
        p.translate(width / 2.0, 34.0)
        p.scale(old_scale, old_scale)
        p.translate(-width / 2.0, -34.0 - collapse * 8.0)
        self.draw_startup_page_content(p, width, height, outgoing)
        p.restore()

        # 过渡期间只保留新页面热点，避免两层透明卡片抢点击。
        self.hotspots.clear()
        if reveal > 0.001:
            p.save()
            p.setOpacity(reveal)
            new_scale = 0.982 + reveal * 0.018
            p.translate(width / 2.0, 34.0)
            p.scale(new_scale, new_scale)
            p.translate(-width / 2.0, -34.0 + (1.0 - reveal) * 8.0)
            self.draw_startup_page_content(p, width, height, incoming)
            p.restore()

        island_phase = 1.0 - abs(progress * 2.0 - 1.0)
        island_amount = Easings.ease_out_expo(island_phase)
        island_w = 116.0 + 250.0 * island_amount
        island_h = 22.0 + 18.0 * island_amount
        island = QRectF(width / 2.0 - island_w / 2.0, 24.0, island_w, island_h)
        radius = island.height() / 2.0
        self.draw_liquid_glass_panel(
            p,
            island,
            radius,
            accent=THEME.cyan,
            hover=0.0,
            surface="ModalGlass",
        )
        if island_amount > 0.12:
            self.draw_glass_text(
                p,
                island,
                "POLAR-RM",
                self.font("poppins_medium", 7.6),
                color("#ffffff", min(1.0, island_amount * 1.4)),
                Qt.AlignmentFlag.AlignCenter,
            )

    def paint_hud_motion_overlay(
        self,
        p: QPainter,
        width: int,
        height: int,
        *,
        include_map: bool | None = None,
        include_vision: bool = True,
        include_target_hud: bool = True,
    ) -> None:
        """以 UI 高刷新率绘制与图传帧率无关的战斗 HUD 动效。"""
        started_at = time.perf_counter()
        now = started_at
        hud = self.registry.get("HUD")
        scale = self.get_hud_scale(width, height)
        logical_width = max(1, int(width / scale))
        logical_height = max(1, int(height / scale))
        p.save()
        p.scale(scale, scale)

        display_result = self.interpolated_vision_result(now)
        armor_module = self.registry.get("ArmorAutoAim")
        armor_3d = self.registry.get("Armor3DESP")
        if armor_module and armor_module.enabled:
            if include_vision and display_result is not None and armor_3d and armor_3d.enabled:
                self.draw_armor_3d_esp(
                    p,
                    logical_width,
                    logical_height,
                    display_result,
                    armor_3d,
                )
            elif include_vision and self._vision_source == "Mock":
                mock_armor = self.vision.process(
                    logical_width,
                    logical_height,
                    self.state,
                    "armor",
                )
                # Mock lock overlay only when the plate sits inside FOV circle.
                if self.vision_target_in_autoaim_fov(mock_armor, logical_width, logical_height):
                    self.draw_target_overlay(p, mock_armor, armor_module)
            # Fluorescent-white FOV circle (ClickGUI: Draw Fov + Circle Size).
            self.draw_armor_fov_circle(p, logical_width, logical_height, armor_module)

        energy_module = self.registry.get("EnergyAutoAim")
        if energy_module and energy_module.enabled and self._vision_source == "Mock":
            mock_energy = self.vision.process(
                logical_width,
                logical_height,
                self.state,
                "energy",
            )
            self.draw_target_overlay(p, mock_energy, energy_module)

        if include_target_hud:
            self.paint_combat_target_overlay(
                p,
                logical_width,
                logical_height,
                display_result,
                now,
            )
        if self.setting_bool(hud, "Dynamic Island", True) and not self.gui_visible:
            self.draw_dynamic_island(p, logical_width)
        tactical_map = self.registry.get("TacticalMap")
        draw_map = not self.gui_visible if include_map is None else include_map
        if draw_map and tactical_map and tactical_map.enabled:
            self.draw_tactical_map_hud(p, logical_width, logical_height)
        self.draw_chassis_gimbal_indicator(p, logical_width, logical_height)
        self.draw_telemetry_strip(p, logical_width, logical_height)
        p.restore()
        # Full-resolution kill icons/score popups; not under hud_scale transform.
        # Keep off while ClickGUI owns the screen so module labels stay readable.
        if self.gui_timeline.progress <= 0.01 and not self.economy_visible:
            self.draw_elimination_fx(p, width, height)
        self.dynamic_hud_ms = (time.perf_counter() - started_at) * 1000.0

    def paint_combat_target_overlay(
        self,
        p: QPainter,
        width: int,
        height: int,
        display_result: VisionResult | None,
        now: float,
    ) -> None:
        """Draw the center target HUD once, directly into its destination FBO."""
        valid_target = self.has_valid_combat_target(display_result)
        presence = self.target_hud_presence.update(now, valid_target)
        combat_target_hud = self.registry.get("CombatTargetHUD")
        if combat_target_hud and combat_target_hud.enabled and presence.visible:
            self.draw_combat_target_hud_layer(
                p,
                width,
                height,
                combat_target_hud,
                presence=presence,
            )
            return
        crosshair = self.registry.get("Crosshair")
        if crosshair and crosshair.enabled:
            self.draw_crosshair(p, width, height)

    def paint_gpu_target_hud_layer(
        self,
        functions,
        width: int,
        height: int,
        ratio: float,
    ) -> bool:
        """Rasterize the center ring into a tight CPU patch, then sub-image upload.

        Design (same as ``upload_dynamic_image``): keep TargetHUD on its isolated
        ``target_fbo``, never full-screen CPU frames.  Qt's OpenGL paint engine
        can leave a semi-transparent rectangular atlas around antialiased arcs;
        exact ``glTexSubImage2D`` replace on a small ROI removes that residue
        without tanking frame rate.

        While ClickGUI / economy owns the screen the target layer is cleared so
        the ring does not composite over module labels (targetTex is topmost).
        """
        gui_open = self.gui_timeline.progress > 0.01 or self.economy_visible
        if gui_open:
            return self.gpu_compositor.clear_target_layer(functions)

        if not self.gpu_compositor.clear_target_layer(functions):
            return False

        scale = self.get_hud_scale(width, height)
        logical_width = max(1, int(width / scale))
        logical_height = max(1, int(height / scale))
        module = self.registry.get("CombatTargetHUD")
        visual = self.combat_target_visual(module)
        show_bars = self.setting_bool(module, "Show Bars", False) if module else False
        combat_scale = 1.65 if visual == "Classic" else 2.35
        # Ring outer + stroke + clear/enhanced radial plate (blueR + redW/2 + 10).
        ring_extent = 16.0 * combat_scale + 5.0 * combat_scale + 14.0
        if visual != "Classic":
            plate_extent = 16.0 * combat_scale + (5.0 * combat_scale * 0.92) * 0.5 + 12.0
            ring_extent = max(ring_extent, plate_extent)
        if visual == "Classic":
            half_logical = max(ring_extent, 78.0)
        elif show_bars:
            half_logical = max(ring_extent, 130.0)
        else:
            half_logical = ring_extent
        # Presence scale can breathe slightly above 1.0 while fading in.
        half_logical *= 1.2

        pixel_scale = max(0.001, float(scale) * float(ratio))
        roi_px = int(math.ceil(half_logical * 2.0 * pixel_scale))
        roi_px = max(64, min(roi_px, 512))
        roi_px = (roi_px + 3) // 4 * 4

        image = QImage(roi_px, roi_px, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # Map full logical HUD space so the screen center lands on the patch center.
        painter.translate(roi_px * 0.5, roi_px * 0.5)
        painter.scale(pixel_scale, pixel_scale)
        painter.translate(-logical_width * 0.5, -logical_height * 0.5)
        now = time.perf_counter()
        self.paint_combat_target_overlay(
            painter,
            logical_width,
            logical_height,
            self.interpolated_vision_result(now),
            now,
        )
        painter.end()

        fb_w = max(1, int(round(float(width) * float(ratio))))
        fb_h = max(1, int(round(float(height) * float(ratio))))
        upload_x = int(round(fb_w * 0.5 - roi_px * 0.5))
        upload_y = int(round(fb_h * 0.5 - roi_px * 0.5))
        upload_x = max(0, min(upload_x, max(0, fb_w - roi_px)))
        upload_y = max(0, min(upload_y, max(0, fb_h - roi_px)))
        return self.gpu_compositor.upload_target_region(functions, image, upload_x, upload_y)

    def paint_clickgui_overlay(
        self,
        p: QPainter,
        width: int,
        height: int,
        *,
        gpu_commands: ClickGuiDrawList | None = None,
        gpu_hotspots: list[Hotspot] | None = None,
        gpu_atlas_prepared: bool = False,
    ) -> None:
        """Draw only the high-frequency ClickGUI layer.

        This layer is cleared every present, while the expensive map, HUD text
        and ModuleList remain cached in the stable UI FBO.
        """

        economy_alpha = self.anim.value(
            "hud.economy.open",
            1.0 if self.economy_visible else 0.0,
            self.anim_duration(0.24),
            Easings.ease_out_expo,
        )
        if economy_alpha > 0.01:
            self.hotspots.clear()
            self.draw_economy_overlay(p, width, height, economy_alpha)

        gui_alpha = self.gui_timeline.progress
        if gui_alpha > 0.01:
            # Drop HUD/map hit targets while ClickGUI owns the pointer.
            self.hotspots.clear()
            p.fillRect(QRectF(0, 0, width, height), with_alpha(THEME.dim, gui_alpha))
            click_gui = self.registry.get("ClickGui")
            direct_gpu = self.setting_mode(click_gui, "Render Backend", "Unified GPU") == "Unified GPU" and self.clickgui_gpu.available
            if direct_gpu:
                if gpu_commands is None:
                    commands = self.build_gpu_clickgui(width, height, gui_alpha)
                else:
                    commands = gpu_commands
                    # Outer path already built layout + atlas once; restore the
                    # snapshot so clear() above does not leave zero hotspots.
                    if gpu_hotspots is not None:
                        self.hotspots.extend(gpu_hotspots)
                    else:
                        self.build_gpu_clickgui(width, height, gui_alpha)
                pixel_ratio = self.devicePixelRatioF()
                if not gpu_atlas_prepared:
                    # Direct compatibility callers do not have the outer
                    # compositor's frame-boundary preparation step.
                    self.clickgui_gpu.prepare_frame(commands, pixel_ratio)
                    gpu_atlas_prepared = True
                p.beginNativePainting()
                context = self.context()
                functions = context.extraFunctions() if context is not None else None
                # QPainter / target-layer uploads may leave non-zero texture units
                # dirty; reset unit 0 before sampling glyph atlases.
                if functions is not None:
                    self.gpu_compositor._restore_qt_texture_state(functions, clear_bindings=True)
                rendered = bool(
                    context
                    and functions is not None
                    and self.clickgui_gpu.render(
                        functions,
                        commands,
                        width,
                        height,
                        pixel_ratio,
                        atlas_prepared=gpu_atlas_prepared,
                    )
                )
                p.endNativePainting()
                if not rendered:
                    # Incomplete atlas snapshot must not permanently flip the user
                    # off Unified GPU; retry prepare+render once this frame.
                    if context is not None and functions is not None:
                        try:
                            self.clickgui_gpu.prepare_frame(commands, pixel_ratio)
                            self.gpu_compositor._restore_qt_texture_state(functions, clear_bindings=True)
                            p.beginNativePainting()
                            rendered = bool(
                                self.clickgui_gpu.render(
                                    functions,
                                    commands,
                                    width,
                                    height,
                                    pixel_ratio,
                                    atlas_prepared=True,
                                )
                            )
                            p.endNativePainting()
                        except Exception:
                            rendered = False
                    if not rendered:
                        backend = click_gui.get_setting("Render Backend") if click_gui else None
                        if backend:
                            backend.value = "Compatibility Painter"
                        direct_gpu = False
            if not direct_gpu:
                p.save()
                p.setOpacity(gui_alpha)
                mode = self.mode_manager.mode
                if mode == "PolarOld":
                    self.draw_old_gui(p, width, height, gui_alpha)
                elif mode == "PolarPanel":
                    self.draw_panel_gui(p, width, height, gui_alpha)
                elif mode == "PolarNew":
                    self.draw_new_gui(p, width, height, gui_alpha)
                elif mode == "PolarDropdown":
                    self.draw_dropdown_gui(p, width, height, gui_alpha)
                elif mode == "PolarUnified":
                    # Compatibility fallback keeps the same one-window
                    # interaction model when OpenGL is unavailable.
                    self.draw_panel_gui(p, width, height, gui_alpha)
                else:
                    self.draw_old_gui(p, width, height, gui_alpha)
                self.draw_mode_switcher(p, width, height)
                self.draw_toasts(p, width, height)
                if self.hover_tooltip:
                    self.draw_tooltip(p, self.hover_point, self.hover_tooltip)
                p.restore()

        if self.binding_module is not None and not (gui_alpha > 0.01 and self.setting_mode(self.registry.get("ClickGui"), "Render Backend", "Unified GPU") == "Unified GPU" and self.clickgui_gpu.available):
            self.draw_keybind_overlay(p, width, height)

    def draw_economy_overlay(self, p: QPainter, width: int, height: int, alpha: float) -> None:
        actions = available_actions(self.state)
        if not actions:
            return
        self.economy_selected = max(0, min(len(actions) - 1, self.economy_selected))
        scale = max(0.78, min(1.18, self.get_auto_ui_scale(width, height, strength=0.34)))
        p.save()
        p.fillRect(QRectF(0, 0, width, height), color("#02050a", 0.34 * alpha))

        island_w = min(620 * scale, width * 0.54)
        collapsed_w = 210 * scale
        morph = Easings.ease_out_expo(max(0.0, min(1.0, alpha)))
        current_w = collapsed_w + (island_w - collapsed_w) * morph
        island = QRectF(width / 2 - current_w / 2, 34 * scale, current_w, 52 * scale)
        self.draw_liquid_glass_panel(p, island, 22 * scale, accent=THEME.cyan, hover=0.25, scale=scale, surface="ModalGlass")
        self.draw_glass_text(p, island.adjusted(22 * scale, 0, -22 * scale, 0), f"ECONOMY  ·  {self.state.remaining_economy} GOLD", self.font("poppins_bold", 10 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)

        panel_w = min(1080 * scale, width - 70 * scale)
        panel_h = min(520 * scale, height - 150 * scale)
        panel = QRectF(width / 2 - panel_w / 2, 108 * scale + (1.0 - morph) * 24 * scale, panel_w, panel_h)
        self.draw_liquid_glass_panel(p, panel, 20 * scale, accent=THEME.cyan, hover=0.12, scale=scale, surface="ModalGlass")
        self.draw_glass_text(p, panel.adjusted(28 * scale, 20 * scale, -28 * scale, -panel.height() + 54 * scale), "战斗经济操作", self.font("poppins_bold", 16 * scale), THEME.text)
        profile = profile_by_key(self.match_mode_manager.current.key, self.current_robot_profile_key())
        self.draw_glass_text(p, panel.adjusted(28 * scale, 54 * scale, -28 * scale, -panel.height() + 76 * scale), f"{self.match_mode_manager.current.title} · {profile.title} · 默认 MOCK", self.font("poppins_regular", 8 * scale), THEME.muted)

        count = len(actions)
        columns = min(3, max(1, count))
        gap = 14 * scale
        cards_left = panel.left() + 26 * scale
        cards_top = panel.top() + 96 * scale
        cards_w = panel.width() - 52 * scale
        card_w = (cards_w - gap * (columns - 1)) / columns
        card_h = 128 * scale
        for index, action in enumerate(actions):
            row, column = divmod(index, columns)
            rect = QRectF(cards_left + column * (card_w + gap), cards_top + row * (card_h + gap), card_w, card_h)
            selected = index == self.economy_selected
            hovered = rect.contains(self.hover_point)
            hover = self.anim.value(f"economy.hover.{action.key}", 1.0 if hovered else 0.0, self.anim_duration(0.14), Easings.ease_out_expo)
            accent = THEME.cyan if action.enabled else color("#9aa3aa", 0.62)
            self.draw_liquid_glass_panel(p, rect.translated(0, -3 * scale * hover), 13 * scale, accent=accent, hover=max(hover, 0.48 if selected else 0.0), scale=scale, surface="SubGlass")
            title_color = THEME.text if action.enabled else color("#b8bec3", 0.74)
            self.draw_glass_text(p, rect.adjusted(16 * scale, 14 * scale, -16 * scale, -rect.height() + 38 * scale), action.short_title, self.font("poppins_bold", 11 * scale), title_color)
            self.draw_glass_text(p, rect.adjusted(16 * scale, 42 * scale, -16 * scale, -rect.height() + 65 * scale), action.title, self.font("poppins_medium", 8 * scale), title_color)
            self.draw_glass_text(p, rect.adjusted(16 * scale, 76 * scale, -16 * scale, -15 * scale), f"{action.cost} GOLD  ·  {action.unit}", self.font("poppins_bold", 8 * scale), accent)
            if not action.enabled:
                self.draw_glass_text(p, rect.adjusted(16 * scale, 98 * scale, -16 * scale, -5 * scale), action.reason or "当前不可用", self.font("poppins_regular", 6.5 * scale), color("#ffb66e", 0.82))
            self.add_hotspot(rect, "economy_select", index, tooltip=action.reason or action.title)

        footer = QRectF(panel.left() + 26 * scale, panel.bottom() - 66 * scale, panel.width() - 52 * scale, 42 * scale)
        submit = QRectF(footer.right() - 184 * scale, footer.top(), 184 * scale, footer.height())
        close = QRectF(footer.left(), footer.top(), 104 * scale, footer.height())
        self.draw_liquid_glass_panel(p, close, 13 * scale, accent=color("#ffffff", 0.66), hover=0.0, scale=scale, surface="SubGlass")
        self.draw_glass_text(p, close, "CLOSE  [B]", self.font("poppins_bold", 7.5 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
        selected_action = actions[self.economy_selected]
        submit_accent = THEME.cyan if selected_action.enabled else color("#8a9298", 0.58)
        self.draw_liquid_glass_panel(p, submit, 13 * scale, accent=submit_accent, hover=0.35 if selected_action.enabled else 0.0, scale=scale, surface="ProminentGlass")
        self.draw_glass_text(p, submit, "SEND MOCK REQUEST", self.font("poppins_bold", 8 * scale), THEME.text if selected_action.enabled else THEME.muted, Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(close, "economy_close")
        self.add_hotspot(submit, "economy_submit", self.economy_selected)
        p.restore()

    def draw_startup_gpu_background(self) -> bool:
        if not self.startup_gpu_enabled or not self.home_visible or not self.startup_gpu.available:
            return False

        try:
            module = self.registry.get("StartupVisual")
            mode = self.setting_mode(module, "Background Mode", "VideoParallax")
            profile = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
            snapshot = self.startup_wallpaper.prepare_gpu_video(
                QRectF(0, 0, self.width(), self.height()),
                self.hover_point,
                self.frame_dt,
                mode=mode,
                profile=profile,
                parallax=self.get_setting_number(module, "Parallax Strength", 22.0),
                zoom=self.get_setting_number(module, "Background Zoom", 1.0),
                high_res=self.high_res_optimize(),
                motion_quality=self.setting_mode(module, "Motion Quality", "Smooth60"),
            )
            if snapshot is None:
                return False
            self.startup_gpu.update_frame(
                snapshot.image,
                self.startup_wallpaper.last_draw_rect,
                snapshot.sequence,
                snapshot.frame_interval,
                self.get_setting_number(module, "Dim Overlay", 0.28),
                origin=TextureOrigin.TOP_LEFT_IMAGE,
            )
            self.liquid_glass.update(
                "startup",
                snapshot.image,
                self.startup_wallpaper.last_draw_rect,
                soft=self.startup_wallpaper.soft_glass_frame,
                lens=self.startup_wallpaper.glass_frame,
            )
            context = self.context()
            return bool(context and self.startup_gpu.render(context.functions(), QRectF(0, 0, self.width(), self.height())))
        except Exception as exc:
            # 若驱动或纹理路径不兼容，保持启动页可用并让 QPainter 接管。
            self.startup_gpu.last_error = str(exc)
            self.startup_gpu.available = False
            return False

    def draw_hud_gpu_background(self) -> bool:
        if self.home_visible or not self.hud_video_gpu.available or self.frame_image is None or self.frame_image.isNull():
            return False
        try:
            canvas = QRectF(0, 0, self.width(), self.height())
            self.hud_video_gpu.update_frame(
                self.frame_image,
                canvas,
                self._last_capture_sequence,
                1.0 / 60.0,
                0.0,
            )
            context = self.context()
            return bool(context and self.hud_video_gpu.render(context.functions(), canvas))
        except Exception as exc:
            self.hud_video_gpu.last_error = str(exc)
            self.hud_video_gpu.available = False
            return False

    def startup_needs_high_rate(self) -> bool:
        module = self.registry.get("StartupVisual")
        mode = self.setting_mode(module, "Background Mode", "VideoParallax")
        profile = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
        if mode in ("ParticleGrid", "VideoParallax"):
            return True
        if profile not in ("ParticleGrid", "Default3000925581Pkg"):
            return True
        return time.perf_counter() - self.startup_transition_started < 0.85

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.context() is not None:
            self.makeCurrent()
            self.clickgui_gpu.release()
            self.vision_wire_gpu.release()
            self.gpu_compositor.release()
            self.startup_gpu.release()
            self.hud_video_gpu.release()
            self.doneCurrent()
        self.startup_wallpaper.release()
        self.camera_worker.stop()
        self.local_vision.stop()
        self.tongji_receiver.stop()
        self.tongji_bridge.stop()
        self.mqtt.stop()
        self.udp.stop()
        self.serial.stop()
        super().closeEvent(event)

    def ensure_camera_started(self) -> None:
        source = self.registry.get("CameraFeed")
        source_setting = source.get_setting("Source") if source else None
        if source_setting is not None and source_setting.value != "Webcam":
            return
        camera_id = int(self.get_setting_number(source, "Camera ID", 0))
        capture_width = int(self.get_setting_number(source, "Capture Width", 960))
        capture_height = int(self.get_setting_number(source, "Capture Height", 540))
        requested_config = (camera_id, capture_width, capture_height)
        if self.camera_started and self._camera_config != requested_config:
            self.camera_worker.stop()
            self.camera_started = False
            self.frame_image = None
            self.frame_pixmap = None
        if not self.camera_started:
            self.camera_worker.configure(camera_id, (capture_width, capture_height))
            self.camera_worker.on_frame = self.on_captured_camera_frame
            self.camera_worker.start()
            self.camera_started = True
            self._camera_config = requested_config

    def draw_video(self, p: QPainter, width: int, height: int) -> None:
        source = self.registry.get("CameraFeed")
        source_setting = source.get_setting("Source") if source else None
        use_camera = source_setting is None or source_setting.value == "Webcam"
        if use_camera:
            self.ensure_camera_started()
            if self.frame_pixmap is not None and not self.frame_pixmap.isNull():
                p.drawPixmap(QRectF(0, 0, width, height), self.frame_pixmap, QRectF(self.frame_pixmap.rect()))
                return
        self.draw_synthetic_video(p, width, height)

    def refresh_vision_runtime(self) -> None:
        bridge_module = self.registry.get("TongjiVisionBridge")
        self._vision_source = os.environ.get("POLAR_VISION_SOURCE", self.setting_mode(bridge_module, "Vision Source", "Local"))
        if self._vision_source not in ("Local", "Tongji", "Auto", "Mock"):
            self._vision_source = "Local"
        bridge_enabled = bool(bridge_module and bridge_module.enabled)
        self._tongji_enabled = self._vision_source in ("Tongji", "Auto") and bridge_enabled
        listen = self.setting_bool(bridge_module, "Listen", True)
        if self._tongji_enabled and listen:
            self.tongji_receiver.configure(int(self.get_setting_number(bridge_module, "UDP Port", 9871)))
            self.tongji_receiver.start()
        elif self.tongji_receiver.running:
            self.tongji_receiver.stop()

        local_enabled = self._vision_source in ("Local", "Auto") and bridge_enabled
        model_path = self.workspace / "同济自瞄" / "sp_vision_25" / "assets" / "yolov5.xml"
        device = self.setting_mode(bridge_module, "Local Device", "AUTO")
        if local_enabled and model_path.exists():
            self.local_vision.configure(model_path, device)
            overlay = self.registry.get("RobotOverlay")
            self.local_vision.configure_prediction(
                int(self.get_setting_number(overlay, "Armor Count", 4)),
                self.get_setting_number(overlay, "Radius M", 0.23),
                self.get_setting_number(overlay, "Predict Horizon", 0.06),
            )
            self.local_vision.start()
        elif self.local_vision.running:
            self.local_vision.stop()

        # 旧 TCP 桥接器只保留给历史配置兼容，默认视觉路径不再抢占摄像头或等待 WSL。
        if self.tongji_bridge.running:
            self.tongji_bridge.stop()

    def on_captured_camera_frame(self, frame: CapturedFrame) -> None:
        if self._vision_source in ("Local", "Auto"):
            self.local_vision.submit(frame.sequence, frame.width, frame.height, frame.bgr)

    def consume_capture_frame(self) -> None:
        frame = self.camera_worker.latest_frame()
        if frame is None or frame.sequence <= self._last_capture_sequence:
            return
        self._last_capture_sequence = frame.sequence
        try:
            self._vision_scene_luminance = float(frame.bgr[::32, ::32].mean()) / 255.0
            self.state.vision_scene_luminance = self._vision_scene_luminance
        except Exception:
            pass
        image = QImage(frame.rgb.data, frame.width, frame.height, frame.width * 3, QImage.Format.Format_RGB888).copy()
        camera_module = self.registry.get("CameraFeed")
        if self.setting_bool(camera_module, "Mirror", False):
            image = image.mirrored(True, False)
        self.frame_image = image
        # QPixmap 会由 Qt OpenGL Paint Engine 缓存为纹理；同一摄像头帧在
        # 120/144Hz HUD 重绘期间不再反复上传 QImage。
        self.frame_pixmap = QPixmap.fromImage(image)
        self.update_hud_liquid_source(image)

    def active_tongji_result(self) -> VisionResult | None:
        bridge_module = self.registry.get("TongjiVisionBridge")
        timeout = self.get_setting_number(bridge_module, "UDP Timeout", 250.0)
        local_snapshot: VisionSnapshot | None = None
        local_result = self.local_vision.latest(timeout)
        if local_result is not None:
            timestamp_ns, sequence, frame_width, frame_height, armors, fps, latency_ms, loss_evidence = local_result
            self.sync_local_autoaim_fov(frame_width, frame_height)
            local_snapshot = snapshot_from_local_result(
                timestamp_ns, sequence, frame_width, frame_height, armors, fps, latency_ms, self.local_vision.active_device, loss_evidence
            )
        else:
            self.sync_local_autoaim_fov()
        tongji_snapshot: VisionSnapshot | None = None
        packet = self.tongji_receiver.latest(timeout)
        if packet is not None:
            tongji_snapshot = snapshot_from_tongji_packet(packet, inference_device=self.setting_mode(bridge_module, "External Device", "AUTO"))
            self.gimbal_command_bridge.cache(tongji_snapshot.gimbal_command)
        snapshot = self.composite_vision.choose(self._vision_source, local_snapshot, tongji_snapshot)
        self._vision_snapshot = snapshot
        if snapshot is not None:
            self._last_vision_result = snapshot.result
            return snapshot.result
        return None

    def autoaim_logical_size(self) -> tuple[float, float]:
        width = max(1.0, float(self.width()))
        height = max(1.0, float(self.height()))
        scale = max(0.001, self.get_hud_scale(int(width), int(height)))
        return width / scale, height / scale

    def autoaim_circle_radius(self) -> float:
        """Logical-pixel FOV radius from ArmorAutoAim Circle Size."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return 0.0
        return max(8.0, self.get_setting_number(module, "Circle Size", 160.0))

    def sync_local_autoaim_fov(self, source_width: int = 0, source_height: int = 0) -> None:
        """Push FOV ellipse into local YOLO selector (source pixel space)."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            self.local_vision.configure_autoaim_fov(None)
            return
        logical_w, logical_h = self.autoaim_logical_size()
        radius = self.autoaim_circle_radius()
        frame_w = max(1, int(source_width) if source_width > 0 else int(round(logical_w)))
        frame_h = max(1, int(source_height) if source_height > 0 else int(round(logical_h)))
        # Map HUD circle into source so the on-screen FOV matches lock gate.
        radius_x = radius * (frame_w / max(1.0, logical_w))
        radius_y = radius * (frame_h / max(1.0, logical_h))
        self.local_vision.configure_autoaim_fov(radius_x, radius_y)

    def armor_center_in_autoaim_fov(self, armor, result: VisionResult) -> bool:
        """True when armor plate center lies inside the fluorescent FOV circle."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return True
        if armor is None or len(getattr(armor, "points", ())) < 2:
            return False
        logical_w, logical_h = self.autoaim_logical_size()
        radius = self.autoaim_circle_radius()
        points = self.armor_esp_points(armor.points, result, int(round(logical_w)), int(round(logical_h)))
        if not points:
            return False
        cx = sum(point.x() for point in points) / len(points)
        cy = sum(point.y() for point in points) / len(points)
        return math.hypot(cx - logical_w * 0.5, cy - logical_h * 0.5) <= radius

    def vision_target_in_autoaim_fov(self, target: VisionTarget, width: int, height: int) -> bool:
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return True
        radius = self.autoaim_circle_radius()
        cx = target.x + target.w * 0.5
        cy = target.y + target.h * 0.5
        return math.hypot(cx - width * 0.5, cy - height * 0.5) <= radius

    def apply_autoaim_fov_lock(self, result: VisionResult) -> VisionResult:
        """Keep all ESP detections; only plates inside FOV may be aim_armor / locked."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return result
        aim = result.aim_armor
        if aim is not None and not self.armor_center_in_autoaim_fov(aim, result):
            aim = None
        if aim is None:
            candidates = [
                armor
                for armor in result.detections
                if len(armor.points) == 4 and self.armor_center_in_autoaim_fov(armor, result)
            ]
            if candidates:
                aim = max(candidates, key=lambda armor: float(armor.confidence))
        # Predicted plates of the locked target may still draw; aim face only when in FOV.
        tracking = result.tracking_state
        if aim is None and (result.detections or result.predicted_armors):
            if tracking.lower() in ("locked", "tracking"):
                tracking = "detected"
        return replace(result, aim_armor=aim, tracking_state=tracking)

    def vision_result_for_display(self, result: VisionResult | None) -> VisionResult | None:
        """将灭灯或已确认战亡目标从可视层移除，原始结果继续供 detector 使用。

        Autoaim FOV only strips / reassigns aim_armor; detections stay for full-screen 3D ESP.
        """
        if result is None:
            return None
        detector = self.vision_kill_detector
        hidden_targets = {
            detector.target_identity(armor)
            for armor in result.detections
            if detector.is_extinguished(armor) or detector.is_suppressed(armor)
        }

        def hidden(armor) -> bool:
            return (
                armor.held
                or
                detector.is_extinguished(armor)
                or detector.is_suppressed(armor)
                or detector.target_identity(armor) in hidden_targets
            )

        detections = tuple(armor for armor in result.detections if not hidden(armor))
        predicted = tuple(armor for armor in result.predicted_armors if not hidden(armor))
        aim = result.aim_armor
        if aim is not None and hidden(aim):
            aim = None
        has_visible_target = bool(detections or predicted or aim)
        tracking_state = result.tracking_state if has_visible_target else "lost"
        filtered = replace(
            result,
            detections=detections,
            predicted_armors=predicted,
            aim_armor=aim,
            tracking_state=tracking_state,
        )
        return self.apply_autoaim_fov_lock(filtered)

    def interpolated_vision_result(self, now: float | None = None) -> VisionResult | None:
        """Return geometry sampled on the display clock, never on the camera clock."""
        self._vision_render_result = self.vision_render_interpolator.sample(now)
        return self._vision_render_result

    def has_valid_combat_target(self, result: VisionResult | None) -> bool:
        """Only a real, FOV-admitted armor plate may activate the center TargetHUD."""
        if result is None or self._vision_source == "Mock":
            return False
        if result.tracking_state.lower() not in {"detected", "tracking", "locked"}:
            return False
        # Prefer aim_armor (already FOV-filtered on the display path).
        candidates = []
        if result.aim_armor is not None:
            candidates.append(result.aim_armor)
        for armor in candidates:
            if armor.predicted or armor.held or len(armor.points) != 4:
                continue
            if self.vision_kill_detector.is_extinguished(armor):
                continue
            if self.vision_kill_detector.is_suppressed(armor):
                continue
            if not self.armor_center_in_autoaim_fov(armor, result):
                continue
            return True
        return False

    def vision_result_calibrated(self, result: VisionResult | None) -> bool:
        if result is None or not result.calibrated:
            return False
        return self.calibration.is_valid_for(result.source_width, result.source_height)

    def alliance_side(self) -> str:
        profile = self.registry.get("AllianceProfile")
        side = self.setting_mode(profile, "Side", "") if profile else ""
        if side not in ("Red", "Blue"):
            side = self.setting_mode(self.registry.get("MatchMode"), "Alliance", "Red")
        return side if side in ("Red", "Blue") else "Red"

    def consume_official_messages(self) -> None:
        for topic, payload, _received_at in self.mqtt.drain_received_messages():
            events, updates = self.official_feed.consume(topic, payload, alliance=self.alliance_side(), local_robot_id=self.state.robot_id)
            self._official_state_updates.update(updates)
            for event in events:
                self.accept_combat_event(event)

    def apply_official_state(self) -> None:
        if not self._official_state_updates:
            self.state.official_events_online = False
            return
        for key, value in self._official_state_updates.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self.state.official_events_online = self.official_feed.is_fresh()
        self.state.official_feed_at = float(self._official_state_updates.get("official_feed_at", 0.0))

    def process_vision_kill_events(self) -> None:
        effect = self.registry.get("EliminationFX")
        result = self._vision_snapshot.result if self._vision_snapshot else None
        if effect is None or result is None:
            self.state.vision_kill_status = "NO_DETECTION"
            return
        evidence = self.setting_mode(effect, "Evidence Mode", "Auto")
        # 校内模拟和实验室常有 MQTT mock；Auto 只在官方赛事场景交由裁判系统优先裁决。
        official_online = (
            self.scenario_manager.current.key == "OfficialEvent"
            and self.official_feed.is_kill_data_fresh()
        )
        if evidence == "Referee Only" or (evidence == "Auto" and official_online):
            self.state.vision_kill_status = "OFFICIAL_SUPPRESSED" if evidence == "Auto" else "REFEREE_ONLY"
            return
        events = self.vision_kill_detector.process(
            result.detections,
            alliance=self.alliance_side(),
            frame_luminance=self._vision_scene_luminance,
            frame_token=(result.timestamp_ns, result.sequence),
            frame_size=(result.source_width, result.source_height),
            sensitivity=self.setting_mode(self.registry.get("TongjiVisionBridge"), "Vision Kill Sensitivity", "Lab Responsive"),
            loss_evidence=result.loss_evidence,
        )
        self.state.vision_kill_status = self.vision_kill_detector.last_status
        for event in events:
            self.accept_combat_event(event)

    def accept_combat_event(self, event: CombatEvent) -> None:
        effect = self.registry.get("EliminationFX")
        if effect is None:
            return
        evidence = self.setting_mode(effect, "Evidence Mode", "Auto")
        if event.source == "vision" and evidence == "Referee Only":
            return
        if event.source not in ("vision", "preview") and evidence == "Vision Only":
            return
        if event.kind == "elimination":
            if event.source == "vision":
                self.state.visual_kill_count += 1
            else:
                self.state.referee_kill_count += 1
            self.state.kill_streak += 1
        elif event.kind == "death":
            self.state.kill_streak = 0
        self.state.push_event("VISION CONFIRMED" if event.source == "vision" else "Referee elimination")
        self.dynamic_island_last_event = "VISION CONFIRMED" if event.source == "vision" else "Official combat event"
        self.dynamic_island_event_started = time.perf_counter()
        if effect.enabled:
            self.kill_fx.trigger(
                event,
                combo_window=self.get_setting_number(effect, "Combo Window", 5.0),
                sound_enabled=self.setting_bool(effect, "Sound Enabled", True),
                volume=self.get_setting_number(effect, "Sound Volume", 55.0),
                preset=self.setting_mode(effect, "Preset", "Default Scrolling"),
                visibility=self.setting_mode(effect, "Element Visibility", "Preset"),
            )

    def draw_elimination_fx(self, p: QPainter, width: int, height: int) -> None:
        effect = self.registry.get("EliminationFX")
        if effect is None or not effect.enabled:
            return
        team_theme = self.setting_mode(effect, "Team Theme", "Alliance")
        if team_theme == "Alliance":
            team_theme = "CT Blue" if self.alliance_side() == "Blue" else "T Gold"
        self.kill_fx.draw(
            p, width, height,
            preset=self.setting_mode(effect, "Preset", "Default Scrolling"),
            visibility=self.setting_mode(effect, "Element Visibility", "Preset"),
            team=team_theme,
            scale=self.get_setting_number(effect, "Scale", 1.0),
            anchor_policy=self.setting_mode(effect, "Anchor Policy", "Combat Focus"),
            x_offset=self.get_setting_number(effect, "X Offset", 0.0),
            y_offset=self.get_setting_number(effect, "Y Offset", 0.0),
            responsive_scale=self.setting_mode(effect, "Responsive Scale", "Auto") == "Auto",
            device_pixel_ratio=self.devicePixelRatioF(),
        )

    def sync_tongji_vision_state(self) -> None:
        result = self.active_tongji_result()
        self.state.vision_backend = self._vision_snapshot.source if self._vision_snapshot else self._vision_source
        self.state.vision_connected = bool(self._vision_snapshot) if self._vision_source != "Mock" else False
        if result is None:
            self.vision_render_interpolator.clear()
            self._vision_render_result = None
            self.state.vision_tracking_state = "mock" if self._vision_source == "Mock" else "disconnected"
            self.state.vision_calibrated = False
            self.state.vision_detection_count = 0
            self.state.vision_prediction_count = 0
            self.state.target_locked = False
            self.state.lock_state = False
            return
        display_result = self.vision_result_for_display(result)
        if display_result is not None:
            source = self._vision_snapshot.source if self._vision_snapshot else self._vision_source
            self.vision_render_interpolator.push(display_result, source=source)
        calibrated = self.vision_result_calibrated(result)
        self.state.vision_calibrated = calibrated
        # Lock / aim telemetry follows FOV-filtered display result; ESP counts stay full.
        lock_result = display_result if display_result is not None else result
        self.state.vision_tracking_state = lock_result.tracking_state
        self.state.vision_inference_device = result.inference_device
        self.state.vision_inference_fps = result.inference_fps
        self.state.vision_latency_ms = result.latency_ms
        self.state.vision_sequence = result.sequence
        self.state.vision_detection_count = len(result.detections)
        self.state.vision_prediction_count = len(result.predicted_armors)
        self.state.vision_aim_yaw_deg = result.aim_yaw_deg
        self.state.vision_aim_pitch_deg = result.aim_pitch_deg
        target = lock_result.aim_armor
        if target is not None:
            self.state.target_id = target.armor_id if target.armor_id >= 0 else self.state.target_id
            self.state.target_distance_m = target.distance_m or self.state.target_distance_m
            terminal = (
                self.vision_kill_detector.is_extinguished(target)
                or self.vision_kill_detector.is_suppressed(target)
            )
            # Only FOV-admitted aim plates may report LOCK.
            self.state.target_locked = bool(calibrated and lock_result.is_tracking and not terminal)
            self.state.lock_state = self.state.target_locked
        else:
            self.state.target_locked = False
            self.state.lock_state = False

    def tongji_target(self, width: int, height: int, result: VisionResult) -> VisionTarget | None:
        observation = result.aim_armor or next((armor for armor in result.detections if len(armor.points) == 4), None)
        if observation is None or len(observation.points) < 2:
            return None
        x_scale = width / max(1.0, float(result.source_width))
        y_scale = height / max(1.0, float(result.source_height))
        camera_module = self.registry.get("CameraFeed")
        mirror = self.setting_bool(camera_module, "Mirror", False)
        points = [(width - x * x_scale if mirror else x * x_scale, y * y_scale) for x, y in observation.points]
        xs, ys = zip(*points)
        return VisionTarget(
            x=min(xs),
            y=min(ys),
            w=max(4.0, max(xs) - min(xs)),
            h=max(4.0, max(ys) - min(ys)),
            confidence=observation.confidence,
            label=observation.label,
            kind="armor",
        )

    def draw_synthetic_video(self, p: QPainter, width: int, height: int) -> None:
        if self.high_res_optimize(width, height):
            self.draw_synthetic_video_cached(p, width, height)
            return
        self.draw_synthetic_video_scene(p, width, height, lite=False)
        # 1080p 下主画面直接绘制，为 HUD 玻璃额外保留一张轻量图传快照。
        now = time.perf_counter()
        cache_w = min(360, max(220, width // 4))
        cache_h = max(124, int(cache_w * height / max(1, width)))
        key = (cache_w, cache_h)
        if self.synthetic_video_cache is None or self.synthetic_video_cache_key != key or now - self.synthetic_video_cache_time > 0.10:
            image = QImage(cache_w, cache_h, QImage.Format.Format_ARGB32)
            image.fill(color("#101721"))
            cache_p = QPainter(image)
            cache_p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.draw_synthetic_video_scene(cache_p, cache_w, cache_h, lite=True)
            cache_p.end()
            self.synthetic_video_cache = image
            self.synthetic_video_cache_key = key
            self.synthetic_video_cache_time = now
        if self.synthetic_video_cache is not None:
            self.update_hud_liquid_source(self.synthetic_video_cache)

    def draw_synthetic_video_cached(self, p: QPainter, width: int, height: int) -> None:
        now = time.perf_counter()
        cache_w = min(1280, max(640, width // 2))
        cache_h = max(360, int(cache_w * height / max(1, width)))
        key = (cache_w, cache_h)
        if self.synthetic_video_cache is None or self.synthetic_video_cache_key != key or now - self.synthetic_video_cache_time > 0.08:
            image = QImage(cache_w, cache_h, QImage.Format.Format_ARGB32)
            image.fill(color("#101721"))
            cache_p = QPainter(image)
            cache_p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            cache_p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self.draw_synthetic_video_scene(cache_p, cache_w, cache_h, lite=True)
            cache_p.end()
            self.synthetic_video_cache = image
            self.synthetic_video_cache_key = key
            self.synthetic_video_cache_time = now
        if self.synthetic_video_cache is not None:
            self.update_hud_liquid_source(self.synthetic_video_cache)
            p.drawImage(QRectF(0, 0, width, height), self.synthetic_video_cache)

    def update_hud_liquid_source(self, image: QImage) -> None:
        if not self.gpu_compositor.available:
            self.liquid_glass.update("hud", image, QRectF(0, 0, self.width(), self.height()))
        return
        # Unified GPU 直接从背景 FBO 采样。CPU 快照只服务于无 OpenGL 的
        # Compatibility Painter，避免摄像头每个源帧在 UI 线程额外缩放两次。
        if self.gpu_compositor.available:
            return
        self.liquid_glass.update("hud", image, QRectF(0, 0, self.width(), self.height()))

    def draw_hud_liquid_glass(
        self,
        p: QPainter,
        rect: QRectF,
        radius: float,
        *,
        surface: str = "MainGlass",
        hover: float = 0.0,
    ) -> None:
        if self._gpu_frame_recording and self.gpu_compositor.available:
            mapped = p.transform().mapRect(rect)
            self.gpu_compositor.add_glass(
                mapped,
                radius * max(abs(p.transform().m11()), abs(p.transform().m22()), 0.01),
                strength=1.08 if surface in ("ProminentGlass", "LensIsland") else 0.82 if surface == "SubGlass" else 1.0,
                surface="sub" if surface == "SubGlass" else "clear" if surface in ("ProminentGlass", "PolarGlass", "LensIsland") else "main",
                hover=hover,
                opacity=p.opacity(),
                material=(
                    LensMaterial.ISLAND
                    if surface == "LensIsland" or (rect.height() <= 58.0 and radius >= rect.height() * 0.44)
                    else LensMaterial.STRONG
                    if surface in ("ProminentGlass", "PolarGlass")
                    else LensMaterial.REGULAR
                ),
            )
            return
        mode = "polar" if surface == "PolarGlass" else "prominent" if surface in ("ProminentGlass", "LensIsland") else "standard"
        self.liquid_glass.draw(
            p, rect, radius, source="hud", mode=mode,
            surface="sub" if surface == "SubGlass" else "main",
            hover=hover, press=self.liquid_press_amount(rect), pointer=self.hover_point,
            lite=self.high_res_optimize(),
        )

    def liquid_press_amount(self, rect: QRectF) -> float:
        if not rect.contains(self.liquid_press_point):
            return 0.0
        remaining = self.liquid_press_until - time.perf_counter()
        return max(0.0, min(1.0, remaining / 0.12))

    def draw_synthetic_video_scene(self, p: QPainter, width: int, height: int, lite: bool) -> None:
        sky = QLinearGradient(0, 0, 0, height)
        sky.setColorAt(0.0, color("#171d28"))
        sky.setColorAt(0.56, color("#121923"))
        sky.setColorAt(1.0, color("#0a1015"))
        p.fillRect(QRectF(0, 0, width, height), sky)

        horizon = height * 0.57
        p.fillRect(QRectF(0, horizon, width, height - horizon), color("#0c141a"))
        pen = QPen(color("#335063", 0.66), 1.0)
        p.setPen(pen)
        grid_x = 108 if lite else 78
        grid_y = 46 if lite else 34
        for x in range(-width, width * 2, grid_x):
            p.drawLine(QPointF(x, horizon), QPointF(x - width * 0.36, height))
        for y in range(int(horizon), height, grid_y):
            p.drawLine(QPointF(0, y), QPointF(width, y))

        now = time.perf_counter()
        p.setPen(Qt.PenStyle.NoPen)
        particle_count = 24 if lite else 38
        for i in range(particle_count):
            phase = now * 0.38 + i * 1.73
            px = (i * 127.0 + math.sin(phase) * 34.0) % max(1, width)
            py = horizon + ((i * 41.0 + now * 18.0) % max(1.0, height - horizon))
            near = (py - horizon) / max(1.0, height - horizon)
            radius = 1.0 + near * 2.2
            p.setBrush(color("#56fff0", 0.18 + near * 0.18))
            p.drawEllipse(QPointF(px, py), radius, radius)

        p.setPen(QPen(color("#56fff0", 0.18), 1.2))
        p.drawLine(QPointF(0, horizon), QPointF(width, horizon))

        cx = width * 0.5 + math.sin(now * 0.82) * width * 0.17
        base = QRectF(cx - 68, horizon - 112, 136, 94)
        glow_rect(p, base, 6, 0.26 if lite else 0.48)
        rounded_rect(p, base, 5, color("#252d38"), color("#7c8d9f", 0.68), 1.4)
        p.setPen(QPen(color("#56fff0", 0.86), 2))
        p.drawLine(QPointF(base.left() + 16, base.top() + 22), QPointF(base.right() - 16, base.top() + 22))
        self.draw_text(
            p,
            QRectF(0, height - 32, width, 18),
            "合成机器人图传 - 摄像头不可用",
            self.font("poppins_regular", 8.5),
            color("#9aa6ac"),
            Qt.AlignmentFlag.AlignCenter,
        )

    def draw_startup_background(self, p: QPainter, width: int, height: int) -> None:
        module = self.registry.get("StartupVisual")
        mode = self.setting_mode(module, "Background Mode", "VideoParallax")
        profile = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
        parallax = self.get_setting_number(module, "Parallax Strength", 22.0)
        zoom = self.get_setting_number(module, "Background Zoom", 1.00)
        dim = self.get_setting_number(module, "Dim Overlay", 0.28)
        motion_quality = self.setting_mode(module, "Motion Quality", "Smooth60")
        if mode != "ParticleGrid":
            drawn = self.startup_wallpaper.draw(
                p,
                QRectF(0, 0, width, height),
                self.hover_point,
                self.frame_dt,
                mode=mode,
                profile=profile,
                parallax=parallax,
                zoom=zoom,
                dim=dim,
                high_res=self.high_res_optimize(width, height),
                motion_quality=motion_quality,
            )
            if drawn:
                if not self._gpu_frame_recording:
                    self.liquid_glass.update(
                        "startup",
                        self.startup_wallpaper.last_frame,
                        self.startup_wallpaper.last_draw_rect,
                        soft=self.startup_wallpaper.soft_glass_frame,
                        lens=self.startup_wallpaper.glass_frame,
                    )
                return
        self.draw_particle_grid_background(p, width, height)

    def draw_particle_grid_background(self, p: QPainter, width: int, height: int) -> None:
        now = time.perf_counter()
        lite = self.high_res_optimize(width, height)
        bg = QLinearGradient(0, 0, 0, height)
        bg.setColorAt(0.0, color("#060910"))
        bg.setColorAt(0.52, color("#0c111b"))
        bg.setColorAt(1.0, color("#05070c"))
        p.fillRect(QRectF(0, 0, width, height), bg)

        horizon = height * 0.58
        mouse = self.hover_point
        if self.home_visible:
            target_x = mouse.x() if mouse.x() > 1 or mouse.y() > 1 else width * 0.5
            target_y = mouse.y() if mouse.x() > 1 or mouse.y() > 1 else height * 0.45
            mouse = QPointF(
                self.anim.value("startup.bg.mouse.x", target_x, self.anim_duration(0.12), Easings.ease_out_sine, initial=width * 0.5),
                self.anim.value("startup.bg.mouse.y", target_y, self.anim_duration(0.12), Easings.ease_out_sine, initial=height * 0.45),
            )
        spacing = max(52.0, min(88.0, width / (15.5 if lite else 18.0)))
        points: list[QPointF] = []
        row_count = 7 if lite else 9
        for row in range(0, row_count):
            depth = row / max(1.0, row_count - 1.0)
            y = horizon + depth * depth * height * 0.46
            row_spacing = spacing * (0.72 + depth * 1.15)
            offset = (now * 18.0 + row * 31.0) % row_spacing
            x = -row_spacing + offset
            while x < width + row_spacing:
                dx = x - mouse.x()
                dy = y - mouse.y()
                dist = math.sqrt(dx * dx + dy * dy)
                pull = max(0.0, 1.0 - dist / 260.0)
                wave = math.sin(now * 1.7 + x * 0.013 + row * 0.8) * 5.0
                px = x + dx * pull * 0.035
                py = y + wave + dy * pull * 0.025
                points.append(QPointF(px, py))
                x += row_spacing

        glow_band = QLinearGradient(0, horizon - 70, 0, horizon + 120)
        glow_band.setColorAt(0.0, color("#56fff0", 0.00))
        glow_band.setColorAt(0.48, color("#56fff0", 0.10))
        glow_band.setColorAt(1.0, color("#ff65df", 0.035))
        p.fillRect(QRectF(0, horizon - 70, width, 190), glow_band)

        p.setPen(QPen(color("#2f6173", 0.62), 1.0))
        for point in points:
            p.drawLine(QPointF(point.x(), horizon), point)
        for index, a in enumerate((0.34, 0.20, 0.11)):
            p.setPen(QPen(color("#56fff0", a), 1.0 + index * 0.45))
            for i, point in enumerate(points):
                if i + 1 < len(points) and abs(points[i + 1].y() - point.y()) < spacing * 0.75:
                    p.drawLine(point, points[i + 1])

        p.setPen(Qt.PenStyle.NoPen)
        star_count = 28 if lite else 42
        for i in range(star_count):
            drift = now * (10.0 + i % 5) + i * 97.0
            px = (drift + math.sin(now * 0.7 + i) * 42.0) % max(1, width)
            py = height * (0.10 + ((i * 0.071 + now * 0.006) % 0.42))
            pulse = 0.5 + 0.5 * math.sin(now * 2.1 + i * 0.53)
            p.setBrush(color("#56fff0", 0.10 + pulse * 0.13))
            p.drawEllipse(QPointF(px, py), 0.8 + pulse * 1.0, 0.8 + pulse * 1.0)

        for i, point in enumerate(points):
            dx = point.x() - mouse.x()
            dy = point.y() - mouse.y()
            dist = math.sqrt(dx * dx + dy * dy)
            pulse = 0.5 + 0.5 * math.sin(now * 3.2 + i * 0.37)
            near = max(0.0, 1.0 - dist / 230.0)
            radius = 1.8 + 2.8 * near + 1.0 * pulse
            c = QColor.fromHsvF((0.48 + i * 0.006 + now * 0.015) % 1.0, 0.62, 1.0, 0.34 + 0.48 * near)
            p.setBrush(c)
            p.drawEllipse(point, radius, radius)

        orb = QLinearGradient(0, 0, width, height)
        orb.setColorAt(0.0, color("#56fff0", 0.12))
        orb.setColorAt(0.55, color("#ff65df", 0.065))
        orb.setColorAt(1.0, color("#000000", 0.0))
        p.fillRect(QRectF(0, 0, width, height), orb)

    def draw_startup_screen(self, p: QPainter, width: int, height: int) -> None:
        active = self.anim.value("startup.open", 1.0, self.anim_duration(0.34), Easings.ease_out_pow4, initial=0.0)
        scenario_module = self.registry.get("Scenario")
        style_setting = scenario_module.get_setting("Startup Style") if scenario_module else None
        if style_setting is not None and str(style_setting.value) == "PolarLauncher":
            self.draw_startup_scene_launcher(p, width, height, active)
        else:
            self.draw_liquid_startup_scene_launcher(p, width, height, active)
        return
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#020205", 0.42))

        scale = max(0.86, min(1.85, self.get_auto_ui_scale(width, height, strength=0.65)))
        title_font = self.font("museo", 30 * scale, QFont.Weight.Bold)
        body_font = self.font("poppins_medium", 10.5 * scale)
        small_font = self.font("poppins_regular", 8.0 * scale)
        menu_w = min(430.0 * scale, width - 88.0)
        row_h = 62.0 * scale
        gap = 11.0 * scale
        total_h = row_h * 3 + gap * 2
        x = width / 2 - menu_w / 2
        y = height / 2 - total_h / 2 + 22.0 * scale

        logo_y = max(72.0 * scale, y - 92.0 * scale)
        glow_text(p, "POLAR-RM", x, logo_y, title_font, THEME.text, THEME.cyan, 8 * scale)
        self.draw_text(p, QRectF(x, logo_y + 10 * scale, menu_w, 44 * scale), "CUSTOM CLIENT", body_font, THEME.muted, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        order = ["OfficialEvent", "CampusSimulation", "LabDebug"]
        for index, key in enumerate(order):
            config = SCENARIOS[key]
            rect = QRectF(x, y + index * (row_h + gap), menu_w, row_h)
            hovered = rect.contains(self.hover_point)
            hover_v = self.anim.value(f"startup.hover.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.18), Easings.ease_out_quad)
            slide = (1.0 - active) * 28.0 * scale + (1.0 - hover_v) * 0.0
            draw_rect = rect.adjusted(slide, 0, -slide, 0)
            accent = self.startup_menu_accent(index)
            glow_rect(p, draw_rect, 9 * scale, 0.12 + 0.10 * hover_v)
            rounded_rect(p, draw_rect, 8 * scale, color("#09090d", 0.88 + 0.05 * hover_v), color("#ffffff", 0.10 + 0.16 * hover_v))
            p.fillRect(QRectF(draw_rect.left() + 3 * scale, draw_rect.top() + 3 * scale, 3 * scale, draw_rect.height() - 6 * scale), accent)
            self.draw_text(p, draw_rect.adjusted(18 * scale, 9 * scale, -104 * scale, -28 * scale), config.title, self.font("poppins_bold", 13.2 * scale), THEME.text)
            self.draw_text(p, draw_rect.adjusted(18 * scale, 31 * scale, -18 * scale, -8 * scale), config.subtitle, small_font, THEME.muted)
            safety = "MOCK" if config.safety.mock_writes else "LIVE"
            chip = QRectF(draw_rect.right() - 82 * scale, draw_rect.center().y() - 11 * scale, 64 * scale, 22 * scale)
            rounded_rect(p, chip, 7 * scale, color("#ffffff", 0.055), color("#ffffff", 0.10 + 0.12 * hover_v))
            self.draw_text(p, chip, safety, self.font("poppins_medium", 7.3 * scale), accent, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(draw_rect, "select_scenario", key, tooltip=config.description)

        current = self.scenario_manager.current
        footer = f"{current.title} | MQTT {current.connection.mqtt_host}:{current.connection.mqtt_port} | UDP {current.connection.udp_port}"
        self.draw_text(p, QRectF(x, y + total_h + 22 * scale, menu_w, 18 * scale), f"Step 1/3 | {footer}", small_font, color("#888890"), Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_robot_profile_screen(self, p: QPainter, width: int, height: int) -> None:
        scale = max(0.72, min(1.12, self.get_auto_ui_scale(width, height, strength=0.42)))
        profiles = profiles_for_match(self.match_mode_manager.current.key)
        selected = self.current_robot_profile_key()
        top = 112 * scale
        margin = 48 * scale
        columns = 4 if width >= 1500 else 3
        gap = 14 * scale
        usable_w = width - margin * 2
        card_w = (usable_w - gap * (columns - 1)) / columns
        card_h = min(135 * scale, (height - top - 90 * scale) / max(1, math.ceil(len(profiles) / columns)) - gap)
        self.draw_text(p, QRectF(0, 38 * scale, width, 30 * scale), "ROBOT PROFILE · STEP 3/3", self.font("poppins_bold", 12 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
        for index, profile in enumerate(profiles):
            rect = QRectF(margin + (index % columns) * (card_w + gap), top + (index // columns) * (card_h + gap), card_w, card_h)
            accent = self.startup_menu_accent(index + 1)
            self.draw_liquid_glass_panel(p, rect, 12 * scale, accent=accent, hover=0.55 if profile.key == selected else 0.0, scale=scale)
            self.draw_text(p, rect.adjusted(18 * scale, 14 * scale, -18 * scale, -rect.height() + 40 * scale), f"{profile.short_title}  ·  ID {profile.robot_id}", self.font("poppins_bold", 10 * scale), THEME.text)
            self.draw_text(p, rect.adjusted(18 * scale, 49 * scale, -18 * scale, -12 * scale), profile.description, self.font("poppins_regular", 7.4 * scale), THEME.muted, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.add_hotspot(rect, "select_robot_profile", profile.key)
        back = QRectF(margin, height - 55 * scale, 110 * scale, 34 * scale)
        self.draw_liquid_glass_panel(p, back, 11 * scale, accent=THEME.cyan, hover=0.0, scale=scale)
        self.draw_text(p, back, "<  BACK", self.font("poppins_bold", 7.5 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(back, "startup_back_match")

    def draw_match_mode_screen(self, p: QPainter, width: int, height: int) -> None:
        active = self.anim.value("startup.match.open", 1.0, self.anim_duration(0.34), Easings.ease_out_pow4, initial=0.0)
        scenario_module = self.registry.get("Scenario")
        style_setting = scenario_module.get_setting("Startup Style") if scenario_module else None
        if style_setting is not None and str(style_setting.value) == "PolarLauncher":
            self.draw_startup_match_launcher(p, width, height, active)
        else:
            self.draw_liquid_startup_match_launcher(p, width, height, active)
        return
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#020205", 0.44))

        scale = max(0.86, min(1.85, self.get_auto_ui_scale(width, height, strength=0.65)))
        title_font = self.font("museo", 28 * scale, QFont.Weight.Bold)
        body_font = self.font("poppins_medium", 10.5 * scale)
        small_font = self.font("poppins_regular", 8.0 * scale)
        menu_w = min(470.0 * scale, width - 88.0)
        row_h = 76.0 * scale
        gap = 12.0 * scale
        total_h = row_h * len(MATCH_MODE_KEYS) + gap * (len(MATCH_MODE_KEYS) - 1)
        x = width / 2 - menu_w / 2
        y = height / 2 - total_h / 2 + 38.0 * scale

        logo_y = max(74.0 * scale, y - 104.0 * scale)
        glow_text(p, "MATCH MODE", x, logo_y, title_font, THEME.text, THEME.cyan, 8 * scale)
        self.draw_text(p, QRectF(x, logo_y + 10 * scale, menu_w, 44 * scale), self.scenario_manager.current.title.upper(), body_font, THEME.muted, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for index, key in enumerate(MATCH_MODE_KEYS):
            config = MATCH_MODES[key]
            rect = QRectF(x, y + index * (row_h + gap), menu_w, row_h)
            hovered = rect.contains(self.hover_point)
            hover_v = self.anim.value(f"startup.match.hover.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.18), Easings.ease_out_quad)
            draw_rect = rect.adjusted((1.0 - active) * 20.0 * scale, 0, 0, 0)
            accent = self.startup_menu_accent(index + 2)
            glow_rect(p, draw_rect, 10 * scale, 0.14 + 0.10 * hover_v)
            rounded_rect(p, draw_rect, 8 * scale, color("#09090d", 0.90 + 0.05 * hover_v), color("#ffffff", 0.10 + 0.16 * hover_v))
            p.fillRect(QRectF(draw_rect.left() + 3 * scale, draw_rect.top() + 3 * scale, 3 * scale, draw_rect.height() - 6 * scale), accent)
            self.draw_text(p, draw_rect.adjusted(18 * scale, 8 * scale, -140 * scale, -45 * scale), config.title, self.font("poppins_bold", 13.6 * scale), THEME.text)
            details = f"{config.field.width_m:g}m x {config.field.height_m:g}m | official map asset | {config.duration_sec // 60}:{config.duration_sec % 60:02d}"
            self.draw_text(p, draw_rect.adjusted(18 * scale, 34 * scale, -18 * scale, -24 * scale), config.subtitle, small_font, THEME.muted)
            self.draw_text(p, draw_rect.adjusted(18 * scale, 52 * scale, -18 * scale, -6 * scale), details, small_font, color("#9fa7ad"))
            chip = QRectF(draw_rect.right() - 110 * scale, draw_rect.center().y() - 12 * scale, 88 * scale, 24 * scale)
            rounded_rect(p, chip, 7 * scale, color("#ffffff", 0.055), color("#ffffff", 0.10 + 0.12 * hover_v))
            self.draw_text(p, chip, "NEXT", self.font("poppins_medium", 7.3 * scale), accent, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(draw_rect, "select_match_mode", key, tooltip=f"载入 {config.title} 官方地图和默认 HUD。")

        footer = "Step 2/3 | Backspace: scenario | Enter: robot selection"
        self.draw_text(p, QRectF(x, y + total_h + 22 * scale, menu_w, 18 * scale), footer, small_font, color("#888890"), Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_startup_scene_launcher(self, p: QPainter, width: int, height: int, active: float) -> None:
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#020205", 0.34))
        self.draw_startup_vignette(p, width, height)

        scale = max(0.82, min(1.65, self.get_auto_ui_scale(width, height, strength=0.65)))
        title_font = self.font("museo", 34 * scale, QFont.Weight.Bold)
        body_font = self.font("poppins_medium", 10.5 * scale)
        small_font = self.font("poppins_regular", 8.0 * scale)
        gap = 18.0 * scale
        card_w = min(292.0 * scale, (width - 112.0 * scale - gap * 2.0) / 3.0)
        card_h = 166.0 * scale
        total_w = card_w * 3.0 + gap * 2.0
        x = width / 2.0 - total_w / 2.0
        y = height / 2.0 - card_h / 2.0 + 26.0 * scale

        logo_y = max(78.0 * scale, y - 112.0 * scale)
        glow_text(p, "POLAR-RM", x, logo_y, title_font, THEME.text, THEME.cyan, 9 * scale)
        self.draw_text(p, QRectF(x, logo_y + 11 * scale, total_w, 42 * scale), "LAUNCHER / SCENE SELECT", body_font, THEME.muted, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.draw_text(p, QRectF(x, logo_y + 46 * scale, total_w, 18 * scale), "选择运行环境", self.font("poppins_medium", 8.5 * scale), color("#c9d6dc", 0.90))

        for index, key in enumerate(("OfficialEvent", "CampusSimulation", "LabDebug")):
            config = SCENARIOS[key]
            meta = self.startup_scenario_meta(key)
            rect = QRectF(x + index * (card_w + gap), y, card_w, card_h)
            detail = f"MQTT {config.connection.mqtt_host}:{config.connection.mqtt_port}"
            chip = "MOCK" if config.safety.mock_writes else "LIVE"
            self.draw_startup_icon_card(
                p,
                rect,
                index,
                key,
                meta["icon"],
                meta["title"],
                meta["subtitle"],
                detail,
                chip,
                "select_scenario",
                key,
                meta["tooltip"],
                self.startup_menu_accent(index),
                scale,
                active,
            )

        current_meta = self.startup_scenario_meta(self.scenario_manager.current.key)
        footer = f"Step 1/3 | 当前: {current_meta['title']} | 按 1/2/3 快速选择"
        self.draw_text(p, QRectF(x, y + card_h + 27 * scale, total_w, 18 * scale), footer, small_font, color("#aeb7bd", 0.88), Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_startup_match_launcher(self, p: QPainter, width: int, height: int, active: float) -> None:
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#020205", 0.36))
        self.draw_startup_vignette(p, width, height)

        scale = max(0.82, min(1.65, self.get_auto_ui_scale(width, height, strength=0.65)))
        title_font = self.font("museo", 32 * scale, QFont.Weight.Bold)
        body_font = self.font("poppins_medium", 10.5 * scale)
        small_font = self.font("poppins_regular", 8.0 * scale)
        gap = 24.0 * scale
        card_w = min(370.0 * scale, (width - 112.0 * scale - gap) / 2.0)
        card_h = 186.0 * scale
        total_w = card_w * 2.0 + gap
        x = width / 2.0 - total_w / 2.0
        y = height / 2.0 - card_h / 2.0 + 30.0 * scale

        scenario_meta = self.startup_scenario_meta(self.scenario_manager.current.key)
        logo_y = max(78.0 * scale, y - 116.0 * scale)
        glow_text(p, "MATCH MODE", x, logo_y, title_font, THEME.text, THEME.cyan, 9 * scale)
        self.draw_text(p, QRectF(x, logo_y + 11 * scale, total_w, 42 * scale), scenario_meta["title"].upper(), body_font, THEME.muted, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.draw_text(p, QRectF(x, logo_y + 46 * scale, total_w, 18 * scale), "选择比赛制式", self.font("poppins_medium", 8.5 * scale), color("#c9d6dc", 0.90))

        for index, key in enumerate(MATCH_MODE_KEYS):
            config = MATCH_MODES[key]
            meta = self.startup_match_meta(key)
            rect = QRectF(x + index * (card_w + gap), y, card_w, card_h)
            detail = f"{config.field.width_m:g}m x {config.field.height_m:g}m | {config.duration_sec // 60}:{config.duration_sec % 60:02d}"
            self.draw_startup_icon_card(
                p,
                rect,
                index,
                f"match.{key}",
                meta["icon"],
                meta["title"],
                meta["subtitle"],
                detail,
                "NEXT",
                "select_match_mode",
                key,
                meta["tooltip"],
                self.startup_menu_accent(index + 2),
                scale,
                active,
            )

        footer = "Step 2/3 | Backspace 返回 | Enter 选择机器人"
        self.draw_text(p, QRectF(x, y + card_h + 27 * scale, total_w, 18 * scale), footer, small_font, color("#aeb7bd", 0.88), Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_startup_vignette(self, p: QPainter, width: int, height: int) -> None:
        p.drawImage(QRectF(0, 0, width, height), self.startup_cache.vignette(width, height))

    def draw_liquid_startup_scene_launcher(self, p: QPainter, width: int, height: int, active: float) -> None:
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#071018", 0.035))
        self.draw_startup_vignette(p, width, height)

        scale = max(0.74, min(1.14, self.get_auto_ui_scale(width, height, strength=0.45)))
        menu_x, menu_y, button_w, button_h, gap = self.liquid_menu_layout(width, height, 3, scale)
        self.draw_liquid_menu_header(p, width, height, scale, "SCENE SELECT", "Choose runtime environment", active)

        for index, key in enumerate(("OfficialEvent", "CampusSimulation", "LabDebug")):
            config = SCENARIOS[key]
            meta = self.startup_scenario_meta(key)
            rect = QRectF(menu_x, menu_y + index * (button_h + gap), button_w, button_h)
            detail = f"MQTT {config.connection.mqtt_host}:{config.connection.mqtt_port}  UDP {config.connection.udp_port}"
            chip = "LIVE" if not config.safety.mock_writes else "MOCK"
            self.draw_liquid_main_button(
                p,
                rect,
                index,
                f"scene.{key}",
                meta["icon"],
                meta["title"],
                meta["subtitle"],
                detail,
                chip,
                "select_scenario",
                key,
                meta["tooltip"],
                self.startup_menu_accent(index),
                scale,
                active,
            )

        self.draw_liquid_status_panel(p, menu_x, menu_y, button_w, height, scale, "scenario", active)
        self.draw_liquid_bottom_bar(p, width, height, scale, active)
        p.restore()

    def draw_liquid_startup_match_launcher(self, p: QPainter, width: int, height: int, active: float) -> None:
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#071018", 0.035))
        self.draw_startup_vignette(p, width, height)

        scale = max(0.74, min(1.14, self.get_auto_ui_scale(width, height, strength=0.45)))
        menu_x, menu_y, button_w, button_h, gap = self.liquid_menu_layout(width, height, 3, scale)
        scenario_meta = self.startup_scenario_meta(self.scenario_manager.current.key)
        self.draw_liquid_menu_header(p, width, height, scale, "MATCH MODE", f"{scenario_meta['title']} profile", active)

        for index, key in enumerate(MATCH_MODE_KEYS):
            config = MATCH_MODES[key]
            meta = self.startup_match_meta(key)
            rect = QRectF(menu_x, menu_y + index * (button_h + gap), button_w, button_h)
            detail = f"{config.field.width_m:g}m x {config.field.height_m:g}m  {config.duration_sec // 60}:{config.duration_sec % 60:02d}  official map"
            self.draw_liquid_main_button(
                p,
                rect,
                index,
                f"match.{key}",
                meta["icon"],
                meta["title"],
                meta["subtitle"],
                detail,
                "NEXT",
                "select_match_mode",
                key,
                meta["tooltip"],
                self.startup_menu_accent(index + 2),
                scale,
                active,
            )

        back_rect = QRectF(menu_x, menu_y + 2 * (button_h + gap), button_w, button_h)
        self.draw_liquid_main_button(
            p,
            back_rect,
            2,
            "match.back",
            "<",
            "Back",
            "Return to scene select",
            "Backspace also works",
            "BACK",
            "startup_back",
            None,
            "Return to the scene launcher.",
            THEME.pink,
            scale,
            active,
        )

        self.draw_liquid_status_panel(p, menu_x, menu_y, button_w, height, scale, "match", active)
        self.draw_liquid_bottom_bar(p, width, height, scale, active)
        p.restore()

    def liquid_menu_layout(self, width: int, height: int, count: int, scale: float) -> tuple[float, float, float, float, float]:
        margin = 50.0 * scale
        button_w = min(590.0 * scale, max(430.0 * scale, width * 0.50))
        button_w = min(button_w, width - margin * 2.0)
        button_h = 118.0 * scale
        gap = 18.0 * scale
        total_h = button_h * count + gap * (count - 1)
        y = max(112.0 * scale, height / 2.0 - total_h / 2.0 + 16.0 * scale)
        max_y = max(94.0 * scale, height - total_h - 105.0 * scale)
        y = min(y, max_y)
        return margin, y, button_w, button_h, gap

    def startup_stagger_value(self, index: int, duration: float = 0.40, delay: float = 0.10) -> float:
        elapsed = time.perf_counter() - getattr(self, "startup_transition_started", time.perf_counter())
        elapsed -= max(0, index) * self.anim_duration(delay)
        if elapsed <= 0.0:
            return 0.0
        return Easings.back_out(elapsed / self.anim_duration(duration))

    def mix_color(self, a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            round(a.red() + (b.red() - a.red()) * t),
            round(a.green() + (b.green() - a.green()) * t),
            round(a.blue() + (b.blue() - a.blue()) * t),
            round(a.alpha() + (b.alpha() - a.alpha()) * t),
        )

    @staticmethod
    def startup_menu_accent(index: int) -> QColor:
        """启动页使用稳定语义色，不用时间驱动色相漂移。"""
        palette = ("#66a8ff", "#5fd3aa", "#f0bf68", "#9f92ff")
        return color(palette[index % len(palette)])

    def startup_glass_settings(self) -> tuple[str, float]:
        module = self.registry.get("StartupVisual")
        style = self.setting_mode(module, "Glass Style", "LiquidGlass")
        strength = max(0.40, min(1.40, self.get_setting_number(module, "Glass Strength", 1.0)))
        return style, strength

    def draw_liquid_glass_panel(
        self,
        p: QPainter,
        rect: QRectF,
        radius: float,
        *,
        accent: QColor | None = None,
        hover: float = 0.0,
        scale: float = 1.0,
        sample_background: bool = True,
        surface: str = "MainGlass",
    ) -> None:
        accent = accent or THEME.cyan
        hover = max(0.0, min(1.0, hover))
        glass_style, strength = self.startup_glass_settings()
        if glass_style == "Legacy":
            self.draw_legacy_glass_panel(p, rect, radius, accent, hover, scale, sample_background)
            return
        if self._gpu_frame_recording and self.gpu_compositor.available:
            mapped = p.transform().mapRect(rect)
            self.gpu_compositor.add_glass(
                mapped,
                radius * max(abs(p.transform().m11()), abs(p.transform().m22()), 0.01),
                strength=strength * (1.10 if surface == "ModalGlass" else 0.78 if surface == "SubGlass" else 1.0),
                surface="sub" if surface == "SubGlass" else "clear" if surface == "ProminentGlass" else "main",
                hover=hover,
                opacity=p.opacity(),
                material=(
                    LensMaterial.ISLAND
                    if rect.height() <= 58.0 and radius >= rect.height() * 0.44
                    else LensMaterial.STRONG
                    if surface in ("ModalGlass", "ProminentGlass")
                    else LensMaterial.REGULAR
                ),
            )
            return
        mode = "prominent" if surface == "ModalGlass" or hover > 0.34 else "standard"
        self.liquid_glass.draw(
            p, rect, radius, source="startup", mode=mode,
            surface="sub" if surface == "SubGlass" else "main",
            hover=hover * strength, press=self.liquid_press_amount(rect), pointer=self.hover_point,
            lite=self.high_res_optimize(),
        )

    def draw_legacy_glass_panel(
        self,
        p: QPainter,
        rect: QRectF,
        radius: float,
        accent: QColor,
        hover: float,
        scale: float,
        sample_background: bool,
    ) -> None:
        # Legacy 是普通半透明面板，不再复用旧镜片采样链路。
        rounded_rect(p, rect, radius, color("#16212b", 0.34), color("#ffffff", 0.18 + 0.12 * hover), 1.0 * scale)
        if hover > 0.001:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(with_alpha(accent, 0.28 * hover), 1.1 * scale))
            p.drawRoundedRect(rect.adjusted(-1.0 * scale, -1.0 * scale, 1.0 * scale, 1.0 * scale), radius + scale, radius + scale)

    def draw_liquid_icon(self, p: QPainter, rect: QRectF, icon: str, c: QColor, scale: float) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(c, max(1.8, 2.4 * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx = rect.center().x()
        cy = rect.center().y()
        r = min(rect.width(), rect.height()) * 0.34
        key = icon.lower()
        if key in ("official", "dji"):
            shield = QPolygonF(
                [
                    QPointF(cx, cy - r),
                    QPointF(cx + r * 0.82, cy - r * 0.56),
                    QPointF(cx + r * 0.65, cy + r * 0.58),
                    QPointF(cx, cy + r),
                    QPointF(cx - r * 0.65, cy + r * 0.58),
                    QPointF(cx - r * 0.82, cy - r * 0.56),
                ]
            )
            p.drawPolygon(shield)
            p.drawLine(QPointF(cx - r * 0.42, cy), QPointF(cx + r * 0.42, cy))
            p.drawLine(QPointF(cx, cy - r * 0.48), QPointF(cx, cy + r * 0.58))
        elif key in ("sim", "campus"):
            nodes = [
                QPointF(cx - r * 0.72, cy + r * 0.22),
                QPointF(cx, cy - r * 0.58),
                QPointF(cx + r * 0.78, cy + r * 0.18),
                QPointF(cx + r * 0.08, cy + r * 0.72),
            ]
            for a, b in ((0, 1), (1, 2), (0, 3), (2, 3)):
                p.drawLine(nodes[a], nodes[b])
            for point in nodes:
                p.drawEllipse(point, r * 0.18, r * 0.18)
        elif key in ("lab", "debug"):
            p.drawLine(QPointF(cx - r * 0.30, cy - r * 0.82), QPointF(cx + r * 0.30, cy - r * 0.82))
            p.drawLine(QPointF(cx - r * 0.14, cy - r * 0.76), QPointF(cx - r * 0.14, cy - r * 0.18))
            p.drawLine(QPointF(cx + r * 0.14, cy - r * 0.76), QPointF(cx + r * 0.14, cy - r * 0.18))
            flask = QPolygonF(
                [
                    QPointF(cx - r * 0.14, cy - r * 0.18),
                    QPointF(cx - r * 0.72, cy + r * 0.72),
                    QPointF(cx + r * 0.72, cy + r * 0.72),
                    QPointF(cx + r * 0.14, cy - r * 0.18),
                ]
            )
            p.drawPolygon(flask)
            p.drawLine(QPointF(cx - r * 0.46, cy + r * 0.30), QPointF(cx + r * 0.48, cy + r * 0.30))
        elif key in ("rmuc", "rmul", "7v7", "3v3"):
            label = "7" if "7" in key or key == "rmuc" else "3"
            # 比赛模式已经由外层圆形图标承载，不再叠加一个小方框。
            self.draw_text(p, rect, label, self.font("poppins_bold", 24.0 * scale), c, Qt.AlignmentFlag.AlignCenter)
            p.setPen(QPen(with_alpha(c, 0.64), max(1.0, 1.2 * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx - r * 0.42, cy + r * 0.53), QPointF(cx + r * 0.42, cy + r * 0.53))
        else:
            p.drawLine(QPointF(cx + r * 0.55, cy), QPointF(cx - r * 0.35, cy - r * 0.55))
            p.drawLine(QPointF(cx - r * 0.35, cy - r * 0.55), QPointF(cx - r * 0.35, cy + r * 0.55))
            p.drawLine(QPointF(cx - r * 0.35, cy + r * 0.55), QPointF(cx + r * 0.55, cy))
        p.restore()

    def draw_liquid_menu_header(self, p: QPainter, width: int, height: int, scale: float, title: str, subtitle: str, active: float) -> None:
        enter = self.startup_stagger_value(0, 0.70, 0.0)
        y = 42.0 * scale - (1.0 - enter) * 95.0 * scale
        x = 50.0 * scale
        p.save()
        p.setOpacity(active * max(0.0, min(1.0, enter)))
        glow_text(p, "POLAR-RM", x, y, self.font("museo", 28.0 * scale, QFont.Weight.Bold), THEME.text, THEME.cyan, 8.0 * scale)
        self.draw_text(p, QRectF(x, y + 11.0 * scale, 330.0 * scale, 24.0 * scale), "CUSTOM CLIENT", self.font("poppins_medium", 8.5 * scale), THEME.muted)

        notice_w = min(420.0 * scale, width * 0.36)
        notice = QRectF(width / 2.0 - notice_w / 2.0, 28.0 * scale, notice_w, 40.0 * scale)
        self.draw_liquid_glass_panel(p, notice, 15.0 * scale, accent=THEME.cyan, hover=0.0, scale=scale)
        self.draw_glass_text(p, notice.adjusted(18.0 * scale, 4.0 * scale, -18.0 * scale, -19.0 * scale), title, self.font("poppins_bold", 9.0 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
        self.draw_glass_text(p, notice.adjusted(18.0 * scale, 19.0 * scale, -18.0 * scale, -4.0 * scale), subtitle, self.font("poppins_regular", 7.0 * scale), THEME.muted, Qt.AlignmentFlag.AlignCenter)

        profile = self.current_profile()
        profile_w = min(230.0 * scale, width * 0.22)
        profile_rect = QRectF(width - profile_w - 50.0 * scale, 34.0 * scale, profile_w, 28.0 * scale)
        self.draw_liquid_glass_panel(p, profile_rect, 10.0 * scale, accent=THEME.cyan, hover=0.0, scale=scale)
        self.draw_glass_text(p, profile_rect.adjusted(12.0 * scale, 0, -12.0 * scale, 0), f"PROFILE  {profile}", self.font("poppins_medium", 7.2 * scale), color("#d8e5ec", 0.92), Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_liquid_main_button(
        self,
        p: QPainter,
        rect: QRectF,
        index: int,
        anim_key: str,
        icon: str,
        title: str,
        subtitle: str,
        detail: str,
        chip_text: str,
        action: str,
        payload: Any,
        tooltip: str,
        accent: QColor,
        scale: float,
        active: float,
    ) -> None:
        enter = self.startup_stagger_value(index, 0.42, 0.10)
        hovered = rect.contains(self.hover_point)
        hover_v = self.anim.value(f"startup.lb.hover.{anim_key}", 1.0 if hovered else 0.0, self.anim_duration(0.16), Easings.ease_out_expo)
        draw_rect = QRectF(rect)
        draw_rect.translate(0.0, 10.0 * (1.0 - enter) * scale - 3.0 * hover_v * scale)
        opacity = active * max(0.0, min(1.0, enter))
        radius = 5.0 * scale

        p.save()
        p.setOpacity(opacity)
        self.draw_liquid_glass_panel(p, draw_rect, radius, accent=accent, hover=hover_v, scale=scale)

        if hover_v > 0.001:
            p.setPen(QPen(with_alpha(accent, 0.18 * hover_v), 1.0))
            p.setBrush(with_alpha(accent, 0.045 * hover_v))
            p.drawRoundedRect(draw_rect, radius, radius)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(accent, 0.86))
        p.drawRoundedRect(QRectF(draw_rect.left(), draw_rect.top(), 4.0 * scale, draw_rect.height()), radius, radius)

        icon_size = min(90.0 * scale, draw_rect.height() - 28.0 * scale)
        icon_rect = QRectF(draw_rect.left() + 26.0 * scale, draw_rect.center().y() - icon_size / 2.0, icon_size, icon_size)
        icon_fill = self.mix_color(accent, THEME.text, hover_v)
        icon_text = self.mix_color(THEME.text, accent, hover_v)
        rounded_rect(p, icon_rect, icon_size * 0.50, with_alpha(icon_fill, 0.92), color("#ffffff", 0.10 + 0.13 * hover_v), 1.0)
        self.draw_liquid_icon(p, icon_rect.adjusted(14.0 * scale, 14.0 * scale, -14.0 * scale, -14.0 * scale), icon, icon_text, scale)

        text_left = icon_rect.right() + 24.0 * scale
        title_rect = QRectF(text_left, draw_rect.top() + 21.0 * scale, draw_rect.width() - (text_left - draw_rect.left()) - 126.0 * scale, 28.0 * scale)
        self.draw_glass_text(p, title_rect, title, self.font("poppins_bold", 18.0 * scale), THEME.text)
        self.draw_glass_text(p, QRectF(text_left, draw_rect.top() + 50.0 * scale, draw_rect.width() - (text_left - draw_rect.left()) - 42.0 * scale, 20.0 * scale), subtitle, self.font("poppins_regular", 9.0 * scale), color("#e1e8ee", 0.88))
        self.draw_glass_text(p, QRectF(text_left, draw_rect.bottom() - 31.0 * scale, draw_rect.width() - (text_left - draw_rect.left()) - 42.0 * scale, 18.0 * scale), detail, self.font("poppins_regular", 7.3 * scale), color("#aeb7bd", 0.90))

        shortcut = QRectF(draw_rect.right() - 78.0 * scale, draw_rect.top() + 20.0 * scale, 26.0 * scale, 22.0 * scale)
        rounded_rect(p, shortcut, 6.0 * scale, color("#ffffff", 0.08), color("#ffffff", 0.11 + 0.11 * hover_v))
        self.draw_text(p, shortcut, str(index + 1) if action != "startup_back" else "B", self.font("poppins_bold", 7.3 * scale), icon_text if hover_v > 0.55 else accent, Qt.AlignmentFlag.AlignCenter)

        chip_w = min(98.0 * scale, max(62.0 * scale, text_width(p, self.font("poppins_medium", 7.2 * scale), chip_text) + 22.0 * scale))
        chip = QRectF(draw_rect.right() - chip_w - 26.0 * scale, draw_rect.bottom() - 34.0 * scale, chip_w, 22.0 * scale)
        rounded_rect(p, chip, 7.0 * scale, color("#ffffff", 0.055 + 0.04 * hover_v), with_alpha(accent, 0.25 + 0.25 * hover_v))
        self.draw_text(p, chip, chip_text, self.font("poppins_medium", 7.2 * scale), icon_text if hover_v > 0.72 else accent, Qt.AlignmentFlag.AlignCenter)

        self.draw_text(p, QRectF(draw_rect.right() - 43.0 * scale, draw_rect.center().y() - 13.0 * scale, 18.0 * scale, 26.0 * scale), ">", self.font("poppins_bold", 15.0 * scale), THEME.text if hovered else THEME.muted, Qt.AlignmentFlag.AlignCenter)
        p.restore()

        self.add_hotspot(draw_rect.adjusted(-3.0 * scale, -3.0 * scale, 3.0 * scale, 3.0 * scale), action, payload, tooltip=tooltip)

    def draw_liquid_bottom_bar(self, p: QPainter, width: int, height: int, scale: float, active: float) -> None:
        enter = self.startup_stagger_value(0, 0.70, 0.22)
        actions: list[tuple[str, str, Any, QColor, str]] = [
            ("Config", "startup_open_config", None, THEME.cyan, "Open ConfigManager in ClickGUI."),
            ("Import", "config_action", "Import Config", THEME.pink, "Import a config json."),
            ("Wallpaper", "startup_open_wallpaper", None, color("#4677ff"), "Open StartupVisual wallpaper settings."),
            ("ClickGUI", "startup_open_gui", None, accent_color(4, 0.0), "Enter HUD and open ClickGUI."),
            ("Exit", "startup_exit", None, color("#ff6464"), "Close POLAR-RM."),
        ]
        if self.startup_step == "match":
            actions.insert(0, ("Back", "startup_back", None, color("#ffd766"), "Return to scene select."))
        button_h = 42.0 * scale
        gap = 10.0 * scale
        widths = [max(72.0 * scale, text_width(p, self.font("poppins_medium", 8.2 * scale), item[0]) + 32.0 * scale) for item in actions]
        total_w = sum(widths) + gap * (len(actions) - 1) + 28.0 * scale
        rect = QRectF(50.0 * scale, height - 64.0 * scale + (1.0 - enter) * 95.0 * scale, min(total_w, width - 100.0 * scale), button_h + 18.0 * scale)
        p.save()
        p.setOpacity(active * max(0.0, min(1.0, enter)))
        self.draw_liquid_glass_panel(p, rect, 8.0 * scale, accent=THEME.cyan, hover=0.0, scale=scale)
        x = rect.left() + 14.0 * scale
        for index, (label, action, payload, accent, tooltip) in enumerate(actions):
            button_w = min(widths[index], rect.right() - x - 14.0 * scale)
            if button_w <= 18.0 * scale:
                break
            self.draw_liquid_small_action_button(p, QRectF(x, rect.top() + 9.0 * scale, button_w, button_h), label, action, payload, accent, scale, tooltip)
            x += button_w + gap
        p.restore()

    def draw_wallpaper_picker(self, p: QPainter, width: int, height: int) -> None:
        open_v = self.anim.value("startup.wallpaper.open", 1.0, self.anim_duration(0.24), Easings.ease_out_pow4, initial=0.0)
        full = QRectF(0, 0, width, height)
        p.fillRect(full, color("#02050a", 0.54 * open_v))
        self.add_hotspot(full, "wallpaper_close")

        scale = max(0.76, min(1.18, self.get_auto_ui_scale(width, height, strength=0.38)))
        panel_w = min(width - 64.0 * scale, 1120.0 * scale)
        panel_h = min(height - 64.0 * scale, 525.0 * scale)
        panel = QRectF(width / 2.0 - panel_w / 2.0, height / 2.0 - panel_h / 2.0 + (1.0 - open_v) * 28.0 * scale, panel_w, panel_h)
        p.save()
        p.setOpacity(open_v)
        self.draw_liquid_glass_panel(p, panel, 18.0 * scale, accent=color("#54c7ff"), hover=0.0, scale=scale, surface="ModalGlass")
        self.add_hotspot(panel, "wallpaper_block")

        self.draw_text(
            p,
            QRectF(panel.left() + 28.0 * scale, panel.top() + 19.0 * scale, panel.width() - 56.0 * scale, 28.0 * scale),
            "WALLPAPER LIBRARY",
            self.font("poppins_bold", 15.0 * scale),
            THEME.text,
        )
        self.draw_text(
            p,
            QRectF(panel.left() + 28.0 * scale, panel.top() + 47.0 * scale, panel.width() - 56.0 * scale, 18.0 * scale),
            "选择内置壁纸，或导入自己的 MP4 / GIF / 图片",
            self.font("poppins_regular", 8.2 * scale),
            color("#c8d5de", 0.78),
        )

        module = self.registry.get("StartupVisual")
        current = self.setting_mode(module, "Wallpaper Profile", "TexasMP4")
        profiles = self.startup_wallpaper.profile_names()
        per_page = 4
        page_count = max(1, math.ceil(len(profiles) / per_page))
        self.wallpaper_picker_page = max(0, min(page_count - 1, self.wallpaper_picker_page))
        visible = profiles[self.wallpaper_picker_page * per_page : (self.wallpaper_picker_page + 1) * per_page]

        gap = 14.0 * scale
        cards_left = panel.left() + 26.0 * scale
        cards_top = panel.top() + 84.0 * scale
        cards_width = panel.width() - 52.0 * scale
        card_w = (cards_width - gap * (per_page - 1)) / per_page
        card_h = min(270.0 * scale, panel.height() - 176.0 * scale)
        for index, profile in enumerate(visible):
            rect = QRectF(cards_left + index * (card_w + gap), cards_top, card_w, card_h)
            self.draw_wallpaper_card(p, rect, profile, profile == current, scale)

        footer_y = panel.bottom() - 67.0 * scale
        button_h = 38.0 * scale
        x = panel.left() + 26.0 * scale
        actions = [
            ("Import", "wallpaper_import", None, color("#54c7ff"), "导入视频、GIF 或图片壁纸。"),
            ("Reset", "wallpaper_reset", None, THEME.cyan, "恢复德克萨斯默认壁纸。"),
        ]
        if self.startup_wallpaper.can_remove(current):
            actions.append(("Remove", "wallpaper_remove", current, color("#ff6b70"), "删除当前用户壁纸。"))
        for label, action, payload, accent, tooltip in actions:
            button_w = (88.0 if label != "Remove" else 96.0) * scale
            self.draw_liquid_small_action_button(p, QRectF(x, footer_y, button_w, button_h), label, action, payload, accent, scale, tooltip)
            x += button_w + 10.0 * scale

        nav_right = panel.right() - 26.0 * scale
        close_w = 82.0 * scale
        self.draw_liquid_small_action_button(
            p,
            QRectF(nav_right - close_w, footer_y, close_w, button_h),
            "Close",
            "wallpaper_close",
            None,
            color("#ffffff", 0.72),
            scale,
            "关闭壁纸库。",
        )
        nav_right -= close_w + 12.0 * scale
        if page_count > 1:
            nav_w = 48.0 * scale
            self.draw_liquid_small_action_button(p, QRectF(nav_right - nav_w * 2.0 - 8.0 * scale, footer_y, nav_w, button_h), "<", "wallpaper_page", -1, THEME.cyan, scale, "上一页")
            self.draw_liquid_small_action_button(p, QRectF(nav_right - nav_w, footer_y, nav_w, button_h), ">", "wallpaper_page", 1, THEME.cyan, scale, "下一页")
            self.draw_text(
                p,
                QRectF(nav_right - nav_w * 2.0 - 8.0 * scale, footer_y - 21.0 * scale, nav_w * 2.0 + 8.0 * scale, 16.0 * scale),
                f"{self.wallpaper_picker_page + 1} / {page_count}",
                self.font("poppins_medium", 7.5 * scale),
                THEME.muted,
                Qt.AlignmentFlag.AlignCenter,
            )
        p.restore()

    def draw_wallpaper_card(self, p: QPainter, rect: QRectF, profile: str, selected: bool, scale: float) -> None:
        hovered = rect.contains(self.hover_point)
        hover_v = self.anim.value(f"startup.wallpaper.hover.{profile}", 1.0 if hovered else 0.0, self.anim_duration(0.18), Easings.ease_out_expo)
        draw_rect = rect.translated(0, -3.0 * scale * hover_v)
        accent = color("#54c7ff") if selected else color("#9eb3c4")
        self.draw_liquid_glass_panel(p, draw_rect, 12.0 * scale, accent=accent, hover=max(hover_v, 0.42 if selected else 0.0), scale=scale, sample_background=False, surface="SubGlass")

        preview = QRectF(draw_rect.left() + 8.0 * scale, draw_rect.top() + 8.0 * scale, draw_rect.width() - 16.0 * scale, max(70.0 * scale, draw_rect.height() - 80.0 * scale))
        clip = QPainterPath()
        clip.addRoundedRect(preview, 8.0 * scale, 8.0 * scale)
        p.save()
        p.setClipPath(clip)
        image = self.startup_wallpaper.thumbnail(profile)
        if not image.isNull():
            self.draw_image_cover(p, preview, image)
        else:
            fallback = QLinearGradient(preview.topLeft(), preview.bottomRight())
            fallback.setColorAt(0.0, color("#16354a", 0.92))
            fallback.setColorAt(1.0, color("#071018", 0.96))
            p.fillRect(preview, fallback)
            self.draw_text(p, preview, "LOADING" if profile != "ParticleGrid" else "GRID", self.font("poppins_bold", 9.0 * scale), color("#bdefff", 0.66), Qt.AlignmentFlag.AlignCenter)
        p.fillRect(preview, color("#02050a", 0.10 if hovered else 0.20))
        p.restore()

        if selected:
            p.setBrush(color("#54c7ff", 0.94))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(draw_rect.right() - 18.0 * scale, draw_rect.top() + 18.0 * scale), 5.0 * scale, 5.0 * scale)
        label = self.startup_wallpaper.profile_label(profile)
        kind = self.startup_wallpaper.profile_kind(profile)
        self.draw_text(p, QRectF(draw_rect.left() + 11.0 * scale, preview.bottom() + 8.0 * scale, draw_rect.width() - 22.0 * scale, 20.0 * scale), label, self.font("poppins_bold", 9.0 * scale), THEME.text)
        self.draw_text(p, QRectF(draw_rect.left() + 11.0 * scale, preview.bottom() + 29.0 * scale, draw_rect.width() - 22.0 * scale, 16.0 * scale), kind, self.font("poppins_medium", 6.9 * scale), accent if selected else THEME.muted)
        self.add_hotspot(draw_rect, "wallpaper_select", profile, tooltip=f"切换到 {label}")

    @staticmethod
    def draw_image_cover(p: QPainter, rect: QRectF, image: QImage) -> None:
        image_aspect = image.width() / max(1.0, image.height())
        rect_aspect = rect.width() / max(1.0, rect.height())
        if image_aspect > rect_aspect:
            source_h = image.height()
            source_w = source_h * rect_aspect
            source = QRectF((image.width() - source_w) / 2.0, 0, source_w, source_h)
        else:
            source_w = image.width()
            source_h = source_w / max(0.01, rect_aspect)
            source = QRectF(0, (image.height() - source_h) / 2.0, source_w, source_h)
        p.drawImage(rect, image, source)

    def draw_liquid_small_action_button(
        self,
        p: QPainter,
        rect: QRectF,
        label: str,
        action: str,
        payload: Any,
        accent: QColor,
        scale: float,
        tooltip: str,
    ) -> None:
        hovered = rect.contains(self.hover_point)
        hover_v = self.anim.value(f"startup.lb.small.hover.{label}", 1.0 if hovered else 0.0, self.anim_duration(0.16), Easings.ease_out_expo)
        self.draw_liquid_glass_panel(p, rect, 6.0 * scale, accent=accent, hover=hover_v, scale=scale, sample_background=False, surface="SubGlass")
        fill = QRectF(rect.left(), rect.top(), rect.width() * hover_v, rect.height())
        if fill.width() > 1.0:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, with_alpha(accent, 0.44))
            grad.setColorAt(1.0, with_alpha(THEME.cyan, 0.20))
            p.save()
            p.setClipRect(fill)
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, 6.0 * scale, 6.0 * scale)
            p.restore()
        self.draw_glass_text(p, rect.adjusted(10.0 * scale, 0, -10.0 * scale, 0), label, self.font("poppins_medium", 8.2 * scale), THEME.text if hover_v > 0.35 else color("#d2d9df", 0.90), Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(rect, action, payload, tooltip=tooltip)

    def draw_liquid_status_panel(self, p: QPainter, menu_x: float, menu_y: float, button_w: float, height: int, scale: float, page: str, active: float) -> None:
        right_x = menu_x + button_w + 48.0 * scale
        right_w = self.width() - right_x - 50.0 * scale
        if right_w < 245.0 * scale:
            return
        enter = self.startup_stagger_value(2, 0.50, 0.08)
        panel = QRectF(right_x + (1.0 - enter) * 90.0 * scale, menu_y + 4.0 * scale, min(390.0 * scale, right_w), min(300.0 * scale, height - menu_y - 108.0 * scale))
        p.save()
        p.setOpacity(active * max(0.0, min(1.0, enter)))
        self.draw_liquid_glass_panel(p, panel, 7.0 * scale, accent=THEME.cyan, hover=0.0, scale=scale)
        top_line = QRectF(panel.left() + 14.0 * scale, panel.top() + 12.0 * scale, panel.width() - 28.0 * scale, 2.0 * scale)
        grad = QLinearGradient(top_line.topLeft(), top_line.topRight())
        grad.setColorAt(0.0, color("#4677ff", 0.90))
        grad.setColorAt(0.55, THEME.cyan)
        grad.setColorAt(1.0, color("#ffffff", 0.28))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(top_line, 1.0 * scale, 1.0 * scale)
        self.draw_glass_text(p, QRectF(panel.left() + 18.0 * scale, panel.top() + 26.0 * scale, panel.width() - 36.0 * scale, 23.0 * scale), "SESSION", self.font("poppins_bold", 11.0 * scale), THEME.text)

        scenario = self.startup_scenario_meta(self.scenario_manager.current.key)
        match = self.startup_match_meta(self.match_mode_manager.current.key)
        rows = [
            ("ENV", scenario["title"]),
            ("MATCH", match["title"]),
            ("CONFIG", self.current_profile()),
            ("MQTT", "mock" if not self.mqtt.connected else "live"),
            ("SERIAL", "mock" if not self.serial.connected else "live"),
        ]
        row_y = panel.top() + 62.0 * scale
        for index, (label, value) in enumerate(rows):
            c = accent_color(index, 0.08)
            row = QRectF(panel.left() + 18.0 * scale, row_y + index * 34.0 * scale, panel.width() - 36.0 * scale, 24.0 * scale)
            self.draw_liquid_glass_panel(p, row, 6.0 * scale, accent=c, hover=0.0, scale=scale, sample_background=False, surface="SubGlass")
            self.draw_glass_text(p, QRectF(row.left() + 10.0 * scale, row.top(), 58.0 * scale, row.height()), label, self.font("poppins_bold", 7.0 * scale), c, Qt.AlignmentFlag.AlignVCenter)
            self.draw_glass_text(p, row.adjusted(72.0 * scale, 0, -10.0 * scale, 0), value, self.font("poppins_medium", 8.1 * scale), color("#dce7ed", 0.92), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        tip_y = panel.bottom() - 56.0 * scale
        if tip_y > row_y + len(rows) * 34.0 * scale:
            tip = QRectF(panel.left() + 18.0 * scale, tip_y, panel.width() - 36.0 * scale, 37.0 * scale)
            self.draw_liquid_glass_panel(p, tip, 10.0 * scale, accent=THEME.cyan, hover=0.0, scale=scale, sample_background=False, surface="SubGlass")
            msg = "Press 1/2/3 to select. Enter continues." if page == "scenario" else "Press 1/2 to load. Backspace returns."
            self.draw_glass_text(p, tip.adjusted(12.0 * scale, 0, -12.0 * scale, 0), msg, self.font("poppins_regular", 7.2 * scale), THEME.muted, Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_startup_icon_card(
        self,
        p: QPainter,
        rect: QRectF,
        index: int,
        anim_key: str,
        icon: str,
        title: str,
        subtitle: str,
        detail: str,
        chip_text: str,
        action: str,
        payload: Any,
        tooltip: str,
        accent: QColor,
        scale: float,
        active: float,
    ) -> None:
        enter = self.anim.value(f"startup.card.enter.{anim_key}", 1.0, self.anim_duration(0.42 + index * 0.045), Easings.ease_out_pow4, initial=0.0)
        hovered = rect.contains(self.hover_point)
        hover_v = self.anim.value(f"startup.card.hover.{anim_key}", 1.0 if hovered else 0.0, self.anim_duration(0.18), Easings.ease_out_quad)
        lift = (1.0 - enter) * (24.0 + index * 7.0) * scale - hover_v * 7.0 * scale
        expand = hover_v * 4.0 * scale
        draw_rect = rect.adjusted(-expand, -expand, expand, expand)
        draw_rect.translate(0, lift)
        opacity = max(0.0, min(1.0, active * (0.12 + enter * 0.88)))

        p.save()
        p.setOpacity(opacity)
        self.draw_startup_card_shadow(p, draw_rect, accent, hover_v, scale)

        bg = QLinearGradient(draw_rect.topLeft(), draw_rect.bottomRight())
        bg.setColorAt(0.0, color("#11141a", 0.92 + 0.04 * hover_v))
        bg.setColorAt(0.55, color("#07080c", 0.90 + 0.05 * hover_v))
        bg.setColorAt(1.0, color("#151018", 0.86 + 0.06 * hover_v))
        p.setBrush(QBrush(bg))
        p.setPen(QPen(color("#ffffff", 0.13 + 0.15 * hover_v), 1.0))
        p.drawRoundedRect(draw_rect, 16 * scale, 16 * scale)

        top_line = QRectF(draw_rect.left() + 14 * scale, draw_rect.top() + 10 * scale, draw_rect.width() - 28 * scale, 3 * scale)
        line_grad = QLinearGradient(top_line.topLeft(), top_line.topRight())
        line_grad.setColorAt(0.0, THEME.pink)
        line_grad.setColorAt(0.52, accent)
        line_grad.setColorAt(1.0, THEME.cyan)
        p.setBrush(QBrush(line_grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(top_line, 2 * scale, 2 * scale)

        icon_size = min(58.0 * scale, draw_rect.height() * 0.38)
        icon_rect = QRectF(draw_rect.left() + 18 * scale, draw_rect.top() + 31 * scale, icon_size, icon_size)
        pulse = 0.5 + 0.5 * math.sin(time.perf_counter() * 3.0 + index)
        p.setBrush(with_alpha(accent, 0.10 + 0.12 * hover_v + 0.04 * pulse))
        p.setPen(QPen(with_alpha(accent, 0.52 + 0.24 * hover_v), 1.2 * scale))
        p.drawEllipse(icon_rect.adjusted(-4 * scale, -4 * scale, 4 * scale, 4 * scale))
        rounded_rect(p, icon_rect, icon_size * 0.50, color("#050609", 0.72), with_alpha(accent, 0.78 + 0.16 * hover_v), 1.2 * scale)
        self.draw_text(p, icon_rect, icon, self.font("poppins_bold", min(17.5 * scale, icon_size * 0.34), QFont.Weight.Bold), THEME.text, Qt.AlignmentFlag.AlignCenter)

        shortcut = QRectF(draw_rect.right() - 38 * scale, draw_rect.top() + 26 * scale, 22 * scale, 20 * scale)
        rounded_rect(p, shortcut, 7 * scale, color("#ffffff", 0.06), color("#ffffff", 0.11 + 0.12 * hover_v))
        self.draw_text(p, shortcut, str(index + 1), self.font("poppins_bold", 7.4 * scale), accent, Qt.AlignmentFlag.AlignCenter)

        text_left = icon_rect.right() + 13 * scale
        text_w = draw_rect.right() - text_left - 46 * scale
        self.draw_text(p, QRectF(text_left, draw_rect.top() + 31 * scale, text_w, 26 * scale), title, self.font("poppins_bold", 14.0 * scale), THEME.text)
        self.draw_text(p, QRectF(text_left, draw_rect.top() + 57 * scale, draw_rect.right() - text_left - 18 * scale, 19 * scale), subtitle, self.font("poppins_regular", 8.0 * scale), color("#d0d5db", 0.86))

        detail_rect = QRectF(draw_rect.left() + 18 * scale, draw_rect.bottom() - 49 * scale, draw_rect.width() - 36 * scale, 17 * scale)
        self.draw_text(p, detail_rect, detail, self.font("poppins_regular", 7.6 * scale), color("#aeb7bd", 0.84))

        chip = QRectF(draw_rect.left() + 18 * scale, draw_rect.bottom() - 28 * scale, min(88.0 * scale, draw_rect.width() * 0.36), 18 * scale)
        rounded_rect(p, chip, 7 * scale, color("#ffffff", 0.055), with_alpha(accent, 0.25 + 0.25 * hover_v))
        self.draw_text(p, chip, chip_text, self.font("poppins_medium", 6.9 * scale), accent, Qt.AlignmentFlag.AlignCenter)

        arrow = QRectF(draw_rect.right() - 38 * scale, draw_rect.bottom() - 30 * scale, 22 * scale, 20 * scale)
        self.draw_text(p, arrow, ">", self.font("poppins_bold", 12.0 * scale), THEME.text if hovered else THEME.muted, Qt.AlignmentFlag.AlignCenter)
        p.restore()

        self.add_hotspot(rect.adjusted(-4 * scale, -5 * scale, 4 * scale, 6 * scale), action, payload, tooltip="")

    def draw_startup_card_shadow(self, p: QPainter, rect: QRectF, accent: QColor, hover_v: float, scale: float) -> None:
        shadow_rect = rect.adjusted(-6 * scale, -6 * scale, 6 * scale, 8 * scale)
        rounded_rect(p, shadow_rect, 18 * scale, color("#000000", 0.18 + 0.08 * hover_v))
        if hover_v > 0.01:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(with_alpha(accent, 0.22 * hover_v), 1.4 * scale))
            p.drawRoundedRect(rect.adjusted(-3 * scale, -3 * scale, 3 * scale, 3 * scale), 18 * scale, 18 * scale)
            p.setPen(QPen(color("#ffffff", 0.11 * hover_v), 1.0))
            p.drawRoundedRect(rect.adjusted(-7 * scale, -7 * scale, 7 * scale, 7 * scale), 22 * scale, 22 * scale)

    def startup_scenario_meta(self, key: str) -> dict[str, str]:
        return {
            "OfficialEvent": {
                "icon": "DJI",
                "title": "大疆官方",
                "subtitle": "官方参数 / 赛事限制",
                "tooltip": "载入官方链路参数和赛事安全限制。",
            },
            "CampusSimulation": {
                "icon": "SIM",
                "title": "校内模拟",
                "subtitle": "Shark / 本地图传",
                "tooltip": "载入校内训练和 SharkDataServer 模拟参数。",
            },
            "LabDebug": {
                "icon": "LAB",
                "title": "实验室调试",
                "subtitle": "摄像头 / Mock 输出",
                "tooltip": "载入本地摄像头预览、协议测试和 mock 输出。",
            },
        }.get(key, {"icon": "RM", "title": key, "subtitle": "POLAR profile", "tooltip": key})

    def startup_match_meta(self, key: str) -> dict[str, str]:
        return {
            "RMUC7v7": {
                "icon": "7V7",
                "title": "RMUC 7v7",
                "subtitle": "超级对抗赛 / 官方大地图",
                "tooltip": "载入 7v7 官方地图、小地图和默认战斗 HUD。",
            },
            "RMUL3v3": {
                "icon": "3V3",
                "title": "RMUL 3v3",
                "subtitle": "高校联盟赛 / 区域控制",
                "tooltip": "载入 3v3 官方地图、控制区和默认战斗 HUD。",
            },
        }.get(key, {"icon": "RM", "title": key, "subtitle": "Match profile", "tooltip": key})

    def reset_startup_page_animation(self, page: str) -> None:
        self.anim.reset_prefix("startup.card.enter.", 0.0)
        key = "startup.robot.open" if page == "robot" else ("startup.match.open" if page == "match" else "startup.open")
        self.anim.reset(key, 0.0)

    def startup_scenario_meta(self, key: str) -> dict[str, str]:
        return {
            "OfficialEvent": {
                "icon": "official",
                "title": "DJI Official",
                "subtitle": "Official limits and referee links",
                "tooltip": "Load official safety limits, referee protocol defaults, and event HUD presets.",
            },
            "CampusSimulation": {
                "icon": "sim",
                "title": "Campus Sim",
                "subtitle": "Shark bridge and local match mock",
                "tooltip": "Load campus simulation defaults for SharkDataServer, mock sending, and local video.",
            },
            "LabDebug": {
                "icon": "lab",
                "title": "Lab Debug",
                "subtitle": "Camera preview and protocol stubs",
                "tooltip": "Load lab debug defaults for webcam preview, protocol testing, and mock outputs.",
            },
        }.get(key, {"icon": "RM", "title": key, "subtitle": "POLAR profile", "tooltip": key})

    def startup_match_meta(self, key: str) -> dict[str, str]:
        return {
            "RMUC7v7": {
                "icon": "7v7",
                "title": "RMUC 7v7",
                "subtitle": "Super combat map and full HUD",
                "tooltip": "Load RMUC 7v7 official map, tactical HUD, base, outpost, gold, ammo, and buff modules.",
            },
            "RMUL3v3": {
                "icon": "3v3",
                "title": "RMUL 3v3",
                "subtitle": "Alliance map and control zone HUD",
                "tooltip": "Load RMUL 3v3 official map, control zone, victory points, robot status, and compact HUD.",
            },
        }.get(key, {"icon": "RM", "title": key, "subtitle": "Match profile", "tooltip": key})

    def reset_startup_page_animation(self, page: str) -> None:
        self.anim.reset_prefix("startup.card.enter.", 0.0)
        self.anim.reset_prefix("startup.lb.hover.", 0.0)
        self.anim.reset_prefix("startup.lb.small.hover.", 0.0)
        self.startup_transition_started = time.perf_counter()
        key = "startup.robot.open" if page == "robot" else ("startup.match.open" if page == "match" else "startup.open")
        self.anim.reset(key, 0.0)
        # 页面切换不应继续混合上一页遗留的视频纹理。保留当前帧，只丢弃
        # 插值历史，避免部分驱动在纹理池轮换时短暂显示上下颠倒的旧帧。
        self.startup_gpu.discard_interpolation_history()

    def draw_rm_hud(
        self,
        p: QPainter,
        width: int,
        height: int,
        armor_target: VisionTarget,
        energy_target: VisionTarget,
        tongji_result: VisionResult | None = None,
        *,
        draw_motion: bool = True,
    ) -> None:
        hud = self.registry.get("HUD")
        armor_module = self.registry.get("ArmorAutoAim")
        energy_module = self.registry.get("EnergyAutoAim")
        armor_enabled = bool(armor_module and armor_module.enabled)
        energy_enabled = bool(energy_module and energy_module.enabled)
        self._bottom_left_diagnostics = []
        # 真实装甲视觉接入后不允许旧 Mock 能量框叠到图传上。
        draw_energy = energy_enabled and self._vision_source == "Mock"
        primary_target = energy_target if draw_energy else armor_target
        hud_scale = self.get_hud_scale(width, height)
        scaled_width = max(1, int(width / hud_scale))
        scaled_height = max(1, int(height / hud_scale))
        p.save()
        p.scale(hud_scale, hud_scale)
        if self.setting_bool(hud, "Watermark", True):
            self.draw_watermark(p)
        if self.registry.get("MatchTimer") and self.registry.get("MatchTimer").enabled:
            self.draw_match_header(p, scaled_width)
        bottom_left = HudAnchorStack(22.0, scaled_height - 60.0, 8.0)
        if self.setting_bool(hud, "Target HUD", True):
            title = "EnergyTargetHUD" if primary_target.kind == "energy" else "RobotTargetHUD"
            self.draw_target_hud_by_style(p, primary_target, title, bottom_left)
        diagnostics = list(self._bottom_left_diagnostics)
        if self.hud_density() != "DebugFull" and diagnostics:
            diagnostics = [max(diagnostics, key=lambda item: item[2])]
        else:
            diagnostics.sort(key=lambda item: item[2])
        for text_value, text_color, _priority in diagnostics:
            diagnostic_rect = bottom_left.take(220.0, 22.0)
            self.draw_pill(p, diagnostic_rect.topLeft(), text_value, text_color)
        if hud:
            mode_setting = hud.get_setting("Right Display")
            mode = str(mode_setting.value) if mode_setting else HUD_MODES[0]
            self.draw_right_hud_mode(p, scaled_width, scaled_height, mode, primary_target, hud_scale)
        p.restore()
        if draw_motion:
            self.paint_hud_motion_overlay(p, width, height)

    def hud_density(self) -> str:
        hud = self.registry.get("HUD")
        setting = hud.get_setting("Density") if hud else None
        value = str(setting.value) if setting else "CombatCompact"
        return value if value in ("CombatCompact", "Balanced", "DebugFull") else "CombatCompact"

    def target_hud_style(self) -> str:
        hud = self.registry.get("HUD")
        setting = hud.get_setting("Target Style") if hud else None
        value = str(setting.value) if setting else "RoundCompact"
        return value if value in ("RoundCompact", "BarOnly", "FullCard") else "RoundCompact"

    def hud_visual_tone(self) -> str:
        hud = self.registry.get("HUD")
        setting = hud.get_setting("Visual Tone") if hud else None
        value = str(setting.value) if setting else "LiquidClean"
        return value if value in ("LiquidClean", "PolarLegacy") else "LiquidClean"

    def hud_clean(self) -> bool:
        return self.hud_visual_tone() == "LiquidClean"

    def hud_accent(self) -> QColor:
        return color("#5d8cff") if self.hud_clean() else THEME.cyan

    def hud_surface(self, alpha: float = 0.68) -> QColor:
        return color("#000000", alpha if self.hud_clean() else min(0.86, alpha + 0.08))

    def hud_panel_outline(self, alpha: float = 0.10) -> QColor:
        return color("#ffffff", alpha if self.hud_clean() else min(0.20, alpha + 0.04))

    def hud_warning(self) -> QColor:
        return color("#efbf04") if self.hud_clean() else color("#ffd166")

    def hud_danger(self) -> QColor:
        return color("#fc4130") if self.hud_clean() else THEME.red

    def hud_success(self) -> QColor:
        return color("#4dac68") if self.hud_clean() else THEME.green

    def hud_state_color(self, kind: str = "info", ratio: float = 0.0) -> QColor:
        if not self.hud_clean():
            return {
                "ally": THEME.cyan,
                "enemy": THEME.red,
                "danger": THEME.red,
                "warning": color("#ffd166"),
                "success": THEME.green,
                "gold": color("#ffd166"),
                "ammo": THEME.green,
                "control": THEME.pink,
                "spin": THEME.pink,
            }.get(kind, THEME.cyan)
        if kind in ("enemy", "danger"):
            return self.hud_danger()
        if kind in ("warning", "gold", "power"):
            if ratio >= 0.95:
                return self.hud_danger()
            return self.hud_warning() if ratio >= 0.78 or kind in ("warning", "gold", "power") else self.hud_accent()
        if kind in ("success", "ammo", "cap"):
            if kind == "cap" and ratio < 0.18:
                return self.hud_danger()
            if kind == "cap" and ratio < 0.34:
                return self.hud_warning()
            return self.hud_success() if kind in ("success", "ammo") else self.hud_accent()
        if kind in ("heat", "speed"):
            if ratio >= 0.92:
                return self.hud_danger()
            if ratio >= 0.78:
                return self.hud_warning()
            return self.hud_accent()
        return self.hud_accent()

    def liquid_map_enabled(self) -> bool:
        module = self.registry.get("LiquidTacticalMap")
        return bool(module and module.enabled)

    def liquid_map_setting(self, name: str, fallback: str) -> str:
        module = self.registry.get("LiquidTacticalMap")
        setting = module.get_setting(name) if module else None
        return str(setting.value) if setting else fallback

    def liquid_map_bool(self, name: str, fallback: bool = True) -> bool:
        module = self.registry.get("LiquidTacticalMap")
        return self.setting_bool(module, name, fallback)

    def draw_watermark(self, p: QPainter) -> None:
        z_font = self.font("museo", 18, QFont.Weight.Bold)
        body = self.font("poppins_medium", 10.5)
        glow_text(p, "POLAR-RM", 12, 28, z_font, THEME.text, self.hud_accent(), 8 if not self.hud_clean() else 4)
        title_w = text_width(p, z_font, "POLAR-RM")
        self.draw_text(p, QRectF(22 + title_w, 12, 90, 24), f"{self.state.fps:.0f} FPS", body, THEME.text)
        status = "CAM" if self.state.camera_connected else "SYN"
        scene = self.scenario_manager.current.title
        match = self.match_mode_manager.current.title
        mqtt = "MQTT mock" if getattr(self.mqtt, "mock_output", True) else "MQTT live"
        serial = "SERIAL mock" if self.control.mock_output else "SERIAL live"
        self.draw_text(p, QRectF(12, 34, 430, 16), f"{status} | {scene} | {match} | {mqtt} | {serial}", self.font("poppins_regular", 8), THEME.muted)

    def draw_target_overlay(self, p: QPainter, target: VisionTarget, module: Module | None = None) -> None:
        rect = QRectF(target.x, target.y, target.w, target.h)
        locked = self.state.energy_target_locked if target.kind == "energy" else self.state.target_locked
        setting = module.get_setting("Lock Style") if module else None
        style = str(setting.value) if setting else "Polar Corner"
        main = self.hud_accent() if locked else self.hud_danger()
        if style == "White Outline":
            self.draw_white_outline_lock(p, rect, target, locked)
            return
        if style == "Minimal Bracket":
            self.draw_minimal_bracket_lock(p, rect, target, locked)
            return
        if style == "Rune Ring":
            self.draw_rune_ring_lock(p, rect, target, module, locked)
            return

        p.setPen(QPen(with_alpha(main, 0.92), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        p.setPen(QPen(main, 3.2))
        corner = min(28.0, rect.width() * 0.28)
        p.drawLine(rect.topLeft(), rect.topLeft() + QPointF(corner, 0))
        p.drawLine(rect.topLeft(), rect.topLeft() + QPointF(0, corner))
        p.drawLine(rect.topRight(), rect.topRight() + QPointF(-corner, 0))
        p.drawLine(rect.topRight(), rect.topRight() + QPointF(0, corner))
        p.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPointF(corner, 0))
        p.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPointF(0, -corner))
        p.drawLine(rect.bottomRight(), rect.bottomRight() + QPointF(-corner, 0))
        p.drawLine(rect.bottomRight(), rect.bottomRight() + QPointF(0, -corner))
        label = self.target_overlay_label(target)
        self.draw_pill(p, QPointF(rect.left(), rect.top() - 27), label, main)

    def draw_fluorescent_white_segments(
        self,
        p: QPainter,
        segments: list[tuple[QPointF, QPointF]],
        *,
        line_width: float = 1.0,
        glow: float = 0.35,
        alpha: float = 1.0,
        dashed: bool = False,
    ) -> None:
        """Debug 3D Box ESP fluorescent white (visual-demo esp-box-white.html).

        Pure #FFFFFF core at ``line_width`` (~1.0 jar). Soft pass:
        alpha = 0.22 * glow, width = line_width + 2.5 * glow, round caps.
        No fill, no pulse, no cyan tint.
        """
        if not segments:
            return
        base_w = max(0.5, float(line_width))
        glow = max(0.0, min(1.0, float(glow)))
        alpha = max(0.0, min(1.0, float(alpha)))
        style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)

        def stroke(a: float, width: float) -> None:
            if a <= 0.001 or width <= 0.01:
                return
            pen = QPen(QColor(255, 255, 255, max(1, min(255, round(255.0 * a)))), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setStyle(style)
            p.setPen(pen)
            for start, end in segments:
                p.drawLine(start, end)

        if glow > 0.01:
            # Multi-pass pure white bloom (CPU/raster-safe; avoid fat single AA pass).
            stroke(0.06 * glow * alpha, base_w + 8.0 * glow)
            stroke(0.12 * glow * alpha, base_w + 4.0 * glow)
            stroke(0.28 * glow * alpha, base_w + 1.8 * glow)
        # Core jar stroke — RGB 1,1,1.
        stroke(1.0 * alpha, base_w)
        stroke(0.55 * alpha, max(0.55, base_w * 0.45))
        p.restore()

    def draw_fluorescent_white_polyline(
        self,
        p: QPainter,
        points: list[QPointF],
        *,
        closed: bool = True,
        line_width: float = 1.0,
        glow: float = 0.35,
        alpha: float = 1.0,
        dashed: bool = False,
    ) -> None:
        if len(points) < 2:
            return
        limit = len(points) if closed else len(points) - 1
        segments = [(points[i], points[(i + 1) % len(points)]) for i in range(limit)]
        self.draw_fluorescent_white_segments(
            p, segments, line_width=line_width, glow=glow, alpha=alpha, dashed=dashed,
        )

    def rasterize_fluorescent_white_circle(
        self,
        radius: float,
        *,
        line_width: float = 1.15,
        glow: float = 0.85,
        alpha: float = 1.0,
        supersample: float = 2.0,
    ) -> tuple[QImage, float]:
        """CPU-only fluorescent white ring (Debug Box ESP recipe).

        Never call drawEllipse on an OpenGL paint device — Qt's AA path paints a
        translucent rectangular atlas (the white square bug). Rasterize here,
        then blit the premultiplied image.

        Returns (image, half_extent_logical) so the caller can center the blit.
        """
        glow = max(0.0, min(1.0, float(glow)))
        alpha = max(0.0, min(1.0, float(alpha)))
        # Cache at full opacity; callers that need dimmed rings should pass alpha=1
        # and multiply painter opacity instead.
        cache_key = (
            int(round(float(radius) * 2.0)),
            int(round(float(line_width) * 100.0)),
            int(round(glow * 100.0)),
        )
        if alpha >= 0.999 and cache_key in self._fluorescent_circle_cache:
            return self._fluorescent_circle_cache[cache_key]

        ss = max(1.0, float(supersample))
        r = max(0.5, float(radius) * ss)
        base_w = max(0.75, float(line_width) * ss)
        # Outer bloom needs headroom so soft strokes are not clipped.
        pad = base_w * 0.5 + (2.5 * glow + 8.0 * glow) * 0.5 + 3.0 * ss
        half = int(math.ceil(r + pad))
        size = max(8, half * 2)
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        ip = QPainter(image)
        ip.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ip.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ip.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        ip.setBrush(Qt.BrushStyle.NoBrush)
        center = QPointF(size * 0.5, size * 0.5)

        def stroke(a: float, width: float) -> None:
            if a <= 0.001 or width <= 0.05:
                return
            pen = QPen(QColor(255, 255, 255, max(1, min(255, round(255.0 * a)))), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            ip.setPen(pen)
            ip.drawEllipse(center, r, r)

        # Multi-pass pure #FFFFFF bloom → core (stronger than thin demo default,
        # still no cyan tint / no fill). Matches jar "fluorescent" AA look.
        if glow > 0.01:
            stroke(0.05 * glow * alpha, base_w + 12.0 * glow)
            stroke(0.10 * glow * alpha, base_w + 7.0 * glow)
            stroke(0.18 * glow * alpha, base_w + 3.8 * glow)
            stroke(0.32 * glow * alpha, base_w + 1.8 * glow)
        stroke(1.00 * alpha, base_w)
        # Crisp inner filament so the ring reads bright, not chalky.
        stroke(0.70 * alpha, max(0.65 * ss, base_w * 0.48))
        ip.end()
        if ss != 1.0:
            out_w = max(1, int(round(size / ss)))
            image = image.scaled(
                out_w,
                out_w,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        half_logical = image.width() * 0.5
        if alpha >= 0.999:
            self._fluorescent_circle_cache[cache_key] = (image, half_logical)
            # Bound cache growth when user scrubs Circle Size.
            if len(self._fluorescent_circle_cache) > 48:
                oldest = next(iter(self._fluorescent_circle_cache))
                if oldest != cache_key:
                    self._fluorescent_circle_cache.pop(oldest, None)
        return image, half_logical

    def draw_fluorescent_white_ellipse(
        self,
        p: QPainter,
        center: QPointF,
        radius_x: float,
        radius_y: float | None = None,
        *,
        line_width: float = 1.15,
        glow: float = 0.85,
        alpha: float = 1.0,
    ) -> None:
        """Fluorescent white ellipse via CPU raster + blit (never GL drawEllipse)."""
        rx = max(0.5, float(radius_x))
        ry = max(0.5, float(radius_x if radius_y is None else radius_y))
        # Non-circle ellipses fall back to segment approximation on CPU image later if needed.
        radius = max(rx, ry)
        image, half = self.rasterize_fluorescent_white_circle(
            radius, line_width=line_width, glow=glow, alpha=alpha, supersample=2.0,
        )
        if rx != ry and ry > 0.5:
            # Scale Y for ellipse while keeping X radius.
            target = QRectF(center.x() - half * (rx / radius), center.y() - half * (ry / radius),
                            half * 2.0 * (rx / radius), half * 2.0 * (ry / radius))
        else:
            target = QRectF(center.x() - half, center.y() - half, half * 2.0, half * 2.0)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(target, image)
        p.restore()

    def draw_armor_fov_circle(self, p: QPainter, width: int, height: int, module: Module | None) -> None:
        """Screen-center fluorescent white FOV ring; size from ClickGUI Circle Size.

        CPU-rasterized so the OpenGL paint engine cannot leave a white square
        atlas around the ring.
        """
        if module is None or not module.enabled:
            return
        if not self.setting_bool(module, "Draw Fov", True):
            return
        radius = max(8.0, self.get_setting_number(module, "Circle Size", 160.0))
        center = QPointF(width * 0.5, height * 0.5)
        # Stronger glow than thin canvas default so it reads as jar fluorescent white.
        self.draw_fluorescent_white_ellipse(
            p, center, radius, line_width=1.15, glow=0.90, alpha=1.0,
        )

    def draw_white_outline_lock(self, p: QPainter, rect: QRectF, target: VisionTarget, locked: bool) -> None:
        alpha = 0.94 if locked else 0.62
        accent = self.hud_accent() if locked else self.hud_danger()
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Full fluorescent white box outline (Debug Box ESP recipe).
        corners = [
            rect.topLeft() + QPointF(0.5, 0.5),
            rect.topRight() + QPointF(-0.5, 0.5),
            rect.bottomRight() + QPointF(-0.5, -0.5),
            rect.bottomLeft() + QPointF(0.5, -0.5),
        ]
        self.draw_fluorescent_white_polyline(
            p, corners, closed=True, line_width=1.0, glow=0.85, alpha=alpha,
        )
        corner = min(22.0, rect.width() * 0.22)
        corner_segs: list[tuple[QPointF, QPointF]] = []
        for start, dx, dy in (
            (rect.topLeft(), corner, 0),
            (rect.topLeft(), 0, corner),
            (rect.topRight(), -corner, 0),
            (rect.topRight(), 0, corner),
            (rect.bottomLeft(), corner, 0),
            (rect.bottomLeft(), 0, -corner),
            (rect.bottomRight(), -corner, 0),
            (rect.bottomRight(), 0, -corner),
        ):
            corner_segs.append((start, start + QPointF(dx, dy)))
        self.draw_fluorescent_white_segments(
            p, corner_segs, line_width=1.15, glow=0.85, alpha=alpha,
        )
        check_origin = QPointF(rect.right() - 18, rect.top() + 12)
        p.setPen(QPen(accent, 1.8))
        p.drawLine(check_origin + QPointF(-7, 0), check_origin + QPointF(-2, 5))
        p.drawLine(check_origin + QPointF(-2, 5), check_origin + QPointF(8, -7))
        self.draw_pill(
            p,
            QPointF(rect.left(), rect.top() - 27),
            self.target_overlay_label(target),
            color("#ffffff", alpha),
        )
        p.restore()

    def draw_minimal_bracket_lock(self, p: QPainter, rect: QRectF, target: VisionTarget, locked: bool) -> None:
        main = color("#ffffff", 0.88) if locked else with_alpha(self.hud_danger(), 0.88)
        corner = min(30.0, rect.width() * 0.24)
        inset = 2.0
        p.save()
        p.setPen(QPen(main, 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        tl = rect.topLeft() + QPointF(inset, inset)
        tr = rect.topRight() + QPointF(-inset, inset)
        bl = rect.bottomLeft() + QPointF(inset, -inset)
        br = rect.bottomRight() + QPointF(-inset, -inset)
        for point, hx, vy in ((tl, corner, corner), (tr, -corner, corner), (bl, corner, -corner), (br, -corner, -corner)):
            p.drawLine(point, point + QPointF(hx, 0))
            p.drawLine(point, point + QPointF(0, vy))
        self.draw_pill(p, QPointF(rect.left(), rect.top() - 27), self.target_overlay_label(target), main)
        p.restore()

    def draw_rune_ring_lock(self, p: QPainter, rect: QRectF, target: VisionTarget, module: Module | None, locked: bool) -> None:
        main = self.hud_accent() if locked else color("#ffffff", 0.58)
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2.0
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(with_alpha(main, 0.82), 1.4))
        p.drawEllipse(center, radius, radius)
        p.setPen(QPen(with_alpha(main, 0.95), 2.3))
        sweep = 16.0
        for angle in (0, 90, 180, 270):
            rad = math.radians(angle)
            outer = QPointF(center.x() + math.cos(rad) * (radius + 7), center.y() + math.sin(rad) * (radius + 7))
            inner = QPointF(center.x() + math.cos(rad) * (radius - sweep), center.y() + math.sin(rad) * (radius - sweep))
            p.drawLine(inner, outer)
        p.setPen(QPen(self.hud_warning() if self.state.energy_rune_rotation == "CCW" else self.hud_accent(), 2.4))
        progress = self.state.energy_rune_progress / 100.0 if target.kind == "energy" else target.confidence
        marker_angle = progress * math.tau - math.pi / 2.0
        marker = QPointF(center.x() + math.cos(marker_angle) * radius, center.y() + math.sin(marker_angle) * radius)
        p.drawEllipse(marker, 4.0, 4.0)
        show_progress = self.setting_bool(module, "Show Progress", True)
        if show_progress and target.kind == "energy":
            bar = QRectF(rect.left(), rect.bottom() + 8, rect.width(), 5)
            draw_bar(p, bar, progress, self.hud_accent(), color("#ffffff", 0.18), 2.5)
        self.draw_pill(p, QPointF(rect.left(), rect.top() - 27), self.target_overlay_label(target), main)
        p.restore()

    def target_overlay_label(self, target: VisionTarget) -> str:
        if target.kind == "energy":
            return f"{target.label}  {target.confidence:.0%}  {self.state.energy_target_distance_m:.1f}m  {self.state.energy_rune_progress}%"
        return f"{target.label}  {target.confidence:.0%}  {self.state.target_distance_m:.1f}m"

    def armor_esp_points(self, points: tuple[tuple[float, float], ...], result: VisionResult, width: int, height: int) -> list[QPointF]:
        camera_module = self.registry.get("CameraFeed")
        mirror = self.setting_bool(camera_module, "Mirror", False)
        x_scale = width / max(1.0, float(result.source_width))
        y_scale = height / max(1.0, float(result.source_height))
        return [QPointF(width - x * x_scale if mirror else x * x_scale, y * y_scale) for x, y in points]

    def armor_esp_back_points(self, armor, result: VisionResult, width: int, height: int, depth: float) -> list[QPointF]:
        if len(armor.back_points) == 4:
            return self.armor_esp_points(armor.back_points, result, width, height)
        front = self.armor_esp_points(armor.points, result, width, height)
        if len(front) != 4:
            return []
        center = QPolygonF(front).boundingRect().center()
        thickness = max(5.0, min(32.0, QPolygonF(front).boundingRect().width() * depth))
        angle = armor.yaw_rad
        offset = QPointF(-math.sin(angle) * thickness, math.cos(angle) * thickness * 0.34)
        return [center + (point - center) * 0.90 + offset for point in front]

    def draw_3d_esp_box(self, p: QPainter, front: list[QPointF], back: list[QPointF], c: QColor, line_width: float, *, glass: bool, ghost: bool, label: str | None = None) -> None:
        if len(front) != 4 or len(back) != 4:
            return
        front_poly = QPolygonF(front)
        # jar base width 1.0; module Line Width defaults to 2.0 → map to ~1.0.
        base_w = max(0.75, float(line_width) * 0.5)
        alpha = max(0.15, min(1.0, c.alphaF() if isinstance(c, QColor) else 1.0))
        if ghost:
            alpha *= 0.72
        # Full 12-edge outlined box — fluorescent white only (no fill default).
        edges: list[tuple[QPointF, QPointF]] = []
        for i in range(4):
            edges.append((front[i], front[(i + 1) % 4]))
            edges.append((back[i], back[(i + 1) % 4]))
            edges.append((front[i], back[i]))
        self.draw_fluorescent_white_segments(
            p, edges, line_width=base_w, glow=0.85, alpha=alpha, dashed=ghost,
        )
        if label:
            box = front_poly.boundingRect()
            white = color("#ffffff", alpha)
            if ghost:
                self.draw_text(p, QRectF(box.left(), box.top() - 16, 44, 13), label, self.font("poppins_medium", 7.0), white)
            else:
                self.draw_pill(p, QPointF(box.left(), box.top() - 22), label, white)

    @staticmethod
    def constrain_prediction_geometry(
        front: list[QPointF],
        back: list[QPointF],
        reference: list[QPointF],
    ) -> tuple[list[QPointF], list[QPointF]]:
        """限制未标定 PnP 偶发的超大投影，但不改预测板中心位置。"""
        if len(front) != 4 or len(reference) != 4:
            return front, back
        box = QPolygonF(front).boundingRect()
        reference_box = QPolygonF(reference).boundingRect()
        if box.width() <= 0.01 or box.height() <= 0.01 or reference_box.isEmpty():
            return front, back
        max_w = max(18.0, reference_box.width() * 1.35)
        max_h = max(10.0, reference_box.height() * 1.45)
        scale = min(1.0, max_w / box.width(), max_h / box.height())
        if scale >= 0.999:
            return front, back
        center = box.center()

        def scaled(points: list[QPointF]) -> list[QPointF]:
            return [center + (point - center) * scale for point in points]

        return scaled(front), scaled(back) if len(back) == 4 else back

    def draw_clean_3d_esp_box(
        self,
        p: QPainter,
        front: list[QPointF],
        back: list[QPointF],
        c: QColor,
        line_width: float,
        *,
        glass: bool,
        ghost: bool,
        label: str | None = None,
    ) -> None:
        """Outlined 3D armor box — fluorescent white wire only (no solid faces)."""
        if len(front) != 4 or len(back) != 4:
            return
        front_poly = QPolygonF(front)
        base_w = max(0.75, float(line_width) * 0.5)
        alpha = max(0.15, min(1.0, c.alphaF() if isinstance(c, QColor) else 1.0))
        if ghost:
            alpha *= 0.72
        edges: list[tuple[QPointF, QPointF]] = []
        for i in range(4):
            edges.append((front[i], front[(i + 1) % 4]))
            edges.append((back[i], back[(i + 1) % 4]))
            edges.append((front[i], back[i]))
        self.draw_fluorescent_white_segments(
            p, edges, line_width=base_w, glow=0.85, alpha=alpha, dashed=ghost,
        )
        if label:
            box = front_poly.boundingRect()
            white = color("#ffffff", alpha)
            if ghost:
                self.draw_text(p, QRectF(box.left(), box.top() - 16, 44, 13), label, self.font("poppins_medium", 7.0), white)
            else:
                self.draw_pill(p, QPointF(box.left(), box.top() - 22), label, white)

    def draw_polar_mechanical_wire(
        self,
        p: QPainter,
        front: list[QPointF],
        back: list[QPointF],
        accent: QColor,
        line_width: float,
        *,
        predicted: bool,
        label: str | None = None,
    ) -> None:
        """Mechanical armor wireframe — Debug Box ESP fluorescent white 1:1.

        Pure #FFFFFF soft+core strokes only; no fill faces. Matches
        visual-demo/esp-box-white.html (glow=0.35, base width ~1.0).
        """
        if len(front) != 4:
            return

        def lerp(a: QPointF, b: QPointF, amount: float) -> QPointF:
            return QPointF(
                a.x() + (b.x() - a.x()) * amount,
                a.y() + (b.y() - a.y()) * amount,
            )

        front_poly = QPolygonF(front)
        alpha = 0.46 if predicted else 1.0
        # jar glLineWidth(1.0); module default Line Width 2.0 → base 1.0.
        base_w = max(0.75, float(line_width) * 0.5 * (0.85 if predicted else 1.0))
        glow = 0.85

        if len(back) == 4:
            back_edges = [(back[i], back[(i + 1) % 4]) for i in range(4)]
            depth_edges = [(front[i], back[i]) for i in range(4)]
            self.draw_fluorescent_white_segments(
                p, back_edges, line_width=base_w * 0.85, glow=glow, alpha=alpha * 0.55, dashed=True,
            )
            self.draw_fluorescent_white_segments(
                p, depth_edges, line_width=base_w * 0.9, glow=glow, alpha=alpha * 0.65, dashed=True,
            )

        self.draw_fluorescent_white_polyline(
            p, front, closed=True, line_width=base_w, glow=glow, alpha=alpha, dashed=predicted,
        )

        edge_lengths = [
            math.hypot(front[(index + 1) % 4].x() - front[index].x(), front[(index + 1) % 4].y() - front[index].y())
            for index in range(4)
        ]
        brace: list[tuple[QPointF, QPointF]] = []
        if edge_lengths[0] + edge_lengths[2] >= edge_lengths[1] + edge_lengths[3]:
            for amount in (0.24, 0.76):
                brace.append((lerp(front[0], front[1], amount), lerp(front[3], front[2], amount)))
        else:
            for amount in (0.24, 0.76):
                brace.append((lerp(front[1], front[2], amount), lerp(front[0], front[3], amount)))
        self.draw_fluorescent_white_segments(
            p, brace, line_width=max(0.65, base_w * 0.72), glow=glow, alpha=alpha * 0.68, dashed=predicted,
        )

        if label:
            box = front_poly.boundingRect()
            label_width = max(42.0, text_width(p, self.font("poppins_medium", 6.4), label) + 4.0)
            self.draw_text(
                p,
                QRectF(box.left(), box.top() - 15, label_width, 13),
                label,
                self.font("poppins_medium", 6.4),
                color("#ffffff", 0.72 if predicted else 0.96),
            )

    @staticmethod
    def _vision_wire_key(armor) -> tuple[int, int, bool]:
        target_id = armor.target_id if armor.target_id >= 0 else armor.armor_id
        plate_id = armor.plate_id if armor.plate_id >= 0 else armor.armor_id
        return target_id, plate_id, bool(armor.predicted)

    def _append_vision_wire_armor(
        self,
        batch: VisionWireBatch,
        front: list[QPointF],
        back: list[QPointF],
        *,
        width: float,
        alpha: float,
        predicted: bool,
        label: str | None = None,
        label_scale: float = 1.0,
    ) -> None:
        """Append fluorescent white linework without any filled geometry.

        Formula matches visual-demo/esp-box-white.html (glow=0.35, pure #FFFFFF).
        """
        if len(front) != 4:
            return
        alpha = max(0.0, min(1.0, float(alpha)))
        # jar lineWidth 1.0; module Line Width default 2.0 → base ~1.0.
        core_width = max(0.75, float(width) * 0.5 * (0.85 if predicted else 1.0))
        glow = 0.85
        if len(back) == 4:
            batch.fluorescent_polyline(
                back,
                width=max(0.6, core_width * 0.85),
                alpha=alpha * 0.55,
                closed=True,
                dashed=True,
                glow=glow,
            )
            for index in range(4):
                batch.fluorescent_line(
                    front[index],
                    back[index],
                    width=max(0.65, core_width * 0.9),
                    alpha=alpha * 0.65,
                    dashed=True,
                    glow=glow,
                )
        batch.fluorescent_polyline(
            front,
            width=core_width,
            alpha=alpha,
            closed=True,
            dashed=predicted,
            glow=glow,
        )

        def lerp(a: QPointF, b: QPointF, amount: float) -> QPointF:
            return QPointF(
                a.x() + (b.x() - a.x()) * amount,
                a.y() + (b.y() - a.y()) * amount,
            )

        lengths = [
            math.hypot(
                front[(index + 1) % 4].x() - front[index].x(),
                front[(index + 1) % 4].y() - front[index].y(),
            )
            for index in range(4)
        ]
        for amount in (0.24, 0.76):
            if lengths[0] + lengths[2] >= lengths[1] + lengths[3]:
                start, end = lerp(front[0], front[1], amount), lerp(front[3], front[2], amount)
            else:
                start, end = lerp(front[1], front[2], amount), lerp(front[0], front[3], amount)
            batch.fluorescent_line(
                start,
                end,
                width=max(0.6, core_width * 0.72),
                alpha=alpha * 0.68,
                dashed=predicted,
                glow=glow,
            )

        if label:
            box = QPolygonF(front).boundingRect()
            font = self.font("poppins_medium", 6.4 * max(1.0, label_scale))
            label_width = max(52.0 * label_scale, len(label) * 6.6 * label_scale)
            batch.labels.text(
                QRectF(
                    box.left(),
                    box.top() - 16.0 * label_scale,
                    label_width,
                    13.0 * label_scale,
                ),
                label,
                font,
                QColor(255, 255, 255, round(245 * alpha)),
            )

    def build_vision_wire_batch(
        self,
        width: int,
        height: int,
        result: VisionResult,
        module: Module,
    ) -> VisionWireBatch:
        batch = VisionWireBatch()
        overlay = self.registry.get("RobotOverlay")
        line_width = self.get_setting_number(module, "Line Width", 2.0)
        opacity = self.get_setting_number(module, "Opacity", 0.82)
        scale = self.get_hud_scale(width, height)
        line_width *= scale
        depth = self.get_setting_number(overlay, "3D Depth", 0.22)
        max_targets = int(self.get_setting_number(overlay, "Max Targets", 6))
        calibrated = self.vision_result_calibrated(result)
        local_pnp = bool(self._vision_snapshot and self._vision_snapshot.source == "Local") and any(
            len(armor.back_points) == 4
            for armor in result.detections + result.predicted_armors
        )
        show_prediction = (
            self.setting_bool(module, "Show Prediction", True)
            and self.setting_bool(overlay, "Predict Plates", True)
            and (calibrated or local_pnp)
        )
        show_labels = self.setting_bool(module, "Show Labels", True)
        prediction_labels = self.setting_bool(module, "Prediction Labels", False)
        observed = [armor for armor in result.detections if len(armor.points) == 4]
        predicted = [armor for armor in result.predicted_armors if len(armor.points) == 4]
        aim = result.aim_armor if result.aim_armor and len(result.aim_armor.points) == 4 else None
        aim_front = self.armor_esp_points(aim.points, result, width, height) if aim is not None else []
        aim_box = QPolygonF(aim_front).boundingRect() if aim_front else QRectF()
        emitted: set[tuple[int, int, bool]] = set()

        def prediction_alpha(armor) -> float:
            armor_depth = armor.depth_m if armor.depth_m > 0 else armor.distance_m
            if armor_depth <= 0:
                return 0.58
            return max(0.24, min(0.62, 6.5 / max(1.0, armor_depth)))

        for armor in (observed + (predicted if show_prediction else []))[:max_targets]:
            key = self._vision_wire_key(armor)
            if key in emitted:
                continue
            front = self.armor_esp_points(armor.points, result, width, height)
            if len(front) != 4:
                continue
            if aim is not None and not armor.predicted:
                box = QPolygonF(front).boundingRect()
                if math.dist(
                    (box.center().x(), box.center().y()),
                    (aim_box.center().x(), aim_box.center().y()),
                ) < max(12.0 * scale, aim_box.width() * 0.45):
                    continue
            back = self.armor_esp_back_points(armor, result, width, height, depth)
            if armor.predicted and aim_front:
                front, back = self.constrain_prediction_geometry(front, back, aim_front)
            label = f"P{armor.plate_id}" if armor.predicted and prediction_labels else None
            self._append_vision_wire_armor(
                batch,
                front,
                back,
                width=line_width,
                alpha=prediction_alpha(armor) if armor.predicted else opacity,
                predicted=bool(armor.predicted),
                label=label,
                label_scale=scale,
            )
            emitted.add(key)

        if aim is not None:
            aim_key = self._vision_wire_key(aim)
            back = self.armor_esp_back_points(aim, result, width, height, depth)
            distance = aim.distance_m if aim.distance_m > 0 else aim.depth_m
            label = None
            if show_labels:
                label = f"DIST {distance:.1f}m" if distance > 0 else "DIST --"
            self._append_vision_wire_armor(
                batch,
                aim_front,
                back,
                width=line_width + 0.35 * scale,
                alpha=1.0,
                predicted=False,
                label=label,
                label_scale=scale,
            )
            emitted.add(aim_key)
        return batch

    def paint_gpu_vision_layer(
        self,
        functions,
        width: int,
        height: int,
        ratio: float,
    ) -> bool:
        """Clear and optionally populate the sole mechanical ESP layer."""
        module = self.registry.get("Armor3DESP")
        armor_module = self.registry.get("ArmorAutoAim")
        overlay = self.registry.get("RobotOverlay")
        native_owner = bool(
            not self.home_visible
            and module
            and module.enabled
            and armor_module
            and armor_module.enabled
            and self.setting_mode(module, "Style", "PolarMechanicalWire") == "PolarMechanicalWire"
            and self.setting_mode(overlay, "ESP Style", "3D Wire") != "Polar Outline"
            and self._vision_source != "Mock"
            and self.vision_wire_gpu.available
            and self.clickgui_gpu.available
        )
        result = self.interpolated_vision_result(time.perf_counter()) if native_owner else None
        batch = self.build_vision_wire_batch(width, height, result, module) if result is not None and module is not None else VisionWireBatch()
        if batch.labels.commands:
            self.clickgui_gpu.prepare_frame(batch.labels, ratio)
        if not self.gpu_compositor.begin_vision_layer(functions):
            return False
        try:
            if not native_owner or result is None:
                return native_owner
            if not self.vision_wire_gpu.render(functions, batch, width, height, ratio):
                return False
            if batch.labels.commands and not self.clickgui_gpu.render(
                functions,
                batch.labels,
                width,
                height,
                ratio,
                atlas_prepared=True,
            ):
                return False
            return True
        finally:
            self.gpu_compositor.end_vision_layer()

    def draw_armor_quad(self, p: QPainter, points: list[QPointF], c: QColor, line_width: float, *, dashed: bool = False, aim: bool = False) -> None:
        if len(points) != 4:
            return
        polygon = QPolygonF(points)
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color("#000000", 0.72), line_width + 2.0, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(polygon)
        p.setPen(QPen(c, line_width, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(polygon)
        if aim:
            center = polygon.boundingRect().center()
            p.setPen(QPen(c, max(1.0, line_width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(center + QPointF(-7, 0), center + QPointF(7, 0))
            p.drawLine(center + QPointF(0, -7), center + QPointF(0, 7))
        p.restore()

    def smooth_armor_geometry(self, armor, result: VisionResult):
        """只平滑连续结果的几何位置；没有结果时不保留任何绘制状态。"""
        if len(armor.points) != 4:
            return armor
        key = (armor.armor_id, armor.plate_id, armor.predicted, armor.label)
        if not result.detections and not result.predicted_armors:
            self._armor_geometry_smooth.clear()
            return armor

        previous = self._armor_geometry_smooth.get(key)
        if previous is None:
            self._armor_geometry_smooth[key] = (armor.points, armor.back_points)
            return armor

        # 约 55ms 的响应时间；识别结果落后相机帧时提高追赶速度，但不制造旧目标。
        alpha = 1.0 - math.exp(-max(0.001, min(0.12, self.frame_dt)) / 0.055)
        frame_lag = max(0, self._last_capture_sequence - result.sequence)
        alpha = max(alpha, min(0.72, frame_lag * 0.12))

        def blend_points(
            current: tuple[tuple[float, float], ...],
            old: tuple[tuple[float, float], ...],
        ) -> tuple[tuple[float, float], ...]:
            if len(current) != len(old):
                return current
            return tuple(
                (
                    before[0] + (after[0] - before[0]) * alpha,
                    before[1] + (after[1] - before[1]) * alpha,
                )
                for before, after in zip(old, current)
            )

        points = blend_points(armor.points, previous[0])
        back_points = blend_points(armor.back_points, previous[1]) if len(armor.back_points) == 4 and len(previous[1]) == 4 else armor.back_points
        self._armor_geometry_smooth[key] = (points, back_points)
        return replace(armor, points=points, back_points=back_points)

    def draw_armor_3d_esp(self, p: QPainter, width: int, height: int, result: VisionResult, module: Module) -> None:
        if not result.detections and not result.predicted_armors:
            self._armor_geometry_smooth.clear()
        overlay = self.registry.get("RobotOverlay")
        overlay_style = self.setting_mode(overlay, "ESP Style", "3D Wire")
        style = self.setting_mode(module, "Style", "PolarMechanicalWire")
        line_width = self.get_setting_number(module, "Line Width", 2.0)
        opacity = self.get_setting_number(module, "Opacity", 0.82)
        calibrated = self.vision_result_calibrated(result)
        local_pnp = bool(self._vision_snapshot and self._vision_snapshot.source == "Local") and any(len(armor.back_points) == 4 for armor in result.detections + result.predicted_armors)
        show_prediction = self.setting_bool(module, "Show Prediction", True) and self.setting_bool(overlay, "Predict Plates", True) and (calibrated or local_pnp)
        show_labels = self.setting_bool(module, "Show Labels", True)
        prediction_labels = self.setting_bool(module, "Prediction Labels", False)
        depth = self.get_setting_number(overlay, "3D Depth", 0.22)
        max_targets = int(self.get_setting_number(overlay, "Max Targets", 6))
        only_secondary = self.setting_bool(overlay, "Only Secondary", True)
        primary = color("#ffffff", opacity)
        aim_color = color("#ffffff")

        # VisionRenderInterpolator 已按视觉时间戳在显示帧间插值。这里必须直接使用
        # 插值结果，不能再做一次追赶平滑，否则低频推理会呈现明显拖滞和阶梯感。
        observed = [armor for armor in result.detections if len(armor.points) == 4]
        predicted = [armor for armor in result.predicted_armors if len(armor.points) == 4]
        aim = result.aim_armor if result.aim_armor and len(result.aim_armor.points) == 4 else None

        def prediction_alpha(armor) -> float:
            """按桥接器回传的真实深度衰减预测线框；旧桥接器无深度时保持默认透明度。"""
            depth = armor.depth_m if armor.depth_m > 0 else armor.distance_m
            if depth <= 0:
                return 0.72
            return max(0.28, min(0.86, 7.5 / max(1.0, depth)))

        if overlay_style == "Polar Outline" or style == "PolarOutline2D":
            source = observed if observed or not calibrated else predicted
            for armor in source:
                points = self.armor_esp_points(armor.points, result, width, height)
                xs = [point.x() for point in points]
                ys = [point.y() for point in points]
                rect = QRectF(min(xs), min(ys), max(4.0, max(xs) - min(xs)), max(4.0, max(ys) - min(ys)))
                c = aim_color if armor.aim else primary
                self.draw_minimal_bracket_lock(p, rect, VisionTarget(rect.x(), rect.y(), rect.width(), rect.height(), armor.confidence, armor.label), armor.aim)
                if show_labels:
                    self.draw_pill(p, QPointF(rect.left(), rect.top() - 22), f"{armor.label.upper()} {armor.confidence:.0%}", c)
            return

        glass = overlay_style == "3D Glass"
        aim_front = self.armor_esp_points(aim.points, result, width, height) if aim is not None else []
        for armor in (observed + (predicted if show_prediction else []))[:max_targets]:
            front = self.armor_esp_points(armor.points, result, width, height)
            if len(front) != 4:
                continue
            box = QPolygonF(front).boundingRect()
            if aim is not None and not armor.predicted:
                aim_box = QPolygonF(self.armor_esp_points(aim.points, result, width, height)).boundingRect()
                if math.dist((box.center().x(), box.center().y()), (aim_box.center().x(), aim_box.center().y())) < max(12.0, aim_box.width() * 0.45):
                    # 主目标由下方的 Aim Face 单独绘制，不能再作为 RobotOverlay 重复画一次。
                    continue
            ghost = armor.predicted
            display_color = color("#ffffff", prediction_alpha(armor) * 0.72) if ghost else primary
            back = self.armor_esp_back_points(armor, result, width, height, depth)
            if ghost and aim_front:
                front, back = self.constrain_prediction_geometry(front, back, aim_front)
            if style == "PolarMechanicalWire":
                label = f"P{armor.plate_id}" if ghost and prediction_labels else None
                self.draw_polar_mechanical_wire(
                    p,
                    front,
                    back,
                    display_color,
                    line_width,
                    predicted=ghost,
                    label=label,
                )
            else:
                self.draw_clean_3d_esp_box(
                    p,
                    front,
                    back,
                    display_color,
                    line_width,
                    glass=glass,
                    ghost=ghost,
                    label=(f"P{armor.plate_id}" if ghost else f"{armor.label.upper()} {armor.distance_m:.1f}m") if show_labels else None,
                )
        if aim is not None:
            points = aim_front
            back = self.armor_esp_back_points(aim, result, width, height, depth)
            if style == "PolarMechanicalWire":
                self.draw_polar_mechanical_wire(
                    p,
                    points,
                    back,
                    aim_color,
                    line_width + 0.35,
                    predicted=False,
                )
            else:
                self.draw_clean_3d_esp_box(p, points, back, aim_color, line_width + 0.35, glass=glass, ghost=False, label=None)
            if show_labels:
                box = QPolygonF(points).boundingRect()
                distance = aim.distance_m if aim.distance_m > 0 else aim.depth_m
                label = f"DIST {distance:.1f}m" if distance > 0 else "DIST --"
                if style == "PolarMechanicalWire":
                    label_width = max(62.0, text_width(p, self.font("poppins_medium", 6.4), label) + 4.0)
                    self.draw_text(
                        p,
                        QRectF(box.left(), box.top() - 16, label_width, 13),
                        label,
                        self.font("poppins_medium", 6.4),
                        color("#ffffff", 0.96),
                    )
                else:
                    self.draw_pill(p, QPointF(box.left(), box.top() - 24), label, aim_color)
        if local_pnp and not calibrated:
            self._bottom_left_diagnostics.append(("DESKTOP PNP | APPROX FOV", self.hud_accent(), 1))
        elif not calibrated:
            self._bottom_left_diagnostics.append(("UNCALIBRATED | detection only", self.hud_warning(), 1))
        kill_status = getattr(self.state, "vision_kill_status", "IDLE")
        if kill_status not in ("IDLE", "NO_DETECTION"):
            status_color = self.hud_accent() if kill_status in (
                "LIT_TRACKED", "MODEL_CONFIRMED", "REFLECTION_IGNORED",
                "WAITING_FRESH_FRAMES", "VISION_CONFIRMED",
            ) else self.hud_warning()
            self._bottom_left_diagnostics.append((f"KILL VISION | {kill_status}", status_color, 2))

    def combat_target_visual(self, module: Module | None = None) -> str:
        module = module or self.registry.get("CombatTargetHUD")
        setting = module.get_setting("Visual") if module else None
        value = str(setting.value) if setting else "Clear"
        return value if value in VALID_COMBAT_HUD_VISUALS else "Clear"

    def draw_combat_target_arc(
        self,
        p: QPainter,
        center: QPointF,
        radius: float,
        start_deg: float,
        end_deg: float,
        arc_color: QColor,
        width: float,
        *,
        glow: float = 0.0,
        alpha: float | None = None,
    ) -> None:
        """Jar-style progress arc (visual-demo drawArc).

        Main stroke uses butt/FlatCap so 15/16 red/blue stay interleaved.
        Enhanced glow is a softer round-cap underlay (demo: width+glow @ α0.2).
        """
        if end_deg - start_deg < 0.05:
            return
        stroke = QColor(arc_color)
        if alpha is not None:
            stroke.setAlphaF(max(0.0, min(1.0, float(alpha) * stroke.alphaF())))
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        span = -int(round((end_deg - start_deg) * 16.0))
        start16 = int(round(start_deg * 16.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if glow > 0.0:
            glow_color = QColor(stroke)
            glow_color.setAlphaF(max(0.0, min(1.0, glow_color.alphaF() * 0.20)))
            glow_pen = QPen(glow_color, width + float(glow))
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(glow_pen)
            p.drawArc(rect, start16, span)
        pen = QPen(stroke, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawArc(rect, start16, span)

    def draw_combat_target_hud(
        self,
        p: QPainter,
        width: int,
        height: int,
        module: Module | None = None,
        *,
        presence: TargetHudPresenceFrame | None = None,
    ) -> None:
        if presence is not None and not presence.visible:
            return
        visual = self.combat_target_visual(module)
        now = time.perf_counter()
        dt = max(0.0, min(0.05, now - self._combat_hud_last_time))
        self._combat_hud_last_time = now
        aim_override = None
        if presence is not None and presence.phase in {"Grace10s", "Fading"}:
            aim_override = 0.0
        frame = self.combat_hud_animator.update(
            self.state,
            dt,
            visual,
            aim_override=aim_override,
        )
        show_bars = self.setting_bool(module, "Show Bars", False)
        show_status_line = self.setting_bool(module, "Show Status Line", True)
        scale = 1.65 if visual == "Classic" else 2.35
        enhanced = visual == "Enhanced"
        center = QPointF(width / 2.0 + 1.0, height / 2.0 + 1.0)
        red_radius = 15.0 * scale
        blue_radius = 16.0 * scale
        red_width = 5.0 * scale * (0.92 if enhanced else 1.0)
        blue_width = 3.0 * scale * (0.92 if enhanced else 1.0)
        health = max(0.0, min(100.0, frame.self_anim))
        heat = max(0.0, min(100.0, frame.heat_anim))
        health_color = self.combat_health_color(health, visual)
        heat_color = self.combat_heat_color(heat, visual)

        p.save()
        if presence is not None:
            p.setOpacity(p.opacity() * presence.opacity)
            p.translate(center)
            p.scale(presence.scale, presence.scale)
            p.translate(-center)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if visual != "Classic":
            # visual-demo clear/enhanced: circular radial plate + one gray track.
            # Circle only (no rect fill) so the GPU ROI stays free of square edges.
            plate_r = blue_radius + red_width * 0.5 + 10.0
            plate = QRadialGradient(center, plate_r)
            plate.setColorAt(0.0, color("#140e0a", 0.55))
            plate.setColorAt(0.72, color("#140e0a", 0.18))
            plate.setColorAt(1.0, color("#140e0a", 0.0))
            plate_path = QPainterPath()
            plate_path.addEllipse(center, plate_r, plate_r)
            p.fillPath(plate_path, QBrush(plate))
            track_pen = QPen(color("#ffffff", 0.10), max(red_width, blue_width) + 1.0)
            track_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(track_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            track_radius = (red_radius + blue_radius) * 0.5
            p.drawEllipse(center, track_radius, track_radius)

        health_end = ring_end(health)
        heat_end = ring_end(heat)
        if enhanced and health > 0.5 and frame.self_ghost > health + 0.5:
            self.draw_combat_target_arc(
                p, center, red_radius, health_end, ring_end(frame.self_ghost),
                color("#ffdcb4", 0.45), red_width, alpha=0.6,
            )
        if enhanced and heat > 0.5 and frame.heat_ghost > heat + 0.5:
            self.draw_combat_target_arc(
                p, center, blue_radius, heat_end, ring_end(frame.heat_ghost),
                color("#b4d2ff", 0.45), blue_width, alpha=0.6,
            )
        if health > 0.5:
            self.draw_combat_target_arc(
                p, center, red_radius, 180.0, health_end, health_color, red_width,
                glow=3.0 if enhanced else 0.0,
            )
        if heat > 0.5:
            self.draw_combat_target_arc(
                p, center, blue_radius, 180.0, heat_end, heat_color, blue_width,
                glow=3.0 if enhanced else 0.0,
            )

        # Ring-center reticle only: white = idle (no aimbot), red = TRACK/LOCK.
        aim_on = frame.aim_anim >= 40.0
        crosshair_color = color("#ff1a1a") if aim_on else color("#ffffff", 0.85)
        crosshair_pen = QPen(crosshair_color, 1.35)
        crosshair_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(crosshair_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for start, end in (
            ((-9.0, 0.0), (-3.0, 0.0)),
            ((3.0, 0.0), (9.0, 0.0)),
            ((0.0, -9.0), (0.0, -3.0)),
            ((0.0, 3.0), (0.0, 9.0)),
        ):
            p.drawLine(center + QPointF(*start), center + QPointF(*end))

        if visual == "Classic":
            health_text = f"HP {float(self.state.current_health):.1f}"
            heat_text = f"HEAT {heat:.0f}%"
            self.draw_text(p, QRectF(center.x() - 70, center.y() + 22, 140, 14), health_text, self.font("poppins_medium", 7.2), color("#ffffff"), Qt.AlignmentFlag.AlignCenter)
            self.draw_text(p, QRectF(center.x() - 70, center.y() + 34, 140, 14), heat_text, self.font("poppins_medium", 6.8), heat_color, Qt.AlignmentFlag.AlignCenter)
        elif show_bars:
            self.draw_combat_target_card(
                p,
                width,
                height,
                visual,
                frame,
                health,
                heat,
                show_status_line=show_status_line,
            )
        p.restore()

    def draw_combat_target_hud_layer(
        self,
        p: QPainter,
        width: int,
        height: int,
        module: Module,
        *,
        presence: TargetHudPresenceFrame | None = None,
    ) -> None:
        """Compatibility path: draw vectors directly, never an image quad."""
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.draw_combat_target_hud(
            p,
            width,
            height,
            module,
            presence=presence,
        )
        p.restore()

    def combat_health_color(self, value: float, visual: str) -> QColor:
        if visual == "Classic":
            return color("#ff0000")
        if value > 55.0:
            return color("#ff4d5a")
        if value > 28.0:
            return color("#ff8a2b")
        return color("#ff1a1a")

    def combat_heat_color(self, value: float, visual: str) -> QColor:
        if visual == "Classic":
            return color("#0000ff")
        if value < 40.0:
            return color("#5ec8ff")
        if value < 75.0:
            return color("#ffb347")
        return color("#ff4444")

    def draw_combat_target_card(
        self,
        p: QPainter,
        width: int,
        height: int,
        visual: str,
        frame: Any,
        health: float,
        heat: float,
        *,
        show_status_line: bool,
    ) -> None:
        enhanced = visual == "Enhanced"
        card_w = 170.0
        card_h = 72.0 if show_status_line else 64.0
        rect = QRectF(width / 2.0 - card_w / 2.0, height / 2.0 + 52.0, card_w, card_h)
        if enhanced:
            for spread, alpha in ((5.0, 0.08), (2.5, 0.14)):
                p.setPen(QPen(color("#ff9f43", alpha), spread))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect, 10.0, 10.0)
        card_path = QPainterPath()
        card_path.addRoundedRect(rect, 10.0, 10.0)
        p.fillPath(card_path, color("#120e0c", 0.90))
        p.setPen(QPen(color("#ff9f43", 0.55) if enhanced else color("#ffffff", 0.12), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(card_path)
        pad = 10.0
        aim_label = "LOCK" if frame.aim_anim >= 80.0 else ("TRACK" if frame.aim_anim >= 40.0 else "IDLE")
        self.draw_text(p, QRectF(rect.left() + pad, rect.top() + 5, 95, 15), f"AIM  {aim_label}", self.font("poppins_medium", 7.2), color("#ffffff"))
        self.draw_text(p, QRectF(rect.right() - 50, rect.top() + 5, 40, 15), f"{frame.aim_anim:.0f}%", self.font("poppins_medium", 6.8), color("#ffc896", 0.90), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        aim_bar = QRectF(rect.left() + pad, rect.top() + 24, rect.width() - pad * 2.0, 8.0)
        rounded_rect(p, aim_bar, 3.0, color("#000000", 0.45))
        aim_fill = QRectF(aim_bar)
        aim_fill.setWidth(aim_bar.width() * max(0.0, min(100.0, frame.aim_anim)) / 100.0)
        if aim_fill.width() > 0.5:
            aim_gradient = QLinearGradient(aim_fill.topLeft(), aim_fill.topRight())
            aim_gradient.setColorAt(0.0, color("#ffb347"))
            aim_gradient.setColorAt(1.0, color("#ff6b35"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(aim_gradient))
            p.drawRoundedRect(aim_fill, 3.0, 3.0)

        ammo = max(0, int(self.state.remaining_ammo))
        ammo_max = max(0, int(self.state.ammo_capacity))
        self.draw_text(p, QRectF(rect.left() + pad, rect.top() + 35, rect.width() - pad * 2.0, 15), f"AMMO  {ammo}/{ammo_max}", self.font("poppins_medium", 7.2), color("#ffffff"))
        ammo_bar = QRectF(rect.left() + pad, rect.top() + 49, rect.width() - pad * 2.0, 8.0)
        rounded_rect(p, ammo_bar, 3.0, color("#000000", 0.45))
        if enhanced and frame.ammo_ghost > frame.ammo_anim + 0.5:
            ghost = QRectF(ammo_bar)
            ghost.setWidth(ammo_bar.width() * max(0.0, min(100.0, frame.ammo_ghost)) / 100.0)
            rounded_rect(p, ghost, 3.0, color("#ffdcb4", 0.40))
        ammo_fill = QRectF(ammo_bar)
        ammo_fill.setWidth(ammo_bar.width() * max(0.0, min(100.0, frame.ammo_anim)) / 100.0)
        if ammo_fill.width() > 0.5:
            rounded_rect(p, ammo_fill, 3.0, color("#ff5555") if ammo <= 0 else color("#5ec8ff"))
        if show_status_line:
            status = f"HEAT {heat:.0f}%  |  HP {int(self.state.current_health)}/{int(self.state.max_health)}"
            self.draw_text(p, QRectF(rect.left() + pad, rect.bottom() - 11, rect.width() - pad * 2.0, 10), status, self.font("poppins_regular", 5.8), color("#ffffff", 0.55))

    def draw_crosshair(self, p: QPainter, width: int, height: int) -> None:
        module = self.registry.get("Crosshair")
        size_setting = module.get_setting("Size") if module else None
        size = float(size_setting.value if size_setting else 18)
        cx = width / 2
        cy = height / 2
        heat_ratio = self.state.current_heat / max(1.0, self.state.max_heat)
        main = self.hud_state_color("heat", heat_ratio)
        p.setPen(QPen(main, 1.7))
        p.setBrush(main)
        p.drawEllipse(QPointF(cx, cy), 2.4, 2.4)
        p.drawLine(QPointF(cx - size, cy), QPointF(cx - 6, cy))
        p.drawLine(QPointF(cx + 6, cy), QPointF(cx + size, cy))
        p.drawLine(QPointF(cx, cy - size), QPointF(cx, cy - 6))
        p.drawLine(QPointF(cx, cy + 6), QPointF(cx, cy + size))

    def draw_chassis_gimbal_indicator(self, p: QPainter, width: int, height: int) -> None:
        """Bottom chassis/gimbal compass (main & gestalt-lab layout).

        Liquid glass (README 液态玻璃规范): register the lens on the live
        painter via draw_hud_liquid_glass (GPU → add_glass; CPU → liquid_glass).
        Never put an opaque frosted plate under the content — that violates
        “采样镜片后方场景” and looks like a dark card.

        IMPORTANT: never stroke hull/barrel with QPainter directly onto an
        OpenGL paint device. On the GPU dynamic FBO, Qt's AA path turns them
        into opaque stacked tiles. CPU-raster icon+text to a tiny QImage, blit
        once above the glass (text/icons always on top of the lens).
        """
        module = self.registry.get("ChassisGimbalIndicator")
        if module is None or not module.enabled:
            return
        style_setting = module.get_setting("Style")
        style = str(style_setting.value) if style_setting else "Minimal"
        size = self.get_setting_number(module, "Size", 74.0)
        smooth = max(0.05, min(1.0, self.get_setting_number(module, "Smooth", 0.35)))
        show_angle = self.setting_bool(module, "Show Angle", True)
        show_mode = self.setting_bool(module, "Show Mode", True)
        chassis_yaw = self.animated_angle("hud.chassis_gimbal.chassis", self.state.chassis_yaw_deg, smooth)
        gimbal_yaw = self.animated_angle("hud.chassis_gimbal.gimbal", self.state.gimbal_yaw_deg, smooth)
        relative_yaw = normalize_angle_deg(gimbal_yaw - chassis_yaw)
        spin = bool(self.registry.get("SpinMode") and self.registry.get("SpinMode").enabled)
        mode_text = "SPIN" if spin else self.chassis_follow_mode()
        alert = min(1.0, abs(relative_yaw) / 90.0)
        pulse = 0.5 + 0.5 * math.sin(time.perf_counter() * 4.0)
        micro = self.hud_density() == "CombatCompact"

        if micro:
            size = min(max(48.0, size), 64.0)
            center = QPointF(width / 2.0, height - 86.0)
            active = self.anim.value("hud.chassis_gimbal.micro", 1.0, self.anim_duration(0.20), Easings.ease_out_pow4, initial=0.0)
            disc_r = size * 0.54
            disc_rect = QRectF(center.x() - disc_r, center.y() - disc_r, disc_r * 2.0, disc_r * 2.0)
            pad = 14.0
            img_w = int(math.ceil(size * 1.55 + pad * 2))
            img_h = int(math.ceil(size * 1.65 + pad * 2))
            origin = QPointF(center.x() - img_w * 0.5, center.y() - img_h * 0.5)
            image = QImage(img_w, img_h, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            ip = QPainter(image)
            ip.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            ip.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            ip.translate(-origin.x(), -origin.y())
            # Content only — glass is registered on the live painter below.
            self.draw_chassis_gimbal_compass_base(ip, center, size * 0.40, style, spin, pulse)
            self.draw_chassis_body_direction(ip, center, size, chassis_yaw, style, spin, pulse)
            self.draw_gimbal_turret_direction(ip, center, size, gimbal_yaw, alert)
            if show_angle or alert > 0.66:
                self.draw_glass_text(
                    ip,
                    QRectF(center.x() - 40, center.y() + size * 0.46, 80, 14),
                    f"{relative_yaw:+.0f}°",
                    self.font("poppins_medium", 7.4),
                    self.hud_accent() if alert < 0.66 else self.hud_warning(),
                    Qt.AlignmentFlag.AlignCenter,
                )
            if show_mode:
                self.draw_glass_text(
                    ip,
                    QRectF(center.x() - 40, center.y() - size * 0.68, 80, 12),
                    mode_text,
                    self.font("poppins_medium", 6.6),
                    self.hud_warning() if spin else THEME.muted,
                    Qt.AlignmentFlag.AlignCenter,
                )
            ip.end()
            p.save()
            p.setOpacity(active)
            # Circular island lens under strokes (LensIsland: radius = half height).
            self.draw_hud_liquid_glass(p, disc_rect, disc_r, surface="LensIsland", hover=0.12 * alert)
            p.drawImage(origin, image)
            p.restore()
            return

        panel_w = max(142.0, size * 2.05)
        panel_h = size + 42.0
        x = width / 2.0 - panel_w / 2.0
        y = max(112.0, height - 64.0 - panel_h - 18.0)
        rect = QRectF(x, y, panel_w, panel_h)
        active = self.anim.value("hud.chassis_gimbal.panel", 1.0, self.anim_duration(0.24), Easings.ease_out_pow4, initial=0.0)
        glass_radius = 10.0

        img_w = int(math.ceil(panel_w)) + 6
        img_h = int(math.ceil(panel_h)) + 6
        origin = QPointF(x - 3.0, y - 3.0)
        image = QImage(img_w, img_h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        ip = QPainter(image)
        ip.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ip.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        ip.translate(-origin.x(), -origin.y())

        # Content layer only (no frosted plate — glass is the backdrop).
        top_line = QLinearGradient(rect.left() + 14, rect.top() + 5, rect.right() - 14, rect.top() + 5)
        top_line.setColorAt(0.0, with_alpha(self.hud_accent(), 0.25 + 0.30 * alert))
        top_line.setColorAt(1.0, with_alpha(self.hud_warning() if alert > 0.55 else self.hud_accent(), 0.18 + 0.34 * alert))
        ip.setPen(QPen(QBrush(top_line), 1.6))
        ip.drawLine(QPointF(rect.left() + 16, rect.top() + 5), QPointF(rect.right() - 16, rect.top() + 5))

        center = QPointF(rect.center().x(), rect.top() + 18.0 + size * 0.48)
        radius = size * 0.43
        self.draw_chassis_gimbal_compass_base(ip, center, radius, style, spin, pulse)
        self.draw_chassis_body_direction(ip, center, size, chassis_yaw, style, spin, pulse)
        self.draw_gimbal_turret_direction(ip, center, size, gimbal_yaw, alert)

        if show_angle:
            angle_text = f"REL {relative_yaw:+.0f}°"
            self.draw_glass_text(
                ip,
                QRectF(rect.left() + 11, rect.bottom() - 24, rect.width() * 0.56, 16),
                angle_text,
                self.font("poppins_medium", 7.6),
                THEME.text,
            )
        if show_mode:
            self.draw_glass_text(
                ip,
                QRectF(rect.right() - 64, rect.bottom() - 24, 52, 16),
                mode_text,
                self.font("poppins_medium", 7.4),
                self.hud_warning() if spin else THEME.muted,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
        ip.end()

        p.save()
        p.setOpacity(active)
        # MainGlass / LensRegular: sample scene, edge refraction only; content blit above.
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, glass_radius, surface="MainGlass", hover=0.10 * alert)
        else:
            glow_rect(p, rect, glass_radius, 0.10 * alert)
            self.draw_hud_liquid_glass(p, rect, glass_radius, surface="MainGlass", hover=0.14 * alert)
        p.drawImage(origin, image)
        p.restore()

    def draw_chassis_gimbal_compass_base(self, p: QPainter, center: QPointF, radius: float, style: str, spin: bool, pulse: float) -> None:
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color("#ffffff", 0.10), 1.0))
        p.drawEllipse(center, radius, radius)
        if style == "Compass":
            for index, angle in enumerate(range(0, 360, 45)):
                outer = self.direction_point(center, angle, radius + 2.0)
                inner = self.direction_point(center, angle, radius - (8.0 if index % 2 == 0 else 5.0))
                p.setPen(QPen(color("#ffffff", 0.30 if index % 2 == 0 else 0.16), 1.1))
                p.drawLine(inner, outer)
            self.draw_text(p, QRectF(center.x() - 8, center.y() - radius - 17, 16, 12), "N", self.font("poppins_bold", 6.8), THEME.muted, Qt.AlignmentFlag.AlignCenter)
        if spin:
            spin_radius = radius + 7.0 + 2.0 * pulse
            p.setPen(QPen(with_alpha(self.hud_warning(), 0.30 + 0.22 * pulse), 1.2))
            p.drawEllipse(center, spin_radius, spin_radius)
        p.restore()

    def draw_chassis_body_direction(self, p: QPainter, center: QPointF, size: float, yaw_deg: float, style: str, spin: bool, pulse: float) -> None:
        """Chassis heading — same silhouette as main/gestalt-lab (top-down hull + nose)."""
        p.save()
        p.translate(center)
        p.rotate(yaw_deg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Slightly higher contrast than stock so hull reads over dark plate / video.
        body_color = color("#ffffff", 0.14 if style == "Minimal" else 0.12)
        outline = color("#f2f6fb", 0.72)
        accent = with_alpha(self.hud_warning(), 0.40 + 0.28 * pulse) if spin else color("#ffffff", 0.55)
        if style == "Tank":
            track_w = size * 0.10
            track_h = size * 0.58
            rounded_rect(p, QRectF(-size * 0.30, -track_h / 2, track_w, track_h), 3, color("#ffffff", 0.05), color("#ffffff", 0.22), 1.0)
            rounded_rect(p, QRectF(size * 0.20, -track_h / 2, track_w, track_h), 3, color("#ffffff", 0.05), color("#ffffff", 0.22), 1.0)
            rounded_rect(p, QRectF(-size * 0.20, -size * 0.32, size * 0.40, size * 0.64), 5, body_color, outline, 1.25)
        else:
            rounded_rect(p, QRectF(-size * 0.22, -size * 0.30, size * 0.44, size * 0.60), 5, body_color, outline, 1.2)
        # Chassis forward chevron
        p.setPen(QPen(accent, 1.7 if spin else 1.4))
        p.drawLine(QPointF(0, -size * 0.30), QPointF(0, -size * 0.50))
        p.drawLine(QPointF(-size * 0.11, -size * 0.40), QPointF(0, -size * 0.50))
        p.drawLine(QPointF(size * 0.11, -size * 0.40), QPointF(0, -size * 0.50))
        p.restore()

    def draw_gimbal_turret_direction(self, p: QPainter, center: QPointF, size: float, yaw_deg: float, alert: float) -> None:
        """Gimbal / muzzle yaw — same layout as main/gestalt-lab (hub + barrel + tip)."""
        p.save()
        p.translate(center)
        p.rotate(yaw_deg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        turret = with_alpha(self.hud_accent(), 0.88)
        if alert > 0.55:
            turret = with_alpha(self.hud_warning(), 0.72 + 0.22 * alert)
        pen = QPen(turret, 2.15)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(QPointF(0, 0), QPointF(0, -size * 0.58))
        p.drawLine(QPointF(0, -size * 0.58), QPointF(-size * 0.075, -size * 0.46))
        p.drawLine(QPointF(0, -size * 0.58), QPointF(size * 0.075, -size * 0.46))
        p.setBrush(color("#05080e", 0.90))
        p.setPen(QPen(turret, 1.2))
        p.drawEllipse(QPointF(0, 0), size * 0.095, size * 0.095)
        p.setBrush(turret)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0, 0), size * 0.04, size * 0.04)
        p.restore()

    def direction_point(self, center: QPointF, angle_deg: float, radius: float) -> QPointF:
        rad = math.radians(angle_deg - 90.0)
        return QPointF(center.x() + math.cos(rad) * radius, center.y() + math.sin(rad) * radius)

    def animated_angle(self, key: str, target: float, smooth: float) -> float:
        track = self.hud_angle_tracks.setdefault(key, AngleRenderTrack())
        response = 8.0 + (1.0 - max(0.0, min(1.0, smooth))) * 18.0
        return track.sample(time.perf_counter(), target, response=response)

    def animated_scalar(self, key: str, target: float, response: float = 18.0) -> float:
        track = self.telemetry_render_tracks.setdefault(key, ScalarRenderTrack())
        return track.sample(time.perf_counter(), target, response=response)

    def chassis_follow_mode(self) -> str:
        chassis = self.registry.get("ChassisAssist")
        setting = chassis.get_setting("Follow") if chassis else None
        value = str(setting.value).upper() if setting else "FOLLOW"
        if value == "GIMBAL":
            return "FOLLOW"
        if value == "FIELD":
            return "FIELD"
        return "FREE"

    def draw_dynamic_island(self, p: QPainter, width: int) -> None:
        payload = self.dynamic_island_payload()
        title_font = self.font("poppins_bold", 9.4)
        desc_font = self.font("poppins_regular", 8.2)
        title_w = QFontMetricsF(title_font).horizontalAdvance(payload["title"])
        desc_w = QFontMetricsF(desc_font).horizontalAdvance(payload["description"])
        content_active = bool(payload["active"])
        collapsed_w = max(300.0, min(580.0, title_w + desc_w + 92.0))
        expanded_w = max(210.0, min(580.0, max(title_w, desc_w) + 66.0))
        target_w = expanded_w if content_active else collapsed_w
        target_h = 46.0 if content_active else 30.0
        self.dynamic_island_state.set_target_geometry(
            (width - target_w) / 2.0,
            17.0,
            target_w,
            target_h,
            target_h / 2.0,
        )
        state = self.dynamic_island_state
        content = state.content.progress
        rect = QRectF(state.x, state.y, state.width, state.height)
        radius = state.height / 2.0

        p.save()
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, radius, surface="LensIsland")
        else:
            rounded_rect(p, rect, radius, self.hud_surface(0.62), self.hud_panel_outline(0.08))
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)

        icon_size = 21.0 + 3.0 * content
        icon_rect = QRectF(rect.left() + 7.0, rect.top() + (rect.height() - icon_size) / 2.0, icon_size, icon_size)
        self.draw_dynamic_island_icon(
            p,
            icon_rect,
            str(payload["kind"]),
            payload["color"],
            max(0.18, 0.72 + 0.28 * content),
        )

        if content < 0.999:
            p.save()
            p.setOpacity(p.opacity() * (1.0 - content))
            p.setPen(QPen(with_alpha(self.hud_accent(), 0.90), 1.4))
            p.drawLine(QPointF(rect.left() + 38.0, rect.top() + 8.0), QPointF(rect.left() + 38.0, rect.bottom() - 8.0))
            self.draw_glass_text(p, QRectF(rect.left() + 46.0, rect.top(), 88.0, rect.height()), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 126.0, rect.top(), rect.width() - 134.0, rect.height()), payload["description"], desc_font, THEME.muted)
            p.restore()

        if content > 0.001:
            p.save()
            p.setOpacity(p.opacity() * content)
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 7.0, rect.width() - 50.0, 16.0), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 22.0, rect.width() - 50.0, 15.0), payload["description"], desc_font, THEME.muted)
            progress = max(0.0, min(1.0, float(payload["progress"])))
            bar_bg = QRectF(rect.left() + 8.0, rect.bottom() - 7.0, rect.width() - 16.0, 3.0)
            rounded_rect(p, bar_bg, 1.5, color("#ffffff", 0.12))
            filled = QRectF(bar_bg)
            filled.setWidth(max(4.0, bar_bg.width() * progress))
            rounded_rect(p, filled, 1.5, with_alpha(payload["color"], 0.95))
            p.restore()
        p.restore()

    def _draw_dynamic_island_legacy(self, p: QPainter, width: int) -> None:
        payload = self.dynamic_island_payload()
        title_font = self.font("poppins_bold", 9.4)
        desc_font = self.font("poppins_regular", 8.2)
        p.setFont(title_font)
        title_w = QFontMetricsF(title_font).horizontalAdvance(payload["title"])
        p.setFont(desc_font)
        desc_w = QFontMetricsF(desc_font).horizontalAdvance(payload["description"])
        content_active = bool(payload["active"])
        collapsed_w = max(300.0, min(580.0, title_w + desc_w + 92.0))
        expanded_w = max(210.0, min(580.0, max(title_w, desc_w) + 66.0))
        now = time.perf_counter()
        self.dynamic_island_morph.set_target(
            1.0 if content_active else 0.0,
            self.anim_duration(0.42),
            now=now,
        )
        morph = self.dynamic_island_morph.update(now=now)
        island_w = collapsed_w + (expanded_w - collapsed_w) * morph
        island_h = 30.0 + 16.0 * morph
        island_x = (width - island_w) / 2.0
        rect = QRectF(island_x, 17.0, island_w, island_h)
        # 灵动岛必须始终是完整胶囊。旧上限 14.5 会把 46px 的展开态
        # 截成圆角矩形，这正是运行界面里“岛变方”的根因。
        radius = rect.height() / 2.0
        active = self.anim.value("hud.dynamic_island.visible", 1.0, self.anim_duration(0.16), Easings.ease_out_expo, initial=0.0)
        icon_v = self.anim.value(
            "hud.dynamic_island.icon",
            1.0 if content_active else 0.0,
            self.anim_duration(0.17 if content_active else 0.13),
            Easings.ease_out_expo,
        )

        p.save()
        p.setOpacity(active)
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, radius, surface="ProminentGlass")
            # DynamicIslandSystem 的主体本来就是稳定的半透明黑色胶囊；
            # 液态玻璃负责背景折射，暗芯负责让内容在明亮图传上仍清晰。
        else:
            for pad, alpha in ((18.0, 0.045), (10.0, 0.070)):
                rounded_rect(p, rect.adjusted(-pad, -pad, pad, pad), radius + pad, color("#000000", alpha), None)
            rounded_rect(p, rect, radius, self.hud_surface(0.62), self.hud_panel_outline(0.08))
        p.setClipRect(rect.adjusted(0.6, 0.6, -0.6, -0.6))

        icon_size = 24.0 if content_active else 21.0
        icon_rect = QRectF(rect.left() + 7.0, rect.top() + (rect.height() - icon_size) / 2.0, icon_size, icon_size)
        self.draw_dynamic_island_icon(p, icon_rect, str(payload["kind"]), payload["color"], max(0.18, icon_v if content_active else 0.72))

        if content_active:
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 7.0, rect.width() - 50.0, 16.0), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 22.0, rect.width() - 50.0, 15.0), payload["description"], desc_font, THEME.muted)
            progress = self.anim.value(
                "hud.dynamic_island.progress",
                max(0.0, min(1.0, float(payload["progress"]))),
                self.anim_duration(0.12),
                Easings.ease_out_expo,
                initial=max(0.0, min(1.0, float(payload["progress"]))),
            )
            bar_bg = QRectF(rect.left() + 8.0, rect.bottom() - 7.0, rect.width() - 16.0, 3.0)
            rounded_rect(p, bar_bg, 1.5, color("#ffffff", 0.12))
            filled = QRectF(bar_bg)
            filled.setWidth(max(4.0, bar_bg.width() * progress))
            rounded_rect(p, filled, 1.5, with_alpha(payload["color"], 0.95))
        else:
            logo_grad = QLinearGradient(icon_rect.left(), icon_rect.top(), icon_rect.right(), icon_rect.bottom())
            logo_grad.setColorAt(0.0, with_alpha(self.hud_accent(), 0.70))
            logo_grad.setColorAt(1.0, with_alpha(self.hud_accent(), 0.95))
            p.setPen(QPen(QBrush(logo_grad), 1.4))
            p.drawLine(QPointF(rect.left() + 38.0, rect.top() + 8.0), QPointF(rect.left() + 38.0, rect.bottom() - 8.0))
            self.draw_glass_text(p, QRectF(rect.left() + 46.0, rect.top(), 88.0, rect.height()), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 126.0, rect.top(), rect.width() - 134.0, rect.height()), payload["description"], desc_font, THEME.muted)
        p.restore()

    def dynamic_smooth(self, key: str, target: float, speed: float) -> float:
        current = self.dynamic_smooth_values.get(key, target)
        difference = target - current
        if abs(difference) <= 0.025:
            current = target
        else:
            # DynamicIslandSystem 的核心是按目标差值连续收敛。这里改成
            # 帧率无关的指数形式，避免 60/120/144 Hz 下速度和手感不同。
            dt = max(1.0 / 240.0, min(1.0 / 20.0, float(self.frame_dt)))
            response = max(0.08, min(0.50, float(speed)))
            time_constant = 0.028 / response
            alpha = 1.0 - math.exp(-dt / time_constant)
            current += difference * alpha
        self.dynamic_smooth_values[key] = current
        return current

    def dynamic_island_payload(self) -> dict[str, Any]:
        now = time.perf_counter()
        if self.state.last_event != self.dynamic_island_last_event:
            self.dynamic_island_last_event = self.state.last_event
            self.dynamic_island_event_started = now

        recent_toast = None
        for toast in reversed(self.toasts):
            age = now - float(toast["created"])
            if age < 3.0:
                recent_toast = toast
                break

        if recent_toast is not None:
            age = now - float(recent_toast["created"])
            message = str(recent_toast["message"])
            kind, main = self.dynamic_message_kind(message)
            return {
                "active": True,
                "kind": kind,
                "color": main,
                "title": self.dynamic_message_title(message, kind),
                "description": message,
                "progress": max(0.0, 1.0 - age / 3.0),
            }

        event_age = now - self.dynamic_island_event_started
        if self.state.last_event and event_age < 2.7:
            kind, main = self.dynamic_message_kind(self.state.last_event)
            duration = max(1.0, float(getattr(self.state, "match_duration_sec", 300)))
            return {
                "active": True,
                "kind": kind,
                "color": main,
                "title": self.match_mode_manager.current.title,
                "description": self.state.last_event,
                "progress": max(0.0, min(1.0, self.state.stage_countdown_sec / duration)),
            }

        mqtt = "MQTT live" if self.state.mqtt_connected else "MQTT mock"
        serial = "SERIAL live" if self.state.serial_connected else "SERIAL mock"
        text = f"{self.scenario_manager.current.title} | {self.match_mode_manager.current.title} | {self.state.fps:.0f} FPS | {mqtt} | {serial}"
        return {"active": False, "kind": "info", "color": self.hud_accent(), "title": "POLAR-RM", "description": text, "progress": 1.0}

    def dynamic_message_kind(self, message: str) -> tuple[str, QColor]:
        lower = message.lower()
        if any(token in lower for token in ("fail", "error", "disabled", "closed")) or any(token in message for token in ("失败", "关闭", "错误")):
            return "warning", self.hud_danger()
        if any(token in lower for token in ("enabled", "ready", "saved", "loaded", "success")) or any(token in message for token in ("启用", "就绪", "保存", "加载", "打开")):
            return "success", self.hud_success()
        if "gui" in lower or "模式" in message or "Scenario" in message or "Match" in message:
            return "module", self.hud_accent()
        return "info", self.hud_accent()

    def dynamic_message_title(self, message: str, kind: str) -> str:
        if kind == "warning":
            return "Warning"
        if kind == "success":
            return "Success"
        if kind == "module":
            return "Client State"
        if "Radar" in message or "雷达" in message:
            return "Radar"
        return "POLAR-RM"

    def draw_dynamic_island_icon(self, p: QPainter, rect: QRectF, kind: str, main: QColor, amount: float) -> None:
        amount = max(0.0, min(1.0, amount))
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        icon_path = QPainterPath()
        icon_path.addEllipse(rect)
        p.setClipPath(icon_path, Qt.ClipOperation.IntersectClip)
        p.setPen(QPen(color("#ffffff", 0.10), 0.8))
        p.setBrush(with_alpha(main, 0.64))
        p.drawEllipse(rect)
        inner = rect.adjusted(2.0, 2.0, -2.0, -2.0)
        if kind == "module":
            rounded_rect(p, inner.adjusted(0.0, inner.height() * 0.25, 0.0, -inner.height() * 0.25), inner.height() * 0.25, color("#1e2028", 0.88))
            knob = inner.height() * 0.42
            kx = inner.left() + 2.0 + (inner.width() - knob - 4.0) * amount
            rounded_rect(p, QRectF(kx, inner.center().y() - knob / 2.0, knob, knob), knob / 2.0, color("#050507", 0.94))
            p.restore()
            return
        if kind == "success":
            clip = QRectF(rect.left(), rect.top(), rect.width() * amount, rect.height())
            p.save()
            p.setClipRect(clip)
            p.setPen(QPen(color("#ffffff", 0.92), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(rect.left() + rect.width() * 0.28, rect.center().y()), QPointF(rect.left() + rect.width() * 0.43, rect.bottom() - rect.height() * 0.30))
            p.drawLine(QPointF(rect.left() + rect.width() * 0.43, rect.bottom() - rect.height() * 0.30), QPointF(rect.right() - rect.width() * 0.22, rect.top() + rect.height() * 0.30))
            p.restore()
            p.restore()
            return
        if kind == "warning":
            clip = QRectF(rect.left(), rect.bottom() - rect.height() * amount, rect.width(), rect.height() * amount)
            p.save()
            p.setClipRect(clip)
            p.setPen(QPen(color("#ffffff", 0.92), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(rect.center().x(), rect.top() + 5.0), QPointF(rect.center().x(), rect.bottom() - 8.0))
            p.drawPoint(QPointF(rect.center().x(), rect.bottom() - 4.6))
            p.restore()
            p.restore()
            return
        p.setPen(QPen(color("#ffffff", 0.92), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        v = inner.height() * 0.72 * amount
        h = inner.width() * 0.72 * amount
        p.drawLine(QPointF(inner.center().x(), inner.center().y() - v / 2.0), QPointF(inner.center().x(), inner.center().y() + v / 2.0))
        p.drawLine(QPointF(inner.center().x() - h / 2.0, inner.center().y()), QPointF(inner.center().x() + h / 2.0, inner.center().y()))
        p.restore()

    def draw_right_hud_mode(
        self,
        p: QPainter,
        width: int,
        height: int,
        mode: str,
        target: VisionTarget,
        hud_scale: float = 1.0,
    ) -> None:
        hud = self.registry.get("HUD")
        if mode == "ModuleListHud" and self.setting_bool(hud, "Module List", True):
            if not self.queue_gpu_module_list(p, width, height, hud_scale):
                self.draw_module_list_hud(p, width, height)
        elif mode == "TacticalMapHud":
            if self.setting_bool(hud, "Module List", True):
                if not self.queue_gpu_module_list(p, width, height, hud_scale):
                    self.draw_module_list_hud(p, width, height)
        elif mode == "KeyBindsHud" and self.setting_bool(hud, "KeyBinds", True):
            self.draw_keybinds_hud(p, width)
        elif mode == "RobotListHud" and self.setting_bool(hud, "Robot List", True):
            self.draw_robot_list_hud(p, width)
        elif mode == "TargetHud" and self.setting_bool(hud, "Target HUD", True):
            self.draw_target_card(p, QRectF(width - 248, 86, 224, 82), target, "TargetHud")
        elif mode == "StatusCardsHud" and self.setting_bool(hud, "Status Cards", True):
            self.draw_status_cards_hud(p, width)
        elif mode == "RMIndicatorsHud" and self.setting_bool(hud, "RM Indicators", True):
            self.draw_rm_indicators_hud(p, width)
        right_list_active = mode in ("ModuleListHud", "TacticalMapHud") and self.setting_bool(hud, "Module List", True)
        if mode != "KeyBindsHud" and not right_list_active and self.setting_bool(hud, "KeyBinds", True):
            self.draw_keybinds_strip(p, width, height)

    def queue_gpu_module_list(self, p: QPainter, width: int, height: int, hud_scale: float) -> bool:
        """保留各预设自己的外观，并由静态 UI FBO 缓存最终绘制结果。"""
        # 统一 GPU 快速模板会破坏各套界面各自的行高、配色、标签和
        # 进入动画。原始绘制结果已经缓存到静态 UI FBO，不需要再用错误模板
        # 替换；返回 False 后由对应样式自己的 renderer 绘制。
        return False

    def draw_module_list_for_tactical_map(self, p: QPainter, width: int, height: int) -> None:
        map_rect = self.tactical_map_rect(width, height)
        below_start = map_rect.bottom() + 14
        if height - below_start >= 180:
            self.draw_module_list_hud(p, width, height, start_y=below_start)
            return
        left_space_right_edge = int(map_rect.left() - 12)
        if left_space_right_edge >= 420:
            self.draw_module_list_hud(p, left_space_right_edge, height)
            return
        self.draw_module_list_hud(p, width, height, start_y=below_start)

    def draw_match_header(self, p: QPainter, width: int) -> None:
        config = self.match_mode_manager.current
        text = f"{config.title}  {self.state.current_stage}  {self.format_time(self.state.stage_countdown_sec)}"
        if config.key == "RMUL3v3":
            text += f"  VP {self.state.ally_victory_points}:{self.state.enemy_victory_points}"
        else:
            text += f"  SCORE {self.state.red_score}:{self.state.blue_score}"
        font = self.font("poppins_medium", 8.6)
        p.setFont(font)
        rect_w = max(280.0, min(520.0, QFontMetricsF(font).horizontalAdvance(text) + 44.0))
        hud = self.registry.get("HUD")
        dynamic_enabled = self.setting_bool(hud, "Dynamic Island", True)
        y_offset = self.anim.value("hud.match_header.dynamic_offset", 12.0 if dynamic_enabled else 0.0, self.anim_duration(0.24), Easings.ease_out_expo)
        rect = QRectF(width / 2 - rect_w / 2, 58 + y_offset, rect_w, 24)
        active = self.anim.value("hud.match_header", 1.0, self.anim_duration(0.24), Easings.ease_out_expo, initial=0.0)
        p.save()
        p.setOpacity(active)
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, 12, surface="SubGlass")
        else:
            rounded_rect(p, rect.adjusted(-12, -12, 12, 12), 18, color("#000000", 0.035), None)
            rounded_rect(p, rect, 12, self.hud_surface(0.62), self.hud_panel_outline(0.08))
        progress = max(0.0, min(1.0, self.state.stage_countdown_sec / max(1.0, float(getattr(self.state, "match_duration_sec", 300)))))
        line = QRectF(rect.left() + 12, rect.bottom() - 3.0, rect.width() - 24, 1.2)
        draw_bar(p, line, progress, self.hud_accent(), color("#ffffff", 0.10), 0.6)
        self.draw_glass_text(p, rect.adjusted(14, 0, -14, 0), text, font, THEME.text, Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_tactical_map_hud(self, p: QPainter, width: int, height: int) -> None:
        module = self.registry.get("TacticalMap")
        if module is not None and not module.enabled:
            return
        config = self.match_mode_manager.current
        rect = self.tactical_map_rect(width, height)
        if self.liquid_map_enabled():
            self.draw_liquid_tactical_map_hud(p, width, height, module, config, rect)
            return
        chrome = self.tactical_map_chrome()
        hold_amount = self.tactical_map_hold_amount()
        minimal = chrome == "Minimal" and self.hud_density() == "CombatCompact" and hold_amount < 0.08
        thin = chrome == "Thin" or (chrome == "Minimal" and hold_amount >= 0.08)
        active = self.anim.value("hud.tactical_map", 1.0, self.anim_duration(0.18), Easings.ease_out_expo, initial=0.0)
        slide = (1.0 - active) * 20.0
        rect = rect.translated(slide, 0)
        p.save()
        p.setOpacity(active)
        scale = 0.985 + 0.015 * active
        p.translate(rect.center())
        p.scale(scale, scale)
        p.translate(-rect.center())
        if not minimal:
            glow_rect(p, rect, 11, 0.04 if self.hud_clean() else 0.08 if thin else 0.17)
        rounded_rect(p, rect, 6 if minimal else 8, self.hud_surface(0.50 if minimal else 0.64 if thin else 0.68), self.hud_panel_outline(0.06 if minimal else 0.09))
        top_line = QLinearGradient(rect.left() + 10, rect.top() + 4, rect.right() - 10, rect.top() + 4)
        top_line.setColorAt(0.0, with_alpha(self.hud_accent(), 0.54 if minimal else 0.78))
        top_line.setColorAt(1.0, with_alpha(self.hud_accent(), 0.76 if minimal else 0.96))
        line_reveal = self.anim.value("hud.tactical_map.line_reveal", 1.0, self.anim_duration(0.18), Easings.ease_out_expo, initial=0.0)
        p.fillRect(QRectF(rect.left() + 10, rect.top() + 4, (rect.width() - 20) * line_reveal, 1.4 if minimal else 2.0 if thin else 2.3), top_line)
        title = f"{config.title} Tactical Map"
        compact = minimal or rect.height() < 220.0
        status_kind = self.tactical_map_status_kind(minimal)
        header_h = 8.0 if minimal else 24.0 if thin else 30.0 if compact else 44.0
        footer_h = self.tactical_map_footer_height(status_kind, minimal, thin, compact)
        detail_alpha = self.anim.value("hud.tactical_map.detail_alpha", 0.0 if minimal else 1.0, self.anim_duration(0.14), Easings.ease_out_expo)
        p.save()
        p.setClipRect(rect.adjusted(1.0, 1.0, -1.0, -1.0))
        if not minimal:
            p.save()
            p.setOpacity(p.opacity() * detail_alpha)
            self.draw_text(p, QRectF(rect.left() + 12, rect.top() + 8, rect.width() - 24, 14), title, self.font("poppins_bold", 7.0 if compact else 8.4), THEME.text)
            p.restore()
        if not compact and not thin:
            p.save()
            p.setOpacity(p.opacity() * detail_alpha)
            self.draw_text(
                p,
                QRectF(rect.left() + 12, rect.top() + 27, rect.width() - 24, 14),
                f"{config.field.width_m:g}m x {config.field.height_m:g}m official field",
                self.font("poppins_regular", 7.2),
                THEME.muted,
            )
            p.restore()
        map_rect = rect.adjusted(6 if minimal else 8 if compact else 10, header_h, -6 if minimal else -8 if compact else -10, -footer_h)
        field_rect = self.draw_official_map(p, map_rect, config)
        map_content_opacity = self.anim.value("hud.tactical_map.content_alpha", 1.0, self.anim_duration(0.16), Easings.ease_out_expo, initial=0.0)
        p.save()
        p.setOpacity(p.opacity() * map_content_opacity)
        self.draw_map_zones(p, field_rect, config.field, compact=compact)
        if self.setting_bool(module, "Map Marks", True):
            self.draw_map_markers(p, field_rect, config.field, compact=compact)
        if self.setting_bool(module, "Robot Dots", True):
            self.draw_map_robots(p, field_rect, config.field, compact=compact)
        p.restore()
        if not compact:
            title_chip = QRectF(field_rect.left() + 6, field_rect.top() + 6, min(188.0, field_rect.width() - 12), 20)
            p.save()
            p.setOpacity(p.opacity() * detail_alpha)
            rounded_rect(p, title_chip, 6, self.hud_surface(0.72), self.hud_panel_outline(0.10))
            self.draw_text(p, title_chip.adjusted(7, 0, -7, 0), f"{config.title} official map", self.font("poppins_medium", 6.9), THEME.text)
            p.restore()
        p.restore()
        stack_top = field_rect.bottom() + (3 if minimal else 5 if compact else 8)
        if status_kind == "orbit":
            self.draw_map_status_orbit_dock(p, rect, field_rect, width, minimal=minimal, compact=compact)
        elif status_kind == "lines":
            self.draw_match_status_lines(p, QRectF(field_rect.left(), stack_top, field_rect.width(), max(8.0, rect.bottom() - 5.0 - stack_top)))
        elif status_kind == "rings":
            ring_h = max(30.0 if compact else 42.0, min(56.0, rect.bottom() - 7.0 - stack_top))
            self.draw_match_status_rings(p, QRectF(field_rect.left(), stack_top, field_rect.width(), ring_h), compact=compact)
        elif status_kind == "bars":
            stack_h = max(20.0 if thin else 32.0 if compact else 42.0, min(58.0, rect.bottom() - 8.0 - stack_top))
            self.draw_match_status_stack(p, QRectF(field_rect.left(), stack_top, field_rect.width(), stack_h), compact=compact)
        p.restore()

    def tactical_map_rect(self, width: int, height: int) -> QRectF:
        module = self.registry.get("TacticalMap")
        setting = module.get_setting("Map Size") if module else None
        mode = str(setting.value) if setting else "Wide"
        density = self.hud_density()
        # CombatCompact 始终以缩略尺寸作为 morph 起点。不能在按键按下时
        # 先切换 base size，否则会在连续动画开始前产生一次明显跳变。
        if density == "CombatCompact":
            base_w, base_h = 170.0, 118.0
        elif mode == "Compact":
            base_w, base_h = 220.0, 170.0
        elif mode == "Full Tactical":
            base_w, base_h = 360.0, 270.0
        else:
            base_w, base_h = 280.0, 212.0
        expanded_w = min(520.0, width * 0.48)
        expanded_h = min(380.0, height * 0.56)
        target_w = expanded_w if self.tactical_map_hold else base_w
        target_h = expanded_h if self.tactical_map_hold else base_h
        target_w = min(target_w, max(190.0, width - 36.0))
        target_h = min(target_h, max(150.0, height - 96.0))
        self.tactical_map_state.set_target(12.0, 58.0, target_w, target_h, self.tactical_map_hold)
        state = self.tactical_map_state.container
        return QRectF(state.x, state.y, state.width, state.height)

    def tactical_map_morph_progress(self) -> float:
        """Tab 展开、底图、标题和状态区共享的唯一可逆进度。"""
        return self.tactical_map_state.progress

    def tactical_map_hold_amount(self) -> float:
        return self.tactical_map_morph_progress()

    def tactical_map_chrome(self) -> str:
        module = self.registry.get("TacticalMap")
        setting = module.get_setting("Chrome") if module else None
        value = str(setting.value) if setting else "Minimal"
        if self.hud_density() == "DebugFull":
            return "Full"
        return value if value in ("Minimal", "Thin", "Full") else "Minimal"

    def tactical_map_status_display(self) -> str:
        module = self.registry.get("TacticalMap")
        setting = module.get_setting("Status Display") if module else None
        value = str(setting.value) if setting else "LiquidAuto"
        value = {
            "Auto": "LiquidAuto",
            "Rings": "LegacyOrbit",
            "Bars": "LegacyBars",
        }.get(value, value)
        valid = (
            "LiquidAuto", "LiquidBars", "LiquidCards",
            "LegacyOrbit", "LegacyBars", "Off",
        )
        return value if value in valid else "LiquidAuto"

    def tactical_map_status_kind(self, minimal: bool) -> str:
        value = self.tactical_map_status_display()
        if value == "Off":
            return "off"
        if value == "LegacyBars":
            return "bars"
        if value == "LegacyOrbit":
            return "orbit"
        return "orbit"

    def tactical_map_footer_height(self, status_kind: str, minimal: bool, thin: bool, compact: bool) -> float:
        if status_kind == "off":
            return 4.0 if minimal else 8.0
        if status_kind == "orbit":
            return 48.0 if minimal else 62.0 if compact else 66.0
        if status_kind == "lines":
            return 14.0 if minimal else 18.0
        if status_kind == "rings":
            return 38.0 if minimal else 46.0 if compact else 50.0 if thin else 56.0
        return 14.0 if minimal else 24.0 if thin else 38.0 if compact else 76.0

    def liquid_status_footer_height(self, display: str, minimal: bool, compact: bool) -> float:
        if display == "Off":
            return 5.0 if minimal else 9.0
        if display == "LegacyOrbit":
            return 48.0 if minimal else 62.0 if compact else 66.0
        if display == "LegacyBars":
            return 18.0 if minimal else 28.0 if compact else 44.0
        if display == "LiquidCards":
            return 38.0 if minimal else 54.0 if compact else 60.0
        return 32.0 if minimal else 44.0 if compact else 48.0

    def draw_liquid_tactical_map_hud(
        self,
        p: QPainter,
        width: int,
        height: int,
        module: Module | None,
        config: MatchModeConfig,
        rect: QRectF,
    ) -> None:
        hold_amount = self.tactical_map_hold_amount()
        compact_density = self.hud_density() == "CombatCompact"
        compact = compact_density
        display = self.tactical_map_status_display()
        active = self.anim.value("hud.tactical_map.liquid", 1.0, self.anim_duration(0.17), Easings.ease_out_expo, initial=0.0)
        slide = (1.0 - active) * 16.0
        rect = rect.translated(slide, 0)
        p.save()
        p.setOpacity(p.opacity() * active)
        scale = 0.992 + 0.008 * active
        p.translate(rect.center())
        p.scale(scale, scale)
        p.translate(-rect.center())

        radius = 5.0
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, radius, surface="MainGlass")
        else:
            rounded_rect(p, rect, radius, color("#000000", 0.72), color("#ffffff", 0.105 if compact_density else 0.085), 0.9)
        left_line = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        left_line.setColorAt(0.0, with_alpha(self.hud_accent(), 0.70))
        left_line.setColorAt(1.0, with_alpha(self.hud_accent(), 0.28))
        p.fillRect(QRectF(rect.left(), rect.top() + 6.0, 2.0, rect.height() - 12.0), left_line)

        title = f"{config.title} Tactical Map"
        collapsed_header = 13.0 if compact_density else (22.0 if compact else 27.0)
        header_h = collapsed_header + (27.0 - collapsed_header) * hold_amount
        collapsed_footer = self.liquid_status_footer_height(display, compact_density, True)
        expanded_footer = self.liquid_status_footer_height(display, False, False)
        footer_h = collapsed_footer + (expanded_footer - collapsed_footer) * hold_amount
        collapsed_title_size = 6.0 if compact_density else 7.2
        title_font = self.font("poppins_medium", collapsed_title_size + (8.0 - collapsed_title_size) * hold_amount)
        title_rect = QRectF(rect.left() + 8.0, rect.top() + 2.0, rect.width() - 16.0, header_h - 2.0)
        self.draw_glass_text(p, title_rect, title, title_font, THEME.text)

        map_rect = rect.adjusted(6.0, header_h, -6.0, -footer_h)
        p.save()
        p.setClipRect(rect.adjusted(1.0, 1.0, -1.0, -1.0))
        field_rect = self.draw_official_map(p, map_rect, config)
        content_alpha = self.anim.value("hud.tactical_map.liquid.content", 1.0, self.anim_duration(0.20), Easings.ease_out_cubic, initial=0.0)
        p.save()
        p.setOpacity(p.opacity() * content_alpha)
        self.draw_map_zones(p, field_rect, config.field, compact=compact, detail_progress=hold_amount)
        if self.setting_bool(module, "Map Marks", True):
            self.draw_map_markers(p, field_rect, config.field, compact=compact, detail_progress=hold_amount)
        if self.setting_bool(module, "Robot Dots", True):
            self.draw_liquid_map_robots(p, field_rect, config.field, compact=compact, detail_progress=hold_amount)
        p.restore()
        p.restore()

        if display == "LegacyOrbit":
            self.draw_map_status_orbit_dock(p, rect, field_rect, width, minimal=compact_density, compact=compact)
        elif display == "LegacyBars":
            stack_top = field_rect.bottom() + 3.0 + 3.0 * hold_amount
            stack_h = max(20.0 if compact else 34.0, min(54.0, rect.bottom() - 6.0 - stack_top))
            self.draw_match_status_stack(p, QRectF(field_rect.left(), stack_top, field_rect.width(), stack_h), compact=compact)
        elif display != "Off":
            self.draw_liquid_status_dock(
                p,
                rect,
                field_rect,
                width,
                display,
                minimal=compact_density,
                compact=compact,
                morph_progress=hold_amount,
            )
        p.restore()

    def official_map_fit_rect(self, rect: QRectF, config: MatchModeConfig) -> QRectF:
        image = self.official_map_image(config)
        if image is None or image.isNull():
            aspect = config.field.width_m / max(0.1, config.field.height_m)
        else:
            aspect = image.width() / max(1.0, image.height())
        return self.fit_aspect(rect, aspect)

    def draw_liquid_map_robots(
        self,
        p: QPainter,
        rect: QRectF,
        field: FieldLayout,
        compact: bool = False,
        detail_progress: float | None = None,
    ) -> None:
        robots = list(self.state.map_robots)
        if not robots:
            return
        own = next((robot for robot in robots if int(robot.get("id", -1)) == int(self.state.robot_id)), None)
        own_x = float(own.get("x", field.width_m * 0.5)) if own else field.width_m * 0.5
        own_y = float(own.get("y", field.height_m * 0.5)) if own else field.height_m * 0.5
        own_point = self.map_point(rect, field, own_x, own_y)
        style = self.liquid_map_setting("Pointer Style", "Triangle")
        show_labels = self.liquid_map_bool("Show Labels", True)
        show_values = self.liquid_map_bool("Show Values", True)
        color_mode = self.liquid_map_setting("Entity Color", "Team")
        max_distance = max(1.0, math.hypot(field.width_m, field.height_m))
        now = time.perf_counter()
        detail = (0.0 if compact else 1.0) if detail_progress is None else max(0.0, min(1.0, detail_progress))
        font = self.font("poppins_medium", 5.8 + 0.9 * detail)

        for index, robot in enumerate(robots):
            x_m = float(robot.get("x", 0.0))
            y_m = float(robot.get("y", 0.0))
            point = self.map_point(rect, field, x_m, y_m)
            team = str(robot.get("team", "ally"))
            hp = int(robot.get("hp", 0))
            hp_max = max(1, int(robot.get("max", 1)))
            hp_ratio = max(0.0, min(1.0, hp / hp_max))
            distance = math.hypot(x_m - own_x, y_m - own_y)
            distance_ratio = max(0.0, min(1.0, distance / max_distance))
            alpha = 0.42 + (1.0 - distance_ratio) * 0.50
            base = self.liquid_entity_color(team, hp_ratio, distance_ratio, color_mode)
            highlight = bool(robot.get("highlight", False))
            if highlight and self.setting_bool(self.registry.get("TacticalMap"), "Radar Pulse", True):
                pulse_r = (7.0 + 2.0 * detail) + (3.0 + 1.6 * detail) * (0.5 + 0.5 * math.sin(now * 4.4 + index))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(with_alpha(base, 0.28 + 0.16 * math.sin(now * 3.2)), 1.0))
                p.drawEllipse(point, pulse_r, pulse_r)
            angle = math.degrees(math.atan2(point.y() - own_point.y(), point.x() - own_point.x())) + 90.0
            size = 5.0 + 1.6 * detail
            self.draw_liquid_radar_pointer(p, point, angle, with_alpha(base, alpha), style, size, highlight)
            if show_labels and (detail > 0.001 or highlight):
                label = str(robot.get("id", "?"))
                show_distance = show_values and (detail > 0.35 or team == "enemy" or distance >= 1.0)
                value = f"{int(distance)}m" if show_distance else ""
                text = f"{label} {value}".strip()
                label_rect = QRectF(point.x() + 6.0, point.y() - 8.0, 44.0, 12.0)
                p.save()
                p.setOpacity(p.opacity() * max(detail, 0.72 if highlight else 0.0))
                self.draw_text(p, label_rect.translated(0.5, 0.7), text, font, color("#000000", 0.72))
                self.draw_text(p, label_rect, text, font, THEME.text)
                p.restore()
            if show_values:
                bar_w = 15.0 + 6.0 * detail
                draw_bar(
                    p,
                    QRectF(point.x() - bar_w * 0.5, point.y() + 5.0 + 2.0 * detail, bar_w, 2.0),
                    hp_ratio,
                    with_alpha(base, 0.82),
                    color("#ffffff", 0.12),
                    1.0,
                )
            tooltip = f"{robot.get('name', 'Robot')} {robot.get('id', '?')} | {hp}/{hp_max} HP | {distance:.1f}m"
            self.add_hotspot(QRectF(point.x() - 11.0, point.y() - 11.0, 22.0, 22.0), "map_robot", robot.get("id"), tooltip=tooltip)

    def draw_liquid_mini_status_overlay(self, p: QPainter, field_rect: QRectF, display: str) -> None:
        match_rows, telemetry_rows = self.map_status_groups()
        match_rows = match_rows[:3]
        telemetry_rows = telemetry_rows[:2]
        if not match_rows and not telemetry_rows:
            return
        bottom_h = 16.0
        bottom_gap = 4.0
        if match_rows:
            total_gap = bottom_gap * max(0, len(match_rows) - 1)
            slot_w = (field_rect.width() - 10.0 - total_gap) / len(match_rows)
            y = field_rect.bottom() - bottom_h - 4.0
            for index, row in enumerate(match_rows):
                x = field_rect.left() + 5.0 + index * (slot_w + bottom_gap)
                self.draw_liquid_mini_status_chip(p, QRectF(x, y, slot_w, bottom_h), row, f"mini.match.{index}", display)
        if telemetry_rows:
            side_w = min(54.0, max(38.0, field_rect.width() * 0.30))
            y = field_rect.top() + 5.0
            for index, row in enumerate(telemetry_rows):
                rect = QRectF(field_rect.right() - side_w - 5.0, y + index * (bottom_h + 4.0), side_w, bottom_h)
                self.draw_liquid_mini_status_chip(p, rect, row, f"mini.telemetry.{index}", display)

    def draw_liquid_mini_status_chip(
        self,
        p: QPainter,
        rect: QRectF,
        row: tuple[str, str, float, QColor, str, str],
        key_prefix: str,
        display: str,
    ) -> None:
        label, value, ratio, c, key, tooltip = row
        ratio = max(0.0, min(1.0, ratio))
        main = self.liquid_status_color(label, ratio, c)
        fast_ratio, _lag_ratio = self.animated_status_ratio(f"{key_prefix}.{key}", ratio)
        hovered = rect.contains(self.hover_point)
        hover = self.anim.value(f"liquid.status.mini.hover.{key_prefix}.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.12), Easings.ease_out_cubic)
        rounded_rect(p, rect, 5.0, color("#081421", 0.46 + 0.08 * hover), color("#eef5ff", 0.16 + 0.08 * hover), 0.8)
        p.fillRect(QRectF(rect.left() + 1.0, rect.top() + 3.0, 1.5, rect.height() - 6.0), with_alpha(main, 0.74))
        fill = QRectF(rect.left() + 2.0, rect.bottom() - 3.0, max(3.0, (rect.width() - 4.0) * fast_ratio), 2.2)
        rounded_rect(p, fill, 1.1, with_alpha(main, 0.82))
        font = self.font("poppins_medium", 5.7 if display != "LiquidCards" else 5.4)
        text = self.compact_map_status_label(label)
        if self.liquid_map_bool("Show Values", True):
            text = f"{text} {value}"
        self.draw_text(p, rect.adjusted(3.0, 0.0, -3.0, -1.0), text, font, THEME.text, Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(rect.adjusted(-2.0, -2.0, 2.0, 2.0), "map_status", key, tooltip=tooltip)

    def liquid_entity_color(self, team: str, hp_ratio: float, distance_ratio: float, color_mode: str) -> QColor:
        if color_mode == "Health":
            if hp_ratio < 0.30:
                return self.hud_danger()
            if hp_ratio < 0.58:
                return self.hud_warning()
            return self.hud_accent() if team == "enemy" else self.hud_success()
        if color_mode == "Distance":
            if distance_ratio < 0.22:
                return self.hud_danger()
            if distance_ratio < 0.48:
                return self.hud_warning()
            return self.hud_accent()
        if self.setting_mode(self.registry.get("TacticalMap"), "Palette", "RM Tactical") == "RM Tactical":
            return self.map_team_color(team)
        return self.hud_danger() if team == "enemy" else self.hud_accent()

    def map_team_color(self, relation: str) -> QColor:
        side = self.alliance_side()
        if relation.lower() in ("enemy", "foe"):
            side = "Blue" if side == "Red" else "Red"
        elif relation.lower() in ("red", "blue"):
            side = relation.title()
        # macOS 风格的低饱和阵营色：仍然保持红/蓝语义，但不再用高亮纯色铺满状态条。
        return color("#ff7882") if side == "Red" else color("#78a7ff")

    def map_control_color(self) -> QColor:
        owner = str(self.state.control_owner).upper()
        if owner == "ALLY":
            return self.map_team_color("ally")
        if owner == "ENEMY":
            return self.map_team_color("enemy")
        if owner == "RED":
            return self.map_team_color("red")
        if owner == "BLUE":
            return self.map_team_color("blue")
        return color("#9aa8ba")

    def draw_liquid_radar_pointer(
        self,
        p: QPainter,
        center: QPointF,
        angle_deg: float,
        c: QColor,
        style: str,
        size: float,
        highlight: bool,
    ) -> None:
        p.save()
        p.translate(center)
        p.rotate(angle_deg)
        p.setPen(QPen(color("#ffffff", 0.64 if highlight else 0.36), 0.8))
        p.setBrush(c)
        if style == "Dot":
            p.drawEllipse(QPointF(0.0, 0.0), size * 0.58, size * 0.58)
        elif style == "Wedge":
            polygon = QPolygonF([
                QPointF(0.0, -size),
                QPointF(-size * 0.70, size * 0.38),
                QPointF(0.0, size * 0.10),
                QPointF(size * 0.70, size * 0.38),
            ])
            p.drawPolygon(polygon)
        else:
            polygon = QPolygonF([
                QPointF(0.0, -size),
                QPointF(-size * 0.62, size * 0.62),
                QPointF(size * 0.62, size * 0.62),
            ])
            p.drawPolygon(polygon)
        p.restore()

    def draw_liquid_status_dock(
        self,
        p: QPainter,
        rect: QRectF,
        field_rect: QRectF,
        width: int,
        display: str,
        minimal: bool,
        compact: bool,
        morph_progress: float = 0.0,
    ) -> None:
        match_rows, telemetry_rows = self.map_status_groups()
        morph_progress = max(0.0, min(1.0, morph_progress))
        bottom_rows = match_rows[:4]
        side_rows = telemetry_rows[:4]
        if not bottom_rows and not side_rows:
            return
        liquid_surface = self.hud_clean()
        if display == "LiquidCards":
            card_blend = 1.0
        elif display == "LiquidBars":
            card_blend = 0.0
        else:
            blend_t = max(0.0, min(1.0, (morph_progress - 0.18) / 0.64))
            card_blend = blend_t * blend_t * (3.0 - 2.0 * blend_t)
        bottom_top = field_rect.bottom() + 3.0 + 2.0 * morph_progress
        bottom_rect = QRectF(rect.left() + 7.0, bottom_top, rect.width() - 14.0, max(22.0, rect.bottom() - bottom_top - 5.0))
        if bottom_rows:
            if liquid_surface:
                self.draw_hud_liquid_glass(p, bottom_rect, 5.0, surface="MainGlass")
            else:
                rounded_rect(p, bottom_rect, 5.0, color("#000000", 0.34 if minimal else 0.28), color("#ffffff", 0.055 if minimal else 0.035), 0.6)
            self.draw_liquid_status_row(
                p,
                bottom_rect,
                bottom_rows,
                card_blend=card_blend,
                vertical=False,
                minimal=minimal,
                dock_key="match",
                liquid_glass=liquid_surface,
                morph_progress=morph_progress,
                collapsed_count=3 if minimal else len(bottom_rows),
            )

        if not side_rows:
            return
        collapsed_row_h = 18.0 if minimal else 24.0
        expanded_row_h = 24.0 if compact else 26.0
        row_h = collapsed_row_h + (expanded_row_h - collapsed_row_h) * morph_progress
        side_gap = 4.0 + morph_progress
        collapsed_side_w = 74.0 if minimal else 104.0
        side_w = collapsed_side_w + (118.0 - collapsed_side_w) * morph_progress
        side_h = len(side_rows) * row_h + max(0, len(side_rows) - 1) * side_gap
        side_x = rect.right() + 6.0 + 3.0 * morph_progress
        side_y = min(rect.bottom() - side_h, max(rect.top() + 14.0, field_rect.top()))
        safe_right = width - 218.0
        if side_x + side_w <= safe_right:
            side_rect = QRectF(side_x, side_y, side_w, side_h)
            shell = side_rect.adjusted(-4.0, -4.0, 4.0, 4.0)
            if liquid_surface:
                self.draw_hud_liquid_glass(p, shell, 6.0, surface="MainGlass")
            else:
                rounded_rect(p, shell, 6.0, color("#000000", 0.30), color("#ffffff", 0.040), 0.6)
            self.draw_liquid_status_row(
                p,
                side_rect,
                side_rows,
                card_blend=card_blend,
                vertical=True,
                minimal=minimal,
                dock_key="telemetry",
                liquid_glass=liquid_surface,
                morph_progress=morph_progress,
                collapsed_count=2 if minimal else len(side_rows),
            )
            return
        fold_rect = QRectF(rect.left() + 7.0, rect.bottom() + 5.0, min(rect.width() - 14.0, 250.0), row_h + 2.0)
        if liquid_surface:
            self.draw_hud_liquid_glass(p, fold_rect, 5.0, surface="MainGlass")
        else:
            rounded_rect(p, fold_rect, 5.0, color("#000000", 0.30), color("#ffffff", 0.040), 0.6)
        self.draw_liquid_status_row(
            p,
            fold_rect,
            side_rows,
            card_blend=card_blend,
            vertical=False,
            minimal=minimal,
            dock_key="telemetry_fold",
            liquid_glass=liquid_surface,
            morph_progress=morph_progress,
            collapsed_count=2 if minimal else len(side_rows),
        )

    def draw_liquid_status_row(
        self,
        p: QPainter,
        rect: QRectF,
        rows: list[tuple[str, str, float, QColor, str, str]],
        *,
        card_blend: float,
        vertical: bool,
        minimal: bool,
        dock_key: str,
        liquid_glass: bool = False,
        morph_progress: float = 1.0,
        collapsed_count: int | None = None,
    ) -> None:
        if not rows:
            return
        gap = 4.0 if minimal else 5.0
        enter = self.anim.value(f"liquid.status.dock.{dock_key}", 1.0, self.anim_duration(0.20), Easings.ease_out_cubic, initial=0.0)
        p.save()
        p.setOpacity(p.opacity() * enter)
        count = len(rows)
        collapsed_count = max(1, min(count, collapsed_count or count))
        morph_progress = max(0.0, min(1.0, morph_progress))
        extra_t = max(0.0, min(1.0, (morph_progress - 0.10) / 0.62))
        extra_reveal = extra_t * extra_t * (3.0 - 2.0 * extra_t)
        if vertical:
            collapsed_h = (rect.height() - gap * (collapsed_count - 1)) / collapsed_count
            expanded_h = (rect.height() - gap * (count - 1)) / count
            for index, row in enumerate(rows):
                collapsed_y = rect.top() + min(index, collapsed_count - 1) * (collapsed_h + gap)
                expanded_y = rect.top() + index * (expanded_h + gap)
                y = collapsed_y + (expanded_y - collapsed_y) * morph_progress
                h = collapsed_h + (expanded_h - collapsed_h) * morph_progress
                slot = QRectF(rect.left(), y, rect.width(), h)
                item_alpha = 1.0 if index < collapsed_count else extra_reveal
                self.draw_liquid_status_item(p, slot, row, card_blend=card_blend, vertical=True, minimal=minimal, dock_key=dock_key, index=index, liquid_glass=liquid_glass, item_alpha=item_alpha)
        else:
            collapsed_w = (rect.width() - gap * (collapsed_count - 1)) / collapsed_count
            expanded_w = (rect.width() - gap * (count - 1)) / count
            for index, row in enumerate(rows):
                collapsed_x = rect.left() + min(index, collapsed_count - 1) * (collapsed_w + gap)
                expanded_x = rect.left() + index * (expanded_w + gap)
                x = collapsed_x + (expanded_x - collapsed_x) * morph_progress
                w = collapsed_w + (expanded_w - collapsed_w) * morph_progress
                slot = QRectF(x, rect.top(), w, rect.height())
                item_alpha = 1.0 if index < collapsed_count else extra_reveal
                self.draw_liquid_status_item(p, slot, row, card_blend=card_blend, vertical=False, minimal=minimal, dock_key=dock_key, index=index, liquid_glass=liquid_glass, item_alpha=item_alpha)
        p.restore()

    def draw_liquid_status_item(
        self,
        p: QPainter,
        rect: QRectF,
        row: tuple[str, str, float, QColor, str, str],
        *,
        card_blend: float,
        vertical: bool,
        minimal: bool,
        dock_key: str,
        index: int,
        liquid_glass: bool = False,
        item_alpha: float = 1.0,
    ) -> None:
        label, value, ratio, c, key, tooltip = row
        animation = self.liquid_map_setting("Dock Animation", "Fly")
        enter = self.anim.value(
            f"liquid.status.item.{dock_key}.{key}",
            1.0,
            self.anim_duration(0.18 + index * 0.025),
            Easings.ease_out_cubic,
            initial=0.0,
        )
        item_rect = QRectF(rect)
        p.save()
        p.setOpacity(p.opacity() * enter * max(0.0, min(1.0, item_alpha)))
        if animation == "Fly":
            item_rect = item_rect.translated((1.0 - enter) * (14.0 if vertical else 0.0), (1.0 - enter) * (8.0 if not vertical else 0.0))
        elif animation == "Flip":
            p.translate(item_rect.center())
            p.scale(0.92 + 0.08 * enter, 0.96 + 0.04 * enter)
            p.translate(-item_rect.center())
        card_blend = max(0.0, min(1.0, card_blend))
        if card_blend < 0.999:
            p.save()
            p.setOpacity(p.opacity() * (1.0 - card_blend))
            self.draw_liquid_status_bar(p, item_rect, label, value, ratio, c, key, tooltip, minimal=minimal, liquid_glass=liquid_glass)
            p.restore()
        if card_blend > 0.001:
            p.save()
            p.setOpacity(p.opacity() * card_blend)
            self.draw_liquid_status_card(p, item_rect, label, value, ratio, c, key, tooltip, minimal=minimal, liquid_glass=liquid_glass)
            p.restore()
        p.restore()

    def liquid_status_color(self, label: str, ratio: float, fallback: QColor) -> QColor:
        label = label.upper()
        ratio = max(0.0, min(1.0, ratio))
        if label in ("RED", "RED YOU"):
            return self.map_team_color("red")
        if label in ("BLUE", "BLUE YOU"):
            return self.map_team_color("blue")
        if label in ("ENEMY", "ENMY", "EBASE", "OUT", "OUTPOST"):
            return self.hud_danger()
        if label == "CTRL":
            return self.map_control_color()
        if label == "GOLD":
            return color("#e6bd68") if self.hud_clean() else self.hud_warning()
        if label in ("AMMO",):
            return self.hud_success()
        if label in ("HEAT", "POWER", "PWR"):
            if ratio >= 0.92:
                return self.hud_danger()
            if ratio >= 0.78:
                return self.hud_warning()
            return self.hud_accent()
        if label in ("SPEED", "SPD", "CAP"):
            return color("#79b7ff") if self.hud_clean() else fallback
        return self.hud_accent() if self.hud_clean() else fallback

    def draw_liquid_status_bar(
        self,
        p: QPainter,
        rect: QRectF,
        label: str,
        value: str,
        ratio: float,
        c: QColor,
        key: str,
        tooltip: str,
        *,
        minimal: bool,
        liquid_glass: bool = False,
    ) -> None:
        fast_ratio, lag_ratio = self.animated_status_ratio(f"liquid.{key}", ratio)
        main = self.liquid_status_color(label, ratio, c)
        hovered = rect.contains(self.hover_point)
        hover = self.anim.value(f"liquid.status.hover.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.14), Easings.ease_out_cubic)
        h = min(rect.height(), 18.0 if minimal else 22.0)
        bar_rect = QRectF(rect.left(), rect.center().y() - h / 2.0, rect.width(), h)
        if liquid_glass:
            self.draw_hud_liquid_glass(p, bar_rect, 5.0, surface="SubGlass", hover=hover)
        else:
            rounded_rect(p, bar_rect, 5.0, color("#0a1420", 0.42 + 0.08 * hover), color("#eef5ff", 0.12 + 0.08 * hover), 0.8)
        progress_bg = QRectF(bar_rect.left() + 5.0, bar_rect.bottom() - 3.0, bar_rect.width() - 10.0, 2.0)
        rounded_rect(p, progress_bg, 1.0, color("#eef5ff", 0.12))
        lag_rect = QRectF(progress_bg.left(), progress_bg.top(), max(2.0, progress_bg.width() * lag_ratio), progress_bg.height())
        rounded_rect(p, lag_rect, 1.0, with_alpha(main, 0.18 + 0.06 * hover))
        fill_rect = QRectF(progress_bg.left(), progress_bg.top(), max(2.0, progress_bg.width() * fast_ratio), progress_bg.height())
        rounded_rect(p, fill_rect, 1.0, with_alpha(main, 0.82 + 0.08 * hover))
        label_font = self.font("poppins_medium", 5.4 if minimal else 6.4)
        value_font = self.font("poppins_medium", 5.5 if minimal else 6.5)
        short_label = self.compact_map_status_label(label) if minimal else label
        text_left = bar_rect.adjusted(5.0, 0.0, -5.0, 0.0)
        self.draw_text(p, text_left.translated(0.5, 0.7), short_label, label_font, color("#000000", 0.72))
        self.draw_text(p, text_left, short_label, label_font, THEME.text)
        if self.liquid_map_bool("Show Values", True):
            self.draw_text(p, text_left.translated(0.5, 0.7), value, value_font, color("#000000", 0.72), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.draw_text(p, text_left, value, value_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.add_hotspot(bar_rect.adjusted(-3.0, -3.0, 3.0, 3.0), "map_status", key, tooltip=tooltip)

    def draw_liquid_status_card(
        self,
        p: QPainter,
        rect: QRectF,
        label: str,
        value: str,
        ratio: float,
        c: QColor,
        key: str,
        tooltip: str,
        *,
        minimal: bool,
        liquid_glass: bool = False,
    ) -> None:
        fast_ratio, lag_ratio = self.animated_status_ratio(f"liquid.card.{key}", ratio)
        main = self.liquid_status_color(label, ratio, c)
        hovered = rect.contains(self.hover_point)
        hover = self.anim.value(f"liquid.status.card.hover.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.14), Easings.ease_out_cubic)
        card_rect = rect.adjusted(0.0, 1.0, 0.0, -1.0)
        if liquid_glass:
            self.draw_hud_liquid_glass(p, card_rect, 5.0, surface="SubGlass", hover=hover)
        else:
            rounded_rect(p, card_rect, 5.0, color("#0a1420", 0.42 + 0.08 * hover), color("#eef5ff", 0.12 + 0.08 * hover), 0.8)
        p.fillRect(QRectF(card_rect.left(), card_rect.top() + 4.0, 2.0, card_rect.height() - 8.0), with_alpha(main, 0.82))
        label_font = self.font("poppins_medium", 5.2 if minimal else 6.1)
        value_font = self.font("poppins_bold", 5.5 if minimal else 6.7)
        label_text = self.compact_map_status_label(label) if minimal else label
        self.draw_text(p, card_rect.adjusted(6.0, 1.0, -5.0, -10.0), label_text, label_font, THEME.muted)
        if self.liquid_map_bool("Show Values", True):
            self.draw_text(p, card_rect.adjusted(6.0, 1.0, -5.0, -10.0), value, value_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar = QRectF(card_rect.left() + 6.0, card_rect.bottom() - 5.0, card_rect.width() - 12.0, 2.0)
        draw_bar(p, bar, lag_ratio, with_alpha(main, 0.18), color("#ffffff", 0.10), 1.0)
        draw_bar(p, bar, fast_ratio, with_alpha(main, 0.78), color("#ffffff", 0.00), 1.0)
        self.add_hotspot(card_rect.adjusted(-3.0, -3.0, 3.0, 3.0), "map_status", key, tooltip=tooltip)

    def draw_official_map(self, p: QPainter, rect: QRectF, config: MatchModeConfig) -> QRectF:
        image = self.official_map_image(config)
        opacity_setting = self.registry.get("TacticalMap").get_setting("Opacity") if self.registry.get("TacticalMap") else None
        image_opacity = float(opacity_setting.value) if opacity_setting else 0.72
        rounded_rect(p, rect, 6, color("#050506", 0.72), color("#ffffff", 0.08))
        if image is None or image.isNull():
            self.draw_text(p, rect, "official map asset missing", self.font("poppins_regular", 8.0), self.hud_danger(), Qt.AlignmentFlag.AlignCenter)
            fit = self.fit_aspect(rect, config.field.width_m / max(0.1, config.field.height_m))
        else:
            fit = self.fit_aspect(rect, image.width() / max(1.0, image.height()))
            p.save()
            p.setOpacity(max(0.35, min(1.0, image_opacity)))
            # Source maps are high resolution scans. Resample only when the map
            # panel itself changes size (for example while Tab expands it), not
            # for every camera/HUD repaint.
            # 地图形变期间直接让 Qt/OpenGL 缩放源纹理，避免每个动画尺寸都在 CPU
            # 生成一张新位图并清空缓存。
            p.drawImage(fit, image)
            p.restore()
            p.fillRect(fit, color("#07111d", 0.16 if self.hud_clean() else 0.28))
        rounded_rect(p, fit, 4, color("#000000", 0.0), with_alpha(self.hud_accent(), 0.30 if self.hud_clean() else 0.22), 1.0)
        return fit

    def official_map_image(self, config: MatchModeConfig) -> QImage | None:
        path = self.workspace / "rm_custom_client" / config.field.asset_path
        key = str(path)
        if key not in self.map_images:
            self.map_images[key] = QImage(key)
        image = self.map_images[key]
        return None if image.isNull() else image

    def official_map_display_image(self, config: MatchModeConfig, source: QImage, fit: QRectF) -> QImage:
        width = max(1, int(round(fit.width())))
        height = max(1, int(round(fit.height())))
        source_key = str(self.workspace / "rm_custom_client" / config.field.asset_path)
        key = (source_key, width, height)
        cached = self.map_display_cache.get(key)
        if cached is not None and not cached.isNull():
            return cached
        cached = source.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if len(self.map_display_cache) >= 24:
            # Exact-size map entries are a bounded LRU-like cache; clearing this
            # tiny cache on a resize is cheaper than holding every animation size.
            self.map_display_cache.clear()
        self.map_display_cache[key] = cached
        return cached

    def fit_aspect(self, rect: QRectF, aspect: float) -> QRectF:
        if rect.width() / max(1.0, rect.height()) > aspect:
            h = rect.height()
            w = h * aspect
        else:
            w = rect.width()
            h = w / max(0.1, aspect)
        return QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)

    def map_point(self, rect: QRectF, field: FieldLayout, x_m: float, y_m: float) -> QPointF:
        nx = max(0.0, min(1.0, x_m / max(0.1, field.width_m)))
        ny = max(0.0, min(1.0, y_m / max(0.1, field.height_m)))
        tactical = self.registry.get("TacticalMap")
        profile = self.registry.get("AllianceProfile")
        mirror = (
            field.mirror_for_blue
            and self.alliance_side() == "Blue"
            and self.setting_bool(tactical, "Mirror Blue", True)
            and self.setting_bool(profile, "Mirror Tactical Map", True)
        )
        if mirror:
            nx = 1.0 - nx
            ny = 1.0 - ny
        return QPointF(rect.left() + rect.width() * nx, rect.bottom() - rect.height() * ny)

    def draw_map_zones(
        self,
        p: QPainter,
        rect: QRectF,
        field: FieldLayout,
        compact: bool = False,
        detail_progress: float | None = None,
    ) -> None:
        now = time.perf_counter()
        detail = (0.0 if compact else 1.0) if detail_progress is None else max(0.0, min(1.0, detail_progress))
        zone_colors = {
            "base": color("#ffffff", 0.13),
            "outpost": with_alpha(self.map_team_color("enemy"), 0.16),
            "rune": with_alpha(self.hud_accent(), 0.16),
            "supply": with_alpha(self.hud_success(), 0.13),
            "control": with_alpha(self.map_control_color(), 0.18),
            "highland": color("#ffffff", 0.10),
        }
        for index, zone in enumerate(field.zones):
            p1 = self.map_point(rect, field, zone.x, zone.y)
            p2 = self.map_point(rect, field, zone.x + zone.w, zone.y + zone.h)
            zone_rect = QRectF(min(p1.x(), p2.x()), min(p1.y(), p2.y()), abs(p2.x() - p1.x()), abs(p2.y() - p1.y()))
            pulse = 0.5 + 0.5 * math.sin(now * 2.0 + index)
            fill = zone_colors.get(zone.kind, color("#ffffff", 0.10))
            border_alpha = 0.06 + 0.04 * detail
            fill_alpha = 0.40 + (0.20 + 0.15 * detail) * pulse
            rounded_rect(p, zone_rect, 3, with_alpha(fill, fill_alpha), color("#ffffff", border_alpha))

    def draw_map_robots(self, p: QPainter, rect: QRectF, field: FieldLayout, compact: bool = False) -> None:
        now = time.perf_counter()
        font = self.font("poppins_medium", 6.8)
        for index, robot in enumerate(self.state.map_robots):
            point = self.map_point(rect, field, float(robot.get("x", 0.0)), float(robot.get("y", 0.0)))
            team = str(robot.get("team", "ally"))
            highlight = bool(robot.get("highlight", False))
            base_color = self.map_team_color(team)
            if highlight:
                radius = (7.0 if compact else 9.5) + (2.8 if compact else 4.0) * (0.5 + 0.5 * math.sin(now * 4.0 + index))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(with_alpha(base_color, 0.40), 1.1))
                p.drawEllipse(point, radius, radius)
            p.setBrush(base_color)
            p.setPen(QPen(color("#ffffff", 0.86), 1.0))
            dot_radius = 3.4 if compact else 4.2
            p.drawEllipse(point, dot_radius, dot_radius)
            if not compact:
                label = str(robot.get("id", "?"))
                label_rect = QRectF(point.x() + 6, point.y() - 9, 34, 14)
                self.draw_text(p, label_rect, label, font, THEME.text)
            hp = int(robot.get("hp", 0))
            hp_max = max(1, int(robot.get("max", 1)))
            bar_w = 15 if compact else 20
            bar = QRectF(point.x() - bar_w / 2, point.y() + (5 if compact else 7), bar_w, 2.4 if compact else 3)
            draw_bar(p, bar, hp / hp_max, base_color, color("#ffffff", 0.16), 1.5)
            tooltip = f"{robot.get('name', 'Robot')} {robot.get('id', '?')} | {hp}/{hp_max} HP"
            self.add_hotspot(QRectF(point.x() - 10, point.y() - 10, 20, 20), "map_robot", robot.get("id"), tooltip=tooltip)

    def draw_map_markers(
        self,
        p: QPainter,
        rect: QRectF,
        field: FieldLayout,
        compact: bool = False,
        detail_progress: float | None = None,
    ) -> None:
        now = time.perf_counter()
        detail = (0.0 if compact else 1.0) if detail_progress is None else max(0.0, min(1.0, detail_progress))
        font = self.font("poppins_medium", 6.5)
        for index, marker in enumerate(self.state.map_markers):
            point = self.map_point(rect, field, float(marker.get("x", 0.0)), float(marker.get("y", 0.0)))
            pulse = bool(marker.get("pulse", False))
            kind = str(marker.get("kind", "marker"))
            c = self.hud_warning() if kind == "control" else self.hud_success() if kind == "supply" else self.hud_accent()
            if pulse:
                p.setPen(QPen(with_alpha(c, 0.44), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                pulse_r = (5.5 + 2.5 * detail) + (2.5 + 1.5 * detail) * (0.5 + 0.5 * math.sin(now * 4.6))
                p.drawEllipse(point, pulse_r, pulse_r)
            p.setPen(QPen(c, 1.2))
            half = 4.0 + 2.0 * detail
            p.drawLine(point + QPointF(-half, 0), point + QPointF(half, 0))
            p.drawLine(point + QPointF(0, -half), point + QPointF(0, half))
            if detail > 0.001:
                p.save()
                p.setOpacity(p.opacity() * detail)
                self.draw_text(p, QRectF(point.x() + 7, point.y() - 8, 48, 13), str(marker.get("label", "")), font, c)
                p.restore()

    def draw_map_status_orbit_dock(self, p: QPainter, rect: QRectF, field_rect: QRectF, width: int, minimal: bool, compact: bool) -> None:
        match_rows, telemetry_rows = self.map_status_groups()
        bottom_rows = match_rows[: 3 if minimal else 4]
        side_rows = telemetry_rows[: 2 if minimal else 4]
        if not bottom_rows and not side_rows:
            return

        margin = 9.0 if minimal else 12.0
        bottom_h = max(29.0 if minimal else 42.0, rect.bottom() - field_rect.bottom() - (5.0 if minimal else 8.0))
        bottom_rect = QRectF(rect.left() + margin, rect.bottom() - bottom_h - 4.0, rect.width() - margin * 2.0, bottom_h)
        mode_key = "mini" if minimal else "full"
        if bottom_rows:
            self.draw_blackhole_disc_row(p, bottom_rect, bottom_rows, minimal=minimal, vertical=False, dock_key=f"match.{mode_key}")

        if not side_rows:
            return

        side_d = 23.0 if minimal else 34.0 if compact else 38.0
        side_gap = 6.0 if minimal else 8.0
        side_label_w = 39.0 if minimal else 54.0
        side_w = side_d + 14.0 + side_label_w
        side_h = len(side_rows) * side_d + max(0, len(side_rows) - 1) * side_gap + 10.0
        side_x = rect.right() + (7.0 if minimal else 9.0)
        side_y = min(rect.bottom() - side_h - 4.0, max(rect.top() + 18.0, field_rect.top() + 4.0))
        safe_right = width - 218.0
        can_use_side = side_x + side_w <= safe_right and side_y >= 24.0

        if can_use_side:
            side_rect = QRectF(side_x, side_y, side_w, side_h)
            self.draw_blackhole_disc_row(p, side_rect, side_rows, minimal=minimal, vertical=True, dock_key=f"telemetry.{mode_key}")
            return

        fold_w = min(rect.width() - margin * 2.0, len(side_rows) * (side_d + (27.0 if minimal else 38.0)))
        fold_h = side_d + (17.0 if minimal else 24.0)
        fold_rect = QRectF(rect.left() + margin, rect.bottom() + 5.0, fold_w, fold_h)
        self.draw_blackhole_disc_row(p, fold_rect, side_rows, minimal=minimal, vertical=False, dock_key=f"telemetry_fold.{mode_key}")

    def draw_blackhole_disc_row(
        self,
        p: QPainter,
        rect: QRectF,
        rows: list[tuple[str, str, float, QColor, str, str]],
        minimal: bool,
        vertical: bool,
        dock_key: str = "status",
    ) -> None:
        if not rows:
            return
        enter = self.anim.value(f"map.status.dock.{dock_key}", 1.0, self.anim_duration(0.26), Easings.ease_out_expo, initial=0.0)
        p.save()
        p.setOpacity(p.opacity() * enter)
        rounded_rect(p, rect, 10 if not minimal else 7, self.hud_surface(0.24 if minimal else 0.34), self.hud_panel_outline(0.040 if self.hud_clean() else 0.050))
        accent = QLinearGradient(rect.topLeft(), rect.topRight() if not vertical else rect.bottomLeft())
        accent.setColorAt(0.0, with_alpha(self.hud_accent(), 0.42 if minimal else 0.58))
        accent.setColorAt(1.0, with_alpha(self.hud_accent(), 0.60 if minimal else 0.76))
        if vertical:
            p.fillRect(QRectF(rect.left() + 4.0, rect.top() + 6.0, 1.2, rect.height() - 12.0), accent)
        else:
            p.fillRect(QRectF(rect.left() + 7.0, rect.top() + 3.0, rect.width() - 14.0, 1.0), accent)
        if vertical:
            slot_h = rect.height() / len(rows)
            for index, row in enumerate(rows):
                label, value, ratio, c, key, tooltip = row
                row_enter = self.anim.value(f"map.status.item.{dock_key}.{key}", 1.0, self.anim_duration(0.18 + index * 0.045), Easings.ease_out_expo, initial=0.0)
                diameter = max(18.0, min(23.0 if minimal else 38.0, slot_h - 5.0, rect.width() - (48.0 if minimal else 62.0)))
                center = QPointF(rect.left() + 7.0 + diameter / 2.0 - (1.0 - row_enter) * 10.0, rect.top() + slot_h * (index + 0.5))
                p.save()
                p.setOpacity(p.opacity() * row_enter)
                self.draw_blackhole_status_disc(p, center, diameter, label, value, ratio, c, key, tooltip, show_label=True, label_side="right")
                p.restore()
            p.restore()
            return

        slot_w = rect.width() / len(rows)
        for index, row in enumerate(rows):
            label, value, ratio, c, key, tooltip = row
            row_enter = self.anim.value(f"map.status.item.{dock_key}.{key}", 1.0, self.anim_duration(0.18 + index * 0.045), Easings.ease_out_expo, initial=0.0)
            label_space = 13.0 if minimal else 16.0
            diameter = max(18.0, min(23.0 if minimal else 38.0, rect.height() - 10.0 - label_space, slot_w - 14.0))
            center = QPointF(rect.left() + slot_w * (index + 0.5), rect.top() + 6.0 + diameter / 2.0 + (1.0 - row_enter) * 8.0)
            p.save()
            p.setOpacity(p.opacity() * row_enter)
            self.draw_blackhole_status_disc(p, center, diameter, label, value, ratio, c, key, tooltip, show_label=True, label_side="bottom")
            p.restore()
        p.restore()

    def animated_status_ratio(self, key: str, target_ratio: float) -> tuple[float, float]:
        target_ratio = max(0.0, min(1.0, target_ratio))
        fast = self.anim.value(
            f"map.status.ratio.fast.{key}",
            target_ratio,
            self.anim_duration(0.18),
            Easings.ease_out_cubic,
            initial=target_ratio,
        )
        lag = self.anim.value(
            f"map.status.ratio.lag.{key}",
            target_ratio,
            self.anim_duration(0.62),
            Easings.ease_out_pow5,
            initial=target_ratio,
        )
        return fast, lag

    def draw_blackhole_status_disc(
        self,
        p: QPainter,
        center: QPointF,
        diameter: float,
        label: str,
        value: str,
        ratio: float,
        c: QColor,
        key: str,
        tooltip: str,
        show_label: bool,
        label_side: str,
    ) -> None:
        fast_ratio, lag_ratio = self.animated_status_ratio(key, ratio)
        radius = max(6.0, diameter / 2.0)
        disc_rect = QRectF(center.x() - radius - 6.0, center.y() - radius - 6.0, diameter + 12.0, diameter + 12.0)
        label_probe = disc_rect.adjusted(-4.0, -4.0, 50.0 if label_side == "right" else 24.0, 16.0 if label_side == "bottom" else 4.0)
        hover_v = self.anim.value(
            f"map.status.hover.{key}",
            1.0 if label_probe.contains(self.hover_point) else 0.0,
            self.anim_duration(0.16),
            Easings.ease_out_cubic,
        )
        danger = label in ("HEAT", "POWER", "SPEED") and fast_ratio > 0.82
        if self.hud_clean():
            if danger or label in ("ENEMY", "EBASE"):
                main = self.hud_danger()
            elif label in ("GOLD", "POWER", "OUT"):
                main = self.hud_warning()
            elif label in ("AMMO",):
                main = self.hud_success()
            else:
                main = c
        else:
            main = THEME.pink if danger else c
        lite = self.high_res_optimize()
        pulse = 0.5 + 0.5 * math.sin(time.perf_counter() * (3.0 if not danger else 5.2) + len(label))
        draw_r = radius + hover_v * 2.0
        arc_rect = QRectF(center.x() - draw_r, center.y() - draw_r, draw_r * 2.0, draw_r * 2.0)

        p.save()
        p.setBrush(with_alpha(main, (0.04 if self.hud_clean() else 0.06 if lite else 0.10 if not danger else 0.18) + (0.025 if self.hud_clean() or lite else 0.08) * pulse + 0.05 * hover_v))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, draw_r + (3.0 if lite else 6.0), draw_r + (3.0 if lite else 6.0))
        p.setBrush(color("#000000", 0.78))
        p.drawEllipse(center, draw_r + 2.0, draw_r + 2.0)

        p.setBrush(Qt.BrushStyle.NoBrush)
        stroke = max(1.7, diameter * 0.095)
        p.setPen(QPen(color("#ffffff", 0.11), stroke))
        p.drawEllipse(arc_rect)
        p.setPen(QPen(with_alpha(main, 0.22 + 0.10 * pulse + 0.10 * hover_v), stroke + 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect.adjusted(-1.0, -1.0, 1.0, 1.0), 90 * 16, -int(360 * 16 * lag_ratio))
        p.setPen(QPen(with_alpha(main, 0.78 + 0.18 * pulse), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect, 90 * 16, -int(360 * 16 * fast_ratio))
        sheen_angle = int((time.perf_counter() * 80.0 + len(label) * 13.0) % 360)
        p.setPen(QPen(color("#ffffff", 0.16 + 0.10 * hover_v), max(0.7, stroke * 0.42), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect.adjusted(3.0, 3.0, -3.0, -3.0), sheen_angle * 16, -38 * 16)

        p.setBrush(color("#050509", 0.96))
        p.setPen(QPen(color("#ffffff", 0.08), 0.7))
        p.drawEllipse(center, draw_r * 0.58, draw_r * 0.58)
        p.setBrush(with_alpha(main, 0.58))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(center.x() - draw_r * 0.15, center.y() - draw_r * 0.16), max(1.3, draw_r * 0.09), max(1.3, draw_r * 0.09))

        font_size = max(4.6, min(7.4, diameter * 0.22))
        value_font = self.font("poppins_bold", font_size)
        value_rect = QRectF(center.x() - diameter * 0.64, center.y() - diameter * 0.22, diameter * 1.28, diameter * 0.44)
        self.draw_text(p, value_rect.translated(0.6, 0.7), value, value_font, color("#000000", 0.72), Qt.AlignmentFlag.AlignCenter)
        self.draw_text(p, value_rect, value, value_font, THEME.text, Qt.AlignmentFlag.AlignCenter)
        p.restore()

        if show_label:
            self.draw_status_label_capsule(p, center, draw_r, diameter, label, tooltip, main, hover_v, label_side)

        self.add_hotspot(label_probe.adjusted(-4.0, -4.0, 8.0, 8.0), "map_status", key, tooltip=tooltip)

    def draw_status_label_capsule(
        self,
        p: QPainter,
        center: QPointF,
        radius: float,
        diameter: float,
        label: str,
        tooltip: str,
        main: QColor,
        hover_v: float,
        label_side: str,
    ) -> None:
        short_text = self.compact_map_status_label(label)
        detail_text = tooltip
        label_font = self.font("poppins_medium", max(4.8, min(6.5, diameter * 0.18)))
        short_w = text_width(p, label_font, short_text) + 9.0
        detail_w = text_width(p, label_font, detail_text) + 13.0
        max_w = 92.0 if label_side == "right" else 118.0
        target_w = min(max_w, max(short_w, detail_w))
        capsule_w = short_w + (target_w - short_w) * hover_v
        capsule_h = max(10.0, min(13.0, diameter * 0.34 + 4.0))
        if label_side == "right":
            capsule_rect = QRectF(center.x() + radius + 5.0, center.y() - capsule_h / 2.0, capsule_w, capsule_h)
            text_rect = capsule_rect.adjusted(5.0, 0.0, -4.0, 0.0)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            capsule_rect = QRectF(center.x() - capsule_w / 2.0, center.y() + radius + 2.5, capsule_w, capsule_h)
            text_rect = capsule_rect.adjusted(3.0, 0.0, -3.0, 0.0)
            align = Qt.AlignmentFlag.AlignCenter

        p.save()
        rounded_rect(
            p,
            capsule_rect,
            capsule_h / 2.0,
            color("#020306", 0.58 + hover_v * 0.16),
            with_alpha(main, 0.18 + hover_v * 0.30),
            0.7,
        )
        shine = QLinearGradient(capsule_rect.topLeft(), capsule_rect.topRight())
        alt = self.hud_accent() if self.hud_clean() else THEME.pink if main == THEME.cyan else THEME.cyan
        shine.setColorAt(0.0, with_alpha(main, 0.36 + 0.16 * hover_v))
        shine.setColorAt(1.0, with_alpha(alt, 0.28 + 0.10 * hover_v))
        if label_side == "right":
            p.fillRect(QRectF(capsule_rect.left() + 1.4, capsule_rect.top() + 2.2, 1.0, capsule_rect.height() - 4.4), shine)
        else:
            p.fillRect(QRectF(capsule_rect.left() + 4.5, capsule_rect.top() + 1.4, capsule_rect.width() - 9.0, 1.0), shine)
        text = detail_text if hover_v > 0.58 and capsule_w > short_w + 22.0 else short_text
        self.draw_text(p, text_rect.translated(0.5, 0.6), text, label_font, color("#000000", 0.68), align)
        self.draw_text(p, text_rect, text, label_font, with_alpha(main, 0.94), align)
        p.restore()

    def compact_map_status_label(self, label: str) -> str:
        return {
            "ALLY": "ALLY",
            "ENEMY": "ENMY",
            "RED YOU": "RED",
            "BLUE YOU": "BLUE",
            "CTRL": "CTRL",
            "GOLD": "GOLD",
            "BASE": "BASE",
            "POWER": "PWR",
            "SPEED": "SPD",
            "EBASE": "EBASE",
            "OUTPOST": "OUT",
            "AMMO": "AMMO",
        }.get(label, label[:5])

    def map_status_groups(self) -> tuple[list[tuple[str, str, float, QColor, str, str]], list[tuple[str, str, float, QColor, str, str]]]:
        config = self.match_mode_manager.current
        match_rows: list[tuple[str, str, float, QColor, str, str]] = []
        own_side = self.alliance_side()
        enemy_side = "Blue" if own_side == "Red" else "Red"
        red_vp = self.state.ally_victory_points if own_side == "Red" else self.state.enemy_victory_points
        blue_vp = self.state.enemy_victory_points if own_side == "Red" else self.state.ally_victory_points
        if config.key == "RMUL3v3":
            if self.registry.get("VictoryPointStatus") and self.registry.get("VictoryPointStatus").enabled:
                match_rows.extend(
                    [
                        ("RED" + (" YOU" if own_side == "Red" else ""), str(red_vp), red_vp / 200.0, self.map_team_color("red"), "red_vp", f"RED VP {red_vp}"),
                        ("BLUE" + (" YOU" if own_side == "Blue" else ""), str(blue_vp), blue_vp / 200.0, self.map_team_color("blue"), "blue_vp", f"BLUE VP {blue_vp}"),
                        ("CTRL", f"{int(self.state.control_progress)}%", self.state.control_progress / 100.0, self.map_control_color(), "control", f"CONTROL {self.state.control_owner} {self.state.control_progress}%"),
                    ]
                )
            if self.registry.get("EconomyPanel") and self.registry.get("EconomyPanel").enabled:
                match_rows.append(("GOLD", str(int(self.state.remaining_economy)), min(1.0, self.state.remaining_economy / 400.0), self.hud_state_color("gold"), "gold", f"GOLD {self.state.remaining_economy} / T{self.state.tech_level}"))
        else:
            if self.registry.get("BaseOutpostStatus") and self.registry.get("BaseOutpostStatus").enabled:
                match_rows.extend(
                    [
                        (f"{own_side.upper()} BASE YOU", self.short_ring_number(self.state.base_health), self.state.base_health / max(1, self.state.base_max_health), self.map_team_color("ally"), "base", f"{own_side} BASE {self.state.base_health}/{self.state.base_max_health}"),
                        (f"{enemy_side.upper()} BASE", self.short_ring_number(self.state.enemy_base_health), self.state.enemy_base_health / max(1, self.state.enemy_base_max_health), self.map_team_color("enemy"), "enemy_base", f"{enemy_side} BASE {self.state.enemy_base_health}/{self.state.enemy_base_max_health}"),
                        ("OUTPOST", self.short_outpost_value(), self.state.enemy_outpost_health / max(1, self.state.enemy_outpost_max_health), self.map_team_color("enemy"), "outpost", f"{enemy_side} OUTPOST {self.state.enemy_outpost_status}"),
                    ]
                )
            if self.registry.get("EconomyPanel") and self.registry.get("EconomyPanel").enabled:
                match_rows.append(("GOLD", str(int(self.state.remaining_economy)), min(1.0, self.state.remaining_economy / 400.0), self.hud_state_color("gold"), "gold", f"GOLD {self.state.remaining_economy} / T{self.state.tech_level}"))
            if self.registry.get("ProjectileShop") and self.registry.get("ProjectileShop").enabled:
                match_rows.append(("AMMO", str(int(self.state.projectile_allowance_17mm)), min(1.0, self.state.projectile_allowance_17mm / 180.0), self.hud_state_color("ammo"), "ammo", f"AMMO 17mm {self.state.projectile_allowance_17mm} | 42mm {self.state.projectile_allowance_42mm}"))
        return match_rows[:5], self.map_telemetry_status_rows()

    def map_telemetry_status_rows(self) -> list[tuple[str, str, float, QColor, str, str]]:
        rows: list[tuple[str, str, float, QColor, str, str]] = []
        thermal = self.registry.get("ThermalPowerPanel")
        if thermal and thermal.enabled:
            ratio = self.state.current_heat / max(1.0, self.state.max_heat)
            rows.append(("HEAT", str(int(self.state.current_heat)), ratio, self.hud_state_color("heat", ratio), "heat", f"HEAT {int(self.state.current_heat)}/{int(self.state.max_heat)}"))
        power = self.registry.get("PowerLimit")
        if power and power.enabled:
            limit = max(1.0, self.get_setting_number(power, "Limit", float(self.state.power_limit)))
            ratio = self.state.chassis_power_w / limit
            rows.append(("POWER", str(int(self.state.chassis_power_w)), ratio, self.hud_state_color("power", ratio), "power", f"POWER {int(self.state.chassis_power_w)} / {int(limit)}W"))
        speed = self.registry.get("SpeedLimit")
        if speed and speed.enabled:
            limit = max(1.0, self.get_setting_number(speed, "Limit", float(self.state.speed_limit)))
            unit_setting = speed.get_setting("Unit")
            unit = str(unit_setting.value) if unit_setting else "dps"
            ratio = self.state.speed_limit / limit
            rows.append(("SPEED", str(int(self.state.speed_limit)), ratio, self.hud_state_color("speed", ratio), "speed", f"SPEED {int(self.state.speed_limit)} {unit}"))
        capacitor = self.registry.get("Capacitor")
        if capacitor and capacitor.enabled:
            ratio = self.state.capacitor_percent / 100.0
            rows.append(("CAP", f"{self.state.capacitor_percent}%", ratio, self.hud_state_color("cap", ratio), "cap", f"CAP {self.state.capacitor_percent}%"))
        return rows[:4]

    def draw_match_status_lines(self, p: QPainter, rect: QRectF) -> None:
        rows = self.match_status_rows(compact=True)[:3]
        if not rows:
            return
        gap = 2.0
        line_h = max(1.4, min(2.4, (rect.height() - gap * (len(rows) - 1)) / max(1, len(rows))))
        y = rect.top()
        for _label, _value, ratio, c in rows:
            draw_bar(p, QRectF(rect.left(), y, rect.width(), line_h), ratio, c, color("#ffffff", 0.12), line_h / 2.0)
            y += line_h + gap

    def draw_match_status_stack(self, p: QPainter, rect: QRectF, compact: bool = False) -> None:
        rows = self.match_status_rows(compact=compact)
        if not rows:
            return
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, 7, surface="SubGlass")
        else:
            rounded_rect(p, rect, 7, self.hud_surface(0.40 if compact else 0.34), self.hud_panel_outline(0.07))
        row_h = rect.height() / max(1, len(rows))
        for index, (label, value, ratio, c) in enumerate(rows):
            y = rect.top() + index * row_h
            label_font = self.font("poppins_medium", 5.6 if compact else 6.8)
            value_font = self.font("poppins_medium", 5.6 if compact else 6.9)
            left_pad = 6 if compact else 8
            main = self.liquid_status_color(label, ratio, c)
            self.draw_text(p, QRectF(rect.left() + left_pad, y, rect.width() * 0.38, row_h), label, label_font, with_alpha(main, 0.88))
            self.draw_text(p, QRectF(rect.left() + rect.width() * 0.43, y, rect.width() * 0.52, row_h), value, value_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            draw_bar(p, QRectF(rect.left() + left_pad, y + row_h - (3.0 if compact else 4.0), rect.width() - left_pad * 2, 1.8 if compact else 2.4), ratio, c, color("#ffffff", 0.10), 1.2)

    def draw_match_status_rings(self, p: QPainter, rect: QRectF, compact: bool = False) -> None:
        max_items = max(1, min(4, int(rect.width() // (46.0 if compact else 58.0))))
        rows = self.match_status_ring_rows()[:max_items]
        if not rows:
            return
        rounded_rect(p, rect, 8, self.hud_surface(0.24 if compact else 0.28), self.hud_panel_outline(0.05))
        slot_w = rect.width() / len(rows)
        ring_d = max(18.0, min(28.0 if compact else 34.0, rect.height() - (12.0 if compact else 15.0), slot_w - 14.0))
        radius = ring_d / 2.0
        top = rect.top() + 5.0
        pulse = 0.5 + 0.5 * math.sin(time.perf_counter() * 3.0)
        for index, (label, value, ratio, c) in enumerate(rows):
            ratio = max(0.0, min(1.0, ratio))
            cx = rect.left() + slot_w * (index + 0.5)
            center = QPointF(cx, top + radius)
            arc_rect = QRectF(center.x() - radius, center.y() - radius, ring_d, ring_d)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color("#ffffff", 0.12), max(1.4, ring_d * 0.085)))
            p.drawEllipse(arc_rect)
            p.setPen(QPen(with_alpha(c, 0.72 + 0.18 * pulse), max(1.6, ring_d * 0.095), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc_rect, 90 * 16, -int(360 * 16 * ratio))
            p.setBrush(color("#050507", 0.80))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(center, max(5.6, ring_d * 0.27), max(5.6, ring_d * 0.27))
            self.draw_text(p, QRectF(center.x() - slot_w / 2.0, center.y() - 6.0, slot_w, 12.0), value, self.font("poppins_bold", 6.2 if compact else 7.0), THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.draw_text(p, QRectF(center.x() - slot_w / 2.0, rect.bottom() - (11.0 if compact else 13.0), slot_w, 10.0), label, self.font("poppins_medium", 5.6 if compact else 6.3), with_alpha(c, 0.92), Qt.AlignmentFlag.AlignCenter)

    def match_status_ring_rows(self) -> list[tuple[str, str, float, QColor]]:
        config = self.match_mode_manager.current
        rows: list[tuple[str, str, float, QColor]] = []
        if config.key == "RMUL3v3":
            if self.registry.get("VictoryPointStatus") and self.registry.get("VictoryPointStatus").enabled:
                rows.extend(
                    [
                        ("ALLY", str(self.state.ally_victory_points), self.state.ally_victory_points / 200.0, self.hud_state_color("ally")),
                        ("ENEMY", str(self.state.enemy_victory_points), self.state.enemy_victory_points / 200.0, self.hud_state_color("enemy")),
                        ("CTRL", f"{int(self.state.control_progress)}%", self.state.control_progress / 100.0, self.hud_state_color("control")),
                    ]
                )
            if self.registry.get("ThermalPowerPanel") and self.registry.get("ThermalPowerPanel").enabled:
                ratio = self.state.current_heat / max(1.0, self.state.max_heat)
                rows.append(("HEAT", f"{int(self.state.current_heat)}", ratio, self.hud_state_color("heat", ratio)))
            return rows[:4]

        if self.registry.get("BaseOutpostStatus") and self.registry.get("BaseOutpostStatus").enabled:
            rows.extend(
                [
                    ("BASE", self.short_ring_number(self.state.base_health), self.state.base_health / max(1, self.state.base_max_health), self.hud_state_color("ally")),
                    ("EBASE", self.short_ring_number(self.state.enemy_base_health), self.state.enemy_base_health / max(1, self.state.enemy_base_max_health), self.hud_state_color("enemy")),
                    ("OUT", self.short_outpost_value(), self.state.enemy_outpost_health / max(1, self.state.enemy_outpost_max_health), self.hud_state_color("warning")),
                ]
            )
        if self.registry.get("EconomyPanel") and self.registry.get("EconomyPanel").enabled:
            rows.append(("GOLD", str(int(self.state.remaining_economy)), min(1.0, self.state.remaining_economy / 400.0), self.hud_state_color("gold")))
        if len(rows) < 4 and self.registry.get("ProjectileShop") and self.registry.get("ProjectileShop").enabled:
            rows.append(("AMMO", str(int(self.state.projectile_allowance_17mm)), min(1.0, self.state.projectile_allowance_17mm / 180.0), self.hud_state_color("ammo")))
        if len(rows) < 4 and self.registry.get("ThermalPowerPanel") and self.registry.get("ThermalPowerPanel").enabled:
            ratio = self.state.current_heat / max(1.0, self.state.max_heat)
            rows.append(("HEAT", f"{int(self.state.current_heat)}", ratio, self.hud_state_color("heat", ratio)))
        return rows[:4]

    def short_ring_number(self, value: float) -> str:
        value = float(value)
        if abs(value) >= 1000:
            return f"{value / 1000.0:.1f}k".replace(".0k", "k")
        return str(int(value))

    def short_outpost_value(self) -> str:
        status = str(self.state.enemy_outpost_status)
        if status.upper() in ("ACTIVE", "ALIVE", "ONLINE"):
            return "OK"
        if status.upper() in ("DOWN", "DESTROYED", "OFFLINE"):
            return "DOWN"
        if self.state.enemy_outpost_health <= 0:
            return "DOWN"
        return self.short_ring_number(self.state.enemy_outpost_health)

    def match_status_rows(self, compact: bool = False) -> list[tuple[str, str, float, QColor]]:
        config = self.match_mode_manager.current
        rows: list[tuple[str, str, float, QColor]] = []
        if config.key == "RMUL3v3":
            if self.registry.get("VictoryPointStatus") and self.registry.get("VictoryPointStatus").enabled:
                rows.extend(
                    [
                        ("ALLY VP", str(self.state.ally_victory_points), self.state.ally_victory_points / 200.0, self.hud_state_color("ally")),
                        ("ENEMY VP", str(self.state.enemy_victory_points), self.state.enemy_victory_points / 200.0, self.hud_state_color("enemy")),
                        ("CONTROL", f"{self.state.control_owner} {self.state.control_progress}%", self.state.control_progress / 100.0, self.hud_state_color("control")),
                    ]
                )
        elif self.registry.get("BaseOutpostStatus") and self.registry.get("BaseOutpostStatus").enabled:
            rows.extend(
                [
                    ("OWN BASE", f"{self.state.base_health}/{self.state.base_max_health}", self.state.base_health / max(1, self.state.base_max_health), self.hud_state_color("ally")),
                    ("ENEMY BASE", f"{self.state.enemy_base_health}/{self.state.enemy_base_max_health}", self.state.enemy_base_health / max(1, self.state.enemy_base_max_health), self.hud_state_color("enemy")),
                    ("OUTPOST", f"{self.state.enemy_outpost_status}", self.state.enemy_outpost_health / max(1, self.state.enemy_outpost_max_health), self.hud_state_color("warning")),
                ]
            )
        if self.registry.get("EconomyPanel") and self.registry.get("EconomyPanel").enabled:
            rows.append(("GOLD", f"{self.state.remaining_economy} / T{self.state.tech_level}", min(1.0, self.state.remaining_economy / 400.0), self.hud_state_color("gold")))
        if self.registry.get("ProjectileShop") and self.registry.get("ProjectileShop").enabled:
            rows.append(("AMMO", f"17 {self.state.projectile_allowance_17mm} | 42 {self.state.projectile_allowance_42mm}", min(1.0, self.state.projectile_allowance_17mm / 180.0), self.hud_state_color("ammo")))
        if self.registry.get("ThermalPowerPanel") and self.registry.get("ThermalPowerPanel").enabled:
            ratio = self.state.current_heat / max(1.0, self.state.max_heat)
            rows.append(("HEAT/PWR", f"{int(self.state.current_heat)}/{int(self.state.max_heat)}  {int(self.state.chassis_power_w)}W", ratio, self.hud_state_color("heat", ratio)))
        if compact:
            compact_labels = {
                "ALLY VP": "ALLY",
                "ENEMY VP": "ENEMY",
                "CONTROL": "CTRL",
                "OWN BASE": "BASE",
                "ENEMY BASE": "E.BASE",
                "OUTPOST": "OUT",
                "GOLD": "GOLD",
                "HEAT/PWR": "HEAT",
            }
            rows = [(compact_labels.get(label, label), value, ratio, c) for label, value, ratio, c in rows[:3]]
        else:
            rows = rows[:4]
        return rows

    def draw_telemetry_strip(self, p: QPainter, width: int, height: int) -> None:
        cards: list[tuple[str, str, float, QColor, str]] = []
        thermal = self.registry.get("ThermalPowerPanel")
        if thermal and thermal.enabled:
            heat = self.animated_scalar("telemetry.heat", self.state.current_heat, 20.0)
            heat_ratio = heat / max(1.0, self.state.max_heat)
            cards.append(("HEAT", f"{int(round(heat))}/{int(self.state.max_heat)}", heat_ratio, self.hud_state_color("heat", heat_ratio), "ThermalPowerPanel"))
        power = self.registry.get("PowerLimit")
        if power and power.enabled:
            limit = max(1.0, self.get_setting_number(power, "Limit", float(self.state.power_limit)))
            power_value = self.animated_scalar("telemetry.power", self.state.chassis_power_w, 18.0)
            ratio = power_value / limit
            cards.append(("POWER", f"{int(round(power_value))} / {int(limit)}W", ratio, self.hud_state_color("power", ratio), "PowerLimit"))
        speed = self.registry.get("SpeedLimit")
        if speed and speed.enabled:
            limit = max(1.0, self.get_setting_number(speed, "Limit", float(self.state.speed_limit)))
            unit_setting = speed.get_setting("Unit")
            unit = str(unit_setting.value) if unit_setting else "dps"
            speed_value = self.animated_scalar("telemetry.speed", self.state.speed_limit, 16.0)
            ratio = speed_value / max(1.0, limit)
            cards.append(("SPEED", f"{int(round(speed_value))} {unit}", ratio, self.hud_state_color("speed", ratio), "SpeedLimit"))
        capacitor = self.registry.get("Capacitor")
        if capacitor and capacitor.enabled:
            cap_value = self.animated_scalar("telemetry.cap", self.state.capacitor_percent, 18.0)
            ratio = cap_value / 100.0
            cards.append(("CAP", f"{int(round(cap_value))}%", ratio, self.hud_state_color("cap", ratio), "Capacitor"))
        cards = cards[:4]
        if not cards:
            return
        if self.hud_density() != "DebugFull":
            self.draw_compact_telemetry_strip(p, width, height, cards)
            return

        card_w = 118.0
        card_h = 34.0
        gap = 8.0
        total_w = len(cards) * card_w + (len(cards) - 1) * gap
        x = max(260.0, min(width - total_w - 270.0, width / 2 - total_w / 2))
        y = height - 62.0
        for index, (label, value, ratio, c, key) in enumerate(cards):
            active = self.anim.value(f"hud.telemetry.{key}", 1.0, self.anim_duration(0.20 + index * 0.02), Easings.ease_out_pow4, initial=0.0)
            rect = QRectF(x + index * (card_w + gap), y + (1.0 - active) * 12.0, card_w, card_h)
            p.save()
            p.setOpacity(active)
            if self.hud_clean():
                self.draw_hud_liquid_glass(p, rect, 7, surface="SubGlass")
            else:
                glow_rect(p, rect, 8, 0.11)
                rounded_rect(p, rect, 7, self.hud_surface(0.68), self.hud_panel_outline(0.09))
            self.draw_text(p, QRectF(rect.left() + 9, rect.top() + 5, 48, 12), label, self.font("poppins_medium", 7.0), THEME.muted)
            self.draw_text(p, QRectF(rect.left() + 46, rect.top() + 4, rect.width() - 55, 13), value, self.font("poppins_bold", 7.3), THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            draw_bar(p, QRectF(rect.left() + 9, rect.bottom() - 10, rect.width() - 18, 4.2), max(0.0, min(1.0, ratio)), c, color("#ffffff", 0.13), 2.1)
            p.restore()

    def draw_compact_telemetry_strip(self, p: QPainter, width: int, height: int, cards: list[tuple[str, str, float, QColor, str]]) -> None:
        strip_w = min(420.0, max(300.0, width * 0.34))
        strip_h = 28.0
        x = width / 2.0 - strip_w / 2.0
        y = height - 42.0
        active = self.anim.value("hud.telemetry.compact", 1.0, self.anim_duration(0.22), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        strip_rect = QRectF(x, y, strip_w, strip_h)
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, strip_rect, 8, surface="SubGlass")
        else:
            rounded_rect(p, strip_rect, 8, self.hud_surface(0.50), self.hud_panel_outline(0.07))
        gap = 9.0
        seg_w = (strip_w - 18.0 - gap * (len(cards) - 1)) / max(1, len(cards))
        seg_x = x + 9.0
        for label, value, ratio, c, key in cards:
            ratio = max(0.0, min(1.0, ratio))
            row_active = self.anim.value(f"hud.telemetry.compact.{key}", 1.0, self.anim_duration(0.16), Easings.ease_out_pow4, initial=0.0)
            p.setOpacity(active * row_active)
            self.draw_text(p, QRectF(seg_x, y + 4, seg_w * 0.44, 10), label, self.font("poppins_medium", 6.4), THEME.muted)
            self.draw_text(p, QRectF(seg_x + seg_w * 0.38, y + 4, seg_w * 0.62, 10), value.replace(" / ", "/"), self.font("poppins_medium", 6.5), THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            draw_bar(p, QRectF(seg_x, y + 18, seg_w, 3.2), ratio, c, color("#ffffff", 0.12), 1.6)
            seg_x += seg_w + gap
        p.restore()

    def format_time(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    def module_list_layout(self, width: int, height: int, start_y: float | None = None) -> ModuleListLayout:
        right_margin = 18.0
        top_margin = 18.0 if start_y is None else max(18.0, float(start_y))
        bottom_margin = 18.0
        clip = QRectF(
            0.0,
            top_margin,
            max(1.0, float(width)),
            max(1.0, float(height) - top_margin - bottom_margin),
        )
        return ModuleListLayout(
            anchor_x=max(1.0, float(width) - right_margin),
            anchor_y=top_margin,
            available_height=clip.height(),
            row_height=18.0,
            row_gap=3.0,
            right_margin=right_margin,
            top_margin=top_margin,
            clip_rect=clip,
        )

    def draw_module_list_hud(
        self,
        p: QPainter,
        width: int,
        height: int,
        start_y: float | None = None,
        layout: ModuleListLayout | None = None,
    ) -> None:
        layout = layout or self.module_list_layout(width, height, start_y)
        hud = self.registry.get("HUD")
        setting = hud.get_setting("ModuleList Style") if hud else None
        style = str(setting.value) if setting else MODULE_LIST_STYLES[0]
        if style not in MODULE_LIST_STYLES:
            style = MODULE_LIST_STYLES[0]
        p.save()
        p.setClipRect(layout.clip_rect)
        if style == "PolarTextList":
            # 裸文字列表位于左侧，必须避开水印和左上战术地图。
            # 其他右对齐样式继续使用统一的右侧安全栏。
            polar_start = max(layout.anchor_y, 64.0)
            tactical_map = self.registry.get("TacticalMap")
            if tactical_map and tactical_map.enabled:
                polar_start = max(
                    polar_start,
                    self.tactical_map_rect(width, height).bottom() + 8.0,
                )
            self.draw_module_list_polar_text(p, polar_start)
        elif style == "PolarRainbowRight":
            self.draw_module_list_rainbow_right(p, width, layout.anchor_y)
        elif style == "GlowRows":
            self.draw_module_list_glow_rows(p, width, layout.anchor_y)
        elif style == "Segmented":
            self.draw_module_list_segmented(p, width, layout.anchor_y)
        elif style == "DynamicIsland":
            self.draw_module_list_dynamic_island(p, width, layout.anchor_y)
        elif style == "KeyBindsRows":
            self.draw_module_list_keybind_rows(p, width, layout.anchor_y)
        elif style == "StatusBars":
            self.draw_module_list_status_bars(p, width, layout.anchor_y)
        elif style == "RobotCards":
            self.draw_module_list_robot_cards(p, width, layout.anchor_y)
        elif style in ("LiquidArrayList", "LiquidArrayTags", "LiquidArrayCompact", "LiquidArrayDock"):
            self.draw_module_list_liquid_array(p, width, style, layout.anchor_y, layout.available_height)
        elif style == "DebugWhiteList":
            self.draw_module_list_debug_white(p, width, layout.anchor_y, layout.available_height)
        else:
            self.draw_module_list_polar_text(p, max(layout.anchor_y, 64.0))
        p.restore()

    def draw_module_list_fast_rows(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        font = self.font("poppins_medium", 8.4)
        category_font = self.font("poppins_bold", 6.1)
        entries = self.module_list_entries(p, font, right_aligned=True)
        x = width - 18.0
        y = 18.0 if start_y is None else start_y
        max_rows = 26
        for idx, entry in enumerate(entries[:max_rows]):
            module = entry["module"]
            row_w = max(96.0, text_width(p, font, module.name) + 50.0)
            row_h = 17.0 * entry["height"]
            if row_h <= 0.1:
                continue
            rect = QRectF(x - row_w + entry["slide"], y, row_w, row_h)
            accent = accent_color(idx, time.perf_counter() * 0.38)
            p.save()
            p.setOpacity(entry["alpha"])
            rounded_rect(p, rect, 6, color("#050507", 0.52), color("#ffffff", 0.06), 0.8)
            index_rect = QRectF(rect.left(), rect.top(), 20.0, rect.height())
            rounded_rect(p, index_rect, 6, with_alpha(accent, 0.78))
            self.draw_text(p, index_rect, str(idx + 1), self.font("poppins_bold", 6.6), THEME.text, Qt.AlignmentFlag.AlignCenter)
            cat = module.category[:3].upper()
            self.draw_text(p, QRectF(rect.right() - 27, rect.top(), 24, rect.height()), cat, category_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.draw_text(p, rect.adjusted(25, 0, -32, 0), module.name, font, THEME.text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            p.restore()
            y += row_h + 3.0 * entry["height"]

    def module_list_preferences(self) -> tuple[bool, str, str, str]:
        hud = self.registry.get("HUD")
        alignment = self.setting_mode(hud, "ModuleList Alignment", "Right")
        order = self.setting_mode(hud, "ModuleList Order", "Descending")
        tags = self.setting_mode(hud, "Module Tags", "Category")
        animation = self.setting_mode(hud, "Module Animation", "FlyFlip")
        return alignment != "Left", order, tags, animation

    @staticmethod
    def module_list_tag(module: Module, tag_style: str) -> str:
        if tag_style == "Keybind":
            return module.keybind if module.keybind != "None" else "ON"
        if tag_style == "Category":
            return module.category[:3].upper()
        return ""

    def module_list_surface(self) -> str:
        hud = self.registry.get("HUD")
        return self.setting_mode(hud, "ModuleList Surface", "LiquidGlass")

    def module_list_entries(
        self,
        p: QPainter,
        font: QFont,
        right_aligned: bool | None = True,
        *,
        use_preferences: bool = False,
    ) -> list[dict[str, Any]]:
        if use_preferences:
            right_aligned, order_style, tag_style, animation_style = self.module_list_preferences()
        else:
            order_style, tag_style, animation_style = "Descending", "Off", "FlyFlip"
        assert right_aligned is not None
        visible = [m for m in self.registry.enabled_modules() if m.name not in ("HUD", "ClickGui")]
        visible.sort(
            key=lambda module: text_width(p, font, f"{module.name}  {self.module_list_tag(module, tag_style)}"),
            reverse=order_style != "Ascending",
        )
        visible_names = {module.name for module in visible}
        for order, module in enumerate(visible):
            row = self.module_list_rows.get(module.name)
            if row is None:
                row = {"module": module, "order": order, "previous_order": order, "target": 1.0, "new": True}
                self.module_list_rows[module.name] = row
            elif row.get("order", order) != order:
                row["previous_order"] = row.get("order", order)
            row["module"] = module
            row["order"] = order
            row["target"] = 1.0
        for name, row in list(self.module_list_rows.items()):
            if name not in visible_names:
                row["target"] = 0.0
                row["order"] = row.get("order", len(self.module_list_rows))

        entries: list[dict[str, Any]] = []
        for name, row in list(self.module_list_rows.items()):
            target = float(row.get("target", 0.0))
            new = bool(row.pop("new", False))
            slide_distance = 34.0 if right_aligned else -34.0
            if animation_style == "Fade":
                slide_distance = 0.0
            alpha = self.anim.value(f"hud.modulelist.alpha.{name}", target, self.anim_duration(0.22), Easings.ease_out_pow3, initial=0.0 if new else target)
            height = self.anim.value(f"hud.modulelist.height.{name}", target, self.anim_duration(0.22), Easings.ease_out_pow3, initial=0.0 if new else target)
            slide = self.anim.value(
                f"hud.modulelist.slide.{name}",
                0.0 if target > 0 else slide_distance,
                self.anim_duration(0.22),
                Easings.ease_out_pow3 if target > 0 else Easings.ease_in_pow3,
                initial=slide_distance if new else 0.0,
            )
            order_initial = float(row.get("previous_order", row.get("order", 0)))
            order_animated = self.anim.value(
                f"hud.modulelist.order.{name}",
                float(row.get("order", 0)),
                self.anim_duration(0.20),
                Easings.ease_out_cubic,
                initial=order_initial,
            )
            if target <= 0.0 and alpha <= 0.025 and height <= 0.025:
                self.module_list_rows.pop(name, None)
                continue
            entries.append(
                {
                    "module": row["module"],
                    "alpha": alpha,
                    "height": height,
                    "slide": slide,
                    "order": int(row.get("order", 0)),
                    "order_animated": order_animated,
                    "tag": self.module_list_tag(row["module"], tag_style),
                }
            )
        entries.sort(key=lambda item: item["order"])
        return entries

    def arraylist_shadow_image(self) -> QImage | None:
        """Debug.jar client/arraylistshadow.png (87×37 black + soft alpha)."""
        cached = getattr(self, "_arraylist_shadow_image", None)
        if cached is not None:
            return cached if not cached.isNull() else None
        candidates = (
            Path(__file__).resolve().parents[2] / "assets" / "hud" / "arraylistshadow.png",
            self.workspace / "rm_custom_client" / "assets" / "hud" / "arraylistshadow.png",
            self.workspace / "assets" / "hud" / "arraylistshadow.png",
        )
        image = QImage()
        for path in candidates:
            if path.exists():
                image = QImage(str(path))
                if not image.isNull():
                    break
        self._arraylist_shadow_image = image
        return image if not image.isNull() else None

    def draw_string_with_shadow_mc(
        self,
        p: QPainter,
        text: str,
        x: float,
        y: float,
        font: QFont,
        *,
        main: QColor | None = None,
    ) -> None:
        """Minecraft 1.8 drawStringWithShadow: shadow (RGB&0xFCFCFC)>>2 at +1,+1, then main."""
        main = main or QColor(255, 255, 255, 255)
        sr = (main.red() & 0xFC) >> 2
        sg = (main.green() & 0xFC) >> 2
        sb = (main.blue() & 0xFC) >> 2
        p.setFont(font)
        p.setPen(QColor(sr, sg, sb, main.alpha()))
        p.drawText(QPointF(x + 1.0, y + 1.0 + QFontMetricsF(font).ascent()), text)
        p.setPen(main)
        p.drawText(QPointF(x, y + QFontMetricsF(font).ascent()), text)

    def draw_module_list_debug_white(
        self,
        p: QPainter,
        width: int,
        start_y: float | None = None,
        available_height: float | None = None,
    ) -> None:
        """Debug.jar fluorescent-white ArrayList (MODLIST_WHITE.md / modlist-white.html).

        Tahoma 16 PLAIN + Color.WHITE α=1 + drawStringWithShadow + arraylistshadow
        underlay at α≈0.7. Right-aligned, stringWidth descending. No rainbow / side
        bar / solid black strip.
        """
        # jar tahoma16: pixel size 16, PLAIN, antiAlias off.
        font = self.font("tahoma", 12.0)
        font.setPixelSize(16)
        font.setBold(False)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        metrics = QFontMetricsF(font)
        row_h = 16.0
        pad_right = 2.0
        pad_top = 2.0 if start_y is None else float(start_y)
        pad_x = 6.0
        pad_y = 2.0
        shadow_alpha = 0.70

        visible = [m for m in self.registry.enabled_modules() if m.name not in ("HUD", "ClickGui")]
        rows = []
        for module in visible:
            name = module.name
            w = metrics.horizontalAdvance(name)
            rows.append((module, name, w))
        rows.sort(key=lambda item: (-item[2], item[1].lower()))

        y0 = pad_top
        height_limit = self.height() if available_height is None else y0 + available_height
        max_rows = max(1, int((height_limit - y0 - 4.0) // row_h))
        rows = rows[:max_rows]
        shadow = self.arraylist_shadow_image()

        p.save()
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for index, (_module, name, text_w) in enumerate(rows):
            x = float(width) - text_w - pad_right
            y = y0 + index * row_h
            # Soft underlay: black+α texture drawn with white×0.7 → dark soft plate.
            if shadow is not None and not shadow.isNull():
                dest = QRectF(x - pad_x, y - pad_y, text_w + pad_x * 2.0, row_h + pad_y * 2.0)
                p.save()
                p.setOpacity(shadow_alpha)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                p.drawImage(dest, shadow)
                p.restore()
            else:
                # Fallback soft plate if asset missing (still no solid bar).
                dest = QRectF(x - pad_x, y - pad_y, text_w + pad_x * 2.0, row_h + pad_y * 2.0)
                p.fillRect(dest, QColor(0, 0, 0, int(255 * 0.22 * shadow_alpha)))
            self.draw_string_with_shadow_mc(
                p, name, x, y, font, main=QColor(255, 255, 255, 255),
            )
        p.restore()

    def draw_module_list_liquid_array(
        self,
        p: QPainter,
        width: int,
        style: str,
        start_y: float | None = None,
        available_height: float | None = None,
    ) -> None:
        """LiquidBounce ArrayList 的宽度排序、对齐、标签和 fly/flip 行为的 PySide6 实现。"""
        compact = style == "LiquidArrayCompact"
        dock = style == "LiquidArrayDock"
        tags_variant = style == "LiquidArrayTags"
        name_font = self.font("poppins_medium", 7.2 if compact else 8.2)
        tag_font = self.font("poppins_medium", 5.8 if compact else 6.4)
        right_aligned, _order, tag_style, animation_style = self.module_list_preferences()
        entries = self.module_list_entries(p, name_font, right_aligned=None, use_preferences=True)
        if not entries:
            return
        row_h = 16.0 if compact else 21.0
        gap = 2.0 if compact else 4.0
        margin = 18.0
        y0 = 18.0 if start_y is None else start_y
        height_limit = self.height() if available_height is None else y0 + available_height
        max_rows = max(1, int((height_limit - y0 - 18.0) // (row_h + gap)))
        entries = entries[:max_rows]
        surface = self.module_list_surface()
        max_label = max(text_width(p, name_font, entry["module"].name) for entry in entries)
        max_tag = max((text_width(p, tag_font, entry["tag"]) for entry in entries), default=0.0)
        row_w = max(116.0 if compact else 144.0, min(238.0, max_label + max_tag + (38.0 if compact else 50.0)))
        x = width - margin - row_w if right_aligned else margin
        dock_rect = QRectF(x - 5.0, y0 - 5.0, row_w + 10.0, len(entries) * (row_h + gap) - gap + 10.0)
        if dock:
            if surface == "LiquidGlass":
                self.draw_hud_liquid_glass(p, dock_rect, 6.0, surface="MainGlass")
            else:
                rounded_rect(p, dock_rect, 6.0, color("#03070d", 0.66), color("#ffffff", 0.075), 0.8)

        for index, entry in enumerate(entries):
            module = entry["module"]
            order_y = entry["order_animated"] if animation_style == "FlyFlip" else float(index)
            y = y0 + order_y * (row_h + gap)
            h = row_h * entry["height"]
            if h <= 0.1:
                continue
            rect = QRectF(x + entry["slide"], y, row_w, h)
            hovered = rect.contains(self.hover_point)
            hover = self.anim.value(f"hud.liquid_array.hover.{module.name}", 1.0 if hovered else 0.0, self.anim_duration(0.15), Easings.ease_out_cubic)
            accent = self.hud_accent()
            p.save()
            p.setOpacity(p.opacity() * entry["alpha"])
            if surface == "LiquidGlass":
                self.draw_hud_liquid_glass(p, rect, 4.0 if compact else 5.0, surface="SubGlass" if compact else "MainGlass", hover=hover)
            elif not compact or hovered:
                rounded_rect(p, rect, 4.0 if compact else 5.0, color("#03060b", 0.48 + 0.16 * hover), color("#ffffff", 0.045 + 0.07 * hover), 0.7)
            rail = QRectF(rect.right() - 4.0, rect.top() + 2.0, 3.0, max(2.0, rect.height() - 4.0)) if right_aligned else QRectF(rect.left() + 1.0, rect.top() + 2.0, 3.0, max(2.0, rect.height() - 4.0))
            rounded_rect(p, rail, 1.2, with_alpha(accent, 0.76 + 0.18 * hover))
            text_rect = rect.adjusted(8.0 if not right_aligned else 7.0, 0.0, -8.0 if right_aligned else -7.0, 0.0)
            if not right_aligned:
                text_rect.adjust(4.0, 0.0, 0.0, 0.0)
            else:
                text_rect.adjust(0.0, 0.0, -4.0, 0.0)
            tag = entry["tag"]
            if tag:
                tag_w = max(21.0, min(44.0, text_width(p, tag_font, tag) + 10.0))
                tag_x = rect.left() + 6.0 if right_aligned else rect.right() - tag_w - 6.0
                tag_rect = QRectF(tag_x, rect.top() + max(1.0, (rect.height() - 13.0) / 2.0), tag_w, min(13.0, max(4.0, rect.height() - 2.0)))
                if tags_variant:
                    if surface == "LiquidGlass" and not compact:
                        self.draw_hud_liquid_glass(p, tag_rect, 3.5, surface="SubGlass", hover=hover)
                    else:
                        rounded_rect(p, tag_rect, 3.5, with_alpha(accent, 0.12 + 0.08 * hover), with_alpha(accent, 0.22), 0.6)
                if right_aligned:
                    text_rect.setLeft(tag_rect.right() + 5.0)
                else:
                    text_rect.setRight(tag_rect.left() - 5.0)
                self.draw_text(p, tag_rect, tag, tag_font, THEME.text if tags_variant else THEME.muted, Qt.AlignmentFlag.AlignCenter)
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter if right_aligned else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            self.draw_text(p, text_rect, module.name, name_font, THEME.text, align)
            if dock:
                progress = self.anim.value(f"hud.liquid_array.progress.{module.name}", 1.0 if module.enabled else 0.0, self.anim_duration(0.20), Easings.ease_out_cubic, initial=1.0)
                bar = QRectF(rect.left() + 7.0, rect.bottom() - 2.3, max(2.0, (rect.width() - 14.0) * progress), 1.1)
                rounded_rect(p, bar, 0.55, with_alpha(accent, 0.62))
            self.add_hotspot(rect, "module_toggle", module.name, tooltip=f"{module.name} | {module.category} | {module.keybind}")
            p.restore()

    def draw_module_list_polar_text(self, p: QPainter, start_y: float | None = None) -> None:
        """紧凑裸文字列表；FPS 仅由 POLAR-RM 水印统一显示。"""
        font = self.font("pingfang", 9.2)
        entries = self.module_list_entries(p, font, right_aligned=False)
        x = 18.0
        row_y = 18.0 if start_y is None else start_y
        for idx, entry in enumerate(entries):
            module = entry["module"]
            alpha = entry["alpha"]
            h = 11.0 * entry["height"]
            if h <= 0.1:
                continue
            p.save()
            p.setOpacity(alpha)
            c = accent_color(idx, 0.0)
            text_rect = QRectF(x + entry["slide"], row_y, 220, h)
            self.draw_text(p, text_rect.translated(1.0, 1.0), module.name, font, color("#000000", 0.72))
            self.draw_text(p, text_rect, module.name, font, with_alpha(c, 0.90))
            p.restore()
            row_y += h

    def draw_module_list_rainbow_right(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        font = self.font("poppins_medium", 9.6)
        entries = self.module_list_entries(p, font, right_aligned=True)
        x = width - 18
        y = 18.0 if start_y is None else start_y
        for idx, entry in enumerate(entries):
            module = entry["module"]
            row_w = text_width(p, font, module.name) + 16
            row_h = 18.0 * entry["height"]
            if row_h <= 0.1:
                continue
            row = QRectF(x - row_w + entry["slide"], y, row_w, row_h)
            p.save()
            p.setOpacity(entry["alpha"])
            shadow = row.translated(1.0, 1.0)
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            self.draw_text(p, shadow, module.name, font, color("#000000", 0.54), align)
            self.draw_text(p, row, module.name, font, with_alpha(accent_color(idx, time.perf_counter() * 0.22), 0.76), align)
            p.restore()
            y += row_h

    def draw_module_list_glow_rows(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        font = self.font("poppins_medium", 8.8)
        entries = self.module_list_entries(p, font, right_aligned=True)
        x = width - 18.0
        y = 18.0 if start_y is None else start_y
        for idx, entry in enumerate(entries):
            module = entry["module"]
            label = module.name
            row_w = max(118.0, text_width(p, font, label) + 42.0)
            row_h = 22.0 * entry["height"]
            if row_h <= 0.1:
                continue
            rect = QRectF(x - row_w + entry["slide"], y, row_w, row_h)
            p.save()
            p.setOpacity(entry["alpha"])
            glow_rect(p, rect, 7, 0.08)
            rounded_rect(p, rect, 6, color("#050506", 0.68), color("#ffffff", 0.10))
            c = accent_color(idx, time.perf_counter())
            rounded_rect(p, QRectF(rect.right() - 4, rect.top() + 3, 2, max(3, rect.height() - 6)), 1, c)
            self.draw_text(p, rect.adjusted(10, 0, -12, 0), label, font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            p.restore()
            y += row_h + 3.0 * entry["height"]

    def draw_module_list_segmented(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        font = self.font("pingfang", 8.2)
        title_font = self.font("museo", 9.6, QFont.Weight.Bold)
        entries = self.module_list_entries(p, font, right_aligned=True)
        x = width - 18.0
        y = 18.0 if start_y is None else start_y
        gap = 5.0
        header_w = 90.0
        header = QRectF(x - header_w, y, header_w, 24)
        rounded_rect(p, header, 5, color("#242424", 0.62), color("#2ab4ff", 0.25))
        self.draw_text(p, header.adjusted(9, 0, -9, 0), "POLAR", title_font, THEME.text)
        self.draw_text(p, header.adjusted(37, 0, -8, 0), "modules", font, THEME.cyan, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        y += 30
        for idx, entry in enumerate(entries):
            module = entry["module"]
            text_w = text_width(p, font, module.name)
            row_w = max(86.0, text_w + 31.0)
            row_h = 23.0 * entry["height"]
            if row_h <= 0.1:
                continue
            rect = QRectF(x - row_w + entry["slide"], y, row_w, row_h)
            p.save()
            p.setOpacity(entry["alpha"])
            rounded_rect(p, rect, 5, color("#242424", 0.50), color("#ffffff", 0.07))
            self.draw_text(p, QRectF(rect.left() + 8, rect.top(), 16, rect.height()), "*", self.font("material", 9.5), THEME.cyan, Qt.AlignmentFlag.AlignCenter)
            self.draw_text(p, rect.adjusted(25, 0, -8, 0), module.name, font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            p.restore()
            y += row_h + gap * entry["height"]

    def draw_module_list_dynamic_island(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        font = self.font("poppins_medium", 8.6)
        entries = self.module_list_entries(p, font, right_aligned=False)
        shown = entries[:5]
        if not shown:
            return
        labels = [entry["module"].name for entry in shown]
        text = "  |  ".join(labels)
        target_w = max(250.0, min(620.0, QFontMetricsF(font).horizontalAdvance(text) + 58.0))
        active = max(entry["alpha"] for entry in shown)
        y = 18.0 if start_y is None else start_y
        rect = QRectF(width / 2 - target_w / 2, y, target_w, 30)
        p.save()
        p.setOpacity(active)
        glow_rect(p, rect, 15, 0.16)
        rounded_rect(p, rect, 15, color("#050506", 0.84), color("#ffffff", 0.12))
        self.draw_text(p, QRectF(rect.left() + 18, rect.top(), 58, rect.height()), "POLAR", self.font("museo", 10, QFont.Weight.Bold), THEME.text, Qt.AlignmentFlag.AlignCenter)
        x = rect.left() + 78
        for idx, entry in enumerate(shown):
            module = entry["module"]
            label_w = text_width(p, font, module.name)
            self.draw_text(p, QRectF(x, rect.top(), label_w + 6, rect.height()), module.name, font, accent_color(idx), Qt.AlignmentFlag.AlignCenter)
            x += label_w + 24
        p.restore()

    def draw_module_list_keybind_rows(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        name_font = self.font("poppins_medium", 8.3)
        key_font = self.font("poppins_regular", 8.0)
        entries = self.module_list_entries(p, name_font, right_aligned=True)
        header_h = 24.0
        row_h_base = 21.0
        panel_w = 188.0
        x = width - panel_w - 18
        y = 18.0 if start_y is None else start_y
        rounded_rect(p, QRectF(x, y, panel_w, header_h), 5, color("#000000", 0.74), color("#ffffff", 0.10))
        self.draw_text(p, QRectF(x + 9, y, panel_w - 18, header_h), "Hotkeys", self.font("poppins_medium", 8.7), THEME.text)
        row_y = y + header_h + 3
        for idx, entry in enumerate(entries):
            module = entry["module"]
            row_h = row_h_base * entry["height"]
            if row_h <= 0.1:
                continue
            key = module.keybind if module.keybind != "None" else "ON"
            name_w = min(120.0, text_width(p, name_font, module.name) + 10.0)
            key_w = 24.0 if key == "ON" else min(42.0, max(24.0, text_width(p, key_font, key) + 10.0))
            base_x = width - 18 - name_w - 3 - key_w + entry["slide"]
            name_rect = QRectF(base_x, row_y, name_w, row_h)
            key_rect = QRectF(base_x + name_w + 3, row_y, key_w, row_h)
            p.save()
            p.setOpacity(entry["alpha"])
            rounded_rect(p, name_rect, 5, color("#000000", 0.36), color("#ffffff", 0.08))
            rounded_rect(p, key_rect, 5, color("#000000", 0.36), color("#ffffff", 0.08))
            self.draw_text(p, name_rect.adjusted(6, 0, -6, 0), module.name, name_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.draw_text(p, key_rect, key, key_font, accent_color(idx), Qt.AlignmentFlag.AlignCenter)
            p.restore()
            row_y += row_h + 3 * entry["height"]

    def draw_module_list_status_bars(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        name_font = self.font("pingfang", 8.3)
        value_font = self.font("axiforma_bold", 7.8)
        entries = self.module_list_entries(p, name_font, right_aligned=True)
        x = width - 18.0
        y = 18.0 if start_y is None else start_y
        for idx, entry in enumerate(entries):
            module = entry["module"]
            category = module.category[:3].upper()
            total_w = max(
                132.0,
                text_width(p, name_font, module.name) + text_width(p, value_font, category) + 58.0,
            )
            total_w = min(max(132.0, total_w), max(132.0, width - 36.0))
            row_h = 18.0 * entry["height"]
            if row_h <= 0.1:
                continue
            rect = QRectF(x - total_w + entry["slide"], y, total_w, row_h)
            icon_w = 21.0
            c = accent_color(idx, 0.0)
            ratio = 0.52 + (idx % 5) * 0.075
            p.save()
            p.setOpacity(entry["alpha"])
            rounded_rect(p, QRectF(rect.left() + icon_w, rect.top(), rect.width() - icon_w, row_h), 5, color("#1e1e23", 0.46), color("#ffffff", 0.06))
            rounded_rect(p, QRectF(rect.left() + icon_w, rect.top(), max(4.0, (rect.width() - icon_w) * ratio), row_h), 5, with_alpha(c, 0.42))
            rounded_rect(p, QRectF(rect.left(), rect.top(), icon_w, row_h), 5, with_alpha(c, 0.72))
            self.draw_text(p, QRectF(rect.left(), rect.top(), icon_w, row_h), str(idx + 1), value_font, THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.draw_text(p, QRectF(rect.left() + icon_w + 6, rect.top(), rect.width() - icon_w - 46, row_h), module.name, name_font, THEME.text)
            self.draw_text(p, QRectF(rect.right() - 42, rect.top(), 36, row_h), category, value_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            p.restore()
            y += row_h + 2.0 * entry["height"]

    def draw_module_list_robot_cards(self, p: QPainter, width: int, start_y: float | None = None) -> None:
        font = self.font("pingfang", 8.4)
        sub_font = self.font("poppins_regular", 7.2)
        entries = self.module_list_entries(p, font, right_aligned=True)
        x = width - 18.0
        y = 18.0 if start_y is None else start_y
        for idx, entry in enumerate(entries):
            module = entry["module"]
            row_w = max(158.0, text_width(p, font, module.name) + 86.0)
            row_h = 30.0 * entry["height"]
            if row_h <= 0.1:
                continue
            rect = QRectF(x - row_w + entry["slide"], y, row_w, row_h)
            c = accent_color(idx, time.perf_counter())
            p.save()
            p.setOpacity(entry["alpha"])
            glow_rect(p, rect, 9, 0.07)
            rounded_rect(p, rect, 8, color("#000000", 0.38), color("#ffffff", 0.08))
            badge = QRectF(rect.left() + 5, rect.top() + 5, 20, max(4.0, rect.height() - 10))
            rounded_rect(p, badge, 7, with_alpha(c, 0.60), color("#ffffff", 0.10))
            self.draw_text(p, badge, module.category[0], self.font("poppins_bold", 8.2), THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.draw_text(p, rect.adjusted(32, 3, -54, -13), module.name, font, THEME.text)
            self.draw_text(p, rect.adjusted(32, 15, -54, -2), module.category, sub_font, THEME.muted)
            chip = QRectF(rect.right() - 46, rect.top() + 6, 38, max(4.0, rect.height() - 12))
            rounded_rect(p, chip, 6, color("#ffffff", 0.05), color("#ffffff", 0.08))
            self.draw_text(p, chip, module.keybind if module.keybind != "None" else "ON", sub_font, c, Qt.AlignmentFlag.AlignCenter)
            p.restore()
            y += row_h + 5.0 * entry["height"]

    def draw_keybinds_strip(self, p: QPainter, width: int, height: int) -> None:
        rows = [m for m in self.registry.modules if m.enabled and m.keybind != "None"][:5]
        if not rows:
            return
        font = self.font("poppins_medium", 8.0)
        row_w = 136.0
        row_h = 18.0
        panel_h = 24 + len(rows) * row_h
        x = width - row_w - 18
        hud = self.registry.get("HUD")
        mode_setting = hud.get_setting("Right Display") if hud else None
        right_mode = str(mode_setting.value) if mode_setting else HUD_MODES[0]
        if right_mode == "ModuleListHud":
            y = min(height - panel_h - 62.0, max(320.0, height * 0.44))
        elif right_mode == "TacticalMapHud":
            map_rect = self.tactical_map_rect(width, height)
            if self.setting_bool(hud, "Module List", True):
                x = max(18.0, map_rect.left() - row_w - 12.0)
                y = min(height - panel_h - 20.0, max(map_rect.bottom() + 12.0, height * 0.58))
            else:
                y = min(height - panel_h - 20.0, max(map_rect.bottom() + 12.0, 78.0))
        else:
            y = max(78.0, height * 0.23)
        active = self.anim.value("hud.keybind.strip", 1.0, self.anim_duration(0.22), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        rounded_rect(p, QRectF(x, y, row_w, panel_h), 7, self.hud_surface(0.64), self.hud_panel_outline(0.09))
        self.draw_text(p, QRectF(x + 9, y + 4, row_w - 18, 14), "KeyBinds", font, THEME.text)
        for i, module in enumerate(rows):
            yy = y + 22 + i * row_h
            self.draw_text(p, QRectF(x + 9, yy, row_w - 56, row_h), module.name, font, THEME.muted)
            self.draw_text(p, QRectF(x + 65, yy, row_w - 74, row_h), module.keybind, font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.restore()

    def draw_keybinds_hud(self, p: QPainter, width: int) -> None:
        modules = [m for m in self.registry.modules if m.keybind != "None"]
        modules.sort(key=lambda module: module.name.lower())
        rect = QRectF(width - 226, 78, 202, 36 + min(11, len(modules)) * 22)
        active = self.anim.value("hud.keybinds.full", 1.0, self.anim_duration(0.26), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        glow_rect(p, rect, 8, 0.07 if self.hud_clean() else 0.18)
        rounded_rect(p, rect, 8, self.hud_surface(0.72), self.hud_panel_outline(0.09))
        self.draw_text(p, rect.adjusted(12, 7, -12, -rect.height() + 27), "KeyBinds", self.font("poppins_bold", 10), THEME.text)
        for i, module in enumerate(modules[:11]):
            y = rect.top() + 32 + i * 22
            row = QRectF(rect.left() + 8, y, rect.width() - 16, 19)
            row_active = self.anim.value(f"hud.bind.row.{module.name}", 1.0 if module.enabled else 0.42, self.anim_duration(0.18), Easings.ease_out_quad, initial=0.0)
            rounded_rect(p, row, 5, color("#ffffff", 0.035 + 0.035 * row_active))
            self.draw_text(p, row.adjusted(8, 0, -56, 0), module.name, self.font("poppins_regular", 8.2), THEME.text if module.enabled else THEME.muted)
            self.draw_text(p, row.adjusted(72, 0, -8, 0), module.keybind, self.font("poppins_medium", 8.2), self.hud_accent(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.restore()

    def draw_robot_list_hud(self, p: QPainter, width: int) -> None:
        rows = self.state.robot_rows or []
        rect = QRectF(width - 254, 78, 230, 38 + len(rows) * 27)
        active = self.anim.value("hud.robot_list", 1.0, self.anim_duration(0.26), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        glow_rect(p, rect, 8, 0.07 if self.hud_clean() else 0.18)
        rounded_rect(p, rect, 8, self.hud_surface(0.72), self.hud_panel_outline(0.09))
        self.draw_text(p, rect.adjusted(12, 8, -12, -rect.height() + 29), "RobotListHud", self.font("poppins_bold", 10), THEME.text)
        for i, row_data in enumerate(rows):
            y = rect.top() + 35 + i * 27
            row = QRectF(rect.left() + 9, y, rect.width() - 18, 22)
            rounded_rect(p, row, 5, color("#ffffff", 0.04))
            name = f"{row_data['id']} {row_data['name']}"
            hp = int(row_data["hp"])
            hp_max = max(1, int(row_data["max"]))
            self.draw_text(p, row.adjusted(7, 0, -88, 0), name, self.font("poppins_regular", 8), THEME.text)
            draw_bar(p, QRectF(row.right() - 76, row.top() + 7, 48, 5), hp / hp_max, self.hud_accent(), color("#ffffff", 0.12))
            self.draw_text(p, QRectF(row.right() - 25, row.top(), 21, row.height()), str(hp), self.font("poppins_regular", 7.5), THEME.muted, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.restore()

    def draw_status_cards_hud(self, p: QPainter, width: int) -> None:
        cards = [
            ("GIMPOWER", f"{self.state.gimbal_power}V", self.state.gimbal_power / 30.0),
            ("POWERLIM", f"{self.state.power_limit}W", self.state.power_limit / 120.0),
            ("SPEEDLIM", f"{self.state.speed_limit}dps", self.state.speed_limit / 720.0),
            ("CAP", f"{self.state.capacitor_percent}%", self.state.capacitor_percent / 100.0),
        ]
        x = width - 194
        y = 78.0
        for i, (label, value, ratio) in enumerate(cards):
            active = self.anim.value(f"hud.card.{label}", 1.0, self.anim_duration(0.25 + i * 0.02), Easings.ease_out_pow4, initial=0.0)
            rect = QRectF(x + (1.0 - active) * 30, y + i * 55, 170, 44)
            p.save()
            p.setOpacity(active)
            glow_rect(p, rect, 8, 0.05 if self.hud_clean() else 0.10)
            rounded_rect(p, rect, 8, self.hud_surface(0.72), self.hud_panel_outline(0.09))
            self.draw_text(p, rect.adjusted(12, 6, -12, -20), label, self.font("poppins_medium", 8), THEME.muted)
            self.draw_text(p, rect.adjusted(12, 15, -12, -5), value, self.font("poppins_bold", 11), THEME.text)
            draw_bar(p, QRectF(rect.left() + 82, rect.top() + 27, 72, 5), ratio, self.hud_state_color("warning" if label in ("POWERLIM", "SPEEDLIM") and ratio > 0.78 else "info", ratio), color("#ffffff", 0.12))
            p.restore()

    def draw_rm_indicators_hud(self, p: QPainter, width: int) -> None:
        indicators = [
            ("FRIC", self.state.friction_wheel),
            ("LOCK", self.state.lock_state),
            ("SMLBUFF", self.state.small_buff),
            ("LARBUFF", self.state.large_buff),
            ("ANTIRO", self.state.anti_rotation),
            ("PTE", self.state.pte_ready),
            ("JUP", self.state.jump_ready),
            ("WHE", self.state.wheel_online),
            ("LES", self.state.les_online),
        ]
        rect = QRectF(width - 244, 78, 220, 172)
        active = self.anim.value("hud.rm_indicators", 1.0, self.anim_duration(0.26), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        glow_rect(p, rect, 8, 0.06 if self.hud_clean() else 0.16)
        rounded_rect(p, rect, 8, self.hud_surface(0.72), self.hud_panel_outline(0.09))
        self.draw_text(p, rect.adjusted(12, 8, -12, -rect.height() + 29), "RMIndicatorsHud", self.font("poppins_bold", 10), THEME.text)
        chip_w = 62
        for i, (label, enabled) in enumerate(indicators):
            col = i % 3
            row = i // 3
            chip = QRectF(rect.left() + 12 + col * (chip_w + 6), rect.top() + 36 + row * 28, chip_w, 21)
            enabled_anim = self.anim.value(f"hud.ind.{label}", 1.0 if enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_quad, initial=0.0)
            fill = with_alpha(self.hud_success() if enabled else self.hud_accent(), 0.12 + 0.44 * enabled_anim)
            rounded_rect(p, chip, 6, fill, color("#ffffff", 0.08))
            self.draw_text(p, chip, label, self.font("poppins_medium", 7.3), THEME.text if enabled else THEME.muted, Qt.AlignmentFlag.AlignCenter)
        ammo = f"17mm {self.state.projectile_allowance_17mm} | 42mm {self.state.projectile_allowance_42mm}"
        self.draw_text(p, rect.adjusted(12, 134, -12, -12), ammo, self.font("poppins_regular", 8.2), THEME.muted)
        p.restore()

    def draw_target_hud_by_style(
        self,
        p: QPainter,
        target: VisionTarget,
        title: str,
        stack: HudAnchorStack,
    ) -> None:
        style = self.target_hud_style()
        if self.hud_density() == "DebugFull" or style == "FullCard":
            self.draw_target_card(p, stack.take(224.0, 82.0), target, title)
        elif style == "BarOnly":
            self.draw_target_bar_only(p, stack.take(156.0, 24.0), target)
        else:
            self.draw_target_round_compact(p, stack.take(154.0, 42.0), target)

    def draw_target_round_compact(self, p: QPainter, rect: QRectF, target: VisionTarget) -> None:
        hp_ratio = self.target_ratio(target)
        lag_ratio = self.anim.value(f"hud.target.lag.{target.kind}", hp_ratio, self.anim_duration(1.15), Easings.ease_out_pow5, initial=hp_ratio)
        main_ratio = self.anim.value(f"hud.target.main.{target.kind}", hp_ratio, self.anim_duration(0.34), Easings.ease_out_pow4, initial=hp_ratio)
        active = self.anim.value(f"hud.target.round.{target.kind}", 1.0, self.anim_duration(0.24), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, 6, surface="SubGlass")
        else:
            rounded_rect(p, rect, 6, self.hud_surface(0.52), self.hud_panel_outline(0.11))
        name = self.target_short_name(target)
        value = f"{hp_ratio * 100:.0f}%"
        self.draw_glass_text(p, QRectF(rect.left() + 8, rect.top() + 4, rect.width() - 55, 14), name, self.font("poppins_medium", 8.4), THEME.text)
        self.draw_glass_text(p, QRectF(rect.right() - 46, rect.top() + 4, 38, 14), value, self.font("poppins_medium", 8.2), self.hud_accent(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar = QRectF(rect.left() + 8, rect.top() + 23, rect.width() - 16, 4.2)
        rounded_rect(p, bar, 2.1, color("#ffffff", 0.12))
        lag = QRectF(bar)
        lag.setWidth(max(bar.height(), bar.width() * max(0.0, min(1.0, lag_ratio))))
        rounded_rect(p, lag, 2.1, color("#ffffff", 0.20))
        filled = QRectF(bar)
        filled.setWidth(max(bar.height(), bar.width() * max(0.0, min(1.0, main_ratio))))
        draw_bar(p, bar, main_ratio, self.hud_accent(), color("#ffffff", 0.0), 2.1)
        info = self.target_compact_info(target)
        self.draw_glass_text(p, QRectF(rect.left() + 8, rect.bottom() - 13, rect.width() - 16, 10), info, self.font("poppins_regular", 6.8), THEME.muted)
        p.restore()

    def draw_target_bar_only(self, p: QPainter, rect: QRectF, target: VisionTarget) -> None:
        hp_ratio = self.target_ratio(target)
        main_ratio = self.anim.value(f"hud.target.bar.{target.kind}", hp_ratio, self.anim_duration(0.28), Easings.ease_out_pow4, initial=hp_ratio)
        active = self.anim.value(f"hud.target.bar.active.{target.kind}", 1.0, self.anim_duration(0.20), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        self.draw_text(p, QRectF(rect.left(), rect.top(), rect.width(), 11), self.target_short_name(target), self.font("poppins_medium", 7.4), THEME.text)
        draw_bar(p, QRectF(rect.left(), rect.bottom() - 7, rect.width(), 4.0), main_ratio, self.hud_accent(), color("#ffffff", 0.13), 2.0)
        self.draw_text(p, QRectF(rect.right() - 42, rect.top(), 42, 11), f"{hp_ratio * 100:.0f}%", self.font("poppins_medium", 7.4), self.hud_accent(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.restore()

    def target_ratio(self, target: VisionTarget) -> float:
        if target.kind == "energy":
            return max(0.0, min(1.0, self.state.energy_rune_progress / 100.0))
        return max(0.0, min(1.0, self.state.target_health / max(1, self.state.target_max_health)))

    def target_short_name(self, target: VisionTarget) -> str:
        if target.kind == "energy":
            return f"RUNE {self.state.energy_rune_phase}"
        return f"ID {self.state.target_id}"

    def target_compact_info(self, target: VisionTarget) -> str:
        if target.kind == "energy":
            return f"{self.state.energy_target_distance_m:.1f}m | {self.state.energy_rune_rotation} | LOCK {str(self.state.energy_target_locked).upper()}"
        return f"{self.state.target_distance_m:.1f}m | LOCK {str(self.state.target_locked).upper()}"

    def draw_target_card(self, p: QPainter, rect: QRectF, target: VisionTarget, title: str) -> None:
        active = self.anim.value(f"hud.target.{title}", 1.0, self.anim_duration(0.24), Easings.ease_out_pow4, initial=0.0)
        p.save()
        p.setOpacity(active)
        glow_rect(p, rect, 9, 0.07 if self.hud_clean() else 0.18)
        rounded_rect(p, rect, 8, self.hud_surface(0.76), self.hud_panel_outline(0.10))
        self.draw_text(p, rect.adjusted(13, 9, -13, -54), title, self.font("poppins_bold", 10), THEME.text)
        if target.kind == "energy":
            ratio = self.state.energy_rune_progress / 100.0
            draw_bar(p, QRectF(rect.left() + 13, rect.top() + 43, rect.width() - 26, 7), ratio, self.hud_accent(), color("#ffffff", 0.14))
            info = f"{self.state.energy_rune_phase} | {self.state.energy_target_distance_m:.1f}m | {self.state.energy_rune_rotation} | LOCK {str(self.state.energy_target_locked).upper()}"
            value = f"{self.state.energy_rune_progress}%"
        else:
            hp_ratio = self.state.target_health / max(1, self.state.target_max_health)
            draw_bar(p, QRectF(rect.left() + 13, rect.top() + 43, rect.width() - 26, 7), hp_ratio, self.hud_accent(), color("#ffffff", 0.14))
            info = f"ID {self.state.target_id} | {self.state.target_distance_m:.1f}m | LOCK {str(self.state.target_locked).upper()}"
            value = f"{target.confidence:.0%}"
        self.draw_text(p, rect.adjusted(13, 56, -13, -8), info, self.font("poppins_regular", 8.2), THEME.muted)
        self.draw_text(p, QRectF(rect.right() - 73, rect.top() + 10, 58, 18), value, self.font("poppins_medium", 9), self.hud_accent(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.restore()

    def build_gpu_module_list(
        self,
        entries: list[dict[str, Any]],
        layout: ModuleListLayout,
        hud_scale: float,
        width: int,
        height: int,
        style: str,
    ) -> ClickGuiDrawList:
        """Emit the compact right-side ModuleList as one GPU draw list.

        The old high-resolution fallback used this same compact density, but
        still paid a QPainter round-rect/text pass for every row. Keeping the
        geometry in logical HUD pixels makes the list stable under HUD Scale and
        lets the renderer apply DPR only once at submission time.
        """
        commands = ClickGuiDrawList()
        scale = max(0.55, min(2.0, float(hud_scale)))
        base_font = self.font("pingfang", 8.3)
        category_font = self.font("poppins_bold", 6.1)
        gpu_font = self.font("pingfang", 8.3 * scale)
        gpu_category_font = self.font("poppins_bold", 6.1 * scale)
        gpu_index_font = self.font("axiforma_bold", 7.8 * scale)
        metrics = QFontMetricsF(base_font)
        category_metrics = QFontMetricsF(category_font)
        clip = QRectF(
            layout.clip_rect.left() * scale,
            layout.clip_rect.top() * scale,
            layout.clip_rect.width() * scale,
            layout.clip_rect.height() * scale,
        )
        y = layout.anchor_y
        max_rows = max(1, int(layout.available_height / max(1.0, layout.row_height + layout.row_gap)) + 2)
        for index, entry in enumerate(entries[:max_rows]):
            module = entry["module"]
            row_h = 17.0 * float(entry["height"])
            if row_h <= 0.1:
                continue
            category = module.category[:3].upper()
            row_w = max(
                132.0,
                metrics.horizontalAdvance(module.name) + category_metrics.horizontalAdvance(category) + 58.0,
            )
            row_w = min(max(132.0, row_w), max(132.0, width - 36.0))
            rect = QRectF(
                (layout.anchor_x - row_w + float(entry["slide"])) * scale,
                y * scale,
                row_w * scale,
                row_h * scale,
            )
            alpha = max(0.0, min(1.0, float(entry["alpha"])))
            accent = accent_color(index, 0.0)
            icon_w = 21.0 * scale
            body = QRectF(rect.left() + icon_w, rect.top(), rect.width() - icon_w, rect.height())
            commands.rect(
                body,
                5.0 * scale,
                color("#090c12", 0.72 * alpha),
                color("#ffffff", 0.09 * alpha),
                0.8 * scale,
                clip=clip,
            )
            fill_ratio = 0.52 + (index % 5) * 0.075
            commands.rect(
                QRectF(body.left(), body.top(), max(4.0, body.width() * fill_ratio), body.height()),
                5.0 * scale,
                with_alpha(accent, 0.24 * alpha),
                clip=clip,
            )
            badge = QRectF(rect.left(), rect.top(), icon_w, rect.height())
            commands.rect(badge, 5.0 * scale, with_alpha(accent, 0.62 * alpha), color("#ffffff", 0.08 * alpha), 0.6 * scale, clip=clip)
            commands.text(badge, str(index + 1), gpu_index_font, color("#ffffff", alpha), Qt.AlignmentFlag.AlignCenter, clip)
            commands.text(
                QRectF(body.left() + 6.0 * scale, rect.top(), max(2.0, body.width() - 49.0 * scale), rect.height()),
                module.name,
                gpu_font,
                color("#ffffff", alpha),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                clip,
            )
            commands.text(
                QRectF(rect.right() - 42.0 * scale, rect.top(), 36.0 * scale, rect.height()),
                category,
                gpu_category_font,
                color("#ffffff", 0.88 * alpha),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                clip,
            )
            y += row_h + 3.0 * float(entry["height"])
            if y > layout.clip_rect.bottom() + 24.0:
                break
        return commands

    def build_gpu_clickgui(self, width: int, height: int, alpha: float) -> ClickGuiDrawList:
        started = time.perf_counter()
        commands = ClickGuiDrawList()
        self.gui_scroll_viewports = []
        mode = self.mode_manager.mode
        if mode == "PolarPanel":
            self.build_gpu_panel_gui(commands, width, height, alpha)
        elif mode == "PolarOld":
            self.build_gpu_old_gui(commands, width, height, alpha)
        elif mode == "PolarNew":
            self.build_gpu_new_gui(commands, width, height, alpha)
        elif mode == "PolarDropdown":
            self.build_gpu_dropdown_gui(commands, width, height, alpha)
        elif mode == "PolarUnified":
            self.build_gpu_polar_unified(commands, width, height, alpha)
        else:
            self.build_gpu_polar_multi(commands, width, height, alpha)
        self.build_gpu_mode_switcher(commands, width, height)
        self.build_gpu_toasts(commands, width, height)
        if self.hover_tooltip:
            self.build_gpu_tooltip(commands, self.hover_point, self.hover_tooltip)
        if self.binding_module is not None:
            self.build_gpu_keybind_overlay(commands, width, height)
        self.clickgui_gpu_layout_ms = (time.perf_counter() - started) * 1000.0
        return commands

    def build_gpu_startup_launcher(
        self,
        width: int,
        height: int,
        *,
        page: str | None = None,
        visual_alpha: float = 1.0,
        settled: bool = False,
    ) -> ClickGuiDrawList:
        """Build the Liquid launcher with GPU rectangles and glyph-atlas text."""
        selected_page = page or self.startup_step
        if selected_page == "robot":
            return self.build_gpu_robot_profile_launcher(width, height, visual_alpha)
        commands = ClickGuiDrawList()
        scale = max(0.74, min(1.14, self.get_auto_ui_scale(width, height, strength=0.45)))
        active = (
            1.0
            if settled
            else self.anim.value(
                "startup.gpu.open",
                1.0,
                self.anim_duration(0.34),
                Easings.ease_out_pow4,
                initial=0.0,
            )
        ) * max(0.0, min(1.0, visual_alpha))
        menu_x, menu_y, button_w, button_h, gap = self.liquid_menu_layout(width, height, 3, scale)
        is_match = selected_page == "match"
        title = "MATCH MODE" if is_match else "SCENE SELECT"
        subtitle = (
            f"{self.startup_scenario_meta(self.scenario_manager.current.key)['title']} profile"
            if is_match
            else "Choose runtime environment"
        )
        header_y = 42.0 * scale
        commands.text(QRectF(50.0 * scale, header_y - 20.0 * scale, 330.0 * scale, 32.0 * scale), "POLAR-RM", self.font("museo", 28.0 * scale, QFont.Weight.Bold), self.gpu_alpha(THEME.text, active))
        commands.text(QRectF(50.0 * scale, header_y + 10.0 * scale, 330.0 * scale, 18.0 * scale), "CUSTOM CLIENT", self.font("poppins_medium", 8.5 * scale), self.gpu_alpha(THEME.muted, active))
        notice_w = min(420.0 * scale, width * 0.36)
        notice = QRectF(width / 2.0 - notice_w / 2.0, 28.0 * scale, notice_w, 40.0 * scale)
        self.build_gpu_glass_rect(commands, notice, 15.0 * scale, active, THEME.cyan)
        commands.text(notice.adjusted(18.0 * scale, 4.0 * scale, -18.0 * scale, -19.0 * scale), title, self.font("poppins_bold", 9.0 * scale), self.gpu_alpha(THEME.text, active), Qt.AlignmentFlag.AlignCenter)
        commands.text(notice.adjusted(18.0 * scale, 19.0 * scale, -18.0 * scale, -4.0 * scale), subtitle, self.font("poppins_regular", 7.0 * scale), self.gpu_alpha(THEME.muted, active), Qt.AlignmentFlag.AlignCenter)
        profile_w = min(230.0 * scale, width * 0.22)
        profile = QRectF(width - profile_w - 50.0 * scale, 34.0 * scale, profile_w, 28.0 * scale)
        self.build_gpu_glass_rect(commands, profile, 10.0 * scale, active, THEME.cyan)
        commands.text(profile.adjusted(12.0 * scale, 0, -12.0 * scale, 0), f"PROFILE  {self.current_profile()}", self.font("poppins_medium", 7.2 * scale), self.gpu_alpha(color("#d8e5ec", 0.92), active), Qt.AlignmentFlag.AlignCenter)

        if is_match:
            entries = []
            for index, key in enumerate(MATCH_MODE_KEYS):
                config = MATCH_MODES[key]
                meta = self.startup_match_meta(key)
                entries.append((key, meta["icon"], meta["title"], meta["subtitle"], f"{config.field.width_m:g}m x {config.field.height_m:g}m  {config.duration_sec // 60}:{config.duration_sec % 60:02d}", "NEXT", "select_match_mode", key, meta["tooltip"], self.startup_menu_accent(index + 2)))
            entries.append(("back", "back", "Back", "Return to scene select", "Backspace also works", "BACK", "startup_back", None, "Return to scene selection.", color("#ec5ad9")))
        else:
            entries = []
            for index, key in enumerate(("OfficialEvent", "CampusSimulation", "LabDebug")):
                config = SCENARIOS[key]
                meta = self.startup_scenario_meta(key)
                entries.append((key, meta["icon"], meta["title"], meta["subtitle"], f"MQTT {config.connection.mqtt_host}:{config.connection.mqtt_port}  UDP {config.connection.udp_port}", "LIVE" if not config.safety.mock_writes else "MOCK", "select_scenario", key, meta["tooltip"], self.startup_menu_accent(index)))
        for index, entry in enumerate(entries):
            self.build_gpu_startup_button(commands, QRectF(menu_x, menu_y + index * (button_h + gap), button_w, button_h), index, entry, scale, active, settled=settled)
        self.build_gpu_startup_session(commands, menu_x, menu_y, button_w, height, scale, active, is_match)
        self.build_gpu_startup_bottom_bar(commands, width, height, scale, active, is_match, settled=settled)
        return commands

    def build_gpu_robot_profile_launcher(self, width: int, height: int, visual_alpha: float = 1.0) -> ClickGuiDrawList:
        commands = ClickGuiDrawList()
        scale = max(0.72, min(1.12, self.get_auto_ui_scale(width, height, strength=0.42)))
        active = self.anim.value(
            "startup.robot.open", 1.0, self.anim_duration(0.32), Easings.ease_out_pow4, initial=0.0
        ) * max(0.0, min(1.0, visual_alpha))
        profiles = profiles_for_match(self.match_mode_manager.current.key)
        selected_key = self.current_robot_profile_key()

        commands.text(QRectF(50 * scale, 28 * scale, 340 * scale, 38 * scale), "POLAR-RM", self.font("museo", 28 * scale, QFont.Weight.Bold), self.gpu_alpha(THEME.text, active))
        island_w = min(470 * scale, width * 0.42)
        island = QRectF(width / 2 - island_w / 2, 27 * scale, island_w, 44 * scale)
        self.build_gpu_glass_rect(commands, island, 17 * scale, active, THEME.cyan)
        commands.text(island.adjusted(16 * scale, 3 * scale, -16 * scale, -21 * scale), "ROBOT PROFILE", self.font("poppins_bold", 9 * scale), self.gpu_alpha(THEME.text, active), Qt.AlignmentFlag.AlignCenter)
        commands.text(island.adjusted(16 * scale, 22 * scale, -16 * scale, -3 * scale), f"{self.match_mode_manager.current.title} · Step 3/3", self.font("poppins_regular", 7 * scale), self.gpu_alpha(THEME.muted, active), Qt.AlignmentFlag.AlignCenter)

        margin = 46 * scale
        top = 112 * scale
        bottom = 74 * scale
        detail_w = min(330 * scale, width * 0.27)
        gap = 14 * scale
        grid_left = margin
        grid_right = width - margin - detail_w - 24 * scale
        grid_w = max(420 * scale, grid_right - grid_left)
        columns = 4 if grid_w >= 880 * scale else 3
        rows = max(1, math.ceil(len(profiles) / columns))
        card_w = (grid_w - gap * (columns - 1)) / columns
        card_h = min(138 * scale, (height - top - bottom - gap * (rows - 1)) / rows)

        for index, profile in enumerate(profiles):
            column = index % columns
            row = index // columns
            rect = QRectF(grid_left + column * (card_w + gap), top + row * (card_h + gap), card_w, card_h)
            hovered = rect.contains(self.hover_point)
            selected = profile.key == selected_key
            hover = self.anim.value(f"startup.robot.hover.{profile.key}", 1.0 if hovered else 0.0, self.anim_duration(0.15), Easings.ease_out_expo)
            enter = self.startup_stagger_value(index, 0.34, 0.045)
            rect.translate(0, (1.0 - enter) * 22 * scale - hover * 3 * scale)
            opacity = active * enter
            accent = self.startup_menu_accent(index + 1)
            self.build_gpu_glass_rect(
                commands,
                rect,
                12 * scale,
                opacity,
                accent,
                hover=max(hover, 0.45 if selected else 0.0),
                material=LensMaterial.STRONG,
                refraction_height_px=rect.height() * 0.375,
                refraction_amount_px=rect.height() * 0.50,
            )
            if selected:
                commands.rect(QRectF(rect.left(), rect.top(), 3 * scale, rect.height()), 1.5 * scale, self.gpu_alpha(accent, opacity))
            icon = QRectF(rect.left() + 13 * scale, rect.top() + 14 * scale, 42 * scale, 42 * scale)
            commands.rect(icon, 14 * scale, self.gpu_alpha(with_alpha(accent, 0.74), opacity), self.gpu_alpha(color("#ffffff", 0.26), opacity), 0.8)
            commands.text(icon, profile.icon, self.font("poppins_bold", 15 * scale), self.gpu_alpha(THEME.text, opacity), Qt.AlignmentFlag.AlignCenter)
            commands.text(QRectF(icon.right() + 11 * scale, rect.top() + 14 * scale, rect.right() - icon.right() - 20 * scale, 23 * scale), profile.short_title, self.font("poppins_bold", 10 * scale), self.gpu_alpha(THEME.text, opacity))
            commands.text(QRectF(icon.right() + 11 * scale, rect.top() + 38 * scale, rect.right() - icon.right() - 20 * scale, 17 * scale), f"ID {profile.robot_id}", self.font("poppins_medium", 6.8 * scale), self.gpu_alpha(accent, opacity))
            commands.text(rect.adjusted(13 * scale, 67 * scale, -13 * scale, -12 * scale), profile.description, self.font("poppins_regular", 7.1 * scale), self.gpu_alpha(color("#dce6ec", 0.86), opacity), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.add_hotspot(rect, "select_robot_profile", profile.key, tooltip=f"选择{profile.title}并进入战斗 HUD")

        profile = profile_by_key(self.match_mode_manager.current.key, selected_key)
        performance = self.current_robot_performance(selected_key)
        panel = QRectF(width - margin - detail_w, top, detail_w, min(390 * scale, height - top - bottom))
        self.build_gpu_glass_rect(
            commands,
            panel,
            14 * scale,
            active,
            THEME.cyan,
            material=LensMaterial.REGULAR,
            refraction_height_px=min(18.0 * scale, panel.height() * 0.12),
            refraction_amount_px=min(24.0 * scale, panel.height() * 0.16),
        )
        commands.text(panel.adjusted(20 * scale, 18 * scale, -20 * scale, -panel.height() + 48 * scale), profile.title, self.font("poppins_bold", 15 * scale), self.gpu_alpha(THEME.text, active))
        commands.text(panel.adjusted(20 * scale, 49 * scale, -20 * scale, -panel.height() + 70 * scale), f"Robot ID {profile.robot_id} · {profile.short_title}", self.font("poppins_medium", 7.4 * scale), self.gpu_alpha(THEME.cyan, active))
        metrics = [
            ("MAX HP", str(performance.max_health) if performance.max_health else "N/A"),
            ("POWER", f"{performance.power_limit_w} W" if performance.power_limit_w else "N/A"),
            ("HEAT", str(performance.heat_limit) if performance.heat_limit else "N/A"),
            ("COOLING", f"{performance.cooling_rate}/s" if performance.cooling_rate else "N/A"),
            ("PROJECTILE", performance.projectile),
        ]
        y = panel.top() + 88 * scale
        for index, (label, value) in enumerate(metrics):
            row = QRectF(panel.left() + 16 * scale, y + index * 43 * scale, panel.width() - 32 * scale, 32 * scale)
            commands.rect(row, 8 * scale, color("#e8f5ff", 0.075 * active), color("#ffffff", 0.12 * active), 0.7)
            commands.text(row.adjusted(11 * scale, 0, -100 * scale, 0), label, self.font("poppins_bold", 6.8 * scale), self.gpu_alpha(THEME.muted, active), Qt.AlignmentFlag.AlignVCenter)
            commands.text(row.adjusted(100 * scale, 0, -11 * scale, 0), value, self.font("poppins_medium", 8.5 * scale), self.gpu_alpha(THEME.text, active), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        back = QRectF(margin, height - 53 * scale, 106 * scale, 34 * scale)
        self.build_gpu_glass_rect(
            commands,
            back,
            back.height() / 2.0,
            active,
            color("#ffffff", 0.68),
            material=LensMaterial.STRONG,
            refraction_height_px=back.height() * 0.375,
            refraction_amount_px=back.height() * 0.50,
        )
        commands.text(back, "<  BACK", self.font("poppins_bold", 7.5 * scale), self.gpu_alpha(THEME.text, active), Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(back, "startup_back_match", None, tooltip="返回比赛模式选择")
        return commands

    def current_robot_profile_key(self) -> str:
        module = self.registry.get("RobotProfile")
        setting = module.get_setting("Role") if module else None
        valid = {profile.key for profile in profiles_for_match(self.match_mode_manager.current.key)}
        value = str(setting.value) if setting else "Infantry1"
        return value if value in valid else profiles_for_match(self.match_mode_manager.current.key)[0].key

    def current_robot_performance(self, role: str | None = None):
        module = self.registry.get("RobotProfile")
        return resolve_performance(
            self.match_mode_manager.current.key,
            role or self.current_robot_profile_key(),
            level=int(self.get_setting_number(module, "Level", 1)),
            hero_type=self.setting_mode(module, "Hero Type", "Melee"),
            infantry_chassis=self.setting_mode(module, "Infantry Chassis", "Power"),
            infantry_shooter=self.setting_mode(module, "Infantry Shooter", "Burst"),
            sentinel_control=self.setting_mode(module, "Sentinel Control", "Automatic"),
        )

    def build_gpu_glass_rect(
        self,
        commands: ClickGuiDrawList,
        rect: QRectF,
        radius: float,
        alpha: float,
        accent: QColor,
        *,
        hover: float = 0.0,
        material: LensMaterial | None = None,
        refraction_height_px: float | None = None,
        refraction_amount_px: float | None = None,
    ) -> None:
        """提交 Combined Backdrop 镜片，材质由用途显式决定。"""
        if self._gpu_frame_recording:
            island_shape = radius >= rect.height() * 0.44
            surface = "clear" if island_shape else "sub" if rect.height() <= 48.0 else "main"
            lens_material = material or (LensMaterial.ISLAND if island_shape else LensMaterial.REGULAR)
            self.gpu_compositor.add_glass(
                rect,
                radius,
                strength=0.92 + hover * 0.18,
                surface=surface,
                hover=hover,
                opacity=alpha,
                material=lens_material,
                refraction_height_px=refraction_height_px,
                refraction_amount_px=refraction_amount_px,
            )

    def build_gpu_startup_button(self, commands: ClickGuiDrawList, rect: QRectF, index: int, entry: tuple, scale: float, active: float, *, settled: bool = False) -> None:
        key, icon, title, subtitle, detail, chip_text, action, payload, tooltip, accent = entry
        enter = 1.0 if settled else self.startup_stagger_value(index, 0.42, 0.10)
        hovered = rect.contains(self.hover_point)
        hover = 0.0 if settled else self.anim.value(f"startup.gpu.hover.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.16), Easings.ease_out_expo)
        draw_rect = QRectF(rect)
        draw_rect.translate(0.0, 10.0 * (1.0 - enter) * scale - 3.0 * hover * scale)
        opacity = active * max(0.0, min(1.0, enter))
        self.build_gpu_glass_rect(
            commands,
            draw_rect,
            18.0 * scale,
            opacity,
            accent,
            hover=hover,
            material=LensMaterial.STRONG,
            refraction_height_px=draw_rect.height() * 0.375,
            refraction_amount_px=draw_rect.height() * 0.50,
        )
        commands.rect(QRectF(draw_rect.left(), draw_rect.top(), 4.0 * scale, draw_rect.height()), 2.0 * scale, self.gpu_alpha(with_alpha(accent, 0.90), opacity))
        commands.rect(
            QRectF(draw_rect.left() + 4.0 * scale, draw_rect.top(), 8.0 * scale, draw_rect.height()),
            8.0 * scale,
            color("#000000", 0.0),
            color("#000000", 0.0),
            0.0,
                self.gpu_alpha(with_alpha(accent, 0.10 + hover * 0.08), opacity),
        )
        icon_size = min(90.0 * scale, draw_rect.height() - 28.0 * scale)
        icon_rect = QRectF(draw_rect.left() + 26.0 * scale, draw_rect.center().y() - icon_size / 2.0, icon_size, icon_size)
        icon_fill = self.mix_color(accent, THEME.text, hover)
        icon_text = self.mix_color(THEME.text, accent, hover)
        commands.rect(icon_rect.adjusted(-4.0 * scale, -4.0 * scale, 4.0 * scale, 4.0 * scale), icon_size * 0.54, self.gpu_alpha(with_alpha(accent, 0.10 + hover * 0.10), opacity), self.gpu_alpha(with_alpha(accent, 0.38 + hover * 0.30), opacity), 1.0)
        commands.rect(icon_rect, icon_size * 0.50, self.gpu_alpha(with_alpha(icon_fill, 0.92), opacity), self.gpu_alpha(color("#ffffff", 0.16 + hover * 0.15), opacity), 1.0)
        icon_glyph = {"official": "\ue9e0", "sim": "\ue9f4", "lab": "\uea4b", "rmuc": "7", "rmul": "3", "back": "<"}.get(str(icon).lower(), str(icon)[:1].upper())
        commands.text(icon_rect, icon_glyph, self.font("material" if len(icon_glyph) == 1 and ord(icon_glyph) >= 0xE000 else "poppins_bold", min(25.0 * scale, icon_size * 0.42), QFont.Weight.Bold), self.gpu_alpha(icon_text, opacity), Qt.AlignmentFlag.AlignCenter)
        text_left = icon_rect.right() + 24.0 * scale
        title_rect = QRectF(text_left, draw_rect.top() + 21.0 * scale, draw_rect.width() - (text_left - draw_rect.left()) - 126.0 * scale, 28.0 * scale)
        commands.text(title_rect, title, self.font("poppins_bold", 18.0 * scale), self.gpu_alpha(THEME.text, opacity))
        commands.text(QRectF(text_left, draw_rect.top() + 50.0 * scale, draw_rect.width() - (text_left - draw_rect.left()) - 42.0 * scale, 20.0 * scale), subtitle, self.font("poppins_regular", 9.0 * scale), self.gpu_alpha(color("#e1e8ee", 0.88), opacity))
        commands.text(QRectF(text_left, draw_rect.bottom() - 31.0 * scale, draw_rect.width() - (text_left - draw_rect.left()) - 42.0 * scale, 18.0 * scale), detail, self.font("poppins_regular", 7.3 * scale), self.gpu_alpha(color("#aeb7bd", 0.90), opacity))
        shortcut = QRectF(draw_rect.right() - 78.0 * scale, draw_rect.top() + 20.0 * scale, 26.0 * scale, 22.0 * scale)
        commands.rect(shortcut, 6.0 * scale, self.gpu_alpha(color("#ffffff", 0.08), opacity), self.gpu_alpha(color("#ffffff", 0.16), opacity), 0.7)
        commands.text(shortcut, str(index + 1) if action != "startup_back" else "B", self.font("poppins_bold", 7.3 * scale), self.gpu_alpha(icon_text if hover > 0.55 else accent, opacity), Qt.AlignmentFlag.AlignCenter)
        chip = QRectF(draw_rect.right() - 98.0 * scale - 26.0 * scale, draw_rect.bottom() - 34.0 * scale, 98.0 * scale, 22.0 * scale)
        commands.rect(chip, 7.0 * scale, self.gpu_alpha(color("#ffffff", 0.07 + hover * 0.04), opacity), self.gpu_alpha(with_alpha(accent, 0.30 + hover * 0.20), opacity), 0.7)
        commands.text(chip, chip_text, self.font("poppins_medium", 7.2 * scale), self.gpu_alpha(icon_text if hover > 0.72 else accent, opacity), Qt.AlignmentFlag.AlignCenter)
        commands.text(QRectF(draw_rect.right() - 43.0 * scale, draw_rect.center().y() - 13.0 * scale, 18.0 * scale, 26.0 * scale), ">", self.font("poppins_bold", 15.0 * scale), self.gpu_alpha(THEME.text if hovered else THEME.muted, opacity), Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(draw_rect.adjusted(-3.0 * scale, -3.0 * scale, 3.0 * scale, 3.0 * scale), action, payload, tooltip=tooltip)

    def build_gpu_startup_session(self, commands: ClickGuiDrawList, menu_x: float, menu_y: float, button_w: float, height: int, scale: float, active: float, is_match: bool) -> None:
        right_x = menu_x + button_w + 48.0 * scale
        right_w = self.width() - right_x - 50.0 * scale
        if right_w < 245.0 * scale:
            return
        panel = QRectF(right_x, menu_y + 4.0 * scale, min(390.0 * scale, right_w), min(300.0 * scale, height - menu_y - 108.0 * scale))
        self.build_gpu_glass_rect(
            commands,
            panel,
            18.0 * scale,
            active,
            THEME.cyan,
            material=LensMaterial.REGULAR,
            refraction_height_px=min(18.0 * scale, panel.height() * 0.12),
            refraction_amount_px=min(24.0 * scale, panel.height() * 0.16),
        )
        commands.rect(QRectF(panel.left() + 14.0 * scale, panel.top() + 12.0 * scale, panel.width() - 28.0 * scale, 2.0 * scale), 1.0, self.gpu_alpha(THEME.cyan, active), None, 0.0, self.gpu_alpha(color("#ffffff", 0.24), active))
        commands.text(QRectF(panel.left() + 18.0 * scale, panel.top() + 26.0 * scale, panel.width() - 36.0 * scale, 23.0 * scale), "SESSION", self.font("poppins_bold", 11.0 * scale), self.gpu_alpha(THEME.text, active))
        scenario = self.startup_scenario_meta(self.scenario_manager.current.key)
        match = self.startup_match_meta(self.match_mode_manager.current.key)
        rows = [("ENV", scenario["title"]), ("MATCH", match["title"]), ("CONFIG", self.current_profile()), ("MQTT", "mock" if not self.mqtt.connected else "live"), ("SERIAL", "mock" if not self.serial.connected else "live")]
        row_y = panel.top() + 62.0 * scale
        for index, (label, value) in enumerate(rows):
            accent = accent_color(index, 0.08)
            row = QRectF(panel.left() + 18.0 * scale, row_y + index * 34.0 * scale, panel.width() - 36.0 * scale, 24.0 * scale)
            # SESSION 只有外层是镜片；状态行属于普通内容层，避免玻璃套玻璃。
            commands.rect(
                row,
                6.0 * scale,
                self.gpu_alpha(color("#ffffff", 0.045), active),
                self.gpu_alpha(color("#ffffff", 0.10), active),
                0.65,
            )
            commands.text(QRectF(row.left() + 10.0 * scale, row.top(), 58.0 * scale, row.height()), label, self.font("poppins_bold", 7.0 * scale), self.gpu_alpha(accent, active), Qt.AlignmentFlag.AlignVCenter)
            commands.text(row.adjusted(72.0 * scale, 0, -10.0 * scale, 0), value, self.font("poppins_medium", 8.1 * scale), self.gpu_alpha(color("#dce7ed", 0.92), active), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        tip = QRectF(panel.left() + 18.0 * scale, panel.bottom() - 56.0 * scale, panel.width() - 36.0 * scale, 37.0 * scale)
        commands.rect(
            tip,
            10.0 * scale,
            self.gpu_alpha(color("#ffffff", 0.035), active),
            self.gpu_alpha(color("#ffffff", 0.10), active),
            0.65,
        )
        commands.text(tip.adjusted(12.0 * scale, 0, -12.0 * scale, 0), "Press 1/2 to load. Backspace returns." if is_match else "Press 1/2/3 to select. Enter continues.", self.font("poppins_regular", 7.2 * scale), self.gpu_alpha(THEME.muted, active), Qt.AlignmentFlag.AlignCenter)

    def build_gpu_startup_bottom_bar(self, commands: ClickGuiDrawList, width: int, height: int, scale: float, active: float, is_match: bool, *, settled: bool = False) -> None:
        actions = [("Config", "startup_open_config", None, THEME.cyan), ("Import", "config_action", "Import Config", THEME.pink), ("Wallpaper", "startup_open_wallpaper", None, color("#4677ff")), ("ClickGUI", "startup_open_gui", None, color("#a98aff")), ("Exit", "startup_exit", None, color("#ff6464"))]
        if is_match:
            actions.insert(0, ("Back", "startup_back", None, color("#ffd766")))
        button_h, gap, button_w = 42.0 * scale, 10.0 * scale, 82.0 * scale
        total_w = len(actions) * button_w + max(0, len(actions) - 1) * gap + 28.0 * scale
        bar = QRectF(50.0 * scale, height - 64.0 * scale, min(total_w, width - 100.0 * scale), button_h + 18.0 * scale)
        self.build_gpu_glass_rect(commands, bar, 8.0 * scale, active, THEME.cyan)
        x = bar.left() + 14.0 * scale
        for label, action, payload, accent in actions:
            rect = QRectF(x, bar.top() + 9.0 * scale, button_w, button_h)
            hovered = rect.contains(self.hover_point)
            hover = 0.0 if settled else self.anim.value(f"startup.gpu.bottom.{label}", 1.0 if hovered else 0.0, self.anim_duration(0.16), Easings.ease_out_expo)
            commands.rect(rect, 6.0 * scale, self.gpu_alpha(with_alpha(accent, 0.08 + hover * 0.12), active), self.gpu_alpha(with_alpha(accent, 0.20 + hover * 0.25), active), 0.8)
            commands.text(rect, label, self.font("poppins_medium", 8.2 * scale), self.gpu_alpha(THEME.text, active), Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(rect, action, payload, tooltip=label)
            x += button_w + gap

    def build_gpu_startup_hover_layer(self, width: int, height: int) -> ClickGuiDrawList:
        """稳定页只绘制 hover 折射层，避免鼠标移动重建所有文字与图标。"""
        commands = ClickGuiDrawList()
        if self.startup_step == "robot":
            return commands
        scale = max(0.74, min(1.14, self.get_auto_ui_scale(width, height, strength=0.45)))
        menu_x, menu_y, button_w, button_h, gap = self.liquid_menu_layout(width, height, 3, scale)
        is_match = self.startup_step == "match"
        if is_match:
            entries = [
                (key, self.startup_menu_accent(index + 2))
                for index, key in enumerate((*MATCH_MODE_KEYS, "back"))
            ]
        else:
            entries = [
                (key, self.startup_menu_accent(index))
                for index, key in enumerate(("OfficialEvent", "CampusSimulation", "LabDebug"))
            ]
        for index, (key, accent) in enumerate(entries):
            rect = QRectF(menu_x, menu_y + index * (button_h + gap), button_w, button_h)
            hovered = rect.contains(self.hover_point)
            hover = self.anim.value(f"startup.gpu.hover.{key}", 1.0 if hovered else 0.0, self.anim_duration(0.16), Easings.ease_out_expo)
            if hover <= 0.002:
                continue
            lift = 4.0 * hover * scale
            overlay = QRectF(rect)
            overlay.translate(0.0, -lift)
            self.build_gpu_glass_rect(commands, overlay, 5.0 * scale, 0.24 * hover, accent, hover=hover)
            commands.rect(
                overlay,
                5.0 * scale,
                color("#000000", 0.0),
                None,
                0.0,
                self.gpu_alpha(with_alpha(accent, 0.055), hover),
            )
            commands.rect(
                QRectF(overlay.left(), overlay.top(), 3.0 * scale, overlay.height()),
                1.5 * scale,
                self.gpu_alpha(with_alpha(accent, 0.96), hover),
            )

        actions = [("Config", THEME.cyan), ("Import", THEME.pink), ("Wallpaper", color("#4677ff")), ("ClickGUI", color("#a98aff")), ("Exit", color("#ff6464"))]
        if is_match:
            actions.insert(0, ("Back", color("#ffd766")))
        button_h, action_gap, action_w = 42.0 * scale, 10.0 * scale, 82.0 * scale
        total_w = len(actions) * action_w + max(0, len(actions) - 1) * action_gap + 28.0 * scale
        bar = QRectF(50.0 * scale, height - 64.0 * scale, min(total_w, width - 100.0 * scale), button_h + 18.0 * scale)
        x = bar.left() + 14.0 * scale
        for label, accent in actions:
            rect = QRectF(x, bar.top() + 9.0 * scale, action_w, button_h)
            hover = self.anim.value(f"startup.gpu.bottom.{label}", 1.0 if rect.contains(self.hover_point) else 0.0, self.anim_duration(0.16), Easings.ease_out_expo)
            if hover > 0.002:
                commands.rect(rect, 6.0 * scale, self.gpu_alpha(with_alpha(accent, 0.12), hover), self.gpu_alpha(with_alpha(accent, 0.44), hover), 0.8)
            x += action_w + action_gap
        return commands

    def gpu_alpha(self, source: QColor, alpha: float) -> QColor:
        return with_alpha(source, alpha)

    def build_gpu_panel_gui(self, commands: ClickGuiDrawList, width: int, height: int, alpha: float) -> None:
        scale = self.get_gui_scale_for_bounds(width, height, 600.0, 440.0, 76.0, 82.0) * (0.98 + 0.02 * alpha)
        panel = QRectF(width / 2 - 300 * scale, height / 2 - 200 * scale, 600 * scale, 400 * scale)
        commands.rect(panel, 8 * scale, color("#101014", 0.96 * alpha), color("#ffffff", 0.13 * alpha), 1.0)
        # Match draw_profile_widget: title + Chinese profile/scale subtitle.
        commands.text(QRectF(panel.left() + 14 * scale, panel.top() + 10 * scale, 200 * scale, 18 * scale), "POLAR-RM", self.font("poppins_bold", 14 * scale), self.gpu_alpha(THEME.text, alpha))
        commands.text(
            QRectF(panel.left() + 14 * scale, panel.top() + 28 * scale, 220 * scale, 14 * scale),
            f"配置 {self.current_profile()} | 缩放 {self.get_gui_scale():.2f}",
            self.font("poppins_regular", 7.6 * scale),
            self.gpu_alpha(THEME.muted, alpha),
        )
        category_bar = QRectF(panel.left() + 414 * scale, panel.top() + 18 * scale, 166 * scale, 28 * scale)
        step = category_bar.width() / len(CATEGORIES)
        target = float(CATEGORIES.index(self.selected_category)) if self.selected_category in CATEGORIES else 0.0
        current = self.gui_motion.value("gpu.panel.category", target, self.anim_duration(0.22), Easings.ease_out_expo, initial=target)
        commands.rect(QRectF(category_bar.left() + current * step + 2 * scale, category_bar.top() + 2 * scale, step - 4 * scale, category_bar.height() - 4 * scale), 8 * scale, color("#ffffff", 0.08 * alpha), color("#ffffff", 0.20 * alpha), 1.0)
        for index, category in enumerate(CATEGORIES):
            box = QRectF(category_bar.left() + index * step, category_bar.top(), step, category_bar.height())
            commands.text(box, self.category_icon(category), self.font("material", 12.0 * scale, QFont.Weight.Bold), self.gpu_alpha(THEME.text if category == self.selected_category else color("#7e7e85"), alpha), Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(box, "select_category", category, tooltip=category)

        module_rect = QRectF(panel.left() + 12 * scale, panel.top() + 43 * scale, 160 * scale, 316 * scale)
        settings_rect = QRectF(panel.left() + 187 * scale, panel.top() + 43 * scale, 401 * scale, 316 * scale)
        self.panel_modules_rect = module_rect
        self.panel_settings_rect = settings_rect
        commands.rect(module_rect, 4 * scale, color("#ffffff", 0.055 * alpha), color("#ffffff", 0.035 * alpha), 1.0)
        commands.text(module_rect.adjusted(10 * scale, 7 * scale, -10 * scale, -module_rect.height() + 30 * scale), self.selected_category, self.font("poppins_bold", 12.0 * scale), self.gpu_alpha(THEME.text, alpha))
        modules = self.panel_modules()
        top = module_rect.top() + 38 * scale
        row_h = 22 * scale
        module_clip = module_rect.adjusted(0, 32 * scale, 0, -4 * scale)
        max_scroll = max(0.0, len(modules) * row_h - module_clip.height())
        target_scroll = max(0.0, min(max_scroll, self.panel_module_scroll.get(self.selected_category, 0.0)))
        scroll = self.gui_motion.value(
            f"gpu.panel.modules.scroll.{self.selected_category}",
            target_scroll,
            self.anim_duration(0.16),
            Easings.ease_out_cubic,
            initial=target_scroll,
        )
        top -= scroll
        selected_index = float(next((i for i, item in enumerate(modules) if item is self.selected_module), 0))
        selected_y = self.gui_motion.value("gpu.panel.module", selected_index, self.anim_duration(0.18), Easings.ease_out_expo, initial=selected_index)
        if modules:
            commands.rect(QRectF(module_rect.left() + 6 * scale, top + selected_y * row_h, module_rect.width() - 12 * scale, 19 * scale), 5 * scale, color("#ffffff", 0.08 * alpha), clip=module_clip)
        for index, module in enumerate(modules):
            row = QRectF(module_rect.left() + 6 * scale, top + index * row_h, module_rect.width() - 12 * scale, 19 * scale)
            self.build_gpu_module_row(commands, row, module, scale, alpha, module_clip, select_only=True)

        commands.rect(settings_rect, 4 * scale, color("#ffffff", 0.075 * alpha), color("#ffffff", 0.08 * alpha), 1.0)
        commands.text(settings_rect.adjusted(12 * scale, 9 * scale, -72 * scale, -settings_rect.height() + 38 * scale), self.selected_module.name, self.font("poppins_bold", 13.0 * scale), self.gpu_alpha(THEME.text, alpha))
        self.build_gpu_toggle(commands, QRectF(settings_rect.right() - 57 * scale, settings_rect.top() + 13 * scale, 36 * scale, 16 * scale), self.selected_module.enabled, alpha, ("module_toggle", self.selected_module.name))
        content = settings_rect.adjusted(10 * scale, 43 * scale, -10 * scale, -10 * scale)
        scroll = self.gui_motion.value(f"gpu.settings.scroll.{self.selected_module.name}", self.settings_scroll.get(self.selected_module.name, 0.0), self.anim_duration(0.12), Easings.ease_out_cubic, initial=self.settings_scroll.get(self.selected_module.name, 0.0))
        self.build_gpu_settings(commands, self.selected_module, content, scale, alpha, scroll)
        search = QRectF(width / 2 - 104 * scale, min(height - 60.0, panel.bottom() + 15 * scale), 208 * scale, 23 * scale)
        commands.rect(search, search.height() / 2, color("#16161b", 0.94 * alpha), color("#ffffff", 0.16 * alpha), 1.0)
        commands.text(search.adjusted(12 * scale, 0, -12 * scale, 0), self.search_query or "Search modules...", self.font("poppins_regular", 7.8 * scale), self.gpu_alpha(THEME.text if self.search_query else color("#77777d"), alpha))
        self.add_hotspot(search, "search_focus")

    def build_gpu_old_gui(self, commands: ClickGuiDrawList, width: int, height: int, alpha: float) -> None:
        scale = self.get_gui_scale_for_bounds(width, height, 6 * 140.0 + 5 * 20.0, 520.0, 20.0, 54.0)
        panel_w, row_h = 140 * scale, 20 * scale
        for index, category in enumerate(CATEGORIES):
            data = self.old_panels[category]
            if not data.get("dragged", False):
                data["x"], data["y"] = 20.0 * scale + index * 160.0 * scale, 20.0 * scale
            x, y = float(data["x"]), float(data["y"])
            header = QRectF(x, y, panel_w, row_h)
            commands.rect(header, 3 * scale, color("#101014", 0.94 * alpha), color("#ffffff", 0.12 * alpha), 1.0)
            commands.text(header.adjusted(8 * scale, 0, -8 * scale, 0), f"{self.category_icon(category)}  {category}", self.font("poppins_bold", 8.2 * scale), self.gpu_alpha(THEME.text, alpha))
            self.add_hotspot(header, "old_drag", category, button=1, tooltip="拖动面板")
            self.add_hotspot(header, "old_expand", category, button=3, tooltip="展开分类")
            open_v = self.gui_motion.value(f"old.panel.{category}", 1.0 if data["expanded"] else 0.0, self.anim_duration(0.34), Easings.ease_out_expo)
            modules = self.registry.by_category(category)
            body_top = y + row_h
            content_h = sum(self.module_draw_height(module, scale, True) for module in modules)
            body_h = min(content_h, max(80.0 * scale, height - body_top - 22.0 * scale))
            maximum = max(0.0, content_h - body_h)
            data["scroll"] = max(0.0, min(float(data.get("scroll", 0.0)), maximum))
            scroll = self.gui_motion.value(f"gpu.old.scroll.{category}", float(data["scroll"]), self.anim_duration(0.12), Easings.ease_out_cubic, initial=float(data["scroll"]))
            clip = QRectF(x, body_top, panel_w, body_h * open_v)
            self.register_gui_scroll_viewport("old", category, clip, content_h, body_h)
            yy = body_top - scroll
            for item_index, module in enumerate(modules):
                reveal = self.gui_motion.waterfall(open_v, item_index, len(modules))
                slot = self.module_draw_height(module, scale, True)
                row = QRectF(x + (1.0 - reveal) * 5 * scale, yy, panel_w - (1.0 - reveal) * 5 * scale, row_h)
                if reveal > 0.01:
                    self.build_gpu_module_row(commands, row, module, scale, alpha * reveal, clip, compact=True, style="old")
                    self.build_gpu_inline_settings(commands, module, row.bottom(), row.left() + 5 * scale, row.width() - 10 * scale, scale, alpha * reveal, clip, f"old.expand.{module.name}", 6)
                yy += slot

    def build_gpu_new_gui(self, commands: ClickGuiDrawList, width: int, height: int, alpha: float) -> None:
        base_w = len(CATEGORIES) * 120.0 + (len(CATEGORIES) - 1) * 8.0
        scale = self.get_gui_scale_for_bounds(width, height, base_w, 430.0, 56.0, 118.0)
        gap, panel_w = 8 * scale, 120 * scale
        start_x = width / 2 - (len(CATEGORIES) * panel_w + (len(CATEGORIES) - 1) * gap) / 2
        # NewClickGui lays its six 120px columns at y=36 from centerX-380.
        # Only clamp on genuinely small windows; 1080p/2K stay source-faithful.
        y = 36.0 * scale if height >= 420.0 * scale else max(12.0 * scale, height * 0.08)
        max_h = min(430 * scale, max(180 * scale, height - y - 32 * scale))
        for index, category in enumerate(CATEGORIES):
            modules = self.registry.by_category(category)
            panel_h = min(max_h, max(72 * scale, 33 * scale + sum(self.module_draw_height(module, scale, True) for module in modules)))
            enter = self.gui_motion.value(f"new.panel.{category}", 1.0, self.anim_duration(0.30 + index * 0.035), Easings.ease_out_expo, initial=0.0)
            rect = QRectF(start_x + index * (panel_w + gap), y + (1.0 - enter) * 9 * scale, panel_w, panel_h)
            # Polar New uses a neutral #171717 surface with a narrow
            # teal accent line; it is not the blue-grey POLAR panel surface.
            commands.rect(rect, 7 * scale, color("#171717", 0.96 * alpha * enter), color("#ffffff", 0.08 * alpha * enter), 1.0)
            commands.rect(QRectF(rect.left(), rect.top(), rect.width(), max(1.0, scale)), 0, color("#2de8ca", 0.88 * alpha * enter), clip=rect)
            commands.text(rect.adjusted(8 * scale, 3 * scale, -8 * scale, -rect.height() + 25 * scale), category, self.font("poppins_bold", 8 * scale), self.gpu_alpha(THEME.text, alpha * enter))
            self.add_hotspot(QRectF(rect.left(), rect.top(), rect.width(), 24 * scale), "select_category", category, tooltip=category)
            clip = rect.adjusted(0, 26 * scale, 0, -4 * scale)
            content_h = sum(self.module_draw_height(module, scale, True) for module in modules)
            maximum = max(0.0, content_h - clip.height())
            self.new_panels[category]["scroll"] = max(0.0, min(float(self.new_panels[category].get("scroll", 0.0)), maximum))
            scroll = self.gui_motion.value(f"gpu.new.scroll.{category}", float(self.new_panels[category]["scroll"]), self.anim_duration(0.12), Easings.ease_out_cubic, initial=float(self.new_panels[category]["scroll"]))
            self.register_gui_scroll_viewport("new", category, clip, content_h, clip.height())
            yy = rect.top() + 27 * scale - scroll
            for module in modules:
                row = QRectF(rect.left() + 4 * scale, yy, rect.width() - 8 * scale, 21 * scale)
                self.build_gpu_module_row(commands, row, module, scale, alpha * enter, clip, compact=True, style="new")
                self.build_gpu_inline_settings(commands, module, row.bottom(), row.left() + 4 * scale, row.width() - 8 * scale, scale, alpha * enter, clip, f"new.expand.{module.name}", 5)
                yy += self.module_draw_height(module, scale, True)

    def build_gpu_dropdown_gui(self, commands: ClickGuiDrawList, width: int, height: int, alpha: float) -> None:
        # TestClient ClickGuiScreen: x=10, y=10, category width=120,
        # header=28 and a 10px column gap.  Never stretch it into the former
        # centred 226px approximation.
        scale = self.get_gui_scale_for_bounds(width, height, 6 * 120.0 + 5 * 10.0 + 20.0, 470.0, 10.0, 38.0)
        gap = 10 * scale
        panel_w = 120.0 * scale
        x0, y0 = 10.0 * scale, 10.0 * scale
        for index, category in enumerate(CATEGORIES):
            modules = self.registry.by_category(category)
            open_v = self.gui_motion.value(f"dropdown.panel.{category}", 1.0 if self.dropdown_panels[category]["expanded"] else 0.0, self.anim_duration(0.26), Easings.ease_out_expo)
            header_h = 28 * scale
            content_h = sum(self.module_draw_height(module, scale, False) for module in modules) + 8 * scale
            body_h = min(430 * scale, max(60 * scale, height - y0 - header_h - 22 * scale), content_h)
            panel = self.dropdown_panels[category]
            maximum = max(0.0, content_h - body_h)
            panel["scroll"] = max(0.0, min(float(panel.get("scroll", 0.0)), maximum))
            scroll = self.gui_motion.value(f"gpu.dropdown.scroll.{category}", float(panel["scroll"]), self.anim_duration(0.12), Easings.ease_out_cubic, initial=float(panel["scroll"]))
            rect = QRectF(x0 + index * (panel_w + gap), y0, panel_w, header_h + body_h * open_v)
            commands.rect(rect, 5 * scale, color("#0c0c0c", 0.57 * alpha), color("#ffffff", 0.07 * alpha), 1.0)
            commands.rect(QRectF(rect.left(), rect.top(), rect.width(), header_h), 5 * scale, color("#2a2a2a", 0.76 * alpha), clip=rect)
            commands.text(QRectF(rect.left() + 12 * scale, rect.top(), rect.width() - 24 * scale, header_h), f"{self.category_icon(category)}  {category}", self.font("poppins_bold", 10 * scale), self.gpu_alpha(THEME.text, alpha))
            self.add_hotspot(QRectF(rect.left(), rect.top(), rect.width(), header_h), "dropdown_expand", category, button=3, tooltip="展开分类")
            clip = QRectF(rect.left(), rect.top() + header_h, rect.width(), body_h * open_v)
            self.register_gui_scroll_viewport("dropdown", category, clip, content_h, body_h)
            yy = rect.top() + header_h - scroll
            for item_index, module in enumerate(modules):
                reveal = self.gui_motion.waterfall(open_v, item_index, len(modules))
                row = QRectF(rect.left() + (1 - reveal) * 6 * scale, yy, rect.width() - (1 - reveal) * 6 * scale, 24 * scale)
                if reveal > 0.01:
                    self.build_gpu_module_row(commands, row, module, scale, alpha * reveal, clip, style="dropdown", row_index=item_index)
                    self.build_gpu_inline_settings(commands, module, row.bottom(), row.left() + 9 * scale, row.width() - 18 * scale, scale, alpha * reveal, clip, f"dropdown.expand.{module.name}", 6)
                yy += self.module_draw_height(module, scale, False)

    def register_gui_scroll_viewport(self, mode: str, key: str, rect: QRectF, content_height: float, viewport_height: float) -> None:
        if rect.width() <= 1.0 or rect.height() <= 1.0:
            return
        self.gui_scroll_viewports.append({
            "mode": mode,
            "key": key,
            "rect": QRectF(rect),
            "maximum": max(0.0, float(content_height) - float(viewport_height)),
        })

    def polar_view_modules(self, category: str) -> list[Module]:
        if category != "Profile":
            return self.registry.by_category(category)
        names = ("ConfigManager", "UIScale", "ClickGui", "AudioFeedback")
        return [module for name in names if (module := self.registry.get(name)) is not None]

    def build_gpu_polar_glass(self, commands: ClickGuiDrawList, rect: QRectF, radius: float, alpha: float, *, prominent: bool = False, hover: float = 0.0) -> None:
        """POLAR 视图使用正式镜片，不用半透明色块伪装玻璃。"""
        if self._gpu_frame_recording:
            refraction_height = min(42.0, rect.height() * (0.22 if prominent else 0.12))
            refraction_amount = min(58.0, rect.height() * (0.30 if prominent else 0.16))
            self.gpu_compositor.add_glass(
                rect,
                radius,
                strength=1.08 if prominent else 0.98,
                surface="clear" if prominent else "main",
                hover=hover,
                opacity=alpha,
                material=LensMaterial.STRONG if prominent else LensMaterial.REGULAR,
                refraction_height_px=refraction_height,
                refraction_amount_px=refraction_amount,
            )
        # 强镜片会直接替换组合背景；再次绘制整块描边会在圆角外形成方形光晕。
        if not prominent:
            commands.rect(
                rect,
                radius,
                color("#ffffff", 0.0),
                color("#d8ffe8", 0.10 * alpha),
                0.55,
            )

    def build_gpu_polar_unified(self, commands: ClickGuiDrawList, width: int, height: int, alpha: float) -> None:
        scale = self.get_gui_scale_for_bounds(width, height, 800.0, 540.0, 74.0, 86.0)
        progress = self.polar_unified_morph.progress
        island_w = 236.0 * scale + (800.0 * scale - 236.0 * scale) * progress
        island_h = 36.0 * scale + (540.0 * scale - 36.0 * scale) * progress
        panel = QRectF(width / 2.0 - island_w / 2.0, height / 2.0 - island_h / 2.0, island_w, island_h)
        self.build_gpu_polar_glass(commands, panel, (24.0 - 6.0 * progress) * scale, progress, prominent=True)
        if progress < 0.08:
            return
        reveal = max(0.0, min(1.0, (progress - 0.16) / 0.84)) * alpha
        header = QRectF(panel.left(), panel.top(), panel.width(), 42.0 * scale)
        commands.text(header.adjusted(17 * scale, 0, -120 * scale, 0), "POLAR-RM", self.font("poppins_bold", 13.0 * scale), self.gpu_alpha(color("#f2fff6"), reveal))
        commands.text(QRectF(header.right() - 98 * scale, header.top(), 82 * scale, header.height()), "POLAR VIEW", self.font("poppins_bold", 7.0 * scale), self.gpu_alpha(color("#73f9ad"), reveal), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        commands.rect(QRectF(panel.left() + 12 * scale, header.bottom() - 1, panel.width() - 24 * scale, 1), 0.5, color("#9bffca", 0.26 * reveal))

        sidebar = QRectF(panel.left() + 12 * scale, header.bottom() + 10 * scale, 54 * scale, panel.height() - header.height() - 22 * scale)
        content = QRectF(sidebar.right() + 12 * scale, sidebar.top(), panel.width() - sidebar.width() - 36 * scale, sidebar.height())
        categories = [*CATEGORIES, "Profile"]
        button_h = min(45.0 * scale, (sidebar.height() - 8 * scale) / len(categories))
        for index, category in enumerate(categories):
            item = QRectF(sidebar.left(), sidebar.top() + index * button_h, sidebar.width(), button_h - 4 * scale)
            selected = category == self.selected_category
            hover = self.gui_motion.value(f"polar.unified.hover.{category}", 1.0 if item.contains(self.hover_point) else 0.0, self.anim_duration(0.16), Easings.ease_out_cubic)
            if selected or hover > 0.01:
                commands.rect(item, 8 * scale, color("#75f7ac", (0.20 + 0.10 * hover) * reveal), color("#ccffe0", (0.24 + 0.20 * hover) * reveal), 0.8)
            commands.text(item, self.category_icon(category) if category != "Profile" else "@", self.font("poppins_bold", 10 * scale), self.gpu_alpha(color("#e9fff1") if selected else color("#b8c9bf"), reveal), Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(item, "select_category", category, tooltip=category)

        modules = self.polar_view_modules(self.selected_category)
        list_w = content.width() * 0.43
        module_panel = QRectF(content.left(), content.top(), list_w, content.height())
        setting_panel = QRectF(module_panel.right() + 10 * scale, content.top(), content.width() - list_w - 10 * scale, content.height())
        self.build_gpu_polar_glass(commands, module_panel, 16 * scale, reveal)
        self.build_gpu_polar_glass(commands, setting_panel, 16 * scale, reveal)
        commands.text(module_panel.adjusted(11 * scale, 8 * scale, -11 * scale, -module_panel.height() + 27 * scale), self.selected_category, self.font("poppins_bold", 10 * scale), self.gpu_alpha(color("#f4fff7"), reveal))
        list_clip = module_panel.adjusted(6 * scale, 33 * scale, -6 * scale, -6 * scale)
        row_h = 32 * scale
        max_scroll = max(0.0, len(modules) * row_h - list_clip.height())
        self.polar_unified_scroll_motion.set_bounds(max_scroll)
        scroll = self.polar_unified_scroll_motion.position
        self.polar_unified_scroll = scroll
        self.register_gui_scroll_viewport("polar_unified", "unified", list_clip, len(modules) * row_h, list_clip.height())
        y = list_clip.top() - scroll
        for index, module in enumerate(modules):
            row = QRectF(list_clip.left(), y, list_clip.width(), row_h - 4 * scale)
            self.build_gpu_polar_module_row(commands, row, module, scale, reveal, list_clip, index, select_only=True)
            y += row_h
        if max_scroll > 0.5:
            self.build_gpu_scroll_island(commands, list_clip, scroll, max_scroll, reveal, scale)

        commands.text(setting_panel.adjusted(12 * scale, 8 * scale, -60 * scale, -setting_panel.height() + 29 * scale), self.selected_module.name, self.font("poppins_bold", 11 * scale), self.gpu_alpha(color("#f4fff7"), reveal))
        toggle = QRectF(setting_panel.right() - 52 * scale, setting_panel.top() + 10 * scale, 34 * scale, 15 * scale)
        self.build_gpu_toggle(commands, toggle, self.selected_module.enabled, reveal, ("module_toggle", self.selected_module.name))
        settings_clip = setting_panel.adjusted(10 * scale, 36 * scale, -10 * scale, -8 * scale)
        settings_content_h = (1 + len(self.selected_module.settings)) * 30.0 * scale
        settings_max = max(0.0, settings_content_h - settings_clip.height())
        settings_motion = self.polar_settings_scroll_motion.setdefault(self.selected_module.name, InertialScroll())
        settings_motion.set_bounds(settings_max)
        self.register_gui_scroll_viewport(
            "polar_settings",
            self.selected_module.name,
            settings_clip,
            settings_content_h,
            settings_clip.height(),
        )
        self.build_gpu_settings(commands, self.selected_module, settings_clip, scale, reveal, settings_motion.position)
        if settings_max > 0.5:
            self.build_gpu_scroll_island(commands, settings_clip, settings_motion.position, settings_max, reveal, scale)

    def build_gpu_scroll_island(
        self,
        commands: ClickGuiDrawList,
        viewport: QRectF,
        position: float,
        maximum: float,
        alpha: float,
        scale: float,
    ) -> None:
        """绘制随惯性滚动平滑移动的贴边灵动岛胶囊。"""
        if maximum <= 0.0:
            return
        track_h = max(1.0, viewport.height() - 12.0 * scale)
        content_ratio = viewport.height() / max(viewport.height() + maximum, 1.0)
        thumb_h = max(24.0 * scale, track_h * content_ratio)
        travel = max(0.0, track_h - thumb_h)
        ratio = max(0.0, min(1.0, position / maximum))
        thumb = QRectF(
            viewport.right() - 4.0 * scale,
            viewport.top() + 6.0 * scale + travel * ratio,
            3.0 * scale,
            thumb_h,
        )
        commands.rect(
            thumb.adjusted(-1.0 * scale, -1.0 * scale, 1.0 * scale, 1.0 * scale),
            2.5 * scale,
            color("#d8ffe8", 0.10 * alpha),
            clip=viewport,
        )
        commands.rect(thumb, 1.5 * scale, color("#72f7ad", 0.72 * alpha), clip=viewport)

    def build_gpu_polar_multi(self, commands: ClickGuiDrawList, width: int, height: int, alpha: float) -> None:
        scale = self.get_gui_scale_for_bounds(width, height, 980.0, 650.0, 34.0, 62.0)
        categories = [*CATEGORIES, "Profile"]
        panel_w, header_h = 210 * scale, 31 * scale
        for index, category in enumerate(categories):
            data = self.polar_windows.setdefault(category, {"x": 70.0 + (index % 4) * 228.0, "y": 94.0 + (index // 4) * 290.0, "scroll": 0.0})
            x = max(6.0, min(width - panel_w - 6.0, float(data["x"])))
            y = max(20.0, min(height - 85.0, float(data["y"])))
            data["x"], data["y"] = x, y
            modules = self.polar_view_modules(category)
            content_h = len(modules) * 28 * scale + 8 * scale
            body_h = min(300 * scale, max(78 * scale, height - y - header_h - 24 * scale), content_h)
            data["scroll"] = max(0.0, min(float(data.get("scroll", 0.0)), max(0.0, content_h - body_h)))
            scroll = self.gui_motion.value(f"polar.multi.scroll.{category}", float(data["scroll"]), self.anim_duration(0.12), Easings.ease_out_cubic, initial=float(data["scroll"]))
            panel = QRectF(x, y, panel_w, header_h + body_h)
            self.build_gpu_polar_glass(commands, panel, 16 * scale, alpha)
            header = QRectF(x, y, panel_w, header_h)
            commands.text(header.adjusted(10 * scale, 0, -10 * scale, 0), f"{self.category_icon(category) if category != 'Profile' else '@'}  {category}", self.font("poppins_bold", 9 * scale), self.gpu_alpha(color("#f1fff5"), alpha))
            self.add_hotspot(header, "polar_drag", category, button=1, tooltip="Drag category window")
            clip = QRectF(x + 5 * scale, y + header_h, panel_w - 10 * scale, body_h)
            self.register_gui_scroll_viewport("polar_multi", category, clip, content_h, body_h)
            yy = clip.top() - scroll
            for row_index, module in enumerate(modules):
                row = QRectF(clip.left(), yy, clip.width(), 24 * scale)
                self.build_gpu_polar_module_row(commands, row, module, scale, alpha, clip, row_index)
                yy += 28 * scale

    def build_gpu_polar_module_row(self, commands: ClickGuiDrawList, row: QRectF, module: Module, scale: float, alpha: float, clip: QRectF, row_index: int, *, select_only: bool = False) -> None:
        selected = module is self.selected_module
        hover = self.gui_motion.value(f"polar.row.{module.name}", 1.0 if row.contains(self.hover_point) else 0.0, self.anim_duration(0.14), Easings.ease_out_cubic)
        enabled = self.gui_motion.value(f"polar.enabled.{module.name}", 1.0 if module.enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_cubic)
        fill = color("#81fbb3", (0.15 * enabled + 0.07 * hover + (0.06 if selected else 0.0)) * alpha)
        commands.rect(row, 5 * scale, fill, color("#effff4", (0.07 + 0.13 * hover) * alpha), 0.8, clip=clip)
        commands.rect(QRectF(row.left(), row.top(), 2 * scale, row.height()), 1 * scale, color("#72f7a9", (0.25 + 0.65 * enabled) * alpha), clip=clip)
        commands.text(row.adjusted(8 * scale, 0, -50 * scale, 0), self.elide_for_gpu(self.font("poppins_medium", 7.6 * scale), module.name, row.width() - 56 * scale), self.font("poppins_medium", 7.6 * scale), self.gpu_alpha(color("#f3fff7"), alpha), clip=clip)
        key = QRectF(row.right() - 39 * scale, row.top() + 4 * scale, 33 * scale, row.height() - 8 * scale)
        commands.rect(key, 4 * scale, color("#b7ffd2", 0.10 * alpha), clip=clip)
        commands.text(key, self.compact_keybind(module.keybind), self.font("poppins_bold", 6.0 * scale), self.gpu_alpha(color("#d9ffe7"), alpha), Qt.AlignmentFlag.AlignCenter, clip)
        self._hotspot_clip = clip
        self.add_hotspot(row.adjusted(0, 0, -42 * scale, 0), "module_select" if select_only else "module_toggle", module.name, tooltip=module.description)
        self.add_hotspot(key, "module_bind", module.name, tooltip="Bind key")
        self._hotspot_clip = None

    def build_gpu_module_row(
        self,
        commands: ClickGuiDrawList,
        row: QRectF,
        module: Module,
        scale: float,
        alpha: float,
        clip: QRectF | None,
        compact: bool = False,
        select_only: bool = False,
        style: str = "panel",
        row_index: int = 0,
    ) -> None:
        enabled = self.gui_motion.value(f"gpu.enabled.{module.name}", 1.0 if module.enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_cubic)
        gradient = None
        if style == "old":
            # Polar Old：近黑色行底与偏亮的启用文字。
            fill = color("#151515", (0.78 + 0.08 * enabled) * alpha)
            outline = color("#ffffff", 0.035 * alpha)
            text_color = color("#b4f8ff") if module.enabled else color("#e5e5e8")
            radius = 0.0
        elif style == "new":
            # NewClickGui keeps rows transparent; enabled state is text/glow.
            fill = color("#202020", (0.28 + 0.12 * enabled) * alpha)
            outline = color("#ffffff", 0.025 * alpha)
            text_color = color("#2de8ca") if module.enabled else color("#ffffff", 0.60)
            radius = 0.0
        elif style == "dropdown":
            # TestClient only fills the active module with its Aura gradient.
            if module.enabled:
                fill = accent_color(row_index, time.perf_counter())
                fill.setAlphaF(0.55 * alpha * enabled)
                gradient = accent_color(row_index + 1, time.perf_counter())
                gradient.setAlphaF(0.55 * alpha * enabled)
            else:
                fill = color("#0c0c0c", 0.57 * alpha)
            outline = color("#5a5a5a", 0.24 * alpha)
            text_color = THEME.text
            radius = 0.0
        else:
            # PanelClickGui uses glassy white hover surfaces and white-glow
            # enabled text.  The previous blue-grey tiles were a POLAR
            # invention and made this mode visually unrelated to Polar Old.
            fill = color("#ffffff", (0.025 + 0.055 * enabled) * alpha)
            outline = color("#ffffff", 0.035 * alpha)
            text_color = THEME.text if module.enabled else color("#aaaaaa")
            radius = 5 * scale if compact else 0.0
        commands.rect(row, radius, fill, outline, 1.0, gradient=gradient, clip=clip)
        # Panel mode matches QPainter: medium weight + slightly brighter enabled text.
        if style == "panel":
            name_font = self.font("poppins_medium" if module.enabled else "poppins_regular", 8.6 * scale)
            key_w = 30 * scale
            name_rect = row.adjusted(6 * scale, 0, -(key_w + 12 * scale), 0)
        else:
            name_font = self.font("poppins_regular", (7.2 if compact else 8.2) * scale)
            key_w = 20 * scale
            name_rect = row.adjusted(7 * scale, 0, -32 * scale, 0)
        label = self.elide_for_gpu(name_font, module.name, name_rect.width())
        commands.text(name_rect, label, name_font, self.gpu_alpha(text_color, alpha), clip=clip)
        if style == "panel":
            key = QRectF(row.right() - 34 * scale, row.top() + 2 * scale, 30 * scale, max(10 * scale, row.height() - 4 * scale))
        else:
            key = QRectF(row.right() - 25 * scale, row.top() + 3 * scale, 20 * scale, max(10 * scale, row.height() - 6 * scale))
        commands.rect(key, 4 * scale, color("#ffffff", 0.05 * alpha), color("#ffffff", 0.08 * alpha), 1.0, clip=clip)
        # PanelClickGui always labels the bind chip "KEY" (see draw_panel_module_list).
        # Other GPU modes keep the compact bind / placeholder.
        if style == "panel":
            key_label = "KEY"
        else:
            key_label = self.compact_keybind(module.keybind) if module.keybind and module.keybind != "None" else "--"
        commands.text(key, key_label, self.font("poppins_medium", 6.3 * scale), self.gpu_alpha(THEME.muted, alpha), Qt.AlignmentFlag.AlignCenter, clip)
        self._hotspot_clip = clip
        if style == "panel":
            self.add_hotspot(row.adjusted(0, 0, -36 * scale, 0), "module_toggle" if not select_only else "module_select", module.name, button=1, tooltip=module.description)
            self.add_hotspot(row.adjusted(0, 0, -36 * scale, 0), "module_expand", module.name, button=3, tooltip="展开设置")
        else:
            self.add_hotspot(row.adjusted(0, 0, -25 * scale, 0), "module_toggle" if not select_only else "module_select", module.name, button=1, tooltip=module.description)
            self.add_hotspot(row.adjusted(0, 0, -25 * scale, 0), "module_expand", module.name, button=3, tooltip="展开设置")
        self.add_hotspot(key, "module_bind", module.name, tooltip="绑定按键")

        self._hotspot_clip = None

    def build_gpu_settings(self, commands: ClickGuiDrawList, module: Module, content: QRectF, scale: float, alpha: float, scroll: float) -> None:
        y = content.top() - scroll
        self._hotspot_clip = content
        bind = QRectF(content.left(), y, content.width(), 27 * scale)
        commands.rect(bind.adjusted(0, 2 * scale, 0, -3 * scale), 5 * scale, color("#ffffff", 0.04 * alpha), color("#ffffff", 0.06 * alpha), 1.0, clip=content)
        commands.text(bind.adjusted(8 * scale, 0, -112 * scale, 0), "Keybind", self.font("poppins_regular", 8 * scale), self.gpu_alpha(THEME.muted, alpha), clip=content)
        key = QRectF(bind.right() - 103 * scale, bind.top() + 5 * scale, 96 * scale, 18 * scale)
        commands.rect(key, 5 * scale, color("#ffffff", 0.06 * alpha), color("#ffffff", 0.10 * alpha), 1.0, clip=content)
        commands.text(key, module.keybind, self.font("poppins_medium", 7.6 * scale), self.gpu_alpha(THEME.text, alpha), Qt.AlignmentFlag.AlignCenter, content)
        self.add_hotspot(key, "module_bind", module.name, tooltip="打开按键绑定")
        y = bind.bottom()
        for setting in module.settings:
            row = QRectF(content.left(), y, content.width(), 30 * scale)
            self.build_gpu_setting_row(commands, setting, row, scale, alpha, content)
            y = row.bottom()
        self._hotspot_clip = None

    def build_gpu_setting_row(self, commands: ClickGuiDrawList, setting: Setting, row: QRectF, scale: float, alpha: float, clip: QRectF | None) -> None:
        body = row.adjusted(0, 2 * scale, 0, -3 * scale)
        commands.rect(body, 5 * scale, color("#ffffff", 0.035 * alpha), clip=clip)
        commands.text(body.adjusted(8 * scale, 0, -120 * scale, 0), setting.name, self.font("poppins_regular", 8 * scale), self.gpu_alpha(color("#d7d7dc"), alpha), clip=clip)
        if setting.kind == "bool":
            self.build_gpu_toggle(commands, QRectF(body.right() - 39 * scale, body.top() + 6 * scale, 30 * scale, 13 * scale), bool(setting.value), alpha, ("setting_toggle", setting), clip)
        elif setting.kind == "number":
            commands.text(QRectF(body.right() - 78 * scale, body.top(), 70 * scale, body.height() * 0.48), setting.display_value(), self.font("poppins_medium", 7.6 * scale), self.gpu_alpha(THEME.text, alpha), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, clip)
            bar = QRectF(body.left() + body.width() * 0.42, body.bottom() - 9 * scale, body.width() * 0.52, 5 * scale)
            commands.rect(bar, 2.5 * scale, color("#ffffff", 0.17 * alpha), clip=clip)
            commands.rect(QRectF(bar.left(), bar.top(), max(bar.height(), bar.width() * setting.ratio()), bar.height()), 2.5 * scale, color("#f15bd5", alpha), clip=clip)
            self.add_hotspot(bar.adjusted(-4 * scale, -7 * scale, 4 * scale, 7 * scale), "setting_slider", setting)
        elif setting.kind == "mode":
            box = QRectF(body.right() - 112 * scale, body.top() + 5 * scale, 103 * scale, body.height() - 10 * scale)
            commands.rect(box, 5 * scale, color("#303036", 0.95 * alpha), color("#ffffff", 0.08 * alpha), 1.0, clip=clip)
            commands.text(box.adjusted(5 * scale, 0, -5 * scale, 0), str(setting.value), self.font("poppins_medium", 7 * scale), self.gpu_alpha(THEME.text, alpha), Qt.AlignmentFlag.AlignCenter, clip)
            self.add_hotspot(box, "setting_mode_next", setting, tooltip="左键/右键循环切换")
        elif setting.kind == "action":
            button = body.adjusted(8 * scale, 4 * scale, -8 * scale, -4 * scale)
            commands.rect(button, 5 * scale, color("#ffffff", 0.92 * alpha), color("#56fff0", 0.35 * alpha), 1.0, clip=clip)
            commands.text(button, setting.name, self.font("poppins_medium", 7.4 * scale), self.gpu_alpha(color("#090a0d"), alpha), Qt.AlignmentFlag.AlignCenter, clip)
            self.add_hotspot(button, "config_action", setting.name, tooltip=setting.description)

    def build_gpu_inline_settings(self, commands: ClickGuiDrawList, module: Module, y: float, x: float, width: float, scale: float, alpha: float, clip: QRectF, key: str, max_rows: int) -> None:
        expand = self.gui_motion.value(key, 1.0 if module.name in self.module_expanded else 0.0, self.anim_duration(0.34), Easings.ease_out_expo)
        if expand <= 0.01:
            return
        self._hotspot_clip = clip
        rows = [None, *module.settings[:max_rows]]
        for index, setting in enumerate(rows):
            reveal = self.gui_motion.waterfall(expand, index, len(rows))
            if reveal <= 0.01:
                continue
            h = self.inline_bind_height(scale, True) if setting is None else self.inline_setting_height(setting, scale, True)
            row = QRectF(x + (1 - reveal) * 7 * scale, y, width - (1 - reveal) * 7 * scale, h)
            if setting is None:
                commands.rect(row, 5 * scale, color("#ffffff", 0.035 * alpha * reveal), clip=clip)
                commands.text(row.adjusted(7 * scale, 0, -68 * scale, 0), "Keybind", self.font("poppins_regular", 7 * scale), self.gpu_alpha(THEME.muted, alpha * reveal), clip=clip)
                box = QRectF(row.right() - 62 * scale, row.top() + 4 * scale, 55 * scale, row.height() - 8 * scale)
                commands.rect(box, 4 * scale, color("#ffffff", 0.06 * alpha * reveal), clip=clip)
                commands.text(box, self.compact_keybind(module.keybind), self.font("poppins_medium", 6.7 * scale), self.gpu_alpha(THEME.text, alpha * reveal), Qt.AlignmentFlag.AlignCenter, clip)
                self.add_hotspot(box, "module_bind", module.name)
            else:
                self.build_gpu_setting_row(commands, setting, row, scale, alpha * reveal, clip)
            y += h
        self._hotspot_clip = None

    def build_gpu_toggle(self, commands: ClickGuiDrawList, rect: QRectF, enabled: bool, alpha: float, action: tuple[str, Any], clip: QRectF | None = None) -> None:
        value = self.gui_motion.value(f"gpu.toggle.{id(action[1])}", 1.0 if enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_cubic)
        commands.rect(rect, rect.height() / 2, color("#43b95b", 0.86 * alpha * value) if enabled else color("#565861", 0.86 * alpha), clip=clip)
        knob = rect.height() - 4
        commands.rect(QRectF(rect.left() + 2 + (rect.width() - knob - 4) * value, rect.top() + 2, knob, knob), knob / 2, self.gpu_alpha(THEME.text, alpha), clip=clip)
        self.add_hotspot(rect.adjusted(-4, -4, 4, 4), action[0], action[1])

    def build_gpu_mode_switcher(self, commands: ClickGuiDrawList, width: int, height: int) -> None:
        gap, margin = 6.0, 18.0
        chip_w = min(128.0, (width - margin * 2 - gap * (len(GUI_MODES) - 1)) / len(GUI_MODES))
        total, x, y = len(GUI_MODES) * chip_w + (len(GUI_MODES) - 1) * gap, max(margin, width - (len(GUI_MODES) * chip_w + (len(GUI_MODES) - 1) * gap) - margin), max(12.0, height - 38.0)
        commands.rect(QRectF(x - 8, y - 6, total + 16, 30), 8, color("#08080a", 0.82), color("#ffffff", 0.10), 1.0)
        for index, mode in enumerate(GUI_MODES):
            rect = QRectF(x + index * (chip_w + gap), y, chip_w, 18)
            active = mode == self.mode_manager.mode
            commands.rect(rect, 5, color("#ffffff", 0.92) if active else color("#1a1c22", 0.95), color("#ffffff", 0.10), 1.0)
            commands.text(rect, self.gui_mode_label(mode), self.font("poppins_medium", 7.1), color("#08080a") if active else THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(rect, "gui_mode", mode)

    def build_gpu_toasts(self, commands: ClickGuiDrawList, width: int, height: int) -> None:
        now = time.perf_counter()
        self.toasts = [toast for toast in self.toasts if now - toast["created"] < 3.0]
        for index, toast in enumerate(self.toasts[-5:]):
            age = now - toast["created"]
            fade = 1.0 if age < 2.35 else max(0.0, 1.0 - (age - 2.35) / 0.65)
            message = str(toast["message"])
            rect = QRectF(width / 2 - 150, height - 82 - index * 42, 300, 36)
            commands.rect(rect, 10, color("#050506", 0.74 * fade), color("#ffffff", 0.08 * fade), 1.0)
            commands.text(rect.adjusted(14, 4, -14, -16), message, self.font("poppins_regular", 7.3), self.gpu_alpha(THEME.text, fade), Qt.AlignmentFlag.AlignCenter)
            commands.rect(QRectF(rect.left() + 8, rect.bottom() - 4, (rect.width() - 16) * max(0.0, 1.0 - age / 3.0), 2), 1, color("#56fff0", fade))

    def build_gpu_tooltip(self, commands: ClickGuiDrawList, point: QPointF, text: str) -> None:
        font = self.font("poppins_regular", 8.0)
        metrics = QFontMetricsF(font)
        label = self.elide_for_gpu(font, text, 340)
        width = metrics.horizontalAdvance(label) + 18
        rect = QRectF(min(point.x() + 14, self.width() - width - 10), min(point.y() + 18, self.height() - 30), width, 24)
        commands.rect(rect, 6, color("#050506", 0.92), color("#ffffff", 0.14), 1.0)
        commands.text(rect.adjusted(9, 0, -9, 0), label, font, THEME.text)

    def elide_for_gpu(self, font: QFont, text: str, width: float) -> str:
        return QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, int(width))

    def build_gpu_keybind_overlay(self, commands: ClickGuiDrawList, width: int, height: int) -> None:
        module = self.binding_module
        if module is None:
            return
        active = self.gui_motion.value("gpu.keybind", 1.0, self.anim_duration(0.18), Easings.ease_out_expo, initial=0.0)
        commands.rect(QRectF(0, 0, width, height), 0, color("#000000", 0.58 * active))
        scale = 0.96 + 0.04 * active
        rect = QRectF(width / 2 - 200 * scale, height / 2 - 90 * scale, 400 * scale, 180 * scale)
        commands.rect(rect, 11 * scale, color("#0b0b0f", 0.97 * active), color("#ffffff", 0.16 * active), 1.0)
        commands.text(QRectF(rect.left(), rect.top() + 28 * scale, rect.width(), 24 * scale), "KEYBIND", self.font("poppins_bold", 18 * scale), self.gpu_alpha(THEME.text, active), Qt.AlignmentFlag.AlignCenter)
        commands.text(QRectF(rect.left(), rect.top() + 67 * scale, rect.width(), 21 * scale), module.name, self.font("poppins_medium", 11 * scale), self.gpu_alpha(THEME.cyan, active), Qt.AlignmentFlag.AlignCenter)
        commands.text(QRectF(rect.left(), rect.top() + 98 * scale, rect.width(), 20 * scale), "Press any key to bind", self.font("poppins_regular", 9 * scale), self.gpu_alpha(THEME.muted, active), Qt.AlignmentFlag.AlignCenter)

    def draw_panel_gui(self, p: QPainter, width: int, height: int, alpha: float) -> None:
        scale_setting = self.get_gui_scale_for_bounds(width, height, 600.0, 440.0, 76.0, 82.0)
        open_scale = 0.98 + 0.02 * alpha
        scale = scale_setting * open_scale
        panel_w = 600.0 * scale
        panel_h = 400.0 * scale
        x = width / 2 - panel_w / 2
        y = height / 2 - panel_h / 2
        panel = QRectF(x, y, panel_w, panel_h)
        self.draw_gui_cached_layer(
            p,
            panel.adjusted(-22 * scale, -22 * scale, 22 * scale, 22 * scale),
            ("panel.shell", round(scale, 3)),
            lambda layer, _rect: (
                glow_rect(layer, panel, 11 * scale, 0.34),
                rounded_rect(layer, panel, 8 * scale, color("#101014", 0.96), color("#ffffff", 0.13)),
            ),
        )

        self.draw_profile_widget(p, x + 14 * scale, y + 13 * scale, scale)
        self.draw_panel_category_bar(p, QRectF(x + 414 * scale, y + 18 * scale, 166 * scale, 28 * scale), scale)
        self.panel_modules_rect = QRectF(x + 12 * scale, y + 43 * scale, 160 * scale, 316 * scale)
        settings_rect = QRectF(x + 187 * scale, y + 43 * scale, 401 * scale, 316 * scale)
        self.panel_settings_rect = settings_rect
        self.draw_panel_module_list(p, self.panel_modules_rect, scale)
        self.draw_settings_area(p, settings_rect, self.selected_module, scale)

        search_y = min(height - 60.0, y + panel_h + 15.0 * scale)
        self.draw_search_bar(p, QRectF(width / 2 - 104 * scale, search_y, 208 * scale, 23 * scale), scale)

    def draw_profile_widget(self, p: QPainter, x: float, y: float, scale: float) -> None:
        self.draw_text(p, QRectF(x, y, 160 * scale, 20 * scale), "POLAR-RM", self.font("poppins_bold", 14 * scale), THEME.text)
        sub = f"配置 Default | 缩放 {self.get_gui_scale():.2f}"
        self.draw_text(p, QRectF(x, y + 20 * scale, 210 * scale, 16 * scale), sub, self.font("poppins_regular", 7.8 * scale), THEME.muted)

    def draw_panel_category_bar(self, p: QPainter, rect: QRectF, scale: float) -> None:
        step = rect.width() / len(CATEGORIES)
        selected_index = float(CATEGORIES.index(self.selected_category)) if self.selected_category in CATEGORIES else 0.0
        initial_index = selected_index
        indicator_index = self.gui_motion.value(
            "panel.category.indicator",
            selected_index,
            self.anim_duration(0.22),
            Easings.ease_out_expo,
            initial=initial_index,
        )
        indicator = QRectF(
            rect.left() + indicator_index * step + 2 * scale,
            rect.top() + 2 * scale,
            max(1.0, step - 4 * scale),
            max(1.0, rect.height() - 4 * scale),
        )
        rounded_rect(p, indicator, 9 * scale, color("#ffffff", 0.055), color("#ffffff", 0.20))
        for i, category in enumerate(CATEGORIES):
            box = QRectF(rect.left() + i * step, rect.top(), step, rect.height())
            active = category == self.selected_category
            self.draw_text(
                p,
                box,
                self.category_icon(category),
                self.font("material", 12.5 * scale, QFont.Weight.Bold),
                THEME.text if active else color("#7e7e85"),
                Qt.AlignmentFlag.AlignCenter,
            )
            self.add_hotspot(box, "select_category", category, tooltip=category)

    def draw_panel_module_list(self, p: QPainter, rect: QRectF, scale: float) -> None:
        self.draw_gui_cached_layer(
            p,
            rect,
            ("panel.module-list.shell", round(scale, 3)),
            lambda layer, shell: rounded_rect(layer, shell, 4 * scale, color("#ffffff", 0.055), color("#ffffff", 0.035)),
        )
        self.draw_text(p, rect.adjusted(10 * scale, 7 * scale, -10 * scale, -rect.height() + 30 * scale), self.selected_category, self.font("poppins_bold", 12.5 * scale), THEME.text)
        modules = self.panel_modules()
        top = rect.top() + 38 * scale
        row_h = 22 * scale
        module_clip = rect.adjusted(0, 32 * scale, 0, -4 * scale)
        max_scroll = max(0.0, len(modules) * row_h - module_clip.height())
        target_scroll = max(0.0, min(max_scroll, self.panel_module_scroll.get(self.selected_category, 0.0)))
        scroll = self.gui_motion.value(
            f"panel.modules.scroll.{self.selected_category}",
            target_scroll,
            self.anim_duration(0.16),
            Easings.ease_out_cubic,
            initial=target_scroll,
        )
        top -= scroll
        selected_index = float(next((i for i, module in enumerate(modules) if module is self.selected_module), 0))
        indicator_index = self.gui_motion.value(
            "panel.module.selection",
            selected_index,
            self.anim_duration(0.18),
            Easings.ease_out_expo,
            initial=selected_index,
        )
        p.save()
        p.setClipRect(module_clip)
        if modules:
            selection = QRectF(rect.left() + 6 * scale, top + indicator_index * row_h, rect.width() - 12 * scale, 19 * scale)
            rounded_rect(p, selection, 5 * scale, color("#ffffff", 0.055), color("#ffffff", 0.045))
        self._hotspot_clip = module_clip
        for i, module in enumerate(modules):
            row = QRectF(rect.left() + 6 * scale, top + i * row_h, rect.width() - 12 * scale, 19 * scale)
            enabled_v = self.gui_motion.value(f"panel.enabled.{module.name}", 1.0 if module.enabled else 0.0, self.anim_duration(0.22), Easings.ease_out_cubic)
            if enabled_v > 0.01:
                rounded_rect(p, row, 5 * scale, color("#ffffff", 0.035 * enabled_v))
            label_color = THEME.text if module.enabled else color("#ababaf")
            label_font = self.font("poppins_medium", 8.6 * scale)
            label = self.elide(p, label_font, module.name, row.width() - 42 * scale)
            if enabled_v > 0.01:
                glow_text(p, label, row.left() + 6 * scale, cap_center_y(p, label_font, row), label_font, label_color, accent_color(i), 4 * enabled_v)
            else:
                self.draw_text(p, row.adjusted(6 * scale, 0, -42 * scale, 0), label, self.font("poppins_regular", 8.6 * scale), label_color)
            key_box = QRectF(row.right() - 34 * scale, row.top() + 2 * scale, 30 * scale, row.height() - 4 * scale)
            rounded_rect(p, key_box, 4 * scale, color("#ffffff", 0.045), color("#ffffff", 0.06))
            self.draw_text(p, key_box, "KEY", self.font("poppins_medium", 6.3 * scale), THEME.muted, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(row.adjusted(0, 0, -36 * scale, 0), "module_select", module.name, button=1, tooltip=module.description)
            self.add_hotspot(row.adjusted(0, 0, -36 * scale, 0), "module_bind", module.name, button=3, tooltip="绑定按键")
            self.add_hotspot(key_box, "module_bind", module.name, tooltip="绑定按键")
        p.restore()

    def draw_settings_area(self, p: QPainter, rect: QRectF, module: Module, scale: float) -> None:
        self._hotspot_clip = None
        self.draw_gui_cached_layer(
            p,
            rect,
            ("panel.settings.shell", round(scale, 3)),
            lambda layer, shell: rounded_rect(layer, shell, 4 * scale, color("#1a1a20", 0.92), color("#ffffff", 0.08)),
        )
        header = QRectF(rect.left() + 12 * scale, rect.top() + 9 * scale, rect.width() - 24 * scale, 29 * scale)
        self.draw_text(p, header.adjusted(0, 0, -72 * scale, 0), module.name, self.font("poppins_bold", 13.5 * scale), THEME.text)
        self.draw_toggle_switch(p, QRectF(rect.right() - 57 * scale, rect.top() + 13 * scale, 36 * scale, 16 * scale), module.enabled, ("module_toggle", module.name))

        content = rect.adjusted(10 * scale, 43 * scale, -10 * scale, -10 * scale)
        p.save()
        p.setClipRect(content)
        scroll = self.gui_motion.value(
            f"panel.settings-scroll.{module.name}",
            self.settings_scroll.get(module.name, 0.0),
            self.anim_duration(0.12),
            Easings.ease_out_cubic,
            initial=self.settings_scroll.get(module.name, 0.0),
        )
        y = content.top() - scroll
        y = self.draw_bind_row(p, QRectF(content.left(), y, content.width(), 27 * scale), module, scale, content)
        for setting in module.settings:
            y = self.draw_setting_row(p, setting, QRectF(content.left(), y, content.width(), 30 * scale), scale)
        if not module.settings:
            self.draw_text(p, QRectF(content.left(), y, content.width(), 44 * scale), module.description or "No settings", self.font("poppins_regular", 8.4 * scale), THEME.muted)
        p.restore()

    def draw_bind_row(self, p: QPainter, rect: QRectF, module: Module, scale: float, clip_rect: QRectF | None = None, compact: bool = False) -> float:
        visible = clip_rect is None or self.rect_visible(rect, clip_rect)
        if visible:
            content_rect = rect.adjusted(0, 2 * scale, 0, -3 * scale)
            rounded_rect(p, content_rect, 5 * scale, color("#ffffff", 0.03 if compact else 0.035), color("#ffffff", 0.055))
            if compact or rect.width() < 160 * scale:
                box_w = min(74.0 * scale, max(48.0 * scale, content_rect.width() * 0.52))
                box = QRectF(content_rect.right() - box_w - 6 * scale, content_rect.top() + 4 * scale, box_w, max(13.0 * scale, content_rect.height() - 8 * scale))
                label_rect = QRectF(content_rect.left() + 7 * scale, content_rect.top(), max(18.0 * scale, box.left() - content_rect.left() - 11 * scale), content_rect.height())
                self.draw_text(p, label_rect, "Keybind", self.font("poppins_regular", 7.0 * scale), THEME.muted)
                key_text = self.compact_keybind(module.keybind)
            else:
                self.draw_text(p, rect.adjusted(8 * scale, 0, -112 * scale, 0), "Keybind", self.font("poppins_regular", 8.4 * scale), THEME.muted)
                box = QRectF(rect.right() - 103 * scale, rect.top() + 5 * scale, 96 * scale, 18 * scale)
                key_text = module.keybind
            rounded_rect(p, box, 5 * scale, color("#ffffff", 0.055), color("#ffffff", 0.10))
            self.draw_text(p, box, key_text, self.font("poppins_medium", (6.9 if compact else 7.8) * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(box, "module_bind", module.name, tooltip="打开按键绑定覆盖层")
        return rect.bottom()

    def draw_setting_row(self, p: QPainter, setting: Setting, rect: QRectF, scale: float, compact: bool = False) -> float:
        if compact:
            return self.draw_compact_setting_row(p, setting, rect, scale)
        row_h = rect.height()
        content_rect = rect.adjusted(0, 2 * scale, 0, -3 * scale)
        rounded_rect(p, content_rect, 5 * scale, color("#ffffff", 0.03 if not compact else 0.02))
        label_font = self.font("poppins_regular", (8.2 if not compact else 7.4) * scale)
        value_font = self.font("poppins_medium", (7.8 if not compact else 7.0) * scale)
        self.draw_text(p, content_rect.adjusted(8 * scale, 0, -120 * scale, 0), setting.name, label_font, color("#d7d7dc"))
        if setting.kind == "bool":
            self.draw_toggle_switch(p, QRectF(content_rect.right() - 39 * scale, content_rect.top() + 6 * scale, 30 * scale, 13 * scale), bool(setting.value), ("setting_toggle", setting))
        elif setting.kind == "number":
            value = setting.display_value()
            self.draw_text(p, QRectF(content_rect.right() - 78 * scale, content_rect.top(), 70 * scale, content_rect.height() * 0.48), value, value_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            bar = QRectF(content_rect.left() + content_rect.width() * 0.42, content_rect.bottom() - 9 * scale, content_rect.width() * 0.52, 5 * scale)
            draw_bar(p, bar, setting.ratio(), THEME.pink, color("#ffffff", 0.17), 2.5 * scale)
            self.add_hotspot(bar.adjusted(-4 * scale, -7 * scale, 4 * scale, 7 * scale), "setting_slider", setting)
        elif setting.kind == "mode":
            box = QRectF(content_rect.right() - 112 * scale, content_rect.top() + 5 * scale, 103 * scale, content_rect.height() - 10 * scale)
            rounded_rect(p, box, 5 * scale, color("#303036", 0.95), color("#ffffff", 0.08))
            self.draw_text(p, box.adjusted(6 * scale, 0, -6 * scale, 0), str(setting.value), value_font, THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(box, "setting_mode_next", setting, tooltip="左键/右键循环切换")
        elif setting.kind == "action":
            button = content_rect.adjusted(8 * scale, 4 * scale, -8 * scale, -4 * scale)
            rounded_rect(p, button, 5 * scale, color("#ffffff", 0.92), color("#56fff0", 0.35))
            self.draw_text(p, button, setting.name, value_font, color("#090a0d"), Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(button, "config_action", setting.name, tooltip=setting.description)
        return rect.bottom()

    def draw_compact_setting_row(self, p: QPainter, setting: Setting, rect: QRectF, scale: float) -> float:
        content_rect = rect.adjusted(0, 1.5 * scale, 0, -2.0 * scale)
        if content_rect.height() < 5 * scale:
            return rect.bottom()
        rounded_rect(p, content_rect, 5 * scale, color("#ffffff", 0.022), color("#ffffff", 0.040))
        label_font = self.font("poppins_regular", 7.0 * scale)
        value_font = self.font("poppins_medium", 6.9 * scale)

        if setting.kind == "bool":
            switch = QRectF(content_rect.right() - 37 * scale, content_rect.top() + 5 * scale, 29 * scale, 13 * scale)
            label_rect = QRectF(content_rect.left() + 7 * scale, content_rect.top(), max(16.0 * scale, switch.left() - content_rect.left() - 11 * scale), content_rect.height())
            self.draw_text(p, label_rect, setting.name, label_font, color("#d7d7dc"))
            self.draw_toggle_switch(p, switch, bool(setting.value), ("setting_toggle", setting))
        elif setting.kind == "number":
            value = setting.display_value()
            bar = QRectF(content_rect.left() + 7 * scale, content_rect.bottom() - 6 * scale, content_rect.width() - 14 * scale, 4.2 * scale)
            value_w = min(58.0 * scale, max(36.0 * scale, content_rect.width() * 0.36))
            label_rect = QRectF(content_rect.left() + 7 * scale, content_rect.top() - 1 * scale, max(20.0 * scale, content_rect.width() - value_w - 18 * scale), content_rect.height() * 0.58)
            value_rect = QRectF(content_rect.right() - value_w - 7 * scale, content_rect.top() - 1 * scale, value_w, content_rect.height() * 0.58)
            self.draw_text(p, label_rect, setting.name, label_font, color("#d7d7dc"))
            self.draw_text(p, value_rect, value, value_font, THEME.text, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            draw_bar(p, bar, setting.ratio(), THEME.pink, color("#ffffff", 0.17), 2.1 * scale)
            self.add_hotspot(bar.adjusted(-5 * scale, -8 * scale, 5 * scale, 8 * scale), "setting_slider", setting)
        elif setting.kind == "mode":
            box_w = min(78.0 * scale, max(50.0 * scale, content_rect.width() * 0.55))
            box = QRectF(content_rect.right() - box_w - 6 * scale, content_rect.top() + 4 * scale, box_w, max(13.0 * scale, content_rect.height() - 8 * scale))
            label_rect = QRectF(content_rect.left() + 7 * scale, content_rect.top(), max(18.0 * scale, box.left() - content_rect.left() - 11 * scale), content_rect.height())
            self.draw_text(p, label_rect, setting.name, label_font, color("#d7d7dc"))
            rounded_rect(p, box, 5 * scale, color("#303036", 0.90), color("#ffffff", 0.08))
            self.draw_text(p, box.adjusted(4 * scale, 0, -4 * scale, 0), str(setting.value), value_font, THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(box, "setting_mode_next", setting, tooltip="左键/右键循环切换")
        elif setting.kind == "action":
            button = content_rect.adjusted(6 * scale, 4 * scale, -6 * scale, -4 * scale)
            rounded_rect(p, button, 5 * scale, color("#ffffff", 0.90), color("#56fff0", 0.28))
            self.draw_text(p, button, setting.name, value_font, color("#090a0d"), Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(button, "config_action", setting.name, tooltip=setting.description)
        return rect.bottom()

    def draw_search_bar(self, p: QPainter, rect: QRectF, scale: float) -> None:
        focus_v = self.anim.value("panel.search.focus", 1.0 if self.search_focus else 0.0, self.anim_duration(0.18), Easings.ease_out_quad)
        rounded_rect(p, rect, rect.height() / 2, color("#16161b", 0.92 + 0.06 * focus_v), color("#ffffff", 0.12 + 0.18 * focus_v))
        text = self.search_query if self.search_query else "Search modules..."
        self.draw_text(p, rect.adjusted(12 * scale, 0, -12 * scale, 0), text, self.font("poppins_regular", 7.8 * scale), THEME.text if self.search_query else color("#77777d"))
        self.add_hotspot(rect, "search_focus", None)

    def draw_old_gui(self, p: QPainter, width: int, height: int, _alpha: float) -> None:
        scale = self.get_gui_scale_for_bounds(width, height, 6 * 140.0 + 5 * 20.0, 520.0, 20.0, 54.0)
        panel_w = 140.0 * scale
        row_h = 20.0 * scale
        for i, category in enumerate(CATEGORIES):
            panel_data = self.old_panels[category]
            if not bool(panel_data.get("dragged", False)):
                panel_data["x"] = 20.0 * scale + i * 160.0 * scale
                panel_data["y"] = 20.0 * scale
            x = panel_data["x"]
            y = panel_data["y"]
            header = QRectF(x, y, panel_w, row_h)
            self.draw_gui_cached_layer(
                p,
                header.adjusted(-12 * scale, -12 * scale, 12 * scale, 12 * scale),
                ("old.header", category, round(scale, 3)),
                lambda layer, _shell: (
                    glow_rect(layer, header, 4 * scale, 0.12),
                    rounded_rect(layer, header, 3 * scale, color("#101014", 0.94), color("#ffffff", 0.12)),
                    self.draw_text(layer, header.adjusted(8 * scale, 0, -8 * scale, 0), f"{self.category_icon(category)}  {category}", self.font("poppins_bold", 8.2 * scale), THEME.text),
                ),
            )
            self.add_hotspot(header, "old_drag", category, button=1, tooltip="拖动面板")
            self.add_hotspot(header, "old_expand", category, button=3, tooltip="展开分类")

            expanded = bool(panel_data["expanded"])
            open_v = self.gui_motion.value(f"old.panel.{category}", 1.0 if expanded else 0.0, self.anim_duration(0.34), Easings.ease_out_expo)
            if open_v <= 0.01:
                continue
            yy = y + row_h
            p.save()
            modules = self.registry.by_category(category)
            total_height = sum(self.module_draw_height(module, scale, compact=True) for module in modules)
            p.setClipRect(QRectF(x, yy, panel_w, total_height * open_v).adjusted(-2 * scale, 0, 2 * scale, 2 * scale))
            for idx, module in enumerate(modules):
                row_reveal = self.gui_motion.waterfall(open_v, idx, len(modules))
                if row_reveal <= 0.025:
                    yy += self.module_draw_height(module, scale, compact=True)
                    continue
                slot_h = self.module_draw_height(module, scale, compact=True)
                row_clip = QRectF(x, yy, panel_w, row_h * row_reveal)
                row = QRectF(x + (1.0 - row_reveal) * 5.0 * scale, yy, panel_w - (1.0 - row_reveal) * 5.0 * scale, row_h)
                p.save()
                p.setClipRect(row_clip.adjusted(-2 * scale, -2 * scale, 2 * scale, 2 * scale))
                p.setOpacity(p.opacity() * row_reveal)
                enabled_v = self.anim.value(f"old.enabled.{module.name}", 1.0 if module.enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_cubic)
                # Match Polar Old's row treatment: enabled modules gain
                # a cool text tint, rather than being inverted into white bars.
                fill = color("#151515", 0.78 + 0.08 * enabled_v)
                rounded_rect(p, row, 0, fill, color("#ffffff", 0.035))
                fg = color("#b4f8ff") if module.enabled else color("#e5e5e8")
                self.draw_text(p, row.adjusted(8 * scale, 0, -32 * scale, 0), module.name, self.font("poppins_regular", 7.4 * scale), fg)
                key_box = QRectF(row.right() - 28 * scale, row.top() + 3 * scale, 23 * scale, row.height() - 6 * scale)
                self.draw_text(p, key_box, self.compact_keybind(module.keybind) if module.keybind and module.keybind != "None" else "--", self.font("poppins_bold", 6.5 * scale), THEME.muted, Qt.AlignmentFlag.AlignCenter)
                self.add_hotspot(row.adjusted(0, 0, -28 * scale, 0), "module_toggle", module.name, button=1, tooltip=module.description)
                self.add_hotspot(row.adjusted(0, 0, -28 * scale, 0), "module_expand", module.name, button=3, tooltip="展开设置")
                self.add_hotspot(key_box, "module_bind", module.name, tooltip="绑定按键")
                p.restore()
                exp = self.gui_motion.value(f"old.expand.{module.name}", 1.0 if module.name in self.module_expanded else 0.0, self.anim_duration(0.36), Easings.ease_out_expo)
                if exp > 0.01:
                    self.draw_inline_settings(p, module, QRectF(x + 5 * scale, row.bottom(), panel_w - 10 * scale, 0), scale, compact=True, max_rows=6, reveal=min(exp, row_reveal))
                yy += slot_h
            p.restore()

    def draw_new_gui(self, p: QPainter, width: int, height: int, _alpha: float) -> None:
        base_w = len(CATEGORIES) * 120.0 + (len(CATEGORIES) - 1) * 8.0
        scale = self.get_gui_scale_for_bounds(width, height, base_w, 430.0, 56.0, 118.0)
        gap = 8.0 * scale
        panel_w = 120.0 * scale
        total = len(CATEGORIES) * panel_w + (len(CATEGORIES) - 1) * gap
        start_x = width / 2 - total / 2
        y = 36.0 * scale if height >= 420.0 * scale else max(12.0 * scale, height * 0.08)
        max_h = min(430.0 * scale, max(180.0 * scale, height - y - 32.0 * scale))
        for i, category in enumerate(CATEGORIES):
            x = start_x + i * (panel_w + gap)
            enter = self.gui_motion.value(
                f"new.panel.{category}",
                1.0,
                self.anim_duration(0.30 + i * 0.035),
                Easings.ease_out_expo,
                initial=0.0,
            )
            modules = self.registry.by_category(category)
            content_h = 25 * scale + sum(self.module_draw_height(module, scale, compact=True) for module in modules)
            panel_h = min(max_h, max(72.0 * scale, content_h + 8 * scale))
            rect = QRectF(x, y + (1.0 - enter) * 9.0 * scale, panel_w, panel_h)
            p.save()
            p.setOpacity(p.opacity() * enter)
            self.draw_gui_cached_layer(
                p,
                rect.adjusted(-16 * scale, -16 * scale, 16 * scale, 16 * scale),
                ("new.panel.shell", category, round(scale, 3), round(panel_h, 2)),
                lambda layer, _shell: self.draw_new_panel_shell(layer, rect, category, scale),
            )
            p.restore()
            self.add_hotspot(rect.adjusted(0, 0, 0, -rect.height() + 24 * scale), "select_category", category, tooltip=category)
            p.save()
            clip = rect.adjusted(0, 26 * scale, 0, -4 * scale)
            p.setClipRect(clip)
            scroll = self.gui_motion.value(
                f"new.scroll.{category}",
                float(self.new_panels[category]["scroll"]),
                self.anim_duration(0.12),
                Easings.ease_out_cubic,
                initial=float(self.new_panels[category]["scroll"]),
            )
            yy = rect.top() + 27 * scale - scroll
            for module in modules:
                yy = self.draw_new_module_block(p, module, QRectF(rect.left(), yy, rect.width(), 0), scale)
            p.restore()

    def draw_new_panel_shell(self, p: QPainter, rect: QRectF, category: str, scale: float) -> None:
        glow_rect(p, rect, 8 * scale, 0.16)
        rounded_rect(p, rect, 7 * scale, color("#171717", 0.96), color("#ffffff", 0.08))
        top_line = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        top_line.setColorAt(0.0, color("#2de8ca"))
        top_line.setColorAt(1.0, color("#166f62"))
        p.fillRect(QRectF(rect.left() + 3 * scale, rect.top() + 1 * scale, rect.width() - 6 * scale, 2 * scale), top_line)
        self.draw_text(p, QRectF(rect.left() + 8 * scale, rect.top() + 3 * scale, rect.width() - 16 * scale, 22 * scale), category, self.font("poppins_bold", 8.0 * scale), THEME.text)

    def draw_new_module_block(self, p: QPainter, module: Module, origin: QRectF, scale: float) -> float:
        row = QRectF(origin.left() + 4 * scale, origin.top(), origin.width() - 8 * scale, 21 * scale)
        enabled_v = self.gui_motion.value(f"new.enabled.{module.name}", 1.0 if module.enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_cubic)
        fill = color("#202020", 0.28 + 0.12 * enabled_v)
        rounded_rect(p, row, 0, fill, color("#ffffff", 0.025))
        self.draw_text(p, row.adjusted(6 * scale, 0, -28 * scale, 0), module.name, self.font("poppins_regular", 7.2 * scale), color("#2de8ca") if module.enabled else color("#ffffff", 0.60))
        key_box = QRectF(row.right() - 24 * scale, row.top() + 3 * scale, 19 * scale, row.height() - 6 * scale)
        rounded_rect(p, key_box, 4 * scale, color("#ffffff", 0.04), color("#ffffff", 0.06))
        self.draw_text(p, key_box, self.compact_keybind(module.keybind) if module.keybind and module.keybind != "None" else "--", self.font("poppins_bold", 6.2 * scale), THEME.muted, Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(row.adjusted(0, 0, -24 * scale, 0), "module_toggle", module.name, button=1, tooltip=module.description)
        self.add_hotspot(row.adjusted(0, 0, -24 * scale, 0), "module_expand", module.name, button=3, tooltip="展开设置")
        self.add_hotspot(key_box, "module_bind", module.name, tooltip="绑定按键")
        yy = row.bottom()
        exp = self.gui_motion.value(f"new.expand.{module.name}", 1.0 if module.name in self.module_expanded else 0.0, self.anim_duration(0.34), Easings.ease_out_expo)
        if exp > 0.01:
            yy = self.draw_inline_settings(p, module, QRectF(row.left() + 4 * scale, yy + 2 * scale, row.width() - 8 * scale, 0), scale, compact=True, max_rows=5, reveal=exp)
        return yy + 2 * scale

    def draw_dropdown_gui(self, p: QPainter, width: int, height: int, _alpha: float) -> None:
        scale = self.get_gui_scale_for_bounds(width, height, 6 * 120.0 + 5 * 10.0 + 20.0, 470.0, 10.0, 38.0)
        gap = 10.0 * scale
        panel_w = 120.0 * scale
        x0 = 10.0 * scale
        y0 = 10.0 * scale
        for i, category in enumerate(CATEGORIES):
            x = x0 + i * (panel_w + gap)
            self.draw_dropdown_panel(p, category, QRectF(x, y0, panel_w, 0), scale)

    def draw_dropdown_panel(self, p: QPainter, category: str, origin: QRectF, scale: float) -> None:
        modules = self.registry.by_category(category)
        expanded = bool(self.dropdown_panels[category]["expanded"])
        open_v = self.gui_motion.value(f"dropdown.panel.{category}", 1.0 if expanded else 0.0, self.anim_duration(0.26), Easings.ease_out_expo)
        header_h = 28.0 * scale
        full_body_h = min(430.0 * scale, sum(self.module_draw_height(module, scale, compact=False) for module in modules) + 8 * scale)
        body_h = open_v * full_body_h
        rect = QRectF(origin.left(), origin.top(), origin.width(), header_h + body_h)
        shell = QRectF(origin.left(), origin.top(), origin.width(), header_h + full_body_h)
        p.save()
        p.setClipRect(rect.adjusted(-18 * scale, -18 * scale, 18 * scale, 18 * scale))
        self.draw_gui_cached_layer(
            p,
            shell.adjusted(-16 * scale, -16 * scale, 16 * scale, 16 * scale),
            ("dropdown.shell", category, round(scale, 3), round(full_body_h, 2)),
            lambda layer, _shell: (
                glow_rect(layer, shell, 8 * scale, 0.13),
                rounded_rect(layer, shell, 5 * scale, color("#0c0c0c", 0.57), color("#ffffff", 0.07)),
                rounded_rect(layer, QRectF(shell.left(), shell.top(), shell.width(), header_h), 5 * scale, color("#2a2a2a", 0.76)),
                self.draw_text(layer, QRectF(shell.left() + 12 * scale, shell.top(), shell.width() - 24 * scale, header_h), f"{self.category_icon(category)}  {category}", self.font("poppins_bold", 11.0 * scale), THEME.text),
            ),
        )
        p.restore()
        self.add_hotspot(QRectF(rect.left(), rect.top(), rect.width(), header_h), "dropdown_expand", category, button=3, tooltip="展开分类")
        if open_v <= 0.01:
            return
        p.save()
        p.setClipRect(QRectF(shell.left(), shell.top() + header_h, shell.width(), body_h))
        yy = rect.top() + header_h
        for idx, module in enumerate(modules):
            row_reveal = self.gui_motion.waterfall(open_v, idx, len(modules))
            if row_reveal <= 0.025:
                yy += self.module_draw_height(module, scale, compact=False)
                continue
            slot_h = self.module_draw_height(module, scale, compact=False)
            row_clip = QRectF(rect.left(), yy, rect.width(), 24 * scale * row_reveal)
            row = QRectF(rect.left() + (1.0 - row_reveal) * 6.0 * scale, yy, rect.width() - (1.0 - row_reveal) * 6.0 * scale, 24 * scale)
            p.save()
            p.setClipRect(row_clip.adjusted(0, -1 * scale, 0, 2 * scale))
            p.setOpacity(p.opacity() * row_reveal)
            if module.enabled:
                grad = QLinearGradient(row.left(), row.top(), row.right(), row.top())
                grad.setColorAt(0.0, accent_color(idx, time.perf_counter()))
                grad.setColorAt(1.0, accent_color(idx + 4, time.perf_counter()))
                p.fillRect(row, grad)
            else:
                rounded_rect(p, row, 0, color("#101412", 0.98), color("#ffffff", 0.06))
            self.draw_text(p, row.adjusted(12 * scale, 0, -34 * scale, 0), module.name, self.font("poppins_medium", 8.3 * scale), THEME.text)
            key_box = QRectF(row.right() - 29 * scale, row.top() + 4 * scale, 23 * scale, row.height() - 8 * scale)
            self.draw_text(p, key_box, self.compact_keybind(module.keybind) if module.keybind and module.keybind != "None" else "--", self.font("poppins_bold", 6.8 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(row.adjusted(0, 0, -31 * scale, 0), "module_toggle", module.name, button=1, tooltip=module.description)
            self.add_hotspot(row.adjusted(0, 0, -31 * scale, 0), "module_expand", module.name, button=3, tooltip="展开设置")
            self.add_hotspot(key_box, "module_bind", module.name, tooltip="绑定按键")
            p.restore()
            exp = self.gui_motion.value(f"dropdown.expand.{module.name}", 1.0 if module.name in self.module_expanded else 0.0, self.anim_duration(0.34), Easings.ease_out_expo)
            if exp > 0.01:
                self.draw_inline_settings(p, module, QRectF(row.left() + 9 * scale, row.bottom(), row.width() - 18 * scale, 0), scale, compact=False, max_rows=6, reveal=min(exp, row_reveal))
            yy += slot_h
        p.restore()

    def draw_inline_settings(self, p: QPainter, module: Module, origin: QRectF, scale: float, compact: bool, max_rows: int, reveal: float = 1.0) -> float:
        yy = origin.top()
        rows: list[tuple[str, Setting | None, float]] = [("bind", None, self.inline_bind_height(scale, compact))]
        rows.extend(("setting", setting, self.inline_setting_height(setting, scale, compact)) for setting in module.settings[:max_rows])
        for index, (kind, setting, row_h) in enumerate(rows):
            row_v = self.waterfall_reveal(reveal, index, len(rows))
            if row_v <= 0.025:
                continue
            clip_h = row_h * row_v
            slide = (1.0 - row_v) * (7.0 if compact else 9.0) * scale
            row_rect = QRectF(origin.left() + slide, yy, origin.width() - slide, row_h)
            clip = QRectF(origin.left(), yy, origin.width(), clip_h)
            p.save()
            p.setClipRect(clip.adjusted(-2 * scale, -2 * scale, 2 * scale, 3 * scale))
            p.setOpacity(p.opacity() * row_v)
            if kind == "bind":
                self.draw_bind_row(p, row_rect, module, scale, compact=compact)
            elif setting is not None:
                self.draw_setting_row(p, setting, row_rect, scale, compact=compact)
            p.restore()
            yy += clip_h
        return yy

    def module_draw_height(self, module: Module, scale: float, compact: bool) -> float:
        row_h = 21.0 * scale if compact else 24.0 * scale
        exp = self.gui_motion.value(f"height.expand.{module.name}", 1.0 if module.name in self.module_expanded else 0.0, self.anim_duration(0.36), Easings.ease_out_expo)
        settings_total = self.inline_bind_height(scale, compact) + sum(self.inline_setting_height(setting, scale, compact) for setting in module.settings[:6])
        return row_h + exp * settings_total + 2 * scale

    def inline_bind_height(self, scale: float, compact: bool) -> float:
        return (21.0 if compact else 24.0) * scale

    def inline_setting_height(self, setting: Setting, scale: float, compact: bool) -> float:
        if not compact:
            return 24.0 * scale
        if setting.kind == "number":
            return 26.0 * scale
        if setting.kind == "mode":
            return 23.0 * scale
        return 22.0 * scale

    def waterfall_reveal(self, reveal: float, index: int, total: int) -> float:
        return self.gui_motion.waterfall(reveal, index, total)

    def compact_keybind(self, keybind: str) -> str:
        aliases = {
            "RightShift": "RShift",
            "LeftShift": "LShift",
            "Control": "Ctrl",
            "Escape": "Esc",
        }
        return aliases.get(keybind, keybind)

    def draw_mode_switcher(self, p: QPainter, width: int, height: int) -> None:
        gap = 6.0
        margin = 18.0
        chip_w = min(128.0, (width - margin * 2 - gap * (len(GUI_MODES) - 1)) / len(GUI_MODES))
        total = len(GUI_MODES) * chip_w + (len(GUI_MODES) - 1) * gap
        x = max(margin, width - total - margin)
        y = max(12.0, height - 38.0)
        bg = QRectF(x - 8, y - 6, total + 16, 30)
        rounded_rect(p, bg, 8, color("#08080a", 0.82), color("#ffffff", 0.10))
        for i, mode in enumerate(GUI_MODES):
            rect = QRectF(x + i * (chip_w + gap), y, chip_w, 18)
            active = mode == self.mode_manager.mode
            active_v = self.anim.value(f"gui.mode.{mode}", 1.0 if active else 0.0, self.anim_duration(0.16), Easings.ease_out_quad)
            fill = color("#ffffff", 0.92 * active_v) if active_v > 0.01 else color("#1a1c22", 0.95)
            rounded_rect(p, rect, 5, fill, color("#ffffff", 0.10))
            text = self.gui_mode_label(mode)
            self.draw_text(p, rect.adjusted(5, 0, -5, 0), text, self.font("poppins_medium", 7.1), color("#08080a") if active else THEME.text, Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(rect, "gui_mode", mode)

    def draw_toasts(self, p: QPainter, width: int, _height: int) -> None:
        now = time.perf_counter()
        self.toasts = [toast for toast in self.toasts if now - toast["created"] < 3.0]
        for i, toast in enumerate(self.toasts[-5:]):
            age = now - toast["created"]
            fade = 1.0 if age < 2.35 else max(0.0, 1.0 - (age - 2.35) / 0.65)
            slide = Easings.ease_out_expo(min(1.0, age / self.anim_duration(0.22)))
            msg = toast["message"]
            kind, main = self.dynamic_message_kind(msg)
            title = self.dynamic_message_title(msg, kind)
            title_font = self.font("poppins_bold", 7.7)
            body_font = self.font("poppins_regular", 7.3)
            tw = max(210.0, min(430.0, max(QFontMetricsF(title_font).horizontalAdvance(title), QFontMetricsF(body_font).horizontalAdvance(msg)) + 58.0))
            if self.gui_visible:
                y = self.height() - 82.0 - i * 42.0 + (1.0 - slide) * 18.0
            else:
                y = 74.0 + i * 42.0 - (1.0 - slide) * 18.0
            rect = QRectF(width / 2 - tw / 2, y, tw, 36.0)
            p.save()
            p.setOpacity(fade)
            rounded_rect(p, rect.adjusted(-10, -10, 10, 10), 16, color("#000000", 0.035), None)
            rounded_rect(p, rect, 10, color("#050506", 0.74), color("#ffffff", 0.08))
            icon_rect = QRectF(rect.left() + 7, rect.top() + 6, 24, 24)
            icon_v = self.anim.value(f"toast.icon.{id(toast)}", 1.0 if age < 2.7 else 0.0, self.anim_duration(0.24), Easings.ease_out_expo, initial=0.0)
            self.draw_dynamic_island_icon(p, icon_rect, kind, main, icon_v)
            self.draw_text(p, QRectF(rect.left() + 39, rect.top() + 5, rect.width() - 48, 13), title, title_font, THEME.text)
            self.draw_text(p, QRectF(rect.left() + 39, rect.top() + 18, rect.width() - 48, 13), msg, body_font, THEME.muted)
            progress = max(0.0, 1.0 - age / 3.0)
            bar = QRectF(rect.left() + 8, rect.bottom() - 4.0, rect.width() - 16, 2.0)
            draw_bar(p, bar, progress, main, color("#ffffff", 0.10), 1.0)
            p.restore()

    def draw_keybind_overlay(self, p: QPainter, width: int, height: int) -> None:
        module = self.binding_module
        if module is None:
            return
        active = self.anim.value("keybind.overlay", 1.0, self.anim_duration(0.18), Easings.ease_out_pow3, initial=0.0)
        p.save()
        p.setOpacity(active)
        p.fillRect(QRectF(0, 0, width, height), color("#000000", 0.58))
        scale = 0.96 + 0.04 * active
        rect = QRectF(width / 2 - 200 * scale, height / 2 - 90 * scale, 400 * scale, 180 * scale)
        glow_rect(p, rect, 12 * scale, 0.46)
        rounded_rect(p, rect, 11 * scale, color("#0b0b0f", 0.97), color("#ffffff", 0.16))
        self.draw_text(p, QRectF(rect.left(), rect.top() + 28 * scale, rect.width(), 24 * scale), "KEYBIND", self.font("poppins_bold", 18 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
        self.draw_text(p, QRectF(rect.left(), rect.top() + 67 * scale, rect.width(), 21 * scale), module.name, self.font("poppins_medium", 11 * scale), THEME.cyan, Qt.AlignmentFlag.AlignCenter)
        self.draw_text(p, QRectF(rect.left(), rect.top() + 98 * scale, rect.width(), 20 * scale), "Press any key to bind", self.font("poppins_regular", 9 * scale), THEME.muted, Qt.AlignmentFlag.AlignCenter)
        phase = time.perf_counter() * 4.6
        for i in range(3):
            dot_alpha = 0.24 + 0.64 * (0.5 + 0.5 * math.sin(phase + i * 0.7))
            p.setBrush(color("#ffffff", dot_alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(rect.center().x() - 16 * scale + i * 16 * scale, rect.bottom() - 37 * scale), 3.3 * scale, 3.3 * scale)
        self.draw_text(p, QRectF(rect.left(), rect.bottom() - 24 * scale, rect.width(), 14 * scale), "ESC 清空绑定", self.font("poppins_regular", 7.4 * scale), color("#888890"), Qt.AlignmentFlag.AlignCenter)
        p.restore()

    def draw_toggle_switch(self, p: QPainter, rect: QRectF, enabled: bool, action: tuple[str, Any] | None = None) -> None:
        t = self.anim.value(f"toggle.{id(action[1]) if action else id(rect)}", 1.0 if enabled else 0.0, self.anim_duration(0.18), Easings.ease_out_cubic)
        fill = QColor(
            round(THEME.gray.red() + (THEME.green.red() - THEME.gray.red()) * t),
            round(THEME.gray.green() + (THEME.green.green() - THEME.gray.green()) * t),
            round(THEME.gray.blue() + (THEME.green.blue() - THEME.gray.blue()) * t),
            220,
        )
        rounded_rect(p, rect, rect.height() / 2, fill)
        knob = rect.height() - 4
        kx = rect.left() + 2 + (rect.width() - knob - 4) * t
        rounded_rect(p, QRectF(kx, rect.top() + 2, knob, knob), knob / 2, THEME.text)
        if action:
            self.add_hotspot(rect.adjusted(-4, -4, 4, 4), action[0], action[1])

    def draw_pill(self, p: QPainter, point: QPointF, text: str, c: QColor) -> None:
        font = self.font("poppins_medium", 8.0)
        p.setFont(font)
        w = max(92.0, QFontMetricsF(font).horizontalAdvance(text) + 18.0)
        rect = QRectF(point.x(), point.y(), w, 20)
        rounded_rect(p, rect, 7, color("#090a0d", 0.86), c, 1.1)
        self.draw_text(p, rect.adjusted(8, 0, -8, 0), text, font, c)

    def draw_tooltip(self, p: QPainter, point: QPointF, text: str) -> None:
        if not text:
            return
        font = self.font("poppins_regular", 8.0)
        p.setFont(font)
        text = self.elide(p, font, text, 340)
        tw = QFontMetricsF(font).horizontalAdvance(text) + 18
        x = min(point.x() + 14, self.width() - tw - 10)
        y = min(point.y() + 18, self.height() - 30)
        rect = QRectF(x, y, tw, 24)
        rounded_rect(p, rect, 6, color("#050506", 0.92), color("#ffffff", 0.14))
        self.draw_text(p, rect.adjusted(9, 0, -9, 0), text, font, THEME.text)

    def add_hotspot(self, rect: QRectF, action: str, payload: Any = None, button: int | None = None, tooltip: str = "") -> None:
        if rect.width() <= 0 or rect.height() <= 0:
            return
        clip = getattr(self, "_hotspot_clip", None)
        if clip is not None:
            rect = rect.intersected(clip)
            if rect.width() <= 0 or rect.height() <= 0:
                return
        self.hotspots.append(Hotspot(QRectF(rect), action, payload, button, tooltip))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self.binding_module is not None:
            return
        button = self.qt_button(event)
        point = event.position()
        if button == 1:
            self.liquid_press_point = QPointF(point)
            self.liquid_press_until = time.perf_counter() + 0.12
        for hotspot in reversed(self.hotspots):
            if hotspot.button not in (None, button):
                continue
            if hotspot.rect.contains(point):
                self.dispatch(hotspot.action, hotspot.payload, point, button, hotspot.rect)
                return
        if button == 1:
            self.search_focus = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        previous_tooltip = self.hover_tooltip
        previous_point = self.hover_point
        self.hover_point = event.position()
        self.hover_tooltip = ""
        hovered_action = ""
        for hotspot in reversed(self.hotspots):
            if hotspot.rect.contains(self.hover_point):
                self.hover_tooltip = hotspot.tooltip
                hovered_action = hotspot.action
                break
        # 启动页可见时渲染时钟已经按显示器刷新率运行；不再为每个原始
        # 鼠标事件强制整帧，仅在跨越热点、拖拽或提示变化时唤醒一帧。
        if (
            self.drag is not None
            or hovered_action != self._startup_last_hover_action
            or self.hover_tooltip != previous_tooltip
            or (not self.home_visible and (self.hover_point - previous_point).manhattanLength() > 6.0)
        ):
            self.frame_scheduler.force()
        self._startup_last_hover_action = hovered_action
        if self.drag is None:
            return
        point = event.position()
        if self.drag["type"] == "slider":
            setting: Setting = self.drag["setting"]
            rect: QRectF = self.drag["rect"]
            setting.set_from_ratio((point.x() - rect.left()) / max(1.0, rect.width()))
            self.after_setting_changed(setting)
        elif self.drag["type"] == "old_panel":
            panel = self.old_panels[self.drag["category"]]
            panel["dragged"] = True
            panel["x"] = point.x() - self.drag["offset_x"]
            panel["y"] = point.y() - self.drag["offset_y"]
        elif self.drag["type"] == "polar_window":
            panel = self.polar_windows[self.drag["category"]]
            panel["x"] = point.x() - self.drag["offset_x"]
            panel["y"] = point.y() - self.drag["offset_y"]

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        if self.drag and self.drag.get("type") in {"old_panel", "polar_window"}:
            self.auto_save_config()
        self.drag = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        point = event.position()
        delta = -event.angleDelta().y() / 120.0 * 28.0
        if self.mode_manager.mode == "PolarPanel" and self.panel_modules_rect.contains(point):
            modules = self.panel_modules()
            scale = self.get_gui_scale_for_bounds(self.width(), self.height(), 600.0, 440.0, 76.0, 82.0)
            row_h = 22.0 * scale
            clip_height = self.panel_modules_rect.height() - 36.0 * scale
            maximum = max(0.0, len(modules) * row_h - clip_height)
            key = self.selected_category
            current = self.panel_module_scroll.get(key, 0.0)
            self.panel_module_scroll[key] = max(0.0, min(maximum, current + delta))
            self.frame_scheduler.force()
            event.accept()
            return
        if self.mode_manager.mode == "PolarPanel" and self.panel_settings_rect.contains(point):
            key = self.selected_module.name
            self.settings_scroll[key] = max(0.0, self.settings_scroll.get(key, 0.0) + delta)
            self.frame_scheduler.force()
            event.accept()
            return
        for viewport in reversed(self.gui_scroll_viewports):
            if not viewport["rect"].contains(point):
                continue
            mode, key, maximum = viewport["mode"], viewport["key"], float(viewport["maximum"])
            if mode == "old":
                target = self.old_panels[key]
            elif mode == "new":
                target = self.new_panels[key]
            elif mode == "dropdown":
                target = self.dropdown_panels[key]
            elif mode == "polar_multi":
                target = self.polar_windows[key]
            elif mode == "polar_settings":
                motion = self.polar_settings_scroll_motion.setdefault(key, InertialScroll())
                motion.set_bounds(maximum)
                motion.add_wheel(delta)
                self.frame_scheduler.force()
                event.accept()
                return
            else:
                self.polar_unified_scroll_motion.set_bounds(maximum)
                self.polar_unified_scroll_motion.add_wheel(delta)
                self.frame_scheduler.force()
                event.accept()
                return
            target["scroll"] = max(0.0, min(maximum, float(target.get("scroll", 0.0)) + delta))
            self.frame_scheduler.force()
            event.accept()
            return

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.binding_module is not None:
            self.handle_keybind_event(event)
            return
        if self.home_visible and self.wallpaper_picker_visible:
            if event.key() == Qt.Key.Key_Escape:
                self.wallpaper_picker_visible = False
            return
        if self.home_visible:
            if self.handle_startup_key(event):
                return
        key_name = self.key_name(event)
        economy_module = self.registry.get("EconomyPanel")
        economy_key = bool(
            economy_module
            and economy_module.enabled
            and economy_module.keybind != "None"
            and self.keybind_matches(economy_module.keybind, key_name, event)
        )
        if event.key() == Qt.Key.Key_Escape and self.economy_visible:
            self.economy_visible = False
            self.frame_scheduler.force()
            return
        if economy_key and not event.isAutoRepeat() and not self.home_visible:
            self.economy_visible = not self.economy_visible
            self.gui_visible = False
            self.economy_opened_at = time.perf_counter()
            self.frame_scheduler.force()
            return
        if self.economy_visible:
            actions = available_actions(self.state)
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
                self.economy_selected = (self.economy_selected - 1) % max(1, len(actions))
                return
            if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
                self.economy_selected = (self.economy_selected + 1) % max(1, len(actions))
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and actions:
                action = actions[self.economy_selected]
                if action.enabled:
                    self.economy_bridge.submit(self.state, action, self.economy_quantity)
                    self.toast(f"经济请求已缓存：{action.title}")
                else:
                    self.toast(action.reason or "当前操作不可用")
                return
        if self.search_focus:
            if event.key() == Qt.Key.Key_Backspace:
                self.search_query = self.search_query[:-1]
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.search_focus = False
            elif event.key() == Qt.Key.Key_Escape:
                self.search_focus = False
            elif event.text() and event.text().isprintable():
                self.search_query += event.text()
            return
        if event.key() == Qt.Key.Key_F8 or self.is_right_shift_event(event):
            self.gui_visible = not self.gui_visible
            self.play_gui_transition_sound("expand" if self.gui_visible else "collapse")
            self.toast("ClickGUI 已打开" if self.gui_visible else "ClickGUI 已关闭")
            return
        if event.key() == Qt.Key.Key_F9:
            mode = self.mode_manager.next_mode()
            self.module_expanded.clear()
            self.play_gui_transition_sound("expand")
            self.sync_mode_setting()
            self.toast(f"GUI 模式：{mode}")
            return
        if event.key() == Qt.Key.Key_Escape and self.gui_visible:
            self.gui_visible = False
            return
        if self.handle_tactical_map_hold_event(event, True):
            return
        if self.handle_control_key_event(event, True):
            return
        for module in self.registry.modules:
            if module.keybind != "None" and self.keybind_matches(module.keybind, key_name, event):
                self.registry.toggle_module(module, source="keybind")
                self.selected_module = module
                self.toast(f"{module.name} {'已启用' if module.enabled else '已关闭'}")
                self.auto_save_config()
                return

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if self.binding_module is not None or self.search_focus:
            return
        if self.handle_tactical_map_hold_event(event, False):
            return
        self.handle_control_key_event(event, False)

    def handle_tactical_map_hold_event(self, event: QKeyEvent, pressed: bool) -> bool:
        module = self.registry.get("TacticalMap")
        if module is None:
            return False
        key_name = self.key_name(event)
        is_tab_view_key = event.key() == Qt.Key.Key_Tab
        is_bound_view_key = module.keybind != "None" and self.keybind_matches(module.keybind, key_name, event)
        if not is_tab_view_key and not is_bound_view_key:
            return False
        if not event.isAutoRepeat():
            self.tactical_map_hold = pressed and module.enabled
        return True

    def handle_control_key_event(self, event: QKeyEvent, pressed: bool) -> bool:
        if event.isAutoRepeat():
            return False
        key = self.key_name(event)
        serial_module = self.registry.get("SerialBridge")
        mock_setting = serial_module.get_setting("Mock Writes") if serial_module else None
        self.control.mock_output = bool(mock_setting.value) if mock_setting else True
        command = self.control.set_key(key, pressed, self.state, self.registry)
        if command is None:
            return False
        if pressed and time.perf_counter() - self.last_control_toast > 1.2:
            self.toast("WASD -> 模拟底盘命令" if command.mock_output else "WASD -> 底盘命令已发送")
            self.last_control_toast = time.perf_counter()
        return True

    def handle_keybind_event(self, event: QKeyEvent) -> None:
        module = self.binding_module
        if module is None:
            return
        if event.key() == Qt.Key.Key_Escape:
            module.keybind = "None"
            self.binding_module = None
            self.anim.value("keybind.overlay", 0.0, self.anim_duration(0.16), Easings.ease_out_quad)
            self.toast(f"{module.name} 按键绑定已清空")
            self.auto_save_config()
            return
        name = self.key_name(event)
        if not name:
            return
        module.keybind = name
        self.binding_module = None
        self.toast(f"{module.name} 已绑定到 {name}")
        self.auto_save_config()

    def dispatch(self, action: str, payload: Any, point: QPointF, button: int, rect: QRectF) -> None:
        if action in {
            "module_toggle", "module_select", "module_expand", "setting_toggle", "setting_slider",
            "setting_mode_next", "select_category", "gui_mode", "old_expand", "dropdown_expand", "polar_drag",
        }:
            self.invalidate_gui_cache()
        if action == "module_toggle":
            module = self.registry.get(str(payload))
            if module:
                self.registry.toggle_module(module, source="clickgui")
                self.selected_module = module
                self.toast(f"{module.name} {'已启用' if module.enabled else '已关闭'}")
                self.auto_save_config()
        elif action == "module_select":
            module = self.registry.get(str(payload))
            if module:
                self.selected_module = module
        elif action == "module_expand":
            name = str(payload)
            if name in self.module_expanded:
                self.module_expanded.remove(name)
            else:
                self.module_expanded.add(name)
            self.auto_save_config()
        elif action == "module_bind":
            module = self.registry.get(str(payload))
            if module:
                self.binding_module = module
                self.anim.value("keybind.overlay", 0.0, 0.01, Easings.linear, initial=0.0)
        elif action == "setting_toggle":
            setting: Setting = payload
            setting.value = not bool(setting.value)
            self.after_setting_changed(setting)
        elif action == "setting_slider":
            setting = payload
            setting.set_from_ratio((point.x() - rect.left()) / max(1.0, rect.width()))
            self.drag = {"type": "slider", "setting": setting, "rect": rect}
            self.after_setting_changed(setting)
        elif action == "setting_mode_next":
            setting = payload
            setting.cycle(-1 if button == 3 else 1)
            self.after_setting_changed(setting)
        elif action == "select_category":
            self.selected_category = str(payload)
        elif action == "search_focus":
            self.search_focus = True
        elif action == "gui_mode":
            self.mode_manager.set_mode(str(payload))
            self.module_expanded.clear()
            self.sync_mode_setting()
            self.play_gui_transition_sound("expand")
            self.toast(f"GUI 模式：{payload}")
            self.auto_save_config()
        elif action == "old_expand":
            self.old_panels[str(payload)]["expanded"] = not bool(self.old_panels[str(payload)]["expanded"])
            self.auto_save_config()
        elif action == "old_drag" and button == 1:
            panel = self.old_panels[str(payload)]
            panel["dragged"] = True
            self.drag = {
                "type": "old_panel",
                "category": str(payload),
                "offset_x": point.x() - float(panel["x"]),
                "offset_y": point.y() - float(panel["y"]),
            }
        elif action == "polar_drag" and button == 1:
            panel = self.polar_windows[str(payload)]
            self.drag = {
                "type": "polar_window",
                "category": str(payload),
                "offset_x": point.x() - float(panel["x"]),
                "offset_y": point.y() - float(panel["y"]),
            }
        elif action == "dropdown_expand":
            self.dropdown_panels[str(payload)]["expanded"] = not bool(self.dropdown_panels[str(payload)]["expanded"])
            self.auto_save_config()
        elif action == "select_scenario":
            self.apply_scenario(str(payload), close_home=False)
            self.reset_startup_page_animation("match")
            self.begin_startup_page_transition("match")
            self.auto_save_config()
        elif action == "select_match_mode":
            self.apply_match_mode(str(payload), close_home=False)
            self.reset_startup_page_animation("robot")
            self.begin_startup_page_transition("robot")
            self.auto_save_config()
        elif action == "select_robot_profile":
            self.apply_robot_profile(str(payload), close_home=True)
            self.auto_save_config()
        elif action == "config_action":
            self.handle_config_action(str(payload))
        elif action == "startup_back":
            self.reset_startup_page_animation("scenario")
            self.begin_startup_page_transition("scenario")
        elif action == "startup_back_match":
            self.reset_startup_page_animation("match")
            self.begin_startup_page_transition("match")
        elif action == "startup_open_gui":
            self.home_visible = False
            self.startup_step = "done"
            self.gui_visible = True
            self.toast("ClickGUI opened from launcher")
        elif action == "startup_open_config":
            config_module = self.registry.get("ConfigManager")
            self.selected_category = "System"
            if config_module:
                self.selected_module = config_module
            self.home_visible = False
            self.startup_step = "done"
            self.gui_visible = True
            self.toast("ConfigManager opened from launcher")
        elif action == "startup_open_wallpaper":
            self.wallpaper_picker_visible = True
            profiles = self.startup_wallpaper.profile_names()
            visual_module = self.registry.get("StartupVisual")
            current = self.setting_mode(visual_module, "Wallpaper Profile", "TexasMP4")
            self.wallpaper_picker_page = profiles.index(current) // 4 if current in profiles else 0
        elif action == "wallpaper_select":
            self.apply_wallpaper_profile(str(payload))
        elif action == "wallpaper_import":
            self.import_wallpaper_from_dialog()
        elif action == "wallpaper_remove":
            self.remove_wallpaper_profile(str(payload))
        elif action == "wallpaper_reset":
            self.reset_wallpaper_profile()
        elif action == "wallpaper_page":
            count = max(1, math.ceil(len(self.startup_wallpaper.profile_names()) / 4))
            self.wallpaper_picker_page = max(0, min(count - 1, self.wallpaper_picker_page + int(payload)))
        elif action == "wallpaper_close":
            self.wallpaper_picker_visible = False
        elif action == "wallpaper_block":
            pass
        elif action == "economy_select":
            self.economy_selected = max(0, int(payload))
            self.frame_scheduler.force()
        elif action == "economy_submit":
            actions = available_actions(self.state)
            index = max(0, min(len(actions) - 1, int(payload))) if actions else 0
            if actions and actions[index].enabled:
                request = self.economy_bridge.submit(self.state, actions[index], self.economy_quantity)
                self.toast(f"经济请求已缓存：{actions[index].title} · {request.cost} 金币")
            elif actions:
                self.toast(actions[index].reason or "当前操作不可用")
        elif action == "economy_close":
            self.economy_visible = False
            self.frame_scheduler.force()
        elif action == "startup_exit":
            self.close()

    def after_setting_changed(self, setting: Setting) -> None:
        self.invalidate_gui_cache()
        scenario = self.registry.get("Scenario")
        if scenario and setting is scenario.get_setting("Mode"):
            self.apply_scenario(str(setting.value), close_home=False)
            self.auto_save_config()
            return
        match_mode = self.registry.get("MatchMode")
        if match_mode and setting is match_mode.get_setting("Mode"):
            self.apply_match_mode(str(setting.value), close_home=False)
            self.auto_save_config()
            return
        alliance_profile = self.registry.get("AllianceProfile")
        if alliance_profile and setting is alliance_profile.get_setting("Side"):
            self.state.alliance_color = str(setting.value)
            self.vision_kill_detector.reset()
            self.toast(f"阵营：{setting.value}")
            self.auto_save_config()
            return
        if match_mode and setting is match_mode.get_setting("Alliance"):
            self.state.alliance_color = str(setting.value)
            if alliance_profile:
                side = alliance_profile.get_setting("Side")
                if side:
                    side.value = setting.value
            self.vision_kill_detector.reset()
            self.auto_save_config()
            return
        robot_profile = self.registry.get("RobotProfile")
        if robot_profile and setting in robot_profile.settings:
            self.apply_robot_profile(self.current_robot_profile_key(), close_home=False, announce=False)
            self.auto_save_config()
            return
        click_gui = self.registry.get("ClickGui")
        if click_gui and setting is click_gui.get_setting("Mode"):
            self.mode_manager.set_mode(str(setting.value))
            self.module_expanded.clear()
            self.play_gui_transition_sound("expand")
            self.toast(f"GUI 模式：{setting.value}")
        hud = self.registry.get("HUD")
        if hud and setting is hud.get_setting("Right Display"):
            self.toast(f"右侧 HUD：{setting.value}")
        config_manager = self.registry.get("ConfigManager")
        if config_manager and setting is config_manager.get_setting("Profile"):
            self.reload_current_config()
            return
        elimination_fx = self.registry.get("EliminationFX")
        if elimination_fx and setting is elimination_fx.get_setting("Preset"):
            self.kill_fx.preload_preset_sounds(str(setting.value))
        self.auto_save_config()

    def handle_config_action(self, action_name: str) -> None:
        if action_name == "Save Current":
            self.save_current_config()
        elif action_name == "Reload Profile":
            self.reload_current_config()
        elif action_name == "Import Config":
            self.import_config_from_dialog()
        elif action_name == "Import Wallpaper":
            self.import_wallpaper_from_dialog()
        elif action_name == "Reset Wallpaper":
            self.reset_wallpaper_profile()
        elif action_name == "Restore Compact HUD":
            self.restore_compact_hud()
        elif action_name in ("Capture Chessboard", "Solve Calibration", "Export Tongji YAML"):
            self.handle_calibration_action(action_name)
        elif action_name in ("Preview FX", "Test Elimination"):
            self.preview_elimination_fx(single=action_name == "Test Elimination")
        elif action_name in ("Import Enable Sound", "Import Disable Sound", "Import Invalid Sound"):
            slot = action_name.removeprefix("Import ").removesuffix(" Sound").lower()
            self.import_custom_ui_sound(slot)
        elif action_name.startswith("Preview ") and action_name in (
            "Preview Enable", "Preview Disable", "Preview Invalid"
        ):
            audio = self.registry.get("AudioFeedback")
            volume = self.get_setting_number(audio, "UI Volume", 45.0)
            self.ui_audio.preview(
                action_name.removeprefix("Preview ").lower(),
                volume,
                self.setting_mode(audio, "Sound Theme", "Polar UI"),
                self.custom_ui_sound_selection(audio),
            )

    def restore_compact_hud(self) -> None:
        """Restore compact visuals without changing behavior or connection settings."""
        hud = self.registry.get("HUD")
        tactical_map = self.registry.get("TacticalMap")
        values = (
            (hud, "Density", "CombatCompact"),
            (hud, "Visual Tone", "LiquidClean"),
            (hud, "Target Style", "RoundCompact"),
            (tactical_map, "Map Size", "Compact"),
            (tactical_map, "Chrome", "Minimal"),
            (tactical_map, "Status Display", "LiquidAuto"),
        )
        for module, name, value in values:
            setting = module.get_setting(name) if module else None
            if setting is not None and (not setting.options or value in setting.options):
                setting.value = value
        self.invalidate_gui_cache()
        self.tactical_map_cached_rect = QRectF()
        self.toast("Compact HUD restored")
        self.auto_save_config()

    def on_module_toggled(self, module: Module, enabled: bool, source: str) -> None:
        self.invalidate_gui_cache()
        audio = self.registry.get("AudioFeedback")
        active = bool(
            audio
            and (audio.enabled or module is audio)
            and self.setting_bool(audio, "Enabled", True)
            and self.setting_bool(audio, "Module Toggle Sounds", True)
        )
        self.ui_audio.module_toggled(
            enabled,
            source,
            active=active,
            volume=self.get_setting_number(audio, "UI Volume", 45.0),
            theme=self.setting_mode(audio, "Sound Theme", "Polar UI"),
            custom_sounds=self.custom_ui_sound_selection(audio),
        )

    def play_gui_transition_sound(self, kind: str) -> None:
        audio = self.registry.get("AudioFeedback")
        if not audio or not self.setting_bool(audio, "Enabled", True):
            return
        self.ui_audio.gui_feedback(
            kind,
            self.get_setting_number(audio, "UI Volume", 45.0),
            self.setting_mode(audio, "Sound Theme", "Polar UI"),
        )

    def preview_elimination_fx(self, *, single: bool = False) -> None:
        module = self.registry.get("EliminationFX")
        sequence = "Single" if single else self.setting_mode(module, "Preview Sequence", "Normal 1-6")
        if sequence == "All Kill Types":
            types = ["NORMAL", "HEADSHOT", "EXPLOSION", "CRIT", "ASSIST", "DESTROY_VEHICLE"]
        elif sequence == "Single":
            types = ["NORMAL"]
        else:
            types = ["NORMAL"] * 6
        for index, kill_type in enumerate(types):
            event = CombatEvent(
                "elimination", "preview", True, time.perf_counter(),
                victim_id=101 + index,
                detail="local_preview",
                kill_type=kill_type,
                combo=index + 1,
                victim_name=f"ROBOT {101 + index}",
                distance_m=8.0 + index,
                score_delta=100,
                tags=("ELIMINATION", "ARMOR HIT") if kill_type != "DESTROY_VEHICLE" else ("ROBOT DESTROYED",),
            )
            QTimer.singleShot(index * 650, lambda queued=event: self.accept_combat_event(queued))

    def handle_calibration_action(self, action_name: str) -> None:
        module = self.registry.get("CameraCalibration")
        name = self.setting_mode(module, "Profile", "polar_webcam")
        columns = int(self.get_setting_number(module, "Board Columns", 9))
        rows = int(self.get_setting_number(module, "Board Rows", 6))
        square_size = self.get_setting_number(module, "Square Size", 25.0)
        if action_name == "Capture Chessboard":
            frame = self.camera_worker.latest_frame()
            if frame is not None and self.calibration.capture(frame.bgr, columns, rows, square_size):
                self.toast(f"Calibration sample {self.calibration.sample_count}: corners locked")
            else:
                self.toast(self.calibration.last_error or "Chessboard capture failed", kind="warning")
            return
        if action_name == "Solve Calibration":
            profile = self.calibration.solve(name, columns, rows, square_size)
            if profile is None:
                self.toast(self.calibration.last_error or "Calibration solve failed", kind="warning")
            else:
                self.toast(f"Calibration solved: {profile.rms_error_px:.2f}px RMS")
            return
        bridge_module = self.registry.get("TongjiVisionBridge")
        device = self.setting_mode(bridge_module, "Inference Device", "AUTO")
        path = self.calibration.export_tongji_yaml(name, device)
        if path is None:
            self.toast(self.calibration.last_error or "Tongji YAML export failed", kind="warning")
        else:
            self.toast(f"Tongji YAML exported: {path.name}")

    def handle_startup_key(self, event: QKeyEvent) -> bool:
        if self.startup_step == "robot":
            if event.key() == Qt.Key.Key_Backspace:
                self.reset_startup_page_animation("match")
                self.begin_startup_page_transition("match")
                return True
            profiles = profiles_for_match(self.match_mode_manager.current.key)
            mapping = {getattr(Qt.Key, f"Key_{index + 1}"): profile.key for index, profile in enumerate(profiles[:9])}
            mapping[Qt.Key.Key_Return] = self.current_robot_profile_key()
            mapping[Qt.Key.Key_Enter] = self.current_robot_profile_key()
            key = mapping.get(event.key())
            if key is None:
                return False
            self.apply_robot_profile(str(key), close_home=True)
            self.auto_save_config()
            return True
        if self.startup_step == "match":
            if event.key() == Qt.Key.Key_Backspace:
                self.reset_startup_page_animation("scenario")
                self.begin_startup_page_transition("scenario")
                return True
            mapping = {
                Qt.Key.Key_1: "RMUC7v7",
                Qt.Key.Key_2: "RMUL3v3",
                Qt.Key.Key_Return: self.match_mode_manager.current.key,
                Qt.Key.Key_Enter: self.match_mode_manager.current.key,
            }
            key = mapping.get(event.key())
            if key is None:
                return False
            self.apply_match_mode(str(key), close_home=False)
            self.reset_startup_page_animation("robot")
            self.begin_startup_page_transition("robot")
            self.auto_save_config()
            return True
        mapping = {
            Qt.Key.Key_1: "OfficialEvent",
            Qt.Key.Key_2: "CampusSimulation",
            Qt.Key.Key_3: "LabDebug",
            Qt.Key.Key_Return: self.scenario_manager.current.key,
            Qt.Key.Key_Enter: self.scenario_manager.current.key,
        }
        key = mapping.get(event.key())
        if key is None:
            return False
        self.apply_scenario(str(key), close_home=False)
        self.reset_startup_page_animation("match")
        self.begin_startup_page_transition("match")
        self.auto_save_config()
        return True

    def apply_scenario(self, key: str, close_home: bool) -> None:
        config = self.scenario_manager.set_scenario(key)
        self.scenario_manager.apply_to_registry(self.registry)
        self.scenario_manager.apply_to_runtime(self.mqtt, self.udp, self.control)
        if close_home:
            self.home_visible = False
            self.gui_visible = False
        self.toast(f"Scenario: {config.title}")

    def apply_match_mode(self, key: str, close_home: bool, announce: bool = True) -> None:
        config = self.match_mode_manager.set_mode(key)
        self.match_mode_manager.apply_to_registry(self.registry)
        self.seed_match_state(config)
        profile_module = self.registry.get("RobotProfile")
        role_setting = profile_module.get_setting("Role") if profile_module else None
        if role_setting is not None:
            role_setting.options = [profile.key for profile in profiles_for_match(config.key)]
            if str(role_setting.value) not in role_setting.options:
                role_setting.value = role_setting.options[0]
        if close_home:
            self.home_visible = False
            self.gui_visible = False
            self.startup_step = "done"
        if announce:
            self.toast(f"Match mode: {config.title}")

    def apply_robot_profile(self, key: str, close_home: bool, announce: bool = True) -> None:
        module = self.registry.get("RobotProfile")
        profiles = profiles_for_match(self.match_mode_manager.current.key)
        valid_keys = [profile.key for profile in profiles]
        profile = profile_by_key(self.match_mode_manager.current.key, key)
        role = module.get_setting("Role") if module else None
        if role is not None:
            role.options = valid_keys
            role.value = profile.key
        performance = self.current_robot_performance(profile.key)
        level = int(self.get_setting_number(module, "Level", 1))
        apply_profile_to_state(self.state, profile, performance, level)
        if close_home:
            self.home_visible = False
            self.gui_visible = False
            self.startup_step = "done"
            self.refresh_vision_runtime()
        if announce:
            self.toast(f"Robot profile: {profile.title}")

    def seed_match_state(self, config: MatchModeConfig) -> None:
        self.state.match_mode = config.key
        self.state.match_title = config.title
        self.state.match_duration_sec = config.duration_sec
        self.state.stage_countdown_sec = config.duration_sec
        self.state.stage_elapsed_sec = 0
        self.state.start_time = time.perf_counter()
        self.state.current_stage = "MATCH"
        match_module = self.registry.get("MatchMode")
        alliance = match_module.get_setting("Alliance") if match_module else None
        self.state.alliance_color = str(alliance.value) if alliance else "Red"
        if config.key == "RMUL3v3":
            self.state.ally_victory_points = 200
            self.state.enemy_victory_points = 200
            self.state.control_owner = "NEUTRAL"
            self.state.control_progress = 0
            self.state.base_health = 0
            self.state.enemy_base_health = 0
            self.state.outpost_health = 0
            self.state.enemy_outpost_health = 0
        else:
            self.state.base_health = self.state.base_max_health
            self.state.enemy_base_health = self.state.enemy_base_max_health
            self.state.outpost_health = self.state.outpost_max_health
            self.state.enemy_outpost_health = self.state.enemy_outpost_max_health

    def refresh_config_profiles(self) -> None:
        module = self.registry.get("ConfigManager")
        setting = module.get_setting("Profile") if module else None
        if setting is None:
            return
        names = self.config_store.profile_names()
        current = str(setting.value)
        setting.options = names
        setting.value = current if current in names else names[0]

    def refresh_wallpaper_profiles(self) -> None:
        module = self.registry.get("StartupVisual")
        setting = module.get_setting("Wallpaper Profile") if module else None
        if setting is None:
            return
        names = self.startup_wallpaper.profile_names()
        current = str(setting.value)
        setting.options = names
        setting.value = current if current in names else names[0]

    def refresh_custom_ui_sound_options(self) -> None:
        module = self.registry.get("AudioFeedback")
        if module is None:
            return
        options = [UiAudioManager.NO_SOUND, *self.ui_audio.custom_sound_names()]
        for name in ("Custom Enable Sound", "Custom Disable Sound", "Custom Invalid Sound"):
            setting = module.get_setting(name)
            if setting is None:
                continue
            current = str(setting.value)
            setting.options = options
            setting.value = current if current in options else UiAudioManager.NO_SOUND

    def custom_ui_sound_selection(self, module: Module | None = None) -> dict[str, str]:
        audio = module or self.registry.get("AudioFeedback")
        return {
            kind: self.setting_mode(audio, f"Custom {kind.title()} Sound", UiAudioManager.NO_SOUND)
            for kind in ("enable", "disable", "invalid")
        }

    def import_custom_ui_sound(self, kind: str) -> None:
        if kind not in UiAudioManager.CUSTOM_KINDS:
            return
        start = str(self.ui_audio.custom_dir)
        filters = "Audio files (*.wav *.ogg *.mp3 *.flac *.m4a *.aac)"
        path, _ = QFileDialog.getOpenFileName(self, f"Import {kind} sound", start, filters)
        if not path:
            return
        try:
            selected = self.ui_audio.import_custom_sound(Path(path), kind)
        except (OSError, ValueError) as exc:
            self.toast(f"Sound import failed: {exc}", kind="warning")
            return
        self.refresh_custom_ui_sound_options()
        audio = self.registry.get("AudioFeedback")
        setting = audio.get_setting(f"Custom {kind.title()} Sound") if audio else None
        if setting is not None:
            setting.value = selected
        self.toast(f"Custom {kind} sound ready")
        self.auto_save_config()

    def import_wallpaper_from_dialog(self) -> None:
        start = str(self.workspace / "rm_custom_client" / "assets" / "wallpapers")
        filters = "Wallpaper media (*.mp4 *.webm *.mov *.avi *.mkv *.gif *.png *.jpg *.jpeg)"
        path, _ = QFileDialog.getOpenFileName(self, "Import startup wallpaper", start, filters)
        if not path:
            return
        try:
            profile = self.startup_wallpaper.import_wallpaper(Path(path))
        except (OSError, ValueError) as exc:
            self.toast(f"Wallpaper import failed: {exc}")
            return
        self.refresh_wallpaper_profiles()
        module = self.registry.get("StartupVisual")
        if module:
            profile_setting = module.get_setting("Wallpaper Profile")
            mode_setting = module.get_setting("Background Mode")
            if profile_setting:
                profile_setting.value = profile
            if mode_setting:
                mode_setting.value = "VideoParallax"
        profiles = self.startup_wallpaper.profile_names()
        self.wallpaper_picker_page = profiles.index(profile) // 4 if profile in profiles else 0
        self.toast(f"Wallpaper loaded: {profile}")
        self.auto_save_config()

    def apply_wallpaper_profile(self, profile: str) -> None:
        if profile not in self.startup_wallpaper.profile_names():
            self.toast("壁纸资源不存在，已保留当前壁纸")
            return
        module = self.registry.get("StartupVisual")
        if module is None:
            return
        profile_setting = module.get_setting("Wallpaper Profile")
        mode_setting = module.get_setting("Background Mode")
        if profile_setting:
            profile_setting.value = profile
        if mode_setting:
            if profile == "ParticleGrid":
                mode_setting.value = "ParticleGrid"
            elif profile == "Default3000925581Pkg":
                mode_setting.value = "PkgScene"
            else:
                mode_setting.value = "VideoParallax"
        self.toast(f"壁纸已切换：{self.startup_wallpaper.profile_label(profile)}")
        self.auto_save_config()

    def remove_wallpaper_profile(self, profile: str) -> None:
        if not self.startup_wallpaper.can_remove(profile):
            self.toast("内置壁纸不能删除")
            return
        if not self.startup_wallpaper.remove_wallpaper(profile):
            self.toast("删除壁纸失败")
            return
        self.refresh_wallpaper_profiles()
        self.apply_wallpaper_profile("TexasMP4")
        count = max(1, math.ceil(len(self.startup_wallpaper.profile_names()) / 4))
        self.wallpaper_picker_page = min(self.wallpaper_picker_page, count - 1)
        self.toast("用户壁纸已删除")

    def reset_wallpaper_profile(self) -> None:
        self.apply_wallpaper_profile("TexasMP4")
        self.wallpaper_picker_page = 0

    def current_profile(self) -> str:
        module = self.registry.get("ConfigManager")
        setting = module.get_setting("Profile") if module else None
        return self.config_store.clean_profile_name(str(setting.value if setting else "default"))

    def current_config_data(self) -> dict[str, Any]:
        return export_client_config(
            self.registry,
            gui_mode=self.mode_manager.mode,
            selected_category=self.selected_category,
            selected_module=self.selected_module.name if self.selected_module else "",
            module_expanded=self.module_expanded,
            old_panels=self.old_panels,
            new_panels=self.new_panels,
            dropdown_panels=self.dropdown_panels,
            polar_windows=self.polar_windows,
        )

    def load_startup_config(self) -> None:
        module = self.registry.get("ConfigManager")
        if not self.setting_bool(module, "Load On Start", True):
            return
        data = self.config_store.load(self.current_profile())
        if data:
            self.apply_config_data(data, announce=False)

    def apply_config_data(self, data: dict[str, Any], announce: bool = True) -> None:
        self.config_loading = True
        try:
            self.refresh_wallpaper_profiles()
            self.refresh_custom_ui_sound_options()
            apply_registry_config(self.registry, data)
            gui_mode = normalize_gui_mode(str(data.get("gui_mode", self.mode_manager.mode)))
            self.mode_manager.set_mode(gui_mode)
            self.selected_category = str(data.get("selected_category", self.selected_category))
            selected_name = str(data.get("selected_module", self.selected_module.name if self.selected_module else ""))
            selected = self.registry.get(selected_name)
            if selected:
                self.selected_module = selected
            expanded = data.get("module_expanded")
            if isinstance(expanded, list):
                self.module_expanded = {str(name) for name in expanded}
            for target, key in ((self.old_panels, "old_panels"), (self.new_panels, "new_panels"), (self.dropdown_panels, "dropdown_panels")):
                value = data.get(key)
                if isinstance(value, dict):
                    for name, panel_data in value.items():
                        if name in target and isinstance(panel_data, dict):
                            target[name].update(panel_data)
            polar_data = data.get("polar_windows", data.get("vape_windows"))
            if isinstance(polar_data, dict):
                for name, panel_data in polar_data.items():
                    if name in self.polar_windows and isinstance(panel_data, dict):
                        self.polar_windows[name].update(panel_data)
            self.sync_runtime_from_registry()
            self.sync_mode_setting()
            self.refresh_config_profiles()
            self.refresh_wallpaper_profiles()
        finally:
            self.config_loading = False
        if announce:
            self.toast(f"配置已加载：{self.current_profile()}")

    def sync_runtime_from_registry(self) -> None:
        scenario = self.registry.get("Scenario")
        scenario_setting = scenario.get_setting("Mode") if scenario else None
        if scenario_setting:
            self.scenario_manager.set_scenario(str(scenario_setting.value))
            self.scenario_manager.apply_to_runtime(self.mqtt, self.udp, self.control)
        match_mode = self.registry.get("MatchMode")
        match_setting = match_mode.get_setting("Mode") if match_mode else None
        if match_setting:
            config = self.match_mode_manager.set_mode(str(match_setting.value))
            self.seed_match_state(config)
        self.apply_robot_profile(self.current_robot_profile_key(), close_home=False, announce=False)
        self.home_visible = self.setting_bool(scenario, "Show Startup", True)
        self.startup_step = "scenario" if self.home_visible else "done"

    def save_current_config(self, announce: bool = True) -> None:
        path = self.config_store.save(self.current_profile(), self.current_config_data())
        self.refresh_config_profiles()
        if announce:
            self.toast(f"配置已保存：{path.name}")

    def reload_current_config(self) -> None:
        data = self.config_store.load(self.current_profile())
        if data is None:
            self.toast("配置重新加载失败")
            return
        self.apply_config_data(data)

    def import_config_from_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入 POLAR-RM 配置", str(self.config_store.config_dir), "JSON 配置 (*.json)")
        if not path:
            return
        try:
            profile = self.config_store.import_file(Path(path))
        except (OSError, ValueError) as exc:
            self.toast(f"Import failed: {exc}")
            return
        self.refresh_config_profiles()
        module = self.registry.get("ConfigManager")
        setting = module.get_setting("Profile") if module else None
        if setting:
            setting.value = profile
        self.reload_current_config()

    def auto_save_config(self) -> None:
        module = self.registry.get("ConfigManager")
        if self.config_loading or not self.setting_bool(module, "Auto Save", True):
            return
        self.save_current_config(announce=False)

    def sync_mode_setting(self) -> None:
        click_gui = self.registry.get("ClickGui")
        if click_gui:
            mode = click_gui.get_setting("Mode")
            if mode:
                mode.value = self.mode_manager.mode

    def panel_modules(self) -> list[Module]:
        if self.search_query:
            query = self.search_query.lower()
            return sorted([m for m in self.registry.modules if query in m.name.lower()], key=lambda module: module.name.lower())
        return self.registry.by_category(self.selected_category)

    def get_setting_number(self, module: Module | None, name: str, default: float) -> float:
        setting = module.get_setting(name) if module else None
        if setting is None:
            return default
        try:
            return float(setting.value)
        except (TypeError, ValueError):
            return default

    def get_auto_ui_scale(self, width: int | None = None, height: int | None = None, strength: float = 1.0) -> float:
        module = self.registry.get("UIScale")
        if not module or not module.enabled or not self.setting_bool(module, "Auto Scale", True):
            return 1.0
        width = self.width() if width is None else width
        height = self.height() if height is None else height
        ref_width = max(320.0, self.get_setting_number(module, "Reference Width", 1280.0))
        ref_height = max(240.0, self.get_setting_number(module, "Reference Height", 720.0))
        raw = math.sqrt(max(1.0, width * height) / (ref_width * ref_height))
        raw = max(0.82, min(1.85, raw))
        if raw < 1.0:
            return raw
        softened = 1.0 + (raw - 1.0) * max(0.0, min(1.0, strength))
        return max(0.82, min(1.85, softened))

    def get_hud_scale(self, width: int | None = None, height: int | None = None) -> float:
        module = self.registry.get("UIScale")
        manual = self.get_setting_number(module, "HUD Scale", 1.0)
        auto_scale = self.get_auto_ui_scale(width, height, strength=0.80)
        if self.high_res_optimize(width, height):
            auto_scale = min(auto_scale, 1.34)
        return max(0.55, min(2.4, manual * auto_scale))

    def high_res_optimize(self, width: int | None = None, height: int | None = None) -> bool:
        module = self.registry.get("UIScale")
        if not self.setting_bool(module, "High Res Optimize", True):
            return False
        width = self.width() if width is None else width
        height = self.height() if height is None else height
        return width * height >= 3_000_000

    def video_sample_size(self, width: int, height: int) -> tuple[int, int]:
        if not self.high_res_optimize(width, height):
            return (width, height)
        max_pixels = 1920 * 1080
        pixels = max(1, width * height)
        if pixels <= max_pixels:
            return (width, height)
        scale = math.sqrt(max_pixels / pixels)
        return (max(320, int(width * scale)), max(180, int(height * scale)))

    def get_gui_scale(self) -> float:
        module = self.registry.get("ClickGui")
        setting = module.get_setting("Scale") if module else None
        ui_module = self.registry.get("UIScale")
        gui_scale = self.get_setting_number(ui_module, "GUI Scale", 1.0)
        base = float(setting.value if setting else 1.0)
        return max(0.55, min(1.85, base * gui_scale * self.get_auto_ui_scale(strength=0.52)))

    def draw_gui_cached_layer(
        self,
        painter: QPainter,
        rect: QRectF,
        key: tuple[object, ...],
        build,
    ) -> None:
        module = self.registry.get("ClickGui")
        if self.setting_mode(module, "Render Backend", "Unified GPU") == "Compatibility Painter":
            build(painter, QRectF(rect))
            return

        def local_build(layer: QPainter, local_rect: QRectF) -> None:
            layer.save()
            layer.translate(-rect.left(), -rect.top())
            build(layer, QRectF(rect))
            layer.restore()

        try:
            self.gui_cache.draw(
                painter,
                rect,
                key,
                local_build,
                device_pixel_ratio=self.devicePixelRatioF(),
            )
        except Exception:
            # 缓存层异常时立即退回直接绘制，交互界面不能因显卡兼容性失效。
            setting = module.get_setting("Render Backend") if module else None
            if setting is not None:
                setting.value = "Compatibility Painter"
            self.gui_cache.clear()
            build(painter, QRectF(rect))

    def invalidate_gui_cache(self) -> None:
        self.gui_cache.clear()

    def get_gui_scale_for_bounds(
        self,
        width: int,
        height: int,
        base_width: float,
        base_height: float,
        margin_x: float,
        margin_y: float,
    ) -> float:
        scale = self.get_gui_scale()
        max_w = (width - margin_x) / max(1.0, base_width)
        max_h = (height - margin_y) / max(1.0, base_height)
        return max(0.55, min(scale, max_w, max_h, 1.85))

    def anim_duration(self, base: float) -> float:
        module = self.registry.get("UIScale")
        speed = self.get_setting_number(module, "Animation Speed", 1.0)
        return max(0.01, base / max(0.2, speed))

    def setting_bool(self, module: Module | None, setting_name: str, default: bool = False) -> bool:
        setting = module.get_setting(setting_name) if module else None
        return bool(setting.value) if setting else default

    def setting_mode(self, module: Module | None, setting_name: str, default: str) -> str:
        setting = module.get_setting(setting_name) if module else None
        return str(setting.value) if setting else default

    def category_icon(self, category: str) -> str:
        return {
            "Combat": "X",
            "Movement": ">",
            "Vision": "O",
            "Strategy": "#",
            "System": "*",
            "Render": "E",
        }.get(category, "?")

    @staticmethod
    def gui_mode_label(mode: str) -> str:
        return {
            "PolarOld": "P Old",
            "PolarPanel": "P Panel",
            "PolarNew": "P New",
            "PolarDropdown": "P Drop",
            "PolarUnified": "Polar One",
            "PolarMulti": "Polar Multi",
        }.get(mode, mode)

    def toast(self, message: str) -> None:
        self.toasts.append({"message": message, "created": time.perf_counter()})
        self.state.push_event(message)

    def font(self, key: str, size: float, weight: QFont.Weight | None = None) -> QFont:
        return self.fonts.font(key, max(1.0, size), weight)

    def draw_text(
        self,
        p: QPainter,
        rect: QRectF,
        text: str,
        font: QFont,
        c: QColor,
        flags: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        p.setFont(font)
        p.setPen(c)
        clipped = self.elide(p, font, text, rect.width())
        p.drawText(rect, int(flags), clipped)

    def draw_glass_text(
        self,
        p: QPainter,
        rect: QRectF,
        text: str,
        font: QFont,
        c: QColor,
        flags: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        """透明镜片上的最小文字保护，不引入额外暗色面板。"""
        self.draw_text(p, rect.translated(0.80, 0.95), text, font, color("#071018", 0.68), flags)
        self.draw_text(p, rect, text, font, c, flags)

    def elide(self, p: QPainter, font: QFont, text: str, width: float) -> str:
        p.setFont(font)
        return p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(1, int(width)))

    def rect_visible(self, rect: QRectF, clip: QRectF) -> bool:
        return rect.intersects(clip)

    def qt_button(self, event: QMouseEvent) -> int:
        if event.button() == Qt.MouseButton.RightButton:
            return 3
        if event.button() == Qt.MouseButton.MiddleButton:
            return 2
        return 1

    def key_name(self, event: QKeyEvent) -> str:
        key = event.key()
        special = {
            Qt.Key.Key_Space: "Space",
            Qt.Key.Key_Tab: "Tab",
            Qt.Key.Key_Backspace: "Backspace",
            Qt.Key.Key_Return: "Enter",
            Qt.Key.Key_Enter: "Enter",
            Qt.Key.Key_Escape: "Escape",
            Qt.Key.Key_Shift: "RightShift" if self.is_right_shift_event(event) else "Shift",
            Qt.Key.Key_Control: "Ctrl",
            Qt.Key.Key_Alt: "Alt",
        }
        if key in special:
            return special[key]
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            return f"F{key - Qt.Key.Key_F1 + 1}"
        text = event.text()
        if text and text.isprintable():
            return text.upper()
        seq = QKeySequence(key).toString()
        return seq or ""

    def keybind_matches(self, bind: str, key_name: str, event: QKeyEvent) -> bool:
        normalized_bind = bind.strip().lower()
        normalized_key = key_name.strip().lower()
        if normalized_bind == normalized_key:
            return True
        if normalized_bind == "tab" and event.key() == Qt.Key.Key_Tab:
            return True
        if normalized_bind == "rightshift" and self.is_right_shift_event(event):
            return True
        return False

    def is_right_shift_event(self, event: QKeyEvent) -> bool:
        if event.key() != Qt.Key.Key_Shift:
            return False
        if event.nativeVirtualKey() == 161:
            return True
        # PySide/Qt 可能把左右 Shift 都上报为 VK_SHIFT(16)。
        # 在 Windows 上，右 Shift 通常仍会保留 0x36 硬件扫描码。
        if event.nativeScanCode() == 0x36:
            return True
        return False


def main() -> None:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        surface = QSurfaceFormat()
        surface.setVersion(3, 3)
        surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
        # 不让 30/60 Hz 图传或错误报告为 60 Hz 的桌面刷新率锁住 HUD。
        # 呈现节奏由 FrameScheduler 控制，视频纹理只在源帧变化时上传。
        # Present at the display cadence.  Unthrottled swaps were racing the
        # launcher FBO lifecycle on high-DPR Windows surfaces.
        surface.setSwapInterval(1)
        surface.setDepthBufferSize(0)
        surface.setStencilBufferSize(0)
        QSurfaceFormat.setDefaultFormat(surface)
        app = QApplication(sys.argv)
    app.setApplicationName("POLAR-RM Custom Client")
    window = PolarRMWindow()
    window.show()
    if owns_app:
        raise SystemExit(app.exec())
