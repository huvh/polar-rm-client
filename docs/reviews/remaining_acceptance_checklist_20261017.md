# Remaining architecture acceptance: bounded close-out plan

## Scope and meaning of completion

Reviewed source: `1b2f580` (production unchanged by this audit). Read together
with `whole_client_debt_inventory_20261016.md` and
`final_third_architecture_audit_20261016.md`. This is a proposed finite acceptance
contract, not a report that all gates pass, and not an instruction to rewrite
all large methods. Later lane commits need their own review before changing
these dispositions.

“Architecture close-out” means the eight gates below have source-bound evidence,
all high-priority counterexamples are resolved, and each of the existing 24
inventory families has an explicit accepted / retained-with-rationale / blocked
disposition. Cohesive drawing code and compatibility facades may be retained.
There is no percentage score, line-count target, or requirement to eliminate
every mutable field. A retained boundary must name its owner, callers, invariants
and remaining risks; moving code into `helper(window)` alone earns no acceptance.

## Prioritized finite gates

Effort is focused engineer-days, including characterization, implementation and
local review, for someone familiar with this tree. Ranges assume no new product
requirements, no redesign of visual style/protocol, and functioning offline
verification dependencies. They are planning estimates, not measured remaining
work or delivery dates. Discovering a new safety defect requires re-estimation.

| Priority / gate | Finite deliverable and pass criterion | Current open boundary | Effort |
| --- | --- | --- | --- |
| P0 A. Evidence and oracle integrity | One clean-checkout, fixed-production-digest integrated report; discovered executable suites equal the report manifest; every FAIL fixed, every SKIP/INCOMPLETE names its prerequisite. Unchanged API/budget/fixture hashes unless a separately reviewed defect requires change. Every new oracle has a deliberately bad candidate that it rejects; candidate constants cannot supply frozen expected semantics. | Focused reviews cannot be added into one aggregate. This audit repairs one demonstrated shared-global oracle weakness; it does not certify all tests. | 1–2 days |
| P0 B. Resource ownership and admission | Enumerate each actual native owner across serial/DT7/CC/angle, MQTT/video/decoder, logger, startup media and GL. For each, record one terminal-release owner and tests for constructor rejection, start rejection, admitted late error, retained close failure, retry, stale completion and replacement veto. Each state either releases or explicitly retains the owner; no phantom reservation or second owner. Shared helper tests plus per-adapter integration, not helper tests alone. | Shared thread ownership and several admission fixes are accepted; native-owner coverage remains adapter-specific, not universal. | 3–6 days |
| P0 C. Window construction/activation | Publish a finite service ownership ledger covering construction, activation, partial construction abort and close. Inject failure at each owned-service acquisition/publication boundary; every acquired owner is released or retained for retry. Test two real windows on one QApplication, closing each independently, delayed completion after close, and lookup/effect ordering against frozen behavior except explicitly approved corrections. | Named startup ports do not themselves own earlier service construction, timers or retained abort. | 2–4 days |
| P0 D. Input and authority | One documented ordered modal-consumer decision and explicit press/release ownership; independent assertions for emergency-first, pending lifecycle, overlapping modal pairs, repeat press/release, dismissed owner, focus loss and no authority leakage. Preserve positive eligible command paths as well as individually false safety gates. Each control egress rechecks its current authority/freshness. | Differential keyboard traces cover entry points; shared harness collaborators and real UI/control adapters still need their own tests. | 2–4 days |
| P1 E. State/projection ownership | Enumerate authoritative official, POLAR, simulation and frontend-owned field groups with producer, projection order and overwrite rule. For selected cross-owner writes, introduce narrow observation/value boundaries rather than duplicate mutable truth; test zero/death vs missing, stale/source generation, overlay precedence and malformed partial-publication behavior. Audit all producers of the selected groups, not merely the extracted function. | RobotState and video/control/combat coordination remain broad. A full RobotState replacement is not required if ownership is explicit and enforced at those writes. | 3–6 days |
| P1 F. Configuration/live effect order | One finite transaction participant matrix: registry/options/binds, profile identity, files/cache/audio, UI projection and runtime scenario. For each participant test mutation rejection, restoration failure/retry and superseded generation; no re-arm, stale completion or premature draft mutation. Document single-writer ordinary-exception recovery separately from crash/concurrent-writer guarantees. | Existing transaction, quiescence and draft owners are substantive; live adapters still span these effects. | 2–4 days |
| P1 G. Presentation responsibility | Select the currently coupled economy, map, ClickGUI and video/combat paths; record immutable observations or explicit read ports, ordered effects and sole cache/hit-map commit point. Test exact pass order, False/exception failure, independent cleanup, retry/invalidation and no state publication before successful presentation. Retain cohesive procedural artwork with rationale. | Earlier map values and renderer lifetime fixes do not certify all host-dependent paint/interaction paths. | 3–6 days |
| P1 H. Whole-inventory disposition | Update all 24 existing family rows against final source: actual responsibility, accepted evidence, retained coupling and qualification blockers. Run exact-source API/static/import/discovery checks and the integrated profile after final production edit. An independent reviewer checks changed ownership and all altered oracles; every P0 counterexample is closed or the close-out is blocked. | No new global “pure” claim from the five protected roots or zero SCCs. No coverage percentage from suite counts. | 2–3 days |

