# UI-thread performance hardening

This patch addresses startup warmup and exposes work outside `paintGL`. It does
not change glass, shaders, render composition, video scaling, frame-rate settings,
HUD geometry, user transport settings, or control authorization.

## Warmup

Previously the first `paintGL` synchronously prepared font atlases for seven
ClickGUI density levels plus HUD/economy pages. Preparation now starts after the
first successful GPU frame and yields to the Qt event loop between individual
font pages or image uploads. Preparation of the module/label list yields every
eight modules. Only the current ClickGUI density is warmed; other densities use
the existing on-demand atlas cache.

The timer waits 16 ms between jobs. Each job executes with the existing context
current on the GUI thread, outside `paintGL`. No GL work runs in a worker thread.
A hidden or invalid-context surface pauses; the next successful GPU frame resumes
it. Close stops the timer. Upload/preparation failures cancel the pending queue
and emit diagnostics; they do not silently change any renderer preference.

The 3 ms check is a **soft scheduling target**, not a hard maximum. A single Qt
font-page rebuild or driver texture upload cannot be interrupted. Cache growth
currently rebuilds an atlas page; splitting strings into tiny batches would
repeatedly rebuild the accumulated page, so this patch does not add that
quadratic workaround. First-use on-demand glyph/image work can still occur.

## Runtime evidence

`ui_tick_timing` is emitted every five seconds and includes:

- Total UI tick duration and maximum
- Timer wakeup gap and maximum (distinct from draw duration)
- Count, total milliseconds and maximum per guarded tick stage, including
  `control.75hz`, backend processing/readiness, vision and team-link work
- Actual last/maximum warmup-slice duration

`frame_timing` also includes the latest UI tick, wakeup gap and warmup values.
Timing-log failure does not terminate the tick callback. The existing target FPS
setting remains unchanged. These metrics can reveal a 4–6 FPS event loop even
when the actual draw call takes under 3 ms.

## Verification

The queue tests cover first-frame deferral, no warmup after CPU fallback, one
page per turn, hidden/invalid-context pause, successful-frame resume, exception
cleanup and per-stage timing. Existing UI-state, renderer-cache, black-hole and
startup suites were rerun. API-freeze changes add only the twelve new
application-owned fields/methods; all old entries remain byte-for-byte equivalent.
The mutation self-test still detects removal of `draw_watermark`.

Local Qt 6.8.3 CPU-only font preparation used the exact repository's Jello light,
Jello medium, Poppins regular/medium/bold and Material Icons fonts from commit
`bd2e590b43b9cfecef61b09f0577a2ba0181578e`; downloaded bytes matched the Git blob
SHAs. GL texture upload was deliberately stubbed because this environment cannot
create an OpenGL context. Across two real-font runs, 36 current-density text jobs
needed about 269–311 ms total CPU preparation, with the largest individual job
about 19–22 ms. Text-job generator preparation peaked around 4 ms after chunking.
These are not target-PC measurements, GPU benchmarks or a claimed 144 FPS pass.
Museo is absent at the expected repository path and retained the existing font
fallback. The user's real GPU, driver and startup config require runtime testing.

## Separate GPU-priority work

This narrow patch does not claim every rendering operation is on the GPU. The
existing application already composes its private FBOs and most HUD/video passes
with OpenGL. Gimbal driver-workaround images, some HUD/map caches and wallpaper
CPU preparation remain. A separate GPU-backend/fallback migration requires
hardware visual, input, context-loss and emergency-surface validation before
publication; it is intentionally excluded from this glass-preserving repair.
