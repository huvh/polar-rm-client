# RM2026 V2 codec foundation: unregistered, offline-qualified

2026-10-19. Full50 completed with **414 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, overall NO-GO**. This report describes the bounded codec foundation, not an enabled V2 client or official-device acceptance.

## Source and document identity

- Local code commit: `c96c378b1c0a44fe931daf09bbcb95b85c5c0f34`.
- Parent-verified public code commit: `287a6b4861ea6880b699ac154a3fa1e6167d0af7`.
- Shared source tree: `a52b9737774ea7e122dae1bd199ab7476d5efe9f`.
- [Official 2026 protocol](https://bbs.robomaster.com/wiki/20204847/811363): V2.0.0, dated2026-06-26; PDF SHA256 `8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b`.

The patch adds one version-specific package, one regression module and one author-created synthetic fixture. Existing V1/Student codec, wire primitives, registry, defaults, state adapters, UI, transport and prior tests are unchanged. No third-party implementation or raw protocol PDF was added to the repository.

## Implemented boundary

The V2 contract accounts for all36 documented topic names:11 uplinks and25 downlinks. The codec supports24 downlink schemas. RadarInfoToClient remains explicitly unavailable because the published wrapper example is incomplete; no empty-success schema or guessed wrapper was introduced. Existing V1 Radar behavior is unchanged.

New decoded fields are GameStatus uint32 fields9/10 (`game_result`, `end_reason`) and SentryStatusSync bool field3 (`is_powered`, meaning boosted/strengthened status). Exact field presence distinguishes omissions from explicit zero or false. Settlement255 remains transmitted data, and absent values are not synthesized as255. Later projection must establish stage/round applicability before displaying an outcome.

The version-local decoder retains bounded malformed-wire rejection, forward-compatible unknown fields, unknown-only authority rejection, signedness, strict scalar validation and existing authority guards. Packed and unpacked negative int32 values both decode correctly in V2. The shared V1 implementation and its existing behavior were not changed.

All11 uplink encoders reuse the unchanged public, stateless V1 wire functions. Sentry values10/11/12 and AirSupport value3 remain values of field1; AirSupport shooter_status value2 remains field5. Documented command sets and topic rates are recorded without changing action policy or transport limits. Map-mark timing remains role-specific; no numeric AirSupport limit was invented.

Wire encoding does not authorize publication. Existing encoder coercions do not enforce every numeric domain, enum, role, finite-coordinate or keyboard-mask rule. Those admission checks, state projection, UI actions and explicit profile activation remain later stages. The registry still rejects V2, with V1.3.1 and Student-readonly defaults/identities preserved. No negotiation or automatic version inference was added.

## Evidence

- New pure suite:24 methods pass, covering24 supported downlinks and11 uplink encoders against independently encoded synthetic fixtures.
- Baseline comparison:four feature-gap probes produce four assertion failures and zero errors; the V2 candidate passes all four. Three concern new V2 fields; one records the older unpacked negative-int32 behavior. These are bounded comparisons, not four new production defect claims.
- Ten runtime-only negative controls are rejected with assertion failures and zero errors.
- Independent review directly compared171 field definitions across35 verified schemas and all36 topic entries with the pinned official PDF:zero discrepancies. A separately written, isolated copied-module runner passed629 checks. These counts are separate from the24 regression methods.
- Integrated repository selection:71 methods pass, comprising the new24 and47 existing V1 presence, state, frontend, domain and profile checks. All five additions match the reviewed bytes; seven pinned original dependency files remain byte-identical.
- Existing guarded API check passes:1,114 established members,540 Python signatures and78 private caller seams. Static quality gates pass:224 production modules,3,502 functions,zero initialization cycles. No gate baseline was changed.

The protocol checks use inert bytes and block native/application/transport activity. The separate API check uses an offscreen window with inert audio, fresh storage and closed serial/network boundaries; its OpenGL-platform warning remains documented. These checks do not establish physical rendering, audio, broker interoperability or robot execution. No excluded algorithm probe was run.

## Full50 qualification and remaining acceptance

The parent ran one offline aggregate for the source tree above. Run ID: `8130d703ab294e69865cf93fc0e23f4c`; started `2026-10-19T02:10:29Z`; terminal counts **414 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL**, overall **NO-GO**. The new V2 regression passed within that run.

All773 declared source inputs had the same start/end SHA256: `3c28dd03f2e07935f2782ce8a936419a01f9be072bd54b72c67fbdd311263a53`. The source was clean at start. This comparison covers the declared code/config/test-fixture inputs, not external fixtures, installed dependencies or transient edits restored between captures.

The four incomplete items retain the existing team CRC capture, firmware/vendor-reference, application-C crosscheck and installation-dependent legacy-test prerequisites. Skips and incomplete items are not passes. This run does not discharge the official-software or physical-device queue, and earlier full46 smoke timeout/full47 fixture failure remain in the [smoke audio isolation history](smoke_audio_isolation_20261019.md).

Still required: version-aware canonical state and freshness; command admission and confirmed UI actions; secondary-consumer compatibility; explicit profile activation; authoritative Radar resolution or a declared unavailable capability; authorized official-software and physical-device validation. No2027 protocol support or complete official-client replacement is claimed.
