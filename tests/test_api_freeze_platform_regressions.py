"""No-GUI checks for narrowly scoped API snapshot portability exceptions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "api_freeze_platform_subject", Path(__file__).with_name("api_freeze_test.py")
)
assert _SPEC is not None and _SPEC.loader is not None
api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(api)


def snapshot(members):
    return {"members": members, "module_symbols": {}}


def entry(kind="plain-attribute", type_="int", sig="1"):
    return {"kind": kind, "type": type_, "sig": sig}


class PlatformSnapshotRegressionTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads(api.DEFAULT_BASELINE.read_text(encoding="utf-8"))

    def test_exact_observed_platform_differences_are_clean(self):
        current = json.loads(json.dumps(self.baseline))
        removed = {name: current["members"].pop(name)
                   for name in api.QT_OPTIONAL_MEMBERS}
        self.assertEqual(set(removed), {
            "accessibleIdentifier", "isQmlExposed", "setAccessibleIdentifier",
        })
        for name, value in removed.items():
            self.assertEqual(value, entry(
                "callable", "builtin_function_or_method", f"PolarRMWindow.{name}"
            ))
        self.assertEqual(current["members"]["workspace"],
                         entry(type_="WindowsPath", sig="WindowsPath"))
        current["members"]["workspace"] = entry(type_="PosixPath", sig="PosixPath")
        before = json.dumps(self.baseline, sort_keys=True)
        self.assertTrue(api.is_clean(api.diff_snapshots(self.baseline, current)))
        self.assertTrue(api.is_clean(api.diff_snapshots(current, self.baseline)))
        self.assertEqual(json.dumps(self.baseline, sort_keys=True), before)

    def test_application_method_removal_still_fails(self):
        current = json.loads(json.dumps(self.baseline))
        del current["members"]["draw_watermark"]
        diff = api.diff_snapshots(self.baseline, current)
        self.assertIn("draw_watermark", diff["missing"])
        self.assertFalse(api.is_clean(diff))

    def test_unrelated_inherited_method_removal_still_fails(self):
        diff = api.diff_snapshots(snapshot({"accessibleName": self.baseline["members"]["accessibleName"]}), snapshot({}))
        self.assertEqual(diff["missing"], ["accessibleName"])
        self.assertFalse(api.is_clean(diff))

    def test_optional_name_application_override_is_not_exempt(self):
        for name in api.QT_OPTIONAL_MEMBERS:
            for value in (
                entry("bound-method", "method", f"PolarRMWindow.{name}"),
                {**self.baseline["members"][name], "provider": "rm_client.ui.polar_app"},
            ):
                with self.subTest(name=name, value=value):
                    self.assertFalse(api.is_clean(api.diff_snapshots(snapshot({name: value}), snapshot({}))))
                    self.assertFalse(api.is_clean(api.diff_snapshots(snapshot({}), snapshot({name: value}))))

    def test_optional_method_signature_change_still_fails(self):
        name = "accessibleIdentifier"
        original = self.baseline["members"][name]
        changed = {**original, "sig": "OtherWindow.accessibleIdentifier"}
        diff = api.diff_snapshots(snapshot({name: original}), snapshot({name: changed}))
        self.assertEqual(diff["sig_changed"], [(name, original["sig"], changed["sig"])])
        self.assertFalse(api.is_clean(diff))

    def test_unrelated_type_change_with_identical_signature_fails(self):
        diff = api.diff_snapshots(snapshot({"value": entry()}),
                                  snapshot({"value": entry(type_="str")}))
        self.assertEqual(diff["type_changed"], [("value", "int", "str")])
        self.assertFalse(api.is_clean(diff))
        self.assertIn("value: int -> str", api.format_diff(diff))

    def test_unrelated_signature_change_still_fails(self):
        diff = api.diff_snapshots(snapshot({"value": entry()}),
                                  snapshot({"value": entry(sig="2")}))
        self.assertEqual(diff["sig_changed"], [("value", "1", "2")])
        self.assertFalse(api.is_clean(diff))

    def test_path_exception_does_not_hide_other_changes(self):
        original = entry(type_="WindowsPath", sig="WindowsPath")
        for name, changed in (
            ("other_path", entry(type_="PosixPath", sig="PosixPath")),
            ("workspace", entry(type_="str", sig="PosixPath")),
            ("workspace", entry(type_="PosixPath", sig="different")),
            ("workspace", entry(kind="property", type_="PosixPath", sig="PosixPath")),
        ):
            with self.subTest(name=name, changed=changed):
                self.assertFalse(api.is_clean(api.diff_snapshots(
                    snapshot({name: original}), snapshot({name: changed})
                )))


if __name__ == "__main__":
    unittest.main()
