"""离线资源完整性校验；不读取游戏、不加载Qt或启动设备。"""
import argparse
import hashlib
import json
from pathlib import Path


def validate(root):
    for name,digest in json.loads((root/"MANIFEST.json").read_text(encoding="utf-8")).items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError("Keybind pack mismatch: "+name)
    provenance = json.loads((root/"PROVENANCE.json").read_text(encoding="utf-8"))
    for entry in provenance["files"]:
        if hashlib.sha256((root/entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Keybind asset digest mismatch: "+entry["file"])
    config = json.loads((root/"source.json").read_text(encoding="utf-8"))
    if len(config["icons"]) != 84 or len(config["clips"]) != 2 or not provenance["verified_game_bundles"]:
        raise ValueError("Incomplete keybind source pack")
    return len(provenance["files"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root",type=Path,required=True)
    args = parser.parse_args()
    print(f"PASS: {validate(args.asset_root)} keybind assets")
