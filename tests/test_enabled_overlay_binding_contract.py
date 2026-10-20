"""Short-circuit and live-release contracts for enabled overlay bindings."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from keyboard_routing_harness import BASELINE, Case, Event, Harness, Key, current, _CURSOR
from PySide6.QtCore import Qt


class ObservedModule:
    def __init__(self, host, name, *, enabled=True, binding="X", fail=None):
        self.host, self.name = host, name
        self.enabled_value, self.binding_value, self.fail = enabled, binding, fail

    def observe(self, field, value):
        self.host.record("module." + field, self.name)
        if self.fail == field:
            raise ValueError("injected " + field)
        return value

    def __bool__(self):
        return self.observe("bool", True)

    @property
    def enabled(self):
        return self.observe("enabled", self.enabled_value)

    @property
    def keybind(self):
        return self.observe("keybind", self.binding_value)


class EnabledOverlayBindingContractTests(unittest.TestCase):
    def trace(self, implementation, name, phase, *, enabled=True, binding="X", fail=None, missing=False):
        host = Harness(Case(wheel=phase == "release"))
        host.modules[name] = None if missing else ObservedModule(
            host, name, enabled=enabled, binding=binding, fail=fail)
        if fail == "matcher":
            def match(*args):
                host.record("matcher.failure")
                raise ValueError("injected matcher")
            host.keybind_matches = match
        event = Event(Key(Qt.Key.Key_Z, phase=phase), host)
        error = None
        with patch.object(current, "QCursor", _CURSOR):
            try:
                getattr(implementation, "keyPressEvent" if phase == "press" else "keyReleaseEvent")(host, event)
            except Exception as exc:
                error = (type(exc), str(exc))
        return host.trace, event.accepted, error

    def test_five_sites_preserve_getter_short_circuit_and_exception_order(self):
        sites = [(name, "press") for name in ("MatchChat", "QuickActionWheel", "EconomyPanel", "ProjectileShop")]
        sites.append(("QuickActionWheel", "release"))
        cases = ({}, {"missing": True}, {"enabled": False}, {"binding": "None"},
                 {"fail": "bool"}, {"fail": "enabled"}, {"fail": "keybind"}, {"fail": "matcher"})
        for name, phase in sites:
            for options in cases:
                with self.subTest(name=name, phase=phase, options=options):
                    expected = self.trace(BASELINE, name, phase, **options)
                    self.assertEqual(self.trace(current.InputDispatchMixin, name, phase, **options), expected)
                    observed = [entry[0] for entry in expected[0] if entry[0].startswith("module.")]
                    if options.get("enabled") is False:
                        self.assertEqual(observed, ["module.bool", "module.enabled"])
                    if options.get("binding") == "None":
                        self.assertEqual(observed, ["module.bool", "module.enabled", "module.keybind"])

    def test_wheel_release_uses_current_enabled_binding_and_repeat(self):
        for enabled, binding, repeat, finishes in (
            (True, "X", False, True), (False, "X", False, False),
            (True, "Z", False, False), (True, "None", False, False),
            (True, "X", True, False),
        ):
            traces = []
            for implementation in (BASELINE, current.InputDispatchMixin):
                host = Harness(Case(bindings={"QuickActionWheel": "X"}))
                with patch.object(current, "QCursor", _CURSOR):
                    implementation.keyPressEvent(host, Event(Key(Qt.Key.Key_X), host))
                    self.assertTrue(host.quick_action_wheel.active)
                    host.modules["QuickActionWheel"].enabled = enabled
                    host.modules["QuickActionWheel"].keybind = binding
                    implementation.keyReleaseEvent(host, Event(Key(Qt.Key.Key_X, phase="release", repeat=repeat), host))
                traces.append(host.trace)
                self.assertEqual(not host.quick_action_wheel.active, finishes)
            self.assertEqual(*traces)


if __name__ == "__main__":
    unittest.main()
