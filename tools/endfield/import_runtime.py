"""Import an explicitly supplied, pinned EndfieldHUD resource package.

Copies source-renderer resources/fonts/notices only, never its executable or
desktop providers. No download, installation, game modification or public asset
license is implied. Use a private user_data/endfield_pack destination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

RELEASE = "https://github.com/DDDuoDuo/EndfieldHUD/releases/tag/v1.2.0"
PACKAGE_SHA256 = "b16f77c5dfa1c7e7cfe2ed96697347b880932a25507f6c8cb823ffec2a9a9341"
ENGINE_COMMIT = "cdbd4f573c8fa3b9c2048fa3d1b089e69196537b"
PREFIXES = ("EndfieldHUD/resources/shell/", "EndfieldHUD/resources/licenses/", "EndfieldHUD/fonts/")


def select_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    if len(archive.infolist()) > 2048:
        raise ValueError("Excessive source archive entries")
    result, seen, total = [], set(), 0
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        if ("\\" in name or ":" in name or path.is_absolute() or ".." in path.parts
                or "\0" in name or stat.S_ISLNK(info.external_attr >> 16)):
            raise ValueError("Unsafe source archive path")
        if name.casefold() in seen:
            raise ValueError("Duplicate source archive path")
        seen.add(name.casefold())
        if info.is_dir() or not name.startswith(PREFIXES):
            continue
        if path.suffix.lower() in {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py"}:
            raise ValueError("Executable content is not a source resource")
        total += info.file_size
        if info.file_size > 32 * 1024 * 1024 or total > 96 * 1024 * 1024:
            raise ValueError("Source resource budget exceeded")
        result.append(info)
    return result


def import_package(package: Path, output: Path) -> dict:
    package, output = package.resolve(), output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new private source-resource directory")
    if not package.is_file() or package.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Missing or oversized explicit source package")
    with package.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != PACKAGE_SHA256:
        raise ValueError("Source package hash differs from the pinned upstream release")
    with zipfile.ZipFile(package) as archive:
        entries = select_entries(archive)
        names = {entry.filename for entry in entries}
        required = {"EndfieldHUD/resources/shell/catalog.ehscene",
                    "EndfieldHUD/resources/shell/runtime-input/runtime-input.json",
                    "EndfieldHUD/fonts/NotoSansSC.ttf", "EndfieldHUD/fonts/NotoSansKR.ttf"}
        if not required <= names:
            raise ValueError("Incomplete original source renderer resources")
        # A fresh root owns this entire transaction; a failed import is never
        # returned as usable and cannot overwrite any existing user package.
        output.mkdir(parents=True)
        hashes = {}
        for entry in entries:
            relative = PurePosixPath(entry.filename).relative_to("EndfieldHUD")
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
            with target.open("rb") as stream:
                hashes[relative.as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"release": RELEASE, "package_sha256": digest, "engine_commit": ENGINE_COMMIT,
                "original_executable_imported": False, "files": hashes,
                "acceptance": {"client_menu_integrated": False, "pixel_parity": "NOT VALIDATED"}}
    (output / "SOURCE_RUNTIME_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = import_package(args.package, args.out)
    print(f"Imported {len(manifest['files'])} original resource files; UI parity remains unvalidated")


if __name__ == "__main__":
    main()
