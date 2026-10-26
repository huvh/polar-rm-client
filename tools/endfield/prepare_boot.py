"""Offline original login loading prefab -> private, bounded presentation pack.

Input is an explicit local EndfieldStudio original/raw/metadata export. UnityPy
is an isolated tooling dependency, never installed/used by the client at run
time. Game assets are not added to Git or licensed by this tool's source code.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil


PREFAB = "assets/beyond/initialassets/prefabs/login/loginrootpanel.prefab"


def decode(root, row):
    from UnityPy.helpers.TypeTreeHelper import read_typetree
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode
    from UnityPy.streams import EndianBinaryReader
    metadata = json.loads((root / row["metadata_path"]).read_text(encoding="utf-8"))
    nodes = metadata["serialized_type"]["m_Type"]["m_Nodes"]
    tree = TypeTreeNode.from_list([{k: v for k, v in node.items()
                                  if k not in ("m_TypeStrOffset", "m_NameStrOffset")} for node in nodes])
    raw = (root / row["raw_path"]).read_bytes()
    return read_typetree(tree, EndianBinaryReader(raw, endian="<"), byte_size=len(raw))


def prepare(root: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in (root / "_index.jsonl").open(encoding="utf-8")]
    objects = {}
    for row in rows:
        if row.get("parent_asset_path") == PREFAB and row["type"] in ("GameObject", "RectTransform", "MonoBehaviour"):
            try:
                objects[row["path_id"]] = decode(root, row)
            except ValueError:
                continue  # Unrelated SerializeReference UI scripts are not needed.
    transforms = {key: value for key, value in objects.items() if "m_AnchoredPosition" in value}
    root_id = next(key for key, value in transforms.items()
                   if objects[value["m_GameObject"]["m_PathID"]]["m_Name"] == "Loading")
    def build(key):
        transform = transforms[key]
        obj = objects[transform["m_GameObject"]["m_PathID"]]
        components = [objects.get(item["component"]["m_PathID"], {}) for item in obj["m_Component"]]
        return {"name": obj["m_Name"], "transform": transform,
                "image": next((c for c in components if "m_Sprite" in c), None),
                "text": next((c for c in components if "m_fontSize" in c), None),
                "children": [build(c["m_PathID"]) for c in transform["m_Children"]]}
    layout = {"schema": 1, "canvas": [1920, 1080], "root": build(root_id),
              "source_prefab": PREFAB, "adaptation": "real client milestones and localized phase text only"}
    clip_row = next(row for row in rows if row.get("original_path") ==
                    "assets/beyond/initialassets/ui/animations/loadingicon_loop.anim")
    clip = decode(root, clip_row)
    layout["rotation"] = clip["m_RotationCurves"][0]["curve"]["m_Curve"]
    layout["sample_rate"] = clip["m_SampleRate"]
    resources = {}
    texture_paths = {}
    for row in rows:
        if row["type"] == "Texture2D" and row.get("name") in ("login_loading_bg01", "login_loading_bg02", "login_loading_icon"):
            name = row["name"] + ".png"
            shutil.copyfile(root / row["output_path"], output / name)
            texture_paths[row["parent_asset_path"]] = name
        if row["type"] == "Font" and "/defaultfont_cn.ttf." in row.get("raw_path", ""):
            font = decode(root, row)
            data = font["m_FontData"]
            (output / "defaultfont_cn.ttf").write_bytes(bytes(data))
    # UIImage references a Sprite, not the underlying Texture2D PathID.
    for row in rows:
        if row["type"] == "Sprite" and row.get("parent_asset_path") in texture_paths:
            resources[str(row["path_id"])] = texture_paths[row["parent_asset_path"]]
    layout["sprites"] = resources
    layout["source_bundles"] = sorted({clip_row["source_path"], next(row["source_path"] for row in rows
                                                                  if row.get("parent_asset_path") == PREFAB)})
    (output / "layout.json").write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    (output / "PROVENANCE.json").write_text(json.dumps({"origin": "read-only local game export", "files": hashes}, indent=2), encoding="utf-8")
    print("Prepared original login loading prefab, sprites, font and 60Hz rotation curve")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.export_root.resolve(), args.out.resolve())
