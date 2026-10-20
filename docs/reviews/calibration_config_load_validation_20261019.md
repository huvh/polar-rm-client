# Saved calibration profile validation — 2026-10-19

## Status and exact source identity

The bounded source repair and focused checks are complete. **Full46 completed:
410 PASS / 12 SKIP / 5 INCOMPLETE / 0 FAIL. Overall acceptance remains NO-GO.**
The new calibration regression passes, but `smoke_test.py` timed out after
300.072 seconds and its child tree was stopped. This is an additional unresolved
INCOMPLETE result, not a successful full-aggregate qualification. Its cause is
under independent investigation; no rerun has been performed.

- Public code commit: `f1d07c5a92670670a1a75bf04045ffd643e58dab`.
- Corresponding local code commit: `e89d3b763a0cd283c69494d1f14e1d7a66bc1b38`.
- Shared Git tree: `12daa7746e53a7afb402709f7731eae3c435328a`.
- Source: [`rm_client/calibration.py`](../../rm_client/calibration.py), SHA-256
  `fd4d59b9997092b8f9e0e2a89def3825aa5575b21406f10475c23f16c00bab41`.
- New regression: [`tests/test_calibration_config_validation.py`](../../tests/test_calibration_config_validation.py), SHA-256
  `24843a33e74a4e4d99dbce83d8505e253f2d3d377f815c4f1aeefcb6e17ccc48`.

The code stage changes one existing source file and adds one regression file.
No existing test assertion, API manifest, gate budget, protocol, quality
threshold or persistence transaction was changed. No production module was added.

## Confirmed failure

The ordinary client-profile loader already validates malformed nested
containers and nonfinite values before registry application. Its existing
validation, migration, wheel and import ordering contracts were reviewed; this
audit did not establish another defect in that path.

The separate saved camera-calibration loader had no corresponding field
validation. `CameraCalibrationManager.load` decoded JSON, constructed
`CalibrationProfile`, and immediately assigned it to `self.profile`. Dataclass
annotations do not validate runtime data.

A saved `sample_count: null` was accepted and replaced the current profile.
The actual presentation predicate `vision_result_calibrated` then called
`is_valid_for`, which raised `TypeError` while comparing `None >= 8`. Other
null/list scalar fields and malformed/nonfinite vector entries were also
published unchecked.

The startup caller is `create_vision_services` in
[`window_assembly.py`](../../rm_client/ui/polar/window_assembly.py). Current
consumers include `active_tongji_result` in
[`video_backend_mixin.py`](../../rm_client/ui/polar/mixins/video_backend_mixin.py)
and `vision_result_calibrated` in
[`esp_wireframe.py`](../../rm_client/ui/polar/renderers/esp_wireframe.py).
The reproduction executes the pure loader and selected complete caller methods
by AST with inert service doubles. No inference or device operation is needed
to reproduce the failure.

## Repair and compatibility

A private validator on the existing calibration module checks the complete
profile before the existing live assignment:

- Name must be a string; empty and Unicode names remain accepted.
- Numeric scalars and vector entries accept finite JSON integers or floats
  without coercion. Float-valued counts/dimensions remain accepted, including
  fractional values; no new integrality rule is introduced.
- Camera-matrix and distortion-coefficient containers must be lists.
- Numeric strings, booleans, nulls, nested objects/lists and nonfinite values
  are deliberately rejected. This is changed malformed-input behavior.
- Numeric overflow during the finite check follows the existing rejected-load
  contract instead of escaping.

The actual unchanged `solve` producer writes integer dimensions/counts and
floating-point geometry/RMS/vector values. Its serialization was exercised
using an explicit inert calibration-result double. No tracked legacy profile
or production writer of booleans/numeric strings was found.

A rejected load returns `None`, records `last_error` and retains any previous
profile object, matching the existing malformed-JSON/schema/read-failure
contract. With no previous profile, it remains `None`. Missing-file behavior,
successful-load historical diagnostics, direct dataclass construction and
process-control exception propagation are unchanged.

