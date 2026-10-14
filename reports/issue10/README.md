# Issue 10 repair evidence — 2026-10-14

Repository: lulunomaro/polar-rm-client. Baseline: bd2e590b43b9cfecef61b09f0577a2ba0181578e.
Firmware reference: StandardRobot++ 2722e0d2daba6113c86544d0c6d7918672669601.

## Implemented

- Explicit physical-controller angle RX and official player-end serial TX, separate from existing keyboard/mouse egress.
- Fixed profile: six little-endian float32 radians, 0x0302/30-byte payload, validated frame CRC and source bounds, zero reserved tail.
- Latest-only forwarding, maximum 30 Hz, independent 300 ms freshness, explicit process-local arming and loss/recovery inhibition.
- Source-guarded firmware patch: correct 0x0302 source, atomic six-axis snapshot, independent timeout, existing arm SAFE gate, sender overread and cadence corrections.
- Setup, wiring, payload and safety documentation; new suites included in tools/verify_all.py.

## Verified offline

Final focused working-tree checks: **37 Python tests PASS; 5 compiled firmware host tests PASS**. Logs are adjacent. Firmware tests exercise the actual reference dispatch and arm FOLLOW branch in disposable copies; they are not an ARM image or a hardware test.

Commands:

```sh
python3 -m unittest discover -s tests -p 'test_controller_angle*.py'
POLAR_REFEREE_REFERENCE=/path/to/exact/reference python3 tools/firmware/controller_angle/test_controller_angle.py
git diff --check
```

## Aggregate remains NO-GO

The earlier aggregate snapshot returned **33 PASS / 21 FAIL / 15 INCOMPLETE (69 checks)**. Do not interpret focused success as a complete regression pass. The aggregate was captured during final hardening; the focused suites were rerun after the final edits.

All 21 failures reproduce on clean baseline: 20 missing PySide6, one missing paho. See baseline_comparison/README.md, summary.json and paired logs. The 15 incomplete checks cover missing cv2, optional CRC reference and prepared firmware/vendor fixtures or a read-only exclusion. Dependency-enabled GUI/MQTT rerun is pending approval; no installation workaround was used.

## Remaining acceptance gates

- Dependency-enabled GUI/API/MQTT regression and actual interface rendering.
- ARM firmware build and board UART/DMA/pin configuration.
- Physical controller -> client -> official player-end -> image transmission -> robot integration, including corrupted frames, unplugging and recovery while unrelated referee traffic continues.
- Verify no regression of existing keyboard/mouse delivery on hardware.
- Mechanical safety assessment: existing SAFE inhibits output; it is not a validated gravity hold or brake for a loaded arm. Support the mechanism and inhibit actuators for initial bench verification.

No hardware was actuated, no main-branch merge was performed, and Issue 10 remains open pending these gates.
