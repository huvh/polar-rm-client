"""Internal oracle coverage using temporary trees; no repository edits."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import verification_sources as sources


class InternalFixtureInputsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.write("tests/test_example.py", b"assert True\n")

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def capture(self):
        return sources.capture_sources(self.root)

    def test_all_four_previously_excluded_oracles_are_measured(self):
        for name in ("angle_port_admission_baseline.txt", "polar_health_baseline.txt",
                     "tactical_map_71ebb0f.py.txt", "rm_indicators_caption_baseline.py.txt"):
            with self.subTest(name=name):
                before = self.capture()
                path = self.write("tests/fixtures/" + name, b"original oracle\n")
                added = self.capture()
                self.assertEqual(added["file_count"], before["file_count"] + 1)
                self.assertEqual(sources.compare_sources(before, added)[0], "FAIL")
                path.write_bytes(b"changed oracle\n")
                self.assertEqual(sources.compare_sources(added, self.capture())[0], "FAIL")

    def test_arbitrary_fixture_bytes_add_change_rename_and_remove(self):
        for name in ("sample.bin", "extensionless", "nested/data.csv"):
            with self.subTest(name=name):
                before = self.capture()
                path = self.write("tests/fixtures/" + name, b"\x00\xff\x01")
                added = self.capture()
                self.assertEqual(sources.compare_sources(before, added)[0], "FAIL")
                path.write_bytes(b"\x00\xff\x02")
                changed = self.capture()
                self.assertEqual(sources.compare_sources(added, changed)[0], "FAIL")
                path = path.rename(path.with_name(path.name + ".renamed"))
                renamed = self.capture()
                self.assertEqual(sources.compare_sources(changed, renamed)[0], "FAIL")
                path.unlink()
                self.assertEqual(sources.compare_sources(renamed, self.capture())[0], "FAIL")
                self.assertEqual(before, self.capture())

    def test_hidden_cache_and_outside_assets_remain_excluded(self):
        before = self.capture()
        for name in ("tests/fixtures/.private/oracle.txt", "tests/fixtures/__pycache__/oracle.pyc",
                     "tests/_runtime.png", "assets/sample.bin", "external/fixtures/oracle.txt"):
            self.write(name, b"excluded")
        self.assertEqual(before, self.capture())
        self.assertEqual(sources.SOURCE_SCOPE.get("all_file_directories"), ["tests/fixtures"])
        self.assertIn("external fixtures", sources.SOURCE_SCOPE["limits"])

    def test_linked_fixture_is_rejected_before_reading_target(self):
        path = self.write("tests/fixtures/oracle.bin", b"data")
        with patch.object(Path, "is_symlink", lambda candidate: candidate == path), \
                patch.object(Path, "open", side_effect=AssertionError("must not read target")):
            result = self.capture()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["error_type"], "ValueError")


if __name__ == "__main__":
    unittest.main(verbosity=2)
