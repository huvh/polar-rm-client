# Official event and display alignment, reconstructed 2026-10-21

This document records newly revalidated changes on the restored tree, not the lost earlier workspace.

## Rune display stage

V2 protocol §2.2.29 defines `RuneStatusSync.average_rings` as mean ring score, applicable only while activating the large rune. It is not completion percent. The protocol adapter retains the score in `state.rune_status`; it no longer overwrites the private mock progress value.

A single pure display helper selects source explicitly. Official state with activating status 2 and a finite nonnegative score displays `8.5 rings` / `8.5 环`; other stages display their phase, and missing/invalid observations display unknown. Official observations never fall back to the demo 48%, draw a percent bar, or drive a fake completion marker. Explicit mock state keeps its existing percent behavior. Detector confidence remains an independent percentage and opaque detector names remain unchanged.

All three target HUD layouts, Rune ESP marker/bar/label, and decorative helicopter-gimbal phase now use that distinction. Public renderer method signatures remain unchanged.

New-tree validation: `test_rune_display_alignment.py` 6/6, `test_hud_display_locale.py` 14/14. Tests inspect actual render calls and marker counts, not permissive pixel thresholds. No device outputs are started.

## Event forms and supervised requests

- Assembly is operation 0 start exchange / 1 confirm assembly / 2 cancel, difficulty 1..4. Rune offers only activate=1. Dart exposes official target 1..5; the aerial operator controls its own-team Dart. `open=False` requests no opening, never means close. `launch_confirm` remains always false.
- V1.3.1 Sentry IDs 1..9 and labels follow official 2026-05-19 §2.2.33. V2 Sentry uses independent V2 economic confirmation, never the old V1 values or direct unsupervised publishing. Actor identities are hints in the form; the backend's fresh wire identity remains final authority.
- Menu entries require a real callable publisher and reviewed profile capability. Cancellation and actual owner/round/identity changes emit nothing. Success means submitted request, not server execution acknowledgement.
- Aerial V2 performance changes same-team Sentry control mode only in fresh PREPARE. One explicit confirmation obtains a 15-second core qualification token, rechecks after input-clear observers, sends once and locks. It does not manufacture PASS evidence. Ground performance still uses the backend's version-aware preset mapping.
- V2 Common/Sentry/paid Sentry Map use independent immutable wire quotes, never legacy V1 offers. Common remote ammunition is one fixed 150-coin pack; local 17mm uses ten-round units and 42mm single-round units; revival uses current wire quotation. Sentry includes the observed automatic/semi-automatic intervention fee; Sentry6 remains explicitly unavailable without target-specific paid revival quotation.
- Paid Map is an explicit separate confirmation targeting same-team Sentry only. Frozen coordinates and attack/defense/warning mark are shown before confirmation. Codec field3=mark category, field6=marking mode remain distinct. Ordinary map clicking does not silently incur Sentry fees. V2 custom ASCII is blocked because official PDF mode4 and student213 mode5 disagree.
- Context captures actual owners, round, connection generation, ClientId and all three match-mode authorities (UI, state, qualification session), requiring RMUC7v7. Equal-value unrelated fresh receipts are accepted; price/identity/phase/target changes cancel or require at most one renewed confirmation. Final MQTT receives the exact checked snapshot. Tokens are one-use and no request is automatically retried.
- Shared context helpers were mechanically moved to `v2_request_context.py` and re-exported from tactical_map, avoiding a deferred import cycle. Air's existing dedicated flow is retained, with exact-snapshot binding and corrected copy: its supervised scope does not imply the whole V2 profile is still partial.

New-tree tests: event forms 12/12; V2 economy dialogs 11/11; V2 preparation performance 4/4; HUD display locale 14/14; literal UI localization 15/15. Air's independent process fixture is owned and revalidated by the protocol stage. All transports in these UI tests are inert recorders, while quote rules and codecs are production implementations.

## Radar units and highlight stage

Official V1/V2 `RadarInfoToClient` target coordinates are unsigned centimetres. Default official conversion is always `/100`, including 20cm→0.2m, with no field-size heuristic. Private/mock metre inputs must declare `private-metres`/`mock-metres`; active official state takes precedence over a private override. Highlight 1 is a special mark; 2 additionally means positioning offline. Neither implies a damage buff. Unknown enum/nonfinite coordinates are rejected.

New-tree validation: pure telemetry12/12, full tactical-map contract16/16, RadarOverlay settings script18 checks, and final localization15/15. The map fixture bytes/SHA remain untouched; its old 20→20 conversion is directly asserted as the historical bug. Only audited coordinate/highlight deltas are applied to an independent expected reference function, with all other command, pixel, hotspot and partial-failure comparisons kept exact. Direct rendering additionally checks source-selected coordinates, offline tooltip, and literal diamond vertices. Static quality gate passes (234 modules, zero initialization cycles).
