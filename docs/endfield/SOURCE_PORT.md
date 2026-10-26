# Endfield source UI port

## Implemented / locally verified (2026-10-21)

The Windows Esc menu now uses the original EndfieldHUD renderer and scene,
not the rejected hand-drawn circular-menu prototype. Existing Jello settings,
liquid-glass HUD shaders, robot protocols and authorization remain unchanged.
Non-Windows/inert CI hosts retain the previous painter menu.

Visual authority:
- EndfieldHUD: https://github.com/DDDuoDuo/EndfieldHUD
- Pinned source: `cdbd4f573c8fa3b9c2048fa3d1b089e69196537b`.
- v1.2.0 Windows resource archive SHA-256:
  `b16f77c5dfa1c7e7cfe2ed96697347b880932a25507f6c8cb823ffec2a9a9341`.
- Original geometry, 15.3818-degree camera, glyph projection, masks, shaders,
  750ms entrance / 333ms exit, ambient loop and button curves are retained.
  RM captions/actions and the central field are adaptation points.

## Runtime ownership

2026-10-25: Esc右侧功能栏已按本体ScrollRect参数补上拖动松手惯性，并更新内置原生DLL。源码依据、重启生效方式和实际D3D/Qt验收见 [Esc惯性说明](menu/README.md)。

`native/endfield/bridge.cpp` owns a retained D3D11/DirectComposition visual on
one worker. Ordinary frames do not read back/copy pixels through Python/Qt.
Qt retains keyboard focus, emergency handling and all semantic client actions.
Qt forwards pointer, leave, key and wheel events using the same physical DPI
transform. The original render carrier stays hidden; the retained swap chain
is composed directly over Qt's presentation HWND. No other process/window is
inspected.

Closing holds modal input until actual source conceal is acknowledged. Only
then can a queued route open settings, inventory, economy or other client pages.
Hero opens its UI only; it never sends deployment. Exit requires confirmation.
Shutdown retires the worker before destroying its parent HWND. F12 remains the
existing guarded emergency route. Reversals finish the current authored finite
clip before switching, rather than jumping between intermediate poses.

The existing GPU compositor owns the blurred backdrop. No alternate glass
shader, CPU desktop capture or reconstructed liquid-glass material is added.

## Central RM field

The supplied official 2027 RMUC 7v7 / RMUL 3v3 / RMUL 1v1 STEP files are
tessellated offline, preserving assembly coordinates. Runtime loads bounded GPU
triangle meshes, not CAD. They sit inside the original circular projection as
inclined floating survey tables: translucent ochre faces, actual CAD crease
outlines, and clear ring margins. Client match mode selects the model.

The 2.88M-triangle RMUC model uses an offline LOD: currently 78,677 surface
triangles plus crease-line quads. This is not full-resolution CAD editing.
Original source hashes and LOD counts are recorded in private map metadata.

## Original loading presentation and voices

Read-only local extraction recovered the original LoginRootPanel/ResourcePanel/
Loading hierarchy, sprites, HarmonyOS Sans SC font and loadingicon_loop.anim
quaternion keys (60Hz, one second). The bottom strip uses authored anchors,
sizes/colors and original sprites; the spinner evaluates the original Hermite
curves. Text/percent represent actual configuration, graphics and atlas work,
not elapsed-time guesses. Covered footer hotspots are excluded from input.

Actual original EFOS audio, not TTS:
- Entering Core AIC area: once after completed initialization.
- Alert! Insufficient power output: fresh official buffer-energy observations,
  module/audio preferences, debounce, hysteresis, identity reset and cooldown.
  Mock/default state is not a warning measurement.

The original game installation is untouched. Required menu resources and the
verified native renderer/three field previews are now versioned under
rm_client/ui/endfield/menu/assets at the maintainer's explicit request. Optional boot/audio
and personal overrides remain under ignored user_data/endfield_pack. Upstream
MIT does NOT grant game asset redistribution rights; see THIRD_PARTY_NOTICES.md.
This source asset update is not a new portable executable release.

## Rebuild / prepare

**A fresh complete main checkout already includes the menu pack. For rebuilding,
use the complete, pinned Windows procedure in
[ENDFIELD_PACK_SETUP.md](PACK_SETUP.md).** It provides real download
URLs, exact tool versions, all three official model hashes, one transactional
prepare command, integrity checks and actual D3D verification. The following
commands are individual development primitives, not a complete installation.

Explicit offline preparation; none of these tools is a runtime installer:

