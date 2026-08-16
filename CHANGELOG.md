# Changelog

## Unreleased

### Field-chain hardening

- Isolated malformed Tongji UDP observations, made calibration/control flags fail closed, and kept the receiver alive for subsequent valid packets.
- Bounded and validated fragmented video frame assembly, including conflicting totals, duplicate chunks, gaps, in-flight floods and aggregate retained memory.
- Stopped 60 Hz demo telemetry from overwriting authoritative referee state outside `LabDebug`.
- Added a 250 ms neutral KMC heartbeat only while match control is explicitly armed in the fighting stage.
- Expired stale normal-video frames after two seconds, isolated frame ownership across video sources, and removed the fake default supply-zone assertion.

### Low-resolution UI

- Small text uses a supersampled alpha atlas, linear filtering, safe UV padding and physical-pixel snapping.
- Animated labels retain subpixel motion and settle to sharp resting positions.
- Dynamic Island icons use transparent GPU SDF circles without rectangular alpha artifacts.

### Economy workspace

- Added a standalone POLAR economy workspace for ammo, recovery, revive and air-support actions.
- Offers adapt to RMUL 3v3/RMUC 7v7, robot profile and live referee permissions.
- Added protobuf-compatible `CommonCommand` and `AirSupportCommand` publishing with QoS 1 and a 10Hz ceiling.
- Official requests wait for referee state confirmation; desktop Mock requests remain deterministic and isolated.
- Matched the workspace to the Control Center hierarchy: one treated live backdrop with independent liquid-glass modules instead of a frosted root sheet.
- Applied the reference spring, module spacing, five-percent container tint and compact interactive lens behavior.
