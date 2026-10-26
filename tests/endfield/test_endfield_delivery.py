"""Source/portable pack discovery without a developer's user_data tree."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from rm_client.runtime_paths import RuntimePaths
from tests.endfield import test_endfield_pack_setup as fixtures
from tools.endfield import pack as pack
from tools.endfield import prepare_pack as prepare


class EndfieldDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def paths(self, frozen=False):
        return RuntimePaths.discover(module_file=self.root / 'rm_client/runtime_paths.py',
            executable=self.root / 'POLAR-RM.exe', frozen=frozen, environ={})

    def shipped(self, paths):
        root = paths.endfield_bundled_menu_pack
        fixtures.write_json(root / pack.MANIFEST, {'synthetic discovery marker': True})
        return root

    def test_source_without_local_resources_selects_shipped_read_only_pack(self):
        paths = self.paths()
        shipped = self.shipped(paths)
        self.assertEqual(paths.endfield_menu_pack, shipped)
        self.assertFalse(paths.user_data_root.exists())

    def test_portable_uses_external_resources_not_exe_or_cwd(self):
        paths = self.paths(frozen=True)
        shipped = self.shipped(paths)
        self.assertEqual(paths.endfield_menu_pack, self.root / 'resources/assets/endfield/menu')
        self.assertEqual(paths.endfield_menu_pack, shipped)

    def test_empty_partial_local_directory_does_not_mask_complete_shipped_pack(self):
        paths = self.paths()
        shipped = self.shipped(paths)
        (paths.user_data_root / 'endfield_pack/native_renderer').mkdir(parents=True)
        self.assertEqual(paths.endfield_menu_pack, shipped)

    def test_local_manifest_retains_explicit_override_and_corruption_diagnostic(self):
        paths = self.paths()
        self.shipped(paths)
        local = paths.user_data_root / 'endfield_pack'
        fixtures.write_json(local / 'native_renderer/CURRENT.json', {})
        self.assertEqual(paths.endfield_menu_pack, local)

    def test_no_shipped_pack_keeps_missing_local_diagnostic(self):
        paths = self.paths()
        self.assertEqual(paths.endfield_menu_pack, paths.user_data_root / 'endfield_pack')


class EndfieldSourceIdentityTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.PackSetupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture.fixture()

    def test_lf_crlf_variation_accepts_same_canonical_adapter_but_not_changed_code(self):
        root = self.fixture()
        record = pack.read_json(root / pack.MANIFEST)
        record['adapter_canonical_sha256'] = pack.adapter_canonical_digest()
        fixtures.write_json(root / pack.MANIFEST, record)
        real_digest = pack.digest
        with patch.object(pack, 'digest', side_effect=lambda path: 'f' * 64
                          if path == pack.ROOT / 'native/endfield/bridge.cpp' else real_digest(path)):
            self.assertEqual(pack.validate(root)['status'], 'PACK_VALID')
            with patch.object(pack, 'adapter_canonical_digest', return_value='e' * 64):
                with self.assertRaisesRegex(ValueError, 'adapter differs'):
                    pack.validate(root)

    def test_export_transfers_whole_verified_pack_without_overwriting_or_machine_paths(self):
        root = self.fixture()
        before = pack.snapshot(root)
        destination = root.parent / 'shipped'
        self.assertEqual(prepare.export(root, destination)['status'], 'PACK_VALID')
        self.assertEqual(pack.snapshot(root), before)

        self.assertEqual(pack.validate(destination)['status'], 'PACK_VALID')
        record = pack.read_json(destination / pack.MANIFEST)
        self.assertEqual(record['adapter_canonical_sha256'], pack.adapter_canonical_digest())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            prepare.export(root, destination)
        with self.assertRaisesRegex(ValueError, 'outside'):
            prepare.export(root, root / 'nested')
        self.assertFalse((root / 'nested').exists())

    def test_native_catalog_extension_is_part_of_adapter_identity(self):
        root = self.fixture()
        original = pack.digest
        with patch.object(pack,"digest",side_effect=lambda path:"f"*64
                          if path==pack.ROOT/"native/endfield/catalog_extension.inc" else original(path)):
            with self.assertRaisesRegex(ValueError,"adapter differs"):
                pack.validate(root)


if __name__ == '__main__':
    unittest.main()
