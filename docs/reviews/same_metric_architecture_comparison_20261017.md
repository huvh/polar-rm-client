# Same-metric architecture comparison — 2026-10-17

## Finding

The quoted **33,597 → 37,377** executable-statement comparison is reproducible:
it compares the PR base `b26b7b7` with earlier PR19 snapshot `6b661c0` using the
same current measurement implementation. At the requested current snapshot
`a4d8774`, the count is **37,434**. These are static function-scoped AST counts,
not executed instructions, physical lines, performance measurements, or a quality score.

Import cycles were removed and selected functions became smaller. However,
local import edges and the central window/manager import fan-out increased.
The evidence therefore supports specific improvements, **not a blanket reduction
in coupling or whole-project size**. Counts alone do not justify a rewrite.

## Fixed inputs and method

| Snapshot | Exact commit |
|---|---|
| PR base | `b26b7b718e348fbda066412f6d86140727f32e73` |
| Earlier PR19 comparison endpoint | `6b661c056cf2cc3501386755a71b72bd6bc0f90f` |
| Current measured snapshot | `a4d8774334586572d17ae06370170606a390b8b3` |

Each snapshot's `rm_client` tree was exported with `git archive` into a temporary
directory, then parsed by the **same** checkout implementation of
[`tools.quality.metrics.measure_tree`](../../tools/quality/metrics.py).
No checkout, application import, hardware access, or repository mutation was
needed for measurement. This report is the only artifact added by this task.

Measurement implementation SHA-256:

- `tools/quality/metrics.py`: `548bcabd7b664a3468d566a0608e40b25ea32ec5bba955c3e22e511481841847`
- `tools/quality/runtime_sources.py`: `e0d560401d7e0eb2b05cdb30c2f4b89db3d58ee2625c7d8dd3da103377d855e7`

Scope is `rm_client/**/*.py`, excluding hidden/cache paths. All discovered files
parsed successfully. Function measurements exclude nested scope bodies from the
outer function and count nested functions separately; string-expression statements
are excluded. Tests, tools, documentation, and evidence logs are outside this scope.
Import edges and fan-out count unique local module targets, including deferred
imports and excluding `TYPE_CHECKING`-only edges. Cycle counts below are numbers
of strongly connected components reported by the existing tool.

## Comparable results

| Same metric | PR base | Earlier PR19 | Current |
|---|---:|---:|---:|
| Parsed Python files | 139 | 221 | 221 |
| Functions | 2,589 | 3,464 | 3,466 |
| Function-scoped executable AST statements | 33,597 | 37,377 | 37,434 |
| Decision count | 11,796 | 13,164 | 13,187 |
| Local import edges | 419 | 615 | 616 |
| Eager non-type-only import cycle components | 0 | 0 | 0 |
| Including deferred non-type-only import cycle components | 3 | 0 | 0 |
| `rm_client.ui.polar_app` import fan-out | 72 | 94 | 94 |
| `rm_client.backend.manager` import fan-out | 25 | 37 | 37 |
| Historical Tk implementation functions | 50 | 50 | 50 |

Current versus PR base: **+3,837 statements**, **+197 local import edges**,
window fan-out **+22**, manager fan-out **+12**. Current versus earlier PR19:
**+57 statements**, **+1 edge**, unchanged central-module fan-out.

Examples of localized improvement from PR base to current:

- `BackendManager._tick_polar_link_ready`: 191 → 27 statements; 134 → 10 decisions.
- Window `__init__`: 289 → 247 statements; 8 → 2 decisions.
- Entire window module: 2,194 → 2,002 statements, while fan-out rises 72 → 94.
- Entire manager module: 1,219 → 1,373 statements, while fan-out rises 25 → 37.

These function reductions do not establish that responsibility disappeared:
extraction can relocate work and add dependencies. The original three deferred
cycle components involved the model/economy/scenario/adapter group,
`ui.cs2_settings_center` with `ui.jello_keybinds`, and
`ui.polar.app_entry` with `ui.polar_app`.

## Source fingerprints and baseline distinction

The metric's `source_tree_sha256` values (normalized decoded Python source,
not Git tree IDs and not full-regression fingerprints) are:

