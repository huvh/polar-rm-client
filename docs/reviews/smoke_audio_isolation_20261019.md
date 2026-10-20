# Isolate smoke-test audio from native device loading — 2026-10-19

The corrected per-test offline fixture is qualified by [full48](#completed-full48-qualification). Overall acceptance remains **NO-GO**; full46’s timeout and full47’s failed first fixture remain counterevidence below.

## Full46 counterevidence

Full46 completed with **410 PASS / 12 SKIP / 5 INCOMPLETE / 0 FAIL, NO-GO**, run `18a16e9727144b7cb5184f115b99de18`. Its exact source identity and calibration evidence remain in the dated [calibration report](calibration_config_load_validation_20261019.md#qualification-limits-and-aggregate-follow-up). Its smoke subprocess exceeded the unchanged 300-second deadline. The last completed function was `test_calibration_export`; the next function, `test_armor_3d_esp_render`, remained in window construction. Two faulthandler snapshots, 120 seconds apart, placed the main thread in `ReliableAudioPool.preload` at `QSoundEffect.setSource`, reached through startup feedback.

Full45 completed the same smoke source in 8.057 seconds; full46 timed out after 300.072 seconds. The smoke, audio, startup and verification-runner sources were unchanged. Both runs recorded PulseAudio/no-device warnings, so those warnings alone do not explain the different outcomes. The observed native call is localized; its underlying stall cause remains unresolved. The calibration regression passed separately, and no causal link from that repair to this timeout is established.

## Initial offline fixture boundary, before full47

The first smoke-runner change entered the existing `isolated_activation_audio` context around each test call. This covers construction, assertions and test-owned cleanup, then restores the audio aliases and clears cached device selection before scoring or the next test. The helper replaces native audio constructors and the three captured device-query aliases while retaining the existing owner paths. Production audio and the helper itself were unchanged at that stage. No deadline, skip rule or failure classification was loosened.

All **71 original smoke-test function ASTs and 1,115 assert statements** are unchanged. The aggregate's 71 completions count functions/checks, not individual assert statements. This runner boundary does not cover unrelated direct test-function calls or top-level imports, and it adds no new guarantee about the helper's existing setup-failure prefix.

Focused evidence:

- Seven pure AST methods pass; the same saved-baseline selection produces eight assertion/subtest failures and zero errors.
- Independent review passes those seven methods, eight additional order/error/cache controls and two unchanged scoring methods.
- Six author and four independent omission mutants are rejected with assertion failures and zero errors. These selections overlap and are not additive unique coverage.
- Repository integration passes the seven new methods plus three existing scoring methods, 59 existing quality-gate methods, and the static gate: 221 production modules, 3,500 functions, zero initialization cycles.
- The pure proof executes the actual runner/helper/preload/device-selector ASTs with inert collaborators. Its 71-name ordering control uses inert callbacks; it is not an execution of the 71 smoke bodies. The smoke module, application facade, excluded implementation and native audio are not imported by that proof.

Independent review found one required scoring-fixture adaptation: its extracted runner namespace lacked the new context port. The unadapted fixture produced **two NameError errors**, retained as failed integration evidence. Adding only `isolated_activation_audio=contextlib.nullcontext` preserves its existing assertions; both scoring methods then pass. The real audio helper is covered separately.

First-stage hashes:

- `tests/smoke_test.py`: `fd701f687d48533b9708b43d7a718fc67e8a07b759bd56498779d7ba89dabb41`
- `tests/test_smoke_audio_isolation.py`: `8dc94117beff706e04f590041f0ead22e07661722d7bce554a4ffa8e5d96424c`
- `tests/test_test_registry.py`: `d5777d237ce5b48b3dfba5cce31d6f28687294123c6906071c9c27f9c2a01e1f`
- Unchanged `tests/test_window_activation_failure.py`: `8c217b5004584f44f5026ba8422294ae89e9722cc2577230cb06dbfb77ed34dd`

## Full47 completed with a fixture failure

Full47 completed with **411 PASS / 12 SKIP / 4 INCOMPLETE / 1 FAIL, NO-GO**, run `be9c21df5f5d43a799d2cf3713ab7a84`, against public source `3531eba8f12e3b11886b3601d9a826814bd7cbba` / local `a8f153420c30390b88b568b6a8e9de1ab2f30327`, identical tree `6587f1d5bf93169f9c539307e0ac95d8121f2f32`. All 767 declared inputs retain SHA256 `95cc092e1011bbd62529047246b42279aa27eae01e7b7fca797d2a1878cbdbbd`.

Smoke completed 48 checks before failing in 6.199 seconds. Its legitimate Hero-interface interaction called GUI feedback, which reached the inert media player's `play`; the reused activation-only fixture raised `unexpected activation playback`. This is a regression in the proposed smoke fixture. The prior pure checks proved native isolation and runner ordering, but omitted this legitimate playback route and did not execute the 71 real smoke bodies. Their acceptance was insufficient to qualify the fixture for all interactions.

This failure required the separately reviewed correction below: permit inert playback explicitly for smoke while keeping activation tests strict by default. No production feedback suppression, swallowed assertion or native-audio repair is justified by this failure. Full46 and full47 remain preserved; native audio/device acceptance and historical timing causation remain open. Raw logs are not published.

## Corrected smoke-only playback fixture

The correction adds a keyword-only `allow_playback=False` to the existing helper. Its default remains strict for activation/constructor fixtures; only the smoke runner explicitly opts into inert playback. Native construction/device-query isolation, per-test context lifetime, exception propagation and cleanup remain in place. The scoring fixture accepts the explicit keyword. No production audio or GUI feedback behavior is changed.

The expanded pure suite executes actual Ready QSoundEffect playback, media fallback/preloaded playback and GUI transition/feedback routing with inert native collaborators. It verifies that an ordinary assertion after successful feedback still propagates with the same identity. The full47 baseline reproduces **three failures and zero errors** in the 11-method suite; the correction passes all 11. Independent review additionally passes six policy controls, including nested strict/allowed scopes and injected playback failures, plus two unchanged scoring methods. Six author and six independent mutants are rejected without errors. These are overlapping focused selections, not additive unique coverage or an execution of the full smoke bodies.

Integrated repository checks pass **14 pure/scoring methods**, **59 quality-gate methods** and the unchanged static production metrics (**221 modules / 3,500 functions / zero initialization cycles**). All 71 original smoke bodies and 1,115 assertions, the previous seven pure test bodies and existing activation test bodies remain unchanged. The completed full48 checkpoint below establishes this corrected fixture’s offline integration; full47 remains the failed result above.

Corrected hashes:

- `tests/smoke_test.py`: `37706c69c8a6b8e977ea2da435f5b4b5b726b1f4df0cc96df3d7fab732b05736`
- `tests/test_smoke_audio_isolation.py`: `2a198b7484324034c41ff7d02b80201c2aaa3c4328612510e58c01b09f58c2e1`
- `tests/test_test_registry.py`: `c6d2bc52e75abd89233bc7ed9389cafff03ed36c355ecacdb5113205ba07bb51`
- `tests/test_window_activation_failure.py`: `1920115f5b1bfbb7c1e9c99d3bb29085fdc79a55c171b25766a536f009f15a85`

## Completed full48 qualification

Full48 completed with **412 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO** (`passed=false`). The smoke subprocess completed **71/71 test functions, zero skipped checks**, in **8.068 seconds**, with the unchanged 300-second deadline. The report’s generic “71 explicit assertions” label denotes these completed functions/checks; it does not count the 1,115 individual assert statements. This is one completed offline run, not a timing benchmark or proof of native-audio recovery.

- Run identifier: `22b81c5ec7d44f4296ba7604ec1a9c2f`, started 2026-10-19 at 01:00:54 UTC.
- Public code source: `66293a014251d561f94ef899874d38721d9fe031`.
- Corresponding local code source: `fe9609ee6ee205efe17d3e7a3f911827adb66473`.
- Shared Git tree: `88e9409326803cdadec4d3b06ff16ea31bb46f81`.
- All 767 declared inputs retained start/end SHA-256 `7e16ea43c151cae5cf382eccda28032322dfcf889db2a55e0844551283516434`; source stability PASS.

These aggregate totals are selected offline suite/check outcomes, not unique test methods. The fingerprint covers declared code/config/test inputs and internal fixtures. It excludes documentation, other assets, external fixtures and installed packages, and cannot detect transient edits restored between the two captures. This report is a later documentation-only update and does not broaden the tested source identity.

The four remaining INCOMPLETE entries concern the missing team CRC reference, missing DT7 firmware/vendor references, missing application C cross-check inputs, and the deliberately excluded installation-based legacy patch test. External/native prerequisites, physical audio/device behavior, native Windows/GPU acceptance and historical timing causes remain open. The new fixture avoids native audio in these offline smoke interactions; it does not repair or explain the full46 native stall. Full47’s fixture-policy failure, the earlier scoring-fixture errors and all failed-stage evidence remain preserved. Raw execution logs are not published.
