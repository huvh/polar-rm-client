# Backend consumer alignment, 2026-10-21 reconstruction

This stage was rebuilt on restored baseline `222899de17d211755b7a0a3b2851144ff8016c6c` (tree `32e942ec4c8112ecf1024488f1e23a0f71bcecb9`). Earlier lost-workspace commits and results are not evidence for this tree.

## Intentional corrections

- Legacy economy transactions retain their actual state owner and profile, match mode, robot identity, alliance, round, and mock provenance. A changed context stops local tracking before mock mutation or telemetry interpretation. This is not a cancellation of a server request and causes no retry. Public transaction constructor shape is unchanged. V2 offers still cannot enter legacy V1 economy; the diagnostic points to its independent confirmation workspace.
- Official countdown chat emits match-end warnings only in MATCH/4, not preparation countdown. Round/profile/owner transitions clear old threshold state. Local mock behavior remains available; chat remains a private/local feature, not an official uplink.
- Private vision result parsing rejects nonfinite numeric values and invalid dimensions/timestamps. Strings such as `false` cannot become positive calibration/aim evidence. Invalid packets do not terminate the reader or overwrite valid results; future timestamps are not fresh. Tongji/PLVR remains a private extension, not an official referee protocol.
- Hero ballistic preview rejects missing/zero/nonfinite quaternion, future/nonfinite native telemetry timestamps, and invalid heat capacity. Quaternion normalization preserves the physical roll under scale. Existing readiness gates remain; no motion/fire output was added.
- Invalid keyboard/mouse policy descriptions, including infinity, return unknown rather than raising OverflowError. This changes no control output or authority.
- A specifically observed own-robot integer zero `max_buffer_energy` produces 0% capacitor display, not the mock 62%. An unobserved/mock or another robot's zero does not overwrite local fallback; later positive capacity restores the ratio.

## Revalidation

- `tests/test_backend_feature_consumers.py`: 22 tests passed on the reconstructed source.
- The same 22 tests against production modules loaded from `git show 222899de:<file>` produce 66 failing subcases and two errors, documenting the old bugs. No historical fixture was regenerated.
- `tests/test_ui_state_regressions.py`: 30 tests passed. Its isolated production-AST loader now includes the exact two new vision helpers, rather than replacing them with weaker test stubs.
- EconomyCommandBridge's exact AST delta is appended in `test_referee_domain_characterization.py`; every historical assertion and baseline fixture remains pinned. Profile/adapter changes are separately owned by the protocol stage.

## Boundaries and remaining stages

AutoSpin, private native transport, controller angles and live safety admission are separate owners; this stage neither substitutes them with official MQTT nor opens new outputs. Official Rune ring units, event command forms, economic confirmations, performance preparation flow and Radar units are subsequent independently tested stages. Decode/raw state availability is not equivalent to a dedicated HUD consumer. No device/network transport is started by this stage's tests.

Final evidence correction: Hero readiness's four positive state flags now require the actual boolean `True`, not Python truthiness. `false`/`true` strings, 0/1, None and False cannot become readiness evidence. This changes no motion/fire output or interface. The expanded consumer suite passes 23 tests; the earlier 22-test baseline counterexample remains identified separately above.
