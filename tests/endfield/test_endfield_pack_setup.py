"""Synthetic integrity/transaction fixtures, never a visual/DLL qualification."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import struct
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.endfield import pack as pack
from tools.endfield import prepare_pack as prepare
from rm_client.ui.endfield.menu.native import library_path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


def mesh():
    return (b"PRMESH01" + struct.pack("<II", 3, 3) + struct.pack("<16d", *([1.] * 16))
            + struct.pack("<27f", *([0.] * 27)) + struct.pack("<3I", 0, 1, 2))


class PackSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        root = self.root / "pack"
        pins = pack.sources()
        runtime = root / "native_source_runtime"
        runtime.mkdir(parents=True)
        (runtime / "fixture.bin").write_bytes(b"synthetic; never rendered")
        locked = {"fixture.bin": pack.digest(runtime / "fixture.bin")}
        write_json(runtime / "SOURCE_RUNTIME_MANIFEST.json", {
            "package_sha256": pins["package_sha256"], "engine_commit": pins["reference_commit"], "files": locked})
        adapter = pack.adapter_digest()
        version = "build_" + adapter[:16]
        native = root / "native_renderer" / version
        native.mkdir(parents=True)
        (native / "polar_endfield.dll").write_bytes(b"synthetic, NEVER executed")
        binary = pack.digest(native / "polar_endfield.dll")
        (native / "EndfieldHUD-MIT-LICENSE.txt").write_text("fixture only")
        write_json(native / "BUILD_MANIFEST.json", {"reference_commit": pins["reference_commit"],
                   "adapter_sha256": adapter, "binary_sha256": binary})
        write_json(root / "native_renderer/CURRENT.json", {"directory": version, "binary_sha256": binary})
        maps = root / "maps"
        maps.mkdir()
        for mode, source in pins["models"].items():
            (maps / (mode + ".efmesh")).write_bytes(mesh())
            (maps / (mode + ".png")).write_bytes(b"synthetic preview")
            write_json(maps / (mode + ".json"), {"mode": mode, "season": 2027,
                "source_sha256": source["sha256"], "camera_up_axis": source["up"],
                "gpu_mesh": mode + ".efmesh", "gpu_mesh_sha256": pack.digest(maps / (mode + ".efmesh")),
                "preview_sha256": pack.digest(maps / (mode + ".png")), "gpu_triangles": 1})
        for name in ("EndfieldHUD-LICENSE", "EndfieldHUD-CREDITS.md", "SOURCES.json"):
            path = root / "licenses" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("synthetic notice, not a distribution")
        self.seal(root)
        original = pack.read_json
        lock = {"package_sha256": pins["package_sha256"], "files": locked}
        self.patcher = patch.object(pack, "read_json", side_effect=lambda p: deepcopy(lock)
            if p.name == "endfield_runtime_files.json" else original(p))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        return root

    def seal(self, root):
        write_json(root / pack.MANIFEST, {"schema": 1, "reference_commit": pack.sources()["reference_commit"],
            "adapter_sha256": pack.adapter_digest(), "files": pack.snapshot(root)})

    def test_missing_whole_pack_cli_points_to_complete_setup(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(prepare.main(["check", "--pack", str(self.root / "missing")]), 2)
        self.assertEqual(json.loads(output.getvalue())["help"], "docs/endfield/PACK_SETUP.md")
        with self.assertRaisesRegex(FileNotFoundError, "PACK_SETUP"):
            library_path(self.root / "missing")

    def test_empty_manifest_cannot_serve_as_resource_pack(self):
        write_json(self.root / pack.MANIFEST, {})
        with self.assertRaisesRegex(ValueError, "schema"):
            pack.validate(self.root)

    def test_all_components_are_required_but_boot_audio_are_optional(self):
        root = self.fixture()
        result = pack.validate(root)
        self.assertEqual(set(result["maps"]), {"RMUC7v7", "RMUL3v3", "RMUL1v1"})
        self.assertFalse(result["optional_boot"] or result["optional_audio"] or result["native_render_verified"])
        (root / "maps/RMUL1v1.efmesh").unlink()
        with self.assertRaisesRegex(ValueError, "files differ"):
            pack.validate(root)

    def test_resealing_modified_base_asset_does_not_override_upstream_pin(self):
        root = self.fixture()
        (root / "native_source_runtime/fixture.bin").write_bytes(b"changed")
        self.seal(root)
        with self.assertRaisesRegex(ValueError, "Original resource changed"):
            pack.validate(root)

    def test_pointer_must_match_binary_and_build_not_just_exist(self):
        root = self.fixture()
        pointer = root / "native_renderer/CURRENT.json"
        data = pack.read_json(pointer)
        data["binary_sha256"] = "0" * 64
        write_json(pointer, data)
        self.seal(root)
        with self.assertRaisesRegex(ValueError, "identity differs"):
            pack.validate(root)

    def test_official_field_provenance_and_orientation_are_not_guessed(self):
        root = self.fixture()
        path = root / "maps/RMUL3v3.json"
        data = pack.read_json(path)
        data["camera_up_axis"] = "z"
        write_json(path, data)
        self.seal(root)
        with self.assertRaisesRegex(ValueError, "field identity"):
            pack.validate(root)

    def test_new_client_adapter_rejects_old_pack(self):
        root = self.fixture()
        record = pack.read_json(root / pack.MANIFEST)
        record["adapter_sha256"] = "0" * 64
        write_json(root / pack.MANIFEST, record)
        with self.assertRaisesRegex(ValueError, "adapter differs"):
            pack.validate(root)

    def test_paths_and_links_cannot_escape_pack(self):
        for name in ("../bad", "/bad", "C:/bad", "dir/../bad", "dir//bad", "dir\\bad", "dir./bad"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pack.confined(self.root, name)
        with patch.object(Path, "is_symlink", lambda p: p.name == "escape"):
            with self.assertRaisesRegex(ValueError, "links"):
                pack.confined(self.root, "escape/secret")

    def test_mesh_is_bounded_finite_and_indices_cannot_overrun(self):
        path = self.root / "mesh"
        path.write_bytes(mesh())
        self.assertEqual(pack.validate_mesh(path), 1)
        for value in (b"", mesh()[:-1], mesh() + b"x",
                      mesh()[:16] + struct.pack("<d", float("nan")) + mesh()[24:],
                      mesh()[:-4] + struct.pack("<I", 3)):
            path.write_bytes(value)
            with self.assertRaises(ValueError):
                pack.validate_mesh(path)

    def test_directory_junction_is_rejected_with_python_311_stat_metadata(self):
        original = Path.lstat
        def metadata(path):
            if path.name == "escape":
                return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_reparse_tag=0xA0000003)
            return original(path)
        with patch.object(Path,"lstat",metadata):
            with self.assertRaisesRegex(ValueError,"links"):
                pack.confined(self.root,"escape/secret")

    def test_invalid_inputs_and_existing_output_leave_user_data_untouched(self):
        out = self.root / "active"
        out.mkdir()
        witness = out / "keep"
        witness.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare.build(self.root / "none", self.root, self.root, out)
        self.assertEqual(witness.read_bytes(), b"keep")
        with self.assertRaises(ValueError):
            prepare.build(self.root / "none", self.root, self.root, self.root / "not-created/pack")
        self.assertFalse((self.root / "not-created").exists())

    def test_publish_never_replaces_an_existing_destination(self):
        root = self.fixture()
        out = self.root / "active"
        out.mkdir()
        witness = out / "keep"
        witness.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "appeared"):
            prepare.publish(root, out)
        self.assertEqual(witness.read_bytes(), b"keep")
        self.assertTrue(root.is_dir())
        result = prepare.publish(root, self.root / "published")
        self.assertEqual(result["status"], "PACK_VALID")
        self.assertFalse(root.exists())

    def test_failed_component_does_not_publish_a_half_pack(self):
        output = self.root / "active"
        with patch.object(prepare, "preflight", return_value=pack.sources()), \
             patch.object(prepare, "import_package", side_effect=RuntimeError("injected import failure")), \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                prepare.build(self.root / "source.zip", self.root, self.root, output)
        self.assertFalse(output.exists())
        work = list(self.root.glob(".endfield-build-*/pack"))
        self.assertEqual(len(work), 1)
        self.assertFalse((work[0] / pack.MANIFEST).exists())

    def test_required_license_notices_cannot_be_dropped_by_resealing(self):
        root = self.fixture()
        (root / "licenses/EndfieldHUD-CREDITS.md").unlink()
        self.seal(root)
        with self.assertRaisesRegex(ValueError, "license notices"):
            pack.validate(root)


if __name__ == "__main__":
    unittest.main()
