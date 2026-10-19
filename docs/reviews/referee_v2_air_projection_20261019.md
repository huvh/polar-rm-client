# V2 aerial observation projection

2026-10-19. The bounded source stage and integrated focused review are accepted. Full52 completed with **417 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO**. V2 remains unregistered.

## Scope and official meaning

The [official V2.0.0 protocol](https://bbs.robomaster.com/wiki/20204847/811363), §2.2.36, printed pp.73–74, defines AirSupportStatusSync field4 `is_being_targeted` as uint32 illumination status and field5 `shooter_status` as uint32 shooting status. Field4 is0 for not illuminated and1 for illuminated. Field5 is0 for radar-locked with release unavailable,1 for normal, and2 for radar-locked with paid release possible. The pinned protocol PDF SHA256 is `8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b`.

The existing decoder already retained both fields, but the canonical state adapter dropped them. Four production files now add23 lines: two optional raw observations on RobotState, an owner method clearing exactly that pair, one reset call at the existing scenario/profile boundary, a no-op common-adapter hook and its V2 override. No profile is enabled.

- `air_support_is_being_targeted` and `air_support_shooter_status` default toNone, meaning unobserved.
- Omitted fields retain prior observations; explicit0 updates; documented and unknown uint32 values stay raw.
- Both present values are converted before either new field is published. A conversion failure preserves both previous new observations and propagates its original exception. Existing common-field partial updates are unchanged; no whole-record rollback is claimed.
- Direct compatibility mappings retain the existing int-conversion style, including numeric strings. No stricter admission policy is inferred from this projection step.
- Scenario/profile reset retires the two observations. Normal stage and match-mode seed behavior stay unchanged. The legacy aerial scalars are not silently assigned a new reset policy.
- V1 and Student retain their existing dropped-field behavior. Input mappings are not mutated.

The two fields use init=False, preserving the constructor signature and defaults. Dataclass fields, asdict and equality deliberately extend from245 to247 declared fields. This is a declared inventory update, not a new full writer census.

## Verification

- The original three feature methods reproduce four assertion/subtest failures and zero errors on the saved baseline; the candidate passes all three.
- New regression:21 methods PASS. Integrated focused selection:78 methods PASS, including the previous V2 projection and unchanged projection/state/domain neighbors.
- Author controls: nine runtime-only regressions rejected by assertions, zero errors. These cover dropped fields, boolean collapse, ignored presence, missing owned reset or actual manager reset call, early publication and an invented economy revision.
- Independent review:78 focused methods, seven added controls and the original three PASS. Additional controls compare256 legacy V1/Student prefixes and24 duplicate-wire orders, exact conversion/exception behavior, presence filtering, complete actual reset deltas and no synthetic acknowledgement. Six independent targeted mutants are rejected with zero errors.
- Integrated independent review verifies all six source/test hashes, normal repository-only78 and seven additional controls. Counts overlap; they are not additive unique coverage.
- Whole-file AST restoration proves the four production changes are confined to this scope. The existing exact-class characterization adds six lines preserving the prior accepted hash and all assertions; removing those lines restores the old test byte-for-byte.
- Guarded API PASS:1,114 established members,540 Python call signatures,78 private caller seams. Static PASS:226 Python modules,3,515 functions,zero initialization cycles. No quality baseline or threshold changed.

Pure selections block native/application/transport imports and socket operations; actual reset and match-mode methods run by AST with inert collaborators. The separate API gate uses fresh storage, offscreen Qt, inert audio and closed serial/network boundaries. Its retained QOpenGLWidget platform warning does not qualify native rendering. No device, broker, official-software or physical action acceptance is claimed.

The independent reviewer's first reset-control harness incorrectly assumed the whole manager reset was idempotent despite an existing deploy revision increment. That harness and log remain retained. The corrected control compares each reset against the baseline; candidate code and old assertions were unchanged.

## Admission and aggregate limits

These fields supply observations only. Illumination does not establish radar lock. Raw shooter_status2 is not a permission token, unique receipt or acknowledgement. Existing cost_coins represents spent support cost, not a release quote. The1Hz topic rate does not establish a receiver expiry threshold.

No role/operator/target eligibility, freshness timestamp, offer, EconomyContext field, budget, timer, command revision, confirmation behavior or publication authority is added. New observations alone neither increment economy_status_revision nor clear a pending command. The existing support-active revision behavior remains. Identity, session, observation freshness, action policy, confirmation/frontend behavior and secondary consumers must agree before V2 activation.

This stage was prepared from full51 source `9ee192547a49747cc22232ff716b5889917daa0d`, tree `1efcd44a59a2f70a5722ba25622d5ad82ae76625`, and integrated on its documentation-only successor `ea4bd58205dfe3367a556a3c1e76def548e211dc`. The integrated stage is local `650ec01c7dfb879311139378e9bd53619399b7e4`, parent-verified public [b58dca1](https://github.com/lulunomaro/polar-rm-client/commit/b58dca157bd60dc7738507328e504bef6baac3bb), shared tree `2e97032d9084fa4a65881690901d52d66d962630`. This is the exact frozen source tested by full52.

The separate [full51 checkpoint](referee_v2_projection_20261019.md#completed-full51-qualification) remains415 PASS /12 SKIP /4 INCOMPLETE /1 FAIL, NO-GO. Its strict DT7 <20ms check failed at20.113138998567592ms; no cause, threshold change, aggregate retry or causal closure is inferred from this unrelated projection. The previous source's failed qualification is preserved. All external/native prerequisites, Radar ambiguity and explicit unsupported V2 registration remain.


## Completed full52 qualification

Full52 started from the clean source above and completed **417 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO**, run `2d21aa1d861f49c5802521b3eae78514`. All778 declared source inputs retained start/end SHA256 `4908534ff2f8d6390089651dff8b2a8ea939d3da4afd004bbc872bfd0dc41aee`. Endpoint stability excludes external dependencies, assets outside fixtures and transient edits restored between captures. These are selected suite/check outcomes, not unique test-method counts.

The new aerial regression passes21 methods in0.154s; the prior projection32 and rule-price12 pass in0.151s and0.117s respectively. The existing DT7 worker-dispatch module passes all15 methods, harness duration6.888s. Its unchanged strict20ms test records250 ticks/2.500s, median0.0789ms and max7.4678ms, scans4/retries3. The test, DT7 worker/link, safety and serial-port sources are byte-identical to full51. This passing sample does not establish the cause of full51's20.113138998567592ms failure or qualify every future scheduler/load condition. Neither the threshold nor the historical result was changed.

The four INCOMPLETE items remain the external team CRC reference, DT7 firmware/vendor reference, application-C cross-check and excluded legacy installation-patch qualification. Twelve SKIP outcomes are not passes. Official-software interoperability, native Windows/device acceptance, remaining authority/action/frontend work and Radar resolution remain open. No whole-project or deployment GO is claimed, and later source edits are not covered by this run.

The [RobotState authority addendum](robot_state_authority_audit_20261017.md#2026-10-19-addendum-unregistered-v2-aerial-observations) records the two additions and247 declared fields while preserving the historical inventories.
