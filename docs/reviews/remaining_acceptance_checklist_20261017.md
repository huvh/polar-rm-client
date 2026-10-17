# Remaining architecture acceptance: evidence-based close-out

## Evidence update at 09:02 UTC (supersedes earlier open-cell descriptions)

- Historical aggregate `93aa839` finished **309 PASS, 12 SKIP, 3 INCOMPLETE,
  2 FAIL**. It is not a passing final-source certificate. The video retry failure
  has accepted test-order correction `909c579` (independent report `5564597`).
  The 30-second activation subprocess timeout remains unexplained: diagnostic
  `893faa3` and subsequent passing repetitions do not identify its cause.
- Constructor matrix `060f190`, independently accepted by root in `939f506`,
  discharges the named serial starter/reader, actual Paho network thread,
  MQTT cleanup thread and three decoder pipe-thread constructor cells.
  Five methods plus three rejecting mutation controls cover these cells;
  they do not certify every native constructor. Earlier instructions to add
  those exact constructor cases are complete, not a remaining task.
- Kill-cue audio retirement `cc33702` needed reviewer correction `f367729`.
  Red `bf85c5f` is retained. Independent 71-test selection plus an additional
  shutdown/decoder-error drain probe accepts active decode ownership and sealed
  delayed admission. Idle unregistered Python threads may finish asynchronously.
  Add this owner to the matrix: active/failed decode drain **T**, delayed entry
  after seal **T**, actual late executor admission **T**, physical audio **external**.
- Glass command buffer/per-draw geometry `b08427f` is independently accepted:
  86 tests and 48 complete baseline/current GL trace pairs. This discharges the
  selected core-rendering responsibility split while preserving live command
  payload reads, membership snapshot timing and failed cache publication.
- Independent detailed reports and raw evidence are in
  `audio_retirement_independent_20261017.md` and
  `glass_owner_independent_20261017.md` (review commit `b089ec4`).

Additional unresolved strict-budget evidence: root's running full profile at
`f34dbda` failed `test_dt7_worker_dispatch.py::DT7WorkerTests::test_no_device_real_time_100hz_tick_retry_budget`:
maximum 22.028550001778058 ms against the unchanged strict `< 20` ms assertion
(15 methods, one failure). Source log was independently read at
`/workspace/shared/clean-ten-hour-baseline/logs/tests__test_dt7_worker_dispatch.stderr.log`.
The reported isolated passing sample at `750c842` and diagnostics-only `b53d832`
do not establish its cause or resolve that failure. Do not label the still-running
aggregate passing or relax the measured region/threshold.

Remaining work is exact-source aggregate reconciliation, unresolved activation
and DT7 strict-budget failure diagnosis, and the bounded acquisition/state/config/input reviews
already assigned by the integrating owner. Keep native Windows/PowerShell,
GPU/device/audio/codec qualification separate. No new speculative rewrite or
schedule estimate follows from these tests. Earlier historical RED rows are
retained as evidence; their named accepted corrections determine current status.


## Current scope

This revision replaces the initial broad planning envelope with concrete
candidate-specific dispositions. Base inventory is `1b2f580`; reviewed follow-on
changes are named below. The integrating owner's final combined revision and
aggregate are still required. Latest integrated source is `8dbe624`, including
independently accepted movement candidate `ec80a3a` and its report `92d4af9`.
The earlier `93aa839` full profile is still running at this update; the final
`8dbe624` source profile will follow. No further production edits are planned.
A passing candidate does not retroactively change
base results or certify unrelated paths.

Three statuses must not be conflated:

- **Reproduced code defect:** executed failing contract, with a named red case.
- **Evidence gap:** an important contract has no established test in this review;
  this is not proof of incorrect production code.
- **External qualification:** requires native desktop, devices, firmware or
  packaging prerequisites; mocks and architecture refactoring cannot close it.

No remaining engineer-day total is asserted: earlier broad estimates mixed
already-covered cells, possible redesign and external work. The finite next
steps below are a more useful basis for scheduling. No new extraction is required
merely because a method is long or receives a host object; retain cohesive code
with a named responsibility and an explicit boundary limitation.

## Eight-gate update

