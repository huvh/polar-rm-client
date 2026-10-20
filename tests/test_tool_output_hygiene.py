"""Disposable output-path regressions; no Qt, capture, device or network use."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(relative):
    spec = importlib.util.spec_from_file_location("output_hygiene_subject", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    # These scripts adjust sys.path for standalone use; keep the caller intact.
    with patch.object(sys, "path", list(sys.path)), patch.object(sys, "dont_write_bytecode", True):
        spec.loader.exec_module(module)
    return module


class Dt7TemporaryProfileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="polar-profile-regression-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        configs = self.root / "configs"
        configs.mkdir()
        self.sentinels = {
            configs / "_t_dt7_profile.json": b"unrelated pre-existing profile\r\n",
            configs / "_t_limit.json": b"unrelated pre-existing limits\r\n",
        }
        for path, content in self.sentinels.items():
            path.write_bytes(content)
        self.profile = configs / "dt7_profile.json"
        self.default_bytes = (ROOT / "configs/dt7_profile.json").read_bytes()
        self.profile.write_bytes(self.default_bytes)
        self.module = load_script("tools/dt7_link/test_dt7_link.py")
        self.module.ROOT = self.root
        profile_patch = patch.object(self.module.dl, "PROFILE_FILE", self.profile)
        profile_patch.start()
        self.addCleanup(profile_patch.stop)
        # Both selected functions must remain entirely mock-output tests.
        emit_patch = patch.object(self.module.dl.Dt7KeyMouseLink, "_emit",
                                 side_effect=AssertionError("serial output is forbidden"))
        emit_patch.start()
        self.addCleanup(emit_patch.stop)

    def assert_sentinels_unchanged(self):
        for path, content in self.sentinels.items():
            self.assertTrue(path.is_file(), f"pre-existing file removed: {path.name}")
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.profile.read_bytes(), self.default_bytes)
        self.assertEqual(set((self.root / "configs").iterdir()), {*self.sentinels, self.profile})

    def exercise(self, name, fault=None):
        # Every negative-control case gets fresh, owned sentinels even if an
        # earlier subtest demonstrated the old destructive behavior.
        for path, content in self.sentinels.items():
            path.write_bytes(content)
        load_profile = self.module.dl.load_profile
        paths = []

        def observe(path=None):
            if path is not None:
                candidate = Path(path)
                paths.append(candidate)
                self.assertTrue(candidate.is_file())
                if fault is not None:
                    raise fault("injected after the temporary profile was written")
            return load_profile(path)

        output = io.StringIO()
        with patch.object(self.module.dl, "load_profile", observe), contextlib.redirect_stdout(output):
            if fault is None:
                getattr(self.module, name)()
            else:
                with self.assertRaises(fault):
                    getattr(self.module, name)()
        self.assert_sentinels_unchanged()
        self.assertTrue(paths, "must exercise a real temporary profile")
        self.assertEqual(len(set(paths)), 1)
        self.assertNotIn(self.root, paths[0].parents)
        self.assertFalse(paths[0].exists())
        self.assertFalse(paths[0].parent.exists())
        self.assertEqual(self.module.FAILED, 0)
        self.assertEqual(self.module.SKIPPED, [])
        return paths[0], output.getvalue()

    def test_repeated_functions_keep_sentinels_and_original_assertion_counts(self):
        used_paths = set()
        for name, expected in (("test_profile_file", 10), ("test_mouse_limit", 8)):
            for repeat in range(2):
                with self.subTest(function=name, repeat=repeat):
                    path, output = self.exercise(name)
                    self.assertNotIn(path, used_paths)
                    used_paths.add(path)
                    self.assertEqual(output.count("[ OK ]"), expected)
                    self.assertNotIn("[FAIL]", output)

    def test_exception_and_keyboard_interrupt_cleanup_owned_unique_directories(self):
        used_paths = set()
        for name in ("test_profile_file", "test_mouse_limit"):
            for fault in (RuntimeError, KeyboardInterrupt):
                with self.subTest(function=name, fault=fault.__name__):
                    path, _ = self.exercise(name, fault)
                    self.assertNotIn(path, used_paths)
                    used_paths.add(path)


def capture_stubs():
    class ForbiddenNative:
        def __init__(self, *args, **kwargs):
            raise AssertionError("native Qt/window construction is forbidden")

    modules = {"PySide6": ModuleType("PySide6")}
    for namespace, names in {
        "QtCore": ("QTimer", "QRectF", "Qt"),
        "QtGui": ("QColor", "QImage", "QLinearGradient", "QPainter", "QPixmap", "QSurfaceFormat"),
        "QtTest": ("QTest",),
        "QtWidgets": ("QApplication",),
    }.items():
        module = ModuleType("PySide6." + namespace)
        for name in names:
            setattr(module, name, ForbiddenNative)
        modules[module.__name__] = module
    window = ModuleType("rm_client.ui.polar_app")
    window.PolarRMWindow = ForbiddenNative
    modules[window.__name__] = window
    return modules


class CaptureOutputTests(unittest.TestCase):
    def load_capture(self, platform=None):
        with patch.dict(sys.modules, capture_stubs()), \
                patch.object(sys, "platform", platform or sys.platform), \
                patch.object(Path, "mkdir", side_effect=AssertionError("import must not create directories")):
            return load_script("tools/economy_live_capture.py")

    def test_import_has_no_directory_writes_or_native_construction(self):
        self.assertTrue(callable(self.load_capture().main))

    def test_windows_location_is_preserved_and_posix_output_is_ignored(self):
        self.assertEqual(str(self.load_capture("win32").OUT), r"C:\tmp\polar-rm-validation")
        relative = "tmp_economy_live_capture/probe.png"
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                self.assertEqual(self.load_capture(platform).OUT, ROOT / "tmp_economy_live_capture")
        result = subprocess.run(
            ["git", "-c", "core.excludesFile=", "check-ignore", "--no-index", "--", relative],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), relative)

    def test_help_does_not_create_output(self):
        module = self.load_capture()
        with patch.object(Path, "mkdir", side_effect=AssertionError("help must not create output")), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            module.main(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_execution_creates_output_before_native_setup(self):
        module = self.load_capture()
        with tempfile.TemporaryDirectory(prefix="polar-capture-output-") as directory:
            output = Path(directory) / "capture"
            module.OUT = output
            with self.assertRaisesRegex(AssertionError, "native Qt/window construction is forbidden"):
                module.main([])
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
