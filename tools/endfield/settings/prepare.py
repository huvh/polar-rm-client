"""从 EndfieldStudio original --full 导出准备独立设置资源包。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.endfield.prepare_boot import decode
from tools.endfield.wiki.prepare import json_numbers


TEXTURES = {
    "row_left": ("deco_settings_bg_contour", .14901961386203766),
    "row_bg": ("bg_common_r2_p2_02", .4),
    "row_right": ("deco_settings_mask_texture", .2),
    "row_edge": ("deco_settings_texture", .10196078568696976),
    "tabs_bg": ("deco_settings_texture02", .2),
    "tab_selected": ("tab_slc_pc_03", 1),
    "close": ("close_btn_bg", 1),
    "tab_display": ("icon_settings_computer", 1),
    "tab_audio": ("icon_settings_audio", 1),
    "tab_game": ("icon_settings_control", 1),
    "tab_keyboard": ("icon_settings_keystroke", 1),
    "tab_crosshair": ("icon_settings_language", 1),
    "tab_hud": ("icon_settings_usercenter", 1),
    "background_deco": ("deco_settings_bg_contour", 1),
}
CLIPS = ("gamesetting_in", "gamesetting_out", "gamesetting_change", "gamesetting_cell_in",
         "common_toggle_to_left01", "common_toggle_to_right01", "dropdownlist_in", "dropdownlist_out",
         "setting_tabcell_selected_in", "setting_tabcell_selected_in01")


def prepare(exports, output, bundle_index=None, game_vfs=None):
    from PIL import Image
    rows = []
    for folder in exports:
        folder = folder.absolute()
        with (folder / "_index.jsonl").open(encoding="utf-8") as index:
            for line in index:
                row = json.loads(line)
                for key in ("metadata_path", "raw_path", "output_path"):
                    if row.get(key):
                        row[key] = str(folder / row[key])
                rows.append(row)
    output.mkdir(parents=True, exist_ok=True)
    provenance, used, slices = [], [], {}

    def record(row, target):
        used.append(row)
        provenance.append({"file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                           "bundle": row["source_path"], "object": row["path_id"],
                           "source": row.get("original_path") or row.get("parent_asset_path")})

    for name, (original, opacity) in TEXTURES.items():
        row = next(r for r in rows if r["type"] == "Texture2D" and r.get("name") == original)
        img = Image.open(row["output_path"]).convert("RGBA")
        if name == "row_bg":
            sprite_row = next(r for r in rows if r.get("path_id") == 148237939410474912)
            sprite = decode(Path("."), sprite_row)
            rect = sprite["m_RD"]["textureRect"]
            x,y,w,h = (round(rect[k]) for k in ("x","y","width","height"))
            img = img.crop((x,img.height-y-h,x+w,img.height-y))
            slices[name] = [sprite["m_Border"][k] for k in "xwzy"]
        if opacity != 1:
            img.putalpha(img.getchannel("A").point(lambda a: round(a*opacity)))
        if name == "close":
            img = img.crop(img.getbbox())
        target = output / (name + ".png")
        img.save(target)
        record(row, target)
    clips = {}
    for name in CLIPS:
        row = next(r for r in rows if r["type"] == "AnimationClip" and r.get("name") == name)
        clip = decode(Path("."), row)
        clips[name] = {key: clip[key] for key in ("m_FloatCurves", "m_PositionCurves", "m_ScaleCurves", "m_SampleRate")}
        used.append(row)
        provenance.append({"clip": name, "bundle": row["source_path"], "object": row["path_id"],
                           "raw_sha256": hashlib.sha256(Path(row["raw_path"]).read_bytes()).hexdigest()})
    fonts = [r for r in rows if r["type"] == "Font" and "defaultfont_cn.ttf" in str(r.get("parent_asset_path"))]
    if fonts:
        row = fonts[0]
        target = output / "defaultfont_cn.ttf"
        target.write_bytes(bytes(decode(Path("."), row)["m_FontData"]))
        record(row, target)
    prefab = next(r for r in rows if r["type"] == "GameObject" and
                  (r.get("parent_asset_path") or "").endswith("/gamesettingpanel.prefab"))
    used.append(prefab)
    scroll_go = next(r for r in rows if r.get("path_id") == 1903948918707663318)
    component_ids = {c["component"]["m_PathID"] for c in decode(Path("."),scroll_go)["m_Component"]}
    scroll_rows = [r for r in rows if r.get("path_id") in component_ids and r["type"] == "MonoBehaviour"]
    decoded = [(r,decode(Path("."),r)) for r in scroll_rows]
    scroll_row,scroll = next((r,d) for r,d in decoded if "smoothScrollTweenSpd" in d)
    mask = next(d for _,d in decoded if "m_Softness" in d)
    scroll_fields = ("m_MovementType","m_Elasticity","m_Inertia","m_DecelerationRate","m_ScrollSensitivity",
                     "smoothScrollTweenSpd","smoothScrollTweenEase","smoothScrollTweenMaxDur","_enableOverScrollEffect")
    scroll_config = {key:scroll[key] for key in scroll_fields}
    scroll_config["mask_softness"] = mask["m_Softness"]
    scroll_config["mask_padding"] = mask["m_Padding"]
    used.append(scroll_row)
    provenance.append({"configuration":"settings_scroll","bundle":scroll_row["source_path"],
                       "object":scroll_row["path_id"],"source":scroll_row["parent_asset_path"],
                       "raw_sha256":hashlib.sha256(Path(scroll_row["raw_path"]).read_bytes()).hexdigest()})
    data = {"schema": 1, "canvas": [1920, 1080], "clips": clips, "slices": slices,
            "scroll":scroll_config,
            "source_prefab": prefab["parent_asset_path"],
            "adaptation": "RM preference pages retain their identity, transactions and safety. Qt paints the extracted textures and samples Unity tracks; game scene blur/shaders are not embedded."}
    (output / "source.json").write_text(json.dumps(json_numbers(data), ensure_ascii=False), encoding="utf-8")
    checked = []
    if bundle_index:
        # 主包与初始包的chunk位于不同VFS目录，逐包查找实际文件再校验。
        index = json.loads(bundle_index.read_text(encoding="utf-8"))
        wanted = {r["source_path"] for r in used}
        for block in index["blocks"]:
            for chunk in block["chunks"]:
                for entry in chunk["files"]:
                    if entry["name"] not in wanted:
                        continue
                    paths = list(game_vfs.glob("*/" + chunk["name"]))
                    if len(paths) != 1:
                        raise ValueError("Cannot locate unique game chunk: " + chunk["name"])
                    with paths[0].open("rb") as stream:
                        stream.seek(entry["offset"])
                        raw = stream.read(entry["length"])
                    digest = hashlib.md5(raw).hexdigest()
                    expected = bytes.fromhex(entry["file_data_md5"])[::-1].hex()
                    if len(raw) != entry["length"] or digest != expected:
                        raise ValueError("Game bundle verification failed: " + entry["name"])
                    checked.append({"bundle": entry["name"], "chunk": str(paths[0]), "offset": entry["offset"],
                                    "length": len(raw), "md5": digest, "sha256": hashlib.sha256(raw).hexdigest()})
        if wanted - {r["bundle"] for r in checked}:
            raise ValueError("Bundle index does not cover every selected resource")
    (output / "PROVENANCE.json").write_text(json.dumps({"schema": 1, "files": provenance,
        "verified_game_bundles": checked}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "NOTICE.txt").write_text(
        "Arknights: Endfield UI textures, animation data and defaultfont_cn.ttf were extracted read-only "
        "from the user's local game installation for the requested local adaptation. "
        "Copyright and trademarks belong to their respective owners, including HYPERGRYPH. "
        "These materials are excluded from this project's source-code license. "
        "EndfieldStudio and UnityPy are offline tools and are not runtime dependencies.\n", encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.iterdir()) if p.is_file() and p.name != "MANIFEST.json"}
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Prepared {len(TEXTURES)} textures, {len(clips)} original clips, {len(checked)} verified game bundles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bundle-index", type=Path)
    parser.add_argument("--game-vfs", type=Path)
    args = parser.parse_args()
    if bool(args.bundle_index) != bool(args.game_vfs):
        parser.error("--bundle-index and --game-vfs must be supplied together")
    prepare(args.export, args.out, args.bundle_index, args.game_vfs)
