# Serial protocol hardening (2026-10-11)

This is a bounded repair of reproducible framing, payload-validation and stream-lifecycle defects. It is not a claim that every possible protocol or hardware defect has been eliminated.

## Changes

- Official A5 frames: reject payload lengths above 300 before buffering; retain genuine partial headers, consume noise, verify CRC8/CRC16, and preserve sequence wrap.
- Referee UART writes: validate complete frames even on the raw write path; reject video-only 0x0310/0x0311, malformed command IDs and payloads. Short writes close the failed stream rather than continue an ambiguous frame.
- Team 0x5A: reject wrong declared sizes for known segments and nonfinite telemetry/control values; invalid spin values cannot wrap into ON. Invalid driving intents neutralize the current stream and latch the existing stop gate.
- Serial/TCP lifecycle: bounded write deadlines, nonblocking control RX, old-worker restart barrier, owned intent snapshots, atomic clear/TX ordering, stale state discard on reconnect, and no stale RC append after backpressure.
- DT7/custom controller: truncated-frame rejection, explicit wire-size bounds, validated scalar layouts/IDs/versions, and consistent key overflow reporting. Existing neutral-release behavior and safety authorization remain intact.
- PRM1 kind 3: canonical 26–30-byte KM payload validation; reserved bytes/bits must be zero. Firmware parser accepts valid variable lengths, publishes coherent payload/freshness snapshots, and never treats a valid outer frame's interior as another command.
- Actual team USB ingress: replace the fictitious fixed-size polling buffer with real CDC callback bytes, a bounded queue, epoch resets, typed CRC-checked parsing, replay rejection before publication, finite-field checks and bounded candidate age. Callback/reset/preemption races and overflow are covered by compiled regression tests.
- Actual referee dispatch: require exact typed sizes before copying or refreshing metadata; bound the variable 0x0301 envelope and validate canonical 0x0311 KM handoff.
- CustomByteBlock is limited to 300 bytes; PDL1 declared size must contain its complete 76-byte fixed header.

No new 0x0310 transmitter, UART pin map, DMA binding, automatic control authorization, firmware flashing, or hardware traffic is introduced.

## Route boundaries

- Referee User UART: 115200, 8N1.
- Robot video-transmitter UART: 921600, 8N1. Client uplink CustomControl maps to 0x0311 (at most 30 bytes, 75 Hz); robot downlink 0x0310 maps to CustomByteBlock (at most 300 bytes, 50 Hz).
- MQTT/Protobuf client messages and UDP video remain separate from the independent team 0x5A USB/TCP route.
- The board's actual 921600 driver, wiring and callback binding remain unverified. A client receiver does not prove a matching board transmitter exists.

See [the portable firmware integration contract](../tools/firmware/km_link/SERIAL_INTEGRATION.md).

## Verification and limits

The focused regression suites (11 codec/tooling, 19 lifecycle, 15 controller, 13 portable KM C, 15 actual-source USB C and 8 API portability tests, plus the actual-source referee dispatch harness) cover CRC vectors, sequence wrap, every split point, seeded random chunking, malformed lengths, type validation, fake short writes/disconnects/reconnect barriers, invalid intents and backpressure. The portable C suite compiles the actual emitted parser and exercises 100,000 ASan/UBSan random-input iterations, with LeakSanitizer disabled under ptrace.

Run:

```
python tests/test_serial_codec_regressions.py
python tests/test_serial_lifecycle_regressions.py
python tests/test_controller_frame_regressions.py
python tools/firmware/km_link/test_serial_parsers_portable.py
python tests/test_transport_safety_regressions.py
python tools/verify_all.py
```

With real GUI/video/communication dependencies installed, unchanged repository assets restored, and the matching public firmware/CRC references selected explicitly, the final aggregate reports **65 passing, 0 failing, 2 incomplete suites out of 67**. The aggregate correctly remains **NO-GO**: missing vendor evidence and the excluded legacy installation test are not passes.

