"""Real JSON nesting failures follow ordinary configuration rejection policy.

Temporary local files only; recursion limits and native services are unchanged.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client import config_store
from rm_client.configuration import validation
from rm_client.model import build_default_registry


class ConfigurationJsonNestingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = config_store.ClientConfigStore(self.root / "profiles")
        self.store.save_with_startup("source", {"unknown": {"keep": [1, 2]}}, load_on_start=True)
        self.before = self.files()
        self.limit = sys.getrecursionlimit()
        self.addCleanup(lambda: self.assertEqual(sys.getrecursionlimit(), self.limit))
        depth = max(self.limit + 100, 10000)  # CPython C JSON recursion guard differs from Python limit.
        self.deep_wire = '{"unknown":' + '[' * depth + '0' + ']' * depth + '}'
        nested = 0
        for _ in range(depth):
            nested = [nested]
        self.deep_value = {"unknown": nested}

    def files(self):
        return {str(path.relative_to(self.store.config_dir)): path.read_bytes()
                for path in self.store.config_dir.rglob('*') if path.is_file()}

    def test_profile_loader_rejects_real_excessive_json_nesting(self):
        path = self.store.profile_path("deep")
        path.write_text(self.deep_wire)
        before = self.files()
        self.assertIsNone(self.store.load("deep"))
        self.assertEqual(self.files(), before)

    def test_startup_loader_rejects_real_excessive_json_nesting(self):
        (self.store.config_dir / '.startup.json').write_text(self.deep_wire)
        before = self.files()
        self.assertIsNone(self.store.load_startup_preferences())
        self.assertEqual(self.files(), before)

    def test_import_rejects_before_backup_or_target_replacement(self):
        source = self.root / 'source.json'
        source.write_text(self.deep_wire)
        with self.assertRaises(ValueError) as caught:
            self.store.import_file(source)
        self.assertIsInstance(caught.exception.__cause__, RecursionError)
        self.assertEqual(self.files(), self.before)
        self.assertEqual(source.read_text(), self.deep_wire)

    def test_import_indented_overflow_preserves_preexisting_backup(self):
        backup = self.store.profile_path('source').with_suffix('.json.bak')
        backup.write_bytes(b'previous recoverable backup')
        before = self.files()
        depth = self.limit + 100
        source = self.root / 'source.json'
        source.write_text('{"unknown":' + '[' * depth + '0' + ']' * depth + '}')
        with self.assertRaises(ValueError) as caught:
            self.store.import_file(source)
        self.assertIsInstance(caught.exception.__cause__, RecursionError)
        self.assertEqual(self.files(), before)

    def test_validation_normalizes_real_serializer_recursion(self):
        with self.assertRaises(ValueError) as caught:
            validation.validate_client_config(self.deep_value)
        self.assertIsInstance(caught.exception.__cause__, RecursionError)

    def test_save_and_registry_preflight_fail_before_mutation(self):
        registry = build_default_registry()
        module = registry.get('ClickGui')
        enabled = module.enabled
        candidate = self.deep_value | {"modules": {"ClickGui": {"enabled": not enabled}}}
        for operation in (
            lambda: self.store.save('source', candidate),
            lambda: self.store.save_with_startup('source', candidate, load_on_start=False),
            lambda: config_store.apply_registry_config(registry, candidate),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError):
                    operation()
                self.assertEqual(module.enabled, enabled)
                self.assertEqual(self.files(), self.before)

    def test_compact_accepted_indented_serializer_failure_precedes_atomic_write(self):
        nested = 0
        for _ in range(self.limit + 100):
            nested = [nested]
        candidate = {"unknown": nested}
        # The pinned Python 3.12 compact C encoder accepts this input while
        # its indented Python encoder exhausts the Python recursion budget.
        validation.validate_client_config(candidate)
        with patch.object(config_store, '_atomic_write') as write:
            with self.assertRaises(ValueError) as caught:
                self.store.save('source', candidate)
            self.assertIsInstance(caught.exception.__cause__, RecursionError)
            write.assert_not_called()
        self.assertEqual(self.files(), self.before)

    def test_compatible_unknown_fields_and_normal_file_roundtrip_remain(self):
        data = {"unknown": {"future": [1, {"nested": True}]}, "selected_category": "System"}
        path = self.store.save_with_startup('normal', data, load_on_start=False)
        self.assertTrue(path.is_file())
        loaded = self.store.load('normal')
        self.assertEqual(loaded['unknown'], data['unknown'])
        self.assertEqual(self.store.load_startup_preferences(), {"profile": "normal", "load_on_start": False})
        source = self.root / 'imported.json'
        source.write_text('{"unknown":{"future":[1,2]}}')
        self.assertEqual(self.store.import_file(source), 'imported')
        self.assertEqual(self.store.load('imported')['unknown'], {"future": [1, 2]})

    def test_unrelated_callback_recursion_is_not_hidden_as_invalid_json(self):
        failure = RecursionError('registry callback failed')
        registry = build_default_registry()
        with patch.object(registry, 'get', side_effect=failure):
            with self.assertRaises(RecursionError) as caught:
                config_store.validate_client_config({"modules": {"ClickGui": {}}}, registry)
        self.assertIs(caught.exception, failure)


if __name__ == '__main__':
    unittest.main()
