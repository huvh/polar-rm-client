# Device-manager fixture isolation and full53 timing evidence — 2026-10-19

## Scope and source

This stage closes a serial-discovery isolation gap in one test fixture. It does not establish a cause or a timing fix for full53's failed device-manager budget assertion.

- Fixture-only local source: `248aa62b675b652da36557417e18fa0f586f25c3`.
- Fixture-only public source: [d1b1bb80472194ab804bc42d68b0e6c8b87b7e63](https://github.com/lulunomaro/polar-rm-client/commit/d1b1bb80472194ab804bc42d68b0e6c8b87b7e63).
- Fixture-only tree: `9fc444836ed107277c723386c48ed383cd29b365`.
- Sole changed file in that commit: `tests/test_device_manager_nonblocking.py`, SHA-256 `2b0fce063c5a5aefd1a61c9b7602b85e515f59fdaeb400c0d77674fbd0599966`.

The subsequent combined source also contains the separately scoped V2 aerial decision foundation. Full54 completed at local `419e91c5a177a3ee7771dba12c81932f68c9950f` / public [0751cd42ed6391f4698ae52944b6c1715e34ac45](https://github.com/lulunomaro/polar-rm-client/commit/0751cd42ed6391f4698ae52944b6c1715e34ac45), tree `65807770a69ecd16f747e05d12db9b0768566d9f`. Local commit/tree and fixture bytes were read directly; public mappings were verified by the publishing parent. The completed result below qualifies that combined source only.

## The demonstrated fixture gap

The existing fixture supplied an empty `port_snapshot`, which covers the asynchronous discovery route. Actual `build_default_registry` also calls `polar_port_choices()` twice with its default blocking behavior for ControllerAngles. That route uses `list_serial_ports` and can read cached physical choices or enumerate ports when the cache has expired.

A fail-closed external diagnostic stopped at the physical-scan entry before the timer began. This demonstrated an uncovered setup dependency, not that a physical scan happened in full53 or caused its timing failure.

The repair retains the empty `port_snapshot`, supplies an empty `list_serial_ports`, and guards `_scan_serial_ports` with an AssertionError during registry construction. The context restores all three helpers on normal return and ordinary or process-control exceptions. Existing ControllerAngles base choices remain `Stub, COM1, COM3, COM5`; the catalog already excludes Auto for these selectors.

All seven original test bodies, helpers and assertions are AST-identical. Removing only the two added context-manager entries restores the complete baseline file AST. The strict 50 ms loop gate and existing 20 ms assertions are unchanged. No production module, endpoint policy or selected setting value is changed by this fixture commit.

## Focused verification and counterevidence

- Five pure controls pass against the integrated repository fixture. They use the actual setup AST and registry/catalog owners with inert manager/control constructor doubles. Expired cache, warm cache, helper restoration, a direct scan bypass and exact source preservation are covered.
- Three supplementary real-owner setup controls pass against the repository test module. They exercise actual manager/control/registry construction, with Git metadata and background logging narrowly stubbed and acquisition boundaries guarded. They do not execute any timed test body.
- Independent external review separately reproduced the same five pure and three supplementary passing controls. These counts overlap and are not eight additional unique checks on top of integration.
- The baseline pure selection produces seven assertion/subtest failures with zero errors. Three omission mutations are assertion-rejected with zero errors, including omission of the local fail-closed scan guard. Structural checks contribute to those failure counts; they are not counts of distinct production bugs.

Earlier harness failures remain recorded: a control initially expected Auto despite the catalog exclusion; a baseline structural oracle initially assumed candidate-only contexts; the first supplementary harness blocked pre-existing constructor metadata/logging boundaries; and an integration wrapper rejected a changed selector before execution. Corrections affected external harness assumptions, not the candidate or existing timing assertions. Final guarded controls passed after those corrections. Raw local traces and harnesses are retained separately from this sanitized report.

## Full53 timing evidence remains unresolved

The [full53 checkpoint](referee_v2_wire_observations_20261019.md#aggregate-status) remains **417 PASS / 12 SKIP / 4 INCOMPLETE / 1 FAIL, NO-GO**, run `5d14352d66d846daadb3582f6ec40729`. Its 780 declared inputs have matching start/end SHA-256 `02469e59b5f170b8929fc8198d8c4dd2fcf1429e0fb972df5e0feb0e262652d8`.

`test_frame_does_not_wait_for_driver_held_intent_lock` measured **0.0912815240008058 seconds** against strict **<0.05 seconds**. This is the total for 1,000 tick calls and 1,000 status assertions while another inert thread holds the intent lock, not one frame's lock wait. Those status assertions passed; the final busy-count assertion follows the failed timing check and was not reached in full53.

The test and eight examined device-path files were byte-identical between full52 and full53. Full52's same seven-method module passed, but its successful loop duration was not printed. The V2 snapshot callbacks/getter do not execute on this tested busy path. Source continuity alone does not establish an environmental cause or exclude every indirect runtime interaction.

The real path performs input-clear and independent egress bookkeeping before `acquire(blocking=False)`, then returns `writer busy` if the intent lock is held. Processing independent egress changes before that attempt is intentional; moving them behind the lock would change behavior.

One authorized, guarded diagnostic sample retained the original 1,000 iterations and strict assertion. It passed at **0.019222404007450677 seconds wall** and **0.019264241000000015 seconds main-thread CPU**; the CPU interval is slightly wider. It recorded 1,000 busy skips, no GC collection or context switch, and two minor faults. No repeat sampling followed that passing sample. A separate deterministic actual-method barrier proved return before lock release; a blocking-acquisition mutation was rejected before any blocking operation.

The initial diagnostic attempt stopped at the scan guard before entering the timed loop. An inert discovery result was then supplied for the single completed sample. Neither that correction, the passing sample nor the barrier proof explains or replaces full53's 91.28 ms result.

## Completed full54 qualification

The sole combined full54 aggregate completed **419 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO**, run `fbcb17f976a5453e90277a4943ffceb1`, starting clean at the source identified above. Its 781 declared inputs have identical start/end SHA-256 `fd96cd589c6a56a78a065c22f9b7c44d35daac0c8840eb1c973364fa73e653bf`. This is an endpoint comparison of declared inputs, not installed dependencies, external fixtures or transient edits restored between captures.

The device-manager module passes all seven existing methods; its runner duration is 0.392 seconds and its own test summary is 0.160 seconds. Neither duration is the successful 1,000-call loop measurement, which the test does not print. The combined aerial decision regression passes 25 methods, the wire-observation regression passes 18, and the existing DT7 dispatch module passes 15. Counts of aggregate entries and test methods are different units and are not combined.

The fixture-only controls establish setup isolation. Full54 supplies a later passing sample of the original timing assertions; it does not establish a cause or resolution of full53's failure. All four external/integration prerequisites remain incomplete, so the runner's overall result remains NO-GO despite zero failed entries.

External/native acceptance and final V2 action admission remain open. See the [acceptance checklist](remaining_acceptance_checklist_20261017.md) and [official-client parity plan](official_client_parity_plan_20261019.md). This passing timing sample does not identify the causes of historical full51/full53 failures or turn source-only work into hardware qualification. No source/test edit or test rerun was made while preparing this report.
