# Windows UI integration — 2026-10-20

## Scope and changes

- Preserve fullscreen while a Jello settings/binding dialog is shown. A native
  normal-state notification can be repaired without replacing the saved normal
  geometry. Explicit F11/video-mode changes, minimization, dialog dismissal and
  parent shutdown are not reversed by this guard.
- Native settings/video/crosshair pages use a reversible analytical scroll
  spring (stiffness 300, critical damping). Wheel events accumulate continuously;
  trackpad pixel input remains direct. Dragging the scrollbar or hiding the page
  cancels old motion. Child widgets/fonts are not rebuilt for scrolling.
- Keep ClickGUI visuals unchanged, expanding only dropdown input tolerance.
  Existing clipping, popup precedence and modal input ownership remain intact.
- No liquid-glass shaders, material parameters, sounds or asset pixels changed.
- Windows regression fixes preserve byte-addressed fixtures, create Qt before
  inert GL-format tests, use native path separators, retain Windows descriptor
  failure chains, and distinguish queued Qt finalization from backend-idle.
  The shop oracle runs the SHA-verified original source on the same Qt runtime;
  all commands/hotspots are compared, not regenerated golden hashes.

## Executed evidence

Compact evidence: `docs/evidence/windows_20261020/summary.json`.
Full logs remain in the local ignored `tmp_windows_acceptance/` directory.

- `winfull6`: **426 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL**. Source fingerprints
  match at start/end. This is **NO-GO**, not a complete-suite PASS.
- `native_desktop_final`: **4 PASS**, native Windows OpenGL. Includes the renderer
  and startup smokes, 7 corner-pixel tests and 18 white-armor-overlay tests.
- Jello fullscreen/scroll tests: **14 tests each** at process DPR factors
  `1 / 1.25 / 1.5 / 2`. Arrow input geometry covers four viewport resolutions and
  four GUI scales. These are input/state checks, not a claim that every visual
  pixel at every monitor configuration has been inspected.
- A mock-only real OpenGL probe exercised five settings open/return sequences,
  a forced normal-state notification/repair, and an arrow-edge click in
  fullscreen. NVIDIA RTX 5070 Ti Laptop, NVIDIA OpenGL driver 596.21.
- `compileall` and `git diff --check`: passed.

## Deliberately not certified

The four incomplete suites concern unselected/prepared firmware and vendor
layout inputs, legacy firmware-patch installation, and native Windows sanitizer
execution. Zig 0.13 compiles/runs the other 12 portable-parser tests but has no
working Windows ASan/UBSan runtime here. The sanitizer test is explicitly
incomplete, not passed. Set `POLAR_SANITIZER_CC` to a sanitizer-capable native
compiler to run it; do not remove this gate to build a release.

One earlier run, concurrent with a native UI probe, observed an audit-log
shutdown timeout. Its failed evidence is retained. Later serial passes do not
constitute a root-cause closure for field soak or stressed filesystem behavior;
production shutdown timeouts were not relaxed.

No real vehicle/referee/VTx/control qualification, physical audio certification,
second clean Windows installation, new portable-package certification or
sustained whole-client frame-rate guarantee is provided by this UI integration.
Control authorization and release/readiness gates remain fail-closed:
**NOT READY FOR REAL MATCH**. No new release is published by this change.

The original workspace's private configuration and PDF extraction are excluded
from changes, staging and public evidence.