- All available GUI, actual startup/wallpaper, HUD, API-freeze, serial, MQTT, video, actual-header C, USB/referee parser and preparation checks pass.
- Referee integration passes 263 checks including real localhost MQTT; student frontend passes 90; DT7 alignment passes 111; team CRC/polar-link passes 81.
- Real-header compilation, all six KM configurations, eight key-ledger behavior groups, gimbal and DBUS checks pass against the explicitly prepared team tree.
- Three grounded client test fixes retain their assertions: map tests use category field 3 and marking-mode field 6, matching the unchanged V1.3.1 codec; missing-setting fixtures remove the actual list entry and assert absence; API-freeze normalizes only three identified inherited Qt-provider differences and WindowsPath/PosixPath representation. Eight negative regressions plus an actual application method-removal self-test preserve strict application API detection. The API baseline was not regenerated.
- Firmware test fixtures now include actual CDC planning inputs and firmware integer typedefs, rather than incompatible host duplicates. Byte-for-byte restoration, no-installer dry runs and negative behavior assertions remain intact. The preparation script resolves sibling file_guard imports for isolated importlib callers.

Earlier missing packages and assets were restored, and actual failures were repaired and rerun, not converted into successful skips. The initial dependency-complete run had 51 passing / 0 failing / 13 incomplete out of 64; source recovery and additional real-source checks produce the final result above. No test outcome qualifies a real robot for use.

## External evidence and remaining gaps

The first run's 13 incomplete suites were missing or unselected inputs in the cloud checkout, not nonexistent C-board materials. Matching public references have now been recovered. Eleven of those checks can run against the explicitly selected, prepared team tree; two require separate evidence/workflows.