```powershell
python tools/endfield/import_runtime.py --package PINNED_ARCHIVE --out user_data/endfield_pack/native_source_runtime
python tools/endfield/build_source_probe.py --reference PINNED_CHECKOUT --native-library --out NEW_BUILD --install-root user_data/endfield_pack/native_renderer
python tools/endfield/prepare_field_preview.py --source OFFICIAL_STEP --out user_data/endfield_pack/maps --mode RMUL3v3 --up=-y
python tools/endfield/prepare_boot.py --export-root LOCAL_ORIGINAL_EXPORT --out NEW_BOOT_PACK
```

Use isolated C++20 Clang/Zig 0.14.1, CAD/VTK and UnityPy tooling environments
as appropriate. None are client runtime dependencies. Builds verify the source
pin, record source/compiler/binary hashes and install immutable versioned DLLs
via atomic CURRENT.json. Python verifies the binary hash before loading.

One documented derivation widens only the scene-submission physical viewport
guard from 4096 to 8192 pixels, retaining the renderer's 16M-pixel bound. This
prevents 2560 logical pixels at 200% DPI (5120 physical) from faulting. No shader,
material, geometry or curve is changed. The derived translation-unit hash is
recorded, and the reference checkout remains clean.

## Verification and limits

Local evidence in tmp_endfield_work; NOT field qualification:

| Check | Result |
|---|---|
| verified_tests.json: 18 selected suites | 18 PASS, 0 SKIP, 0 INCOMPLETE, 0 FAIL |
| Static quality | PASS: 234 modules, 3596 functions, zero initialization cycles |
| Python compile checks | PASS |
| desktop_verified_100/report.json | Real Windows GL/D3D, 100 close/open cycles plus reversals: PASS |
| Visible fullscreen source hit -> settings | PASS; fullscreen and F12 retained; exit Cancel retained fullscreen |
| Resource lifetime | 56 textures / 57 meshes stable; one owner; retired on shutdown |
| Additional visible 150% DPI / 10 cycles | PASS |
| native_dpi_final/report.json | 16 resolution/DPI combinations, all three fields, up to 5120x2880: PASS |
| Original wheel spring -> bottom action | PASS; actual projected hit dispatched the RM startup route |

The first extended DPI run exposed the 4096 guard, which was fixed before the
complete 16-case run was repeated successfully. Earlier exploratory failures
are not passes. Tests used temporary profiles and inert transport starts;
both protected default config hashes stayed unchanged.

On the local 75Hz display the final synthetic HUD sample averaged 70.98 FPS;
swap-interval P95 was 20.34ms, NOT a passing <14.3ms render-time claim. This is
not a camera/field throughput measurement or a stable 90FPS promise. Full-repo
regression and actual match qualification remain separate work.

Direct original-source rendering is not a hand-drawn approximation, but
bit-identical Windows/macOS/TMP typography and every game-build pixel/timing
have NOT been certified. Do not advertise literal pixel parity, match readiness
or a new portable release from these scoped tests.

## Esc hover regression (2026-10-21)

The host used to send an empty pointer in every frame's environment. The
original session correctly dropped hover on the following sample, while the
next mouse-move event restored it and restarted its authored transition. The
adapter now retains pointer input between frames, including keyboard selection,
and tracks native WM_MOUSELEAVE explicitly. Modal blocking disables interaction
without discarding real leave events; concealment clears the retained point.
Original hit geometry, colors, motion curves and glass materials are unchanged.

`tools/endfield/verify_hover.py` checks the actual D3D owner's source hover
identity/change counter, with one stationary pointer and duplicate move events,
not screenshot guesses or fake session state. The pre-fix diagnostic build
failed; the installed fix passed 21 dwell/re-entry cases across 1280x720,
1920x1080 and 3840x2160 physical pixels, English/Chinese, normal leave and modal
leave/resume (`tmp_endfield_work/hover_final/report.json`). The camera is allowed
to finish its original parallax before positioning over a small projected card.

The visible fullscreen check positions the actual cursor over this client's
own HWND; genuine OS leave events must not compete with an unrelated injected
point. It restores the previous cursor position on teardown. The latest scoped
offline regression is `hover_final_unit_tests.json`: 14 PASS, no skipped,
incomplete or failed suites. These checks do not certify real-match operation.

`desktop_hover_verified_100/report.json` also passed visible fullscreen dwell
and duplicate-input checks, source hit -> settings, F12 routing, and 100 menu
close/open cycles with reversals. Resources stayed at 56 textures / 57 meshes,
and the single native owner retired successfully. No game installation or
protected default configuration was changed by this fix.

