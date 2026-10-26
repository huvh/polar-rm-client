"""Source asset import is explicit, confined and never installs another app."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from tools.endfield.import_runtime import import_package, select_entries


class SourceResourceImportTests(unittest.TestCase):
    def archive(self, names):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for name in names:
                archive.writestr(name, b"test")
        data.seek(0)
        archive = zipfile.ZipFile(data)
        self.addCleanup(archive.close)
        return archive

    def test_only_source_resource_roots_are_selected(self):
        archive = self.archive(["EndfieldHUD/EndfieldHUD.exe", "EndfieldHUD/resources/shell/catalog.ehscene",
                                "EndfieldHUD/fonts/NotoSansSC.ttf", "EndfieldHUD/resources/account/token.json"])
        self.assertEqual([entry.filename for entry in select_entries(archive)], [
            "EndfieldHUD/resources/shell/catalog.ehscene", "EndfieldHUD/fonts/NotoSansSC.ttf"])

    def test_no_path_escape_or_script_is_accepted(self):
        for name in ("../bad", "/bad", "C:/bad", "EndfieldHUD/resources/shell/../bad",
                     "EndfieldHUD/resources/shell/start.exe", "EndfieldHUD/fonts/install.ps1"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                select_entries(self.archive([name]))
        archive = self.archive(["safe"])
        archive.filelist[0].filename = "bad\\file"
        with self.assertRaises(ValueError):
            select_entries(archive)

    def test_case_collision_is_not_silently_overwritten(self):
        with self.assertRaises(ValueError):
            select_entries(self.archive(["EndfieldHUD/fonts/a.ttf", "EndfieldHUD/fonts/A.ttf"]))

    def test_modified_package_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "bad.zip"
            package.write_bytes(b"not the pinned release")
            with self.assertRaisesRegex(ValueError, "hash differs"):
                import_package(package, root / "import")
            self.assertFalse((root / "import").exists())

    def test_existing_user_directory_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            witness = root / "keep.txt"
            witness.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "new private"):
                import_package(root / "missing.zip", root)
            self.assertEqual(witness.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
