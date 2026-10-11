# Serial receiver integration contract

The exact team source was audited read-only at StandardRobot++
`2722e0d2daba6113c86544d0c6d7918672669601`. Patches were applied only to disposable
copies. Host-compiled parser tests are not a target firmware build, UART wiring
validation, DMA integration, or hardware qualification.

## A5 / PRM1 receive path

- `HostKmFeedBytes` consumes arbitrary chunks from one serialized video byte stream.
  Its static parser is not reentrant: use one producer and immutable input bytes;
  never combine independent UART streams or write its mailbox via DMA.
- Video framing buffer is 309 bytes (300-byte payload + 9). Length arithmetic is
  bounded before addition. CRC8 covers the five-byte header; CRC16 covers the whole
  frame. Bad candidates discard one byte and retain suffixes. CRC-valid outer frames
  are consumed whole, including ignored commands, so embedded 0311 cannot inject
  through a valid 0310 body. Partial candidates expire after an inter-call gap >300 ms.
- Command 0311 accepts PRM1/version1/kind3 KM payloads of 26..30 bytes, button bits
  0..2, flag bit0 only, zero reserved/padding. Truncated, oversized or malformed typed
  commands do not refresh freshness. Accepted commands zero-fill the mailbox.
  `alive=0` is accepted but inert. Other PRM1 kinds do not extend KM freshness.
- `HostKmFeed` returns acceptance (1/0). It is a trusted **complete, CRC-validated**
  frame handoff. The actual referee FIFO verifies both CRCs and complete frame length
  before calling its dispatcher. The generated dispatcher passes actual payload size
  and validates typed sizes before changing data/freshness.
- Mailbox publication and snapshots (payload/time/count) use short save/disable/restore
  Cortex-M CMSIS PRIMASK critical sections. Nested masks are restored exactly. The
  actual source include chain supplies CMSIS through main.h and STM32 HAL. Other
  architectures must explicitly override both critical macros with equivalent
  exclusion and compiler memory barriers; no silent no-op fallback exists.
- `km_rx` counts accepted canonical KM payloads; `km_ok` counts bounded CRC-valid
  outer frames. Key/fire masks and physical RC arbitration are preserved. No-key
  receiver frames now actually clear the driver mouse ledger (old patch probe skipped it).

## USB 5A receive path

The audited USB_Receive wrapper only rearmed CDC; it did not return received bytes.
The old task scanned a presumed 150-byte buffer, performed unchecked CRC/copies,
and could reuse stale/partial bytes. The generated host_bridge patch replaces that
path and updates `Src/usbd_cdc_if.c` as one required integration bundle:

- Only actual CDC OUT callback Buf/Len bytes enter a 512-byte bounded queue. Each
  byte retains callback arrival time. Callback copies bytes, rearms the same endpoint,
  and never parses or actuates. No UART/pin/DMA choices are changed.
- Queue producer/consumer and command publication preserve/restore PRIMASK.
  Overflow drops the overflowing chunk and queued prefix, increments an epoch, and
  invalidates task-held partial candidates. CDC init/deinit similarly reset ingress.
  Reset preserves the monotonic timestamp replay barrier; disconnect is not a command
  to stop actuators. Existing task freshness policies remain responsible for expiry.
- Task parsing uses a 261-byte stream buffer and actual queued bytes, with complete
  header/CRC/body checks before dispatch. Unknown valid frames are skipped whole.
  Every supported command requires exact `sizeof` wire length. Chassis param0 bit0
  remains the existing gimbal request; other reserved bits/bytes must be zero.
  RobotCmd's nine and PID's five binary32 fields reject NaN/Inf without new tuning limits.
- Queue age, total candidate age and final commit age are bounded to 150 ms. Final
  publication rechecks epoch/age under exclusion, including preemption/reset races.
- Timestamp is read with memcpy (no unaligned uint32 pointer). **Before copying**, a
  recognized accepted frame must have timestamp strictly greater than the last accepted
  timestamp. Initial zero, duplicates, backwards timestamps and rollover fail closed.
  Unknown/rejected frames cannot advance the replay barrier or control freshness.
- Budget is 150 dequeued bytes per task call; parsing stays outside ISR except short
  queue and publication critical sections. Buffer/counter memory is static (~3 KB).

## Hardware still unbound

Video-transmitter robot link: 921600 baud, 8N1. Regular referee link: separate 115200.
No UART instance/pin/DMA channel/interrupt is chosen or enabled. Route only verified
video-UART bytes after board ownership identifies the binding. 0311 uplink is at
most 30 bytes /75 Hz; 0310 downlink at most 300 bytes /50 Hz. No 0310 sender is added.

Before deployment: build supported target configurations; verify memory budgets,
actual callback/context timing and all critical sections; then separately qualify
USB/UART/DMA and physical RC priority with actuation disabled.

## Offline regression

- `python tools/firmware/km_link/test_serial_parsers_portable.py`
  13 portable C tests, including 100,000 ASan/UBSan random-input iterations.
- `python tools/firmware/host_bridge/test_usb_receiver_portable.py <prepared-copy>`
  Real source layouts and official CRC, emitted queue/parser, 15 tests including
  fragmentation, typed sizes, replay, nonfinite data, overflow/reset/preemption,
  stale/slow assembly, masks, idempotence, and 30,000 ASan/UBSan random iterations.
- `POLAR_REFEREE_REFERENCE=<read-only-reference> python tools/firmware/referee_rx/test_referee_rx.py`
  runs the actual-source typed dispatcher regressions.
- Existing `test_km_link.py` checks all five arbitration policies and the fire-mask
  option against prepared source. GCC host execution also works when the TU uses
  firmware integer typedefs instead of including conflicting host stdint typedefs.

LeakSanitizer is disabled under the executor's ptrace sandbox; ASan and UBSan remain
active. No parser dynamic allocation is used. No upstream build scripts are run.
