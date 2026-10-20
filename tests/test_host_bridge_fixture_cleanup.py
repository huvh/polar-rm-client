"""Host-bridge self-test cleanup, using disposable files and inert processes only."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    fixture = load("host_bridge_cleanup_fixture", "tools/firmware/bridge_fixture.py")
    # The standalone tool adjusts sys.path; keep that and its helper import local.
    with mock.patch.object(sys, "path", list(sys.path)), \
            mock.patch.dict(sys.modules, {"bridge_fixture": fixture}):
        return load("host_bridge_cleanup_subject", "tools/firmware/host_bridge/test_host_bridge.py")


class HostBridgeFixtureCleanupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="host-bridge-cleanup-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / ".git").mkdir()
        self.tool = load_tool()
        self.tool.REPO = self.root
        self.rels = [self.tool.USB_REL, self.tool.RC_REL,
                     self.tool.MECA_REL, self.tool.OMNI_REL]
        self.cdc = "Src/usbd_cdc_if.c"
        self.original = {rel: b"pre-existing user bytes\xff\r\n" + rel.encode()
                         for rel in [*self.rels, self.cdc]}
        self.original[self.tool.HEADER_REL] = None
        for rel, data in self.original.items():
            if data is not None:
                self.write(rel, data)
        self.mode = "nonzero"
        self.fault = None
        self.calls = []
        self.runner = mock.Mock(side_effect=self.inert_run)
        self.tool.subprocess = SimpleNamespace(run=self.runner)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.stage = stack.enter_context(mock.patch.object(self.tool.bf, "stage", wraps=self.tool.bf.stage))
        self.restore = stack.enter_context(mock.patch.object(self.tool.bf, "restore", wraps=self.tool.bf.restore))
        stack.enter_context(mock.patch.dict(os.environ, {"POLAR_FIRMWARE_READ_ONLY": "0"}))

    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def assert_original(self):
        actual = {rel: (self.root / rel).read_bytes() if (self.root / rel).exists() else None
                  for rel in self.original}
        self.assertEqual(actual, self.original)

    def inert_run(self, argv, **kwargs):
        if argv[0] == "git":
            self.assertEqual(argv, ["git", "checkout", "--", *self.rels])
            self.assertEqual(kwargs["cwd"], self.root)
            self.calls.append("checkout")
            for index, rel in enumerate(self.rels):
                self.write(rel, b"clean baseline\n")
                if self.mode == "checkout_fault" and index == 1:
                    raise self.fault
            return subprocess.CompletedProcess(argv, 0, "", "")
        self.assertEqual(argv, [sys.executable, str(self.tool.HERE / "apply_host_bridge.py"), str(self.root)])
        self.calls.append("apply")
        if self.mode == "launch_fault":
            raise self.fault
        self.write(self.tool.HEADER_REL, b"temporary installed header\n")
        self.write(self.cdc, b"temporary installed ingress\n")
        if self.mode == "wait_fault":
            raise self.fault
        return subprocess.CompletedProcess(argv, 0 if self.mode == "validation_fault" else 1,
                                           "", "inert installer result")

    def call_main(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.tool.main()

    def check_fault(self, mode, fault):
        self.mode, self.fault = mode, fault
        with self.assertRaises(type(fault)) as caught:
            self.call_main()
        self.assertIs(caught.exception, fault)
        self.assert_original()
        self.stage.assert_called_once()
        self.restore.assert_called_once()
        self.assertEqual(self.calls, ["checkout"] if mode == "checkout_fault" else ["checkout", "apply"])

    def test_apply_launch_error_restores_original_bytes(self):
        self.check_fault("launch_fault", OSError("inert spawn failure"))

    def test_apply_keyboard_interrupt_restores_created_header_and_ingress(self):
        self.check_fault("wait_fault", KeyboardInterrupt("inert process-wait interruption"))

    def test_partial_checkout_error_restores_original_bytes(self):
        self.check_fault("checkout_fault", OSError("inert partial checkout failure"))

    def test_partial_checkout_keyboard_interrupt_restores_original_bytes(self):
        self.check_fault("checkout_fault", KeyboardInterrupt("inert partial checkout interruption"))

    def test_nonzero_apply_restores_existing_header_once(self):
        self.original[self.tool.HEADER_REL] = b"pre-existing custom header\xff\r\n"
        self.write(self.tool.HEADER_REL, self.original[self.tool.HEADER_REL])
        self.assertEqual(self.call_main(), 1)
        self.assert_original()
        self.restore.assert_called_once()
        self.assertEqual(self.calls, ["checkout", "apply"])
        self.assertEqual(len(self.tool.FAILED), 1)

    def test_later_validation_failure_still_restores_once(self):
        self.mode = "validation_fault"
        with self.assertRaisesRegex(AssertionError, "GetChassisCmdData"):
            self.call_main()
        self.assert_original()
        self.restore.assert_called_once()
        self.assertEqual(self.calls, ["checkout", "apply"])

    def test_snapshot_failure_does_not_start_mutation_or_restore(self):
        fault = OSError("inert snapshot read failure")
        self.stage.side_effect = fault
        with self.assertRaises(OSError) as caught:
            self.call_main()
        self.assertIs(caught.exception, fault)
        self.assert_original()
        self.runner.assert_not_called()
        self.restore.assert_not_called()

    def test_readonly_missing_preparation_remains_incomplete_without_mutation(self):
        with mock.patch.dict(os.environ, {"POLAR_FIRMWARE_READ_ONLY": "1"}):
            self.assertEqual(self.call_main(), 77)
        self.assert_original()
        self.stage.assert_not_called()
        self.restore.assert_not_called()
        self.runner.assert_not_called()

    def test_prepared_tree_validation_does_not_own_or_restore_files(self):
        self.original[self.tool.USB_REL] += b"\nPOLAR-HOST-BRIDGE\n"
        self.write(self.tool.USB_REL, self.original[self.tool.USB_REL])
        self.original[self.tool.HEADER_REL] = b"pre-existing prepared header"
        self.write(self.tool.HEADER_REL, self.original[self.tool.HEADER_REL])
        with self.assertRaisesRegex(AssertionError, "GetChassisCmdData"):
            self.call_main()
        self.assert_original()
        self.stage.assert_not_called()
        self.restore.assert_not_called()
        self.runner.assert_not_called()

    def test_restore_failure_is_visible_with_original_exception_chained(self):
        self.mode = "launch_fault"
        self.fault = OSError("inert spawn failure")
        cleanup_fault = OSError("inert restore failure")
        self.restore.side_effect = cleanup_fault
        with self.assertRaises(OSError) as caught:
            self.call_main()
        self.assertIs(caught.exception, cleanup_fault)
        self.assertIs(caught.exception.__context__, self.fault)
        self.restore.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
