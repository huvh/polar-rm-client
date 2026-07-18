# Changelog

## Unreleased

### Low-resolution UI

- Small text uses a supersampled alpha atlas, linear filtering, safe UV padding and physical-pixel snapping.
- Animated labels retain subpixel motion and settle to sharp resting positions.
- Dynamic Island icons use transparent GPU SDF circles without rectangular alpha artifacts.

### Economy workspace

- Added a standalone POLAR economy workspace for ammo, recovery, revive and air-support actions.
- Offers adapt to RMUL 3v3/RMUC 7v7, robot profile and live referee permissions.
- Added protobuf-compatible `CommonCommand` and `AirSupportCommand` publishing with QoS 1 and a 10Hz ceiling.
- Official requests wait for referee state confirmation; desktop Mock requests remain deterministic and isolated.
