# Endfield Esc runtime pack — provenance and distribution boundary

The repository maintainer explicitly requested inclusion of the runtime assets
in Git on 2026-10-22. `assets/endfield_pack` contains the verified, complete menu
pack, not personal runtime data or a complete game installation.

- EndfieldHUD code: commit `cdbd4f573c8fa3b9c2048fa3d1b089e69196537b`, MIT.
  Original license and CREDITS are retained inside the pack.
- Original required scene/raster/font inputs: the pinned v1.2.0 build18 portable
  resource archive; file hashes are locked in `tools/endfield_runtime_files.json`
  and the imported runtime manifest. The upstream executable is not included.
- Noto font licenses: the original OFL notices are retained beside the fonts.
- RM field previews/meshes: derived from the pinned official RMUC7v7, RMUL3v3
  and RMUL1v1 2027 V1.0.0 STEP models. Sources, hashes and axis choices are in
  `assets/endfield_pack/licenses/SOURCES.json`; the official models' stated
  CC BY-NC-SA 4.0 terms and source attribution remain applicable.
- POLAR native adapter: built locally from the checked-in C++ source and pinned
  upstream sources. Actual source/binary/compiler identity is retained in the
  renderer build manifest. No compiler or CAD tool is needed at runtime.

Upstream MIT does not relicense original game imagery, logos, trademarks or
other third-party content. Their rights remain with the respective holders;
the maintainer's inclusion request and technical integrity checks are not an
independent legal determination of third-party redistribution rights.

Optional boot art/audio, user configuration, qualification evidence, logs and
the raw STEP downloads are not included in this runtime pack.