- PR base: `5a04ad95267f31229029c8c6a0e00f446caff8640e6ee990bc568c2b3eced2aa`
- Earlier PR19: `83a5900d96c4f6f567f3c9254484520fd36732542ff976c0ea9aca3ee795a5df`
- Current: `fa4ef91a7abe37a1154ea6bb5e4cda8ad57e5a408a3e586fa59d68c3c1013c5d`

The separately documented quality-gate baseline in
[`docs/quality_gates.md`](../quality_gates.md#reproducing-the-initial-source-measurements-offline)
is `d64f1528e2e1864ef369537c026b6d3f7127f590`, not the PR base above.
The same tool measures that snapshot as 141 files, 2,619 functions,
34,124 statements, 11,995 decisions, 423 edges, window fan-out 73,
manager fan-out 25, and 0 eager / 3 including-deferred cycle components.
Its source digest is
`cd432aed2f9188765812905cab9e76a61aac6c36980d6f8bec3100d91138aca5`.
It must not be substituted for the 33,597-statement endpoint.

## Limits and acceptance meaning

Historical Tk remains included: its move from `rm_client.app` to
`rm_client.legacy_tk_app` is not credited as deleting its implementation.
The historical-function label excludes the old forwarding `main`; the total
function metric still measures all discovered functions. Current imports contain
six unique type-only module-target pairs, five exclusively type-only; the PR base
has none. These are not silently added to the non-type-only edge totals.

AST import graphs do not cover dynamic imports, reflection, runtime callback
routing, inherited mixin state access, or all ownership relationships. Acyclic
imports do not prove low coupling. These measurements do not validate runtime
behavior, latency, device safety, or physical operation, and they do not replace
the RobotState authority ledger or focused regression results. The defensible
acceptance statement is: **specific cycle/hotspot improvements are verified;
overall central dependency reduction remains unproven and these static fan-out
measures increased.** No raw measurement JSON or logs are published by this report.

## 2026-10-18 addendum: renewed repair-stage comparison

This is a separate comparison between exact commits
`a3c3103d831f5500c79b38685f4a05352d926bfc` and
`4c63180c9c92c68c5f9252e2dcd1a2b70dfba5dc`. Both `rm_client` trees were exported
from Git into temporary directories and parsed using the same current
`tools.quality.metrics.measure_tree` implementation. No application import,
regression suite or source modification was needed. Historical measurements
above retain their original endpoints.

The measurement implementation remains byte-identical to the version recorded
above:

- `tools/quality/metrics.py` SHA-256:
  `548bcabd7b664a3468d566a0608e40b25ea32ec5bba955c3e22e511481841847`
- `tools/quality/runtime_sources.py` SHA-256:
  `e0d560401d7e0eb2b05cdb30c2f4b89db3d58ee2625c7d8dd3da103377d855e7`

| Same metric | `a3c3103` | `4c63180` |
|---|---:|---:|
| Parsed Python files | 221 | 221 |
| Functions | 3,470 | 3,474 |
| Function-scoped executable AST statements | 37,495 | 37,556 |
| Decisions | 13,216 | 13,251 |
| Local import edges | 616 | 616 |
| Eager non-type-only cycle components | 0 | 0 |
| Including deferred non-type-only cycle components | 0 | 0 |
| Window module import fan-out | 94 | 94 |
| Backend manager import fan-out | 37 | 37 |

Normalized Python-source measurement digests, distinct from Git tree IDs and
aggregate-verification source fingerprints:

- `a3c3103`: `a21a14d7b30650bcd2bf5b0cc5d1f9f961bc6cafab14432c2162a86f881f527b`
- `4c63180`: `e76a6489ac0fb9b8b65bb6fe4ad70404ccbccc668f481abf3c6d8f7961900423`

The repair stage therefore leaves measured import coupling unchanged and adds
61 statements / 35 decisions. This establishes neither global simplification
nor a quality regression by itself. Correctness repairs require explicit
handling; these counts do not assess its necessity or clarity.

Three leading observed hotspots at `4c63180`:

1. `InputDispatchMixin.keyPressEvent`, `input_dispatch_mixin.py:1022`:
   100 decisions / 171 statements. Keyboard characterization and actual-window
   routing tests exist; ownership ordering makes mechanical rearrangement risky.
2. `Rm2026StateAdapter._apply_one`, `state_adapter.py:171`:
   73 decisions / 176 statements. Frozen referee characterization protects field
   presence, write ordering and error semantics.
3. `ModuleListMixin.draw_rm_indicators_hud`, `module_list.py:1251`:
   73 decisions / 89 statements. It combines geometry, diagnostic precedence,
   localization and tooltips. HUD locale/rendering tests exist, but should not
   be treated as an exhaustive diagnostic-precedence oracle.

A bounded next proposal, **not implemented by this addendum**, is to compute
ordered offers per category once inside `ui/cs2_buy_menu.py:build_grid`, reusing
those lists for both maximum-row/scroll calculation and column rendering.
Currently these two consumers independently classify the same offers. Before
changing it, characterize complete draw output, hotspot order/payloads and
scroll bounds for uneven, empty, unknown-category and supplier cases with the
existing buy-matrix host. Baseline and candidate should both pass; a changed
ordering/grouping mutation should fail. This would be a local consistency
improvement without a new helper/module, not reduced global coupling.

Raw temporary metric reports are not included or published. This addendum
changes documentation only and claims no new runtime qualification.

## 2026-10-18 addendum: finite tactical-map CPU-raster elapsed-time observation

At measured source `47a8be46cd88f0e351c0a8f926fca1af19b3e62e`, read-only inspection
found no recurring map-file decoding: `official_map_image` caches loaded images,
including failures. The resampling method `official_map_display_image` has no
production callers. Rounded-mask preprocessing is on a real presentation path:
`polar_app.py`'s GPU motion-layer painter calls `paint_hud_motion_overlay`, then
`draw_tactical_map_hud`, `draw_official_map` and conditionally `_rounded_map_layer`.
The diagnostic below executes that map painter on a raster device; it does not
exercise the native GPU device or measure frame presentation.

The original bounded observation used Linux, Qt offscreen, both checked-in map
PNGs, DPR 1, 1920×1080, fixed telemetry/time and a 24-frame collapsed→expanded→
collapsed geometry sequence repeated once without clearing image/mask caches.
The first cycle for later scenes still shares process-wide Qt/font state.

| Scene | First-cycle median elapsed ms | Warm-cycle median elapsed ms |
|---|---:|---:|
| RMUC standard | 3.08 | 2.85 |
| RMUC liquid | 2.77 | 2.35 |
| RMUL standard | 2.99 | 3.04 |
| RMUL liquid | 2.95 | 2.91 |

The first draw in the process took **20.94 ms**, versus **1.69 ms** for its warm
counterpart. This is a cold-draw observation, not an isolated diagnosis of font
initialization or the historical Tab stutter. Image decoding was timed separately
and excluded from these draw durations. Every corresponding frame in the two
cycles matched raster pixels and hotspot action/payload/geometry traces. RMUL
liquid retained some rounded-cache churn, but its warm total draw maximum was
3.65 ms in this sample. These observations do not justify a cache change.
No cache implementation was changed.

The reusable developer diagnostic is
[`tools/diagnostics/profile_tactical_map.py`](../../tools/diagnostics/profile_tactical_map.py):

```sh
# Linux example: an external process watchdog bounds hangs as well as work.
timeout 60s python tools/diagnostics/profile_tactical_map.py
```

Use the repository test dependencies and an external process watchdog appropriate
to your platform. The finite 192-frame workload has no internal timeout. The
diagnostic forces Qt offscreen before importing the host. It explicitly reuses the actual-window
`test_tactical_map_contract` host and fixture rather than adding a runtime API.
The script resolves repository paths relative to itself, prints JSON summaries
including source/renderer/asset identities, allocation totals and consistency
checks, and exits nonzero on pixel/hotspot inconsistency. It performs no full
suite, network exercise, capture, playback or native GL presentation; Qt
multimedia initialization is possible. Setup/cleanup, hashing and image decoding
are outside the measured draw interval, while instrumentation overhead remains
inside. Cold decoding may already benefit from the OS file cache. Timing values
are observations, not thresholds or guarantees, and may differ between runs.
The clock measures CPU-raster elapsed duration, not process CPU time. HEAD plus
renderer/asset hashes do not establish a full clean dependency snapshot. Normal
cleanup uses the existing test host; a failure during its initial setup inherits
that host's partial-construction cleanup limitations. No new partial-window
teardown is attempted. Raw profiling output is not included or published.
