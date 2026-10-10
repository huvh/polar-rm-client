"""Isolated build/tooling regressions. No firmware, patch installer or binary runs.

Run: python tests/test_build_safety_regressions.py
Qt, subprocesses, network probes and firmware checks are replaced with spies.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import contextlib
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.runtime_paths import RuntimePaths
from rm_client import preflight


def load_file(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


file_guard = load_file("build_safety_file_guard", "tools/firmware/file_guard.py")
verify = load_file("build_safety_verify", "tools/verify_all.py")


def definitions(relative, names, namespace):
    """Load only named definitions, never the firmware tool's entry point."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                 and node.name in names]
    exec(compile(tree, relative, "exec", flags=__import__("__future__").annotations.compiler_flag), namespace)
    return namespace


class FileProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        self.names = ["original.txt", "prior-header.h", "new-header.h", "nested/parameter.txt"]
        (self.root / "original.txt").write_bytes(b"uncommitted user content\r\n")
        (self.root / "prior-header.h").write_bytes(b"custom user header")

    def journal(self):
        return file_guard.FileJournal(self.root, self.names)

    def prepare(self):
        journal = self.journal()
        with journal.locked():
            journal.begin()
            for name in self.names:
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"tool-produced content")
            journal.finish()
        return journal

    def test_revert_restores_all_bytes_and_existing_headers(self):
        journal = self.prepare()
        with journal.locked():
            self.assertEqual(journal.revert(), 4)
        self.assertEqual((self.root / "original.txt").read_bytes(), b"uncommitted user content\r\n")
        self.assertEqual((self.root / "prior-header.h").read_bytes(), b"custom user header")
        self.assertFalse((self.root / "new-header.h").exists())
        self.assertFalse((self.root / "nested/parameter.txt").exists())
        with self.assertRaises(file_guard.SnapshotError):
            journal.revert()

    def test_later_edit_refuses_entire_revert_without_partial_writes(self):
        journal = self.prepare()
        (self.root / "original.txt").write_bytes(b"important later change")
        before = {name: (self.root / name).read_bytes() for name in self.names}
        with self.assertRaises(file_guard.SnapshotError):
            journal.revert()
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in self.names})

    def test_rerun_keeps_original_snapshot(self):
        journal = self.prepare()
        with journal.locked():
            journal.begin()
            (self.root / "original.txt").write_bytes(b"second tool run")
            journal.finish()
            journal.revert()
        self.assertEqual((self.root / "original.txt").read_bytes(), b"uncommitted user content\r\n")

    def test_missing_or_interrupted_snapshot_never_falls_back_to_checkout(self):
        journal = self.journal()
        with self.assertRaises(file_guard.SnapshotError):
            journal.revert()
        journal.begin()
        with self.assertRaises(file_guard.SnapshotError):
            self.journal().revert()
        self.assertEqual((self.root / "original.txt").read_bytes(), b"uncommitted user content\r\n")

    def test_lock_and_later_edit_block_rerun(self):
        journal = self.prepare()
        with journal.locked(), self.assertRaises(file_guard.SnapshotError):
            with self.journal().locked():
                self.fail("concurrent operation acquired lock")
        (self.root / "original.txt").write_bytes(b"later user edit")
        with self.assertRaises(file_guard.SnapshotError):
            journal.begin()

    def test_path_escape_and_symlink_are_rejected(self):
        with self.assertRaises(file_guard.SnapshotError):
            file_guard.FileJournal(self.root, ["../outside"]).begin()
        link = self.root / "link"
        try:
            link.symlink_to(self.root / "original.txt")
        except OSError:
            return  # Windows can deny symlink creation; the traversal case still ran.
        with self.assertRaises(file_guard.SnapshotError):
            file_guard.FileJournal(self.root, ["link"]).begin()


