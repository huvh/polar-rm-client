# Saved calibration export error contract — 2026-10-19

## Status

The bounded export repair is qualified by the completed [full49 checkpoint](#completed-full49-qualification) below: **413 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO**. The prior [full48 checkpoint](smoke_audio_isolation_20261019.md#completed-full48-qualification) remains source-specific; its retained full46 timeout and full47 fixture failure are not waived.

## Confirmed failure and existing caller contract

The `Export Tongji YAML` action calls `CameraCalibrationManager.export_tongji_yaml`. Its UI adapter already displays a warning when the owner returns None and a success message when it returns a Path. Missing profiles and missing templates already follow this contract. However, ordinary filesystem errors from template/profile acquisition and target writing escaped the owner and action adapter before a warning could be displayed.

A pure reproduction executes the real calibration owner and actual dispatch/config-action/calibration-action method ASTs. Real directories occupying either the template or output path produce `IsADirectoryError`; injected permission errors cover write and stat failures. The preserved baseline probe has **five assertion failures and zero errors across seven methods**. Healthy export and the existing missing-template warning pass.

The proof establishes exception escape through the actual action adapter. It does not execute native Qt signal/event delivery or claim a native UI crash.

## Bounded repair

Two OSError handlers are added to the existing export owner: one around profile/template acquisition, including fallback-load stat, and one around target writing. They record `str(exc)` in `last_error` and return None, allowing the existing UI warning branch to run. No UI callback, public signature, calibration algorithm, quality threshold or load implementation changes.

YAML/numeric rendering remains outside both handlers. ValueError, TypeError, RuntimeError, KeyboardInterrupt and SystemExit retain their existing propagation. Even OSError raised by unusual custom formatting code remains outside the file-operation guards. Toast failures remain outside the owner as well.

Preserved behavior includes:

- Existing-profile precedence, even when its name differs from the export name or it fails the current quality threshold.
- Publication of a successfully loaded fallback profile before a later export-write failure; no new rollback is introduced.
- Existing generic no-profile diagnostics after an already contained load-read failure.
- Raw export names and direct overwrite, including the existing direct-API ability to name `demo` and overwrite the template. No new naming or source-protection policy is added.
- UTF-8 replacement decoding, first-key replacement/append, coefficient formatting, rotation/translation defaults, device substitution, metadata comments and success diagnostic clearing.

A partial write may already change destination bytes before raising OSError. The regression explicitly preserves that observed prefix while reporting failure. **This is not an atomic export, rollback, backup, crash-durability or destination-preservation repair.** Missing output directories are not created. Capture/solve math, coefficient shape/ranges and the separate calibration-save path are outside this change.

## Focused evidence

- New regression: **21 PASS**; the identical saved-baseline selection produces **10 assertion failures / 0 errors**.
- New regression plus existing load-validation tests: **36 PASS**.
- Unchanged original seven-method probe plus the unchanged existing calibration-export smoke method loaded by AST: **8 PASS**.
- Eight author and seven independent omission/broadening mutants are assertion-rejected with zero errors. These selections overlap and are not additive unique coverage.
- Independent external review passes the 36-method selection and seven additional controls covering error identity, actual UI warning, partial writes, profile retention, retry and compatibility.
- Normal repository integration passes **37 checks**: new21, existing load15 and the unchanged export AST1. Independent integrated review reruns those 37 and its seven repository-source controls successfully, verifies both frozen hashes and unchanged prior load/smoke tests, and accepts the integration.
- Guarded API check passes: **1,114 established members / 540 Python signatures / 78 private caller seams**.
- Static gates pass: **221 modules / 3,500 functions / zero initialization cycles**.

The pure checks use temporary files and inert collaborators, with native/application imports blocked. The API check is a separate offscreen Qt/facade construction with fresh storage, inert audio/serial boundaries and fail-fast socket operations. Its unsupported-QOpenGLWidget warning is retained; it establishes no native rendering, audio, hardware timing or physical-device qualification. The full smoke module is not imported by the focused export proof.

The first external design used one outer OSError handler and would also absorb custom-formatting OSError. It was rejected during scope review. Its bytes/log remain as counterevidence; the accepted design has two guards and a regression requiring formatting OSError propagation. No prior assertion or gate budget was weakened.

## Frozen files

- [`rm_client/calibration.py`](../../rm_client/calibration.py): `71a2cf6bed7500e91918679491a53acbeadeb46f49ec7dce2c8a7d41c28f5cf4`.
- New [`tests/test_calibration_export_errors.py`](../../tests/test_calibration_export_errors.py): `df43dd662a62dd3f35b4d3005a01ec624a57084fdebdf339868075bb42bd5c0f`.

Unwrapping exactly the two new handlers restores the entire previous production module AST. The accepted [saved-profile validation](calibration_config_load_validation_20261019.md) is unchanged. One existing production file changes and one regression file is added; no production module is added.

## Completed full49 qualification

Full49 completed with **413 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL, NO-GO** (`passed=false`). The new export regression passes all **21 methods**; the existing load-validation regression passes all **15 methods**. Smoke completes **71/71 test functions, zero skipped checks**, in **8.611 seconds**, with the unchanged 300-second deadline and inert per-test audio. Its generic “71 explicit assertions” label counts completed functions/checks, not the 1,115 individual assert statements. This is a completed offline run, not a native-audio recovery claim or timing benchmark.

- Run identifier: `7c6014d9aee847689b0236f1948d3ae1`, started 2026-10-19 at 01:48:44 UTC.
- Public code source: `db46402ae238a60db2df8623dc345781229d6c43`.
- Corresponding local code source: `667a7dd1d3332a95d134c844cb5c894be5ca4b91`.
- Shared Git tree: `93f2943f4474cf242c9bbfebabf1e549f4a0bc19`.
- All 768 declared inputs retained start/end SHA-256 `727b1406c8c5c21381c7dd60dcfea435e874a2e215447df61cf6de4fe02a6645`; source stability PASS.

These totals are selected offline suite/check outcomes, not unique test methods. The fingerprint covers declared code/config/test inputs and internal fixtures. It excludes documentation, other assets, external fixtures and installed packages, and cannot detect transient edits restored between captures. This later documentation-only update does not broaden the tested source identity.

The four remaining INCOMPLETE entries concern the missing team CRC reference, missing DT7 firmware/vendor references, missing application C cross-check inputs, and the deliberately excluded installation-based legacy patch test. External firmware/reference prerequisites, native Windows/GPU/device acceptance and historical timeout causation remain open. Full46’s timeout, full47’s fixture failure and the rejected broad-catch export design remain preserved. Raw execution logs are not published.
