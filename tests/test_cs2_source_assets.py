"""Clean source/portable asset loading without developer user_data or Steam."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("POLAR_DISABLE_MEDIA_PRELOAD", "1")

from PySide6.QtWidgets import QApplication

from rm_client.runtime_paths import RuntimePaths
from rm_client.ui.cs2_assets import (
    Cs2Assets, FONT_IDS, IMAGE_IDS, SOUND_IDS, SCOREBOARD_ADDON_IDS, local_cs2_assets,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "assets/cs2_ui_pack"


class BundledAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(local_cs2_assets.cache_clear)
        local_cs2_assets.cache_clear()
        self.root = Path(self.temp.name)
        self.paths = RuntimePaths.discover(
            module_file=self.root / "rm_client/runtime_paths.py", environ={}, frozen=False,
        )

    def install(self, paths=None):
        paths = paths or self.paths
        target = paths.asset("cs2_ui_pack")
        shutil.copytree(BUNDLE, target)
        return target

    def load(self, paths=None):
        with patch("rm_client.ui.cs2_assets.RuntimePaths.discover", return_value=paths or self.paths):
            return local_cs2_assets()

    def test_complete_source_inventory_and_hashes(self):
        manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["scope"], "authorized-distribution")
        self.assertEqual(set(manifest["assets"]), IMAGE_IDS | FONT_IDS | SOUND_IDS)
        expected = {"manifest.json"}
        for entry in manifest["assets"].values():
            expected.add(entry["file"])
            self.assertEqual(hashlib.sha256((BUNDLE / entry["file"]).read_bytes()).hexdigest(), entry["sha256"])
        for name, entry in manifest["additional_files"].items():
            expected.add(name)
            self.assertEqual(hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest(), entry["sha256"])
        self.assertEqual({p.name for p in BUNDLE.iterdir()}, expected)
        pack = Cs2Assets(BUNDLE)
        self.assertFalse(pack.error)
        self.assertEqual(set(pack.paths), IMAGE_IDS | FONT_IDS | SOUND_IDS)
        self.assertEqual(set(pack.families), FONT_IDS)

    def test_clean_source_and_portable_use_immutable_bundle(self):
        frozen = RuntimePaths.discover(
            executable=self.root / "portable/POLAR-RM.exe", environ={}, frozen=True,
        )
        for paths in (self.paths, frozen):
            with self.subTest(source_mode=paths.source_mode):
                local_cs2_assets.cache_clear()
                target = self.install(paths)
                before = RuntimePaths.hash_tree(target)
                self.assertFalse(paths.user_data_root.exists())
                pack = self.load(paths)
                self.assertTrue(pack.available, pack.error)
                self.assertEqual(pack.root, target)
                self.assertFalse(paths.user_data_root.exists())
                self.assertEqual(RuntimePaths.hash_tree(target), before)
                self.assertIs(pack, self.load(paths))

    def test_valid_personal_pack_remains_an_override(self):
        self.install()
        personal = self.paths.user_data_root / "cs2_ui_pack"
        shutil.copytree(BUNDLE, personal)
        manifest_path = personal / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["scope"] = "local-personal-use"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(self.load().root, personal)

    def test_corrupt_personal_pack_falls_back_without_rewriting_it(self):
        target = self.install()
        personal = self.paths.user_data_root / "cs2_ui_pack"
        shutil.copytree(BUNDLE, personal)
        (personal / "skull.png").write_bytes(b"invalid local override")
        before = RuntimePaths.hash_tree(personal)
        with self.assertLogs("rm_client.ui.cs2_assets", level="WARNING"):
            pack = self.load()
        self.assertTrue(pack.available)
        self.assertEqual(pack.root, target)
        self.assertEqual(RuntimePaths.hash_tree(personal), before)

    def test_old_personal_pack_cannot_hide_new_scoreboard_resources(self):
        target = self.install()
        personal = self.paths.user_data_root / 'cs2_ui_pack'
        shutil.copytree(BUNDLE, personal)
        manifest_path = personal / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for key in SCOREBOARD_ADDON_IDS:
            entry = manifest['assets'].pop(key)
            (personal / entry['file']).unlink()
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        before = RuntimePaths.hash_tree(personal)
        pack = self.load()
        self.assertEqual(pack.root, personal)
        for key in SCOREBOARD_ADDON_IDS:
            self.assertEqual(pack.paths[key].parent, target)
        self.assertEqual(pack.paths['skull'].parent, personal)
        self.assertEqual(RuntimePaths.hash_tree(personal), before)

    def test_missing_both_packs_preserves_original_fallback(self):
        pack = self.load()
        self.assertFalse(pack.available)
        self.assertFalse(self.paths.user_data_root.exists())

    def test_reviewed_builtin_video_hashes(self):
        expected = {
            "texas.mp4": "42b5dd4223dd280a925580709e5c62a9ca835721274fd21934df38febfa03b5e",
            "vending-machine.mp4": "e005a9a4bb84eb88280978f86135eb6121f826f6fa2680e19f05a15850539985",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                data = (ROOT / "assets/wallpapers/builtin" / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
