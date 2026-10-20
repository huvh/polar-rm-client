"""Hit-revision ownership characterization without assets, audio or a window."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_client.kill_fx import KillFxRenderer
from rm_client.ui.polar.mixins.video_backend_mixin import VideoBackendMixin


def bare_renderer():
    renderer = object.__new__(KillFxRenderer)
    renderer._last_hit_revision = -1
    renderer.notify_hit = Mock()
    return renderer


class HitHost:
    update = VideoBackendMixin.update_elimination_hit_info

    def __init__(self):
        self.effect = NS(enabled=True)
        self.registry = NS(get=lambda name: self.effect)
        self.state = NS(projectile_hit_revision=0, last_projectile_damage_delta="12",
                        last_projectile_kind="17mm")
        self.kill_fx = bare_renderer()
        self.hit_enabled = True
        self.settings = []

    def setting_bool(self, module, name, default):
        self.settings.append(name)
        return self.hit_enabled if name == "Hit Info" else default

    def setting_mode(self, module, name, default):
        self.settings.append(name)
        return default

    def get_setting_number(self, module, name, default):
        self.settings.append(name)
        return default

    def elimination_element_toggles(self, module):
        self.settings.append("toggles")
        return {"hit_info": True}


class HitRevisionCharacterizationTests(unittest.TestCase):
    def test_first_revision_notifies_with_existing_arguments(self):
        host = HitHost()
        host.update()
        self.assertEqual(host.kill_fx._last_hit_revision, 0)
        host.kill_fx.notify_hit.assert_called_once_with(
            12, "17mm", preset="Default Scrolling", visibility="Preset",
            sound_enabled=True, volume=55.0, element_toggles={"hit_info": True})
        self.assertEqual(host.settings, ["Hit Info", "Preset", "Element Visibility",
                                        "Sound Enabled", "Sound Volume", "toggles"])

    def test_repeated_revision_skips_all_settings_and_notification(self):
        host = HitHost()
        host.update()
        host.settings.clear()
        host.update()
        self.assertEqual(host.settings, [])
        self.assertEqual(host.kill_fx.notify_hit.call_count, 1)

    def test_any_changed_revision_including_lower_values_is_consumed(self):
        host = HitHost()
        for revision in (4, 5, 2, -1):
            host.state.projectile_hit_revision = revision
            host.update()
            self.assertEqual(host.kill_fx._last_hit_revision, revision)
        self.assertEqual(host.kill_fx.notify_hit.call_count, 4)

    def test_missing_or_disabled_module_does_not_read_or_consume_revision(self):
        class UnreadableState:
            @property
            def projectile_hit_revision(self):
                raise AssertionError("disabled effects must not read a revision")

        for effect in (None, NS(enabled=False)):
            with self.subTest(effect=effect):
                host = HitHost()
                host.effect, host.state = effect, UnreadableState()
                host.update()
                self.assertEqual(host.kill_fx._last_hit_revision, -1)
                self.assertEqual(host.settings, [])
                host.kill_fx.notify_hit.assert_not_called()

    def test_disabled_module_allows_same_revision_after_enable(self):
        host = HitHost()
        host.effect.enabled = False
        host.update()
        host.effect.enabled = True
        host.update()
        host.kill_fx.notify_hit.assert_called_once()

    def test_disabled_hit_info_consumes_revision_without_later_replay(self):
        host = HitHost()
        host.hit_enabled = False
        host.update()
        self.assertEqual(host.kill_fx._last_hit_revision, 0)
        self.assertEqual(host.settings, ["Hit Info"])
        host.hit_enabled = True
        host.update()
        host.kill_fx.notify_hit.assert_not_called()
        host.state.projectile_hit_revision = 1
        host.update()
        host.kill_fx.notify_hit.assert_called_once()

    def test_clear_resets_revision_and_permits_same_revision_again(self):
        host = HitHost()
        renderer = host.kill_fx
        renderer.scrolling = NS(icons=[], pending=[], last_display=0)
        renderer.cs2 = NS(clear=Mock())
        renderer.combo = NS(context=None, started=0)
        renderer.card = NS(cards=[])
        renderer.card_bar = NS(context=None, started=0, waves=[])
        renderer.battlefield = NS(queue=[], context=None, started=0)
        renderer.valorant = NS(context=None, started=0, particles=[])
        renderer.honor = NS(active=[])
        renderer.hit_info = NS(lines=[], last_hit_at=0)
        renderer.companion = NS(lines=[], score_scroll=NS(reset=Mock()))
        host.update()
        renderer.clear()
        self.assertEqual(renderer._last_hit_revision, -1)
        host.update()
        self.assertEqual(renderer.notify_hit.call_count, 2)

    def test_invalid_revision_conversion_preserves_exact_exception_and_state(self):
        for value, error_type in (("bad", ValueError), (None, TypeError)):
            with self.subTest(value=value):
                host = HitHost()
                host.state.projectile_hit_revision = value
                with self.assertRaises(error_type):
                    host.update()
                self.assertEqual(host.kill_fx._last_hit_revision, -1)
                self.assertEqual(host.settings, [])
                host.kill_fx.notify_hit.assert_not_called()

    def test_int_conversion_occurs_once_before_comparison_and_settings(self):
        host = HitHost()
        events = []

        class Revision:
            def __int__(self):
                events.append("int")
                self_test.assertEqual(host.kill_fx._last_hit_revision, -1)
                self_test.assertEqual(host.settings, [])
                return 7

        self_test = self
        host.state.projectile_hit_revision = Revision()
        host.update()
        self.assertEqual(events, ["int"])
        self.assertEqual(host.kill_fx._last_hit_revision, 7)
        self.assertIs(type(host.kill_fx._last_hit_revision), int)

    def test_comparison_failure_does_not_update_or_notify(self):
        failure = RuntimeError("comparison failed")

        class PreviousRevision:
            def __eq__(self, other):
                raise failure

        host = HitHost()
        previous = host.kill_fx._last_hit_revision = PreviousRevision()
        with self.assertRaises(RuntimeError) as raised:
            host.update()
        self.assertIs(raised.exception, failure)
        self.assertIs(host.kill_fx._last_hit_revision, previous)
        self.assertEqual(host.settings, [])
        host.kill_fx.notify_hit.assert_not_called()

    def test_revision_assignment_failure_precedes_settings_and_notification(self):
        failure = RuntimeError("assignment failed")

        class RejectRevision(KillFxRenderer):
            def __setattr__(self, name, value):
                if name == "_last_hit_revision" and value != -1:
                    raise failure
                super().__setattr__(name, value)

        host = HitHost()
        host.kill_fx = object.__new__(RejectRevision)
        host.kill_fx._last_hit_revision = -1
        host.kill_fx.notify_hit = Mock()
        with self.assertRaises(RuntimeError) as raised:
            host.update()
        self.assertIs(raised.exception, failure)
        self.assertEqual(host.kill_fx._last_hit_revision, -1)
        self.assertEqual(host.settings, [])
        host.kill_fx.notify_hit.assert_not_called()

    def test_settings_failure_consumes_revision_without_retry(self):
        host = HitHost()
        failure = RuntimeError("settings failed")
        host.setting_bool = Mock(side_effect=failure)
        with self.assertRaises(RuntimeError) as raised:
            host.update()
        self.assertIs(raised.exception, failure)
        self.assertEqual(host.kill_fx._last_hit_revision, 0)
        host.update()
        host.setting_bool.assert_called_once()
        host.kill_fx.notify_hit.assert_not_called()

    def test_invalid_damage_consumes_revision_without_retry(self):
        host = HitHost()
        host.state.last_projectile_damage_delta = "bad"
        with self.assertRaises(ValueError):
            host.update()
        self.assertEqual(host.kill_fx._last_hit_revision, 0)
        host.state.last_projectile_damage_delta = 12
        host.update()
        host.kill_fx.notify_hit.assert_not_called()

    def test_notification_failure_consumes_revision_without_retry(self):
        host = HitHost()
        failure = RuntimeError("notification failed")
        host.kill_fx.notify_hit.side_effect = failure
        with self.assertRaises(RuntimeError) as raised:
            host.update()
        self.assertIs(raised.exception, failure)
        self.assertEqual(host.kill_fx._last_hit_revision, 0)
        host.update()
        host.kill_fx.notify_hit.assert_called_once()

    def test_reentrant_notification_cannot_consume_same_revision_twice(self):
        host = HitHost()
        host.kill_fx.notify_hit.side_effect = lambda *args, **kwargs: host.update()
        host.update()
        host.kill_fx.notify_hit.assert_called_once()


class HitRevisionOwnerTests(unittest.TestCase):
    def test_owner_only_updates_revision_and_repeats_do_not_write(self):
        class TracedRenderer(KillFxRenderer):
            def __setattr__(self, name, value):
                writes.append((name, value))
                super().__setattr__(name, value)

        writes = []
        renderer = object.__new__(TracedRenderer)
        renderer._last_hit_revision = -1
        renderer.retained = {"cache": object()}
        renderer.notify_hit = Mock(side_effect=AssertionError("not presentation"))
        before = dict(vars(renderer))
        before["retained"] = dict(renderer.retained)
        writes.clear()
        self.assertIs(renderer.consume_hit_revision(-1), False)
        self.assertEqual(writes, [])
        self.assertIs(renderer.consume_hit_revision(7), True)
        self.assertEqual(writes, [("_last_hit_revision", 7)])
        self.assertIs(renderer.consume_hit_revision(7), False)
        self.assertEqual(writes, [("_last_hit_revision", 7)])
        before["_last_hit_revision"] = 7
        self.assertEqual(vars(renderer), before)
        renderer.notify_hit.assert_not_called()

    def test_owner_preserves_equality_operand_order_without_coercion(self):
        events = []

        class Revision:
            def __int__(self):
                raise AssertionError("conversion belongs to the caller")

            def __eq__(self, other):
                events.append(other)
                return False

        renderer = bare_renderer()
        revision = Revision()
        self.assertIs(renderer.consume_hit_revision(revision), True)
        self.assertEqual(events, [-1])
        self.assertIs(renderer._last_hit_revision, revision)


if __name__ == "__main__":
    unittest.main()
