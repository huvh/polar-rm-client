"""Offline importer contract; no Qt, installed game, or runtime UnityPy required.

Optional real-export round trip: set ENDFIELD_SETTINGS_EXPORT_BASE to the explicit
tmp_endfield_work directory and ENDFIELD_SETTINGS_FONT to the explicit font file.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import prepare_endfield_settings as importer


def digest(data):
    return hashlib.sha256(data).hexdigest()


def png(width=128, height=128):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    pixels = (b"\0" + b"\xff\xff\xff\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def pointer(pid):
    return {"m_FileID": 0, "m_PathID": pid}


class SettingsImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="settings-import-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.roots = [self.base / "primary", self.base / "extra"]
        for root in self.roots:
            root.mkdir()
        self.output = self.base / "pack"
        self.font = self.base / "font.ttf"
        self.font.write_bytes(b"\x00\x01\x00\x00" + struct.pack(">HHHH", 1, 0, 0, 0)
                              + b"test" + struct.pack(">III", 0, 28, 4) + b"font")
        self.rows = [[], []]
        self.images = {}
        self.sprite_rows = {}
        self.texture_rows = {}
        self.patch_geometry = patch.object(importer, "GEOMETRY_COUNT", 2)
        self.patch_geometry.start()
        self.addCleanup(self.patch_geometry.stop)
        self.patch_item_count = patch.object(importer, "ITEM_CELL_COUNT", 2)
        self.patch_item_count.start()
        self.addCleanup(self.patch_item_count.stop)
        self.patch_decode = patch.object(importer, "decode", side_effect=self.decode)
        self.patch_decode.start()
        self.addCleanup(self.patch_decode.stop)
        # All textures deliberately share ONE parent path. A path-keyed dict
        # would overwrite every texture except the last one.
        for i, name in enumerate((*importer.NAMES, *importer.SPRITES)):
            texture = self.add(0, "Texture2D", 100 + i, name, {})
            texture["output_path"] = f"images/{i}.png"
            image_path = self.roots[0] / texture["output_path"]
            image_path.parent.mkdir(exist_ok=True)
            image_path.write_bytes(png(128 + i, 128))
            self.images[name + ".png"] = image_path.read_bytes()
            sprite_id = importer.SPRITES.get(name, 200 + i)
            sprite = self.add(0, "Sprite", sprite_id, "", {
                "m_RD": {"texture": pointer(texture["path_id"]),
                         "textureRect": {"x": 1.25, "y": 1.0, "width": 79.5, "height": 80.0},
                         "textureRectOffset": {"x": 0, "y": 0}, "settingsRaw": 64},
                "m_Rect": {"x": 1.0, "y": 1.0, "width": 80.0, "height": 80.0},
                "m_Border": {"x": 18.0, "y": 24.0, "z": 26.0, "w": 27.0},
                "m_PixelsToUnits": 100.0, "m_Pivot": {"x": 0.5, "y": 0.5},
                "m_Offset": {"x": 0.0, "y": 0.0}})
            self.sprite_rows[name], self.texture_rows[name] = sprite, texture
        self.transforms = []
        self.item_transforms = []
        for prefab, cab, transforms in ((importer.PREFAB, "prefab", self.transforms),
                                        (importer.ITEM_CELL_PREFAB, "widget", self.item_transforms)):
            for i in range(2):
                self.add(1, "GameObject", 400 + i, f"node{i}", {"m_Name": f"node{i}",
                         "m_Component": [{"component": pointer(300 + i)}]}, prefab, cab=cab)
                value = {k: {"x": float(i), "y": float(i)} for k in importer.GEOMETRY_KEYS}
                value.update(m_GameObject=pointer(400 + i), m_Father=pointer(300 if i else 0),
                             m_Children=[] if i else [pointer(301)])
                transforms.append(self.add(1, "RectTransform", 300 + i, "", value, prefab, cab=cab))
        self.clips = []
        for i, name in enumerate(importer.CLIPS):
            count, key_count = importer.CLIP_COUNTS[name]
            curves = [{"path": f"Node/{n}", "attribute": "m_Alpha", "classID": 225,
                       "curve": {"m_Curve": [{"time": k / 60, "value": float(k)} for k in
                                              range(1 if n == 0 and key_count % 2 else 2)]}}
                      for n in range(count)]
            self.clips.append(self.add(1, "AnimationClip", 500 + i, name,
                                       {"m_Name": name, "m_SampleRate": 60.0, "m_FloatCurves": curves},
                                       f"assets/{name}.anim", cab="clips"))

    def add(self, root_index, kind, pid, name, value, asset="assets/shared.prefab", cab="images"):
        row = {"status": "exported", "source_path": f"Data/Bundles/{cab}.ab", "serialized_file": cab,
               "path_id": pid, "class_id": {"Texture2D": 28, "Sprite": 213, "GameObject": 1,
                                            "RectTransform": 224, "AnimationClip": 74}[kind],
               "type": kind, "name": name, "parent_asset_path": asset,
               "raw_path": f"raw/{cab}/{kind}_{pid}.raw", "metadata_path": f"raw/{cab}/{kind}_{pid}.metadata.json"}
        self.rows[root_index].append(row)
        self.set_value(row, value)
        return row

    def row_root(self, row):
        return next(root for root, rows in zip(self.roots, self.rows) if any(r is row for r in rows))

    def set_value(self, row, value):
        root = self.row_root(row)
        raw = json.dumps(value).encode()
        path = root / row["raw_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        row["source_size"] = len(raw)
        md = {k: row[k] for k in ("serialized_file", "path_id", "class_id", "type", "parent_asset_path", "source_size")}
        md.update(bundle_path=row["source_path"], endian="LittleEndian",
                  serialized_type={"classID": row["class_id"], "m_Type": {"m_Nodes": [{"m_Level": 0}]}}, externals=[])
        (root / row["metadata_path"]).write_text(json.dumps(md), encoding="utf8")

    @staticmethod
    def decode(root, row):
        return json.loads((root / row["raw_path"]).read_bytes())

    def change(self, row, callback):
        value = self.decode(self.row_root(row), row)
        callback(value)
        self.set_value(row, value)

    def write_indexes(self):
        for root, rows in zip(self.roots, self.rows):
            (root / "_index.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf8")

    def run_import(self, reverse=False):
        self.write_indexes()
        roots = self.roots[::-1] if reverse else self.roots
        return importer.prepare(roots[0], self.font, self.output, roots[1:])

    def rejects(self, message=None):
        with self.assertRaises((ValueError, OSError)) as caught:
            self.run_import()
        if message:
            self.assertIn(message, str(caught.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pack.staging-*")), [])

    def test_complete_manifest_preserves_png_and_exact_sprite_fields(self):
        manifest = self.run_import()
        self.assertEqual(manifest["schema"], 2)
        expected = set(self.images) | {"source_layout.json", "defaultfont_cn.ttf"}
        self.assertEqual(set(manifest["files"]), expected)
        self.assertEqual({p.name for p in self.output.iterdir()}, expected | {"PROVENANCE.json"})
        for name, hash_value in manifest["files"].items():
            self.assertEqual(digest((self.output / name).read_bytes()), hash_value)
        for name, data in self.images.items():
            self.assertEqual((self.output / name).read_bytes(), data)
            sprite = manifest["sprites"][name]
            self.assertEqual(sprite["rect"], {"x": 1, "y": 1, "width": 80, "height": 80})
            self.assertEqual(sprite["border"], {"x": 18, "y": 24, "z": 26, "w": 27})
            self.assertEqual(sprite["pixels_per_unit"], 100)
            self.assertEqual(sprite["render_data"]["textureRect"]["x"], 1.25)
            for source in (sprite["sprite_source"], sprite["texture_source"]):
                root = next(Path(r["path"]) for r in manifest["inputs"] if r["id"] == source["export_root"])
                for field in ("raw", "metadata"):
                    record = source[field]
                    raw = (root / record["path"]).read_bytes()
                    self.assertEqual(record["sha256"], digest(raw))
                    self.assertEqual(record["size"], len(raw))
        for prefab in (importer.PREFAB, importer.ITEM_CELL_PREFAB):
            self.assertEqual(len(manifest["layout_sources"]["prefabs"][prefab]["geometry"]), 2)
            self.assertEqual(len(manifest["layout_sources"]["prefabs"][prefab]["game_objects"]), 2)
        layout = json.loads((self.output / "source_layout.json").read_bytes())
        self.assertEqual(layout["geometry"], layout["layouts_by_prefab"][importer.PREFAB]["geometry"])
        self.assertEqual(set(layout["layouts_by_prefab"]), {importer.PREFAB, importer.ITEM_CELL_PREFAB})
        self.assertEqual(layout["logical_reference"], [3840, 2160])
        self.assertNotIn("canvas", layout)
        self.assertEqual(layout["canvas_scaler"]["status"], "runtime_rules_unavailable")
        self.assertEqual(set(manifest["layout_sources"]["clips"]), set(importer.CLIPS))
        self.assertEqual(manifest["font_source"]["sha256"], digest(self.font.read_bytes()))
        self.assertEqual(manifest["vector_adaptations"], [])
        for root in manifest["inputs"]:
            self.assertEqual(root["index_sha256"], digest((Path(root["path"]) / "_index.jsonl").read_bytes()))

    def test_extra_root_geometry_and_clips_decode_from_their_own_root(self):
        manifest = self.run_import(reverse=True)
        self.assertTrue(all(s["export_root"] == "root0" for s in
                            manifest["layout_sources"]["prefabs"][importer.PREFAB]["geometry"]))

    def test_missing_sprite_is_error_not_vector_fallback(self):
        self.rows[0].remove(self.sprite_rows["row_bg"])
        self.rejects("Sprite role row_bg")

    def test_missing_named_texture_is_error(self):
        self.rows[0].remove(self.texture_rows[importer.NAMES[0]])
        self.rejects("named Texture2D")

    def test_duplicate_identity_even_across_roots_is_rejected(self):
        self.rows[1].append(copy.deepcopy(self.rows[0][0]))
        self.rejects("duplicate object identity")

    def test_distinct_sprite_objects_with_same_role_path_id_are_ambiguous(self):
        row = self.sprite_rows["row_bg"]
        self.add(1, "Sprite", row["path_id"], "", self.decode(self.roots[0], row), cab="collision")
        self.rejects("Sprite role row_bg")

    def test_ambiguous_named_texture_is_rejected(self):
        self.add(1, "Texture2D", 900, importer.NAMES[0], {}, cab="collision")
        self.rejects("named Texture2D")

    def test_multiple_sprites_for_one_named_texture_are_rejected(self):
        self.add(0, "Sprite", 901, "", self.decode(self.roots[0], self.sprite_rows[importer.NAMES[0]]))
        self.rejects("Sprite for named Texture2D")

    def test_wrong_texture_pointer_is_not_resolved_by_shared_parent_path(self):
        self.change(self.sprite_rows["row_bg"], lambda v: v["m_RD"].update(texture=pointer(999999)))
        self.rejects("Texture2D reference")

    def test_missing_named_sprite_is_rejected(self):
        self.rows[0].remove(self.sprite_rows[importer.NAMES[0]])
        self.rejects("Sprite for named Texture2D")

    def test_missing_png_is_rejected(self):
        (self.roots[0] / self.texture_rows["row_bg"]["output_path"]).unlink()
        self.rejects("missing input file")

    def test_corrupt_png_is_rejected(self):
        (self.roots[0] / self.texture_rows["row_bg"]["output_path"]).write_bytes(png()[:-8])
        self.rejects("PNG")

    def test_invalid_rect_border_or_ppu_are_rejected(self):
        row = self.sprite_rows["row_bg"]
        original = self.decode(self.roots[0], row)
        mutations = (lambda v: v["m_Rect"].update(width=1000),
                     lambda v: v["m_Border"].update(x=1000),
                     lambda v: v.update(m_PixelsToUnits=0),
                     lambda v: v["m_Rect"].update(x=float("nan")))
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = copy.deepcopy(original)
                mutate(value)
                self.set_value(row, value)
                self.rejects("Sprite")

    def test_missing_raw_and_metadata_inputs_are_rejected(self):
        for row, field in ((self.transforms[0], "raw_path"), (self.clips[0], "metadata_path")):
            with self.subTest(field=field):
                path = self.row_root(row) / row[field]
                data = path.read_bytes()
                path.unlink()
                self.rejects("missing input file")
                path.write_bytes(data)

    def test_truncated_raw_is_rejected(self):
        row = self.clips[0]
        path = self.row_root(row) / row["raw_path"]
        path.write_bytes(path.read_bytes()[:-1])
        self.rejects("raw size mismatch")

    def test_mismatched_metadata_identity_is_rejected(self):
        row = self.clips[0]
        path = self.row_root(row) / row["metadata_path"]
        value = json.loads(path.read_bytes())
        value["path_id"] += 1
        path.write_text(json.dumps(value))
        self.rejects("metadata path_id mismatch")

    def test_missing_type_tree_is_rejected(self):
        row = self.clips[0]
        path = self.row_root(row) / row["metadata_path"]
        value = json.loads(path.read_bytes())
        value["serialized_type"]["m_Type"]["m_Nodes"] = []
        path.write_text(json.dumps(value))
        self.rejects("missing original type tree")

    def test_input_changed_during_decode_is_rejected(self):
        def changing_decode(root, row):
            value = self.decode(root, row)
            if row["type"] == "Sprite":
                path = root / row["raw_path"]
                path.write_bytes(path.read_bytes() + b" ")
            return value
        with patch.object(importer, "decode", side_effect=changing_decode):
            self.rejects("input changed while decoding")

    def test_external_texture_reference_is_resolved_by_metadata_not_parent(self):
        row = self.sprite_rows["row_bg"]
        self.change(row, lambda v: v["m_RD"].update(texture={"m_FileID": 1, "m_PathID": 902}))
        self.add(1, "Texture2D", 902, "external_image", {}, cab="external")
        texture = self.rows[1][-1]
        texture["output_path"] = "external.png"
        (self.roots[1] / "external.png").write_bytes(png())
        path = self.row_root(row) / row["metadata_path"]
        md = json.loads(path.read_bytes())
        md["externals"] = [{"fileName": "external"}]
        path.write_text(json.dumps(md))
        manifest = self.run_import()
        self.assertEqual(manifest["sprites"]["row_bg.png"]["texture_source"]["serialized_file"], "external")

    def test_missing_or_malformed_index_leaves_no_output(self):
        self.write_indexes()
        index = self.roots[0] / "_index.jsonl"
        for data in (b"", b"{invalid json", b"[]", b'{"path_id":true}'):
            with self.subTest(index=data):
                index.write_bytes(data)
                with self.assertRaises(ValueError):
                    importer.prepare(self.roots[0], self.font, self.output, self.roots[1:])
                self.assertFalse(self.output.exists())
        index.unlink()
        with self.assertRaisesRegex(ValueError, "missing input file"):
            importer.prepare(self.roots[0], self.font, self.output, self.roots[1:])
        self.assertFalse(self.output.exists())

    def test_duplicate_roots_are_rejected(self):
        self.write_indexes()
        with self.assertRaisesRegex(ValueError, "duplicate export roots"):
            importer.prepare(self.roots[0], self.font, self.output, [self.roots[0]])
        self.assertFalse(self.output.exists())

    def test_missing_geometry_row_is_rejected(self):
        self.rows[1].remove(self.transforms[1])
        self.rejects("incomplete prefab")

    def test_missing_fullwidth_widget_geometry_is_rejected(self):
        self.rows[1].remove(self.item_transforms[1])
        self.rejects("gamesettingitemcellv2.prefab")

    def test_disconnected_geometry_is_rejected(self):
        self.change(self.transforms[1], lambda v: v.update(m_Father=pointer(0)))
        self.rejects("prefab root")

    def test_broken_parent_child_link_is_rejected(self):
        self.change(self.transforms[0], lambda v: v.update(m_Children=[]))
        self.rejects("parent/child")

    def test_missing_geometry_game_object_is_rejected(self):
        self.rows[1][:] = [r for r in self.rows[1] if r["path_id"] != 400]
        self.rejects("GameObject reference")

    def test_missing_geometry_field_is_rejected(self):
        self.change(self.transforms[0], lambda v: v.pop("m_Pivot"))
        self.rejects("m_Pivot")

    def test_missing_or_ambiguous_clip_is_rejected(self):
        row = self.clips.pop()
        self.rows[1].remove(row)
        self.rejects("AnimationClip")
        self.rows[1].append(row)
        self.add(1, "AnimationClip", 999, row["name"], self.decode(self.roots[1], row), cab="collision")
        self.rejects("AnimationClip")

    def test_incomplete_clip_curves_or_keyframes_are_rejected(self):
        row = self.clips[0]
        original = self.decode(self.roots[1], row)
        for mutate in (lambda v: v["m_FloatCurves"].pop(),
                       lambda v: v["m_FloatCurves"][1]["curve"]["m_Curve"].pop(),
                       lambda v: v.update(m_SampleRate=30),
                       lambda v: v["m_FloatCurves"].__setitem__(1, v["m_FloatCurves"][0])):
            value = copy.deepcopy(original)
            mutate(value)
            self.set_value(row, value)
            self.rejects("AnimationClip")

    def test_metadata_path_traversal_and_absolute_paths_are_rejected_before_read(self):
        row = self.texture_rows["row_bg"]
        for unsafe in ("../outside.raw", "/outside.raw", "C:\\game\\file.raw", "\\\\server\\share\\file", "raw/file:stream"):
            with self.subTest(path=unsafe):
                row["raw_path"] = unsafe
                self.rejects("unsafe export-relative path")

    def test_symlink_escape_is_rejected(self):
        outside = self.base / "outside.raw"
        outside.write_bytes(b"do not read")
        link = self.roots[0] / "escaped.raw"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("host does not permit creating file symlinks")
        self.texture_rows["row_bg"]["raw_path"] = link.name
        self.rejects("escapes root")

    def test_invalid_font_is_rejected(self):
        self.font.write_bytes(b"not a font")
        self.rejects("font")

    def test_existing_output_is_never_touched(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "output already exists"):
            self.run_import()
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"original")

    def test_output_may_not_overlap_export(self):
        self.output = self.roots[0] / "pack"
        self.rejects("overlaps an input")

    def test_decode_exception_leaves_no_output(self):
        with patch.object(importer, "decode", side_effect=RuntimeError("decode failed")):
            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                self.run_import()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pack.staging-*")), [])

    def test_staging_write_failure_rolls_back(self):
        write = Path.write_bytes
        def fail(path, data):
            if ".staging-" in str(path) and path.name == "source_layout.json":
                raise OSError("simulated disk failure")
            return write(path, data)
        with patch.object(Path, "write_bytes", fail):
            self.rejects("simulated disk failure")

    def test_publish_failure_rolls_back(self):
        with patch.object(Path, "rename", side_effect=OSError("simulated rename failure")):
            self.rejects("simulated rename failure")

    def test_output_appearing_during_staging_is_not_removed(self):
        write = Path.write_bytes
        def create_competing_output(path, data):
            if ".staging-" in str(path) and not self.output.exists():
                self.output.mkdir()
                write(self.output / "keep.txt", b"competing output")
            return write(path, data)
        with patch.object(Path, "write_bytes", create_competing_output):
            with self.assertRaisesRegex(ValueError, "output appeared during import"):
                self.run_import()
        self.assertEqual((self.output / "keep.txt").read_bytes(), b"competing output")
        self.assertEqual(list(self.base.glob(".pack.staging-*")), [])

    def test_importing_tool_does_not_import_unitypy(self):
        result = subprocess.run([sys.executable, "-c", "import sys; from tools import prepare_endfield_settings; "
                                 "assert not any(n == 'UnityPy' or n.startswith('UnityPy.') for n in sys.modules)"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ExistingPackIntegrityTests(unittest.TestCase):
    def test_existing_original_resource_inventory_hashes_and_layout(self):
        root = ROOT / "assets/endfield_settings"
        manifest = json.loads((root / "PROVENANCE.json").read_text(encoding="utf8"))
        expected_sprites = {name + ".png" for name in (*importer.NAMES, *importer.SPRITES)}
        self.assertEqual(set(manifest["sprites"]), expected_sprites)
        self.assertEqual(set(manifest["files"]), expected_sprites | {"source_layout.json", "defaultfont_cn.ttf"})
        for name, expected in manifest["files"].items():
            self.assertEqual(digest((root / name).read_bytes()), expected, name)
        for name, item in manifest["sprites"].items():
            self.assertEqual(item["sha256"], manifest["files"][name])
            self.assertTrue(item["asset"])
            self.assertTrue(item["bundle"])
        layout = json.loads((root / "source_layout.json").read_bytes())
        self.assertEqual(layout["prefab"], importer.PREFAB)
        self.assertEqual(len(layout["geometry"]), importer.GEOMETRY_COUNT)
        self.assertEqual(set(layout["clips"]), set(importer.CLIPS))
        for name, (curves, keys) in importer.CLIP_COUNTS.items():
            clip = layout["clips"][name]
            self.assertEqual(clip["sample_rate"], 60)
            self.assertEqual(len(clip["curves"]), curves)
            self.assertEqual(sum(len(c["curve"]["m_Curve"]) for c in clip["curves"]), keys)

    @unittest.skipUnless(os.environ.get("ENDFIELD_SETTINGS_EXPORT_BASE") and os.environ.get("ENDFIELD_SETTINGS_FONT"),
                         "real-export test needs explicit offline export/font paths")
    def test_explicit_real_exports_round_trip_without_changing_original_pack(self):
        self.assertIsNotNone(importlib.util.find_spec("UnityPy"), "real-export test requires tooling-only UnityPy")
        base = Path(os.environ["ENDFIELD_SETTINGS_EXPORT_BASE"])
        font = Path(os.environ["ENDFIELD_SETTINGS_FONT"])
        roots = [base / name for name in ("settings_original", "settings_common_original",
                                         *(f"common_extra_{i}" for i in range(5)))]
        original = json.loads((ROOT / "assets/endfield_settings/PROVENANCE.json").read_bytes())
        with tempfile.TemporaryDirectory(prefix="settings-real-import-test-") as tmp:
            output = Path(tmp) / "pack"
            manifest = importer.prepare(roots[0], font, output, roots[1:])
            self.assertEqual(set(manifest["files"]), set(original["files"]))
            for filename in set(original["files"]) - {"source_layout.json"}:
                self.assertEqual(manifest["files"][filename], original["files"][filename], filename)
            layout = json.loads((output / "source_layout.json").read_bytes())
            previous_layout = json.loads((ROOT / "assets/endfield_settings/source_layout.json").read_bytes())
            self.assertEqual(layout["geometry"], previous_layout["geometry"])
            self.assertEqual(layout["clips"], previous_layout["clips"])
            self.assertEqual(len(layout["layouts_by_prefab"][importer.ITEM_CELL_PREFAB]["geometry"]), 26)
            self.assertIn("GameSettingItemCellV2", layout["layouts_by_prefab"][importer.ITEM_CELL_PREFAB]["game_object_names"].values())
            self.assertNotIn("canvas", layout)
            self.assertEqual(layout["logical_reference"], [3840, 2160])
            self.assertEqual(manifest["canvas_scaler"]["status"], "runtime_rules_unavailable")
            self.assertEqual({p.name for p in output.iterdir()}, set(manifest["files"]) | {"PROVENANCE.json"})
            expected = {"bg_setting_dropdown": ((80, 80), (28, 28, 28, 28)),
                        "button_bg": ((116, 96), (57, 0, 57, 0)),
                        "toggle_bg": ((94, 78), (40, 0, 42, 0)),
                        "toggle_ring": ((44, 44), (21, 21, 22, 22)),
                        "row_bg": ((58, 58), (18, 24, 26, 27))}
            for name, (size, border) in expected.items():
                sprite = manifest["sprites"][name + ".png"]
                self.assertEqual(sprite["rect"], dict(zip(("x", "y", "width", "height"), (1, 1, *size))))
                self.assertEqual(sprite["border"], dict(zip(("x", "y", "z", "w"), border)))
                self.assertEqual(sprite["pixels_per_unit"], 100)
            for filename, info in manifest["sprites"].items():
                source = info["sprite_source"]
                root = Path(manifest["inputs"][int(source["export_root"][4:])]["path"])
                value = importer.decode(root, {"raw_path": source["raw"]["path"],
                                               "metadata_path": source["metadata"]["path"]})
                self.assertEqual(info["rect"], value["m_Rect"], filename)
                self.assertEqual(info["border"], value["m_Border"], filename)
                self.assertEqual(info["pixels_per_unit"], value["m_PixelsToUnits"], filename)
                self.assertEqual(digest((output / filename).read_bytes()), info["sha256"])


if __name__ == "__main__":
    unittest.main()
