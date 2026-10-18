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

## 2026-10-18 addendum: full10 to full12 source comparison

This separate comparison uses the exact source checkpoints recorded in the
[renewed repair report](renewed_clean_code_repairs_20261018.md), preserving all
historical endpoints above:

- Full10: public `c9180595ddbdd6ec8a17012b35a62328ae1d762d`, local
  `d23443a224672e3ac05b34d15394d14525c33eea`, tree
  `695e8b9e2d1d2b1bccb8805439b134350b71b26d`.
- Full12: public `863954d30aa841058a073d2c0020d1468e20ebaf`, local
  `6a802d5c73be8585a0f814997edd38cc8d81243a`, tree
  `5c24ec773655f730f63892ee48477640bfc8771f`.

Both committed `rm_client` trees were exported with `git archive` into temporary
directories and measured by the same existing `measure_tree` implementation;
all 221 Python files parsed at each endpoint. Tool hashes still match the
original method: `metrics.py` SHA-256
`548bcabd7b664a3468d566a0608e40b25ea32ec5bba955c3e22e511481841847`,
`runtime_sources.py` SHA-256
`e0d560401d7e0eb2b05cdb30c2f4b89db3d58ee2625c7d8dd3da103377d855e7`.
No application imports, regression tests or source edits were required.

| Same metric | Full10 source | Full12 source |
|---|---:|---:|
| Functions | 3,479 | 3,481 |
| Function-scoped executable AST statements | 37,579 | 37,637 |
| Decisions | 13,246 | 13,273 |
| Local import edges | 616 | 616 |
| Eager / including-deferred cycle components | 0 / 0 | 0 / 0 |
| Window / manager import fan-out | 94 / 37 | 94 / 37 |

Normalized Python-source digests, distinct from Git trees and aggregate-run
fingerprints, are respectively
`2871233fffd8f8c1ba1847ae15cb9373c034e34cf0f9e43402a8dd192849518a`
and `0bd2c9f52b151c0a5cdfb7cb4407409bfa1c7b3caa4cda132c172424e0f795d7`.

The repair stage adds 58 statements, 27 decisions and two functions while these
static import-coupling measures remain unchanged. This neither proves global
decoupling nor makes the added handling a quality regression. Runtime callback,
state and ownership coupling remain outside this graph, and zero cycles are not
whole-project Clean Code acceptance. No raw metric output is published here.

## 2026-10-18 addendum: full12 to full23 ownership-stage comparison

The original completed aggregate reports identify these exact source endpoints;
their clean-start commits and trees were checked against local Git objects:

- Full12: local `6a802d5c73be8585a0f814997edd38cc8d81243a`, tree
  `5c24ec773655f730f63892ee48477640bfc8771f` (public `863954d30aa841058a073d2c0020d1468e20ebaf`).
- Full23: local `1fc3e36fd92c8d38ef7da0c69e268ac9aa4938a2`, tree
  `03ed0ebd80452670f7c044d3d83e472291beba84` (public `8a7b6abcc3eb5274bfeeef63df508b56e231f226`).

Both were measured with the same CPython 3.12.14 interpreter and identical
existing metric/gate inputs. These SHA-256 values match at **both** commits:

| Tool/input | SHA-256 |
|---|---|
| `tools/quality/metrics.py` | `548bcabd7b664a3468d566a0608e40b25ea32ec5bba955c3e22e511481841847` |
| `tools/quality/runtime_sources.py` | `e0d560401d7e0eb2b05cdb30c2f4b89db3d58ee2625c7d8dd3da103377d855e7` |
| `tools/quality/__init__.py` | `8457d57b46817f3bf5fb7a05e89d6a20af64acfdcebae59cad1d4dfee3836f6f` |
| `tools/quality_gate.py` | `c57181a460b33f071b3a96178b3ac630ab7a51e883e7073cea06082a9b3f71d3` |
| `tools/quality/gates.py` | `ad5b6ef9c093960b0a89b158bc4a2dc22c4910043f20d13e500ab26f46a6f9bf` |
| `tools/quality/baseline.json` | `7c468aef442546824fc0c18dc72faa836299a9d17e23e2ab3315401483a1b9f4` |

