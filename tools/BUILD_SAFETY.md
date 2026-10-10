# Build and maintenance safety

## Portable package

- PyInstaller includes `polar_protocol.json` and `cc_key_usage.json` beside their frozen loaders. The release manifest also hashes those packaged JSON files. Preflight rejects missing protocol data or a fallback to built-in protocol tables.
- Imported UI sounds live in `user_data/ui_sounds/custom`. Existing `custom/<filename>` selections remain portable. Older files in the resources folder are copied only when absent from user data; the original resources and newer user files are left intact. Legacy custom imports are excluded from the disposable release staging tree.
- Official preflight checks manifest, sidecar, critical-file/resource hashes and the FFmpeg hash before running FFmpeg or codec probes. A failed integrity check prevents those executions. These local hashes detect changes; they are not a cryptographic publisher signature.
- Failed Windows builds keep the staging directory and test logs named in the warning. Successful builds still clean up. The source launcher keeps the Python executable separate from `py -3` arguments and checks core dependencies.

## Verification results and target identity

`tools/verify_all.py --firmware <prepared-worktree>` uses that exact worktree for every firmware-aware child check. It prints its commit and worktree-byte hash and checks that the tree did not change. It invokes preparation diagnostics with `--check-only`; it never silently installs prerequisites into the requested tree.

Missing test files, an explicit skip, an unavailable prerequisite or a timeout cannot produce a complete GO result. Checks report FAIL or INCOMPLETE separately. Each child has a configurable timeout (`--timeout`, default 180 seconds).

The legacy baseline-patch logic test requires temporary installation and is deliberately INCOMPLETE under this read-only gate. It needs separate validation in a disposable copy; its exclusion must not be interpreted as a passing firmware check. This change does not certify a full firmware build or hardware behavior.

## Dry-run and revert

- Host/KM tool dry-runs never auto-install missing prerequisites. If a prerequisite is absent, planning stops with an explicit error before any write. A fully prepared disposable tree is needed for a complete dry-run plan.
- Preparation keeps an original-byte/file-mode journal for the complete enumerated file inventory, including parameter files and both headers. Reruns retain the original snapshot.
- Revert first verifies every file against its post-operation fingerprint. Later edits, symlinks, missing/incomplete journals or concurrent operations block restoration. It never falls back to `git checkout` or deletes an unrecorded custom header.
- Older preparations made without a journal cannot be safely auto-reverted. Preserve and inspect them manually. Interrupted operations retain their journal/lock for inspection; do not blindly delete the journal or lock to force a retry.
- A successful revert says that prior file content was restored. It is not a build-readiness result.

## Isolated regression suite

`python tests/test_build_safety_regressions.py` uses temporary files and spies for subprocesses, Qt, network and firmware operations. It does not execute a firmware installer, compiler, FFmpeg or a hardware connection. Windows cmd/PowerShell/PyInstaller behavior, GPU rendering and real compiler/hardware tests still require their intended environment.