| Gate | Concrete evidence now discharged | Remaining condition and category |
| --- | --- | --- |
| A. Evidence/oracle integrity | Referee metadata oracle fixed at `27eb687`; four red mutations at `95b5a24`, 22 focused methods and static gate pass, independently reproduced. Build interpreter `b0f5942` independently passes 29 methods + four prerequisite boundary probes. | Final integrated source digest, complete suite discovery/results, unchanged protected baselines and all known red cases green at that exact source. **Integration evidence pending**, not a new code defect. |
| B. Resource ownership/admission | Existing explicit adapter tests discharge many close/retry/stale-result cells; see the 13-owner matrix. POLAR admission correction `9c80e74` has separate transport/render review. Wallpaper `643accd` independently passes 40 methods + three extra probes; UDP `8a354c0` independently passes 19 methods. Thumbnail `a23999f` independently passes 32 methods plus a two-native-acquisition drain probe. | Constructor-vs-start coverage must be completed only for the identified matrix gaps, where still unestablished. **Bounded evidence gaps**. The named thumbnail executor submission/shutdown gap is discharged at `a23999f`. Wallpaper post-close open and UDP phantom-session counterexamples are fixed at named candidates; no remaining failure in those reproductions. |
| C. Window construction/activation | Existing startup ordering evidence retained; corrected finalization `fb271c8` independently passes 51 methods + 26 historical lookup/failure-prefix comparisons. | Earlier partial-constructor acquisitions are outside finalization scope. Enumerate acquisitions before the retained-abort boundary and fault each owned-service publication. **Evidence/ownership review gap**. Early audio QObject retention was subsequently reproduced; weak-callback correction `9dd5a80` is independently accepted: 47 audio tests and the same red/green native-QObject retention probe. This discharges the audio acquisition example, not the entire early-constructor ledger. |
| D. Input/authority | Existing emergency, focus-loss, hold-repeat and keyboard historical routing tests retained. Existing egress tests cover positive eligible output as well as individual false gates. | Retain explicit press/release/modal assertions in final-source regression. Shared differential collaborators do not prove their own runtime behavior. **Fixed candidate accepted:** drag ownership correction `8df72aa` passed independent review (22 methods and five pre-fix red failures reported by the input/review lanes). Movement candidate `ec80a3a` is independently accepted (30 tests + two successor/payload-failure probes), included in `8dbe624` but outside the earlier `93aa839` run. |
| E. State/projection ownership | Pure health/map/referee values and their historical/explicit assertions retained. Frozen referee globals now genuinely independent. | A field-group producer/overwrite ledger for RobotState and video/control/combat cross-owner writes is still absent from this close-out. **Architecture documentation/coverage gap**. Do not require wholesale model replacement without a demonstrated conflicting writer or change reason. |
| F. Configuration/live order | Existing transaction, quiescence, preference draft, descriptor and audio recovery evidence retained; ordinary-error rollback and explicit failed-restoration retry remain separate. | Recheck relevant contracts in final integration; retain live UI/runtime adapters with their documented ordered-effect responsibility. **No new defect selected**. Crash/concurrent-writer atomicity is explicitly outside the implemented guarantee. |
| G. Presentation responsibility | Existing map values, exact rendering/cleanup contracts retained. Framebuffer `99c96e9` has separate transport review; specialized renderer/startup texture ownership already has enumerated fault tests. | Keep source-specific map/ClickGUI/economy/video adapters when cohesive; only split if a concrete independent policy/state owner is identified. **Native rendering qualification blocked externally**; broad host independence is not asserted. |
| H. Whole-inventory disposition | All 24 families have an explicit disposition below; ownership matrix and exact independent reports identify acceptance boundaries. | Integrating owner must attach final source/digest and complete aggregate, then reconcile any new failure. **Final evidence pending**. Zero SCCs and passing counts are not universal semantic coverage. |

The window eager-lookup regression was a genuine extraction defect; its
correction restores historical prefixes rather than weakening tests. Wallpaper
and UDP admission were genuine ownership/status defects. Shared metadata in the
referee test was an oracle defect, not incorrect production metadata. All have
named fixed candidates; none is represented here as permanently open merely
because its historical red evidence remains in the repository.

## Disposition of the original 24 families

“Retain” accepts the stated responsibility for the current scope; it does not
certify every runtime path or waive the named tests/native qualification.
“Review gap” identifies bounded work still needed before claiming complete
architecture close-out, not a demand for an automatic rewrite.

