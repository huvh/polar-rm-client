# Issue 20: legacy video evidence and acceptance boundary

Date: 2026-10-18. Investigation context: parent-reported public PR head
`04a1d072`; this is a documentation-only evidence record, not a new full-test
result or hardware compatibility certification.

## What is established

[Issue 20](https://github.com/lulunomaro/polar-rm-client/issues/20) records the
user's report that the same legacy video hardware works with official
**RoboMasterClient 11.0.1.128**. It does not report a completed POLAR hardware
connection test or establish that POLAR has failed with that device attached.
The exact receiver/transmitter model, host interfaces and stream remain unknown.

Primary public sources distinguish different generations:

- The [official 2025 competition-engine page](https://www.robomaster.com/zh-CN/products/components/detail/6145)
  lists client 11.0.1.128, provides an official client download entry and states
  that its student version supports switching between old and new video links.
  This is software provenance, not a published third-party capture API.
- The [official VT12 2020 product page](https://www.robomaster.com/zh-CN/products/components/detail/2595)
  specifies USB Type-C video output and links the DJI Phantom 4 Drivers_1.2
  package and VT02/VT12 manual.
- The [manufacturer's VT02/VT12 manual](https://rm-static.djicdn.com/tem/17348/RoboMaster%20%E5%9B%BE%E4%BC%A0%E6%A8%A1%E5%9D%97%20VT02%2612%202020%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6.pdf),
  PDF page 7 (printed page 6), describes the driver, receiver USB connection,
  transmitter role through the referee main controller, receiver role through
  RoboMaster Client, and activation requirement. Although the linked filename
  includes 2020, its cover identifies v1.0, 2019.02. It does not specify a host
  decoding API, USB endpoint contract or stream encoding.
- The earlier [2018 camera-link product page](https://www.robomaster.com/zh-CN/products/components/detail/145)
  instead documents HDMI output and capture-card connection to a computer.
  That option belongs to that hardware; it cannot be selected for this issue's
  unidentified device merely because both are called old video links.
- The public [DJI RoboMaster SDK repository](https://github.com/dji-sdk/RoboMaster-SDK)
  targets the RoboMaster EP education robot. Its existence does not establish
  competition-receiver compatibility.

No verified public legacy-receiver SDK, reusable official-client video output
API or documented bridge endpoint was established by this bounded search.
DLL export names recorded in the issue are investigation clues, not sufficient
calling-convention, ownership, initialization or transport documentation.
No installer/DLL was downloaded or executed for this investigation.

## Existing repository contracts

- [FrameAssembler](../../rm_client/transports.py) consumes the Shark fragment
  contract: an **8-byte big-endian** header comprising `uint16 frame_id`,
  `uint16 chunk_index`, `uint32 total_bytes`, followed by fragment payload.
  Arbitrary bare codec bytes, device USB packets or official internal UDP are
  not interchangeable with this framing.
- [parse_video_0310_chunk](../../rm_client/native_viewer_telemetry.py) accepts
  **exactly 300 bytes**: a 3-byte header and up to 297 payload bytes. Header byte
  0 contains reset bit 0 and payload-length high bit 1, with other bits reserved;
  byte 1 is the modulo-256 sequence; byte 2 supplies the low length bits. The
  resulting video payload is designated H.264. This project-specific Native
  0x0310 path is not a legacy-device driver or generic raw-video input.
- The H.264 dispatch gap in [video_backend.py](../../rm_client/backend/video_backend.py)
  is now implemented and independently reviewed at local
  `3f94f0f0a4ac3d0a8313f9fc49808ff021b4652a`, public
  [32da8ad51baf5834fdd77f8ee7c29afc4bd946e2](https://github.com/lulunomaro/polar-rm-client/commit/32da8ad51baf5834fdd77f8ee7c29afc4bd946e2),
  tree `2f08204b1eb2a3dc96fbbe7fb171c6873e3e65b5` (parent-verified mapping).
  Fixing this path does not identify the legacy device's codec, initialize its
  receiver or prove its HUD output.

## Smallest evidence needed to choose an implementation

1. Receiver/transmitter model labels and firmware versions, including whether
   the working setup uses standalone or referee-controlled operation.
2. Host device/interface descriptors and driver identity from the known-working
   official-client setup. Do not guess VID/PID, interface class or endpoints.
3. The working startup/selection sequence and ownership dependencies, including
   whether the official daemon must remain running or owns the device exclusively.
4. A bounded genuine video sample preserving transport boundaries, with explicit
   permission for any sharing. Establish actual encoding and initialization/read
   protocol, or obtain a documented supported output interface.
5. If bridging is chosen, document input ownership, output framing/encoding,
   timestamps, loss/recovery behavior and startup/shutdown dependencies. An
   official-process-dependent bridge must be described as such.

## Hardware acceptance still required

- On the same hardware already working in the official client, show continuously
  updating real video in POLAR's HUD; record duration, resolution and frame rate.
- Distinguish device opened, bytes received, valid stream parsed and fresh frame
  decoded. Receiving bytes alone must not assert live video.
- Exercise disconnect, stale stream, occupied device/port, reconnect and shutdown;
  stale images must not remain presented as current live frames.
- Regress existing HEVC/MJPEG/Webcam/Synthetic/Native paths according to the
  eventual change scope, retaining Hero deployment switching restrictions and
  all control-authorization boundaries.
- Report software implemented, automated checks passed, hardware checks passed
  and remaining unknowns separately. Synthetic dispatch markers and unrelated
  camera frames cannot substitute for this legacy-device acceptance.

This report includes links and original summaries only, with no binary copies,
protocol guesses, raw-log publication or claim that legacy compatibility is done.


## H.264 software stage and verification

The existing Shark path now feeds H.264 into the persistent Annex-B decoder
slot, sharing its ownership/lifecycle with HEVC. Codec changes retire the old
owner before replacement; blocks received during retirement are dropped, so a
later parameter-set/keyframe sequence is required for recovery. Missing FFmpeg,
failed admission/write, stale callbacks and stop/close ownership are covered by
[test_udp_h264_dispatch.py](../../tests/test_udp_h264_dispatch.py).

The standalone codec detector contract is retained. An earlier blanket
high-layer-bit detection change failed an existing protocol test and was
reverted. Ambiguous `0x41` non-IDR handling is contextual to an already selected
H.264 stream; it is not a new universal codec discriminator.

- Baseline dispatch regressions: **2 failures, 0 errors**.
- Final new regression: **12 methods**. Author focused total: **105 methods**,
  with **198 protocol checks** and API-freeze verification reported separately.
- Independent focused selection: **31 methods passed**, including real split-NAL
  H.264 advancement, H.264 → HEVC → MJPEG → H.264 transitions and close ownership.
  These selections overlap and must not be added as distinct test counts.
- Existing bundled sample `assets/selftest/h264_one_gop.h264`: **44,832 bytes**,
  SHA-256 `60c903a9e311b588d2fa453560c5af4884a6767e3a62c9fef8e91123dfa2ec59`.
  Reported ffprobe inspection identifies **160×120, 30 frames**. Actual continuous
  decoding produced **17 frames before EOF** for one GOP; this does not claim
  all 30 were emitted before EOF. Feeding a second GOP advanced decoded-frame
  count and freshness. The regression requires advancement, not a hardcoded 17.
- Full offline run `client-renewed20h-full3/results.json` is **completed:
  358 PASS, 12 SKIP, 4 INCOMPLETE, 0 FAIL; NO-GO** (`passed: false`). Independently
  verified run ID: `41c9338e5bb543a3a369ee25acaeeab7`. Its source commit/tree are
  the exact `3f94f0f0` / `2f08204b` identities above. It uses the parent-selected
  official scratch PowerShell runtime through `POLAR_TEST_PWSH`.
- Source-at-start provenance records **dirty: true**, not a clean full worktree.
  Parent-recorded run context and independently inspected current Git status
  identify only the edited renewed-repairs report and this untracked issue20
  report; source/tests/tools changes were committed. Declared source stability
  passed with **707 inputs** at both endpoints and SHA-256
  `8fece1870f64b410d1e3c3d9af90ebcafb45d222af2a942b01e698dde9a96d04`.
  This scope covers declared code/configuration inputs and excludes documentation,
  assets, external fixtures and installed packages. Matching endpoints do not
  rule out transient edits restored between captures. The sample hash above is
  separate from that source fingerprint.

| Area | Status and evidence boundary |
|---|---|
| Code implemented | Shark-framed H.264 decoding and owned codec transitions, reviewed and published |
| Automated verified | Focused real-decoder/lifecycle checks and completed scoped aggregate above; aggregate remains NO-GO |
| Hardware verified | None by this task; official-client success remains the user's reported control condition |
| Still pending | Exact old device/interface, supported initialization/read path or bridge, genuine device stream, POLAR HUD and disconnect/reconnect acceptance |

This software stage adds neither a USB driver nor arbitrary raw-UDP input and
does not redefine Native 0x0310. Issue 20 remains open for its device-integration
and hardware acceptance requirements.
