# Dependency-enabled independent regression comparison

Baseline: clean `bd2e590b43b9cfecef61b09f0577a2ba0181578e` export.
Issue 10 target: `7d8bf919d9ac99e7b2d2a2eda488257ddba4e068`.
Interpreter: `/tmp/polar-angle-qa-venv/bin/python`, with the user-approved PySide6, paho-mqtt and pyserial dependencies. No additional packages were installed by this review.

## Result

The dependency-enabled aggregate remains **NO-GO: 48 PASS, 4 FAIL, 17 INCOMPLETE / 69 checks**. The four remaining failures were each rerun on baseline and Issue 10 under identical conditions, with `QT_QPA_PLATFORM=offscreen`, `PYTHONFAULTHANDLER=1`, capture/media preload disabled, and isolated user data.

| Suite | Baseline | Issue 10 | Verified failing stage |
|---|---:|---:|---|
| Student frontend | -11 | -11 | Native segmentation fault while constructing `QSoundEffect` |
| Polar startup | -11 | -11 | Same native audio initialization crash |
| API freeze | -11 | -11 | Same crash before collecting/comparing the window API |
| BuffTimeline | 1 | 1 | Pixel child exits -11; three pixel/visibility assertions cannot complete |

The directly rerun BuffTimeline `--pixel-probe` child also crashes at the same point on both trees. Faulthandler identifies `rm_client/ui_audio.py:54`, `effect = QSoundEffect(self)`, called from audio initialization at line 214 and `PolarRMWindow.__init__` at line 414. This file is unchanged between baseline and Issue 10. PipeWire `client.conf` errors and an unsupported offscreen `QOpenGLWidget` warning precede the crash. These observations identify the failing native initialization stage; they do not prove a specific Qt, audio, or display subsystem fix.

BuffTimeline's earlier logical checks execute before its child crashes. Actual window/pixel acceptance and the API snapshot comparison remain blocked, not passed. Fontconfig also emits cache warnings, but the recorded terminating failure is the native audio crash.

## Remaining incomplete coverage

- `backend_protocol_test` still skips video-dependent cases: cv2 and numpy are absent from this isolated interpreter.
- The optional third-party CRC reference script is unavailable.
- Prepared firmware fixtures and vendor reference dumps are unavailable, and the aggregate intentionally excludes the legacy mutating firmware check.
- This aggregate invocation omitted `POLAR_REFEREE_REFERENCE`, so the angle-firmware and referee-dispatch reference tests are recorded as incomplete here. Their separately executed source-pinned passes must be reported separately, rather than changing this aggregate log.

## Conclusion

No new Issue 10-caused failure was observed in this matched comparison. Most dependency-blocked suites now execute and pass in the aggregate, including referee MQTT integration and the DT7 C-route pitfalls suite. The remaining four failures reproduce on the clean baseline at the same native audio initialization stage. No runtime/UI fixes, test weakening, API rebaseline, hardware operation, or further dependency installation was performed.

All paired full logs and command outcomes are retained beside `summary.json`. Physical serial operation, official player-end delivery, ARM firmware builds, and robot/mechanical qualification remain unverified.