**No vector-shape, numeric-range, distortion-model, physical-accuracy or new
calibration-quality guarantee is added.** Existing sample-count/RMS/dimension
checks are unchanged. Empty/arbitrary vector lengths and finite values outside
physically meaningful ranges remain accepted. Capture, solving and export math
are unchanged. This is validation of serialized value types and finite numeric
representation, not certification of calibration quality.

## Reproducible evidence

The selections below overlap and must not be added together as unique tests.

| Selection | Baseline | Repaired source |
|---|---|---|
| Original five-method loader/caller probe | 28 assertion/subtest failures, zero errors | Five PASS |
| New 15-method regression | 108 assertion/subtest failures, zero errors | 15 PASS |
| Seven independent compatibility controls | Five unchanged-behavior controls PASS; malformed-input controls intentionally target the repair | Seven PASS |
| Existing calibration-export smoke method, loaded unchanged by AST | Existing positive contract | One PASS |

Normal repository imports exercise the integrated regression and
compatibility controls. Coverage includes startup rejection, the actual
presentation predicate, prior-profile identity, file-byte preservation,
producer serialization, scalar/vector null/list/string/bool/nonfinite values,
huge numeric integers, existing quality thresholds, accepted numeric/shape
compatibility and exact process-control exception prefixes.

Twenty author mutation controls and six independent controls reject omitted
checks or altered contracts. They cover individual fields, scalar/vector type
and finite checks separately, early live publication, overflow escape, boolean
admission, new shape policy and process-control swallowing.

The first broad early-publication mutation run produced assertion failures
plus two real predicate `TypeError` errors. That rejected-mutant result is
retained. The final ordering control uses the existing direct profile-identity
assertions and rejects the same mutation with zero errors; production and
regression hashes did not change to obtain that result.

Whole-file AST comparison confirms unrelated methods are unchanged. API
compatibility passes for 1114 established members, 540 Python signatures and
78 private caller seams. Static gates pass: 221 Python modules, 3500 functions
and zero initialization cycles. Existing gate baselines were not updated.

## Qualification limits and aggregate follow-up

The focused regression is source-only: temporary files, the pure calibration
owner, explicit result/service doubles and selected caller ASTs. Import guards
exclude native vision libraries, Qt, the window facade, backend and spin code.
The existing API checker is a separate offscreen Qt/facade construction check
with fresh storage and inert audio/serial/network boundaries; its unsupported
QOpenGLWidget platform warning does not establish native rendering support.

No physical camera, robot, network endpoint, model inference, native GPU,
calibration accuracy or hardware timing was tested. No concurrent-writer,
crash-durability, file-size or universal JSON-depth guarantee is claimed.

Full46 is the sole aggregate run for the exact code identity above:

- Result: **410 PASS / 12 SKIP / 5 INCOMPLETE / 0 FAIL; NO-GO**.
- Run identifier: `18a16e9727144b7cb5184f115b99de18`.
- Stable input manifest: 766 inputs; SHA-256
  `debc13076c26af21a24d1ddbdb1277ad87042a3e7f3abc6ffe62c2fdaddcbee3`.
- The new calibration regression passes in this run.
- Additional unresolved INCOMPLETE: `smoke_test.py` exceeded the 300-second
  limit (300.072 seconds recorded); its child process tree was stopped.

Both faulthandler dumps, emitted at approximately 120 and 240 seconds, locate
the main thread in `ui_audio.py:115` (`preload`), reached through startup feedback
and kill-effect sound preloading while `test_armor_3d_esp_render` constructs its
first window. The preceding calibration-export check had passed. These are
observed stack locations, not an established root cause.

The unchanged `smoke_test.py` had passed 71 explicit assertions in 8.057 seconds
in Full45. Its file SHA-256 is unchanged across the two code revisions:
`f5f5c65ae1137a19c0349da4e112e0914a758475591639f2ac6cab68e6c0a0df`.
This counterevidence does not diagnose the timeout or waive the Full46 result.

The timeout has not been attributed to this repair or to another cause.
Independent diagnosis of fixture isolation is in progress, with no rerun at
this reporting checkpoint. The existing SKIP and INCOMPLETE acceptance
requirements remain open. The zero-FAIL count does not
cancel a timed-out smoke test or establish full success. Focused checks and an
offline aggregate do not remove external firmware/hardware/native acceptance
requirements.
