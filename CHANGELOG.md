# Changelog

## Unreleased

### Field-chain hardening

- Waived the match qualification evidence chain for DT7 direct egress in `LabDebug` only, so bench driving works while E-stop precedence, module gates, Real TX, 30 Hz limiting, neutral flush and the other two scenarios stay unchanged.
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
# v0.1.0 — 首个 Windows x64 便携现场候选版（2026-10-14）

- Jello 设置中心、原版时间线键盘绑定管理器与中英文清晰排版。
- 修复圆角像素溢出、MC 背包中文、ModList 对齐、MC 字形/上传裁切；YOLO/ESP 改为荧光白空心框。
- CS2 式顶栏、完整 RM 购买网格、击杀反馈及准星分享码导入/导出；新增 0.5×–8× 本地准星整体倍率。
- 设置页保留真实分辨率、渲染帧率、画质、声音、鼠标与键位设置；不修改液态玻璃 shader。
- 新版便携包含 FFmpeg、全部选定内置资源和版本/哈希清单；可显式注入经白名单验证的本机 CS2 素材包。
- 真实控制仍 fail-closed：没有真车、裁判、正式图传及双人签字，结论为 **NOT READY FOR REAL MATCH**。
