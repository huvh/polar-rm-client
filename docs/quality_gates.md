# Reviewable quality gates

These checks support the Clean Code refactor. They do not define “clean” by a
20-line function limit, a giant formatting diff, or a new passing snapshot.

## Commands

Use the same Python environment as the client. The static gate and its focused
self-tests require only the standard library; they do not import the client.

```sh
python tools/quality_gate.py
python tools/quality_gate.py --json tmp_quality/architecture.json --markdown tmp_quality/architecture.md
python tests/test_quality_gates.py
python tools/verify_all.py --test test_quality_gates --test test_test_registry --json tmp_quality/quality-tests.json
```

`verify_all.py` discovers the new suite automatically. It must record a nonzero
unittest count, and dependency skips remain SKIP/INCOMPLETE. A successful static
check is not an application, GPU, firmware, robot, or visual qualification.
The new suite also runs the real repository gate, so the existing aggregate
verification command cannot silently omit architecture checks.

## Verification report provenance

Execution reports from `tools/verify_all.py --json <path>` now include an
additive `provenance` object with its own `schema_version: 1`. Existing top-level
schema, results, counts, selection and PASS/SKIP/INCOMPLETE/FAIL meanings are
unchanged. Inventory-only `--list` does not run Git or collect this metadata.

The report records the UTC capture time, Python implementation/version, OS
system/release/machine, and the installed distribution versions of the declared
runtime/build dependencies plus PySide6's key companion packages. Versions come
from `importlib.metadata`, without importing Qt, OpenCV, OpenVINO or other
optional runtime packages. Missing packages and unreadable metadata have
separate explicit statuses; collecting a version does not verify native imports,
GPU support, hardware access, or a reproducible dependency lock.

`source_at_start` records Git HEAD, the HEAD tree ID, and a dirty flag covering
tracked changes and nonignored untracked files. The tree ID describes the
committed tree, not a dirty working copy; ignored resources are outside the
status check. Preserve the actual patch/resource manifest when that distinction
matters. Git is queried read-only with optional index locking disabled; a
missing executable, source snapshot without Git, invalid object ID or failed
query is `unavailable`, never silently reported as clean. No checkout, fetch,
download, baseline rewrite, dependency installation or environment-variable
dump is performed. Executable paths, remote URLs, filenames from dirty status,
and Git error text are not included in this metadata.

## What is enforced

- Every discovered production Python file must parse. An empty source tree,
  unreadable/malformed baseline, or invalid syntax cannot yield PASS.
- The backend, model, configuration, lifecycle, runtime-path, and state-overlay
  layers cannot import `rm_client.ui`, even via a function-local or type-only
  import. The model boundary includes its extracted `module_catalog` and
  `module_settings` domains; emergency-action coordination and qualification
  observation predicates are also protected. UI depends on those layers, not
  the reverse.
- No new module-initialization import cycles. Deferred imports are reported
  separately; they are not falsely called an initialization cycle.
- No increase in scoped existing debt for bare `except`, wildcard imports,
  shadowed definitions, inline compound suites, or semicolon-separated code.
  Strings and comments containing semicolons are not violations. Property
  setters/deleters and typing overloads are recognized.
- Nine existing orchestration hotspots have explicit no-growth budgets for
  executable statements, decisions, and control nesting. Reducing a hotspot
  through a tested responsibility boundary is allowed. Physical line count is
  never a failure condition.

The initial baseline is tied to the published commit
`d64f1528e2e1864ef369537c026b6d3f7127f590`, Git tree
`46333e99db86988f503b4ff31cd651d0e07eed86`. Its source-equivalent local staging
commit was `da91fc54b97caffd8f76b1aba86f88105d3c0379`; that local object is not
required to run the checks or expected to exist in a fresh clone. Connector
publication can change commit identity while preserving the complete Git tree.
It records existing debt, not permission to add more. Its two wildcard-import
locations are historical compatibility facades; rewriting their export behavior
is a separate compatibility task. Other recorded debt is intentionally left in
place to avoid whole-project beautification.

A check never rewrites `tools/quality/baseline.json`. Do not increase budgets or
regenerate it just to turn a failure green. First inspect the failing change. If
an exception is justified, review the exact symbol/rule, the behavior change,
the focused negative test, and the reason alongside that small baseline diff.
When cleanup reduces debt, lower the relevant budget after tests; do not replace
unrelated entries. Removing a function retires that function's budget, so review
its replacements and the full report rather than claiming a deleted metric
proves the design improved.