| Check | Evidence and status after source recovery | Remaining limit / reproduction |
| --- | --- | --- |
| Team CRC cross-check | Actual Serial_Port_Assistant Python CRC selected explicitly; 81 polar-link checks pass | `POLAR_TEAM_CRC_REFERENCE=/path/to/Serial_Port_Assistant/lib/CRC8_CRC16.py python tests/polar_link_test.py`; an explicitly missing path fails. |
| Real firmware headers | Prepared matching StandardRobot++ headers; real-header compile passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/test_patch_real_headers.py`; host compilation is not a Keil/board build. |
| Legacy patch behavior | **INCOMPLETE**: intentionally excluded from read-only aggregate because it installs an old fixture | Run `POLAR_FIRMWARE_ROOT=/path/to/disposable/copy python tools/firmware/test_patch_logic.py` separately under its documented workflow. Preserve/inspect source diffs; do not disable protection on a working board project. Existing current-parser fuzz/behavior suites are supplementary, not a claim this legacy test ran. |
| Host bridge | Actual prepared USB/chassis headers; test passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/host_bridge/test_host_bridge.py`; real hardware stop behavior remains unqualified. |
| Motion feedback | Actual prepared kinematics/USB headers; test passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/motion_feedback/test_motion_feedback.py`; robot-specific parameters require board qualification. |
| Gimbal requests | Actual-header compile and truth-table tests pass | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/gimbal_host/test_gimbal_host.py`; no physical gimbal activation was tested. |
| RC key ledger | Actual receiver sources, eight behavior groups pass | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/host_bridge/test_rc_key_ledger.py`; actual ISR timing and physical RC priority still need bench validation. |
| DT7 firmware decoding | Actual remote_control.c decode comparison passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/dt7_link/test_dbus_frame_vs_firmware.py`; comparison does not choose a live port. |
| PRM1 layout | Installed actual host_km_link.h offset probe passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/km_link/test_km_payload_layout.py`; target ABI/linker remains a separate build step. |
| KM arbitration/fire masks | Five policies plus fire-mask configuration pass | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/firmware/km_link/test_km_link.py`; existing physical RC and firing restrictions remain. |
| Custom-controller CRC | Actual team C CRC acceptance passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/dt7_link/test_cc_link.py`. |
| DT7 vendor anchors | **INCOMPLETE**: matching vendor `dump.cs` fixture is absent | Supply the matching authorized vendor fixture in the documented location and rerun `tools/dt7_link/test_dt7_link.py`. Internal frames/CRC/safety/release assertions do not prove inferred vendor command IDs. |
| C-route UI cross-check | Actual selected firmware source; offline cross-check passes | `POLAR_FIRMWARE_ROOT=/path/to/prepared/tree python tools/dt7_link/test_dt7_ui_selftest.py`; no physical X-probe was sent. |

Full reproduction: set `POLAR_TEAM_CRC_REFERENCE` to the reviewed CRC file, `POLAR_REFEREE_REFERENCE` to the clean matching reference, then run `python tools/verify_all.py --firmware /path/to/prepared/StandardRobotpp`. Preparation must occur on a disposable copy, using this repository's preparation tool rather than downloaded upstream build scripts. Linux host fixtures use the actual firmware integer typedefs, avoiding incompatible duplicate glibc typedefs without changing board source.

A disconnect, short write or timestamp rollover cannot guarantee physical stopping if the deployed firmware retains its last actuator command. Best-effort neutral frames are not an acknowledgement. A separately verified firmware watchdog and physical operator stop path are mandatory. The KM parser's stale-frame/mailbox checks do not establish a watchdog for every other control path. The emitted outer USB receiver is now tested against actual public source layouts and CRC code. Target compiler/linker integration, interrupt latency, memory budgets, all board configurations, DMA ownership and physical RC priority still require validation on the actual board project with actuation disabled.

Reconnect discards buffered frames and cached driving intent. Existing manager input clearing/authorization remains in place. This does not add a new universal MATCH_ARMED gate to the existing team-link settings model: fresh state can still express an already-enabled spin/gimbal setting under the preexisting permissions.

## Recovered source provenance

The exact team source referenced by this repository was retrieved and inspected. These public revisions are not evidence of the firmware deployed on a particular robot. Patches and host tests use disposable copies; original references remain unchanged. No upstream build scripts or hardware interfaces were run.

- [StandardRobot++](https://gitee.com/SMBU-POLARBEAR/StandardRobotpp), `2722e0d2daba6113c86544d0c6d7918672669601`. Root MIT; imported DJI files retain their own notices.
- [Serial_Port_Assistant](https://gitee.com/SMBU-POLARBEAR/Serial_Port_Assistant), `af97031fb8dde62e15f2f33e686b0d35234a13a4`. Root MIT. Python CRC reference SHA256 `f46cce6382bbbae2056b81538c1de5c06a93c2199b4d07784d9bc551509ed2f5`. The explicit `POLAR_TEAM_CRC_REFERENCE` path avoids relying on a developer-specific sibling directory.
- [Official C-board examples](https://github.com/RoboMaster/Development-Board-C-Examples), `59d12b1adcd321dbf1f9e9166aef5eb95ab657bf`, GPL-3.0-or-later. These supplement, rather than replace, the team tree.
- [Official C-board user manual](https://rm-static.djicdn.com/tem/35228/RoboMaster%20%20%E5%BC%80%E5%8F%91%E6%9D%BF%20C%20%E5%9E%8B%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.pdf), v1.0 (2020.01), SHA256 `04353087264c7de85f163359c1d659c4d6b89604a0477628725c30c188f9bedb`. Casing UART1 means STM32 UART6; casing UART2 means STM32 UART1. Team source initializes UART1/6 at 115200 and UART3 at 100000; no 921600 binding is supplied.

Only source links, revision identifiers and our patch/test code are committed. Upstream trees and the manual are not vendored or relicensed. USB integration now includes `Src/usbd_cdc_if.c` in the preparation/restore ownership bundle.