| Family | Disposition and rationale | Remaining actionable condition |
| --- | --- | --- |
| 1. Entry/window | **Accepted fixes + review gap:** activation/finalization ports and early audio weak ownership have real responsibilities; window remains composition root. | Audio example discharged at `9dd5a80`; remaining partial-constructor acquisition ledger/fault prefixes and final multiwindow/lifecycle tests. |
| 2. Domain/catalog | **Review gap:** stable catalog/profile/codec values are separated; RobotState intentionally aggregates runtime views. | Field-group producer/overwrite ledger and tests for any conflicting authoritative writes found. |
| 3. Economy | **Retain with boundary:** interaction owner/hold threshold and shared geometry are meaningful; broad view adapter remains. | Preserve selection/query, price/order, hold and render/hit contracts; no cosmetic builder split. |
| 4. Input/overlays | **Drag correction accepted:** ordered routing is meaningful, priority cannot become unordered dispatch. | Final-source regression for accepted `8df72aa` and `ec80a3a`; native mouse delivery remains external. |
| 5. Configuration | **Retain with boundary:** participants/drafts own distinct recovery/state responsibilities; adapter sequences UI/runtime effects. | Final transaction/retry/no-rearm tests; do not promise crash or multiprocess durability. |
| 6. Backend orchestration | **Retain with boundary:** coordinator, teardown and policies separate owned lifetimes from projection; manager remains composition/arbitration adapter. | Exact-source lifecycle/egress tests and resource matrix gaps; no manager-size target. |
| 7. Control/qualification | **Retain with safety invariants:** UI authority, worker freshness and egress checks serve different roles. | Positive and negative egress tests; physical neutral, remote priority and explicit operator qualification remain external. |
| 8. Referee protocol | **Retain with boundary:** annual decoding/projection and metadata are separate; historical partial-publication semantics characterized. | Frozen independent metadata and protocol bytes at final source; reference/annual compatibility prerequisites remain external. |
| 9. Robot protocol/transport | **Fixed candidate accepted within scope:** spec remains authoritative; POLAR admission correction supplements existing retained-native tests. | Final-source regression; physical acknowledgment is not inferred from queue/close status. |
| 10. Device egress | **Retain with boundary:** shared thread ownership does not replace per-adapter native/protocol ownership. | Existing DT7/CC/angle adapter tests and final integration; device qualification separate. |
| 11. Official transports/decoders | **Review gap:** UDP constructor defect has accepted correction; nested process/pipe/socket ownership already extensively tested. | Establish remaining MQTT/decoder constructor cells rather than assuming start tests cover them. |
| 12. Audit/replay | **Retain:** bounded writer/accounting and replay isolation have specific responsibilities. | Final admission/loss/drain/intact tests; no claim that drained implies lossless. |
| 13. Vision/video UI | **Review gap:** camera/model workers retain native owners and reject stale results; UI coordinates control/combat. | Include cross-owner source/generation/authority in field ledger; native model/driver throughput external. |
| 14. Combat/audio | **Retain with accepted ownership fix:** confirmed-vs-inferred events, dedup and repeat-cue behavior are deliberate; weak signal listeners prevent unintended pool retention. | Final event/audio recovery tests; offscreen QObject lifetime passed, physical sound-device output remains external. |
| 15. Core rendering | **Retain with boundary:** resource/presenter/diagnostic owners meaningful; ordered source-specific passes remain. | Final failed-present/cache/hit-map and framebuffer tests; native context/pixels/cadence external. |
| 16. Specialized GL | **Retain:** named context handles and unit-specific cleanup are cohesive. | Enumerated partial-init/release/retry tests; actual driver state external. |
| 17. Map/status | **Retain with boundary:** pure geometry/radar/status observations extracted; painter/menu/cache adapter intentionally remains. | Preserve alliance/units/TTL/geometry and command gates; no line-count split. |
| 18. ClickGUI layout | **Retain with boundary:** layout, clipping and interaction registration are coupled by view purpose. | Preserve modal ownership, cache invalidation, language/scale and hit targets; host independence not claimed. |
| 19. Other HUD/presentation | **Retain:** style-specific artwork is cohesive even when procedurally large. | Existing view/geometry/source fixtures; native screenshot/performance evidence external. |
| 20. Startup media | **Fixed candidates accepted:** wallpaper admission retained through retirement; thumbnail active native work owned independently of executor join bookkeeping. | Final-source regression for `643accd` and `a23999f`; native decode external. |
| 21. Animation/frame planning | **Retain:** separate clocks/plans/controllers express timing responsibilities. | Preserve resume/no-backlog/pending tests; real presentation cadence external. |
| 22. Assets/locale/geometry | **Retain:** loaders/formatters/painter helpers are cohesive. | Locale/cache/shortcut contracts, installed fonts/assets and CJK bounds externally validated. |
| 23. Paths/preflight | **Retain:** source/portable roots and observational preflight are distinct. Explicit build interpreter accepted in source/Python scope. | Native Windows path-with-spaces/default/explicit interpreter and actual packaged launch. |
| 24. Historical/package facades | **Retain:** compatibility exports and historical source are intentional, counted and not complexity wins. | Keep API identity/frozen fixtures; update misleading migration comments only when relevant. |

