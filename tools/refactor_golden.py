"""Golden-frame display-regression safety net for the polar_app.py refactor.

 WHY
----
ui/polar_app.py (~16.8k lines) is about to be split into multiple modules
under the hard constraint "display output changes zero pixels".  This tool
captures a set of deterministic golden frames from the REAL render pipeline
(QSurfaceFormat(3,3 Core) -> QApplication -> PolarRMWindow ->
frame_scheduler.force()+update()+processEvents() -> grabFramebuffer(), same
driver pattern as tools/visual_audit.py and the tmp_corner_verify forensic
scripts), and re-captures them later to pixel-diff against the baseline.

 USAGE (for refactorers)
-------------------------
After finishing EACH refactor stage, run:

    .\\.venv\\Scripts\\python.exe tools\\refactor_golden.py compare

Exit code 0 + "ALL FRAMES PASS" means the display is still bit-compatible
with the pre-refactor baseline (within AA noise).  Any FAIL prints the frame
name, offending pixel count / max channel delta and saves a diff
visualization PNG next to the report.  Re-generate the baseline ONLY on
purposeful visual changes, and say so in the PR:

    .\\.venv\\Scripts\\python.exe tools\\refactor_golden.py capture

Subcommands:
    capture   [--out DIR] [--only SUBSTR]   record golden frames into DIR
    compare   [--baseline DIR] [--out DIR]  recapture + pixel-diff vs baseline
    calibrate [--out DIR]                   capture twice, self-compare,
                                            report the GPU noise floor

 DETERMINISM MODEL (how "same state" is guaranteed across runs)
-----------------------------------------------------------------
1. Static backdrop: CameraFeed.Source="Synthetic" + a fixed synthetic QImage
   injected into window.frame_image/frame_pixmap (tools/visual_audit.py
   recipe); StartupVisual "Background Mode"="Static" on launcher pages.
2. Mock telemetry disabled (window.state.mock_simulation_enabled=False right
   after construction) so HUD numbers stay at dataclass defaults instead of
   drifting with wall-clock demo simulation.  ``state.start_time`` is also
   pinned relative to the frozen clock during every grab: MockVisionPipeline
   derives its target geometry from ``perf_counter() - start_time`` even when
   telemetry ticking is disabled, so leaving the constructor timestamp live
   made the target rectangle—and every blur sampling it—change between runs.
3. Frozen paint clock: every wall-clock read goes through time.perf_counter()
   (polar_app, animation.GuiMotionController/AnimationBank, kill_fx, model)
   or time.time() (rm_client.ui.paint.rainbow_color / rainbow_color_index --
   the HUD RGB cycle of polar module-list rows).  During the grab we patch
   BOTH to FIXED constants (FROZEN=1e9, TIME_FROZEN=2e9 -- always beyond any
   real reading, so duration-based animations evaluate as fully completed,
   stored-timestamp ages stay positive, and parity/hue-bucket terms like
   int(now*2)%2 or millis//speed%360 become constants).  Tick dt is pinned via
   window.last_frame_time=FROZEN so spring integrators take only tiny 1 ms
   steps and quiesce; logic/control gates (_last_logic_time,
   _last_control_tick_time) are pinned so backend stages stop.  All pins are
   restored to the real clock on exit.
   NOTE on StartupVisual "Background Mode": the value "Static" is NOT static
   -- startup_wallpaper.py treats it like VideoParallax and keeps playing the
   TexasMP4 video (real-time decode => different frames per run).  This tool
   therefore uses "ParticleGrid", which is fully procedural and reproducible
   once the paint clock is frozen.
4. Every state is driven to an exact rest condition before the freeze
   (timelines progress==1 / velocity==0, scroll positions pinned, economy
   island morph forced, tactical-map spring stepped manually with a FIXED
   iteration count while its own tick is no-op'd -- the verified recipe from
   tmp_corner_verify/verify_map_corners.py).
5. Kill-FX age is pinned exactly: after triggering through the real
   VisionKillDetector -> accept_combat_event path, the anchor timestamp is
   read back from kill_fx.scrolling.icons[-1].started and kill_fx.draw is
   instance-wrapped to inject now_override=anchor+KILL_AGE, so the effect is
   frozen mid-animation at a reproducible age regardless of grab timing.
6. random.seed(FIXED_SEED): kill_fx ValorantRenderer picks self.spin via
   random.choice; seeding makes even unused paths reproducible.
7. Fresh empty POLAR_USER_DATA_ROOT per run: every run starts from factory
   settings, immune to config drift.

 CALIBRATED NOISE FLOOR (capture twice -> self-compare, see `calibrate`)
--------------------------------------------------------------------------
Measured on the dev machine (1920x1080 logical @ dpr 1.5 -> 2880x1581 device,
OpenGL 3.3 Core, swap interval 1), 2026-09, `calibrate` run twice
independently:

    01_startup_scenario     0 changed pixels   (bitwise identical)
    02_startup_match        0 changed pixels   (bitwise identical)
    03_startup_robot        0 changed pixels   (bitwise identical)
    04_hud_idle            20 changed pixels, max channel delta 1 (AA jitter)
    05_official_map        20 changed pixels, max channel delta 1 (AA jitter)
    06_kill_fx              0 changed pixels   (bitwise identical)
    07_jello_gui_midscroll  0 changed pixels   (bitwise identical)
    08_economy_island_offer 0 changed pixels   (bitwise identical)

i.e. worst fail-pixels(>CHAN_TOL) = 0, worst channel delta = 1 -- the frozen
clock + forced background/static-cache rebuilds remove not just animation
phase noise but nearly all AA jitter as well, because the rasterizer sees
byte-identical geometry each run.  The compare tolerance is deliberately
conservative to absorb driver variation while still catching regressions:

    FAIL iff  (changed pixels > 0) AND (max channel delta > GOLDEN_CHANNEL_TOL)

    GOLDEN_CHANNEL_TOL = 8   (absorbs <=8/255 AA/blending jitter;
                              real regressions - moved/missing/recolorred
                              UI - produce deltas of tens to 255)

If your machine shows nonzero-but-tiny noise (a few hundred pixels at
delta<=8), that is expected and PASSES; if you see deltas >8 on an UNCHANGED
tree, your render backend differs from the baseline environment (different
GPU/driver/"Render Backend" setting) -- regenerate the baseline locally
instead of chasing phantom failures.

 STATE COVERAGE (8 states)
---------------------------
 01_startup_scenario     launcher scenario menu, entrance stagger settled
 02_startup_match        launcher match page (page morph completed)
 03_startup_robot        launcher robot page (page morph completed)
 04_hud_idle             HUD idle over synthetic backdrop, GUI closed
 05_official_map         expanded tactical map island w/ official RMUC asset
 06_kill_fx              vision-kill EliminationFX frame @ fixed age 0.55 s
 07_jello_gui_midscroll  JelloSigma ClickGUI open, busiest category scrolled
                         to middle (rounded-corner/scrollbar paths)
 08_economy_island_offer economy island expanded, category + offer selected

A state that cannot be reached deterministically is SKIPPED with the reason
recorded in manifest.json / the compare report -- an unstable state is never
used as a baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Hermetic user-data: every run starts from factory defaults and cannot
# pollute (or be polluted by) the developer's real config.
USER_DATA_PARENT = ROOT / "tmp_corner_verify"
USER_DATA_PARENT.mkdir(parents=True, exist_ok=True)
os.environ["POLAR_USER_DATA_ROOT"] = str(
    Path(tempfile.mkdtemp(prefix="golden_userdata_", dir=str(USER_DATA_PARENT)))
)

import numpy as np  # noqa: E402  (venv has numpy 2.x)

# ---------------------------------------------------------------- constants
FROZEN = 1_000_000_000.0          # frozen perf_counter value (> any real one)
FIXED_MOCK_ELAPSED = 7.25          # deterministic MockVision target phase
# Frozen wall-clock for time.time() consumers (rm_client.ui.paint.rainbow_color
# drives HUD RGB cycles from epoch millis). Must be a FIXED constant across
# runs (absolute-time terms like millis//speed%360 must be identical) and above
# any real epoch (~1.79e9 in 2026) so stored-timestamp ages stay positive.
TIME_FROZEN = 2_000_000_000.0
FIXED_SEED = 20260922
WINDOW_W, WINDOW_H = 1920, 1080
FREEZE_PUMPS = 900                 # forced frames while the clock is frozen
                                   # (lets any residual frozen-clock spring
                                   # motion fully converge -> run-invariant)
CHAN_TOL = 8                       # GOLDEN_CHANNEL_TOL, see docstring
KILL_AGE = 0.55                    # seconds into the kill-FX animation
DEFAULT_BASELINE = ROOT / "tmp_corner_verify" / "golden_baseline_v1"

FRAME_NAMES = (
    "01_startup_scenario",
    "02_startup_match",
    "03_startup_robot",
    "04_hud_idle",
    "05_official_map",
    "06_kill_fx",
    "07_jello_gui_midscroll",
    "08_economy_island_offer",
)


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------ frozen clock
def _frozen_perf_counter() -> float:
    return FROZEN


def _frozen_time() -> float:
    return TIME_FROZEN


class FrozenClock:
    """Patch time.perf_counter to a constant for the duration of one grab."""

    def __init__(self, window) -> None:
        self.window = window
        self._saved_pc = time.perf_counter
        self._saved_time = time.time
        self._pins: dict[str, float] = {}
        self._saved_state_start_time: float | None = None

    def __enter__(self) -> "FrozenClock":
        w = self.window
        for attr in (
            "last_frame_time",
            "_last_logic_time",
            "_last_control_tick_time",
            "_last_present_time",
        ):
            try:
                self._pins[attr] = float(getattr(w, attr))
            except Exception:
                pass
            setattr(w, attr, FROZEN)
        # never let a frozen tick trigger a config write
        try:
            w._auto_save_pending = False
            w._auto_save_due_at = FROZEN + 1.0e6
        except Exception:
            pass
        # Force the background FBO to rebuild under the frozen clock: the
        # procedural synthetic-video scene (particles, drifting stars, the
        # wandering fake-robot card) is painted from time.perf_counter() but
        # cached in an FBO keyed only by size -- without this reset every run
        # would bake a different real-time sample into the baseline.
        for attr in ("_gpu_background_key", "_gpu_blur_source_key"):
            try:
                setattr(w, attr, None)
            except Exception:
                pass
        try:
            w.synthetic_video_cache = None
        except Exception:
            pass
        # MockVisionPipeline is intentionally rendered by the golden states.
        # It does not consume RobotState.tick(), but it does animate from the
        # dataclass construction timestamp.  Pin that origin so two fresh
        # windows render the exact same target and therefore the same Jello
        # blur source.
        try:
            self._saved_state_start_time = float(w.state.start_time)
            w.state.start_time = FROZEN - FIXED_MOCK_ELAPSED
        except Exception:
            self._saved_state_start_time = None
        # Pin the wallpaper parallax (integrated against the real clock during
        # settle); a run-dependent residual would shift glass refraction by a
        # sub-pixel and produce sparse edge noise.
        try:
            wp = getattr(w, "startup_wallpaper", None)
            if wp is not None:
                wp.parallax_x = 0.0
                wp.parallax_y = 0.0
        except Exception:
            pass
        time.perf_counter = _frozen_perf_counter  # type: ignore[assignment]
        time.time = _frozen_time  # type: ignore[assignment]
        return self

    def __exit__(self, *exc) -> None:
        time.perf_counter = self._saved_pc  # type: ignore[assignment]
        time.time = self._saved_time  # type: ignore[assignment]
        if self._saved_state_start_time is not None:
            try:
                self.window.state.start_time = self._saved_state_start_time
            except Exception:
                pass
        now = self._saved_pc()
        for attr in (
            "last_frame_time",
            "_last_logic_time",
            "_last_control_tick_time",
            "_last_present_time",
        ):
            try:
                setattr(self.window, attr, now)
            except Exception:
                pass


# ------------------------------------------------------------- app bootstrap
def build_window():
    """QSurfaceFormat(3,3 Core) + QApplication + PolarRMWindow, ready to show.

    Returns (app, window).  Raises on GL-less desktops (caller may fall back
    to QT_QPA_PLATFORM=offscreen like tmp_corner_verify scripts do).
    """
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    surface = QSurfaceFormat()
    surface.setVersion(3, 3)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)

    from rm_client.ui.polar_app import PolarRMWindow

    app = QApplication.instance() or QApplication(sys.argv)
    random.seed(FIXED_SEED)
    window = PolarRMWindow()
    window.resize(WINDOW_W, WINDOW_H)

    cam = window.registry.get("CameraFeed")
    if cam and cam.get_setting("Source"):
        cam.get_setting("Source").value = "Synthetic"  # static backdrop owner
    sv = window.registry.get("StartupVisual")
    if sv and sv.get_setting("Background Mode"):
        # ParticleGrid is fully procedural (no TexasMP4 video decode), so the
        # launcher backdrop is reproducible once the paint clock is frozen.
        sv.get_setting("Background Mode").value = "ParticleGrid"
    # Freeze mock telemetry at dataclass defaults (no wall-clock drift).
    window.state.mock_simulation_enabled = False
    return app, window


def make_bg(w: int = 1280, h: int = 720):
    """Static synthetic camera backdrop (identical to tools/visual_audit.py)."""
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(w, h, QImage.Format.Format_RGB888)
    p = QPainter(image)
    p.fillRect(0, 0, w, h, QColor("#1c2c3a"))
    p.fillRect(0, 0, w // 2, h, QColor("#152432"))
    p.fillRect(560, 300, 160, 80, QColor("#3a4a5a"))
    p.setPen(QColor("#66aadd"))
    p.drawRect(560, 300, 160, 80)
    p.end()
    return image


def apply_static_backdrop(window) -> None:
    from PySide6.QtGui import QPixmap

    bg = make_bg()
    window.frame_image = bg
    window.frame_pixmap = QPixmap.fromImage(bg)
    window._last_capture_sequence += 1


def pump_real(app, window, seconds: float) -> None:
    """Settle loop on the REAL clock: animations converge toward rest."""
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        window.update()
        app.processEvents()
        time.sleep(0.03)


def freeze_grab(app, window, name: str | None, out_dir: Path | None = None):
    """Deterministic grab: pin clocks -> N forced frames at FROZEN -> grab."""
    with FrozenClock(window):
        for _ in range(FREEZE_PUMPS):
            window.frame_scheduler.force()
            window.update()
            app.processEvents()
        # Pin the FPS readout: state.fps is recomputed from REAL present
        # intervals at the end of every paint; the text is baked into BOTH the
        # watermark QImage cache and the "battle-ui"/"startup-ui" static GPU
        # layer, so invalidate those caches and repaint once at fps=1000.0
        # (every frozen paint appends a 1 ms sample -> samples converge to
        # exactly 1000.0 regardless of real timing).
        try:
            window.state.fps = 1000.0
            window._watermark_title_cache_key = None
            # the watermark refresh gate is "now >= next_refresh_at"; under the
            # frozen clock the first frozen paint already consumed the gate, so
            # re-open it to force one rebuild with the pinned fps
            window._watermark_cache_next_refresh_at = 0.0
            window._gpu_static_ui_key = None
        except Exception:
            pass
        window.frame_scheduler.force()
        window.update()
        app.processEvents()
        img = window.grabFramebuffer()
    if img.isNull():
        raise RuntimeError("grabFramebuffer returned a null image")
    if name and out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        img.save(str(out_dir / f"{name}.png"), "PNG")
        log(f"  captured {name}.png ({img.width()}x{img.height()})")
    return img


# ------------------------------------------------------------- kill helpers
def _lit_armor():
    from rm_client.vision import ArmorObservation

    return ArmorObservation(
        103, "three", "blue", 0.93,
        ((560.0, 300.0), (720.0, 300.0), (720.0, 380.0), (560.0, 380.0)),
        light_strength=0.82, light_state="lit", target_id=7,
    )


def _extinguish_armor():
    from rm_client.vision import ArmorObservation

    return ArmorObservation(
        103, "three", "extinguish", 0.91,
        ((562.0, 302.0), (718.0, 302.0), (718.0, 378.0), (562.0, 378.0)),
        light_strength=0.12, light_state="extinguished", target_id=7,
    )


def trigger_vision_kill(window):
    """Drive the real VisionKillDetector until it emits an elimination event,
    then feed it through window.accept_combat_event (exact timeline of
    tools/visual_audit.py phase_kill_ui, which is known to produce events).
    Returns the kill-fx anchor timestamp (started) or None."""
    from rm_client.combat_events import VisionKillDetector

    bridge = window.registry.get("TongjiVisionBridge")
    if bridge and bridge.get_setting("Vision Kill Sensitivity"):
        bridge.get_setting("Vision Kill Sensitivity").value = "Lab Responsive"
    det = VisionKillDetector()
    for i in range(3):  # warm lit frames (t = 100.00 / 100.15 / 100.30)
        det.process([_lit_armor()], alliance="Red", frame_luminance=0.4,
                    frame_token=900 + i, frame_size=(1280, 720),
                    now=100.0 + i * 0.15)
    event = None
    for i in range(8):  # extinguish sequence (t = 100.60 + i*0.10) -> event
        events = det.process([_extinguish_armor()], alliance="Red",
                             frame_luminance=0.4, frame_token=950 + i,
                             frame_size=(1280, 720), now=100.60 + i * 0.10)
        if events:
            event = events[0]
            break
    if event is None:
        return None
    window.accept_combat_event(event)

    kf = window.kill_fx
    icons = getattr(getattr(kf, "scrolling", None), "icons", [])
    if icons:
        return float(icons[-1].started)
    lines = getattr(getattr(kf, "companion", None), "lines", [])
    if lines:
        return float(lines[-1][2])
    return None


def pin_killfx_age(window, anchor: float):
    """Instance-wrap kill_fx.draw so every element renders at anchor+KILL_AGE.
    Returns the unwrapper."""
    kf = window.kill_fx
    original = kf.draw

    def draw_at_frozen_age(*args, **kwargs):
        kwargs["now_override"] = anchor + KILL_AGE
        return original(*args, **kwargs)

    def unwrap():
        kf.draw = original  # type: ignore[method-assign]

    kf.draw = draw_at_frozen_age  # type: ignore[method-assign]
    return unwrap


# ------------------------------------------------------------ state drivers
# Each driver mutates the live window into one stable state, settles it on the
# real clock, then lets the caller do the frozen grab.  They reuse the verified
# recipes from tmp_corner_verify (jello/map/offer/match forensic scripts and
# tools/visual_audit.py).


def state_startup_scenario(app, window, meta):
    if not (window.home_visible and window.startup_step == "scenario"):
        raise RuntimeError(f"launcher not on scenario page (step={window.startup_step!r})")
    pump_real(app, window, 3.5)  # stagger needs 0.2 delay + 0.42s duration
    pump_real(app, window, 0.2)


def state_startup_match(app, window, meta):
    window.begin_startup_page_transition("match")
    if window.startup_step != "match":
        raise RuntimeError("begin_startup_page_transition('match') refused")
    pump_real(app, window, 1.8)  # page morph 0.42s + static glass rebuild


def state_startup_robot(app, window, meta):
    window.begin_startup_page_transition("robot")
    if window.startup_step != "robot":
        raise RuntimeError("begin_startup_page_transition('robot') refused")
    pump_real(app, window, 2.5)  # page morph 0.42s + static glass rebuild


def _leave_launcher_to_hud(app, window) -> None:
    window.finish_startup_page_transition()
    window.home_visible = False
    window.startup_step = "done"
    apply_static_backdrop(window)
    pump_real(app, window, 1.5)


def state_hud_idle(app, window, meta):
    _leave_launcher_to_hud(app, window)
    window.state.mock_simulation_enabled = False
    pump_real(app, window, 0.5)


def state_official_map(app, window, meta):
    config = window.match_mode_manager.current
    img = window.official_map_image(config)
    if img is None:
        raise RuntimeError("official map asset failed to load")
    module = window.registry.get("TacticalMap")
    if module is None or not module.enabled:
        raise RuntimeError("TacticalMap module unavailable/disabled")
    tms = window.tactical_map_state
    # Own the morph clock (verify_map_corners.py recipe): manual spring steps,
    # fixed iteration count -> geometry identical across runs.
    tms.container.velocity_width = 0.0
    tms.update = lambda dt: None  # type: ignore[method-assign]
    window.tactical_map_hold = True
    for _ in range(600):
        tms.container.update(1.0 / 120.0)
    meta["map_asset"] = str(config.field.asset_path)
    meta["container_width"] = round(float(tms.container.width), 4)
    pump_real(app, window, 1.0)
    state_official_map._tms = tms


def state_official_map_after(app, window, meta):
    """Collapse the map island again so later states show plain HUD."""
    tms = getattr(state_official_map, "_tms", None)
    if tms is None:
        return
    window.tactical_map_hold = False
    for _ in range(600):
        tms.container.update(1.0 / 120.0)
    del state_official_map._tms
    pump_real(app, window, 0.5)


def state_kill_fx(app, window, meta):
    effect = window.registry.get("EliminationFX")
    if effect is None:
        raise RuntimeError("EliminationFX module missing")
    effect.enabled = True
    if effect.get_setting("Sound Enabled"):
        effect.get_setting("Sound Enabled").value = False
    if effect.get_setting("Preset"):
        # factory default is "Card"; the scrolling preset renders the richest,
        # most regression-sensitive FX layer (icons + feed + rings)
        effect.get_setting("Preset").value = "Default Scrolling"
    if effect.get_setting("Element Visibility"):
        effect.get_setting("Element Visibility").value = "Preset"
    hud = window.registry.get("HUD")
    if hud and hud.get_setting("Dynamic Island"):
        hud.get_setting("Dynamic Island").value = False  # no banner springs
    anchor = trigger_vision_kill(window)
    if anchor is None:
        raise RuntimeError("no elimination event / scrolling icon produced")
    unwrap = pin_killfx_age(window, anchor)
    # Pre-expire the dynamic-island banner so its springs relax BEFORE freeze.
    window.dynamic_island_event_started = time.perf_counter() - 3600.0
    meta["kill_age_s"] = KILL_AGE
    pump_real(app, window, 2.0)
    # keep the pin active through the grab; the teardown unwraps it
    state_kill_fx._unwrap = unwrap


def state_kill_fx_after(app, window, meta):
    """Post-grab cleanup so later states have no stale overlay."""
    unwrap = getattr(state_kill_fx, "_unwrap", None)
    if unwrap:
        unwrap()
        del state_kill_fx._unwrap
    effect = window.registry.get("EliminationFX")
    if effect is not None:
        effect.enabled = False


def state_jello_gui_midscroll(app, window, meta):
    window.set_clickgui_visible(True, announce=False, play_sound=False)
    window.mode_manager.set_mode("JelloSigma")
    tl = window.gui_timeline
    tl.target = 1.0
    tl.progress = 1.0
    tl.velocity = 0.0
    window.gui_visible = True
    window.invalidate_transient_overlay_scene()

    # pick the category with the most modules -> guaranteed scrollable panel
    counts: dict[str, int] = {}
    for m in window.registry.modules:
        counts[m.category] = counts.get(m.category, 0) + 1
    target = max(counts, key=lambda c: counts[c])
    click_gui = window.registry.get("ClickGui")
    scale_req = float(click_gui.get_setting("Scale").value) if click_gui and click_gui.get_setting("Scale") else 1.0
    layout = window.jello_clickgui.layout(window.width(), window.height(), scale_req)
    scale = layout.scale
    header, row = 60.0, 30.0  # Sigma constants (verify_jello_corners.py)
    panel = layout.panels[target]
    viewport_h = panel.height() - header * scale
    maximum = max(0.0, counts[target] * row * scale - viewport_h)
    if maximum <= 0.0:
        raise RuntimeError(f"category '{target}' cannot scroll ({counts[target]} modules)")
    mid = maximum * 0.5
    window.jello_state.panel_scroll[target] = mid
    meta["category"] = target
    meta["modules"] = counts[target]
    meta["scroll"] = round(mid, 3)
    pump_real(app, window, 1.5)
    # remember how to close cleanly for the next state
    state_jello_gui_midscroll._cat = target


def state_jello_gui_after(app, window, meta):
    cat = getattr(state_jello_gui_midscroll, "_cat", None)
    if cat is not None:
        window.jello_state.panel_scroll[cat] = 0.0
    window.gui_visible = False
    tl = window.gui_timeline
    tl.target = 0.0
    tl.progress = 0.0
    tl.velocity = 0.0
    window.invalidate_transient_overlay_scene()
    pump_real(app, window, 0.8)


def state_economy_island_offer(app, window, meta):
    window.open_economy_workspace()
    # Let the Control-Center spring open the island on its own trajectory and
    # run until it SNAPS (progress==target exactly, velocity==0 -- the state
    # class snaps at |err|<5e-4, |vel|<8e-3).  Forcing the morph with a
    # clamped 50 ms step kicks the underdamped spring and leaves runs at
    # different sub-pixel phases.
    pump_real(app, window, 3.0)
    if not window.economy_visible:
        window.economy_visible = True
    categories = window.economy_categories()
    if not categories:
        raise RuntimeError("no economy categories available")
    window.economy_category = categories[0]
    offers = window.economy_offers(window.economy_category)
    if not offers:
        raise RuntimeError(f"category '{window.economy_category}' has no offers")
    window.economy_selected_key = offers[0].key
    window.economy_selected = 0
    sc = window.economy_offers_scroll
    sc.position = sc.target = sc.velocity = 0.0
    meta["category"] = str(window.economy_category)
    meta["selected_key"] = str(offers[0].key)
    meta["island_progress"] = round(float(window.economy_island.progress), 6)
    if abs(float(window.economy_island.progress) - 1.0) > 1e-4:
        raise RuntimeError("economy island did not settle to progress==1")
    pump_real(app, window, 0.5)


# Driver table: (frame name, setup fn, post-grab fn or None)
STATES = (
    (FRAME_NAMES[0], state_startup_scenario, None),
    (FRAME_NAMES[1], state_startup_match, None),
    (FRAME_NAMES[2], state_startup_robot, None),
    (FRAME_NAMES[3], state_hud_idle, None),
    (FRAME_NAMES[4], state_official_map, state_official_map_after),
    (FRAME_NAMES[5], state_kill_fx, state_kill_fx_after),
    (FRAME_NAMES[6], state_jello_gui_midscroll, state_jello_gui_after),
    (FRAME_NAMES[7], state_economy_island_offer, None),
)


def capture_all(out_dir: Path, only: str | None = None) -> dict:
    """Run every state on one live window; returns the capture manifest dict."""
    app, window = build_window()
    window.show()
    ctx = window.context()
    if ctx is None or not ctx.isValid():
        window.close()
        app.quit()
        raise RuntimeError(
            "No valid GL context on this desktop; "
            "re-run with QT_QPA_PLATFORM=offscreen for the CPU compat path "
            "(and regenerate the local baseline)."
        )
    pump_real(app, window, 0.8)

    manifest: dict = {
        "tool": "refactor_golden",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "env": {
            "python": sys.version.split()[0],
            "window": f"{window.width()}x{window.height()}",
            "dpr": round(window.devicePixelRatioF(), 4),
            "backend": str(
                window.registry.get("ClickGui").get_setting("Render Backend").value
                if window.registry.get("ClickGui") and window.registry.get("ClickGui").get_setting("Render Backend")
                else "?"
            ),
            "channel_tol": CHAN_TOL,
            "frozen_clock": FROZEN,
            "freeze_pumps": FREEZE_PUMPS,
        },
        "frames": [],
        "skipped": [],
    }
    for name, setup, teardown in STATES:
        matched = not only or only in name
        meta: dict = {}
        # States are sequential (each builds on the previous window state), so
        # ALWAYS drive the setup chain even when --only filters the grab;
        # otherwise a filtered recapture would land in a different state than
        # the baseline frame.
        try:
            setup(app, window, meta)
        except Exception as exc:  # noqa: BLE001  -- degrade honestly, never fake
            log(f"  SKIP {name}: {exc!r}")
            manifest["skipped"].append({"frame": name, "reason": repr(exc)})
            continue
        if not matched:
            if teardown:
                try:
                    teardown(app, window, meta)
                except Exception as exc:  # noqa: BLE001
                    log(f"  WARN teardown {name}: {exc!r}")
            continue
        try:
            freeze_grab(app, window, name, out_dir)
        except Exception as exc:  # noqa: BLE001
            log(f"  SKIP {name} (grab failed): {exc!r}")
            manifest["skipped"].append({"frame": name, "reason": repr(exc)})
        if teardown:
            try:
                teardown(app, window, meta)
            except Exception as exc:  # noqa: BLE001
                log(f"  WARN teardown {name}: {exc!r}")
        manifest["frames"].append({"frame": name, "file": f"{name}.png", "meta": meta})

    window.close()
    app.quit()
    return manifest


# ------------------------------------------------------------------ compare
def qimage_to_rgb_array(img) -> np.ndarray:
    """QImage -> HxWx3 uint8 (RGBA8888 normalized, stride-safe)."""
    from PySide6.QtGui import QImage

    rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
    h, w = rgba.height(), rgba.width()
    stride = rgba.bytesPerLine()
    buf = bytes(rgba.constBits())
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, stride)[:, : w * 4]
    return arr.reshape(h, w, 4)[:, :, :3].copy()


def diff_pair(base_img, fresh_img) -> dict:
    base = qimage_to_rgb_array(base_img).astype(np.int16)
    fresh = qimage_to_rgb_array(fresh_img).astype(np.int16)
    if base.shape != fresh.shape:
        return {
            "size_mismatch": True,
            "base_shape": list(base.shape),
            "fresh_shape": list(fresh.shape),
            "fail_pixels": 10**9,
            "max_delta": 255,
        }
    delta = np.abs(base - fresh)
    maxchan = delta.max(axis=2)
    changed = int(np.count_nonzero(maxchan))
    fail_mask = maxchan > CHAN_TOL
    fail = int(np.count_nonzero(fail_mask))
    mse = float((delta.astype(np.float64) ** 2).mean())
    psnr = float(10.0 * np.log10(255.0**2 / mse)) if mse > 0 else float("inf")
    return {
        "size_mismatch": False,
        "changed_pixels": changed,
        "fail_pixels": fail,
        "max_delta": int(maxchan.max()),
        "mean_delta": float(delta.mean()),
        "psnr_db": round(psnr, 2),
    }


def save_diff_visualization(base_img, fresh_img, path: Path) -> None:
    from PySide6.QtGui import QColor, QImage

    base = qimage_to_rgb_array(base_img)
    fresh = qimage_to_rgb_array(fresh_img)
    if base.shape != fresh.shape:
        return
    maxchan = np.abs(base.astype(np.int16) - fresh.astype(np.int16)).max(axis=2)
    vis = (base.astype(np.float32) * 0.35).astype(np.uint8)
    vis[maxchan > CHAN_TOL] = np.array([255, 32, 32], dtype=np.uint8)
    tol_mask = (maxchan > 0) & (maxchan <= CHAN_TOL)
    vis[tol_mask] = np.array([255, 220, 64], dtype=np.uint8)
    h, w = vis.shape[:2]
    out = QImage(vis.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
    out.save(str(path), "PNG")


def run_compare(baseline_dir: Path, out_dir: Path, only: str | None = None) -> bool:
    baseline_manifest_path = baseline_dir / "manifest.json"
    if not baseline_manifest_path.exists():
        log(f"ERROR: no baseline manifest at {baseline_manifest_path}")
        return False
    baseline_manifest = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))

    cap_dir = out_dir / "recapture"
    log(f"=== recapturing frames into {cap_dir} ===")
    fresh_manifest = capture_all(cap_dir, only=only)
    (out_dir / "recapture_manifest.json").write_text(
        json.dumps(fresh_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for skip in fresh_manifest["skipped"]:
        log(f"WARN: fresh run skipped {skip['frame']}: {skip['reason']}")

    from PySide6.QtGui import QImage

    base_env = baseline_manifest.get("env", {})
    fresh_env = fresh_manifest.get("env", {})
    if base_env.get("dpr") != fresh_env.get("dpr") or base_env.get("window") != fresh_env.get("window"):
        log(
            f"WARN: environment differs from baseline "
            f"(baseline {base_env.get('window')} dpr={base_env.get('dpr')} vs "
            f"fresh {fresh_env.get('window')} dpr={fresh_env.get('dpr')})"
        )

    base_frames = {f["frame"]: f for f in baseline_manifest.get("frames", [])}
    fresh_frames = {f["frame"]: f for f in fresh_manifest.get("frames", [])}

    all_ok = True
    rows: list[dict] = []
    log("")
    log(f"{'frame':26} {'changed_px':>10} {'fail_px':>9} {'max_d':>6} {'mean_d':>7} {'psnr':>9}  verdict")
    log("-" * 86)
    for name in FRAME_NAMES:
        if only and only not in name:
            continue
        if name not in base_frames and name not in fresh_frames:
            continue
        if name not in base_frames:
            log(f"{name:26} {'-':>10} {'-':>9} {'-':>6} {'-':>7} {'-':>9}  MISSING-IN-BASELINE -> FAIL")
            all_ok = False
            rows.append({"frame": name, "verdict": "FAIL", "reason": "missing in baseline"})
            continue
        if name not in fresh_frames:
            log(f"{name:26} {'-':>10} {'-':>9} {'-':>6} {'-':>7} {'-':>9}  CAPTURE-SKIPPED -> FAIL")
            all_ok = False
            rows.append({"frame": name, "verdict": "FAIL", "reason": "fresh capture skipped"})
            continue
        base_img = QImage(str(baseline_dir / base_frames[name]["file"]))
        fresh_img = QImage(str(cap_dir / fresh_frames[name]["file"]))
        if base_img.isNull() or fresh_img.isNull():
            log(f"{name:26}  unreadable image -> FAIL")
            all_ok = False
            rows.append({"frame": name, "verdict": "FAIL", "reason": "unreadable image"})
            continue
        rep = diff_pair(base_img, fresh_img)
        ok = rep.get("fail_pixels", 1) == 0 and not rep.get("size_mismatch")
        verdict = "PASS" if ok else "FAIL"
        all_ok &= ok
        log(
            f"{name:26} {rep.get('changed_pixels', '-'):>10} "
            f"{rep.get('fail_pixels', '-'):>9} {rep.get('max_delta', '-'):>6} "
            f"{rep.get('mean_delta', 0):>7.4f} {rep.get('psnr_db', 0):>9.2f}  {verdict}"
        )
        if not ok:
            save_diff_visualization(base_img, fresh_img, out_dir / f"diff_{name}.png")
            log(f"    -> diff visualization: {out_dir / f'diff_{name}.png'}")
        rows.append({"frame": name, **rep, "verdict": verdict})

    report = {
        "baseline": str(baseline_dir),
        "tolerance": {
            "rule": "FAIL iff changed_pixels > 0 AND max_channel_delta > CHAN_TOL",
            "channel_tol": CHAN_TOL,
        },
        "rows": rows,
        "all_pass": all_ok,
    }
    (out_dir / "compare_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log("-" * 86)
    log(f"report: {out_dir / 'compare_report.json'}")
    log("RESULT: ALL FRAMES PASS — display unchanged." if all_ok else "RESULT: DISPLAY REGRESSION DETECTED.")
    return all_ok


# ----------------------------------------------------------------- modes
def cmd_capture(args) -> int:
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"=== capturing golden frames into {out_dir} ===")
    manifest = capture_all(out_dir, only=args.only)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    n_ok = len(manifest["frames"])
    n_skip = len(manifest["skipped"])
    log(f"captured {n_ok}/{len(FRAME_NAMES)} states; skipped {n_skip}")
    log(f"manifest: {out_dir / 'manifest.json'}")
    if n_ok == 0:
        return 2
    return 0 if n_skip == 0 else 2  # a baseline must cover every state


def cmd_compare(args) -> int:
    baseline = Path(args.baseline).resolve() if args.baseline else DEFAULT_BASELINE
    out_dir = Path(args.out).resolve() if args.out else ROOT / "tmp_corner_verify" / "golden_compare_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    return 0 if run_compare(baseline, out_dir, only=args.only) else 1


def cmd_calibrate(args) -> int:
    """Capture twice (independent subprocesses, fresh process state each) and
    self-compare -> the machine's GPU noise floor."""
    import subprocess

    out_root = Path(args.out).resolve() if args.out else USER_DATA_PARENT / "golden_calibrate"
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    for tag in ("run_a", "run_b"):
        log(f"=== calibration capture {tag} ===")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "capture", "--out", str(out_root / tag)],
            cwd=str(ROOT),
        )
        if proc.returncode != 0:
            log(f"WARNING: {tag} capture exit code {proc.returncode} (incomplete)")

    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    log("")
    log(f"{'frame':26} {'changed_px':>10} {'fail_px':>9} {'max_d':>6} {'psnr':>9}")
    log("-" * 66)
    worst_fail = worst_max = 0
    for name in FRAME_NAMES:
        pa, pb = out_root / "run_a" / f"{name}.png", out_root / "run_b" / f"{name}.png"
        if not pa.exists() or not pb.exists():
            log(f"{name:26} {'SKIP':>34}")
            continue
        rep = diff_pair(QImage(str(pa)), QImage(str(pb)))
        worst_fail = max(worst_fail, rep.get("fail_pixels", 0))
        worst_max = max(worst_max, rep.get("max_delta", 0))
        log(
            f"{name:26} {rep.get('changed_pixels', 0):>10} "
            f"{rep.get('fail_pixels', 0):>9} {rep.get('max_delta', 0):>6} "
            f"{rep.get('psnr_db', 0):>9.2f}"
        )
    log("-" * 66)
    log(
        f"noise floor: worst fail-pixels(>CHAN_TOL={CHAN_TOL})={worst_fail}, "
        f"worst channel delta={worst_max}"
    )
    if worst_fail == 0 and worst_max <= CHAN_TOL:
        log("CALIBRATION OK: self-comparison within tolerance on this machine.")
        return 0
    log(
        "CALIBRATION OVER TOLERANCE: this machine's render path differs from the "
        "baseline environment. Regenerate a LOCAL baseline with `capture` before "
        "trusting compare results."
    )
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cap = sub.add_parser("capture", help="record golden frames into a baseline dir")
    p_cap.add_argument("--out", default=str(DEFAULT_BASELINE))
    p_cap.add_argument("--only", default=None, help="substring filter on frame names")
    p_cap.set_defaults(func=cmd_capture)

    p_cmp = sub.add_parser("compare", help="recapture + pixel-diff against baseline")
    p_cmp.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    p_cmp.add_argument("--out", default=None)
    p_cmp.add_argument("--only", default=None)
    p_cmp.set_defaults(func=cmd_compare)

    p_cal = sub.add_parser("calibrate", help="capture twice and self-compare (noise floor)")
    p_cal.add_argument("--out", default=None)
    p_cal.set_defaults(func=cmd_calibrate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
