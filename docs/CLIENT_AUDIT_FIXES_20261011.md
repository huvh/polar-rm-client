# Client audit repairs and branch readiness

Baseline: `deepseekv4flash后端` at `841c2db88c30a9cf4da573b01bcd0e14409c9e93`.

## Scope

This change repairs the reported latest-branch safety, configuration, rendering-lifecycle and packaging defects. It does not add targeting/firing capabilities, claim RoboMaster protocol V2 support, merge branches, or change the default branch. `gestalt-lab` is deliberately excluded at the owner's request.

### Repairs

- Transport: immediate neutral writes during emergency stop; controller release on disable and retry after failure; TCP EOF/reconnect and nonblocking receive; clear old input/telemetry on endpoint or identity changes; preserve latched emergency stop through scenario reload; best-effort local shutdown despite network errors.
- Protocol/video: map field meanings and conservative three-second rate gate; decimal extension IDs parsed consistently; V/S key configuration consistency; Annex-B boundary recognition; completed UDP frame order, duplicate and restart handling; explicit missing decoder dependency errors.
- UI/state: full red/blue identity before connecting; consistent alliance source; CPU fallback modal restoration; installation-fault display; unified economy display; held observation provenance retained; warning toast compatibility; guarded resource cleanup.
- Configuration: validate candidates before applying/importing, atomic writes and recovery backups, stable profile identity, explicit startup preferences, preserve saved endpoints, failed-save retries, rollback runtime mode/role/bindings and keep output stopped.
- Build/tools: include protocol JSON data, validate packaged contracts, move mutable sounds outside immutable resources with safe migration, fix launcher quoting, validate FFmpeg integrity before executing it, forward explicit firmware targets, distinguish PASS/SKIP/INCOMPLETE, make dry-run non-mutating, snapshot-based revert with conflict protection.
- Tests: discover all smoke functions, make optional source video-fixture checks explicit (required for releases), add three isolated regression suites, preserve failed build logs. The frozen API baseline only adds two new method entries; existing entries are unchanged.

## Verification in the available Linux environment

- `python3 tests/test_build_safety_regressions.py`: 22 tests passed.
- `python3 tests/test_ui_state_regressions.py`: 30 tests passed.
- `python3 tests/test_transport_safety_regressions.py`: 36 tests passed.
- Existing `polar_link_test.py`, `polar_spec_test.py`, `polar_bridge_test.py`: passed.
- Existing `backend_protocol_test.py`: **INCOMPLETE, exit 77**. 189 checks passed; three decoder tests explicitly skipped because `cv2` is unavailable. This is not a full suite pass.
- All 211 Python files parsed successfully; `git diff --check` passed.
- Independent H264 diagnostic: old/new recovery output was byte-identical for the existing fixture; system FFmpeg decoded 60 JPEG frames. This does not validate production OpenCV display, performance, or all packet-loss cases.

The isolated suites use stubs/AST-isolated methods and temporary data. They do not establish physical stopping behavior or whole-application acceptance.

## Remaining acceptance work

Run the full Windows/PySide6 smoke and API-freeze checks, packaged startup from paths containing spaces, real GPU fallback/recovery, production OpenCV video decoding and sustained 60fps tests, and supervised non-actuating hardware-link checks. Test actuator stop behavior only in an appropriately controlled physical setup.

Protocol V2 remains explicitly unsupported rather than silently treated as V1.3.1. Unknown map roles use a conservative three-second interval. TCP bridge authentication/network isolation remains a deployment decision; no system/network permissions were changed. UDP's maximum packet size remains permissive. Dependency pinning and a complete CI pipeline are not supplied by this patch.

Firmware tools without a compatible snapshot refuse old destructive revert. Missing prerequisites in dry-run are reported without installation. Checks requiring mutable firmware fixtures remain INCOMPLETE under read-only verification; no complete firmware GO claim is made.

## Branch recommendation

Remote heads were checked again before publication. The history is:

`main` -> `fix/clickgui-targethud-v2` -> `qwen3.8repair` -> `deepseekv4flash后端`.

The latest branch contains all commits from those three older branches (167, 136 and 110 commits ahead respectively). There is no need to merge the older branches back into it merely to collect their history. `gestalt-lab` has unrelated history and is excluded.

Recommended sequence: review and validate this repair branch against `deepseekv4flash后端`; after acceptance, promote that line into `main` using the intended history-preserving repository workflow. Do not overwrite `main` with copied files or force-push history. The ancestry supports it as the new mainline candidate; outstanding runtime/hardware acceptance means it is not yet a release certification.
