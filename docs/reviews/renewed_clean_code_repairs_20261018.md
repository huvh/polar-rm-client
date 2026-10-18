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

## Second stage: receipt age and tactical-map hold

This separate stage is frozen at local
`9a076129cc4979494137f720c7e8703839a04ad4`, published as
[46219cc63644d8e379eb8b95f43f95d4e10cc8c3](https://github.com/lulunomaro/polar-rm-client/commit/46219cc63644d8e379eb8b95f43f95d4e10cc8c3),
tree `88dc0a9f96b9d3e407d94f738e110a20f6659e37` (parent-verified mapping).
Its full offline run, `client-renewed20h-full2/results.json`, has **completed:
355 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`). The result
was independently read, run ID `f5caf4028f5d4c5a8a1f40659642595c`, with the exact
local commit/tree above and a clean source-at-start worktree. Both source
fingerprints contain **704 inputs**, SHA-256
`406db1b4bab783c5576867743d5174dd2395fbf455cef2784364d630ec55c0de`;
source stability is PASS under the same declared scope and endpoint limitations
as the first run. The four prerequisite suites remain incomplete. The completed
353-PASS checkpoint above remains the separate first-stage result.

### MQTT callback-entry receipt time

- Local `300df566dd59361081de349f7523175283e37dbd`; public `c84fe18b`.
- Source: [mqtt_backend.py](../../rm_client/backend/mqtt_backend.py) and
  [transports.py](../../rm_client/transports.py); regression:
  [test_mqtt_callback_receipt_time.py](../../tests/test_mqtt_callback_receipt_time.py).
- Receipt time was sampled after validation/hooks/decoding. Slow processing could
  make an older message appear newly received to downstream freshness checks.
  The backend now captures the monotonic timestamp on callback entry after the
  client-identity check and carries that same value into both raw and decoded
  queues. Existing generation/profile/client checks still discard obsolete
  callbacks before enqueueing.
- The bridge accepts a keyword-only receipt timestamp for that internal handoff;
  ordinary three-argument callbacks capture their own entry timestamp. This
  preserves the existing callback invocation form and avoids resampling the
  supplied timestamp. It does not add new packet formats or freshness cutoffs.
- Initial five-method baseline: **4 failures, 0 errors**. Final regression has
  **6 methods**. Author focused selection: **86 passed**. Independent groups
  contain **56 unique methods**: 50 plus 12, with six overlapping methods.
  These totals describe their respective selections rather than additional
  independent tests to sum together.
- Tests cover delayed hooks/decoding, preserved event age, discarded stale
  generations, malformed/unknown packets and direct bridge compatibility.
  They use repository decoding and controlled clocks without a live broker.

### Tactical-map hold retirement

- Local `9a076129cc4979494137f720c7e8703839a04ad4`; public `46219cc`.
- Source: [input_dispatch_mixin.py](../../rm_client/ui/polar/mixins/input_dispatch_mixin.py);
  regression: [test_tactical_map_hold_retirement.py](../../tests/test_tactical_map_hold_retirement.py).
- A held map input could survive modal/focus/lock boundaries and remain active
  after the modal closed. Two assignments clear `tactical_map_hold` at the
  beginning of the existing modal-neutralization and control-lock hooks, before
  callbacks or reentry can observe the old intent.
- Three new actual-window methods: baseline **14 failing outcomes, 0 errors**.
  Author focused selection: **72 passed**; independent selection: **63 passed**,
  with different neighboring tests. Independent positive controls confirm a
  properly eligible fresh map-point action still works while retired stale
  intent is rejected; callback-error probes verify hold retirement precedes
  cleanup failure.
- The change adds no new permission or backend authority and does not bypass
  existing map-command eligibility. Real offscreen Qt routing and inert command
  recorders establish input ownership, not physical transmission or Windows
  device qualification.

Only this report is updated to record the completed second-stage full run.
No raw logs are included or published.

## Third stage: receive-epoch history and release ZIP publication

The integrated source for this stage is local
`3f94f0f0a4ac3d0a8313f9fc49808ff021b4652a`, public
[32da8ad51baf5834fdd77f8ee7c29afc4bd946e2](https://github.com/lulunomaro/polar-rm-client/commit/32da8ad51baf5834fdd77f8ee7c29afc4bd946e2),
tree `2f08204b1eb2a3dc96fbbe7fb171c6873e3e65b5` (parent-verified mapping).
The full offline run, `client-renewed20h-full3/results.json`, has completed:
**358 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`). Its result
was independently read, run ID `41c9338e5bb543a3a369ee25acaeeab7`, against the
exact local commit/tree above. Provenance records **dirty: true**: documentation
was edited or untracked during this stage, so this is not a clean-worktree claim.
The declared verification source inputs remained unchanged: both endpoint
fingerprints contain **707 files**, SHA-256
`8fece1870f64b410d1e3c3d9af90ebcafb45d222af2a942b01e698dde9a96d04`.
Source stability is PASS under the declared source-input and endpoint limits
already described above; this excludes documentation, assets, external fixtures,
installed packages and transient edits restored between captures.

The PowerShell publication suite actually ran through `POLAR_TEST_PWSH`: its
result is **6 unittest tests passed, 0 skipped**, exit code 0. It was not counted
as passing through runtime unavailability or a class skip. The four prerequisite
suites remain INCOMPLETE. The completed 353-PASS and 355-PASS runs above remain
distinct historical checkpoints. This integrated source also contains the
separately documented H264 issue 20 correction; its evidence is not folded into
either focused result below.

### Official-feed receive-epoch retirement

- Local `c0e7ff8`; public `04a1d072`.
- Source: [combat_events.py](../../rm_client/combat_events.py) and
  [video_backend_mixin.py](../../rm_client/ui/polar/mixins/video_backend_mixin.py);
  regression: [test_official_feed_receive_epoch.py](../../tests/test_official_feed_receive_epoch.py).
- A changed MQTT receive generation now retires the feed's prior health history,
  event deduplication and freshness clocks before the next raw-message drain.
  Pending `official_feed_at` is explicitly cleared even for an empty batch.
  Profile transitions reuse the same reset operation. This prevents inferred
  events and stale receipt freshness from spanning observed receive sessions.
- Four regression methods: baseline **2 failures**. Author neighboring selection:
  **85 passed**; independent selection: **34 passed**. These are different
  selections and are not additive. The correction does not establish an atomic
  transaction with callbacks already in flight or a globally atomic state reset.

### Release ZIP publication

- Local `bd171b9`; public `1a8797f`.
- Source: [build_release.ps1](../../tools/build_release.ps1); regression:
  [test_release_archive_publication.py](../../tests/test_release_archive_publication.py).
- Previously the builder removed the old output and wrote the replacement ZIP
  directly at its final path. Actual PowerShell execution of the original
  publication block reproduced **4 failures, 0 errors**: missing or locked
  source input left an incomplete ZIP at the final path and replaced existing
  sentinel bytes.
- The existing script now builds a unique sibling ZIP, then uses `File.Replace`
  for an existing destination or `File.Move` for an absent destination. It marks
  success only after publication returns. Temporary cleanup is best-effort.
  Tests cover complete successful archives, failed creation, an injected replace
  failure and a real directory-destination move failure.
- Independent review rejected the first cleanup diagnostic: with
  `WarningPreference=Stop`, a warning after injected deletion failure masked the
  original creation exception. The added runtime regression failed once before
  the correction. Explicit `-WarningAction Continue` now preserves the original
  exception by reference while reporting the retained temporary archive.
- Final author and independent focused selections each report **38 passed**;
  these repeated selections are not 76 distinct tests. The harness parses and
  executes only the production publication helper, never the full builder.
- Runtime: official Microsoft PowerShell **7.4.11**, Linux x64 portable archive,
  downloaded from the PowerShell project's GitHub release into scratch only.
  SHA-256 `55c5429d32256fa0cec4c2529856679f684a41525d78071f78b0fbf1fc3d1f0a`
  matched the official release's checksum file before execution. The harness
  redirects runtime cache/config/data into temporary directories and requires
  an entry marker so runtime startup failure cannot count as expected rejection.
  No global installation, full Windows release, native Windows filesystem-lock
  qualification, concurrent-publisher guarantee or crash-durability claim is made.

This addendum changes documentation only and does not publish raw test logs.

## Third repair stage: queued Qt exception counterevidence

