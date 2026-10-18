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
