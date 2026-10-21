# Endfield cross-machine delivery and video reconnect

Base: `cbf60e66602ffa06667b7d95c4358c624e5779f4` plus the recorded patch.
See [behavior and transfer instructions](../../docs/endfield_delivery_video_reconnect_20261022.md).

Final stable-source offline regression: **458 PASS / 12 SKIP / 6 INCOMPLETE /
0 FAIL** (completed, exit 1 / NO-GO). Native D3D, production-default Windows
menu loading, ZIP relocation/LF-source validation and real H.264/HEVC UDP
reconnection probes passed. The complete local transfer ZIP is 22,962,506 bytes;
its contents remain unpublished pending the separate asset-rights confirmation.

## Evidence boundaries

- A complete, previously cold-built 55-file menu pack was explicitly exported
  to a new read-only asset tree. No user configuration, private installation
  directory, account, game process or whole user_data tree was copied.
- Actual native D3D rendered all three official field previews at 720p/2K.
- Actual Windows client integration used its **production default pack selection**,
  **no private pack**, a fresh temporary user profile and inert transports.
  Esc/fullscreen/settings/hover/reopen passed; texture growth was zero.
- Native renderer binary/visuals/materials/animation remain unchanged. Metadata
  removes machine-local compiler paths and permits only LF/CRLF differences
  when comparing the same C++ source identity across checkouts.
- The explicit real FFmpeg probe uses loopback UDP and the existing pinned
  H.264/HEVC GOPs. A sender interruption, changed source port and frame-ID reset
  both recover with fresh decoded frames and confirmed resource cleanup.
- Native 0x0310 idle/counter/keyframe decisions are tested with an inert decoder;
  these are not real referee or receiver evidence. Existing wire and control
  authorization gates are unchanged. No robot commands were sent.
- The original characterization baseline was not refreshed. A first regression
  exposed extra observable timing/diagnostic effects; the implementation now
  keeps idle bookkeeping on a separate monotonic observation and preserves the
  original decoder/retry trace. The fixture clock gained that separate method;
  new idle behavior is asserted independently in test_video_reconnect.py.

The JSON records final verification and any earlier rejected/mixed-source run.
Skips/incomplete checks remain NO-GO for whole-project qualification. Desktop
throughput observations are not a 70–90 FPS certification; this is not a new
clean Windows computer, GPU-driver matrix or official hardware acceptance.

## Explicit reproduction commands

```powershell
$env:PYTHONUTF8 = '1'
& $AppPy tools/prepare_endfield_pack.py export --pack $CompletePack --out $NewAssetTree
& $AppPy tools/prepare_endfield_pack.py check --pack $NewAssetTree
& $AppPy tools/verify_endfield_pack_runtime.py --pack $NewAssetTree --out tmp_native_check
# Place the verified tree at assets/endfield_pack first; no --pack injection:
& $AppPy tools/verify_endfield_desktop.py --out tmp_desktop_check --cycles 3
& $AppPy tools/verify_video_reconnect.py --ffmpeg $Ffmpeg --out tmp_decoder_reconnect
& $AppPy tools/verify_all.py --profile offline --json tmp_reconnect/full_final.json --log-dir tmp_reconnect/full_final
git diff --check
```

The local ready-to-transfer ZIP and original textures/fonts/screenshots are not
uploaded by this report. A source-code commit, private transfer or technical
pack validation is not a third-party redistribution license. Public asset
publication requires the separately requested authorization confirmation.
