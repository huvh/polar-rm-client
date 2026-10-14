# Physical controller angles: firmware contract and offline patch

This patch is for the **StandardRobot++ engineer controller and engineer arm**
at [`2722e0d2daba6113c86544d0c6d7918672669601`](https://gitee.com/SMBU-POLARBEAR/StandardRobotpp/tree/2722e0d2daba6113c86544d0c6d7918672669601),
for [polar-rm-client issue #10](https://github.com/lulunomaro/polar-rm-client/issues/10).
It is an offline source installer, not a firmware flasher or hardware qualification.
It does not select a robot profile, change any pin/UART binding, or enable outputs.

## Exact end-to-end contract

Physical engineer controller → client angle RX → client angle TX → official
player-client controller serial input → video link → robot `0x0302` dispatcher →
`GetCustomControllerAngles()` → engineer-arm FOLLOW reference.

- Outer frame: the existing `0xA5` referee frame, header CRC8, command `0x0302`,
  exactly 30 payload bytes, and frame CRC16. Keep the existing frame parser/CRC
  checks in front of `referee_data_solve`; the typed dispatcher is not itself a
  byte-stream framing parser.
- Bytes 0–23: six little-endian IEEE-754 binary32 values, J0 through J5, in radians.
  No degrees conversion, Euler-angle interpretation, axis permutation, or sign
  change belongs in the PC relay.
- Bytes 24–29: reserved, emitted as zero by the repaired sender and PC relay. The
  receiver ignores these bytes for compatibility with the old sender. They are
  not a state word, CRC, or seventh joint.
- `0x0309` is the opposite-direction robot-to-controller data. It cannot update
  the angle mailbox. `0x0306` keyboard/mouse input and the `0x0311` PRM1 kind-3
  keyboard/mouse path are separate and retain their existing behavior.
- Transport uses at most 30 frames/s. The physical sender's existing 34 ms period
  is now actually enforced; PC forwarding is independently rate-limited.

Direction and rate are stated in the official DJI [referee protocol V1.8.0](https://bbs-web-static.robomaster.com/ac9ea0bb2550481fa6b9090fbe0597501764044473591/RoboMaster%20%E8%A3%81%E5%88%A4%E7%B3%BB%E7%BB%9F%E4%B8%B2%E5%8F%A3%E5%8D%8F%E8%AE%AE%E9%99%84%E5%BD%95%20V1.8.0%EF%BC%8820250418%EF%BC%89.pdf),
command table and section 4.1, tables 4-1/4-2. Current event equipment must still
be checked against its applicable season protocol and actual video-UART routing.

## Source-backed coordinates and limits

In the pinned firmware, `application/custom_controller/custom_controller_engineer.c`
lines 160–185 transform measured motor positions using configured zero offsets,
motor direction, accumulated turns, and reduction ratio. Lines 190–211 clamp
J0–J3, clamp the two virtual joints, then transmit:

- J4 = virtual J4 + virtual J5
- J5 = −virtual J4 + virtual J5

The source limits are defined in `application/robot_param_engineer_controller.h`
lines 60–79. The engineer source really applies these clamps; these are not
inferred mechanical limits. Both client and firmware validate the same pinned
source profile, with an absolute `1e-5` rad tolerance for float32 rounding:

| Wire value | Accepted source range, before rounding tolerance |
| --- | --- |
| J0 | −2π to +2π |
| J1 | −1.10 to +1.20 |
| J2 | −2.50 to 0 |
| J3 | −4π to +4π |
| J4 | −4.5π to +4.5π |
| J5 | −4.5π to +4.5π |

The final two bounds follow from virtual J4 in ±π/2 and virtual J5 in ±4π.
NaN, infinity, out-of-profile values, and non-30-byte payloads are rejected before
updating angle data or age. This profile is not a universal custom-controller
schema. A different controller requires a separately reviewed source profile,
matching client/firmware validation, and direction/calibration qualification.

The arm's existing mapping remains in
`application/mechanical_arm/mechanical_arm_engineer.c`, original lines 486–511:
J0–J3 use the arm's own limits; J4/J5 are converted back to virtual joint values,
arm midpoint offsets are added, virtual J4 is constrained, and the coupled motor
targets are reconstructed. The patch does not recalibrate these values. Its
half-before-sum/difference form avoids an unnecessary intermediate overflow.

## Freshness, loss, and recovery

- The angle mailbox is invalid at startup and is reset by
  `init_referee_struct_data()`.
- Only a valid `0x0302` six-angle payload updates its own receive timestamp and
  validity. General referee frames, `0x0309`, and valid `0x0311` KM traffic cannot
  refresh it. Rejected angle frames also cannot refresh it.
- Data is fresh for **age < 300 ms**, using unsigned 32-bit elapsed-time arithmetic.
  Exactly 300 ms is stale. Observed expiry latches invalid, preventing later tick
  wrap from reviving old data. The 300 ms value is an explicit software watchdog
  default consistent with the existing referee/KM budget, not measured link safety.
- `GetCustomControllerAngles(float[6])` returns one coherent six-axis snapshot
  under a short interrupt-mask critical section. When unavailable, it returns
  false and leaves the caller's output untouched. The old scalar getter now uses
  the same mailbox, bounds-checks the index, and returns zero when unavailable;
  control code must use the boolean snapshot API rather than interpret zero as
  validity. The legacy raw-payload pointer now points to `0x0302`, but conveys no
  freshness and is not used for motor control.
- FOLLOW rechecks freshness when consuming the snapshot and immediately before
  producing motor output. On startup/expiry it enters the existing
  `MECHANICAL_ARM_SAFE` output path instead of applying a stale target.
- The next valid frame makes the mailbox available. FOLLOW can resume only when
  the existing DT7-online, mode-switch, initialization, and latched-error gates
  allow it. Existing J0–J2 jump detection still rejects jumps over 1.5 rad; RX does
  not clear that or any other error.

**SAFE here is the firmware's existing motor-output inhibition. It is not a
verified gravity-safe hold or emergency-braking strategy.** A loaded arm can
require mechanical support or a different board-approved loss policy. Qualify
that policy, actual task scheduling, the physical UART route, and recovery on an
unloaded/secured robot before enabling physical actuation.

## Source defects repaired

1. `GetCustomControllerPos` and its raw-payload accessor read `robot_custom_data`
   (`0x0309`, reverse direction) instead of the controller's `0x0302` source.
2. The arm's `GetRefereeState()` call is not defined in the pinned source; shared
   referee liveness would be the wrong replacement because unrelated traffic can
   keep it online. The replacement is angle-specific.
3. `CCControlData_t` is `float pos[7]` (28 bytes), while old `SendDataToPC` copied
   30 bytes from it. The repaired sender reads only six defined floats (24 bytes)
   into a zero-initialized 30-byte payload, removing the two-byte source overread.
4. `custom_controller_task.c` never advanced `lastTick`. After startup it could
   send every task iteration. The repaired block advances it and uses a wrap-safe
   34 ms interval.

## Install, inspect, revert

Run on a disposable checkout first:

```sh
python tools/firmware/controller_angle/apply_controller_angle.py /path/to/StandardRobotpp --dry-run
python tools/firmware/controller_angle/apply_controller_angle.py /path/to/StandardRobotpp
```

The installer recognizes all five source files before writing, is idempotent,
and keeps a separate byte-preserving snapshot from the hero/KM installer. It
rejects symlinked sources, unsupported layouts, and edits made after installation
rather than silently overwriting them. It leaves all other files unchanged.
To remove it, use `--revert`. If multiple installers touch the same source, undo
them in reverse installation order; their journals deliberately refuse to erase
one another's later modifications. Source transformations have been tested in
both orders with the existing KM/typed-dispatch patch.

This patch intentionally is not automatically applied by the hero/infantry build
preparer: it selects neither engineer nor controller profiles and must not change
another robot's angle schema as a side effect of a keyboard setup.

## Reproducible offline tests

```sh
POLAR_REFEREE_REFERENCE=/path/to/read-only/StandardRobotpp \
  python tools/firmware/controller_angle/test_controller_angle.py
```

The suite creates disposable fixtures and compiles real patched dispatch/types,
sender functions, and the real arm FOLLOW branch with `-Wall -Wextra -Werror`
and UBSan/bounds checks. It covers startup, exact timeout, malformed/nonfinite
payloads, source bounds, unrelated referee/KM/reverse-direction traffic,
uint32 wrap, recovery, all six values, snapshot/output freshness, sender length,
zeroed tail, sender cadence, idempotence, KM composition, and conservative revert.

These are portable host checks. Full Keil/ARM build, ISR timing, real serial
routing through the official player client/video system, joint direction,
loaded-arm safety, and on-hardware interruption/recovery have not been verified.

An optional AddressSanitizer run is also supported:

```sh
ASAN_OPTIONS=detect_leaks=0 POLAR_REFEREE_SANITIZERS=address,undefined,bounds \
POLAR_REFEREE_REFERENCE=/path/to/read-only/StandardRobotpp \
  python tools/firmware/controller_angle/test_controller_angle.py
```

The bounded sender is exercised with an allocation of exactly 24 input bytes, so
an accidental return to reading 28 or 30 bytes is detected. LeakSanitizer itself
cannot run in ptrace-based containers; disabling leak detection for this optional
run does not disable the address/bounds checks. This suite is not a leak audit.
