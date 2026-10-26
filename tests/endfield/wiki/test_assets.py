"""Wiki 资源封装、缺失检测与源码/便携版路径契约。"""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from rm_client.runtime_paths import RuntimePaths
from tools.endfield.wiki.check_assets import DEFAULT_ASSETS, validate, write_manifest


class WikiAssetTests(unittest.TestCase):
    def test_source_pack_is_inside_feature_and_complete(self):
        paths = RuntimePaths.discover(module_file=ROOT / "rm_client/runtime_paths.py",
                                      environ={}, frozen=False)
        self.assertEqual(paths.endfield_wiki_pack, DEFAULT_ASSETS)
        report = validate(paths.endfield_wiki_pack)
        self.assertEqual(report["images"], 244)
        self.assertEqual(report["clips"], 29)

    def test_portable_pack_loads_without_source_or_other_endfield_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = RuntimePaths.discover(executable=Path(directory) / "POLAR-RM.exe",
                                          environ={}, frozen=True)
            self.assertEqual(paths.endfield_wiki_pack, paths.asset("endfield/wiki"))
            shutil.copytree(DEFAULT_ASSETS, paths.endfield_wiki_pack)
            self.assertEqual(validate(paths.endfield_wiki_pack)["status"], "PASS")
            (paths.endfield_wiki_pack / "fonts/NotoSansSC.ttf").unlink()
            with self.assertRaisesRegex(ValueError, "NotoSansSC.ttf"):
                validate(paths.endfield_wiki_pack)

    def test_external_font_and_changed_curves_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wiki"
            shutil.copytree(DEFAULT_ASSETS, root)
            layout_file = root / "layout.json"
            layout = json.loads(layout_file.read_text(encoding="utf-8"))
            layout_file.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest mismatch: layout.json"):
                validate(root)
            layout["font"] = "../other/font.ttf"
            layout_file.write_text(json.dumps(layout), encoding="utf-8")
            write_manifest(root)
            with self.assertRaisesRegex(ValueError, "font must be bundled"):
                validate(root)


if __name__ == "__main__":
    unittest.main()
