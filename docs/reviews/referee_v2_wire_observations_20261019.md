# V2 decoded-wire observation foundation — 2026-10-19

## Scope and source

This stage adds immutable receipt evidence for nine verified V2 message types/61 scalar fields. It does **not** register V2, enable actions, change RobotState projection, or qualify an official-client/hardware connection.

- Local source: `dabebe448b4eb942fa8221b15e34ff7f910df05b`.
- Public source: [df33b91491513902ff57eba38f39da3103687f33](https://github.com/lulunomaro/polar-rm-client/commit/df33b91491513902ff57eba38f39da3103687f33).
- Tree: `abb6e127f2b744c2736f23ce7f61ff1531293ce6`.
- Changed files: `rm_client/backend/mqtt_backend.py`, new `rm_client/backend/referee/rm2026_v2/observations.py`, and new `tests/test_referee_v2_observations.py`. No earlier test assertions were edited.

The local source/tree and clean worktree were independently read after commit; the parent verified the public mapping. The contract comes from the pinned [2026 protocol V2.0.0](https://bbs.robomaster.com/wiki/20204847/811363), using the existing verified field table rather than another schema copy. See the [codec foundation](referee_v2_codec_foundation_20261019.md) and [parity plan](official_client_parity_plan_20261019.md).

## Deliberate authority boundary

The implementation records successfully decoded **wire observations**, not proof of successful RobotState/UI publication. Future peer-fact decisions must use the stamped fields, with separate current safety/qualification checks; retained model defaults cannot fill gaps.

Each present scalar retains its own callback-entry `perf_counter` receipt. Omission does not refresh a sibling; explicit zero/false and raw unknown enums remain distinguishable. Frozen records/tuples prevent mutation through a held snapshot or decoded-queue dictionary. Configured ClientId is configuration context, not authenticated peer identity. Actual robot ID/type and round require present observations.

First scope binding retires unbound measurements while preserving already observed scope keys, allowing partial identity assembly. A changed known robot ID/type/round retires all previous evidence before the current record. A receipt high-watermark rejects older-completing records, including fields erased by retirement. This intentionally discards some older disjoint data; equal receipts use commit order, without an atomic peer-snapshot claim.

The callback adds only pure reduction under its existing decoded lock. It never acquires lifecycle there. Getter and retirement retain lifecycle→decoded ordering. A returned snapshot can become stale immediately after unlock; it is not an action-admission witness.

The selected topics are GameStatus, GlobalLogisticsStatus, RobotStaticStatus, RobotDynamicStatus, RobotRespawnStatus, PenaltyInfo, SentryStatusSync, AirSupportStatusSync and RobotPerformanceSelectionSync. SentryCtrlResult is excluded because retained individual fields cannot establish one reply pairing. Performance selection supplies raw sentry_control observations for later policy; neither its prose nor robot_type establishes target/role ownership. PenaltyInfo expiry cannot be treated as proof that a penalty cleared.

## Focused evidence and retained counterevidence

- Author repository-only selection: **122 methods PASS**. API freeze passes 1,114 established members, 540 signatures and 78 private seams. Static gates pass: 227 modules, 3,518 functions, zero initialization cycles. These metrics do not establish hardware behavior or global coupling reduction.
- Independent repository-normal selection: **122 methods PASS**, plus **seven separate controls PASS**, covering all61 scalars, partial-scope permutations, actual threaded late completion/epoch ABA, stop/getter lock ordering, and endpoint/disconnect/profile retirement. These selections overlap; their counts are not summed as unique tests.
- Five independent targeted mutations are assertion-rejected with zero errors. The author's separate mutation set includes errors and a surviving storage-clear-only omission: existing generation guards independently prevent public reuse. That survivor is retained, not called a successful sensitivity test.
- The first candidate converted ClientId for V1 callbacks too. An added exotic-object regression rejected that candidate; final code gates the conversion to V2. The accepted eight-topic revision is also retained; parent then approved the ninth topic's three existing scalar fields and one additional test.
- The review's initial scalar-count expectation was corrected from65 to58 for the eight-topic revision. Its first integrated122-method run passed the tests but failed a post-run assertion banning BackendManager imports. Existing endpoint/decoded-batch neighbors intentionally exercise that owner. Only this combined-suite import assertion was corrected; facade/spin/Qt/GL and acquisition guards remain. The seven pure controls continue to forbid manager imports.

Raw probes/logs remain local; this report publishes only the bounded findings.

## Aggregate status

**Full53 completed with a failure: 417 PASS / 12 SKIP / 4 INCOMPLETE / 1 FAIL, NO-GO.** Run `5d14352d66d846daadb3582f6ec40729` started clean at the exact source/tree above. Its780 declared inputs have identical start/end SHA-256 `02469e59b5f170b8929fc8198d8c4dd2fcf1429e0fb972df5e0feb0e262652d8`. The new observation module passed all18 methods (runner duration0.186s). These are selected offline checks, not hardware qualification; source stability covers declared inputs at the two endpoints, not external dependencies or transient restored edits.

The sole failure is `tests/test_device_manager_nonblocking.py::ManagerNonblockingTests.test_frame_does_not_wait_for_driver_held_intent_lock`, line51. Its1000 tick calls, including per-call status assertions while an inert driver thread holds the intent lock, measured `0.0912815240008058` seconds against the unchanged strict `<0.05`-second gate. The module ran seven methods with one failure; runner duration0.572s. The final busy-skip-count assertion follows the failed time assertion and was not reached in that case.

Direct Git-byte comparison against full52 proves the failing test, manager, POLAR bridge, control, model and serial-port modules are unchanged. Full52's same seven-method module passed. This establishes source continuity of those files, **not** the cause of the new timing failure or a reason to waive it. No rerun, timeout increase or gate relaxation was performed for this report. Diagnosis is separate and remains unresolved.

The preceding full52 result remains **417 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO**, qualified to its earlier source. Its passing DT7 sample does not explain or erase [full51's strict timing failure](referee_v2_action_rules_20261019.md). External-reference prerequisites, native hardware acceptance, final action admission, target scope, receipt freshness decisions and registration remain open; see the [acceptance checklist](remaining_acceptance_checklist_20261017.md).
