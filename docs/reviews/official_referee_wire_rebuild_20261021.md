# Official referee alignment, rebuilt after workspace rollback

This report describes the reconstructed tree, not the lost 2700ada commit. Old
aggregate results do not verify this tree. No vendor program or real match/device
command is run. The integration owner records fresh commits and durable bundles.

## Sources

- Official software: https://bbs.robomaster.com/wiki/20204847/804784
- Official protocol: https://bbs.robomaster.com/wiki/20204847/811363
- Official RMUC rules: https://bbs.robomaster.com/wiki/20204847/809871
- Student 12.0.0.213 is V2.0.0 (minimum engine123); engine137 is not evidence for V1.
- V2 PDF SHA256: `8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b`.
- Official213 CustomClientProReflection descriptor: 8205 bytes, SHA256
  `db398c02c9c6636852ab02693df3c51a77b9b219f836e9b1b3deb88b34091b50`.
  Recovered anew from the official binary, not inferred from the implementation.
- RMUC V2.2.0 rules SHA256:
  `88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5`.

## Wire schema and state

Fresh comparison of all 37 local field tables against the recovered descriptor:
zero field-number/type/cardinality differences. Official MapClickInfoNotify is
the descriptor shared by MapClickInfo and MapClickCmd topics. Native names
RobotPosition.robotid and TechCoreMotionStateSync.status map to PDF/API robot_id
and basic_state, without changing wire numbers. All 11 uplink and 25 downlink
schemas have exact shapes; this does not mean every action or HUD is complete.

RadarInfoToClient field1 is repeated RadarSingleRobotInfo, named robot_info in the
descriptor and aliased to local robots. Nested uint32 fields are x, y, highlight.
Synthetic descriptor-generated golden (not a network capture):
`0a07086410c80118020a06080010001800`; the second entry has explicit zero presence.
Coordinates are centimetres; highlight denotes positioning-offline display, not
a damage buff. Invalid nested wire is rejected, not treated as empty success.

Repeated int32 packed and unpacked forms now share sign extension. Explicit zero
static capabilities are observed values, distinct from omission. max_chassis_energy
and optional team damage totals project into state; round changes retire damage.
Rune average_rings remains a ring score, not a percentage, and does not overwrite
mock progress. A phase-only change retires the previous average. Dynamic fire rate,
experience and countdown remain raw dictionaries; path plans remain decoded raw
because documented relative-point formulas conflict. No invented map conversion.

## Uplink behavior and limits

- KMC and CustomControl: signed axes/defined key bits/strict bools, <=30-byte block.
- Assembly: requester Engineer2/102; operation0/1/2, difficulty1..4.
- Hero deploy: requester1/101; mode0/1, separate Hero capability.
- Rune: requester Infantry3/4/5 (+100); only activate1.
- Dart: requester Aerial6/106 controls own-team Dart, targets1..5. open=false means
  no opening request, NOT closing the gate. No additional launch permission.
- Performance: Hero choices3/4 and Infantry choices1/2, zero means no action.
  Aerial mode-only0/1 controls own-team Sentry only in public PREPARE1, with explicit
  one-time supervised authorization. It is not a Sentry7/107 actor action.
- Map ordinary categories1..3 retained. Custom category4 is blocked: official213
  dispatch passes MapClickCmd bytes unchanged to SendMapClickInfoNotify, whose
  custom branch tests5, conflicting with PDF4. Do not silently rewrite to5.
- Common/Sentry/paid-Map require version-specific immutable economic confirmation;
  Sentry requester is Aerial, target own-team Sentry. Paid target resurrection6
  remains unavailable because the aerial feed provides no target quote/eligibility.
  Request enqueued is not server acceptance or a payment ACK; the official Sentry
  result publisher appears stubbed in this client version.

Real publication must retain current SUBACK, lifecycle and authority epochs,
per-field freshness, source identity, selected profile, stage and Safety gates.
Economic rules apply only to explicit RMUC7v7 owners/session, not generic V2 or
RMUL3v3. Final enqueue rechecks the exact confirmed snapshot object, not equality.
No permission is granted merely by decoding or matching a schema.

## Fresh verification, first reconstruction stage

- 29 codec/projection tests PASS.
- 61 domain/existing projection tests PASS.
- Independent descriptor shape comparison: 37 tables, zero mismatches.
- `git diff --check` PASS.

Transport integration and full-tree aggregate must be rerun on the final rebuilt
commit. Physical device, engine interoperability and hardware qualification are
not established by these offline tests.

## Fresh transport and regression verification (04:14 UTC)

The reconstructed transport now enables all11 structural topics with per-action
policy. The unrecoverable historical commits/tests are not used as pass evidence.

- All referee-named unittest modules: 309 methods PASS.
- All MQTT-named unittest modules: 92 methods PASS.
- New immutable economic admission: 10 methods PASS, including both alliances,
  all6 Common requests, reviewed10 Sentry requests, no target quote for Sentry6,
  all bytes entrypoints, exact confirmed snapshot identity, same-value fresh
  receipt rejection, actual RMUC owner/session scope, final race checks, bounded
  paid-route parsing, and paidMap versus ordinary teammate recipients.
- New ordinary uplink final-admission: 8 methods PASS; pure domains: 8 PASS.
- Independent audit reran those26 methods: PASS on stage6735909.
- backend_protocol_test: 199 checks PASS; hud_batch10_settings_test: PASS.
- External inert Air Qt: three fresh processes, each18 PASS, each
  GUARD_CALL_COUNT0. A strong reference retains seen modal wrappers to prevent
  Python object-ID reuse; the original3-second watchdog is unchanged.
- Old characterization fixtures remain unchanged. Only explicitly documented
  presence/unit/API deltas are applied in tests; no baseline re-recording.

SUBACK is required both at final enqueue and before publishing any received
record to authoritative queues/snapshots. Thus an early stage cannot become
permission after ACK through delayed state consumption. Fixed neutral KMC keeps
its dedicated bypass. Ordinary mock demonstrations do not become real authority.

Full aggregate and physical interoperability remain separate pending gates.