## Reproducing the initial source measurements offline

Ordinary quality/API checks use committed evidence files and the checked-out
source. They do not run Git, require old history, download a baseline, or rewrite
one. Reconstructing the initial architecture report additionally needs either
the published commit already present locally or a separately supplied snapshot
whose measured source digest matches. A shallow clone may lack the old commit;
stop with that explicit missing-history result rather than substituting `HEAD`.

From the refactored checkout, this POSIX command verifies the complete original
Git tree before exporting only the measured `rm_client` source into a new
temporary directory. It does not check out or mutate the current branch:

```sh
(
  set -eu
  revision=d64f1528e2e1864ef369537c026b6d3f7127f590
  git cat-file -e "$revision^{commit}" || {
    echo "Baseline commit is absent locally; obtain the published history or a verified source snapshot separately. No automatic fetch." >&2
    exit 2
  }
  test "$(git rev-parse "$revision^{tree}")" = 46333e99db86988f503b4ff31cd651d0e07eed86
  baseline=$(mktemp -d)
  git archive --format=tar --output="$baseline/source.tar" "$revision" rm_client
  tar -xf "$baseline/source.tar" -C "$baseline"
  python tools/quality_gate.py --root "$baseline" \
    --expect-source-sha256 cd432aed2f9188765812905cab9e76a61aac6c36980d6f8bec3100d91138aca5 \
    --json tmp_quality/architecture-before-reproduced.json \
    --markdown tmp_quality/architecture-before-reproduced.md
)
```

The 64-character measured digest is the report's sorted `rm_client` path/content
digest, not the 40-character Git tree identifier. It binds the measured source text
independently of commit ancestry and also works with a plain source directory
that has no `.git`. The measurement reads UTF-8 with BOM removal and normalized
newlines; the Git tree check additionally fixes the original byte-level tree.
A mismatch fails even when the ordinary debt checks pass.
Keep the original `reports/clean_code/architecture_before.md` as historical
evidence; reproduction outputs belong in a separate path. A later downward
ratchet may correctly reject the old source's larger hotspot counts; the content
digest and reproduced measurements remain meaningful independently of that
current-budget result.

## How to interpret the measurements

The full JSON preserves per-function direct `self` names, state reads/writes,
call targets, parameters, source span, executable statements, decision points,
and control depth. Markdown shows the top executable-statement hotspots and
module fan-in/fan-out. Compare full reports at known revisions when reviewing
extractions.

- Multiline shader strings, documentation, and declarative data can occupy many
  physical lines without adding many executable statements. Neither a small
  AST count nor a large data literal proves that a function is easy to change.
- Nested function bodies are measured independently, not charged twice to the
  outer function. An `elif` chain adds decisions, not artificial nesting.
- Decision counts include `and`/`or`, comprehensions, and exception branches.
  They are explicitly defined review signals, not a claim of exact McCabe
  complexity or a measure of how many responsibilities a person would identify.
- Static imports, direct `self` attributes and literal `state.field` paths can
  be measured. Dynamic imports, reflective dispatch, aliases, indirect field
  mutations and effects inside collaborators require code review and behavior
  tests. Deferred-cycle components remain visible as coupling debt.

## Test design and source guidance

The checks follow the supplied book's emphasis on readable, independent,
repeatable tests, one concept per test, consistent team formatting, and placing
responsibility with the object that owns it:

