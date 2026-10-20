# V2 rule-price and command-membership foundation

2026-10-19. The bounded source stage is independently accepted; the combined full51 aggregate completed with one failing DT7 timing check and remains NO-GO. V2 remains unregistered. This stage supplies arithmetic and enum membership, not an enabled action path.

## Exact source and references

- Local stage: `9ee192547a49747cc22232ff716b5889917daa0d`.
- Parent-verified public stage: [eb9c052](https://github.com/lulunomaro/polar-rm-client/commit/eb9c052f4859a68259558a1bcf67f2997cc321e4).
- Tree: `1efcd44a59a2f70a5722ba25622d5ad82ae76625`.
- This follows the separate V2 projection stage, local `1a46e2a` / public `2535d8bf`; its evidence is separate.
- [Official protocol](https://bbs.robomaster.com/wiki/20204847/811363): V2.0.0, 2026-06-26. [Competition rules](https://bbs.robomaster.com/wiki/20204847/809871): V2.2.0, 2026-08-07, SHA256 `88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5`. Protocol and rules version numbers are distinct.

Only two files are added: `rm_client/backend/referee/rm2026_v2/economy_rules.py` and `tests/test_referee_v2_action_rules.py`. Existing V1 policy and V2 contract bytes are unchanged. The review does not establish which older competition-rule revision originally applied to V1.3.1; no retrospective V1 correction is claimed.

## Implemented scope

Rules Table5-6 p.77 places the heal multiplier20 inside upward rounding, while revival multiplier80 is outside. For integer remaining seconds T and observed level L:

- Base remote heal estimate: `50 + ceil((420-T)*20/60)`.
- Same-level ground revival comparator: `ceil((420-T)/60)*80 + 20*L`.
- Aerial countermeasure-release estimate: twice that comparator, as specified in §5.6.3.

Integer arithmetic avoids floating-point rounding. Invalid/missing inputs are rejected rather than defaulted or clamped: T must be an integer0..420; L an integer1..10; bool, float and numeric strings are rejected. Rules §5.4.1/Table5-12 define the leveled Hero/Infantry/Aerial system; this does not infer a Sentry or Engineer level.

At419 seconds the heal rule estimate is51, whereas the existing V1 minute-rounded policy produces70. A copied complete V1 offer with51 coins is locally disabled by that price. This proves the concrete local arithmetic/admission difference against the pinned V2 rules; it does not prove a server charge or transaction. Base heal excludes Sentry intervention surcharge. Arbitrary server quotes must not have a second surcharge blindly added.

`is_documented_command` reuses the reviewed V2 contract sets: Sentry `{1,3,4,5,6,7,8,9,10,11,12}`, Air `{0,1,2,3}`. It answers membership only. Tests pin the existing Sentry trigger/10Hz, Air trigger/no numeric limit and QoS1 metadata; this patch installs no limiter or new rate table.

No offer catalogue, model fields, role/stage eligibility, target/freshness authority, server quote, cooldown/budget tracking, receipt correlation, UI, registration or transport behavior is added. No inactive-Air-as-dead gate is introduced. Future callers must establish explicit V2/RMUC7v7 identity and correctly scoped current observations before using these estimates. The module cannot establish those facts itself.

## Verification and retained counterevidence

- New pure regression:12 methods PASS, including421 integer countdown values and4210 time/level pairs against independent Fraction/ceil formulas, fixed boundaries, strict input rejection and exact command sets.
- Eight in-memory single-expression mutations are rejected by assertion failures, zero errors: old minute-rounded heal, floor heal, wrong revival rounding, missing aerial multiplier, accepting bool in prices or commands, accepting removed Sentry2 and excluding Air3.
- Independent official-source review:9,183 pure check points PASS, including421 heal,4210 revival and4210 aerial formula evaluations plus type/membership/scope/hash controls. These are loop/check counts, not9,183 test methods. Candidate files and unchanged V1/V2 contracts were hash-verified.
- Repository integration:35 focused methods PASS, comprising the new12 plus existing domain characterization, domain boundary and economy value-dependency tests. No old assertions were changed. `git diff --check` passes.

The earlier complete-policy comparison found399 differing heal prices across421 valid countdown values; its candidate matched all421 and preserved421 dead-state complete offer lists, including revival. Its first harness compared dataclass instances from different isolated module identities and failed equality. That rejected harness was retained; corrected comparison uses fields. This was a harness error, not hidden production evidence. The new12 helper tests are not advertised as a pre-existing baseline red suite because those APIs did not exist before this stage.

Pure checks load only contract/arithmetic modules and inert test values. The focused integration is distinct from the independent loop counts. Neither proves official software, broker, physical receiver, actual payment or action execution.

## Aggregate status and remaining acceptance

Full51 completed for the combined projection and price tree above: **415 PASS / 12 SKIP / 4 INCOMPLETE / 1 FAIL, NO-GO**, run `bd73bca4db9e430f958ce2c682ff185d`. The start was clean; all777 declared inputs retained start/end SHA256 `e025d7f0ab8591751d9cc6d7b55a25650e3cee094045baad97fae64d36ce8c1d`. The new price12, projection32 and existing V2 codec24 methods passed. Source stability compares declared endpoint snapshots; it does not cover external dependencies, assets outside fixtures or transient restored edits.

The sole failure is `tests/test_dt7_worker_dispatch.py:341`, `test_no_device_real_time_100hz_tick_retry_budget`: tick138/250 measured **20.113138998567592ms**, violating the unchanged strict `<20ms` gate. Diagnostic caller thread CPU interval was20.339525ms, scans4, retries3; that interval also includes timing bookkeeping. These measurements do not establish a cause. The15-method module had one failure; it is not an accepted aggregate despite passing V2 checks.

Full50 passed the same15-method DT7 module; its sample reported max5.8432ms, median0.0779ms across250 ticks/2.500s, scans4/retries3. The test, DT7 worker/link, safety and serial-port sources are byte-identical between the tested full50/full51 commits. Unchanged source does not prove an environmental cause or excuse this failure. No retry, threshold relaxation or causal fix is claimed here. Full50 remains **414 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO**, a separate earlier-source checkpoint.

Still required: authority-backed offer/action policy, correctly scoped target/role/stage and freshness, UI confirmation and failure behavior, secondary consumers, explicit profile activation, Radar resolution or an explicit unavailable capability, and authorized official-software/hardware acceptance. Historical smoke failures, external prerequisites and all prior qualification limits remain.

Frozen source SHA256: `188b718f4dad2b846c47a81f0e28510420ca34e6667adc0bfad48c89cc401252`.
Frozen test SHA256: `e2b9d17d3e06e691c81fad3031d1d27d5025e4944e0cc80aa34d81be9efc344c`.
