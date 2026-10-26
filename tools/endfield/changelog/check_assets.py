"""检查公告资源、原版组件与本体字体是否完整，不启动浏览器或访问网络。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def validate(root: Path) -> dict:
    manifest = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    paths = set()
    for row in manifest["files"]:
        path = root / row["output"]
        if not path.resolve().is_relative_to(root.resolve()) or row["output"] in paths:
            raise ValueError("Invalid or duplicate announcement asset: " + row["output"])
        paths.add(row["output"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Announcement asset differs: " + row["output"])
    required = {"index.html", "adapter.js", "commons.8113a7.css", "commons.29f297.js", "game.451b84.js",
                "fonts/HarmonyOS_Sans_SC_Bold.woff2", "fonts/HarmonyOS_Sans_SC_Medium.woff2",
                "fonts/HarmonyOS_Sans_Bold.woff2", "fonts/HarmonyOS_Sans_Medium.woff2"}
    if not required <= paths:
        raise ValueError("Missing announcement resources: " + str(sorted(required - paths)))
    return {"status": "PASS", "files": len(paths)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.asset_root)))