- [Chapter 9: Unit Tests](https://aeryzhao.github.io/cleancode-book/ch9.html)
- [Chapter 17: Smells and Heuristics](https://aeryzhao.github.io/cleancode-book/ch17.html)
- [Chapter 5: Formatting](https://aeryzhao.github.io/cleancode-book/ch5.html)

Use build/operate/check fixtures and observable behavior for new service tests.
Keep hardware-safe defaults and test error, interruption and retry paths. A
private attribute may be a deliberately retained legacy test seam, but a broad
snapshot of every newly added private field is not a substitute for a public
compatibility contract or a behavioral assertion.

## Window compatibility contract and legacy audit

```sh
python tests/api_freeze_test.py
python tests/api_freeze_test.py --mutation-selftest
python tests/api_freeze_test.py --legacy-snapshot
python tools/verify_all.py --test api_freeze_test --test test_api_freeze_platform_regressions --test test_window_api_contract --json tmp_quality/api-contract-tests.json
```

Default compatibility mode protects the 1,036 public entries in the existing
snapshot plus 78 explicitly retained private caller seams. The manifest
`tests/window_api_contract.json` records up to three independently observed
caller locations for every private seam, and 540 actual Python call signatures.
It preserves names, parameter order/kinds/defaults, callable kinds, stable
attribute types/default values, the narrow Qt-version/path portability rules,
and the module-level exports. Type annotations and a method's implementing
Mixin/class name do not change which calls it accepts, so they are not compared
as calling conventions. Added public methods do not break existing callers.

Private storage without recorded external callers and new implementation fields
are not implicitly made permanent APIs. Existing behavioral tests remain in
place. A contract of 1,114 members is evidence about that named surface, not a
claim that every possible external caller or runtime behavior was verified.
For example, static caller discovery does not resolve dynamically constructed
attribute names; inspect relevant consumers when moving a private seam.

On 2026-10-16, two storage aliases (`_field_frame_times_ms` and
`_last_field_frame_log_at`) retired from the mandatory private-seam set after
migration to `FrameTelemetry`. Their former callers in GPU warmup/UI-state
harnesses now use that owner. Remaining uses characterize the owner or the alias
itself, so they are not independent caller evidence. The manifest's
`retired_private_members` retains the original locations, implementation stage,
replacement fields, rationale and behavior-test paths. Those records cannot
exempt a public member or a still-active private seam. The runtime aliases stay
in place: `test_window_construction.py` checks assignment and reading in both
directions on an actual window, while `test_frame_telemetry_contract.py` checks
the owner's reporting behavior. Removing either alias from a synthetic snapshot
still fails the historical audit.

`_last_present_time` remains protected because `overlay_live_capture.py` and
`refactor_golden.py` reset it; its pre-existing volatile classification protects
presence without asserting its changing value/type. `_ui_tick_stages` remains
protected, with normal-frame and tick-behavior test consumers and stable-type
negative controls. The caller-evidence check itself is unchanged.

The original 1,161-entry `tests/api_freeze_baseline.json` is unchanged. Its digest
is pinned by the compatibility manifest, so refreshing the historic snapshot
cannot silently approve changed defaults. `--legacy-snapshot` still checks the
full original `dir(window)` surface and method qualnames, reports real drift,
and returns failure when it differs. It is deliberately an opt-in historical
audit after compatible implementation extractions, not a synthetic passing
result. Any intentional drift should be explained with the affected name and
its behavior tests.

`--update` is restricted to `--legacy-snapshot` with a separate `--baseline`
destination for review. It never updates the compatibility manifest or overwrites
the committed historical evidence by default. Do not copy a fresh dump over the
baseline to mask a failing contract.

Negative tests prove that public callable removal, changed arguments/defaults,
missing signature evidence, protected private removal/type drift, module export
loss and attempted volatility exemptions are caught. They also prove that a
provider-only move or added private collaborator can pass the compatibility
contract while the legacy full audit still reports the difference. The real
window mutation command deletes `draw_watermark`, checks that removal fails,
restores it, and checks that the original contract passes again.

### Asynchronous workflow behavior is a separate contract

Preserved names and call signatures do not prove preserved completion timing.
The asynchronous lifecycle intentionally makes the first `window.close()` return
before retained native owners finish; that close is ignored until completion is
confirmed and the event loop accepts a later close. Likewise, returning from
`apply_config_data()` is not proof of committed runtime configuration. Callers
must respect `configuration_change_pending` and the owner-thread completion
path. A passing API snapshot is not synchronous-behavior compatibility evidence
for these operations.

Keep these focused behavioral suites in the verification inventory:

- `test_backend_async_lifecycle`: public request/poll/shutdown/retry operations,
  latest-request ownership, locked output, failure visibility and stopped
  recovery. Private worker storage is not added to the window snapshot.
- `test_window_async_lifecycle`: a real offscreen window's first rejected close,
  responsive event loop, owner-thread final save, no normal runtime work while
  closing, and scenario completion routing.
- `test_window_normal_frame`: settled normal ticks execute the production
  presentation, control and backend stages. Their counters must increase on
  each normal frame, pause during a controlled pending transition, and resume
  after real owner-thread completion; launcher/HUD/ClickGUI paints enter
  the actual `paintGL()` compatibility path. Only its final `QPainter(window)`
  target is redirected to a real `QImage`; nested paint devices remain intact.
  This checks real CPU drawing and nonempty output, not native GL presentation
  or visual pixel equivalence. Both uncaught frame errors and recorded
  `_run_tick_stage` errors fail the smoke. Python network audit events are
  rejected; native Qt audio probes remain outside that audit's scope.
- `test_configuration_transactions` and `test_async_configuration`: accepted
  settings/profile changes, pending-versus-committed status, exact
  values/options/binds rollback, failure reporting, and no implicit re-arm.

The API harness uses `settle_window_lifecycle` before stable sampling and
`close_window_safely` in every teardown path. These helpers pump the real window
lifecycle and Qt events; they do not substitute synchronous backend shutdown.
Pending timeout or unconfirmed native cleanup must fail the test, including
snapshot-update mode. Do not delete the window immediately after the first
close or suppress a cleanup failure to make the contract check green.

The general `smoke_test` window fixtures and `student_frontend_test` also wait
for startup profile settlement before exercising normal interactions, then
confirm asynchronous close completion. Directly editing a registry value while
an initial profile transaction is pending can be reverted by that transaction;
it is not a valid setup for a language-toggle or hotbar-edit assertion. Their
existing interaction assertions remain intact. Tests specifically about input
during a pending transition must instead assert that transition's explicit
contract, without pre-settling it.

Run the short normal-frame smoke directly with
`python tests/test_window_normal_frame.py`, or select it through
`python tools/verify_all.py --test test_window_normal_frame`. It must report three
executed unittest methods, covering multiple frame/surface cases, rather than a
zero-test success. Its standalone entry sets the same optional-import telemetry
and capture/media guards as the runner.

## Historical implementation evidence

`tools/module_backend_map.py` keeps the retained Tk prototype in a separate
historical-evidence appendix. It excludes that implementation from current Qt
module-name coverage only when `rm_client.app.main` is a direct forwarder to the
canonical `rm_client.ui.polar_app.main` and there is no other statically visible
production consumer of the historical client. A filename alone is insufficient.
The post-extraction facade must reference the moved implementation only through
its explicit lazy compatibility export. Unverified sources stay in the search.

The AST report keeps historical functions in its full statement/decision totals
and marks their source role. Moving the same class from `app.py` to
`legacy_tk_app.py` does not count as reducing its complexity or wiring a setting.
The settings-orphan audit remains a separate command with its existing scope.
No classification changes its baseline automatically. The module map retains
its manually reviewed section and now describes missing grep evidence honestly:
absence of a nearby name does not prove there is no generic/dynamic consumer.

## Optional dependency telemetry in local verification

Every `verify_all.py` child gets `CI=true` before importing test/application
code, in addition to `POLAR_DISABLE_LOCAL_CAPTURE=1` and
`POLAR_DISABLE_MEDIA_PRELOAD=1`. This applies to offline, native-desktop and
release profiles and does not mutate the invoking process's environment or
start any hosted CI job.

The installed OpenVINO 2026.4.1 wrapper initializes its optional telemetry with
`disable_in_ci=True`. In openvino-telemetry 2025.2.0,
`OptInChecker._run_in_ci()` recognizes `CI=true` and `check()` returns declined
before reading a consent file. This behavior was verified from the installed
official package's source by executing only those isolated AST methods with
file access prohibited. No OpenVINO import, consent-file modification,
telemetry initialization, or network request was needed for that check.

The release freezer applies the same opt-out separately: `build_release.ps1`
sets `CI=true` for its PyInstaller invocation and restores the prior process
value (including absence) in `finally`. `POLAR-RM.spec` also sets it before hook
imports, so direct spec invocation is covered. The spec runs in the freezer;
this does not inject a telemetry preference into the packaged application.
`tests/test_build_telemetry_environment.py` checks the PowerShell source contract
and executes the real spec with inert PyInstaller hooks in isolated Python
children. No PyInstaller installation, real freeze, Windows packaging, or actual
SDK import was performed for that check. A freezing-time external request was a
review risk, not an observed reproduction in this environment.

For standalone Qt/inference tests outside the runner, set the same environment
before imports. On a POSIX shell:

```sh
CI=true POLAR_DISABLE_LOCAL_CAPTURE=1 POLAR_DISABLE_MEDIA_PRELOAD=1 python tests/api_freeze_test.py
```

This is an opt-out for the observed official dependency path, not a claim of a
universal network sandbox. Keep denied external requests denied, inspect other
optional dependencies before importing them, and continue to distinguish local
fixtures from hardware/network qualification. Environment-contract regressions
exercise both all profile combinations and a real inert child process; they
never import the telemetry package.
