# Unregistered V2 settlement and Sentry projection, 2026-10-19

## Status and scope

The bounded projection stage is integrated and independently accepted. Projection publication is complete. The combined full51 aggregate completed with415 PASS / 12 SKIP / 4 INCOMPLETE / 1 FAIL; passed=false and release remains NO-GO. The previous full50 result qualifies the codec foundation source, not this later projection. V2 remains unregistered; no live profile selection, command publication or native/firmware interoperability is enabled or claimed.

This stage adds canonical GameStatus settlement observations and the present-only Sentry strengthened-status key. It does not complete all P0.2 prerequisites: aerial targeting/shooter observations, current-session freshness, UI consumption and later action admission remain pending.

## Specification and explicit local policy

The pinned official 2026 V2.0.0 protocol, section 2.2.3 printed pages 50–52, defines GameStatus field 9 game_result as 0 draw / 1 red victory / 2 blue victory and field 10 end_reason with values 1–9. These values are meaningful only at stage 5 settlement; the sender transmits 255 otherwise. Section 2.2.30 page 70 defines SentryStatusSync field 3 is_powered as strengthened/boosted status (是否强化). It is not an electrical-power flag. The saved official PDF SHA-256 is `8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b`; [official protocol landing page](https://bbs.robomaster.com/wiki/20204847/811363).

The specification does not define receiver omission retention, round-reset lifetime, an acknowledgement or an atomic state snapshot. The following receiver policy is local stale-observation prevention:

- game_result, end_reason and settlement_round default to None. Omitted decoder defaults do not become observed draw/false/255.
- A present stage 5 admits outcomes against the current stored model round. Within that context, omitted outcomes preserve prior accepted observations. Explicit 0 and 255 retain their distinct raw meanings; undocumented enum values remain uninterpreted.
- An explicit round change or nonsettlement stage retires all three fields. A round-only change cannot borrow retained old stage 5; later result-only data stays inapplicable until fresh stage 5. A single record containing new round, stage 5 and an outcome is admitted.
- settlement_round is a stored-round witness. A first stage 5 without a round field can bind default 1 or a retained pre-reset round. It does not confirm newly observed official round identity. Fresh peer-round/stage admission must be assessed before profile enablement.
- The existing sentry_status dictionary stores is_powered only when present. Omission preserves an existing observation; explicit False updates it. Absence remains unknown.

## Ownership and compatibility

The isolated Rm2026V2StateAdapter selects the independent V2 presence table and overrides a private settlement hook. The existing common adapter remains the sole shared projection implementation for stage, scores, identity, clocks and Sentry dictionary updates. The V1 public presence-helper signature and tables are unchanged; no codec tables are mutated.

The hook runs after existing round/score conversions and stage parsing, before safety and field-log callbacks. This prevents a post-callback write from resurrecting state retired by a reentrant callback. V1 uses a no-op hook, retains its one-read round trace and preserves existing behavior/exception prefixes.

Required round/stage retirement occurs before applicability checks. All present applicable outcomes convert into local values before publishing the new witness or either outcome. Failed direct mappings cannot seed later stage-only results. Prior accepted same-context values remain, while required new-round retirement remains effective. Common round/score writes can already have occurred: this is not an atomic-record or rollback guarantee, and no exception catch is added.

RobotState.clear_match_settlement owns the three-field reset. BackendManager._reset_state_for_scenario and PersistenceMixin.seed_match_state call it alongside their existing stage-reset boundaries. Scenario/profile reset already clears sentry_status. Existing retained round/scores/clocks, selected settings, counters and the opened Student settlement snapshot keep their prior policies. Endpoint/client-ID changes do not newly clear accepted state in this patch.

The three fields use init=False: the exact RobotState constructor signature is retained, while dataclass fields(), asdict() and equality state deliberately expand. The declared field count becomes 245. The earlier 242-field authority inventory remains historical; the [new authority addendum](robot_state_authority_audit_20261017.md#2026-10-19-addendum-unregistered-v2-settlement-observations) documents these additions without claiming a regenerated whole-source writer inventory.

## Regression and review evidence

- Foundation-only baseline: three feature-gap methods produce five assertion/subtest failures and zero errors. The candidate passes all three. This demonstrates missing unregistered V2 projection, not an error in deliberately selected V1.
- Final new regression: 32 pure methods. The repository-only focused selection passes 57, including existing presence, state and domain characterization.
- Independent integrated review: the same 57, nine additional controls and one unchanged failed-record conversion probe pass. Counts overlap and are not additive unique coverage.
- Fourteen author runtime mutants and five independent mutants are assertion-rejected with zero errors in their specified selections. The original twelve author controls use the original 27-method domain; two conversion-order controls use the five added methods.
- The guarded API checker passes with 1,114 established members, 540 Python call signatures and78 private caller seams. Static quality gates pass with 225 modules / 3,507 functions / zero initialization cycles before the separate price foundation was added. No gate baseline or budget changed.

Pure tests use actual V2 wire decoding and adapter/model code, plus actual reset methods extracted by AST with inert collaborators. They reject application/native/transport imports and network operations. The separate API check uses offscreen Qt, fresh storage, inert audio and closed serial/network boundaries; its retained warning is “QOpenGLWidget is not supported on this platform.” It does not qualify native rendering, audio or any excluded algorithm.

## Retained failures and changed behavior

The first broader external attempt stopped during harmless unittest.mock→asyncio→socket import under an overly broad import guard; no tests ran. The corrected operation guard permits the standard module while rejecting network operations. The unchanged exact-class hash then correctly rejected the added private seams: 52 methods, one assertion failure, zero errors. The separate precise hash approval extension retains every historical hash, behavioral assertion and fixture byte.

Independent review found that the first candidate could publish a valid result before an invalid direct-mapping reason failed. A later stage 5-only record could retain that failed result. The first candidate and its 52 passing methods remain preserved as counterevidence. The unchanged reviewer probe reproduces one failure there; the five final added methods produce seven assertion/subtest failures against that old hook, with zero errors. The revised hook passes them while preserving all original 27 test/helper ASTs.

Initial revised broad mutation runs caused malformed-value errors under deliberately broken applicability/reset controls, alongside assertion failures. Those logs remain preserved. Final targeted mutant selections make the assertion domains explicit rather than claiming those initial runs had zero errors.

## Frozen implementation

Eight proposed files were integrated exactly: model.py, manager.py, the common projection_policy.py and state_adapter.py, persistence_mixin.py, the new V2 state_adapter.py, new test_referee_v2_projection.py, and the precise test_referee_domain_characterization.py hash extension.

- V2 adapter SHA-256: `30260817f0876629ec7b116289845a382ca526835a4b0bdd075e34f1e4708d86`.
- New regression SHA-256: `b6483d66a83d551d206ea8b657787baede6a2a882f76ec10c680e7420173f6fb`.
- Existing characterization extension SHA-256: `0e9858663f326c4432a70f726d214126927ddc8ed4184418ada0f75db30ab3d2`.

Whole-file AST checks restore each existing production file by removing only the enumerated additions. The exact prior constructor and all original new-regression methods remain verified. The pinned domain fixture and existing behavioral assertions are unchanged. No profile/default, command encoder, foundation codec/contract, API baseline or static budget was changed.

## Completed full51 qualification

Projection-only source:
- Local `1a46e2aec8dcb71d15f5cc6490a30bbec0d06a09`.
- Parent-verified public `2535d8bf115e3d1ec6fa104f742c03f39c03f5d3`.
- Shared tree `de20f447fd7610974f63b2a80221af350414605c`.

Full51 completed on the combined projection and separate pure price-foundation source:
- Local `9ee192547a49747cc22232ff716b5889917daa0d`.
- Parent-verified public `eb9c052f4859a68259558a1bcf67f2997cc321e4`.
- Shared tree `1efcd44a59a2f70a5722ba25622d5ad82ae76625`.

The separate price stage adds only rm2026_v2/economy_rules.py and test_referee_v2_action_rules.py; it does not register a profile or publish commands. Its focused evidence is recorded in the [separate price-rule report](referee_v2_action_rules_20261019.md). The terminal results.json reports:
- Run `bd73bca4db9e430f958ce2c682ff185d`, started `2026-10-19T02:41:36Z`.
- `415 PASS / 12 SKIP / 4 INCOMPLETE / 1 FAIL`; `run_state=completed`, `passed=false`, **NO-GO**.
- All777 declared source inputs have identical start/end SHA-256 `e025d7f0ab8591751d9cc6d7b55a25650e3cee094045baad97fae64d36ce8c1d`.
- The new projection module passes 32 methods in 0.203s; the separate price-rule module passes 12 in 0.153s; the existing V2 codec module passes 24 in 0.152s.

The existing test_dt7_worker_dispatch module fails its unchanged test_no_device_real_time_100hz_tick_retry_budget assertion: maximum caller wall time 20.113138998567592ms is not less than 20ms, at tick 138/250. The diagnostic reports caller thread CPU 20.339525ms, four scans and three retries, and explicitly says the CPU interval includes wall-clock bookkeeping and cause is not inferred. The module runs 15 methods with one failure. The threshold was not weakened; a small excess still fails. Investigation is separate, and this observation does not establish that the V2 projection or price stage caused it.

Full50 passed the same 15-method DT7 module with a sample maximum 5.8432ms and median 0.0779ms over 250 ticks / 2.500s. The dispatch test, DT7 worker/link, safety and serial-port source bytes match between the full50/full51 tested commits. Unchanged source does not establish an environmental cause or excuse the failure. No causal fix, successful retry or threshold relaxation is claimed.

The four INCOMPLETE entries remain the absent team CRC reference, missing DT7 vendor firmware/decompiled reference, missing firmware application C source and the deliberately excluded legacy installation patch. The twelve SKIP entries and unselected native/external checks are not passes. These results do not qualify physical control, native rendering, official-client interoperability or a releasable V2 profile.
