# Deferred elimination preview close guard

A queued six-event preview could continue actual presentation-state updates after window close admission. In an inert actual-method reproduction, closing after the first event still allowed five later callbacks to raise kill/streak counters and request rendering. No native playback or wire output was established.

The repair checks the current existing WindowLifecycleController.closing flag at callback delivery. Standalone preview hosts without that owner retain existing behavior; real windows attach it before preview actions. Generic combat acceptance is unchanged. This does not introduce profile epochs, cancel scheduled timers, or establish a native Qt lifetime policy.

Frozen source SHA256: bf3301a9243995e98bf166d53f8909e76b3835ba6b5c2307b50e6a3216120e94.
New test SHA256: 17e5eefc41fc0999091554635bd93d46bceced170c8b2642d0004c37ee57182e.

Independent external validation: 28 focused tests, original three probes and eight additional controls pass. Baseline new eleven reproduce eight assertion/subtest failures with zero errors; nine negative controls reject without errors. These overlapping selections are not additive unique coverage. Actual preview/acceptance/close AST and pure lifecycle code execute with inert collaborators, without Qt/GL/facade/manager/spin imports.

Controls preserve healthy event identity/staggering, no-owner compatibility, delivery-time owner replacement, reentrant close admission, ordinary/SystemExit identity and scheduling-failure prefixes. Existing audio-replay assertions are unchanged. An initial mutation run exposed a missing prefix precondition; the new test was corrected before freezing, all mutants rerun, and original counterevidence retained locally. No raw logs published.

Reproduce: python -m unittest discover -s tests -p test_deferred_preview_close.py

This source is newer than full42 (406 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL at public8b3cfc1). Aggregate qualification of this repair is pending. Overall remains NO-GO: authentic external references, disposable installer qualification, native Windows/device acceptance and historical timing causes remain open.

Integrated independent validation also passed 28 focused tests and eight controls at the exact frozen hashes; API freeze and static gates pass.

## Completed full43 qualification

**407 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL**, selected offline scope remains **NO-GO**. Run `1a875329fcb94b0c918ef5b94941380f`, clean local code `e21b7f6c42c4faabac1f14dc855d0695ae9a07e0`, public code `7c5f61113ab02b678a59c7bb077767116d90d84f`, identical tree `faa30c897b0ce467a9df5e06954cc57274f58b7e`.

All 762 declared inputs retain start/end fingerprint `e31e3848576fa09fca799f6d5b6a2f2da89ddb61a0cb1388b312f0b5d620876d`. New preview module passes all eleven methods. Result, clean provenance and source stability independently checked. Counts are suites/checks, not unique methods; start/end scope excludes external assets/dependencies and restored transient edits.

Four incomplete prerequisites remain authentic team CRC, complete firmware baseline, authentic vendor type dump and separate disposable legacy installer qualification. Windows/GPU/audio/video/serial/robot/portable acceptance and historical timeout causation remain unresolved. This documentation-only follow-up does not change tested code. Prior failed/interrupted records retained; no raw logs uploaded.
