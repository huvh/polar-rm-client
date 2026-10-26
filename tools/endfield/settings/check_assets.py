"""校验源码和便携版的设置页资源，不依赖游戏或离线解包库。"""
import argparse
import hashlib
import json
from pathlib import Path


def validate(root):
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    required = {"source.json", "PROVENANCE.json", "defaultfont_cn.ttf", "NOTICE.txt", "close.png"}
    if not required.issubset(manifest):
        raise ValueError("Endfield settings pack is incomplete")
    for name, digest in manifest.items():
        path = root / name
        if path.parent != root or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Endfield settings resource mismatch: " + name)
    source = json.loads((root / "source.json").read_text(encoding="utf-8"))
    scroll = source["scroll"]
    if scroll["smoothScrollTweenEase"] != 3 or scroll["smoothScrollTweenSpd"] <= 0:
        raise ValueError("Unsupported Endfield settings scroll parameters")
    return len(manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True, type=Path)
    print("Verified", validate(parser.parse_args().asset_root), "Endfield settings assets")
