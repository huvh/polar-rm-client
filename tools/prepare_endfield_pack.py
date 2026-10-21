"""Explicit offline, all-or-nothing Endfield Esc pack preparation (issue #22).

    python tools/prepare_endfield_pack.py build --package ... --reference ... --models ... --out user_data/endfield_pack
    python tools/prepare_endfield_pack.py check --pack user_data/endfield_pack

No implicit downloads, dependency installs, game extraction, DLL execution or
existing-pack replacement. Boot artwork and EFOS audio are NOT menu requirements.
"""
from __future__ import annotations

import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.endfield_pack import MANIFEST, digest, snapshot, sources, validate
from tools.import_endfield_source_runtime import import_package


def preflight(package: Path, reference: Path, models: Path, out: Path) -> dict:
    """All input/dependency validation precedes creating any pack/build output."""
    pins = sources()
    if out.exists() or out.is_symlink() or out.is_junction():
        raise ValueError("Output already exists; keep it unchanged and choose a NEW --out")
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise ValueError("Building the native menu requires Windows x64 Python")
    expected = [(package, pins["package_sha256"])]
    expected += [(models / row["filename"], row["sha256"]) for row in pins["models"].values()]
    for path, sha in expected:
        if not path.is_file() or digest(path) != sha:
            raise ValueError(f"Missing or wrong pinned input: {path.name}; see docs/ENDFIELD_PACK_SETUP.md")
    for name, version in pins["tool_versions"].items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            actual = "not installed"
        if actual != version:
            raise ValueError(f"Tool {name}: expected {version}, got {actual}; install requirements-endfield-tools.txt in an isolated tooling venv")
    revision = subprocess.check_output(["git", "-C", str(reference), "rev-parse", "HEAD"], text=True).strip()
    if revision != pins["reference_commit"]:
        raise ValueError("Wrong EndfieldHUD source commit; use the pinned checkout")
    subprocess.run(["git", "-C", str(reference), "diff", "--exit-code", "HEAD", "--", "windows", "LICENSE", "CREDITS.md"], check=True)
    return pins


def publish(stage: Path, output: Path) -> dict:
    """Validate, then atomically make a NEW root visible; never replace user data."""
    report = validate(stage)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise ValueError("Output appeared during preparation; existing data is unchanged")
    stage.rename(output)  # Windows refuses an existing destination directory.
    return report


def build(package: Path, reference: Path, models: Path, output: Path) -> dict:
    package, reference, models, output = [path.absolute() for path in (package, reference, models, output)]
    pins = preflight(package, reference, models, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (".endfield-build-" + uuid.uuid4().hex)
    stage = work / "pack"
    stage.mkdir(parents=True, exist_ok=False)
    # Only owned fresh directories are written. On error keep work for diagnosis;
    # no recursive cleanup, active pack publication or config mutation occurs.
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    def run(tool: str, *arguments: str) -> None:
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools" / tool), *map(str, arguments)],
                       cwd=ROOT, env=environment, check=True)
    try:
        import_package(package, stage / "native_source_runtime")
        run("build_endfield_source_probe.py", "--reference", reference, "--native-library",
            "--out", work / "native", "--install-root", stage / "native_renderer")
        for mode, source in pins["models"].items():
            run("prepare_rm_field_preview.py", "--source", models / source["filename"],
                "--out", stage / "maps", "--mode", mode, "--size", "2048", "--up=" + source["up"])
        notices = stage / "licenses"
        notices.mkdir()
        for name in ("LICENSE", "CREDITS.md"):
            shutil.copyfile(reference / name, notices / ("EndfieldHUD-" + name))
        shutil.copyfile(ROOT / "tools/endfield_pack_sources.json", notices / "SOURCES.json")
        record = {"schema": 1, "reference_commit": pins["reference_commit"],
                  "adapter_sha256": digest(ROOT / "native/endfield_bridge.cpp"),
                  "optional_assets": "boot and audio not included or needed for Esc",
                  "redistribution": "Local preparation only. Game resources are excluded from upstream MIT.",
                  "files": snapshot(stage)}
        (stage / MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return publish(stage, output)
    except BaseException:
        print(f"Preparation not published. Owned diagnostic build retained: {work}", file=sys.stderr)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build", help="Prepare ALL required menu components into a new directory")
    for name in ("package", "reference", "models", "out"):
        create.add_argument("--" + name, type=Path, required=True)
    check = commands.add_parser("check", help="Verify an installed pack without executing a DLL")
    check.add_argument("--pack", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = (build(args.package, args.reference, args.models, args.out)
                  if args.command == "build" else validate(args.pack))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "PACK_INCOMPLETE", "detail": str(error),
                          "help": "docs/ENDFIELD_PACK_SETUP.md"}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
