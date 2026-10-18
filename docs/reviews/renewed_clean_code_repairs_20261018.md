# Renewed clean-code repairs: 2026-10-18

## Frozen stage and evidence status

Four bounded repairs are frozen at local commit
`0b5692b74ba4ee8b40dc7183a23b779d946f8478`, published as
[1b03e46251aca63d186bf484ff0bf9efe2a7fabe](https://github.com/lulunomaro/polar-rm-client/commit/1b03e46251aca63d186bf484ff0bf9efe2a7fabe),
with tree `a68108aed5472938d3aa5ff0a87add9e301e74ba`.
Local/public commit mappings are parent-verified; connector-created commits have
different IDs. The full offline run has **completed: 353 PASS, 12 SKIP,
4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`). Independently read local result:
`client-renewed20h-full1/results.json`, run ID
`5105544384da4bb49b4a3eee725df69f`. Its source-at-start records the exact local
commit/tree above and a clean worktree.

Declared source stability passed: both endpoints contain **702 inputs** with
SHA-256 `b0a7c5e6efa6080ec8d7506b0ba844b4f72c5bc34b78d0d1c6d1cdfde4f9dd86`.
The scope covers declared code/configuration suffixes under `rm_client`, `tests`,
`tools` and `configs`, plus root `main.py` and `requirements*.txt`. It excludes
assets, external fixtures, installed packages and documentation; endpoint
identity does not rule out transient edits restored between captures.

The four incomplete suites still require the team CRC reference, selected
firmware and vendor dump for DT7 comparisons, or the separately mutable legacy
patch-installation test. Their unchanged gates prevent a complete GO.

The prior 349-PASS aggregate is historical remote evidence. Its original local
raw logs and verification environment were lost during workspace reset; this
stage does not claim to have rerun or independently re-established that result.
No raw logs are published with this report.

## 1. Referee observer ownership

- Local `d026144ff9063d1434820d862892c3c2215e5483`; public `c021923`.
- Source: [manager.py](../../rm_client/backend/manager.py),
  `_notify_referee_view`; regression:
  [test_referee_observer_ownership.py](../../tests/test_referee_observer_ownership.py).
- A shallow copy of decoded data retained nested list/dictionary aliases. A
  presentation observer could mutate authoritative state even before raising
  its own handled exception. The boundary now deep-copies the observer payload;
  observer failure accounting remains separate from state application.
- Four new methods exercise real repository codecs/adapters and the manager
  application path, including current/legacy profiles, retained references and
  nested decoded dictionaries. Baseline: **5 failing outcomes, 0 errors**.
  Independent selections: **26 passed** and **23 passed**; these are different
  selections, not a claim of 49 distinct tests.
- The existing top-match-bar integration fixture imports `deepcopy` and exposes
  it in the extracted-method execution namespace; its original assertions are
  unchanged. No MQTT, serial or hardware session was needed to establish this
  ownership defect.

## 2. Configuration nesting rejection before mutation

- Local `4a1858d51c6fa0a693dd5a0fd9b5aa20fe9a10b5`; public `d2a4a17`.
- Source: [config_store.py](../../rm_client/config_store.py) and
  [validation.py](../../rm_client/configuration/validation.py); regression:
  [test_config_json_nesting.py](../../tests/test_config_json_nesting.py).
- Excessively nested JSON could escape the established rejection policy as
  `RecursionError` during decoding or encoding. Narrow JSON helpers translate
  this expected content failure into `ValueError`; loaders retain their ordinary
  rejection result. Validation likewise rejects encoder recursion exhaustion.
- Import now preflights the actual indented encoder before replacing a backup.
  Compact validation alone can succeed where indented encoding fails. The
  negative control removing this preflight produced **1 failure**, demonstrating
  that backup preservation requires the added ordering.
- Nine new methods: baseline **9 error outcomes**. Independent focused selection
  **44 passed**; author selection **48 passed**, with different neighboring tests.
  Temporary files verify unchanged profile/startup/backup bytes on rejection and
  ordinary successful paths. Runtime recursion limits were not changed.
- These checks establish normal-operation rejection and file preservation;
  they do not establish power-loss durability or a universal nesting limit.

## 3. Uncaught worker-thread counterevidence

- Local `53fd636dfa1026a8ad2665f50105b8a2dcadace7`; public `1bd831b`.
- Source: [verify_all.py](../../tools/verify_all.py), `execute_script`; regression:
  [test_verification_thread_exceptions.py](../../tests/test_verification_thread_exceptions.py).
- A real worker could raise an uncaught assertion while unittest printed `OK`
  and the child exited zero. The runner consequently classified the check PASS.
  The child bootstrap now installs a thread exception hook before starting its
  watcher. It synchronously emits an anchored failure marker, then delegates to
  the original hook to retain the traceback. Existing classification recognizes
  the marker; there is no generic traceback-text rejection rule.
- The hook remains installed through interpreter shutdown so late non-daemon
  failures are visible. Main-thread exit behavior is unchanged. Thread
  `SystemExit` retains default ignored semantics. Caught exceptions and scoped
  custom hooks explicitly capturing expected errors remain supported; this is
  not universal accounting for custom exception-handling policies.
- Initial six-method baseline: **2 failures, 0 errors**. Independent review
  rejected the first candidate because unterminated stderr could prefix the
  marker and hide it from anchored classification. A new real-bootstrap
  regression reproduced that failure; the marker now starts with a newline.
  Revised **7 methods passed**. Failed-candidate evidence remains separate.
- Existing registry suite: **44 passed on rerun**. Its first run had one failure
  from an additional source-stability failure while shared sources were changing;
  that unsuccessful run is retained rather than counted as a clean pass.
  Nothing here establishes hidden thread failures in the historical 349 run.

## 4. Escape-menu capture retirement

- Local `0b5692b74ba4ee8b40dc7183a23b779d946f8478`; public `1b03e462`.
- Source: [escape_menu_mixin.py](../../rm_client/ui/polar/mixins/escape_menu_mixin.py);
  regression: [test_escape_menu_capture_epochs.py](../../tests/test_escape_menu_capture_epochs.py).
- A mouse press retained across keyboard navigation or a menu-page change could
  activate a different action when released. Capture is now cleared before page
  actions, navigation and visibility-transition callbacks. Fresh same-page mouse
  and keyboard interactions remain covered.
- Baseline: **5 failing outcomes, 0 errors**. Independent focused selection:
  **62 passed**; author selection **58 passed**, with different neighbors.
  Tests route real Qt events through a QWidget host and production mixins;
  settings/close effects are inert recorders. This is not physical Windows,
  display-device or robot qualification.

## Scope and follow-through

The repairs use existing ownership, rejection, classification and input-routing
boundaries. They add no new framework, relax no external-reference gate, and do
not imply an architecture-wide reduction in coupling. The completed full offline result above preserves the remaining
SKIP/INCOMPLETE gates and source-stability scope. It does not establish hardware
qualification or supersede the historical run with a claim about its original
raw evidence. This report itself changes only documentation.