The bootstrap repair is local `77557f224ed2a1b0adda23c1c340372d39f2b6af`, public
[328215e73a81a5d705848e03f0374ff02cc7755c](https://github.com/lulunomaro/polar-rm-client/commit/328215e73a81a5d705848e03f0374ff02cc7755c).
Source: [verify_all.py](../../tools/verify_all.py), `execute_script`; regression:
[test_verification_qt_exceptions.py](../../tests/test_verification_qt_exceptions.py).

A real QObject signal delivered through `Qt.QueuedConnection` to a decorated
slot can report an uncaught assertion through `sys.excepthook`, while unittest
still prints `OK` and the child exits zero. The production bootstrap reproduced
that false-PASS behavior. A separate QTimer Python-callable control propagated
its exception to unittest normally; this finding is not a blanket claim about
all Qt callbacks or evidence of hidden failures in historical runs.

The child bootstrap now emits a newline-prefixed failure marker on an uncaught
non-SystemExit hook invocation and delegates to the original hook to preserve
the traceback. The hook remains installed through shutdown. It does not scan
arbitrary traceback text, alter the production application's hook, or introduce
an unraisable-exception policy. Scoped test handlers may explicitly capture and
assert expected errors. Actual Qt `SystemExit(7)` still terminates the child
with exit code 7 without a hook marker; nonzero-exit classification remains FAIL.

Baseline: **2 failures, 0 errors** across six new methods. Independent focused
verification: **57 passed**, comprising **6 Qt**, **7 existing thread** and
**44 registry** methods. The real subprocess cases include healthy/caught-error
callbacks, custom handler capture/restoration, uncaught queued assertions,
unterminated stderr and SystemExit. No historical aggregate is reclassified
solely because this new counterexample exists.

### Integrated full-run status

The integrated stage, also containing the separately documented H.264 HUD test,
is local `4c63180c9c92c68c5f9252e2dcd1a2b70dfba5dc`, public
[8c51d06fa8a2941322ea710c8efa08a2dbf9bfa0](https://github.com/lulunomaro/polar-rm-client/commit/8c51d06fa8a2941322ea710c8efa08a2dbf9bfa0),
tree `dea2bf3cfd9ed523d28f24ec6b2a235dfe44e332` (parent-verified mapping).
`client-renewed20h-full4/results.json` was independently verified as **completed:
359 PASS, 12 SKIP, 5 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`), run ID
`4e373a09ed304adaae9161e537ba2d7f`. This is an unsuccessful acceptance candidate,
not a successful acceptance merely because FAIL is zero. Source-at-start records
the exact local commit/tree above and `dirty: false`. Both declared source
fingerprints contain **709 inputs**, SHA-256
`e4798ca3fa70537a34633fb0367454fbb9dd2bf9f021da847c4151b9ecbefa89`;
source stability is PASS under the previously stated scope/endpoint limitations.

The extra INCOMPLETE is `tests/test_modal_input_epoch.py`: **300-second timeout;
child tree stopped**. Retained local faulthandler logs show the main thread at
`ui_audio.py:115`, `QSoundEffect.setSource`, through GUI-transition sound from
`open_hero_deploy_interface`. Logs also report unavailable audio output and a
PulseAudio connection failure after its runtime-directory creation failed on a
read-only filesystem. The inherited `test_window_economy_commands.py` fixture
assigned `ui_audio_enabled=False`, a flag not consumed by production audio code,
allowing real native audio into
an input-ownership test. Scoped fixture isolation is under repair. This stack
observation does not establish the underlying native Qt cause or a historical
Escape-menu root cause. Full4 logs remain local and are not uploaded.

The preceding 358-PASS, 12-SKIP, 4-INCOMPLETE, 0-FAIL NO-GO run belongs to public
`32da8ad` and remains separate from this newer unsuccessful candidate. H.264/HUD details remain in the
[issue20 evidence report](issue20_legacy_video_evidence_20261018.md).
Only documentation is changed by this report update; no raw logs are published.

## Fifth full-run stage: fixture isolation and buy-grid category reuse

### Input-fixture native audio isolation

Local `11a26761afab65ce9326616443082da4a060c6e1`, public
[c95649cf55d6d041b6cd9cec2843277f90815399](https://github.com/lulunomaro/polar-rm-client/commit/c95649cf55d6d041b6cd9cec2843277f90815399).
Only test files change: the shared
[test_window_economy_commands.py](../../tests/test_window_economy_commands.py)
fixture and [test_input_fixture_audio_isolation.py](../../tests/test_input_fixture_audio_isolation.py).

Before constructing the real window, the fixture replaces `ReliableAudioPool`
preload/media-preload/play methods with inert call recorders. It retains the
QObject pool and production feedback routing while removing native source
loading/playback from these input tests. The ineffective `ui_audio_enabled`
assignment is removed. Patches are registered for cleanup, including setup
failure, so neighboring tests do not inherit this isolation.

Independent verification: **32 focused methods passed**; safe baseline controls
using mocked native constructors produced **2 failures, 0 errors**. These checks
cover the intended boundary and normal/setup-failure restoration. This is a
fixture-isolation repair, not a production audio fix or a diagnosis of the
native backend's underlying stall. Full4's timeout evidence remains valid and
separate.

### Reuse existing ordered offer categories

Local `80e71dd0f15db91dfecc6a0fe1646f65ff71a20a`, public
[80a78695eb6d422dc81593759c71db69623c2e2f](https://github.com/lulunomaro/polar-rm-client/commit/80a78695eb6d422dc81593759c71db69623c2e2f).
[cs2_buy_menu.py](../../rm_client/ui/cs2_buy_menu.py), `build_grid`, now constructs
the existing ordered category lists once and reuses them for row counts and
column rendering. The original filters/order are retained without adding a
helper module or changing the category definition.

[Category characterization](../../tests/test_buy_grid_category_characterization.py)
compares the same **18 draw/interaction traces** against baseline `1fb3650`,
whose actual module hash was verified. Candidate selection: **8 methods passed**;
separate baseline validation: **1 method passed**. Order/grouping negative
controls produced **12** and **15 failing outcomes**, respectively, with
**0 errors**. These results substantiate this local behavior-preserving reuse;
they establish neither a project-wide coupling reduction nor a performance
score.

### Completed fifth-stage integrated result

The integrated source is local `80e71dd0f15db91dfecc6a0fe1646f65ff71a20a`, public
`80a78695eb6d422dc81593759c71db69623c2e2f`, tree
`702021b8362abf6162bd34b555ba4577b4929b2d` (parent-verified mapping).
`client-renewed20h-full5/results.json` was independently verified as **completed:
362 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`), run ID
`99c6df2d7ce04152b37c369cc9612b08`. Source-at-start records the exact local
commit/tree above and `dirty: false`. Both source endpoints contain **712 inputs**,
SHA-256 `8b60aa16e38cf069ae0207694423aa166bc345cd027e8a8bbfc737a20d824c0c`;
source stability is PASS under the previously stated scope/endpoint limitations.

With the same 300-second child timeout, `tests/test_modal_input_epoch.py` passed
**5 methods** in 1.501 seconds; it did not time out in this run. Full4's timeout
is retained as a separate unsuccessful candidate. This result validates the
scoped fixture isolation; it does not claim that a production native-audio hang
was fixed. The four external/integration prerequisite suites remain incomplete,
so full acceptance is still NO-GO. This update changes only documentation and
publishes no raw logs.

## Sixth full-run stage: GUI audio, fragment isolation and caption extraction

### Respect GUI audio module activation

Local `7e6404747e72c163da15d7a5a55d18c1d919d7e1`, public `bd1c520`.
[config_actions_mixin.py](../../rm_client/ui/polar/mixins/config_actions_mixin.py)
adds the missing module-enabled condition to normal GUI transition sound
admission, alongside the existing setting check. Explicit previews and the
self-disable acknowledgement retain their existing behavior. The
[test_gui_audio_activation.py](../../tests/test_gui_audio_activation.py)
regression has six new methods; baseline **1 failure, 0 errors**, independent
focused selection **41 passed**. This is a specific activation-policy correction,
not a claim to fix or explain the native audio stall observed in full4.

### Reject impossible fragments before pressure eviction

Local `683dc07fc34e3119b73513ba88ffd3fc6322490c`, public `4b10bf6`.
[FrameAssembler](../../rm_client/transports.py) now rejects accumulated payload
larger than the frame's declared total before admitting that fragment and
potentially evicting unrelated frames. The malformed frame is still removed and
counted; a valid sibling can survive and complete. The
[test_frame_assembler_pressure_isolation.py](../../tests/test_frame_assembler_pressure_isolation.py)
regression uses a **5-byte buffer budget**, avoiding giant allocations. Five new
methods: baseline **1 failure, 0 errors**; independent focused selection
**54 passed**. This preserves existing framing and does not establish a legacy
receiver protocol or unlimited resilience to arbitrary traffic.

### Extract diagnostic-caption priority without changing painting behavior

Local `47a8be46cd88f0e351c0a8f926fca1af19b3e62e`, public
`5008a8f235b0b1075191d08382dde7ac8ac7d3f3`.
[module_list.py](../../rm_client/ui/polar/renderers/module_list.py) extracts one
pure `_polar_link_caption` helper in the same module. It separates caption/tone
selection from painting while retaining diagnostic priority and the order in
which later tooltip-only errors occur.

[test_rm_indicator_caption_contract.py](../../tests/test_rm_indicator_caption_contract.py)
compares the frozen full-method fixture and candidate: **5 methods passed on
each**. Author focused selection **60 passed**; independent selection **19 passed**,
with different neighbors. Wrong-priority mutation produced **2 failures**;
early-tooltip mutation produced **1 failure**. Evidence covers panel raster and
recorded text commands, not native glyph appearance, GPU performance or a global
coupling reduction. No helper module or new framework was introduced.

### Completed sixth-stage integrated result

The integrated source is local `47a8be46cd88f0e351c0a8f926fca1af19b3e62e`, public
[5008a8f235b0b1075191d08382dde7ac8ac7d3f3](https://github.com/lulunomaro/polar-rm-client/commit/5008a8f235b0b1075191d08382dde7ac8ac7d3f3),
tree `cd0b0a832f4ec3e9ff2d19b4c689a8b528ad9076` (parent-verified mapping).
`client-renewed20h-full6/results.json` was independently verified as **completed:
365 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`), run ID
`9882f26f0d404472a821ef5844c859a9`. Source-at-start records the exact local
commit/tree above and `dirty: false`. Both source endpoints contain **715 inputs**,
SHA-256 `bd6f7d07f0957bbab44fcc3ca6b59acfda47dc3ab1f59acff48ea5916df20760`;
source stability is PASS under the previously stated scope/endpoint limitations.
No check reports a new timeout. The four prerequisite suites remain incomplete.

The completed 362-PASS checkpoint remains the distinct fifth-stage result.
Full4's timeout and full5's test-only isolation remain recorded above; this run
does not establish resolution of an underlying production native-audio hang.
This update changes only documentation and publishes no raw logs.

## Provenance follow-up: internal fixture inputs

Local `746c38a07382884147d745251caf941c46cae249`, public
[633fd33fc6052bf46b01f71a2325d5e8856a770b](https://github.com/lulunomaro/polar-rm-client/commit/633fd33fc6052bf46b01f71a2325d5e8856a770b),
tree `948917300944b64e325c1d3eb1cff3b71486e657` (parent-verified remote mapping).

The old suffix-based scope omitted four consumed internal text fixture oracles:
`angle_port_admission_baseline.txt`, `polar_health_baseline.txt`,
`tactical_map_71ebb0f.py.txt` and `rm_indicators_caption_baseline.py.txt` under
`tests/fixtures`. [verification_sources.py](../../tools/verification_sources.py)
now fingerprints all regular files under that directory, regardless of suffix.
Existing symlink rejection and hidden-directory/cache exclusions remain in place;
metadata explicitly declares this broader internal-fixture scope. Assets outside
that directory, external fixtures and installed packages remain outside scope,
and start/end equality still cannot exclude restored transient changes.

[test_verification_fixture_inputs.py](../../tests/test_verification_fixture_inputs.py)
uses temporary trees to cover inclusion and add/change/rename/remove behavior,
with rejection/exclusion controls. Baseline: **8 failing subcases across 4
methods, 0 errors**. Independent focused verification: **30 methods passed**.
No fixture oracle content was edited by this repair.

This identifies an old measurement gap, not evidence that any historical oracle
was mutated. The prior **715-input** result measures only its declared old scope;
it must not be retroactively described as covering these text fixtures. The
latest completed full run remains **365 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL,
NO-GO** at local `47a8be46` / public `5008a8f`. At the provenance-repair checkpoint no full aggregate had yet been established;
the subsequently completed seventh-stage result below measures the expanded
scope. Past results remain intact; this report update publishes no raw logs.

## Seventh full-run candidate: callback epochs and bounded map diagnostic

### Retire a drained event batch after callback epoch changes

Local `eb75e0291e424e0edf62f55606937fc6d04f7cf3`, public
[856db3e79aff8af52c3ef2e2871988d095158285](https://github.com/lulunomaro/polar-rm-client/commit/856db3e79aff8af52c3ef2e2871988d095158285),
tree `3f3f7fc4df1278fdf5fed8d0e3cdc53fab8da6e6`.
[video_backend_mixin.py](../../rm_client/ui/polar/mixins/video_backend_mixin.py)
now synchronizes the official-feed receive generation around raw consumption
and combat-event callbacks. If a synchronous callback switches endpoint/profile,
the already-drained old batch is retired; a reentrant consumer's newer state is
preserved. This establishes synchronous callback-reentry behavior, not atomic
cancellation against arbitrary concurrent thread changes.

[test_official_feed_callback_epoch.py](../../tests/test_official_feed_callback_epoch.py):
baseline **3 failures, 0 errors across 4 methods**; independently verified
focused selection **38 passed**. Scalar authority remains with decoded backend
application; this does not grant raw events a new telemetry writer.

### Reproducible tactical-map diagnostic, without a cache change

Local `875f4f6f0f0533ae77014c0f120cf563d901b70f`, public
[0d9161582b0a245c06ee5fadd067d95ec9aca682](https://github.com/lulunomaro/polar-rm-client/commit/0d9161582b0a245c06ee5fadd067d95ec9aca682),
tree `b6a84410bbb0474694ea1cbca7902e27b40c95b2`.
The [diagnostic script](../../tools/diagnostics/profile_tactical_map.py) reuses
the actual-window test host and production map painter for four scenes, each
with **48 frames** covering two transition cycles. Independent execution found
matching corresponding raster pixels and hotspot traces. Details and timing
limits are in the [architecture comparison report](same_metric_architecture_comparison_20261017.md).
No production cache was changed; measured draw times are observations rather
than performance thresholds or native GPU/FPS results.

The script forces Qt offscreen. Its finite workload has no internal timeout:
an external process watchdog is required to bound a hang. It inherits the host's
partial-construction cleanup limitations, and Qt multimedia initialization may
occur. No hardware stream, native display or historical-stutter root cause is
established by this diagnostic.

### Completed seventh-stage integrated result

`client-renewed20h-full7/results.json` was independently verified as **completed:
367 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`), run ID
`84446a49f66341f6ab5373fec96a1a67`. Source-at-start is the exact local
`875f4f6f0f0533ae77014c0f120cf563d901b70f` / tree
`b6a84410bbb0474694ea1cbca7902e27b40c95b2` stage, public `0d916158` above.
Provenance records **dirty: true**; the parent identified this renewed report as
the only dirty file at start. It is not a clean-full-worktree claim.

Source stability is PASS with **722 declared inputs** at both endpoints and
SHA-256 `79b5657b0893577a4e00a7199fd074972b71947fc117586db465721ae7812c07`.
This run explicitly includes all internal `tests/fixtures` regular files under
the expanded scope, retaining hidden/cache exclusions and the documented
external-assets/packages/transient-edit limitations. Earlier 715-input evidence
retains its old scope; no historical coverage is rewritten.

A separate edge where a callback changes endpoint and then raises is under
reproduction. This completed run does not establish that edge as repaired or
exhaustively validate callback reentry. Prior results remain separate. Only this
document is updated; no raw logs are published.

## Eighth full-run candidate: callback raises after changing epoch

The follow-up identified after full7 is repaired at local
`17510e2478cc475bb83d462ea2a2cde403d92583`, public
[415ed09abb32090c5eb34c7b49649f111d406afb](https://github.com/lulunomaro/polar-rm-client/commit/415ed09abb32090c5eb34c7b49649f111d406afb),
tree `56f7c77a8640a0a299730d4debb0e6bdf72da35b` (parent-verified mapping).
The same [video backend mixin](../../rm_client/ui/polar/mixins/video_backend_mixin.py)
now synchronizes the receive epoch in `finally` around each combat-event callback.
A callback that switches endpoint and raises can no longer skip receipt/history
retirement before the next tick stage applies state. The original callback
exception still propagates to the existing stage runner; newer history produced
by a nested consumer is preserved.

The expanded [callback regression](../../tests/test_official_feed_callback_epoch.py)
uses the actual `TickStageRunner` boundary. Baseline: **2 failures, 0 errors
across 6 methods**; independent focused selection **40 passed**. This is the
bounded exception path missing from the earlier synchronous-reentry repair,
not a claim of atomic cancellation across arbitrary concurrent threads.

Full8, `client-renewed20h-full8/results.json`, was independently verified as
**completed: 367 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `b47f401033f04462bf0cf9071367a183`. Source-at-start records the exact local
`17510e2478cc475bb83d462ea2a2cde403d92583` / tree
`56f7c77a8640a0a299730d4debb0e6bdf72da35b` stage above and `dirty: false`.
Expanded-scope source stability passed with **722 inputs** at both endpoints,
SHA-256 `55846af2322d5fe4c10d2ba4d4f04797f2b278379ce2c1d4a35f73d577eb5632`.
The same internal-fixture inclusion, exclusions and endpoint limitations apply.

The prior identically counted full7 result belongs to local `875f4f6` and remains
separate; equal counts do not mean equal source or coverage. This completed run
covers the bounded exception-path repair, while the four prerequisite suites
still prevent a complete GO. No raw logs are published, and this update changes
only documentation.

## Ninth full-run candidate: settings factory failure cleanup

This section is reconstructed from retained findings after the cloud workspace
reset. The original uncommitted ninth-stage report text and local raw logs were
lost; this is a disclosed summary, not a recovery of those exact bytes.

The settings-factory repair was already pushed and is restored at public
[c83c8b94a77120e585bf73b8c677ba2e7c282af2](https://github.com/lulunomaro/polar-rm-client/commit/c83c8b94a77120e585bf73b8c677ba2e7c282af2),
tree `b9de9c287c004cc499beaa74a2a12134b5af3599`. Its earlier local commit
`47696619dea44da7634d3d4503b3ba864f96ae0a` is a historical provenance reference;
it is not assumed to exist as an object in the restored clone.

`rm_client/ui/cs2_settings_center.py` guards setup after acquiring the
factory-created `JelloDialog`. If subsequent setup raises, it cancels acquired
page builders, schedules the acquired dialog for deletion with `deleteLater()`,
and preserves the original exception. Tests preserve host-owned sibling dialogs
and the successful construction path. Failure inside the initial `JelloDialog`
constructor, before the factory acquires the dialog, remains outside this repair.

The actual-Qt baseline reproduced retained dialogs increasing from one to two
on repeated failures. The three methods in
`tests/test_settings_factory_failure_cleanup.py` produced **5 FAIL / 0 ERROR**
baseline outcomes. The author's focused selection passed **77** methods;
independent review passed **68** in a different selection. These are retained
pre-reset findings, not reruns in the restored workspace, and the selections
must not be added as distinct-test counts.

### Interrupted ninth-stage aggregate and recovery boundary

The root runner started full9 at **09:14:45 UTC** from a clean worktree at the
settings-factory checkpoint. Cloud shell transport disconnected during that run.
Recovery checks confirmed the old repository/results were absent and no
`verify_all` process remained. **No completed full9 result was recovered or is
claimed.** Its output directory was `client-renewed20h-full9`; the lost run must
not be assigned a passing aggregate score.

The published full8 summary above remains the latest verified completed result:
**367 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO**, at its separately identified
source and run ID. Its original local raw results/logs were also lost in this
reset. The historical verification is retained as published evidence, not
represented as freshly reverified against locally available raw files.

The restored clone's public commit and tree match the pushed settings-factory
checkpoint. A replacement aggregate requires a new run with its own run ID and
fresh provenance after environment restoration; it cannot be treated as a
continuation or completion of the lost full9. No tests were launched for this
documentation reconstruction and no raw logs are uploaded.

### Completed recovery run, distinct from interrupted full9

After environment restoration, `client-renewed20h-full9-recovery/results.json`
was independently read and verified as **completed: 368 PASS, 12 SKIP,
4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`). This is a new run, ID
`b5096814df534faa8506eadddcb8da37`, started **2026-10-18 09:20:11 UTC**;
it does not supply a result for the interrupted full9.

Provenance records local `21e2fb323319e1ed5380c259757eec170f17dfb2`, tree
`ec5c9c6a2e457147fa674316d34c68ae0befe5f9`, and `dirty: false` at start.
The parent-verified corresponding public checkpoint is
[0d0b35dcd3cbec4909147b3f7283ac5b17aecc93](https://github.com/lulunomaro/polar-rm-client/commit/0d0b35dcd3cbec4909147b3f7283ac5b17aecc93).
Declared source stability passed with **723 inputs** at both endpoints and
SHA-256 `76ed9b5b98d15c0ef143f7f0b732fbd2fd21ea17b3a28efbd5d3ee0587bf7bbe`.
The expanded internal-fixture scope and endpoint limitations remain unchanged:
external fixtures, installed packages, assets outside the fixture directory,
and transient edits restored between captures are outside this comparison.

This recovery result is the latest verified completed offline aggregate. The
four incomplete prerequisite checks still prevent GO; offline success does not
qualify physical hardware. Fresh recovery results/logs are available locally;
this does not recover any earlier raw evidence lost in the reset. All preceding
loss disclosures and historical run distinctions remain in force. No raw logs
are uploaded by this documentation update.

## Tenth full-run candidate: shared selection policies

Two behavior-preserving policy consolidations are frozen at local
`d23443a224672e3ac05b34d15394d14525c33eea`, public
[c9180595ddbdd6ec8a17012b35a62328ae1d762d](https://github.com/lulunomaro/polar-rm-client/commit/c9180595ddbdd6ec8a17012b35a62328ae1d762d),
tree `695e8b9e2d1d2b1bccb8805439b134350b71b26d` (parent-verified mapping).
Each helper remains in its existing module; no imports or helper modules were
added. These are characterized consolidations, with no claim of a repaired
behavioral defect, performance improvement or global coupling reduction.

- `InputDispatchMixin._enabled_overlay_binding_matches` replaces five repeated
  checks in `rm_client/ui/polar/mixins/input_dispatch_mixin.py`. Module presence,
  enabled state, the `"None"` binding sentinel and the existing matcher retain
  their short-circuit order. The two methods in
  `tests/test_enabled_overlay_binding_contract.py` passed on both baseline and
  candidate. Independent focused review passed **40** methods. Removing the
  enabled guard produced **31 failure outcomes, 0 errors** in the mutation check.
- `BackendManager._native_video_selected` in `rm_client/backend/manager.py`
  serves decoder recovery and chunk admission. Each caller explicitly supplies
  its authoritative state: recovery uses `self.state`, while chunk application
  uses its supplied state, which may be a different object. Source aliases and
  exact `deploy_mode == 1` selection are retained. The five methods in
  `tests/test_native_video_activation.py` passed on the baseline; independent
  candidate review passed **50** focused methods. Mutating the mode condition
  to `>= 1` produced **8 failure outcomes, 0 errors**.

Full10, `client-renewed20h-full10/results.json`, was independently read and
verified as **completed: 370 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO**
(`passed: false`), run ID `df060d09f95d431eb3ee76d49ad04177`. The root started
this run at **2026-10-18 09:34:40 UTC**. Provenance records the exact local
`d23443a224672e3ac05b34d15394d14525c33eea` / tree
`695e8b9e2d1d2b1bccb8805439b134350b71b26d` checkpoint above and `dirty: false`
at start. Declared source stability passed with **725 inputs** at both endpoints,
SHA-256 `9c76ffca46b0eadde71db4e29e79db76ef925ae83670b32b2455153ced07cf66`.
The same expanded internal-fixture scope and endpoint limitations apply.

This is the latest verified completed offline aggregate; the four incomplete
prerequisite checks still prevent GO. The earlier completed recovery run remains
separate, including its 723-input fingerprint and 368/12/4/0 NO-GO result.
No hardware qualification or exhaustive defect coverage follows from these
counts. This update publishes only the textual evidence summary; raw logs are
not uploaded.

## Eleventh integrated result: issue-family repairs

The [issue-family audit](issue_family_audit_20261018.md) records the video
evidence, UI repeated-input/nested-factory, and installer lexical-validation
repair families, including focused regressions, counterevidence and limits.
Their integrated checkpoint is local `b45d429b9e410109d227ac28b50a3c0294c84599`,
public [62c31466b08e4a7d2930b4b07312e08b2742f228](https://github.com/lulunomaro/polar-rm-client/commit/62c31466b08e4a7d2930b4b07312e08b2742f228),
tree `a709a945e96773ba8ef24fe8a068892b1ae3218e` (parent-verified mapping).

`client-renewed20h-full11/results.json` was independently read and verified as
**completed: 374 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `7fcbdb0e44a7401ebd911841f636691d`. Source-at-start matches the local
commit and tree above. Provenance records **dirty: true**; the parent identified
only the issue-audit document as dirty at start. This is not a clean-worktree
claim. Declared source stability passed with **729 inputs** at both endpoints,
SHA-256 `1ebbbe27a4d0bad6eaa2809619fcb70d01517f1b7844f5d4f9f597833a629b43`.
The previously stated fingerprint scope, exclusions and endpoint limitations
continue to apply.

This supersedes full10 only as the latest completed offline aggregate. Earlier
runs, interrupted-run history and raw-evidence loss disclosures remain intact.
The four incomplete prerequisites still prevent GO; the aggregate does not
establish native hardware qualification, exhaustive defect coverage or closure
of the GitHub issues. No raw logs are published by this report update.

## Twelfth integrated result: second UI repair stage

The [issue-family audit's second UI supplement](issue_family_audit_20261018.md#第二次-ui-补充旧弹出操作与启动确认)
records stale keyboard Add/Remove actions, nested-modal repaint and
`BindingPicker` cleanup, plus startup confirmation Return/Enter and mapped
numeric-key auto-repeat handling. Independent focused review passed **91**
methods; the baseline produced **33 failure outcomes across 19 methods**.
The initial candidate's nested-modal gap remains documented in that audit.

Integrated source: local `6a802d5c73be8585a0f814997edd38cc8d81243a`, public
[863954d30aa841058a073d2c0020d1468e20ebaf](https://github.com/lulunomaro/polar-rm-client/commit/863954d30aa841058a073d2c0020d1468e20ebaf),
tree `5c24ec773655f730f63892ee48477640bfc8771f` (parent-verified mapping).
`client-renewed20h-full12/results.json` was independently read and verified as
**completed: 376 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `9c2130f8c2084ceba8f4d8e6023a65d1`. Source-at-start matches this local
commit and tree, with `dirty: false`. Declared source stability passed with
**731 inputs** at both endpoints and SHA-256
`60b1df8c68fe76765d0e0db3319a0773a1b48ff11651e90ce343b4003ebcf64e`.
The previously documented scope, exclusions and endpoint limitations apply.

This is the latest completed offline aggregate. Earlier stage results and loss
disclosures are preserved. Four incomplete prerequisites still prevent GO;
these results do not establish native hardware qualification or exhaustive
issue closure. This update publishes no raw logs.


## Thirteenth-stage recovery result: angle receipt boundary

The [issue-family audit](issue_family_audit_20261018.md#角度接收边界补充延迟读取与授权代际)
records the controller-angle read-start receipt time, arm-generation and partial
frame retirement repair. Its local-read bound does not recover hardware sample
time or establish the age of bytes already queued in OS buffers.

The original full13, run `0d123dd22d4342eea7894821c91320e0`, remained incomplete
after the environment transition; its partial files are preserved. The distinct
`client-renewed20h-full13-recovery/results.json` was independently read and
verified as **completed: 377 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO**
(`passed: false`), run ID `109252f3f53e4ee6b7afdcadcbc264ee`. This does not
retroactively pass the interrupted run.

Recovery provenance matches local `3970e7f8ce2b7d4eceec2216ffd1cac7b8065ab9`,
public [1ec12135bfc40576d2e15aaaa97d3e909e3e5a5f](https://github.com/lulunomaro/polar-rm-client/commit/1ec12135bfc40576d2e15aaaa97d3e909e3e5a5f),
tree `09e3660966d6a60919a9bdeadae80e6d193d0d17` (parent-verified public mapping).
It records **dirty: true**; the parent identified only the issue-audit document
as dirty at start. Declared source stability passed with **732 inputs** at both
endpoints and SHA-256
`d86522325be259656961ba6acac5e25967d71fa4ef20db126f6b6bad4572e096`.
Existing fingerprint scope and endpoint limitations apply.

This is the latest completed offline aggregate. Earlier results and evidence
loss disclosures remain distinct. Four incomplete prerequisites still prevent
GO; physical-link safety and hardware qualification remain outstanding. No raw
logs are published by this documentation update.

## Fourteenth full-run candidate: tool output hygiene

The scoped tool repair is local `689f2e175c994ab1352bc7816fca56377113cc2e`, public
[210f5a60223b28d45514f9177da04a281d6e88c9](https://github.com/lulunomaro/polar-rm-client/commit/210f5a60223b28d45514f9177da04a281d6e88c9),
tree `8838f18a4e971d0efd1bde9403e37eb8dd745195` (parent-verified mapping).
`tools/dt7_link/test_dt7_link.py` uses `TemporaryDirectory` for its temporary
configs instead of fixed filenames, preserving pre-existing sentinel files.
`tools/economy_live_capture.py` defers output-directory creation until use and
selects an OS-appropriate output path, avoiding import-time directory creation.
Repository configs were not changed.

Independent review passed the **6 methods** in
`tests/test_tool_output_hygiene.py`; the baseline produced **12 failure outcomes,
0 errors across those 6 methods**. Checks include cleanup after a write followed
by `OSError` or `KeyboardInterrupt`. The extracted DT7 profile's 10 assertions
and mouse check's 8 assertions remain unchanged. Separately, the author reported
**116 DT7 CLI checks with 2 external prerequisites missing, INCOMPLETE**; that
CLI result is not presented as an independent review pass or external validation.

The bounded hygiene audit reported **4,129 tracked files**, with no accidental
runtime files identified. Its **2,366 tracked files matching ignore rules** were
historical `docs/evidence` material and remain preserved. No blanket deletion
or ignore-rule expansion accompanies this repair.

Full14, `client-renewed20h-full14/results.json`, was independently read and
verified as **completed: 378 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO**
(`passed: false`), run ID `4f398ad92b8e4e38ba762080d5a7d8b0`. The root started
this run at **2026-10-18 11:13:27 UTC**. Provenance matches the exact local
`689f2e175c994ab1352bc7816fca56377113cc2e` / tree
`8838f18a4e971d0efd1bde9403e37eb8dd745195` checkpoint above and records
`dirty: false` at start. Declared source stability passed with **733 inputs**
at both endpoints and SHA-256
`96353d352a83e642da6f8cb9041305ef307bf8b036e578ee43e57b822b1eda2d`.
The existing fingerprint scope, exclusions and endpoint limitations apply.

This is the latest completed offline aggregate. Four incomplete prerequisites
still prevent GO; external-reference and hardware qualification gaps remain.
The earlier 377/12/4/0 recovery result belongs to public `1ec12135`; historical
failed/interrupted runs and evidence-loss disclosures remain preserved. This
documentation update changes no source and publishes no raw logs.

## Fifteenth full-run candidate: motion evidence owner reset

Source: local `0de5e521c21e383a0dafb17f508babc7aab0486c`, public
[1b5e962e3950d874c171b64601445e9ff4c3b73a](https://github.com/lulunomaro/polar-rm-client/commit/1b5e962e3950d874c171b64601445e9ff4c3b73a),
tree `437b72ede643fe376a807c3108917cd4323f6a8b` (parent-verified mapping).
The existing `PolarMotionVerifier` in `rm_client/backend/polar_bridge.py` now
owns a `reset()` operation for all its motion history, retaining its injected
clock. `BackendManager` replaces five partial field writes with that operation
and invokes it at three bridge-epoch boundaries. No production module was added;
this local ownership repair makes no global fanout-reduction claim.

The initial eight methods in `tests/test_polar_motion_epoch.py` produced
**7 FAIL / 0 ERROR** against the baseline. The final nine-method regression
passed; independent review passed **95 focused methods**, with **14 historical
assertions/probes** also passing. These selections are not additive distinct-test
counts. Two narrow fixture updates in `test_projectile_counter_baselines.py`
and `test_transport_safety_regressions.py` retained their checks and incorporated
the reset-order contract. The review packet remains local; raw evidence is not
uploaded by this report.

Full15, `client-renewed20h-full15/results.json`, was independently read and
verified as **completed with a failure: 378 PASS, 12 SKIP, 4 INCOMPLETE,
1 FAIL; NO-GO** (`passed: false`), run ID
`80e2c7d449a34cf1a81ea548483daf72`. The root started the run at
**2026-10-18 11:31:38 UTC**. Provenance records the exact local
`0de5e521c21e383a0dafb17f508babc7aab0486c` / tree
`437b72ede643fe376a807c3108917cd4323f6a8b` checkpoint above and `dirty: false`.
Declared source stability passed with **734 inputs** at both endpoints and
SHA-256 `e99d14f1f2043145356fa36177daf1ee1ba0df0094febba989a894ea0d9eeeb7`.
Existing scope and endpoint limitations apply.

The failing suite is `tests/test_fullscreen_input_extended.py`: 12 methods ran,
with one failure in
`test_lazy_page_f11_nested_modal_f12_and_cancel_preserve_safety`. At line 116,
the assertion requiring `slices > 0` received zero. This is a failed integrated
candidate despite the focused motion checks passing. Diagnosis is in progress;
no root cause, retry pass or weakened threshold is asserted here.

Full14's 378 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL at public `210f5a60` remains
the last completed aggregate without a FAIL, on its own earlier source. It
still carries NO-GO for the external prerequisites and cannot qualify this
new candidate. Historical failures and interruptions are preserved. This update
changes only documentation and uploads no raw logs.

## Follow-up candidates after full15 failure

### Separate motion defect: idle time consumed the STUCK budget

A separately reproduced defect in `PolarMotionVerifier` started or advanced the
missing-feedback motion timer without first testing the existing `trying`
predicate. With a live link and zero commanded velocity, elapsed idle time could
therefore produce `STUCK`; a later movement could inherit that elapsed budget.
The actual manager-tick regression also covers disabled drive publishing zero
velocity. These are inert software checks, not physical motion measurements.

The scoped candidate in `rm_client/backend/polar_bridge.py` clears
`_moving_since` when `trying` is false, retaining idle `NO_FEEDBACK` and existing
start/advance behavior for real attempts. Thresholds, timeouts, authority gates
and position-relock behavior are unchanged. The new
`tests/test_polar_motion_idle_budget.py` contains nine methods. The author's
baseline recorded **9 failure outcomes, 0 errors across 9 methods** (six affected
methods, including subcases, and three passing positive controls); the author's
focused selection passed **70 methods**. The baseline checkout was the docs-only
successor `87faa70d29801add86ffac89b2b15c30833f7c50`; the review packet reports
byte-identical verifier source against full15's `0de5e521` as well. Independent
review confirmed that exact checkout and both baseline blobs match Git blob
`3659a28afdcda79d7e67d552e7bdda18b3ac056c`, reproduced the unchanged baseline
outcomes, and accepted the candidate with **70 focused methods PASS**, no errors
or skips. An existing historical verifier function's **14 assertions** and
strict-timeout, zero-origin and rotation release/repress probes also passed.
Mutations retaining the timer across release and ignoring angular attempts each
produced **2 failure outcomes, 0 errors**. These overlapping selections are not
added into a distinct-test count. Accepted source SHA-256:
`3f354ac7b473624cbd455805959aadd9e00f5e52c9abd2683e76d49589bb2730`;
new test SHA-256:
`f85d2f0d65e92ca8a334c184431cccc4678227a8263ebf499a43ada29b7bb48a`.
No new aggregate result is claimed for this candidate.

### Lazy fullscreen synchronization diagnosis and pending test repair

The retained diagnosis uses the unchanged original test method and production
sources. An external wrapper queued one inert 60 ms GUI callback before its
existing fixed 30 ms wait. **Three of three paired delayed-event trials failed**
at the original `slices > 0` assertion. At failure, the panel and page were
visible, entrance animation finished, and the active builder timer was overdue,
yet no slice had run. An additional event-loop turn dispatched the real callback;
that observation did not reclassify the failed trial as a pass.

With the same delay, bounded polling for actual visibility and the first real
slice yielded **three of three paired passes**. The intermediate `slices > 0`
and `ready == False` checks, F11/F12, nested-modal, neutral-input, no-autosave and
cancellation assertions were retained. This supports a bounded synchronization
repair in the test; it is not a UI timing/performance qualification. The test
repair was still pending acceptance at this diagnostic checkpoint; subsequent
acceptance and integrated results are recorded below.

The original full15 did not capture these timer/visibility diagnostics, so its
exact causal delay cannot be established retroactively. Its failed aggregate
remains unchanged and published at
[010ba98bc219a69fc74caa88b647792cc265b2d1](https://github.com/lulunomaro/polar-rm-client/commit/010ba98bc219a69fc74caa88b647792cc265b2d1).
Neither the separate motion repair nor the paired diagnostic trials erase it.
Only this textual report is updated; the local review packets and raw logs are
not uploaded.

### Accepted test-only synchronization repair after paired diagnosis

Independent review accepted the frozen fullscreen test SHA-256
`a3f13e2f576b83d0026127de16db6547501a4329f69dd46c44ef7e272e193648`.
Bounded condition waits observe entrance completion and the first actual build
slice, while preserving `ready == False`. The original safety scenario is shared
with a delayed-event variant; a real Qt callback activates the production timer
and remains busy for 60 ms before yielding. No production scheduler changes.

Author runs passed all 13 methods at each DPR 1, 1.25, 1.5, 2 and 2.5 (65
executions, not 65 unique methods). Independent runs passed 13 methods at DPR 1
and 2.5. AST review confirmed the original first-slice assertion and all 22
subsequent safety statements remain unchanged, as do the other original methods.
Independent negative controls fail for stalled timers, construction errors,
cancellation and premature readiness. The reviewer also reproduced the original
fixed-wait failure from `0de5e521`, including an active overdue timer and zero
slices, then observed a real slice on a subsequent event turn. That failed trial
remains a failure. Full15's exact original delay remains unproven; these focused
results do not replace its failed aggregate or qualify native presentation.

The separate idle-budget source is published at
`c1f10208eda6cddce504340f3af525710c23d709` (local `cc19379e442a2d3607bfa180dbf02930bdbae108`,
tree `8c677d18b723b838530ce0d9dc7432a8af4c1a91`). The combined accepted source
and test repair was subsequently tested in full16 below. No raw logs are included.

### Completed sixteenth integrated result

`client-renewed20h-full16/results.json` was independently read and verified as
**completed: 380 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `a36e52193ccc44f9b8425b65b584b904`. Exact source: local
`59fccabbe5d1ef5458ead95db227e0beefdf5083`, public
[358920a40ea0fb74335be2695a551dffa0e6448d](https://github.com/lulunomaro/polar-rm-client/commit/358920a40ea0fb74335be2695a551dffa0e6448d),
tree `1a84932d774c6ccf3753e1a247c581bfb9f69a93` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**735 inputs** at both endpoints and SHA-256
`39a607e09f6d85f0176f08e4e5e726736d5ebba10e625c52a80fd88d93abb165`.
The existing fingerprint scope, exclusions and endpoint limitations apply.

The aggregate explicitly records `test_fullscreen_input_extended.py` **13 methods
PASS** and `test_polar_motion_idle_budget.py` **9 methods PASS**. These results
belong to this frozen source. An analogous test patch applied after this run is
not qualified by full16. Full15's original failure remains counterevidence;
its precise environmental cause is still unknown and is not retroactively
resolved by this passing aggregate.

Full16 is the latest completed offline aggregate. The four incomplete
prerequisites still prevent GO; hardware and native-display qualification gaps
remain. This report update changes no source and uploads no raw logs.

## Analogous lazy-settings coverage repair: candidate evidence

The follow-on audit of `test_settings_cold_start.py` and
`test_lazy_settings_state.py` reproduced one fixed-35-ms assertion race and four
coverage gaps: under a queued inert 60 ms callback, tests naming mid-build
pause/search/cancellation could pass with zero slices and zero controls. Their
later completed-state assertions remained useful. This establishes test setup
and intermediate-state coverage deficiencies, not broken production behavior.

The candidate changes only these two test files and their existing shared
`test_cs2_settings_center.py` helper. A bounded `partial_page` barrier observes
real entrance completion and real Qt-created controls, with positive slices,
active uncancelled/error-free construction and `ready == False`. It does not
call the builder manually or fabricate a populated page. Static review approved
preservation of all original assertions, the four-steps-per-turn and explicit
stage-yield budgets, final `slices > 15`, and post-pause/cancel quiet windows.
A delayed-event variant exercises the same real timer path.

Author runtime evidence records **48 tests PASS**, plus **30 scenario executions**
across DPR 1, 1.25, 1.5, 2 and 2.5. These are overlapping selections, not 78 unique
methods. The inspected state summary contains **40 checkpoints**, each with
**1–2 real controls, exactly 1 slice, active construction and `ready == False`**.
Four external negative controls reject stopped timers, construction errors,
cancellation and premature readiness, with bounded diagnostic failures.

The first applied cold-start invocation failed at import because its `PYTHONPATH`
setup was missing; that setup error is retained separately from the later
correctly configured runtime evidence. The earlier `TEST_PLAN.md` describes the
pre-application stage; subsequent runtime JSON and logs supply the results above.
Independent runtime review is still pending. No production/performance fix or
new full qualification is claimed: full16 predates this patch and remains tied
to its own source. Full15's failed run and its original causal uncertainty remain
unchanged. Only this report is edited; raw logs are not uploaded.

Independent runtime review subsequently accepted this frozen three-test-file
candidate. It ran 9 selected methods at each DPR 1 and 2.5: **18 executions
PASS**, zero errors/skips. Sixteen captured checkpoints had 1–2 constructed
controls, exactly one slice, visible/active builders and timers, no error or
cancellation, and `ready == False`. These include delayed-event coverage and
all close/reject/accept variants. Existing F12, no-autosave/no-arm, final
>15-slice, four-step and explicit-stage-yield assertions passed. Four independent
negative controls rejected stalled construction, a real generator exception,
cancellation and premature readiness; the stalled case failed near 1.005 seconds.
The reviewer did not rerun the author's full 48+30 executions; counts overlap
and are not aggregated into unique coverage. Candidate hashes and diff checks
matched. A full aggregate on this changed source remains pending.

### Seventeenth integrated result: failed candidate

`client-renewed20h-full17/results.json` was independently read and verified as
**completed with a failure: 379 PASS, 12 SKIP, 4 INCOMPLETE, 1 FAIL; NO-GO**
(`passed: false`), run ID `e4ac0881ab634d9d8171359a15e9af52`. Source-at-start is
local `0e5964e6fb7f32f43f1ac57e75fb8d19b516aa67`, public `c14e551`
(parent-verified mapping), tree `f88346131ab815380cc8df1c1c931e3b9eb90835`,
with `dirty: false`. Declared source stability passed with **735 inputs** at
both endpoints and SHA-256
`8780de7ad2d25b2cb7cb2c7670c9a80825fe67d3cb18bfa731851715dcf24549`.
The existing fingerprint scope and endpoint limitations apply.

`tests/test_jello_settings_keyboard.py` ran **15 methods with 1 failure**.
In `test_jello_checkbox_90_70ms_color_and_rounding`, line 154 performed
`QTest.qWait(120)` and then required `box.motion.progress == 1`; the observed
value was **0.9999937555524715**. Diagnosis is ongoing. No cause, repaired
behavior or passing retry is inferred from the proximity of that value to one,
and the failed assertion is not weakened or reclassified here.

Full16 remains the prior zero-FAIL aggregate, **380/12/4/0 NO-GO**, on its
separately identified public `358920a4` source. It cannot qualify the newer
full17 candidate. This new failure and full15's counterevidence are retained;
external prerequisites and hardware gaps remain. Only documentation is updated,
and no raw logs are uploaded.

## Pending-divergence epoch ownership: integrated candidate

A separate deterministic reproduction at local
`0e5964e6fb7f32f43f1ac57e75fb8d19b516aa67` showed that the arbiter's pending
divergence timestamp survived transport-epoch retirement. The first fresh joint
feedback after a boundary could therefore immediately enter `LOCKOUT` using
elapsed time from the old epoch. Identical external baseline/candidate tests
produced **9 assertion-failure outcomes, 0 errors across 11 baseline methods**
(seven affected methods, including boundary subcases, and four positive methods)
versus **11 candidate methods PASS**. Independent external review verified the
saved source against that exact commit and replayed both outcomes, plus **14
historical authority/slew/lockout assertions** and additional convergence probes.

The seven added production lines give the existing `PolarControlArbiter` an
owner method clearing only `_divergent_since`, called at the three existing
manager bridge-epoch boundaries. Established endpoint/reconnect/reconfigure/
shutdown `LOCKOUT`, command slew references, settings and clock remain intact;
scenario reset retains its existing explicit-clear behavior. No generic reset
framework or new production module is introduced. This repairs old-epoch timer
reuse; safe re-anchoring to a newly connected robot and same-epoch observation
or disabled-planning gaps remain outside its contract.

Subsequent integrated author evidence records **131 focused methods PASS**, API
freeze PASS and static quality gates PASS. Independent integration review subsequently passed the same **131 methods**
with no failures, errors or skips, verified all five frozen hashes before and
after, and confirmed preserved fixture assertions plus strengthened reset order.
API/static/bridge logs were inspected by that reviewer, not rerun. The published
checkpoint is public `1e9171c32f626c19779e62e9a0f67259b761a8f3`, local
`f59490eea6afe2a18d25944f74eae42f5ad5d7c7`, tree
`0e59c0d4d311a9fd60ba122f988a17bc06bcdce1` (parent-verified mapping).
The external-only README and review describe their earlier stage;
the separate integrated logs supply these later author results. Initial harness
errors from calling nonexistent `ingest` were retained separately and corrected
to the real bridge `apply` API before the reported baseline/candidate evidence;
they are not product failures.

No aggregate qualification is claimed for this integrated candidate. Full17's
Jello assertion failure remains unresolved counterevidence, and the other Jello
candidate under diagnosis is not accepted by these arbiter checks. Earlier
failed runs and full16's source-specific result are preserved. Only this report
is edited, and no raw review packets or logs are uploaded.

Final integrated independent review accepted the frozen five-file arbiter
candidate: the exact 131-method focused selection passed with zero failures,
errors or skips. Source hashes matched before/after and production bytes matched
the separately reviewed external candidate. The new regression class differs
only by standalone import bootstrap; both fixture changes preserve prior
assertions and extend reset ordering to include divergence invalidation.
No re-anchoring or same-epoch observation-gap claim is made. Aggregate pending.


## Jello animation endpoint: production candidate

A real timer-callback reproduction demonstrated that the epsilon-based
`JelloReversibleAnimation.active()` could stop its consumer before `update()`
reached the exact endpoint. It reproduced full17's observed forward progress
**0.9999937555524715**, which remained unchanged after another 250 ms; reverse
motion reproduced the corresponding failure to reach zero. This establishes a
production mechanism capable of the recorded symptom, while preserving the
original full17 failure and its missing historical callback trace.

The production change is limited to `active()` returning
`self.progress != self.target`. `update()` already clamps to the exact target;
its arithmetic, animation durations and original keyboard-test assertions are
unchanged. Nine new endpoint methods exercise the repair. Independent review
passed **24 methods** (the nine new methods plus the unchanged fifteen keyboard
methods). Restoring the old epsilon produced **21 assertion-failure outcomes
across nine methods, 0 errors**. Review also checked **9,000 arithmetic operations**
for identical results and **126 fractional cases** for exact termination.

Author focused runs are still finishing at this reporting checkpoint. The
independent focused acceptance does not constitute a new aggregate result or
native-display/performance qualification. Full17 remains **379/12/4/1 NO-GO**;
full16's **380/12/4/0 NO-GO** belongs to its earlier source. No raw logs are
uploaded, and this update changes only the report.

Author supplementary DPR validation stopped on a separate failure: at DPR 1,
1.25 and 1.5, the original 15-method keyboard module and new 9-method endpoint
module each passed. At DPR 2 the original keyboard module passed its exact
endpoint assertion, then failed the following fixed-coordinate color-pixel
assertion at line 155 (15 tests, one failure). This failure is retained; remaining
batch jobs were not run. Baseline equivalence for the color failure is under
investigation. No all-DPR success or color/physical-display qualification is
claimed for the endpoint candidate; the original test remains unchanged.

### Completed eighteenth integrated result: default-DPR scope

`client-renewed20h-full18/results.json` was independently read and verified as
**completed: 382 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `7d2377edfe14410b89fe47d621da6059`. Exact source: local
`9153e0bf45cab8d12255ede2e03c5b795a22bf5a`, public
[62ce34fff4e42be4b5521c2be1779728e3213d70](https://github.com/lulunomaro/polar-rm-client/commit/62ce34fff4e42be4b5521c2be1779728e3213d70),
tree `ad3c124a2371caa74a7696f534b090049a3045e8` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**737 inputs** at both endpoints and SHA-256
`c335e2c633cb21ff1cd669def26c862fe5432d95132b3677f5830ab23d669bfc`.
The existing source scope, exclusions and endpoint limitations apply.

This aggregate ran at the default DPR; it does not establish all-DPR success.
Full17's failed aggregate and the separate DPR-2 color-pixel failure above remain
counterevidence on their respective sources. A separate DPR test correction is
being applied after full18 and is not covered by this result. Full18 is the
latest completed offline aggregate, with four incomplete prerequisites still
preventing GO and native/physical-display qualification still outstanding.
Only documentation is updated here; no raw logs are uploaded.

## Separate DPR-aware checkbox test correction

The DPR-2 color failure was reproduced on both the old epsilon predicate and
endpoint-fixed source with exact progress 1 and a stopped timer. The image was
200x80 for a 100x40 logical widget; blue indicator pixels occupied physical
rows 26..53 while the test sampled physical row 20. Sampling the original
logical row after conversion by the captured image DPR was blue in both.
This is a test-coordinate correction, not a production color/geometry fix.

Only `tests/test_jello_settings_keyboard.py` changes: map the original logical
scan x=0..29, y=20 to image coordinates and add a synthetic mapping regression.
The strict blue >180 / red <100 predicates, original 90/70ms durations,
120/100ms waits, exact 1/0 endpoint assertions, cleanup and all other original
methods remain. The card origin (0,0) is invariant and unchanged.

Author and independent external checks each passed 3 focused methods at DPR
1, 1.25, 1.5, 2 and 2.5 (15 executions per selection). Actual capture DPR and
physical dimensions matched; fractional rounding and all scan points were
in bounds. Four negative controls reject raw coordinates, red=100, blue=180,
and blue outside the sampled logical row. The original failure is retained.

After applying the exact reviewed patch, the complete 16-method module passed
at all five DPRs (80 executions, zero skips/failures). Frozen file SHA-256
`cdbc2081fd219b6cdb42a90309f7fb9795f0f688fb2f1adac849d34c20163755`
matched before/after each run; diff check passed. Counts overlap and are not
summed into distinct coverage. This later source is not qualified by full18;
its aggregate is pending. Native display/DWM/GPU acceptance remains open.

### Completed nineteenth integrated result

`client-renewed20h-full19/results.json` was independently read and verified as
**completed: 382 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `f1a2d87e97664216845d96765dd2cfd3`. Exact source: local
`5277b07d0e33f7f7e91a7ae5caac2ff8da698f1c`, public
[269a050a6a4600301bfd6c6446e9a7cd58bae2ad](https://github.com/lulunomaro/polar-rm-client/commit/269a050a6a4600301bfd6c6446e9a7cd58bae2ad),
tree `ee783a293e4f8a59a7ea16b5eae6c99aed72adbb` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**737 inputs** at both endpoints and SHA-256
`e528533c923a824e1ec1ff9ff308cf82b07b945c581cf36a3a5b99b016eca795`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

This is the latest completed offline aggregate. Its equal counts to full18 do
not imply identical source or coverage. Focused multi-DPR checks remain separate
from this aggregate; the result does not establish a full-suite DPR matrix or
native-display qualification. Original full15/full17 failures and the DPR-2
counterevidence remain preserved. Four incomplete prerequisites still prevent
GO. This update changes only documentation and publishes no raw logs.

## Reported role identity across epochs: external candidate

At baseline `5277b07d0e33f7f7e91a7ae5caac2ff8da698f1c`, the bridge discarded old
reported identity at an epoch boundary while the model scalar could retain it
and select the new connection's drive role. A real manager/bridge/policy/model
reproduction with recording-only transport showed an old hero identity selecting
a 2.0 m/s cap instead of the selected infantry's 1.5 m/s after fresh IMU-only
telemetry. Old unsupported roles could instead block the new selected role.

The identical external regression runs **14 methods**: baseline **16 assertion-
failure outcomes, 0 errors**, candidate **14 PASS**. Independent external review
verified the pinned model/manager bytes and replayed both outcomes. Additional
identity-only probes checked selective/idempotent removal, unrelated-overlay
preservation, replay prevention, independent overlay ownership and established
LOCKOUT preservation. Initial harness import errors were retained separately
and corrected before these results; they are not product failures.

The proposed owner operation clears only `polar_reported_robot_id` and its
replayable model-overlay key, called at the three existing epoch paths. Operator
selection, fresh current-epoch report precedence, same-epoch partial-message
retention, unsupported-role blocks, genuine E-stop and established LOCKOUT
remain unchanged. Repository call-site review found current production GUI/tick/
configuration callers use the same attached `RobotState`.

**Outstanding limitation:** callers using a detached explicit target while
`manager.state` is absent or different can still retain stale identity through
endpoint/shutdown invalidation. An independent probe reproduced that retention.
The external candidate is accepted for the actual attached-state path, not every
optional explicit-target arrangement; broader target ownership needs a separate
contract and repair.

Four-file integration is in progress. No integrated acceptance, publication or
new aggregate result is claimed here; full19 remains tied to its own source.
This section makes no claim about the separate spin investigation. Only this
report is edited and no raw packets or logs are uploaded.

Final integrated identity review accepted the actual attached-state GUI scope.
Author and independent reviewer each ran the same 165-method focused selection:
all passed, no errors/skips. The existing nine role-alignment functions passed;
API/static/diff gates passed. Four frozen file hashes matched before/after.
Production bytes match the external candidate; the regression class differs
only by import setup. The isolated transport fixture adds only `state=None`
and preserves every prior reset-order/cleanup assertion. The detached explicit
target limitation above remains unresolved. No aggregate on this source yet.


### Completed twentieth integrated result

`client-renewed20h-full20/results.json` was independently read and verified as
**completed: 383 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `aeba0c43ae7741d3b6aa586d605b2d93`. Exact source: local
`9584d4b3a1cb4a291f8f440c840d3cb8a7173f33`, public `44f5437`
(parent-verified mapping), tree `31b43f12886d90f15405cd61917b84c6a1cf280e`.
Provenance records `dirty: false` at start. Documentation was edited during the
run; this is a clean-start claim, not an unchanged-whole-worktree claim.
Declared source stability passed with **738 inputs** at both endpoints and
SHA-256 `42aeb4182f8cc9bd13c00b76653f5c3f894f058ae78d18c93f49ab7648402741`.
Documentation is outside that fingerprint; the other established scope,
exclusions and endpoint limitations remain applicable.

This is the latest completed offline aggregate for the attached-state identity
repair. It does not close the demonstrated detached explicit-target limitation,
prove hardware/native behavior, or replace the original failed and interrupted
runs. Four incomplete prerequisites still prevent GO. Earlier full19 evidence
remains tied to its own source. This update changes only documentation and
publishes no raw logs.

## Decoder process-owner acquisition prefix: accepted focused repair

The existing pipe-thread constructor matrix began after `_DecoderSession`
creation. A separate earlier gap was reproduced in `ContinuousMjpegDecoder`:
`Popen` returned a process before queue/session bookkeeping was constructed.
Rejecting either post-spawn allocation returned failure with no retained owner,
no process cleanup calls, and `cleanup_complete == True`, even after `stop()`.
The probe used only fake process/pipe objects; no actual subprocess or device
was acquired. Its first exploratory Queue fault hit an earlier pre-spawn queue
allocation; that mistaken attempt is disclosed separately from the corrected
post-spawn reproduction.

The narrow repair in `rm_client/backend/video_backend.py` allocates the queue
and session before native acquisition, then immediately attaches the returned
process. Failed spawn leaves no phantom retired session. Acquired-process
cleanup failure retains the session, blocks replacement, and uses existing
`stop()` / `wait_closed()` retry. Original startup error and cleanup detail are
both retained within the applicable generation.

The first candidate was independently rejected: a new stop-admission failure
could publish its diagnostic after old cleanup returned, then the old startup
message overwrote it. The added real-cleanup/request-stop interleaving test
rejects that candidate with **1 failure across 5 methods**. The corrected combined
write is under the owner lock and checks generation equality. This is bounded
protection of that new diagnostic write, not proof of every concurrent error path.
The rejected source/logs remain local evidence. An initial fixture also used
`stop()` alone for already-retired-owner retry; it was corrected to the existing
`wait_closed()` contract without changing production retry behavior.

Final `tests/test_decoder_owner_prefix.py` has **5 methods**. Against the preserved
whole baseline module, the identical suite produces **4 failure outcomes,
0 errors**; the generation-diagnostic positive control passes. Author focused
neighbors passed **33 methods**; final independent review accepted **34 focused
methods** in its selection. These overlapping counts are not additive.
Frozen source SHA-256:
`d1dde05f028586f08b0c054e5ee66faadf0af950cad91c7823f81fd9bbd81b34`;
new-test SHA-256:
`44931ea3d496e633e8857a5dd0b1389195dca834e6eb1f89d92da39df2822363`.
Evidence packet: local `decoder-owner-prefix-20261018`, including baseline,
rejected-candidate and revised focused logs. No raw evidence is uploaded.

No new full aggregate or hardware qualification is claimed for this repair.
Full20's 383/12/4/0 NO-GO remains tied to its earlier source; historical failed
runs and unresolved external prerequisites remain preserved.


### Completed twenty-first integrated result

`client-renewed20h-full21/results.json` was independently read and verified as
**completed: 384 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `636093d980664bbe92db0e09e8095973`. Exact source: local
`04cdd8366da105fa337a9018ee01dc18ae53d9fb`, public
[b4e6a15338fe7703b3e4b71961773a58a7640d55](https://github.com/lulunomaro/polar-rm-client/commit/b4e6a15338fe7703b3e4b71961773a58a7640d55),
tree `52cebad65a68c1ac1d282de2d258c8cedbf05d8f` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**739 inputs** at both endpoints and SHA-256
`43f5eadf941cd8d0c238d945f40856ab3da36c0cfae67414564b5bb25a5f1bb0`.
The new `test_decoder_owner_prefix.py` entry explicitly records **5 methods PASS**.
Existing fingerprint scope, exclusions and endpoint limitations apply.

A separate bounded read-only inspection found no additional actionable acquisition
ownership defect in active `CameraCaptureWorker`, `UDPVideoReceiver` and the
`RmVideoBackend.start()` wrapper. Camera acquisition is worker-local within
try/finally, with failed release retained; UDP creates its session before socket
acquisition and publishes the socket before bind. Existing admission/close tests
map the inspected cases. This was source/test inspection, not a new test run,
exhaustive interleaving proof or native-driver qualification; historical Tk
`CameraFeed` was excluded.

Full21 is the latest completed offline aggregate. Four incomplete prerequisites
still prevent GO, and detached-target/native/hardware limitations remain. Earlier
failed and interrupted runs retain their own results. This documentation update
publishes no raw logs.

## Referee-stage evidence ownership: accepted characterization cleanup

This behavior-preserving cleanup centralizes the existing ordered assignments
`current_stage = "0"` then `_stage_seen = False` in
`OfficialSafety.clear_stage_evidence()`. Eight cross-owner sites (three manager,
five MQTT) and the owner's existing `from_scenario` path delegate at their
original positions. The three existing production files have a net reduction
of four lines. No module, policy framework, lock, clock read or notification is
added, and no existing oracle is changed. This is not a new bug-fix claim.

The exact eleven characterization methods passed against the preserved full21
baseline modules and the candidate. Two new owner-contract methods bring the
candidate suite to **13 methods**, covering state-only mutation, independent
mutable-dictionary snapshots, idempotence and setter-failure assignment order.
Author focused evidence records **120 methods PASS**, API freeze and static gates
PASS. Independent review accepted **76 focused methods** and rejected all six
behavior-changing negative controls, including in-place limiter-dictionary
mutation. Expanding the helper calls back into the original assignments yields
full-file AST equivalence for all three production files; the eleven baseline
characterization methods are AST-identical. Counts from overlapping selections
are not additive.

Frozen SHA-256 identities:
- `manager.py`: `9c06ef5260fdc7610043de5d0b275554c2c9f0e22820762974fb9773ceb53a06`
- `mqtt_backend.py`: `6178c623504210257535d38c4d458f8d8202826cea26c1c6df913a705b3b76c6`
- `safety.py`: `99ad3496eccb43813e7fe57e720373f667fd8009f48564c02e265542cbf88baf`
- `test_safety_stage_owner.py`: `46a6902e764f25c3ed98fcb91dc18a34b1f5bca3eb8b6fb9acdd7fe1f9118253`

Observer timing, original exception propagation and partial assignment behavior,
E-stop, qualification and limiter ownership remain unchanged. Constructor field
initialization stays direct, avoiding a new virtual call during construction.
The local packet's README predates independent acceptance; final review logs
supply the later results above. No new full aggregate, global coupling claim or
hardware qualification follows. Full21 remains tied to its earlier source;
this report publishes no raw logs.


### Completed twenty-second integrated result

`client-renewed20h-full22/results.json` was independently read and verified as
**completed: 385 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `ba1af2ed9b8d421b98fc48848d724d8b`. Exact source: local
`c7e71c1f23af4d447d3aa2ae714baf982d3fa169`, public
[51b78544ccda723c3a0cead4971d50db86f0e649](https://github.com/lulunomaro/polar-rm-client/commit/51b78544ccda723c3a0cead4971d50db86f0e649),
tree `70068698f1c93289b2c2463732b330a2f6a42884` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**740 inputs** at both endpoints and SHA-256
`e0b10fbf6e6f435ff59b96ebd3fea367901352fb31f2e97473233e465a8a88b1`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

Full22 is the latest completed offline aggregate. It supplies source-specific
integration evidence for the stage-owner cleanup, not a global decoupling or
exhaustive semantic-coverage claim. Four incomplete prerequisites still prevent
GO; detached-target and native/hardware limitations remain. All earlier failed,
interrupted and completed runs retain their own evidence. This update changes
only documentation and uploads no raw logs.

## Hit-revision ownership: accepted characterization cleanup

`KillFxRenderer.consume_hit_revision()` centralizes the comparison/store pair
previously performed by `VideoBackendMixin.update_elimination_hit_info` against
the renderer's private revision. All production access to that private revision
now belongs to its owner. The two existing production files change by **8
insertions / 2 deletions**, with no new module or framework. Initialization,
`clear()` and `notify_hit()` remain AST-unchanged. This is behavior-preserving
ownership cleanup, not a newly reproduced defect or global decoupling claim.

The caller retains exactly one `int` conversion at its original position and
preserves operation order. Disabled/missing EliminationFX leaves the revision
pending; disabled Hit Info consumes it without later replay. Changed revisions,
including decreasing ones, remain consumed before settings/conversion/notification
failures; equal revisions and reentrant repeats do not notify again. Existing
exception and reset semantics are retained; no audio/asset/clock work is added.

The identical **15 characterization methods PASS** against both full baseline
modules and the candidate. Two owner-contract methods bring the candidate suite
to **17 methods**. Author evidence records **64 focused methods PASS**, **16
existing recording-sound assertions PASS**, and API/static gates PASS.
Independent review accepted **64 focused methods**, **1,000 paired traces**, and
six mutation variants yielding **seven rejecting checks**. Overlapping selections
are not added into unique-test or aggregate counts; existing oracles were not
changed.

Frozen SHA-256 identities:
- `kill_fx.py`: `42550c0814a6b9d6574e4752e79cc4c3c7e6449eead9c26e7c84e65844a31e75`
- `video_backend_mixin.py`: `b5350d32fc8531fae5823415995975631e79c0dfb6cf9832599d16bbbcbf3907`
- `test_kill_hit_revision_owner.py`: `c34910d2103636ef7d956ea8584803e93708c925eec80ccd21c9a234e557908c`

The local packet README predates independent acceptance; the review results above
are separately reported by the integrating owner. No new aggregate, physical
audio or hardware qualification is claimed. Full22 remains source-specific,
and prior counterevidence and external gaps remain intact. Only this report is
edited; raw logs are not uploaded.


### Completed twenty-third integrated result

`client-renewed20h-full23/results.json` was independently read and verified as
**completed: 386 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `612db0098f8146e4a15114335ea5bc76`. Exact source: local
`1fc3e36fd92c8d38ef7da0c69e268ac9aa4938a2`, public
[8a7b6abcc3eb5274bfeeef63df508b56e231f226](https://github.com/lulunomaro/polar-rm-client/commit/8a7b6abcc3eb5274bfeeef63df508b56e231f226),
tree `03ed0ebd80452670f7c044d3d83e472291beba84` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**741 inputs** at both endpoints and SHA-256
`3e6c908d8f3257bcbd6ee4a96b63bc0b4711fee04d1b9699e40d681da0bf662b`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

This is source-specific integration evidence for the behavior-preserving
hit-revision ownership cleanup; it does not turn that refactor into a new bug
fix or prove global decoupling. Full23 is the latest completed offline aggregate,
with four incomplete prerequisites still preventing GO. Native/hardware and
other documented limitations remain. All earlier results and counterevidence
retain their historical source scope. Only documentation is updated and no raw
logs are uploaded.

## ClickGUI close: accepted pointer-epoch repair

An actual pending module press could survive closing ClickGUI through F8,
RightShift, Escape or a programmatic call, then toggle the module and autosave
on its later hidden release. A moved module could assign a hotbar slot, and a
held slider could continue changing its hidden value. The existing pointer
owner already provides cancellation with ownership of the stale left release.
Two production lines in `ClickGuiBuildersMixin.set_clickgui_visible` now call
`pointer_interaction.cancel_epoch()` on a genuine visible-to-hidden request,
before close-side callbacks can reenter release handling. Redundant opening and
already-hidden closing preserve other captures. Fullscreen overlay policy and
radial behavior are unchanged.

The author's identical integrated **17-method** suite produced **11 FAIL,
0 ERROR**, with six positive controls passing on the baseline; all 17 pass with
the repair. Author qualification records **97 focused methods PASS**, API freeze
PASS and static gates PASS. Independent review recorded **143 executions** across
DPR 1, 1.5 and 2: 97 focused methods at DPR 1, 17 capture methods at each additional
DPR, and four independent route methods at each DPR. These overlapping selections
and repeated DPR executions are not 143 distinct tests or an aggregate result.
The corrected independent baseline harness produced **12 relevant subcase
failures, 0 errors** across four methods. Earlier harness attempts with errors
remain in the local packet and are not counted as valid defect evidence.
Negative controls rejected unconditional already-hidden cancellation (**4 failure
outcomes**) and cancellation delayed until after callbacks (**2 failure outcomes**).

Reviewed frozen SHA-256 identities:
- `clickgui_builders_mixin.py`: `853bb8a813633ced5b1de5aaacddb50912cee16fa80f4494e67cf0a17b64250a`
- `test_clickgui_close_capture.py`: `b1d0df6aa42aae38a6b73ba22e5a9709b3ad977b36d867e678c90907d0b732db`

Evidence was read from the local `clickgui-close-pointer-20261018` README and
`client-clickgui-close-independent-review` matrix and test summaries. This is
focused automated acceptance; no new full aggregate or hardware qualification
is claimed. Full23 remains the latest completed aggregate at its own source.
Existing counterevidence and incomplete prerequisites remain; raw logs are not
uploaded.


### Completed twenty-fourth integrated result

`client-renewed20h-full24/results.json` was independently read and verified as
**completed: 387 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `7dd18451a54c41f2b78e49cdca1f1950`. Exact source: local
`f14ec46ff47c4b61d2f0b71edb3f2e65cb8c28d7`, public
[77d78194ad01f542365c7184fe02d108ceababcb](https://github.com/lulunomaro/polar-rm-client/commit/77d78194ad01f542365c7184fe02d108ceababcb),
tree `38230673ef32ac83ab480c922ceac7423428f563` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**742 inputs** at both endpoints and SHA-256
`6bc83e71b5749623ee1485a0bebce2ce6e7bb3c5cf61e2a52a261c14e1552bf5`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

Full24 is the latest completed offline aggregate and supplies source-specific
integration evidence for the ClickGUI close pointer-epoch repair. Four incomplete
prerequisites still prevent GO. Native/hardware, detached-target and other
previously documented limitations remain. Earlier completed, failed and
interrupted results retain their own source scope. This update changes only
documentation and uploads no raw logs.

## Radial focus loss: integrated candidate, final review pending

The documented radial contract is hold Q, point at an existing action, then
release to execute. An actual window retained the active wheel, radial owner
and old selection after `focusOutEvent` had broken its control epoch. A fresh Q
press could then be consumed without a fresh selection, and its release could
execute the stale ClickGUI action. A lost original release could also leave the
wheel consuming input. This is a bounded correction to transient gesture
ownership, rather than a policy that all overlays close on focus loss.

One production line calls `cancel_quick_action_wheel()` first inside the existing
focus-loss release callback. Authority revocation is attempted before that
callback. The existing cancellation owner clears selection and radial ownership
before refresh callbacks; refresh failure still reaches the existing independent
neutral/reset fallback and Qt-finally delegation. Two AST-extracted focus
fixtures explicitly wire the new owner and assert normal-path execution, so a
missing fixture method cannot silently pass through fallback. Existing failure
and neutralization assertions are retained and extended.

The external **11-method** baseline produced **7 failures, 0 errors**, with four
positive controls passing. Its candidate passed all 11; independent review
replayed both and passed seven additional order checks, including rejection of
before-revocation and after-release placements. Integrated author evidence records
**128 focused methods PASS**, API freeze PASS and static gates PASS. Final
integrated independent acceptance is pending at this report checkpoint; these
selections are not summed into an aggregate or unique-test count.

Frozen integration SHA-256 identities:
- `polar_app.py`: `831c571f674631d841fbf2c16adffc12828e62c5af00a8503bc0c69f40445cd7`
- `test_radial_focus_loss.py`: `3ff6986909aad436d8001b8800c10b956f6282f67cc30da84f292100c432bec3`
- `test_focus_loss_failures.py`: `ac2b2bd721ac470adebc034c69a54165636771e47260d089fbb4438671f19e37`
- `test_fullscreen_input_extended.py`: `9fbb0bd38915026a341aa68fe48b80d0d8c0a2d05bb5927394c9cca482476967`

The direct fullscreen route preserves the wheel and selection when no FocusOut
is delivered. Whether native fullscreen generates FocusOut remains unverified;
a delivered FocusOut follows this cancellation rule. Chat drafts, ClickGUI and
ordinary hold/release behavior are preserved in the scoped probes. Reentry
coverage begins at cancellation and covers refresh and subsequent neutral
publication, not arbitrary injected input before that callback. Evidence is
from the local `radial-focus-20261018` packet and integrated logs, using inert
sinks and offscreen windows. Full24 remains the latest completed aggregate at
its own source; no new aggregate, native-focus or hardware qualification is
claimed, and no raw logs are uploaded.

Final integrated independent review accepted all four frozen files: 128 focused
methods passed. Production matches the externally reviewed single call; all 11
radial methods are AST-identical to the external suite. Two negative controls
reject silent fallback: missing cancellation ownership fails retirement, and
an exception after retirement fails the normal-release count. Fixture wiring
is therefore resolved within this scope. Native fullscreen-generated FocusOut
and broader arbitrary reentry remain unverified. Aggregate pending.

## Completed twenty-fifth integrated result

Selected offline aggregate full25 completed **388 PASS / 12 SKIP / 4 INCOMPLETE /
0 FAIL**, still **NO-GO**, run `bab15560d77049dcb6414be57ea6c738`.
Exact tested local source `9b22c93844fb6143446a7b025e984f233411a78d` corresponds
to public `fa30c45771fdaf7723226ee5712dce19648987a9`, tree
`2967f407b4808016a2f03f9eec6227cb80d551d5`. Run-start worktree was clean.
All 743 declared inputs retained identical start/end SHA-256
`30bd54f2eae2e843c2cc4e04837e35fdf427a7e560a3ef796014afa037db5117`.
This source includes the independently reviewed focus-loss radial cancellation
and explicit fixture-owner wiring. Counts are suites/checks, not unique tests
or native/hardware coverage. The unchanged external prerequisite failures and
all earlier failed/interrupted results remain. Native fullscreen-generated
FocusOut is unverified; direct offscreen fullscreen routing is a narrower check.
Later changes require their own qualification. New raw logs remain private.

## Activation fixture: accepted native-audio isolation

A deterministic recording-only probe of the actual activation child reached
**18 QSoundEffect constructions and 18 setSource calls** before its injected
timer-factory failure, despite `POLAR_DISABLE_MEDIA_PRELOAD=1`. That flag guards
compressed-media preload; `UiAudioManager` still eagerly preloads WAV cues.
The probe doubled multimedia construction/device queries and observed the exact
expected retirement dictionary through real abort/rescue handling. This proves
a present fixture isolation gap, not the cause of the historical 30-second
timeout at `93aa839`.

The repair changes only `tests/test_window_activation_failure.py` and adds
`tests/test_activation_audio_isolation.py`. Real window, UiAudioManager,
QObject audio pools, timers, abort and rescue remain. An ExitStack replaces the
native multimedia constructors and all three captured QMediaDevices aliases;
normal and exceptional exits restore aliases and clear the cached device result.
The unchanged five activation routes retain their original expected retirement
states. Independent AST comparison confirms all ten child assertions, three
drain loops, fault injectors, network guard and **30-second timeout** remain.

The same two new guarded methods against the saved whole baseline produce
**2 FAIL, 0 ERROR**. The candidate's **19-method focused selection PASS** is a
general neighboring-test result: its existing constructor-failure neighbors still
have unisolated audio assembly, so this is explicitly not an isolation claim for
all 19. Independent review separately ran **all five activation fault routes**
with native constructors/device queries guarded before application imports and
verified zero guarded calls, real owners and timer/abort/rescue execution.
Baseline and removed-isolation controls fail at QMediaDevices; an intentionally
swallowed QSoundEffect attempt is rejected by the call ledger. A separate process
guard blocked the backend's Git metadata lookup, without launching that process.

Accepted frozen SHA-256 identities:
- `test_window_activation_failure.py`: `8c217b5004584f44f5026ba8422294ae89e9722cc2577230cb06dbfb77ed34dd`
- `test_activation_audio_isolation.py`: `fe01c03c8abc4a5646fca1025588940190243be6b915833241e2fe9f0529bc33`

The local `activation-native-boundary-20261018` packet retains the recording
probe, exact baseline, focused results and the initial failed invocation that
mistyped a neighboring module name. That setup error is separate from the valid
baseline failures. Native cleanup behavior and historical timeout causation
remain unqualified; no production audio fix or new aggregate result is claimed.
Earlier failed runs and external acceptance gaps remain intact. Raw logs are
not uploaded.

## DT7 recovery policy: concrete condition-blocking repair candidate

An event-barrier probe established a current blocking path: an expired explicit
qualification during fault recovery invokes real `OfficialSafety` policy, which
revokes control and synchronously reaches the manager's presentation observer
while `AsyncDt7KeyMouseLink.send` owns `_cv`. Holding that inert observer prevents
another thread from admitting neutral release. The six original structural
methods characterize this defect and confirm that discovery, ordinary/neutral
writes and the other tested observer boundaries already run outside the condition.
This does not identify the cause of the historical **22.028550001778058 ms**
failure: that old no-device fixture did not enter qualification recovery.

The candidate changes only the existing worker's `send` implementation. It
captures recovery generation, fault text/epoch, safety identity and safety epoch
under the condition, evaluates the real policy outside it, then revalidates the
snapshot under the condition before clearing the fault and admitting an intent.
Closing, release (including already-neutral release), changed fault/epoch,
same-text fault ABA, policy replacement and overlapping recovery invalidate
stale results. Existing approval, armed state, pending/exhausted neutral and
confirmed wire-neutral gates remain. Final worker/pre-write authorization is
unchanged. The observer may still delay its own sending caller; it no longer
holds the worker condition throughout that callback. This does not serialize
every independent mutation of the safety object.

External evidence: the 19-method candidate-contract suite produced **14 failure
outcomes, 0 errors** on the saved baseline and **19 PASS** on the candidate.
Independent external review passed those 19, four additional policy controls,
and all 15 existing dispatch methods (**38 methods in these selections**), plus
replayed the six original structural probes separately. Eight runtime-only
removed-guard variants were rejected with assertion failures and zero errors.
The unchanged strict `<20 ms` 250-tick gate reported a maximum **0.8688 ms** in
that review; this is one observed sample, not a historical-cause diagnosis or a
universal latency guarantee.

Integration adds 25 methods from the external 19-method suite and six additional
unchanged-policy controls, retaining their test bodies. Author logs record
**65 focused methods PASS**, eight selected existing dispatch methods PASS,
and API/static gates PASS. Final integrated independent review is pending at
this checkpoint. Overlapping selections are not summed into aggregate counts.
Frozen SHA-256 identities:
- `dt7_worker.py`: `7a8a602cf4e6cdfbf6c38a73e5b277379c1139bf1ac387b3ac80ae6ae75e998a`
- `test_dt7_recovery_policy.py`: `240cf50783e3455d4e11b6c2752b0a920ae779c61078662fc79107b02879734d`

Evidence was read from the local `dt7-condition-probe-20261018` author and
independent-review packets and integration logs. Probes use inert serial/write
boundaries and event barriers; timeout guards are not timing-gate replacements.
No new aggregate or hardware qualification is claimed. A later accepted-source
aggregate may cover this repair together with activation fixture isolation;
previous results retain their exact source scope and all external gaps remain.
No raw logs are uploaded.

Final integrated independent review accepted the frozen DT7 source/test pair:
65 focused methods and eight selected existing dispatch methods passed (73
executions). Production bytes match the reviewed external candidate; all 25 new
methods and fixtures are AST-identical to the external suites. The unchanged
existing dispatch file retains its strict timing/count assertions. The direct
caller is `KeyboardControlBridge._send_direct_dt7`. Historical 22 ms causation
remains unresolved; no full aggregate on this later source is claimed yet.


### Completed twenty-sixth integrated result

`client-renewed20h-full26/results.json` was independently read and verified as
**completed: 390 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `7b00dd45f3294d97960a0353478669ab`. Exact source: local
`0d1dc12d0db93a3c7f1e0941a64b4c7c032115f9`, public
[52492777362cb23e286c5ad00d93b4e52a3ce6ff](https://github.com/lulunomaro/polar-rm-client/commit/52492777362cb23e286c5ad00d93b4e52a3ce6ff),
tree `905c7522877552ffe52b63e73a003514c46f1326` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**745 inputs** at both endpoints and SHA-256
`8df690ca0b614e1f046dcf44163fad577e5e2124cab41b5de73936dda9904d59`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

Full26 supplies source-specific integration evidence for the activation-fixture
isolation and DT7 recovery-condition repair. It does not establish the causes of
the historical activation timeout or strict DT7 timing failure. Earlier failed,
interrupted and completed runs retain their own source scope. Four incomplete
prerequisites still prevent GO; native/hardware and other documented limitations
remain. A bounded public-reference lookup did not obtain the required exact
team CRC bytes, so that prerequisite remains missing without substitution.
Only documentation is updated and no raw logs are uploaded.

## Legacy host-bridge self-test transaction prefix

The direct mutable `tools/firmware/host_bridge/test_host_bridge.py` route reset
preexisting firmware edits before entering its restoration `try/finally`.
Checkout partial failure or apply-launch OSError/KeyboardInterrupt could lose
those edits. Canonical verify_all already forces READ_ONLY=1; that path was not
the reproduced mutation route and its INCOMPLETE result remains unchanged.

The scoped fix enters the existing transaction before preparation, takes the
snapshot before mutation, owns restoration before checkout, and removes the
duplicate manual restore. No real firmware checkout/process was exercised:
actual helper/main code used disposable trees and rejected native spawning.
The unchanged final ten-method suite produced five baseline failures/zero errors
and passes on the candidate. Independent review passed those ten methods plus
22 inert transaction scenarios, including partial checkout, absent/present
headers, CDC bytes, OSError/KeyboardInterrupt/SystemExit and unrelated sentinels.
Two mutations reject late cleanup ownership and double restoration.

The validation/compiler/behavior body, finally, reporting and read-only branch
are AST-preserved. If restoration succeeds, original exception identity is
preserved; if restoration itself fails, that failure remains raised with the
original chained, not falsely reported as successful rollback. Frozen source
SHA-256 `eb026df2bec2412f8dc9983ee12783f08aad1d622936a15104d3911d46f69811`;
new test `b479a4c73e20cb80b300768803ef0ccdf6615abed82d325e49772ec9338fb41e`.
Full qualification of this later source remains pending. No external firmware
installation, raw-log publication or hardware acceptance is claimed.

Publication identity correction for the host-bridge test: local `23f83d4` /
public `15adfdcd` contains test SHA-256
`12511e95ce3c2e5434cccf69040bf2c514b2335e6d42693d815465e88704ed49`,
not the earlier frozen-review hash above. Before staging, the fixture replaced
Python-3.11-only unittest.enterContext with ExitStack plus addCleanup for the
project's Python 3.10 minimum. Assertions and production bytes did not change.
The final hash was independently rechecked and all ten methods passed with
native process creation rejected; the author's 22 focused methods also passed.
This is source/API compatibility review, not an actual Python 3.10 runtime run.
The earlier hash records the prior reviewed snapshot; this paragraph identifies
the published bytes and subsequent final review without rewriting that history.

## Retire native telemetry as one scenario-owned sample

A real PDL1 sample with 42 rounds survived scenario/profile reset in 14 model
fields and its `backend_stats.native_telemetry` mirror. Fresh official ammo-zero
updates without fresh PDL1 then left readiness reporting the old native sample
as recent/ready. This is an inert state/readiness reproduction, not actuation.
`RobotState.clear_native_telemetry()` now restores that owned sample group to
its dataclass defaults and removes only its diagnostic mirror; the existing
scenario/profile reset calls it once. Endpoint/shutdown policy is not broadened.

Author and independent focused selections each passed 127 methods. Independent
whole-baseline replay of the same 13 caller/characterization methods produced
seven failures/zero errors. Fifteen omission controls reject retention of any
one sample field or its mirror. Whole-state comparison preserves other settings,
scalars and diagnostics; actual scenario tests retain four native-video lifetime
counters, selected role and latched E-stop. All three frozen source/test hashes
were verified unchanged. External/native acceptance and other boundary-design
limitations remain. Combined-source aggregate qualification is pending.


### Completed twenty-seventh integrated result

`client-renewed20h-full27/results.json` was independently read and verified as
**completed: 392 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `225dc8585ffb425db146f235d30a96a6`. Exact source: local
`bce40e30301f563e842442b3d05c3689c138654e`, public
[64fcacc77bfd047756006190a7a2390308bd20ef](https://github.com/lulunomaro/polar-rm-client/commit/64fcacc77bfd047756006190a7a2390308bd20ef),
tree `c7b052dfb2dae3f7b55a65e5f64b03656c16de95` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**747 inputs** at both endpoints and SHA-256
`76fac03a0fe4ace6eea8769d352a2080d92813965242e6ae18d5e82c9128600d`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

This is source-specific integration evidence for the native-telemetry scenario/
profile reset and host-bridge fixture cleanup stages. Four incomplete prerequisites
still prevent GO. It supplies no Python 3.10 runtime qualification or native/
hardware acceptance, and does not establish historical timeout/timing causes.
Earlier failed, interrupted and completed runs retain their own source scope.
Only documentation is updated; raw logs are not uploaded.

## Decoded MQTT batch: epoch-admission candidate

The real MQTT owner can retire its receive queues on disconnect while the
manager still holds an already-drained decoded list. An inert reproduction
pauses the observer after one record, invokes the real disconnect callback on
another thread, then observes a second old heat record applied after retirement.
Its original receipt time is retained; no invented current timestamp is alleged.
Earlier raw-message/event consumer fixes remain intact and address a later stage;
they cannot undo this earlier canonical scalar write.

The three-line change snapshots `receive_generation` before draining and checks
it before each decoded record. Retirement stops admission of the remaining list
without clearing new queues or undoing newer nested state. Per-record exception
behavior and final current-state stats/frontend synchronization are unchanged.
The rejected v1 skipped final sync after retirement; its passing initial suite
missed first-record HUD projection and nested applied-counter refresh. Those
positive contracts are now asserted, and the rejected source/logs remain in the
local packet. Two explicit existing MQTT doubles gain `receive_generation=0`;
no production `getattr` fallback or weakening of existing assertions is added.

The same external **19 methods** against whole preserved modules produce
**10 baseline failures, 0 errors**, versus **19 candidate PASS**. Independent
external review reproduced both, passed 27 existing fixture-module methods with
in-memory field wiring, and rejected seven runtime-only negative controls.
Four-file integration retains the production bytes and AST-identical complete
regression class. Author evidence records **165 focused methods PASS** and
API/static gates PASS. Final integrated independent review is pending at this
checkpoint; overlapping selections are not aggregate or unique-test totals.

Frozen SHA-256 identities:
- `manager.py`: `2885aa1553298065ae47b6a5997b105425d7148fb752082fbf2e0e9d1f34acec`
- `test_mqtt_decoded_batch_epoch.py`: `6612ad3fbb9b339687ce08a988c0b4f075e53505dd38a53d6f0d118d2919ebf9`
- `top_match_bar_integration_test.py`: `4abf02df4eb92171439d5fdd640add1fa982048efb56487d02a6237e7c9588f5`
- `test_referee_observer_ownership.py`: `2e50eb8900aa5c8f43c28b014a0692017bb035064f19219702a4800933f92a41`

This is next-record admission, not atomic rollback of a record already executing
when another thread disconnects. Rollover between snapshot and drain may
conservatively discard a newly drained batch; lossless atomic pairing would
require a broader drain contract. Same-generation nesting and source precedence
remain unchanged. Evidence is in the local `decoded-mqtt-epoch-20261018` packet;
no native I/O or new aggregate qualification is claimed. Full27 remains qualified
only at its own source, prior failures/limitations remain, and no raw logs are
uploaded.

Final integrated decoded-batch review is accepted: 165 focused methods passed
independently with zero errors/skips. All four hashes matched; manager bytes
match the external candidate and the full nineteen-method class is AST-identical.
Each existing fixture adds only its one receive_generation=0 field; no prior
assertion changed. This supersedes the pending-review status immediately above,
not the pending full-source aggregate qualification.


### Completed twenty-eighth integrated result

`client-renewed20h-full28/results.json` was independently read and verified as
**completed: 393 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `ad3feb015b4949b89301907f5b6ea819`. Exact source: local
`3823e0aa537248dfb35ff75fa3523904a53c7610`, public
[3f3ed4f0fff4878c8f28ffb42728a6e25b48ee73](https://github.com/lulunomaro/polar-rm-client/commit/3f3ed4f0fff4878c8f28ffb42728a6e25b48ee73),
tree `033f7f4134fe92194a43ebdfcb250f099f4162f8` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**748 inputs** at both endpoints and SHA-256
`0313f75b59a24717c70dc52accbe1855c60540868e00f9d7fb256c6e91db6f26`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

Full28 supplies source-specific integration evidence for the accepted decoded
MQTT batch repair. Its per-record admission and conservative rollover-drop
limitations remain; already-executing records are not atomically rolled back.
Four incomplete prerequisites still prevent GO. Native/hardware requirements,
exact external-reference gaps and historical causation uncertainties remain.
Earlier completed, failed and interrupted runs retain their own source scope.

A separate bounded source/consumer inventory in the local
`final-epoch-sweep-20261018/INVENTORY.md` found no additional demonstrated defect
in the inspected video, POLAR/referee serial, controller-angle and pending-intent
paths. Seventeen selected existing inert controls passed. This is a bounded
inspection plus focused evidence, not exhaustive epoch coverage or an additional
aggregate; no real-FFmpeg codec test was selected. Only documentation is updated,
and no raw logs are uploaded.

## Settings ESTOP filter: Python-wrapper retention repair

Repeated real settings construction/deferred deletion exposed retained Python
wrappers even though the native QObject ownership census returned to zero.
Across the same 18 ordinary settings cycles, the baseline retained **294 tracked
invalid wrappers**; one intentional retain-then-clean sensitivity cycle added
16, giving **310**, versus **zero** on the candidate. The tracked set comprises
dialogs, pages, builders, builder timers and selected editors; this is neither
310 dialogs nor a full heap/byte measurement. All native dialogs were destroyed
in both versions. The same audit's 80 ClickGUI cycles retained bounded maps and
stale-capture protection, with zero native descendants/timers/builders after
cleanup. Separate six-settings-cycle reproduction is corroboration, not another
count to add to this census.

Causal plain-dialog cohorts distinguish the retained per-call filter class:
eight dialogs without the filter and eight with an unstored filter leave zero
wrappers, while the stored-filter cohort retains eight. The repair moves the
nested `EstopFilter` to module scope and keeps explicit strong dialog/host
instance references and the same QObject parent. It does not substitute weak
owner lookup. F12 dispatch logic, application-filter installation, finished
removal and returned-owner behavior are retained; the event-filter body is
AST-identical after accounting for the new local aliases.

The unchanged final seven regression methods produce **2 baseline failures,
0 errors**, specifically wrapper collection in plain and actual settings paths;
the other five safety controls pass. Candidate author qualification records
**17 guarded focused methods PASS**, retaining actual emergency service ordering,
nested-modal F12 behavior, repeat/release/override handling and failure fallback.
The repeated 18-settings/80-ClickGUI probe also passes. Earlier failed diagnostic
expectations about persistent scroll keys and instrumentation are preserved
separately in the local `client-lifecycle-ownership-audit` packet. Final independent
review accepted the frozen hashes: 19 guarded focused methods passed, with paired
eight-dialog cohorts, four actual failure paths and three rejecting mutation
controls. These selections are separate from the author's 17-method result and
are not summed into unique-test or aggregate totals. The reviewer checked the
294+16 author census structurally; the full repeated-cycle measurement was not
independently rerun. Original errors survive the tested exception paths, and
wrappers collect after traceback release.

Frozen SHA-256 identities:
- `emergency_shortcut.py`: `476cbd9aceb443c6cf92df0707d87dc54227f6e60483157ad5ebfda87c025e95`
- `test_emergency_shortcut_lifetime.py`: `c85db203d37daa651f09b1098b0848077c41497808a6b6418c25dc573e9744c7`

This fixes measured Python wrapper/object-graph retention; the native ownership
baseline was already clean. No native QObject leak, retained-byte/RSS estimate,
FPS improvement, indefinite-duration result or hardware qualification is claimed.
No new full aggregate is claimed, and raw logs are not uploaded.


### Completed twenty-ninth integrated result

`client-renewed20h-full29/results.json` was independently read and verified as
**completed: 394 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `fbdfbf7845eb4c0c92f1c641660cbd75`. Exact source: local
`cb61372d25719d2c5157010ffce682f2f51e9e6f`, public
[5ae75ce674391e43dd51e85e3501d58fbe18e289](https://github.com/lulunomaro/polar-rm-client/commit/5ae75ce674391e43dd51e85e3501d58fbe18e289),
tree `9382d549fcff1e65558064ec5b96f11a2234d85d` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**749 inputs** at both endpoints and SHA-256
`a2358a9a6d81118cc53550bde72e239b3e639cfcb0d4d7fbb1d6799ad70689ca`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

Full29 supplies source-specific integration evidence for the ESTOP filter
Python-wrapper retention repair. Four incomplete prerequisites still prevent
GO; external/native acceptance and previously documented design limits remain.
No historical failed or interrupted result is superseded at its original source.

A separate bounded same-family scan parsed 221 production Python files without
errors and found only the two remaining function-local Qt classes, crosshair
Editor and Preview. Its actual offscreen factory/modal/settings probes collected
all **96 tracked wrappers across 24 cycles** (24 Editors and 72 Previews), with
zero residual host descendants/timers/builders and zero native-boundary guard
calls. The local `client-local-qt-class-audit/REVIEW.md` records eight embedded,
eight modal, four ready-settings and four partial-settings cancellation cycles.
No additional defect or source change was proposed. This bounded class-family
check is not proof against all GUI reference cycles, arbitrary constructor
failures or indefinite operation; it supplies no heap-byte, FPS or native-device
claim. Only documentation is updated and no raw logs are uploaded.

### Accepted neighboring constructor-test audio isolation (focused evidence)

`tests/test_window_constructor_failure.py` now reuses the existing, unchanged
`isolated_activation_audio` helper from `test_window_activation_failure.py`.
Its `ExitStack` covers real window construction through deferred cleanup;
the existing guard suite adds constructor-route checks without a duplicate
fake helper or production change. Native audio constructors/device queries are
isolated while the actual window, audio managers/Qt pools, timers, abort and
rescue paths remain exercised.

Independent review (`client-constructor-audio-independent-review/REVIEW.md`)
approved all four actual guarded constructor routes (`after`, `before`,
`diagnostics`, `unavailable`) and the four-method audio-isolation suite. The
traced routes recorded zero native-audio and network attempts. Three negative
controls rejected the saved baseline, removal of isolation, and a deliberately
swallowed native `QSoundEffect` attempt; the latter is detected by the access
ledger after cleanup. Static comparison confirmed the original **15-second**
subprocess deadline, five child assertions, four original methods, fault
injectors, network guard and expected cleanup/rescue dictionaries are unchanged.
The unavailable-timer route still observes incomplete ownership before rescue.

The author separately ran **21 general focused methods** and four direct/runpy
constructor tests successfully. Those selections are not additional independent
isolation proof. The review's initial extra metadata-command classifier used an
incorrect expected Git command shape; its failed trace and corrected replay are
preserved locally. The strict process guard blocked the metadata lookup in both;
no subprocess permission was relaxed.

Frozen SHA-256:
- `tests/test_window_constructor_failure.py`:
  `e62120e2b54153fb47961968b1292a057d33be30dd3a13f5c7c18c4db122a3f9`
- `tests/test_activation_audio_isolation.py`:
  `02438946342551ec82123f6fa1cb6937c6b2d72bb59509ff0ce1798b5fdca0d3`

This is accepted test isolation, with no new aggregate result yet. It does not
establish any historical timeout's cause or qualify native audio/device cleanup.
Full29 remains the last completed aggregate at its recorded source; raw evidence
remains local and is not uploaded.


### Completed thirtieth integrated result

`client-renewed20h-full30/results.json` was independently read and verified as
**completed: 394 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `23d8b665aefa4374b8b5d4fa0774393f`. Exact source: local
`76865f1bc3164252396c6969add6983178126353`, public
[afc252e5c4b7a22bcf9886837b3341d0473cb38f](https://github.com/lulunomaro/polar-rm-client/commit/afc252e5c4b7a22bcf9886837b3341d0473cb38f),
tree `65af73140b2c6b3fb4d3883cc86977ec8e0b1390` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**749 inputs** at both endpoints and SHA-256
`c0840788d562acec1a1e5b0925d229a4bafbb1b3461b7ae2c3bf98a9e36958ee`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

Both `test_window_constructor_failure` and `test_activation_audio_isolation`
passed four methods each. This supplies source-specific integration evidence for
the neighboring constructor fixture's audio isolation. It does not establish a
historical timeout cause or qualify native audio/device behavior. Four incomplete
prerequisites still prevent GO; earlier failed/interrupted evidence and all
external acceptance limits remain intact.

A separate read-only settings-policy scan found no justified behavior-preserving
consolidation in its examined manager/UI readers. Missing, false, zero, malformed
and default-valued settings have distinct existing semantics; numeric validation
already has explicit configuration owners. The local settings-policy scan README
records these distinctions. No test was executed for that scan, no additional
pass count or universal configuration-validation claim is added, and no raw logs
are uploaded.

### Literal owner-write regression gate candidate

The existing `ModuleVisitor` in `tools/quality/metrics.py` now identifies
`Store`/`Del` on seven reviewed literal private-field paths:
`self.kill_fx._last_hit_revision`, `self.safety._stage_seen`, and
`self.polar_motion.{_moving_since,_last_feedback_segment_at,_ever_had_feedback,
_position_origin,_position_now}`. Existing finding/debt machinery handles the
new `cross-owner-private-write` rule. Owner-local writes, diagnostic reads,
owned method calls, unrelated objects and annotation-only targets remain allowed.
No production source, baseline, report schema or new module is changed.

The author reports **68 focused methods PASS**, API/static PASS and rejection of
all seven table-entry-removal mutants. The tests enumerate protected fields
independently of the table. Current-source static JSON before/after is
byte-identical, SHA-256
`d6ee71f1c5a2b41be06b05e458ebdf00a5de654af1bebfdb7f5212723b920fbe`;
this is unchanged measurement, not a coupling or executable-size improvement.
External independent review accepted the bounded proposal, reran actual-path and
synthetic mutation controls, and added 20 grouped syntax controls plus debt
controls. These groups are not repository test-method counts. Final integrated
review is pending; no new aggregate result is claimed.

This is a `path:scope:rule` **count ratchet**, not a field/site fingerprint.
No current baseline allowance permits this rule. A future explicitly reviewed
allowance could be reused by a different protected field/site in the same scope.
Aliases, deeper/differently named receivers, reflective `setattr`/`getattr`,
container/descriptor mutations and callee effects remain outside its coverage.
Literal spelling does not infer object type; future matching names require scope
review. It is a narrow regression guard, not complete ownership or runtime proof.

Local evidence: `owner-write-gate-proposal-20261018` README, independent review,
integrated focused/API/static logs and entry-removal controls. Frozen candidate
SHA-256 values are `0656f37fe7141f14e1c8979900d679e7349deee6dfc14c1ed7d74b45f038db82`
(metrics), `294878e0d35435fa2e087429b627eb995728bdafca9929ad467cd91de876175f`
(gates), and `1b92af26a9809d59ea2a300df8c6332a61e77bbc110fa1653487157d6d8d0fc8`
(quality tests). Raw logs remain local.

Integrated owner-write guard review is accepted at all three frozen hashes:
68 focused methods passed independently; four actual-path and thirteen synthetic
mutations were rejected; twenty syntax/control groups and same-scope debt checks
passed; all seven production-table entry removals were rejected by independently
specified expectations. Fresh static JSON remained byte-identical to baseline
`d6ee71f1c5a2b41be06b05e458ebdf00a5de654af1bebfdb7f5212723b920fbe`.
Baseline/schema/CLI/application source are unchanged. Full aggregate pending.


### Completed thirty-first integrated result

`client-renewed20h-full31/results.json` was independently read and verified as
**completed: 394 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`),
run ID `477d799183534af39c6065dbd5076b2e`. Exact source: local
`7c3aaa06848bc440e7504fa92986b9ebdbc8b26b`, public
[2121eb75eb4cbaac1ba55aa4835e236999873f62](https://github.com/lulunomaro/polar-rm-client/commit/2121eb75eb4cbaac1ba55aa4835e236999873f62),
tree `2d404af8dced2ac8cd70729261f89d05141885ac` (parent-verified public mapping).
Provenance records `dirty: false` at start. Declared source stability passed with
**749 inputs** at both endpoints and SHA-256
`a9ac2e5fdf81074a06e5af60bd3c816b4faded6fffa809789f1d337c43b4e28d`.
Existing fingerprint scope, exclusions and endpoint limitations apply.

The quality-gate module passed **59 methods**. Aggregate check counts remain
unchanged because this stage extends an existing test module. This completed run
supplies integration evidence for the accepted literal owner-write guard; it
changes neither application source nor the reviewed debt baseline. The rule's
alias/dynamic-access blind spots and scoped-count allowance limitations remain.
Four incomplete prerequisites still prevent GO. Historical failures, interrupted
runs and external/native qualification limits are preserved; no global ownership
or architecture acceptance is inferred and no raw logs are uploaded.
