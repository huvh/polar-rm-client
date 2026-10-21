# Full backend reconstruction verification, 2026-10-21

This is the reconstructed source line, not the lost original 2700ada tree. No
results are inherited from that lost workspace. All commands below are offline
or localhost/fake transports; none qualifies a physical robot or official pair.

## First complete aggregate (retained, not overwritten)

- Source commit: `298af0b5633391b8152b42e841ccb821dee99ecc`.
- Source tree: `b98eff9ee2eb61922cfc3c19d5fd1f53c2483b09`.
- Run ID: `b7c9a53b9a784fafb8ac1c4c96ffe121`.
- Started 2026-10-21 04:20:42 UTC; completed, exit 1.
- 464 registered selected suites plus one derived orphan-settings check:
  **444 PASS, 13 SKIP, 5 INCOMPLETE, 3 FAIL** (465 result entries).
- Start/end source stability: PASS, 823 inputs, identical SHA-256
  `5b2cb3d04f6e849fbcf59f8b0edb9ba90e6810809091bdb4bd79b6641b4b761e`.
- Full JSON, main log and all 930 stdout/stderr files are retained in the
  cumulative recovery archive. A passing focused retry does not erase this run.

Command from repository root:

```sh
PYTHONPATH=. QT_QPA_PLATFORM=offscreen POLAR_DISABLE_LOCAL_CAPTURE=1 \
POLAR_DISABLE_MEDIA_PRELOAD=1 ../client-verification-venv/bin/python -u \
tools/verify_all.py --profile offline \
--json tmp_quality/rebuilt_backend_aggregate.json \
--log-dir tmp_quality/rebuilt_backend_aggregate_logs \
> tmp_quality/rebuilt_backend_aggregate.log 2>&1
```

## Three precise fixture repairs after the first aggregate

1. `tests/dt7_alignment_test.py`: the signed DT7 fixture used only
   `mqtt.connected=True`. It now establishes an inert current client through the
   real connect/subscription acknowledgement callbacks before arming. The
   current-session stage is then set explicitly. Original script: **112 checks
   PASS**. No socket, MQTT publication or physical firmware evidence was added.
2. `tests/test_referee_v2_publish_guard.py`: its AST extraction now includes the
   real manager `_v2_action_admission` helper, package and state dependencies.
   It does not stub the new gate. **26 methods PASS**.
3. `tests/test_v2_air_ui_external.py`: the same real manager helper is bound in
   its AST-based port. The previous error was caught by the UI as a toast, not a
   modal timeout or an invalid production identity decision. **18 methods PASS
   in each of three independent processes**, `GUARD_CALL_COUNT=0` each time.

Only these three test files changed; production source was not relaxed. The
second complete aggregate below supersedes the pending state, not the retained
first-run failure evidence.

## Second complete aggregate

- Tested source commit: `0f58747be4533ece2fc9c873189651db9cf2b368`.
- Tested tree: `e0ff067cf4559e7b43a0f43efd5a948795d55ae8`; clean at start.
- Run ID: `8db50feb2f4a472795dc503bf66eaa52`.
- Started 2026-10-21 04:34:07 UTC, completed at approximately 04:42:30 UTC.
- Same command/environment as above with output stem
  `tmp_quality/rebuilt_backend_aggregate_final`; first outputs remain intact.
- **447 PASS, 13 SKIP, 5 INCOMPLETE, 0 FAIL**, 464 selected registered suites
  plus one derived settings check, 465 result entries. All three first-run
  failures now PASS in the complete run, not only in isolation.
- Start/end source stability: PASS, 823 inputs, identical SHA-256
  `0195840a20c0b95b5ed007408f48a878b23af2572ea1b4d16c651ea724621af0`.
- The runner correctly returns exit 1 and `passed=false` / **NO-GO for the
  selected verification scope**, because SKIP and INCOMPLETE are not PASS.
  Zero FAIL is not an all-prerequisites-complete result.
- CPython 3.12.14, Linux x86_64, PySide6 6.8.2, paho-mqtt 2.1.0. Exact dependency
  versions and selected/not-selected inventories are in the complete JSON.
- Full final JSON, main log and all 930 per-suite stdout/stderr files are archived
  alongside the first run. Subsequent changes are report-only; the archive's
  `stage.json` records the final documentation commit/tree separately from the
  tested source identity above. No production/config/test code changed afterward.

## Verification prerequisites still incomplete

These account for the runner NO-GO, not for unimplemented product capabilities.

- External team CRC implementation and explicitly selected StandardRobot++
  firmware/build fixtures are absent. Skipped cross-checks remain unverified.
- Native libpcap BPF coverage and PowerShell archive-publication execution are
  unavailable here. Static packaging tests are not a Windows release build.
- The legacy firmware patch installation test is excluded from read-only target
  verification; its exclusion remains INCOMPLETE, not PASS.
- Six registered GPU/native-desktop, visual-capture or external-fixture suites
  are outside the offline profile and were not selected.
- Official engine/client end-to-end execution, physical controls, stop latency,
  radio recovery and field qualification remain unverified, independently of
  the offline suite's result.

## Product capabilities not implemented or deliberately unsupported

These are separate from missing verification prerequisites and cannot be fixed
by relabeling skipped tests as passed.

1. The old receiver's complete standalone driver/control initialization,
   pairing and radio-channel setup are not implemented as an official-equivalent
   replacement. Selecting a serial port or ClientId is not hardware pairing.
2. RC150 Windows USB hardware factory, live interface ownership/open/read,
   incremental raw HEVC decoder and main-program/UI integration are **not
   implemented**. This reconstruction deliberately did not restore the old
   fake-only adapter skeleton. Static evidence is not a usable USB transport.
3. Custom map mode remains unsupported because the official public contract and
   native sender disagree about values 4/5. Normal reviewed modes are distinct.
4. Sentry command 6 (paid revival) is rejected: target-specific current quote,
   permission and intervention-fee inclusion are not evidenced by the available
   requester telemetry. Aerial self-state must not substitute for Sentry state.
5. V2 Common/Sentry/paid Map economics are supported only in explicitly bound
   RMUC7v7 contexts. RMUL3v3 and unknown modes are rejected; their price/rule
   contracts have not been implemented from corresponding official evidence.
6. Private DBUS reserved neutral 1024 intentionally remains distinct from the
   official DT7 reserved value 0; the prior qualification-bound adaptation was
   not silently rewritten or claimed wire-identical.

Thus these runs are not a full-green release or a hardware READY declaration.
