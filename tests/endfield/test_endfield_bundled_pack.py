"""The shipped menu must work without the developer's private user_data."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rm_client.runtime_paths import RuntimePaths
from rm_client.ui.endfield.menu.native import library_path
from tools.endfield.pack import MANIFEST, read_json, validate


class EndfieldBundledPackTests(unittest.TestCase):
    def test_complete_shipped_pack_passes_all_locked_hash_source_and_mesh_checks(self):
        pack = ROOT / 'rm_client/ui/endfield/menu/assets'
        report = validate(pack)
        self.assertEqual(report['status'], 'PACK_VALID')
        self.assertEqual(set(report['maps']), {'RMUC7v7', 'RMUL3v3', 'RMUL1v1'})
        files = read_json(pack / MANIFEST)['files']
        # 清单精确覆盖当前构建；旧构建不作为发布依赖。
        self.assertGreaterEqual(len(files), 54)
        self.assertEqual(len([p for p in pack.rglob('*') if p.is_file()]), len(files)+1)
        self.assertEqual(library_path(pack).read_bytes()[:2], b'MZ')
        renderer = pack/'native_renderer'
        current = read_json(renderer/'CURRENT.json')['directory']
        self.assertEqual({path.name for path in renderer.glob('build_*')},{current})

    def test_fresh_profile_selects_shipped_dll_without_creating_private_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = RuntimePaths.discover(module_file=ROOT / 'rm_client/runtime_paths.py',
                frozen=False, environ={'POLAR_USER_DATA_ROOT': directory})
            self.assertEqual(paths.endfield_menu_pack, ROOT / 'rm_client/ui/endfield/menu/assets')
            self.assertTrue(library_path(paths.endfield_menu_pack).is_file())
            self.assertFalse((Path(directory) / 'endfield_pack').exists())

    def test_private_pack_does_not_shadow_shipped_native_bugfix(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / 'endfield_pack'
            renderer = local / 'native_renderer'
            renderer.mkdir(parents=True)
            (renderer / 'CURRENT.json').write_text('{"directory":"old-build"}')
            paths = RuntimePaths.discover(module_file=ROOT / 'rm_client/runtime_paths.py',
                frozen=False, environ={'POLAR_USER_DATA_ROOT': directory})
            self.assertEqual(paths.endfield_menu_pack, local)
            self.assertEqual(paths.endfield_renderer_pack, ROOT / 'rm_client/ui/endfield/menu/assets')
            self.assertEqual((renderer / 'CURRENT.json').read_text(), '{"directory":"old-build"}')


if __name__ == '__main__':
    unittest.main()
