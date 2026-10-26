"""校验随 Wiki 分发的资源；提交前可额外检查是否已纳入 Git。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ASSETS = ROOT / "rm_client/ui/endfield/wiki/assets"
MANIFEST = "RUNTIME_MANIFEST.json"


def resource_file(root: Path, relative: str) -> Path:
    """资源引用必须留在包内，避免本机外部目录掩盖缺失文件。"""
    path = (root / relative).resolve()
    if not relative or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or external Wiki resource: {relative}")
    return path


def file_record(path: Path) -> dict:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_manifest(root: Path) -> None:
    """仅在离线准备时记录资源摘要；校验过程不修改清单。"""
    files = {path.relative_to(root).as_posix(): file_record(path)
             for path in sorted(root.rglob("*")) if path.is_file() and path.name != MANIFEST}
    (root / MANIFEST).write_text(json.dumps({"schema": 1, "files": files},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(root: Path) -> dict:
    """检查图片、动画清单、字体、许可及来源记录，不导入 Qt 或解包器。"""
    root = root.resolve()
    manifest = json.loads(resource_file(root, MANIFEST).read_text(encoding="utf-8"))
    records = manifest["files"]
    if manifest.get("schema") != 1 or not records:
        raise ValueError("Invalid Wiki runtime manifest")
    for relative, expected in records.items():
        if file_record(resource_file(root, relative)) != expected:
            raise ValueError(f"Wiki resource digest mismatch: {relative}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != set(records) | {MANIFEST}:
        raise ValueError("Wiki files differ from runtime manifest")
    layout = json.loads(resource_file(root, "layout.json").read_text(encoding="utf-8"))
    references = {*layout["images"].values(), layout["font"], "PROVENANCE.json", "fonts/manifest.json"}
    fonts = json.loads(resource_file(root, "fonts/manifest.json").read_text(encoding="utf-8"))
    if layout["font"] != "fonts/NotoSansSC.ttf" or fonts["license"] != "OFL-1.1":
        raise ValueError("Wiki font must be bundled with its OFL license")
    references.add("fonts/NotoSansSC-OFL.txt")
    for entry in fonts["files"]:
        relative = "fonts/" + entry["file"]
        references.add(relative)
        expected = {key: entry[key] for key in ("bytes", "sha256")}
        if file_record(resource_file(root, relative)) != expected:
            raise ValueError(f"Wiki font digest mismatch: {relative}")
    provenance = json.loads(resource_file(root, "PROVENANCE.json").read_text(encoding="utf-8"))
    for entry in provenance["files"]:
        references.add(entry["output"])
        if file_record(resource_file(root, entry["output"]))["sha256"] != entry["sha256"]:
            raise ValueError(f"Wiki source digest mismatch: {entry['output']}")
    for relative in references:
        resource_file(root, relative)
        if relative not in records:
            raise ValueError(f"Wiki reference is not shipped: {relative}")
    return {"status": "PASS", "root": str(root), "files": len(actual),
            "images": len(layout["images"]), "clips": len(layout["clips"]),
            "bytes": sum(entry["bytes"] for entry in records.values())}


def require_tracked(root: Path) -> None:
    """提交前检查索引覆盖；不执行 add、commit 或 push。"""
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                            capture_output=True, check=True)
    tracked = set(result.stdout.decode("utf-8").split("\0"))
    missing = [path.relative_to(ROOT).as_posix() for path in root.rglob("*")
               if path.is_file() and path.relative_to(ROOT).as_posix() not in tracked]
    if missing:
        raise ValueError(f"{len(missing)} Wiki resources are not in the Git index; first: {missing[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    try:
        report = validate(args.asset_root)
        if args.require_tracked:
            require_tracked(args.asset_root.resolve())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        report = {"status": "FAIL", "error": str(exc)}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