## Esc world backdrop (2026-10-21)

Esc now retires combat chrome visually (ModuleList, MC HUD, maps, targets,
chat/student panels, Hero/radial lenses), without toggling any modules or
stopping referee/safety work. The world alone gets a dedicated normalized,
separable Gaussian and 42% dim. Adjacent Gaussian taps use linear filtering;
the radius is DPR-aware and bounded to 32 physical pixels. This does not
stretch the glass's sparse kernel into repeated scene/text edges. Ordinary
glass and Jello kernels, weights, refraction and materials remain unchanged.

The native child waits for a successful backdrop frame AND Qt frameSwapped
before revealing. Close/reopen invalidates pending readiness; this prevents a
covering HWND from preserving an old sharp HUD before the first treated frame.
Input remains modal while waiting. Emergency painter fallback hides/dims chrome
but does not pretend to implement a CPU blur.

The real GPU check also exposed a pre-existing cleanup assumption:
[Qt 6.11's OpenGL engine end implementation](https://github.com/qt/qtbase/blob/6.11/src/opengl/qopenglpaintengine.cpp#L2102-L2131)
returns false even after normal retirement. Previously that rejected the
compositor frame and selected compatibility rendering. Painter completion now
recognizes this only for an active OpenGL2 engine that fully releases its
device; raster false, inactive painters, retained ownership and exceptions
still reject. Earlier native-hover tests did not assert the parent's unified
GPU path, so their FPS must not be read as unified-compositor performance.

`test_endfield_backdrop` verifies empty actual combat FBOs, no duplicate sharp
draw, modal priority, and unchanged settings/full restoration on exit. Frozen
frame parity remains enforced for every other scene; Esc's intentional removal
of the two crisp foreground calls has its own explicit delta contract. The
Windows tool reads owned GL targets to verify that all six chrome layers have
zero alpha and that edge energy decreases even after mathematically undoing
the dim pass, rather than accepting a dark screenshot as blur evidence.

Final local evidence: `backdrop_regression.json` is 27 PASS / 0 SKIP /
0 INCOMPLETE / 0 FAIL; `desktop_backdrop_final_100/report.json` passed actual
Windows GL/D3D blur, empty chrome layers, fullscreen stationary hover and 100
open/close cycles with reversals. Native textures/meshes stayed 56/57 and the
test owner retired. This is scoped UI evidence, not field qualification or a
performance target certification. The user's separately running main.py and
its runtime profile were not stopped, overwritten or restored by these tests.

## Update-log menu

The former About / Help entries now say Changelog / 更新日志 and retain source
action 7. The dialog lists dated, implemented local changes in the selected
ClickGUI language; it does not claim a new release or match qualification.
It reuses Jello's fullscreen guard, emergency shortcut and smooth scroll area,
with a viewport-sized scrollable body instead of clipping long notes. Native
labels were rebuilt and installed into a fresh immutable renderer version.
`changelog_tests.json` passed 8 selected suites; `changelog_native_hover` passed
the real D3D source-hover regression with the rebuilt labels.

## Esc white-window composition fix (2026-10-22)

The visible native child HWND occluded Qt's OpenGL presentation surface. Its
transparent menu pixels exposed the white window backing store even though
the owned GL backdrop and D3D menu targets both contained correct pixels.
Consequently, the former framebuffer-only desktop check could pass while the
actual window was white.

The adapter now borrows the original renderer's retained composition swap
chain and binds it to an upper DirectComposition visual on the Qt presentation
HWND. The renderer's carrier HWND stays hidden. Entrance is exposed only after
the first native draw and Qt backdrop swap; the visual is detached at the end
of the authored exit and before renderer teardown. No background color,
material, blur, per-frame CPU copy or framebuffer readback was added. Qt now
forwards window-leave events to retire native hover tracking.

`verify_endfield_desktop.py` additionally inspects the actual native child
visibility, so the former white-window implementation fails even when its GL
and D3D target checks pass. Final Windows display inspection confirmed the
existing blurred world showing through the menu. The desktop regression also
checks resize, fullscreen, hover, source hits, F12, animation reversals and
resource retirement; these are UI checks with inert transports.

Final evidence: [default shipped-pack desktop check](../evidence/esc-window-composition-20261022/desktop.json)
passed 10 close/open cycles, fullscreen hover and source actions. Native
textures/meshes stayed at 56/57 and the owner retired. Pack integrity, modal
input, Qt leave routing and real hidden-OpenGL pixel regressions also passed.
