# UI-thread device I/O isolation

This change addresses missing/disconnected DT7 stalls without changing render
resolution, visual effects, frame-rate targets, or real-output defaults.

## Production behavior

- Real DT7 and custom-controller output use one serial-owner worker each.
  Their mailbox is bounded to the newest intent; relative DT7 mouse deltas are
  accumulated within the bounded, expiring mailbox rather than silently lost.
- Enqueue acceptance is distinct from actual `sent`, `failed`, `queued`, and
  `coalesced` counters. Neutral completion is reported only after a full write.
- Neutral supersedes queued motion. Generation, age, and fresh policy checks
  run again after a slow open, before an ordinary DT7 write. Failure discards
  pending movement and locks once through UI-thread polling.
- A release campaign has at most three attempts. Exhaustion stays visibly
  unconfirmed and blocks movement. Explicit port rescan can retry neutral on
  the old target; it does not re-arm motion. A disconnected receiver might
  still be holding the last command: this is not a substitute for physical
  E-stop or verified receiver watchdog behavior.
- A healthy-port stale-input watchdog requests neutral immediately. Real I/O
  failures honor the transport backoff deadline; repeated UI calls cannot
  reset either the backoff or the release budget.
- The authorized neutral/X qualification probe has a token-bound, bounded
  no-send hold. Ordinary motion cannot suppress the worker watchdog. A probe
  cannot count host watchdog neutralization as receiver expiration evidence.
- Port discovery uses a shared one-second snapshot. Dropdown construction and
  diagnostic polling request asynchronous refresh. Explicit rescan and failed
  handles invalidate the snapshot. New DT7 handles revalidate device identity;
  established handles are not enumerated again on every write.
- POLAR connection requests snapshot settings and use at most one connector.
  Cancelled or configuration-mismatched opens are closed before publication.
  Request-stop/estop latch immediately; cleanup never races new connection
  ownership. Frame-driven settings changes wait for old real-stream neutral
  cleanup before changing mock mode or endpoint.
- The manager never waits for POLAR's driver-held TX lock during a frame. It
  still drains DT7/CC completion/fault notifications, then skips only POLAR work
  while that lock is busy. Existing transport deadman logic remains active.

Synchronous link methods remain available to offline tools/tests. Synchronous
scenario shutdown remains ordered before applying a new scenario, so it cannot
turn the old live stream into mock before its final neutral flush. Scenario
switches and final shutdown can therefore still pause the GUI during existing
transport zero/close operations; a pathological OS close has no reliable upper
bound. DT7/CC shutdown waits share an additional 2.5-second completion budget,
and log unconfirmed cleanup instead of calling a queued neutral successful.
Ordinary frame/reconnect/settings operations never use those joins. A stuck OS
write already in progress cannot be recalled; subsequent stale motion is
rejected, and no worker is replaced while it still owns cleanup.

## Offline measurements (Linux, fake drivers only)

These numbers are test observations, not an achieved hardware FPS claim:

- 1,000 DT7 submissions with a fake 19.3 ms enumeration and blocked write:
  observed caller median about 0.003 ms and maximum below 0.4 ms; all
  enumeration/open/write/close calls occurred on `dt7-writer`.
- 250 real-time calls at 100 Hz over 2.500 s with no fake DT7 present:
  four scans (initial plus three neutral attempts), one input-clear callback;
  observed caller median about 0.034 ms and maximum below 0.8 ms.
- An additional 2,000-call burst cannot reset the exhausted release budget.
- Fake 200 ms opens, blocked close, disconnect, stale key-up, silent UI,
  qualification expiry/hold, config mutation, and shutdown races are covered.
- 1,000 manager frame calls while the POLAR TX lock is held return in under
  50 ms total in the offline regression, without waiting for that driver.

No physical robot, DT7, serial output, or Windows GPU was used for validation.
The field capture's 89-second/737-loop result is not directly comparable to the
short fake benchmark. Actual device and platform frame pacing need a new trace.

## Transferable requirements for a Rust implementation

1. A bounded latest-intent mailbox, separate priority neutral barrier, and
   generation-tagged completion; never call serial discovery/open/write from
   the UI loop or hold a UI-accessed mutex through device I/O.
2. Perform backoff checks before enumeration, including the no-target path.
3. Keep reconnect/config/shutdown ownership on one worker; close late handles
   locally and never let an older generation close a newer stream.
4. Reject expired/old-epoch motion after blocking open and before writing.
5. Distinguish accepted, written, neutral-confirmed, failed, and exhausted.
6. Preserve physical-RC priority, fire gates, E-stop and explicit re-arm;
   reconnect alone must not replay or re-authorize old commands.
7. Use fake slow drivers and queue/epoch race tests before hardware testing;
   retain renderer quality and instrument UI work versus paint time separately.
