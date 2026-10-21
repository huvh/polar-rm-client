# Issue #22 — complete Endfield Esc pack preparation

Issue: https://github.com/lulunomaro/polar-rm-client/issues/22

The fix supplies an explicit, transactional source preparation workflow, not an
empty BUILD_MANIFEST, a replacement menu, a disabled effect or a new public game
asset release. Complete user instructions: [setup](../../docs/ENDFIELD_PACK_SETUP.md).

## Scope and reproduction

Base: `b29445ccc57cc0dc9e62dbf35e993bdb129c7763` plus the recorded patch on
`fix/issue22-endfield-pack`. The evidence JSON records actual tested fingerprints,
file hashes, environment, build output and incomplete regression checks.

- Cached, hash-pinned **raw** upstream ZIP and official STEP inputs were reused.
- The prepared destination was absent. DLL/objects, resource import and all three
  field meshes/previews/metadata were built into fresh owned directories.
- No author-prepared DLL, converted map, private installation tree, boot artwork,
  EFOS audio, account data or existing user configuration was copied into it.
- Tooling used existing isolated Python targets with the exact recorded package
  versions. This was NOT a clean-machine/new-venv installation test.
- Native D3D runs used the newly compiled DLL, not an already-loaded author's DLL.
  Its import table references Windows system libraries, not a Zig/compiler DLL.
- Screenshots read only the client's own native/GL targets. The original renderer
  and field mesh code have no Git changes; newline conversion differs across
  local checkouts, so raw adapter/binary hashes are tied to the actual build.
- Prepared assets and screenshots remain local/ignored; only factual metadata,
  hashes, source/tools/tests/documentation and reviewed results are retained.

## Results

- Fresh complete pack preparation and integrity check: **PASS**, 54 tracked pack
  files plus the top-level manifest; optional boot/audio absent.
- Actual native D3D rendering: **PASS**, all three maps at 720p and 2K.
- Actual Windows client Esc integration: **PASS**, three reopen cycles, fullscreen
  preserved, no native error or texture growth. Observed synthetic HUD throughput
  was 44.82 FPS with P95 49.88 ms; this does **not** certify the performance target.
- Targeted regression: **6 suites PASS**, including 13 new setup assertions/tests.
- Full offline regression: **456 PASS / 12 SKIP / 6 INCOMPLETE / 0 FAIL**.
  The runner completed with exit 1 / overall NO-GO, not an all-green verdict.
- Changed Python compilation and `git diff --check`: **PASS**; primary user
  configuration hash unchanged. This is the pre-commit verification snapshot;
  its JSON source identity describes the tested uncommitted patch, not any later
  commit, push or main integration.

Commands from the source root (input variables are the real paths described in
our setup guide, not an unavailable private build tree):

```powershell
$env:PYTHONUTF8 = '1'
& $ToolPy tools/prepare_endfield_pack.py build --package $Package --reference $Reference --models $Models --out $NewPack
& $AppPy tools/prepare_endfield_pack.py check --pack $NewPack
& $AppPy tools/verify_endfield_pack_runtime.py --pack $NewPack --out tmp_issue22_native
& $AppPy tools/verify_endfield_desktop.py --pack $NewPack --out tmp_issue22_desktop --cycles 3
& $AppPy tools/verify_all.py --profile offline --json tmp_issue22/full.json --log-dir tmp_issue22/full
git diff --check
```

All output roots must be new. Source tools never install dependencies or download
resources implicitly. Pack validation is integrity/source checking, not code
signing. Native rendering and desktop integration are separate tests; neither
qualifies a robot, a real match, a release, or a performance target.

Do not read the optional 1v1 preview as full 1v1 match/business support. Existing
control, backend authorization, liquid-glass materials and ordinary HUD geometry
were outside this change. Aggregate skips/incomplete checks remain **NO-GO**.
