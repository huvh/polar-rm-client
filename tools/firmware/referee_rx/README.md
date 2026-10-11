# Referee typed payload boundary

`apply_referee_rx.py` is called by `km_link.apply_referee` after its `HostKmFeed`
handoff. It patches only `referee_data_solve`, leaving framing and CRC validation
with the existing upstream FIFO receiver.

- Every fixed-size active typed copy requires exactly `sizeof(the declared type)`.
- `0x0301` accepts the six-byte interaction prefix and 0–112 user bytes (6–118
  total), copies only the received bytes, and clears the unused destination tail.
  This checks the outer interaction envelope, not each interactive subcommand.
- `0x0311` delegates to the existing acceptance-returning `HostKmFeed` validator;
  it preserves canonical 26–30-byte KM packets and never forces a 30-byte length.
- Rejected and unknown commands do not change payloads, shared receive header,
  receive count, or online freshness. The successful path keeps timeout reset
  and receive-count increment semantics. A null frame is rejected.

## Source and limits

The matched public reference is
[StandardRobot++](https://gitee.com/SMBU-POLARBEAR/StandardRobotpp/tree/2722e0d2daba6113c86544d0c6d7918672669601),
commit `2722e0d2daba6113c86544d0c6d7918672669601`, specifically
`application/referee/referee.c`, `referee.h`, and `protocol.h`.
External source is not vendored here. The reference is not proof of the firmware
on any deployed board. This helper does not establish DMA, IRQ, UART wiring,
board ABI/toolchain, or hardware qualification. Its input must already be a
complete CRC-validated frame: the existing function signature has no buffer size
and cannot independently prove physical input length.

## Test

```
POLAR_REFEREE_REFERENCE=/path/to/read-only/StandardRobotpp \
  python tools/firmware/referee_rx/test_referee_rx.py
```

The harness includes the real payload declarations and compiles the extracted,
patched dispatch plus this project's canonical KM validator/receiver. No external
build script or complete external firmware is executed. It checks all 24 active
cases (22 fixed, interaction, KM), every valid interaction length, KM sizes 26–30,
malformed sizes/content, payload preservation, header/counter/freshness
preservation, timeout behavior, and installer idempotence. It uses a minimal
hardware-free header shim and verifies key packed sizes. Missing source/compiler
prints `SKIP:` and exits 77 when the script is run directly, never a claimed pass.
The reference must be explicitly selected with `POLAR_REFEREE_REFERENCE`; no
machine-specific external checkout is selected automatically. Default sanitizers are undefined/bounds;
`POLAR_REFEREE_SANITIZERS=address,undefined,bounds` additionally enables ASan.

In ptrace-based execution sandboxes, LeakSanitizer itself may fail. The checked
ASan run used `ASAN_OPTIONS=detect_leaks=0` (address checks remain enabled).