Scope remains **`rm_client/**/*.py` only**: tests, tools, root `main.py`, assets
and dependency packages are not counted. All 221 files parse at each endpoint;
the retained historical UI module and its 50 functions remain included. Metric
definitions and graph limitations are unchanged from the earlier sections.

| Same metric | Full12 source | Full23 source | Change |
|---|---:|---:|---:|
| Parsed Python modules | 221 | 221 | 0 |
| Functions | 3,481 | 3,487 | +6 |
| Function-scoped executable AST statements | 37,637 | 37,666 | +29 |
| Decisions | 13,273 | 13,286 | +13 |
| Local import edges | 616 | 616 | 0 |
| Eager / including-deferred cyclic SCCs | 0 / 0 | 0 / 0 | 0 / 0 |
| Window / manager import fan-out | 94 / 37 | 94 / 37 | 0 / 0 |

Both complete directed import-edge sets, eager and deferred-inclusive, are
identical; equal totals do not conceal replaced edges. The window source is
unchanged. Manager counts are 116 → 116 functions, 1,374 → 1,377 statements and
552 → 554 decisions. Both versions pass the same unchanged static gates.
Normalized Python-source digests, distinct from Git trees and aggregate-run
fingerprints, are:

- Full12: `0bd2c9f52b151c0a5cdfb7cb4407409bfa1c7b3caa4cda132c172424e0f795d7`
- Full23: `305bf5c4ab212259cb51369b90e3c600e344b745f1da156244ca2cc064f19668`

The following commands were replayed from the repository root using local Git
objects and temporary exports, without checking out either source tree. `PY`
names the actual verification interpreter; adjust its path for another machine.

```sh
set -eu
BEFORE=6a802d5c73be8585a0f814997edd38cc8d81243a
AFTER=1fc3e36fd92c8d38ef7da0c69e268ac9aa4938a2
PY=../client-verification-venv/bin/python
WORK=$(mktemp -d)
TOOLS='tools/quality_gate.py tools/quality/metrics.py tools/quality/runtime_sources.py tools/quality/gates.py tools/quality/__init__.py tools/quality/baseline.json'
git diff --exit-code "$BEFORE" "$AFTER" -- $TOOLS
mkdir -p "$WORK/before" "$WORK/after" "$WORK/tool"
git archive "$BEFORE" rm_client | tar -x -C "$WORK/before"
git archive "$AFTER" rm_client | tar -x -C "$WORK/after"
git archive "$AFTER" $TOOLS | tar -x -C "$WORK/tool"
(cd "$WORK/tool" && sha256sum $TOOLS)
PYTHONDONTWRITEBYTECODE=1 "$PY" "$WORK/tool/tools/quality_gate.py" \
  --root "$WORK/before" --json "$WORK/before.json"
PYTHONDONTWRITEBYTECODE=1 "$PY" "$WORK/tool/tools/quality_gate.py" \
  --root "$WORK/after" --json "$WORK/after.json"
```

The ownership gains are bounded: motion/arbitration/identity evidence uses its
existing owners at epoch boundaries; safety owns ordered stage invalidation;
the effect renderer owns hit-revision consumption. The latter two are
characterized behavior-preserving cleanups, not additional bug-fix counts.
Angle-reception and process-acquisition repairs add explicit boundary handling.
No production module was added. These changes support local ownership claims,
**not global decoupling or size reduction**: graph/fan-out measures are unchanged
and statements/decisions increase. Static counts cannot establish necessity,
clarity or runtime correctness of that handling.

No application modules or regression suites were run for this comparison.
Original full12/full23 NO-GO results and native/external acceptance gaps retain
their separate meaning; no aggregate counts are added together or upgraded.
Only this existing report is amended. Raw metric output and logs are not
published, and all historical comparisons above retain their original scope.