The arithmetic envelope is **18–35 engineer-days**, before newly discovered
scope. Some evidence already exists and may discharge individual cells after
checking source applicability; therefore this is not 18–35 days of mandatory
new coding. Parallel lanes can reduce calendar time, but integration and
independent review are serial dependencies. Conversely, promising that the
remaining architecture is “one more extraction” is not supported by the scope.

For an immediate bounded checkpoint, complete A and the specific failing
counterexamples found by B–D, then publish H with unresolved E–G explicitly
retained. That is a truthful incremental checkpoint, not whole-project closure.

## Separate native and release qualification

The following are separate deliverables. They neither disappear when the
architecture gates pass nor automatically imply code debt when unavailable:

- Native Windows/desktop Qt/OpenGL: actual framebuffer capture through the
  repository's supported path; driver/context-loss, multiwindow behavior,
  clipping/fonts/scale, real presentation cadence and performance under load.
  Offscreen pixels or passing mocks cannot substitute for native evidence.
- Device and firmware: compiled target firmware/reference compatibility, real
  serial reconnect/blocked I/O, physical remote priority, explicit motion
  authorization and observed zero/release behavior. Queued neutral is not
  firmware acknowledgment. Human hardware access and safe procedure required.
- Video/audio: real camera/stream/ffmpeg and sound-device output, device removal,
  restart and source freshness. Encoded JPEG unit tests are not field throughput.
- Packaging/deployment: installed portable/source layout, bundled assets/fonts,
  permissions, clean machine launch and dependency/protocol prerequisites.

Do not combine these into a speculative single completion date. With equipment,
firmware and operator time already available, planning 2–5 engineer-days for a
first native/packaging test pass and 2–5 for a first hardware session is a rough
scheduling allowance only; failures and external waiting can dominate. Each
qualification must list platform/device/firmware versions, source digest,
procedure, result and evidence. Existing SKIP/INCOMPLETE remain open until their
specific prerequisites are met.

## Independent oracle audit performed in this lane

Reviewed the latest test diffs from `fa2c2b8` through `1b2f580`, and inspected
keyboard differential, POLAR health differential and referee frontend projection
contracts. This was a targeted review, not all-test semantic coverage. The diff
scan found no removed assertion/skip/timeout/join lines in non-fixture tests in
that range; that narrow fact is not proof that no harness weakened an oracle.
The keyboard repeat-release normalization is an explicit previously documented
bug correction, not a silent relaxation. Its shared collaborators mean its
claim remains entry-point routing equivalence. POLAR health's frozen namespace
uses independent inert values for its semantic globals.

A concrete weakness exists in the referee frontend differential: the historical
function bytes are hash-checked, but its namespace previously took role order,
maximum health and robot/buff names from the current production adapter. Thus
changing a candidate metadata value changed both candidate and expected output.
This is a test-oracle gap, not evidence that the current production values are
wrong. Existing literal assertions catch some role-order changes, but do not
make every shared semantic global independent.

The added mutation control substitutes all four semantic globals in turn. It
requires frozen output to remain identical, candidate output to differ, and the
ordinary differential assertion to reject the candidate. Before the repair it
fails all four subcases. The repair supplies historical literal globals, checked
against `1b2f580`, without editing the frozen function, production code, timeout,
join, API manifest or static budget. After repair, the 12 frontend-contract
methods and 10 projection-policy methods pass (22 total). This is focused
acceptance only; no full profile or native test was run by this lane.

Evidence: `../evidence/clean-code-20261017/oracle-audit/`.
