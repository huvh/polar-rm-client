"""Strict, offline EndfieldStudio original --raw --metadata settings importer.

Only explicit export roots and a font file are read; bundle paths are provenance,
never filesystem inputs. UnityPy is a lazy, tooling-only dependency. The client
does not need it. An existing output is never replaced, even if empty.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import shutil
import struct
import tempfile
import zlib
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.endfield.prepare_boot import decode


PREFAB = "assets/beyond/dynamicassets/gameplay/ui/prefabs/settings/gamesettingpanel.prefab"
ITEM_CELL_PREFAB = "assets/beyond/dynamicassets/gameplay/ui/prefabs/settings/widgets/gamesettingitemcellv2.prefab"
NAMES = ("icon_settings_computer", "icon_settings_audio", "icon_settings_control",
         "icon_settings_keystroke", "icon_settings_language", "icon_setting_controller",
         "deco_settings_bg_contour", "deco_settings_texture", "deco_settings_texture02",
         "bg_setting_dropdown", "reset_icon02")
# Actual Sprite references in GameSettingPanel, not similarly named guesses.
SPRITES = {"tab_selected": -5531568788748473073, "tab_fill": -2760948283806938507,
           "close": 773692512950687577, "arrow": 5212326347193956327,
           "row_bg": 148237939410474912, "button_bg": 3973521261885058101,
           "toggle_bg": -3568285162789770101, "toggle_ring": -4917338924575604315,
           "toggle_line": -2270496130516329645}
CLIPS = ("gamesetting_in", "gamesetting_out", "gamesetting_change",
         "common_toggle_to_left01", "common_toggle_to_right01")
# Version contract for this original prefab, NOT a generic Unity importer.
GEOMETRY_COUNT = 785
ITEM_CELL_COUNT = 26
CLIP_COUNTS = dict(zip(CLIPS, ((7, 13), (7, 14), (1, 2), (24, 48), (25, 49))))
GEOMETRY_KEYS = ("m_AnchoredPosition", "m_SizeDelta", "m_AnchorMin", "m_AnchorMax", "m_Pivot")
CLASS_IDS = {"Texture2D": 28, "Sprite": 213, "RectTransform": 224, "GameObject": 1, "AnimationClip": 74}


class ImportValidationError(ValueError):
    """Incomplete, ambiguous or unsafe original export; no pack is published."""


def require(condition, message):
    if not condition:
        raise ImportValidationError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique(rows, description):
    rows = list(rows)
    require(len(rows) == 1, f"{description}: expected exactly one object, found {len(rows)}")
    return rows[0]


def confined(root, relative):
    # Reject Windows paths even when tests/imports run on another OS. Resolve
    # symlinks/junctions before opening a file, not after reading it.
    require(isinstance(relative, str) and bool(relative), "missing export-relative path")
    win = PureWindowsPath(relative)
    require(not win.drive and not win.root and ".." not in win.parts and ":" not in relative,
            f"unsafe export-relative path: {relative!r}")
    path = (root / relative.replace("\\", "/")).resolve()
    require(path.is_relative_to(root), f"export path escapes root: {relative!r}")
    require(path.is_file(), f"missing input file: {path}")
    return path


def identity(row):
    return row["source_path"], row["serialized_file"], row["path_id"]


class Export:
    def __init__(self, roots):
        self.rows, self.roots, self.sources = [], [], {}
        self.objects, self.metadata, self.values, self.payloads = {}, {}, {}, {}
        require(len(set(roots)) == len(roots), "duplicate export roots")
        for number, root in enumerate(roots):
            index = confined(root, "_index.jsonl").read_bytes()
            root_id = f"root{number}"
            lines = index.decode("utf-8").splitlines()
            require(bool(lines), f"empty export index: {root}")
            self.roots.append({"id": root_id, "path": str(root), "index_sha256": sha256(index),
                               "index_rows": len(lines)})
            for line_number, line in enumerate(lines, 1):
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise ImportValidationError(f"{root}/_index.jsonl:{line_number}: {exc}") from exc
                require(isinstance(row, dict), f"invalid index object: {root}:{line_number}")
                for key in ("source_path", "serialized_file", "type"):
                    require(isinstance(row.get(key), str) and bool(row[key]),
                            f"missing {key}: {root}:{line_number}")
                require(type(row.get("path_id")) is int, f"invalid path_id: {root}:{line_number}")
                row = dict(row, export_root=root, root_id=root_id, index_line=line_number)
                key = identity(row)
                require(key not in self.objects, f"duplicate object identity: {key}")
                self.objects[key] = row
                self.rows.append(row)

    def read(self, row, field):
        path = confined(row["export_root"], row.get(field))
        data = path.read_bytes()
        require(bool(data), f"empty {field}: {path}")
        return data, {"path": row[field], "sha256": sha256(data), "size": len(data)}

    def validate(self, row):
        key = identity(row)
        if key in self.sources:
            return self.sources[key]
        require(row.get("status") == "exported" and not row.get("decode_error"),
                f"unsuccessful export: {key}")
        raw, raw_source = self.read(row, "raw_path")
        metadata, metadata_source = self.read(row, "metadata_path")
        md = json.loads(metadata)
        require(isinstance(md, dict), f"invalid metadata object: {key}")
        require(type(row.get("class_id")) is int and row["class_id"] == CLASS_IDS[row["type"]],
                f"invalid class_id: {key}")
        require(type(row.get("source_size")) is int and row["source_size"] == len(raw),
                f"raw size mismatch: {key}")
        for field, expected in (("bundle_path", row["source_path"]),
                                *((field, row.get(field)) for field in
                                  ("serialized_file", "path_id", "type", "class_id",
                                   "parent_asset_path", "source_size"))):
            require(md.get(field) == expected, f"metadata {field} mismatch: {key}")
        require(md.get("endian") == "LittleEndian", f"unsupported endian: {key}")
        serialized_type = md.get("serialized_type")
        require(isinstance(serialized_type, dict) and serialized_type.get("classID") == row["class_id"],
                f"type tree classID mismatch: {key}")
        tree = serialized_type.get("m_Type")
        require(isinstance(tree, dict) and isinstance(tree.get("m_Nodes"), list) and bool(tree["m_Nodes"]),
                f"missing original type tree: {key}")
        source = {"export_root": row["root_id"], "index_line": row["index_line"],
                  "bundle": row["source_path"], "serialized_file": row["serialized_file"],
                  "path_id": row["path_id"], "type": row["type"], "name": row.get("name"),
                  "asset": row.get("parent_asset_path"), "raw": raw_source,
                  "metadata": metadata_source}
        self.sources[key], self.metadata[key] = source, md
        # Snapshot consumed files so a changed input cannot be silently copied
        # after its manifest hash was computed.
        self.payloads[key] = {"raw_path": raw, "metadata_path": metadata}
        return source

    def value(self, row):
        key = identity(row)
        self.validate(row)
        if key not in self.values:
            value = decode(row["export_root"], row)
            for field, expected in self.payloads[key].items():
                require(self.read(row, field)[0] == expected, f"input changed while decoding: {key}")
            require(isinstance(value, dict), f"invalid decoded object: {key}")
            self.values[key] = value
        return self.values[key]

    def reference(self, row, pointer, expected_type):
        require(isinstance(pointer, dict) and type(pointer.get("m_FileID")) is int
                and type(pointer.get("m_PathID")) is int and pointer["m_PathID"] != 0,
                f"invalid {expected_type} reference: {identity(row)}")
        file_id, path_id = pointer["m_FileID"], pointer["m_PathID"]
        if file_id == 0:
            candidates = [self.objects.get((row["source_path"], row["serialized_file"], path_id))]
        else:
            self.validate(row)
            externals = self.metadata[identity(row)].get("externals", [])
            require(0 < file_id <= len(externals), f"invalid external file id: {identity(row)}")
            cab = externals[file_id - 1].get("fileName")
            require(bool(cab), "missing external serialized file name")
            candidates = [r for r in self.rows if r["serialized_file"] == cab and r["path_id"] == path_id]
        return unique((r for r in candidates if r and r["type"] == expected_type),
                      f"{expected_type} reference {file_id}:{path_id}")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector(value, keys, description):
    require(isinstance(value, dict) and all(finite(value.get(k)) for k in keys),
            f"invalid {description}")
    return {k: value[k] for k in keys}


def png_size(data):
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "invalid PNG signature")
    offset, dimensions, ended = 8, None, False
    while offset + 12 <= len(data):
        size, = struct.unpack_from(">I", data, offset)
        end = offset + 12 + size
        require(end <= len(data), "truncated PNG chunk")
        kind, payload = data[offset + 4:offset + 8], data[offset + 8:end - 4]
        crc, = struct.unpack_from(">I", data, end - 4)
        require(zlib.crc32(kind + payload) == crc, "PNG CRC mismatch")
        if dimensions is None:
            require(kind == b"IHDR" and size == 13, "missing PNG IHDR")
            dimensions = struct.unpack_from(">II", payload)
            require(all(dimensions), "empty PNG dimensions")
        offset = end
        if kind == b"IEND":
            require(size == 0 and end == len(data), "invalid PNG IEND")
            ended = True
            break
    require(ended, "missing PNG IEND")
    return list(dimensions)


def sprite_info(export, sprite, texture, dimensions):
    value = export.value(sprite)
    resolved = export.reference(sprite, value.get("m_RD", {}).get("texture"), "Texture2D")
    require(identity(resolved) == identity(texture), "Sprite texture reference mismatch")
    rect = vector(value.get("m_Rect"), ("x", "y", "width", "height"), "Sprite rect")
    border = vector(value.get("m_Border"), ("x", "y", "z", "w"), "Sprite border")
    ppu = value.get("m_PixelsToUnits")
    require(finite(ppu) and ppu > 0, "invalid Sprite pixels per unit")
    require(rect["x"] >= 0 and rect["y"] >= 0 and rect["width"] > 0 and rect["height"] > 0
            and rect["x"] + rect["width"] <= dimensions[0]
            and rect["y"] + rect["height"] <= dimensions[1], "Sprite rect outside texture")
    require(all(v >= 0 for v in border.values()) and border["x"] + border["z"] <= rect["width"]
            and border["y"] + border["w"] <= rect["height"], "Sprite border outside rect")
    rd = value["m_RD"]
    return {"rect": rect, "border": border, "pixels_per_unit": ppu,
            "pivot": vector(value.get("m_Pivot"), ("x", "y"), "Sprite pivot"),
            "offset": vector(value.get("m_Offset"), ("x", "y"), "Sprite offset"),
            "render_data": {k: rd[k] for k in ("textureRect", "textureRectOffset", "atlasRectOffset",
                                               "settingsRaw", "downscaleMultiplier") if k in rd},
            "sprite_source": export.validate(sprite)}


def prefab_geometry(export, prefab, expected_count):
    rows = [r for r in export.rows if r["type"] == "RectTransform" and r.get("parent_asset_path") == prefab]
    require(len(rows) == expected_count,
            f"incomplete prefab {prefab}: expected {expected_count} RectTransforms, found {len(rows)}")
    unique({(r["source_path"], r["serialized_file"]) for r in rows}, "prefab serialized file")
    transforms = {r["path_id"]: export.value(r) for r in rows}
    geometry, parents, children, game_objects, names = {}, {}, {}, set(), {}
    go_rows = []
    for row in rows:
        pid, value = row["path_id"], transforms[row["path_id"]]
        geometry[str(pid)] = {k: vector(value.get(k), ("x", "y"), k) for k in GEOMETRY_KEYS}
        go = export.reference(row, value.get("m_GameObject"), "GameObject")
        require(go.get("parent_asset_path") == prefab and identity(go)[:2] == identity(row)[:2],
                "RectTransform GameObject outside prefab")
        require(identity(go) not in game_objects, "multiple RectTransforms reference one GameObject")
        game_objects.add(identity(go))
        go_value = export.value(go)
        require(isinstance(go_value.get("m_Name"), str), "missing prefab GameObject name")
        names[str(pid)] = go_value["m_Name"]
        components = go_value.get("m_Component")
        require(isinstance(components, list) and sum(c.get("component") == {
            "m_FileID": 0, "m_PathID": pid} for c in components) == 1,
            "GameObject does not reference its RectTransform")
        go_rows.append(go)
        father = value.get("m_Father", {})
        require(father.get("m_FileID") == 0 and type(father.get("m_PathID")) is int,
                "invalid prefab parent")
        parents[pid] = father["m_PathID"]
        refs = value.get("m_Children")
        require(isinstance(refs, list), "missing prefab children")
        children[pid] = []
        for ref in refs:
            child = export.reference(row, ref, "RectTransform")
            require(child["path_id"] in transforms
                    and identity(child)[:2] == identity(row)[:2], "prefab child outside geometry")
            children[pid].append(child["path_id"])
        require(len(set(children[pid])) == len(children[pid]), "duplicate prefab child")
    root = unique((pid for pid, parent in parents.items() if parent == 0), "prefab root")
    for pid, parent in parents.items():
        require(pid == root or parent in transforms and pid in children[parent], "broken prefab parent/child link")
        require(all(parents[c] == pid for c in children[pid]), "inconsistent prefab child/parent link")
    visited, pending = set(), [root]
    while pending:
        pid = pending.pop()
        require(pid not in visited, "cyclic prefab geometry")
        visited.add(pid)
        pending.extend(children[pid])
    require(len(visited) == len(transforms), "disconnected prefab geometry")
    return {"geometry": geometry, "game_object_names": names}, {
        "geometry": [export.validate(r) for r in rows],
        "game_objects": [export.validate(r) for r in go_rows]}


def layout_data(export):
    layouts, prefab_sources = {}, {}
    for prefab, count in ((PREFAB, GEOMETRY_COUNT), (ITEM_CELL_PREFAB, ITEM_CELL_COUNT)):
        layouts[prefab], prefab_sources[prefab] = prefab_geometry(export, prefab, count)
    clips, clip_sources = {}, {}
    for name in CLIPS:
        row = unique((r for r in export.rows if r["type"] == "AnimationClip" and r.get("name") == name),
                     f"AnimationClip {name}")
        value = export.value(row)
        require(value.get("m_Name") == name, f"AnimationClip name mismatch: {name}")
        curves, sample_rate = value.get("m_FloatCurves"), value.get("m_SampleRate")
        require(sample_rate == 60 and isinstance(curves, list) and len(curves) == CLIP_COUNTS[name][0],
                f"incomplete AnimationClip curves/sample rate: {name}")
        bindings, key_count = set(), 0
        for curve in curves:
            binding = (curve.get("path"), curve.get("attribute"), curve.get("classID"))
            require(all(isinstance(v, str) and v for v in binding[:2]) and binding not in bindings,
                    f"invalid/duplicate AnimationClip binding: {name}")
            bindings.add(binding)
            keys = curve.get("curve", {}).get("m_Curve")
            require(isinstance(keys, list) and bool(keys), f"empty AnimationClip keyframes: {name}")
            last = -1
            for key in keys:
                require(finite(key.get("time")) and key["time"] >= 0 and key["time"] > last
                        and finite(key.get("value")), f"invalid AnimationClip keyframe: {name}")
                last = key["time"]
            key_count += len(keys)
        require(key_count == CLIP_COUNTS[name][1], f"incomplete AnimationClip keyframes: {name}")
        clips[name] = {"sample_rate": sample_rate, "curves": curves}
        clip_sources[name] = export.validate(row)
    return {"prefab": PREFAB, "geometry": layouts[PREFAB]["geometry"], "clips": clips,
            "layouts_by_prefab": layouts, "logical_reference": [3840, 2160],
            "logical_reference_status": "presentation adaptation reference only; not confirmed Unity Canvas dimensions",
            "canvas_scaler": {"status": "runtime_rules_unavailable",
                              "note": "Unity CanvasScaler runtime rules were not obtained; no scale mode or match rule inferred"}}, {
        "prefabs": prefab_sources, "clips": clip_sources}


def prepare(root: Path, font: Path, output: Path, extra_roots=()):
    roots = [Path(p).resolve() for p in (root, *extra_roots)]
    font, output = Path(font).resolve(), Path(output).absolute()
    # lexists behaviour: do not follow/replace even a dangling output symlink.
    require(not output.exists() and not output.is_symlink(), f"output already exists: {output}")
    output = output.resolve()
    require(not any(output.is_relative_to(r) or r.is_relative_to(output) for r in roots)
            and not font.is_relative_to(output), "output overlaps an input")
    export = Export(roots)
    require(font.is_file(), f"missing font file: {font}")
    font_data = font.read_bytes()
    require(len(font_data) >= 12 and font_data[:4] in (b"\x00\x01\x00\x00", b"OTTO"), "invalid sfnt font")
    table_count = struct.unpack_from(">H", font_data, 4)[0]
    require(table_count > 0 and len(font_data) >= 12 + table_count * 16, "truncated font table directory")
    for i in range(table_count):
        offset, length = struct.unpack_from(">II", font_data, 12 + i * 16 + 8)
        require(length > 0 and offset + length <= len(font_data), "truncated font table")
    selected = {}
    for name in NAMES:
        texture = unique((r for r in export.rows if r["type"] == "Texture2D" and r.get("name") == name),
                         f"named Texture2D {name}")
        # A prefab may contain many textures/Sprites with the same parent path.
        # Match actual PPtr, never overwrite a parent_asset_path dictionary.
        candidates = [r for r in export.rows if r["type"] == "Sprite"
                      and (r["source_path"], r["serialized_file"], r.get("parent_asset_path")) ==
                      (texture["source_path"], texture["serialized_file"], texture.get("parent_asset_path"))]
        matches = [r for r in candidates if identity(export.reference(
            r, export.value(r).get("m_RD", {}).get("texture"), "Texture2D")) == identity(texture)]
        selected[name] = texture, unique(matches, f"Sprite for named Texture2D {name}")
    for name, path_id in SPRITES.items():
        sprite = unique((r for r in export.rows if r["type"] == "Sprite" and r["path_id"] == path_id),
                        f"Sprite role {name} ({path_id})")
        texture = export.reference(sprite, export.value(sprite).get("m_RD", {}).get("texture"), "Texture2D")
        selected[name] = texture, sprite
    payloads, provenance = {}, {}
    for name, (texture, sprite) in selected.items():
        texture_source = dict(export.validate(texture))
        require(str(texture.get("output_path", "")).lower().endswith(".png"), f"missing PNG for {name}")
        data, source = export.read(texture, "output_path")
        texture_source["output"] = source
        dimensions = png_size(data)
        info = sprite_info(export, sprite, texture, dimensions)
        filename = name + ".png"
        payloads[filename] = data  # PNG is byte-for-byte original, NOT pre-cropped.
        provenance[filename] = {"asset": texture.get("parent_asset_path"), "bundle": texture["source_path"],
                                "sha256": sha256(data), "texture_size": dimensions,
                                "texture_source": texture_source, **info}
    layout, layout_sources = layout_data(export)
    payloads["source_layout.json"] = json.dumps(layout, ensure_ascii=False, separators=(",", ":"),
                                                allow_nan=False).encode("utf-8")
    payloads["defaultfont_cn.ttf"] = font_data
    manifest = {"schema": 2, "origin": "read-only local Endfield game export", "prefab": PREFAB,
                "sprites": provenance, "files": {name: sha256(data) for name, data in sorted(payloads.items())},
                "inputs": export.roots, "layout_sources": layout_sources,
                "font_source": {"path": str(font), "sha256": sha256(font_data), "size": len(font_data),
                                "kind": "explicit offline font file; original bundle not inferred"},
                "completeness": {"geometry_count": len(layout["geometry"]),
                                 "geometry_by_prefab": {p: len(v["geometry"]) for p, v in layout["layouts_by_prefab"].items()},
                                 "clip_curve_key_counts": CLIP_COUNTS, "sprite_count": len(provenance)},
                "logical_reference": layout["logical_reference"],
                "logical_reference_status": layout["logical_reference_status"],
                "canvas_scaler": layout["canvas_scaler"],
                "sprite_coordinates": {"rect_origin": "Unity bottom-left, texture pixels",
                                       "border_order": "x=left,y=bottom,z=right,w=top",
                                       "png_policy": "unchanged full Texture2D; crop rect once before 9-slice"},
                "vector_adaptations": [],
                "scope": "settings presentation adaptation; not a native Unity settings runtime"}
    payloads["PROVENANCE.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    # No output directory exists during validation. Stage on the same filesystem
    # and publish in one rename only after every byte/hash is ready.
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        for name, data in payloads.items():
            (stage / name).write_bytes(data)
        require(set(p.name for p in stage.iterdir()) == set(payloads), "staged file inventory mismatch")
        for name, data in payloads.items():
            require((stage / name).read_bytes() == data, f"staged file verification failed: {name}")
        require(not output.exists() and not output.is_symlink(), f"output appeared during import: {output}")
        stage.rename(output)
    finally:
        if stage.exists():
            require(stage.resolve().parent == output.parent, "refusing cleanup outside output parent")
            shutil.rmtree(stage)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--extra-root", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.export_root, args.font, args.out, args.extra_root)
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        parser.exit(1, f"Settings import failed (no pack published): {exc}\n")
    print(f"Prepared complete offline settings pack: {args.out.absolute()}")