## Finite next-stage list

1. **Seal the final combined regression:** exact revision/digest, discovery,
   API/static gates and complete profile; list FAIL, SKIP and INCOMPLETE separately.
   Stop and fix any new reproducible regression before declaring this checkpoint.
2. **Close named resource test gaps:** constructor rejection for serial starter/
   reader, MQTT and decoder boundaries where not yet established. UDP constructor
   and the named thumbnail submit/late-admission/cancellation cases now have
   accepted corrections and evidence; do not count them as remaining gaps.
   Read production cleanup before adding fixes. Finish when each matrix cell has
   either a precise passing test or a documented inapplicable ownership contract.
3. **Bound early-window construction:** enumerate only resources acquired before
   existing abort ownership; inject each publication failure and retain/release
   already-acquired owners. Finish at a complete finite acquisition list.
4. **Record authoritative field groups:** official/POLAR/simulation/frontend,
   plus video/control/combat generation and freshness; identify producer and
   overwrite order. Add tests/fixes only for uncovered meaningful conflicts.
5. **Complete external qualification separately:** Windows/Qt/GL/audio/video,
   portable packaging and firmware/device field procedure. Record exact platform,
   device/firmware, source, prerequisites and results. Do not transform missing
   equipment into a code-quality defect or a mocked pass.

The drag-release defect (red `61e1cf8`) is now addressed by independently
accepted `8df72aa`, including cross-button ownership. An existing drag fixture
was updated at `0cf5b4` to use the real owner with its 82 assertions unchanged;
the reported independent review passes 30 methods and rejects two deliberately
bad finalizers. These are source-scoped reports from their respective lanes,
not tests rerun or added into this audit's totals.

Early audio-pool QObject retention became a confirmed constructor-failure defect
after traceback/normal-destruction controls. Weak-callback correction `9dd5a80`
is included in `93aa839` and independently accepted by the transport reviewer:
47 audio-discovery tests pass; the same retained-object probe exits 1 at baseline
`53e527e` and 0 at corrected source. Parentless pool, weak global registry and
traceback/mock-history controls isolate the signal reference cycle. Evidence
commit `93db40a`, `../evidence/clean-code-20261017/audio-independent/README.md`,
records exact commands and limits. This accepts real offscreen Qt object lifetime,
not audible output or physical sound-device/codec teardown.
Movement `ec80a3a` is independently accepted in report `92d4af9`: 30 tests
and two payload-conversion/successor-failure probes preserve the six-pixel
threshold, live successor writes, consume-before-command and initiating-button
ownership. No original fixture or public baseline was rewritten.

The `93aa839` aggregate is still running, not a pass, and cannot certify the
later movement edit. Final integrated source `8dbe624` needs its own run. Earlier aggregate
`dcd523c` predates these corrections and cannot certify them.

All reproduced code/oracle defects named in this report now have accepted
corrections. Remaining necessary work is the final combined run and its actual
failures, the specifically unmapped constructor cells, the remaining early-window
acquisition ledger, the authoritative field-group ledger, and external native
qualification. These evidence gaps do not imply new production defects or
justify an automatic rewrite. This report does not declare the whole project clean.

## Evidence

- `resource_owner_evidence_matrix_20261017.md`
- `window_finalization_independent_20261017.md`
- `wallpaper_admission_independent_20261017.md`
- `udp_constructor_independent_20261017.md`
- `thumbnail_admission_independent_20261017.md`
- `module_drag_state_independent_review_20261017.md` (review commit `92d4af9`)
- `build_interpreter_independent_20261017.md`
- `../evidence/clean-code-20261017/oracle-audit/`

Earlier family-level inventory and third-stage acceptance remain historical
source-scoped evidence, not a replacement for the final integrating report.