class BuildAndAudioTests(unittest.TestCase):
    def test_spec_includes_module_relative_json_files(self):
        tree = ast.parse((ROOT / "tools/POLAR-RM.spec").read_text())
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "datas" for t in node.targets))
        ns = {"root": ROOT, "str": str}
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), "spec", "exec"), ns)
        self.assertIn((str(ROOT / "rm_client/backend/polar_protocol.json"), "rm_client/backend"), ns["datas"])
        self.assertIn((str(ROOT / "configs/cc_key_usage.json"), "configs"), ns["datas"])
        for source, _ in ns["datas"]:
            self.assertIsInstance(json.loads(Path(source).read_text()), dict)

    def test_audio_import_does_not_change_immutable_resources(self):
        class FakeQObject:
            def __init__(self): pass
        ns = definitions("rm_client/ui_audio.py", {"ReliableAudioPool", "UiAudioManager"}, {
            "Path": Path, "RuntimePaths": RuntimePaths, "shutil": shutil,
            "QObject": FakeQObject, "defaultdict": defaultdict, "logging": logging,
            "_media_preload_disabled": lambda: True,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = RuntimePaths.discover(executable=root / "POLAR-RM.exe", frozen=True, environ={})
            sounds = paths.asset("ui_sounds")
            sounds.mkdir(parents=True)
            (sounds / "builtin.dat").write_bytes(b"immutable")
            custom = paths.user_data_root / "ui_sounds/custom"
            manager = ns["UiAudioManager"](sounds, custom_root=custom)
            manager.pool.preload = mock.Mock()
            source = root / "example.wav"
            source.write_bytes(b"test audio bytes")
            before = paths.hash_tree(paths.resource_root)
            name = manager.import_custom_sound(source, "enable")
            self.assertEqual(name, "custom/enable-example.wav")
            self.assertEqual(manager.pool._sound_path(name), custom / "enable-example.wav")
            self.assertEqual(manager.custom_sound_names(), [name])
            self.assertEqual(before, paths.hash_tree(paths.resource_root))
            self.assertEqual(manager.import_custom_sound(source, "enable"), "custom/enable-example-2.wav")
            self.assertIsNone(manager.sound_name("Custom", "enable", {"enable": "custom/../escape.wav"}))

    def test_existing_custom_sound_selections_migrate_without_overwrite(self):
        class FakeQObject:
            def __init__(self): pass
        ns = definitions("rm_client/ui_audio.py", {"ReliableAudioPool", "UiAudioManager"}, {
            "Path": Path, "RuntimePaths": RuntimePaths, "shutil": shutil,
            "QObject": FakeQObject, "defaultdict": defaultdict, "logging": logging,
            "_media_preload_disabled": lambda: True,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sounds, custom = root / "resources/ui_sounds", root / "user_data/ui_sounds/custom"
            (sounds / "custom").mkdir(parents=True)
            custom.mkdir(parents=True)
            (sounds / "custom/old.wav").write_bytes(b"old selection")
            (sounds / "custom/new.wav").write_bytes(b"outdated")
            (custom / "new.wav").write_bytes(b"newer user selection")
            before = RuntimePaths.hash_tree(sounds)
            manager = ns["UiAudioManager"](sounds, custom_root=custom)
            self.assertEqual(manager.pool._sound_path("custom/old.wav").read_bytes(), b"old selection")
            self.assertEqual((custom / "new.wav").read_bytes(), b"newer user selection")
            self.assertEqual(RuntimePaths.hash_tree(sounds), before)

    def test_unreadable_legacy_audio_does_not_block_ui_construction(self):
        class FakeQObject:
            def __init__(self): pass
        ns = definitions("rm_client/ui_audio.py", {"ReliableAudioPool", "UiAudioManager"}, {
            "Path": Path, "RuntimePaths": RuntimePaths, "shutil": shutil,
            "QObject": FakeQObject, "defaultdict": defaultdict, "logging": logging,
            "_media_preload_disabled": lambda: True,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sounds, custom = root / "resources/ui_sounds", root / "user_data/ui_sounds/custom"
            (sounds / "custom").mkdir(parents=True)
            (sounds / "custom/old.wav").write_bytes(b"old selection")
            with mock.patch.object(shutil, "copy2", side_effect=OSError("fixture locked")), self.assertLogs("rm_client.ui_audio"):
                manager = ns["UiAudioManager"](sounds, custom_root=custom)
            self.assertEqual(len(manager.migration_errors), 1)
            self.assertIn("old.wav", manager.migration_errors[0])

    def test_launcher_keeps_executable_and_arguments_separate(self):
        source = (ROOT / "启动.bat").read_text(encoding="ascii")
        self.assertIn('set "CAND=py"\nset "CANDARGS=-3"', source)
        self.assertIn('"%PYEXE%" %PYARGS% "%~dp0main.py" %*', source)
        self.assertIn('"%BASE%" %BASEARGS% -m venv', source)
        self.assertNotIn("PYQUOTED", source)
        for label in ("provision", "provision_verify", "probe_path", "probe_bare", "ready", "frozen"):
            self.assertEqual(source.count("\n:" + label + "\n"), 1)

    def test_failed_build_retains_diagnostics(self):
        source = (ROOT / "tools/build_release.ps1").read_text()
        self.assertIn('$buildSucceeded -and (Test-Path -LiteralPath $stageRoot)', source)
        self.assertIn('".venv-polar"', source)


class PreflightSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = RuntimePaths.discover(executable=self.root / "POLAR-RM.exe", frozen=True, environ={})
        self.paths.bin_root.mkdir()
        self.paths.resource_root.mkdir()
        self.paths.ffmpeg_path.write_bytes(b"never execute this fixture")
        self.manifest = {"ffmpeg": {"sha256": hashlib.sha256(self.paths.ffmpeg_path.read_bytes()).hexdigest()},
                         "resources": {"tree_sha256": self.paths.hash_tree(self.paths.resource_root)},
                         "critical_files": {}}
        self.save_manifest()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(preflight, "_qt_opengl_context", return_value=(True, "stub")))
        self.stack.enter_context(mock.patch.object(preflight, "_port_available", return_value=(True, "stub")))
        self.stack.enter_context(mock.patch.object(preflight, "_writable", return_value=(True, "stub")))
        self.process = self.stack.enter_context(mock.patch.object(preflight.subprocess, "run", return_value=
                                                SimpleNamespace(returncode=0, stdout="ffmpeg version fixture\n", stderr="")))
        key_file = self.root / "cc_key_usage.json"
        key_file.write_text('{"W":26}')
        protocol = SimpleNamespace(SPEC_STATUS={"ok": True, "fell_back": False})
        spec = SimpleNamespace(load_spec=lambda: SimpleNamespace(ok=True, source="fixture", error_text=lambda: ""))
        self.stack.enter_context(mock.patch.dict(sys.modules, {
            "rm_client.backend.polar_link": protocol,
            "rm_client.backend.polar_spec": spec,
            "rm_client.backend.cc_link": SimpleNamespace(KEY_USAGE_FILE=key_file),
            "rm_client.backend.codec_selftest": SimpleNamespace(run_all_codec_selftests=mock.Mock(return_value=[])),
        }))

    def save_manifest(self):
        self.paths.manifest_path.write_text(json.dumps(self.manifest))
        (self.root / "BUILD_MANIFEST.sha256").write_text(hashlib.sha256(self.paths.manifest_path.read_bytes()).hexdigest())

    def test_valid_integrity_allows_version_probe(self):
        report = preflight.run_preflight(self.paths, official=True)
        self.assertTrue(report.passed, report.as_dict())
        self.process.assert_called_once()

    def test_bad_ffmpeg_hash_blocks_execution_and_codec_tests(self):
        self.paths.ffmpeg_path.write_bytes(b"tampered")
        report = preflight.run_preflight(self.paths, official=True, codec_selftest=True)
        self.assertFalse(report.passed)
        self.process.assert_not_called()
        sys.modules["rm_client.backend.codec_selftest"].run_all_codec_selftests.assert_not_called()

    def test_bad_manifest_and_critical_files_block_execution(self):
        for reason in ("sidecar", "invalid-json", "missing-sidecar", "critical", "resources"):
            with self.subTest(reason=reason):
                self.manifest["critical_files"] = {}
                self.save_manifest()
                if reason == "sidecar": (self.root / "BUILD_MANIFEST.sha256").write_text("0" * 64)
                elif reason == "invalid-json": self.paths.manifest_path.write_text("[]")
                elif reason == "missing-sidecar": (self.root / "BUILD_MANIFEST.sha256").unlink()
                elif reason == "critical":
                    self.manifest["critical_files"] = {"missing.bin": "F" * 64}
                    self.save_manifest()
                else: (self.paths.resource_root / "unexpected.txt").write_text("modified")
                report = preflight.run_preflight(self.paths, official=True)
                self.assertFalse(report.passed)
                self.process.assert_not_called()

    def test_protocol_fallback_blocks_release(self):
        sys.modules["rm_client.backend.polar_link"].SPEC_STATUS["fell_back"] = True
        report = preflight.run_preflight(self.paths, official=True)
        self.assertFalse(next(check for check in report.checks if check.key == "protocol_spec").passed)


class FirmwareToolIsolationTests(unittest.TestCase):
    def test_dry_run_missing_prerequisites_never_calls_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "usb.c").write_text("unprepared")
            (root / "rc.c").write_text("unprepared")
            patch = root / "fixture.patch"
            patch.write_text("not a real patch")
            bridge = root / "host_bridge"
            bridge.mkdir()
            (bridge / "apply_host_bridge.py").write_text("not executable")
            runner = mock.Mock(side_effect=AssertionError("must never execute installer"))
            ns = definitions("tools/firmware/host_bridge/apply_host_bridge.py", {"ensure_drive_keys_patch"}, {
                "Path": Path, "USB_REL": "usb.c", "DRIVE_KEYS_PATCH": patch,
                "subprocess": SimpleNamespace(run=runner),
            })
            with self.assertRaisesRegex(RuntimeError, "dry-run"):
                ns["ensure_drive_keys_patch"](root, [], dry_run=True)
            ns = definitions("tools/firmware/km_link/apply_km_link.py", {"ensure_host_bridge"}, {
                "Path": Path, "RC_REL": "rc.c", "FIRM_TOOL_DIR": root,
                "ensure_drive_keys_patch": runner, "subprocess": SimpleNamespace(run=runner),
            })
            with self.assertRaisesRegex(RuntimeError, "dry-run"):
                ns["ensure_host_bridge"](root, [], dry_run=True)
            runner.assert_not_called()
            self.assertEqual((root / "usb.c").read_text(), "unprepared")
            self.assertEqual((root / "rc.c").read_text(), "unprepared")

    def test_dry_run_entrypoints_preserve_all_fixture_bytes(self):
        for prepared in ("fresh", "drive-only", "host-ready"):
            with self.subTest(prepared=prepared), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                usb_rel = "application/communication/usb_task.c"
                rc_rel = "application/other/remote_control.c"
                ref_rel = "application/referee/referee.c"
                for rel in (usb_rel, rc_rel, ref_rel):
                    path = root / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture")
                (root / "application/typedef").mkdir()
                if prepared != "fresh": (root / usb_rel).write_text("UsbMergeVirtualRcKeys")
                if prepared == "host-ready": (root / rc_rel).write_text("HOST_RC_MERGED_KEYS")
                source = root / "tool-source"
                source.mkdir()
                (source / "fixture.h").write_text("header fixture")
                (source / "fixture.patch").write_text("patch fixture, never applied")
                (source / "host_bridge").mkdir()
                (source / "host_bridge/apply_host_bridge.py").write_text("never executed")
                before = RuntimePaths.hash_tree(root)
                runner = mock.Mock(side_effect=AssertionError("must never execute installer"))
                ns = definitions("tools/firmware/host_bridge/apply_host_bridge.py", {"main", "ensure_drive_keys_patch"}, {
                    "__doc__": "isolated file-safety test", "argparse": argparse, "Path": Path,
                    "HERE": source, "HEADER_NAME": "fixture.h", "USB_REL": usb_rel,
                    "DRIVE_KEYS_PATCH": source / "fixture.patch", "subprocess": SimpleNamespace(run=runner),
                    "apply_usb_task": lambda path, log: path.read_text() + "planned",
                    "apply_remote_control": lambda path, log: path.read_text() + "planned",
                    "apply_chassis": lambda path, anchor, log: path.read_text() + "planned",
                })
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(ns["main"]([str(root), "--dry-run"]), 2 if prepared == "fresh" else 0)
                self.assertEqual(before, RuntimePaths.hash_tree(root))
                km = definitions("tools/firmware/km_link/apply_km_link.py", {"main", "ensure_host_bridge"}, {
                    "__doc__": "isolated file-safety test", "argparse": argparse, "Path": Path,
                    "RC_REL": rc_rel, "REF_REL": ref_rel, "USB_REL": usb_rel, "FIRM_TOOL_DIR": source,
                    "ensure_drive_keys_patch": runner, "subprocess": SimpleNamespace(run=runner),
                    "apply_referee": lambda path, log: path.read_text() + "planned",
                    "apply_remote_control": lambda path, log: path.read_text() + "planned",
                    "apply_usb_task": lambda path, log: path.read_text() + "planned",
                })
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(km["main"]([str(root), "--dry-run"]), 0 if prepared == "host-ready" else 2)
                self.assertEqual(before, RuntimePaths.hash_tree(root))
                runner.assert_not_called()

    def test_aggregate_classifies_skips_and_passes_separately(self):
        for stdout, code, expected in (("[PASS] yes", 0, True), ("SKIP: absent", 0, False),
                                       ("[SKIP] absent", 0, False), ("", 77, False), ("[FAIL] no", 1, False)):
            with self.subTest(stdout=stdout), mock.patch.object(verify.subprocess, "run", return_value=
                    SimpleNamespace(stdout=stdout, stderr="", returncode=code)) as runner:
                ok, detail = verify.run("fixture", ["unused"], firmware=Path("/target-A"))
                self.assertEqual(ok, expected)
                self.assertEqual(runner.call_args.kwargs["env"]["POLAR_FIRMWARE_ROOT"], str(Path("/target-A")))
                self.assertEqual(runner.call_args.kwargs["env"]["POLAR_FIRMWARE_READ_ONLY"], "1")
                self.assertGreater(runner.call_args.kwargs["timeout"], 0)
                if "SKIP" in stdout or code == 77: self.assertTrue(detail.startswith("INCOMPLETE:"))

    def test_aggregate_timeout_is_incomplete(self):
        with mock.patch.object(verify.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 1)):
            ok, detail = verify.run("fixture", ["unused"], timeout=1)
        self.assertFalse(ok)
        self.assertIn("INCOMPLETE", detail)

    def test_prepare_compile_checks_receive_exact_target_and_reject_skips(self):
        step = SimpleNamespace(ok=mock.Mock(), bad=mock.Mock())
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="SKIP: not run", stderr=""))
        ns = definitions("tools/firmware/prepare_hero_build.py", {"compile_check"}, {
            "Path": Path, "os": os, "sys": sys, "re": re,
            "HERE": ROOT / "tools/firmware",
            "COMPILE_CHECKS": [("fixture", "test_patch_real_headers.py", ())],
            "subprocess": SimpleNamespace(run=runner, TimeoutExpired=subprocess.TimeoutExpired),
        })
        with mock.patch.dict(sys.modules, {"ziglang": ModuleType("ziglang")}), contextlib.redirect_stdout(io.StringIO()):
            ns["compile_check"](Path("/chosen-target-A"), step)
        self.assertIn(str(Path("/chosen-target-A").resolve()), runner.call_args.args[0])
        self.assertEqual(runner.call_args.kwargs["env"]["POLAR_FIRMWARE_ROOT"], str(Path("/chosen-target-A").resolve()))
        step.ok.assert_not_called()
        step.bad.assert_called_once()

    def test_no_destructive_revert_and_no_implicit_prepare(self):
        prepare = ast.parse((ROOT / "tools/firmware/prepare_hero_build.py").read_text())
        revert = next(node for node in prepare.body if isinstance(node, ast.FunctionDef) and node.name == "revert")
        self.assertNotIn("checkout", ast.unparse(revert).replace("未使用 git checkout", ""))
        self.assertIn('"--check-only"', (ROOT / "tools/verify_all.py").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
