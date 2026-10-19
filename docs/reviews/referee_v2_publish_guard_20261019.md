# V2 command publication: full55 final-context qualification

2026-10-19. The unregistered V2 foundation now applies the existing Air request decision at its final MQTT enqueue boundary. The change is confined to MQTT, Safety and one new regression module. V2 profile registration, frontend enabling and Sentry business eligibility remain pending.

## Completed full55 qualification

- Local source: `c2d5d7003c576d6548f4cd3229632ebd4ed859a0`.
- Public source: `38e8e398eecd6fc3f562cc0c19aaa93b42c71dc5`.
- Shared tree: `d6e9610da00ee225beb8a09fbd0c78eff998d793`.
- **Full55:420 PASS /12 SKIP /4 INCOMPLETE /0 FAIL, overall NO-GO.** Run `dd29465e2db04e9f95c7ee55a141b128`, started2026-10-19 04:15:51 UTC, completed. All782 declared inputs had identical start/end SHA-256 `7a85f294c47bf8abd975ab2f9b2939a31dd01661ada3d79f73031b098587f560`.
- New guard module:26 methods PASS, harness0.209s (unittest0.057s). The existing Air decision25, wire-observation18, device-manager7 and DT7 dispatch15 methods pass. Later timing passes do not explain historical failures.

This is the single source-specific parent-managed aggregate for the guard. The [preceding full54 Air decision qualification](referee_v2_air_decision_20261019.md#published-source-and-current-qualification) remains a separate tree/result. Twelve skipped checks and four incomplete prerequisites keep this result NO-GO; offline counts do not replace native/external acceptance.

## Bounded implementation

Only AirSupportCommand and SentryCtrlCommand under the exact V2 protocol/codec binding enter the new path. The complete legacy publication body and legacy Safety admission method remain unchanged. Raw, named, binary and existing manager adapters converge on the same guarded publisher. Unsupported Sentry commands are denied by the existing request decision.

The publisher captures current profile, connection session, Safety owner/control generation and immutable wire snapshot before payload conversion. It freezes bytes once, validates those bytes and uses protobuf singular last-wins/default-zero command semantics. Economy intent is fixed for these two topics, so a caller cannot select the control capability instead. An initial ordinary Safety check runs outside the final locks.

At final enqueue, lifecycle→decoded locking protects the current session and wire context. The original profile and Safety owners, mock mode, session/control generations and exact current snapshot must still agree. Equal-value snapshot replacement is a changed context and rejects the held request. A direct protected final call without its required context is rejected.

The final section validates the actual bytes again, samples a fresh internal clock, invokes a side-effect-free Safety-owned check and repeats the same pure business decision. Current allowance, capability, phase, qualification expiry and rate limit are checked even without a generation change. Qualification cannot bypass MATCH or peer-business prerequisites. Caller-supplied time cannot retain stale authority or evidence. Successful real enqueue debits the existing rate limiter in the same critical section. Observers, events and external diagnostics remain outside these locks.

Governed V2 mock success also needs the current connected context and all admission checks. It is diagnostic only, with no enqueue, sent count or limiter debit. Legacy mock behavior is unchanged. Air's inherited numeric limiter is local Safety policy; the verified official Air topic is trigger-based without a numeric maximum. No vendor frequency is invented.

## Focused evidence

- New guard suite:26 methods PASS. Combined guard/Air/snapshot/MQTT lifecycle/receipt-time selection:96 PASS. Counts overlap.
- Ten selected missing-feature baseline methods produce17 assertion/subtest failures and zero errors using an explicitly installed inert V2 profile. This demonstrates an unimplemented foundation boundary, not an already-enabled production path.
- Twelve runtime-only omissions are assertion-rejected with zero errors.
- Independent review:102 focused methods plus two additional policy methods PASS. Repository-only final review:104 PASS, zero failures/errors; exact source hashes and module paths verified before/after execution. These are overlapping selections, not additive unique-test totals.
- Complete source AST restoration independently confirms both legacy owner files after removal of the reviewed additions and expansion of the extracted locked snapshot getter.
- Supplemental author-only Safety comparison:3,840 paired states PASS; all36 final positives also pass the corresponding unchanged initial economy check and MATCH requirement, with no Safety mutation. This is separate from the unittest counts.
- Repository API PASS:1,114 established members,540 signatures,78 private seams. Static PASS:227 production modules,3,524 functions,zero initialization cycles. Diff check passes.

The new tests use actual MQTT/Safety owners and extracted manager adapter ASTs with inert collaborators. Native/application imports and network/process acquisition are blocked. Positive Air0–3 paths, stage exit before UI drain, field/token expiry, rearm, owner/session replacement, callback ordering, payload mutation, malformed/overflow wire data, duplicate/default commands and final rate behavior are exercised.

## Retained failed evidence

The first new fixture run had two TypeErrors from indexing a bool-returning adapter result. The correction matches its existing return contract; production bytes did not change. An initial baseline expiry probe was rejected at the old control-intent gate before its intended barrier. Explicit economy intent now reaches that boundary and exposes stale publication. Original fixtures and logs remain saved; no assertion was weakened.

An independent policy-control draft referenced nonexistent codec rate metadata and raised four AttributeErrors. The corrected control reads the actual topic metadata and retains its assertions. These are documented harness failures, not erased or included as passing candidate evidence. Earlier full51 DT7 and full53 device-manager timing failures retain their separate historical status; this guard provides no causal closure.

## Concurrency and acceptance limits

The guarantee uses the existing ownership model: UI-owner Safety mutation, decoded-lock MQTT phase updates, lifecycle-lock retirement, and asynchronous device workers reporting faults for owner polling. Arbitrary unsynchronized Safety writes and fabricated private contexts are outside that contract.

The fresh clock sample and bounded pure checks precede the existing client.publish enqueue call inside the final section. A callback committed first invalidates held admission; a callback arriving during final admission waits until enqueue completes. This cannot recall an already-enqueued request, guarantee broker latency, authenticate a human, prove server permission or provide request-specific acknowledgement. Positive request wording remains 请求/待服务器确认.

V2 remains unregistered. Sentry eligibility, current frontend cues, actual broker/official-peer interoperability, native rendering and hardware acceptance are separate remaining gates in the [parity plan](official_client_parity_plan_20261019.md). The [historical failed full51](referee_v2_projection_20261019.md#completed-full51-qualification) and [failed full53](referee_v2_wire_observations_20261019.md#aggregate-status) are preserved. Offline focused checks and this completed aggregate do not discharge those requirements or qualify later source edits.
