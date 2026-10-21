"""Characterize referee-stage invalidation and its existing safety owner.

Real safety/MQTT/manager methods with no acquired client, device, or worker.
This is an ownership refactor: the characterized boundary behavior is unchanged.
"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_client.backend.manager import BackendManager
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.registry import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, get_profile
from rm_client.backend.safety import OfficialSafety
from rm_client.scenarios import SCENARIOS


class StageResetCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.safety = OfficialSafety()
        self.mqtt = RmMqttBackend(safety=self.safety, mock_output=True)
        self.safety.update_stage(4)
        self.safety.arm_match({"core_kmc"})
        self.safety.mark_published("KeyboardMouseControl", now=123.0)
        self.observed = []
        self.safety.input_clear_hook = lambda reason: self.observed.append(
            (reason, self.safety.current_stage, self.safety._stage_seen))
        self.manager = object.__new__(BackendManager)
        self.manager.safety = self.safety
        self.manager.mqtt = self.mqtt
        self.manager.referee = get_profile(DEFAULT_PROFILE)
        self.manager._lifecycle = SimpleNamespace(
            snapshot=lambda: None, final=False, pending_scenario=None,
            update_pending_identity=lambda value: None, applying=False,
            blocks_work=False,
        )
        self.manager._input_clear_incomplete = lambda: False

    def assert_cleared(self):
        self.assertEqual((self.safety.current_stage, self.safety._stage_seen), ("0", False))
        self.assertFalse(self.safety.is_fighting())
        self.safety.update_stage("MATCH")
        self.assertFalse(self.safety.is_fighting(), "A model label is not fresh referee evidence")
        self.safety.update_stage(4)
        self.assertTrue(self.safety.is_fighting())
        self.assertEqual(self.safety.control_state.value, "LOCKED")
        self.assertIsNone(self.mqtt.client)
        self.assertIsNone(self.mqtt._cleanup_thread)
        self.assertFalse(self.mqtt._started)

    def test_mqtt_stop_preserves_deferred_observer_order(self):
        self.mqtt.stop(wait=False)
        self.assertEqual(self.observed, [("MQTT stopped; explicit re-arm required", "0", False)])
        self.assert_cleared()

    def test_mqtt_endpoint_preserves_deferred_observer_order(self):
        self.assertTrue(self.mqtt.set_address("next.invalid", 3334))
        self.assertEqual(self.observed, [("MQTT endpoint changed", "0", False)])
        self.assert_cleared()

    def test_mqtt_reconnect_preserves_deferred_observer_order(self):
        self.mqtt._schedule_reconnect("link lost")
        self.assertEqual(self.observed, [("link lost", "0", False)])
        self.assert_cleared()

    def test_mqtt_profile_change_preserves_observer_coalescing(self):
        self.mqtt.set_referee_profile(STUDENT_PREVIEW_PROFILE)
        self.assertEqual(self.observed, [("referee profile changed", "0", False)])
        self.assert_cleared()

    def test_mqtt_invalid_profile_preserves_both_observers(self):
        with self.assertRaises(ValueError):
            self.mqtt.set_referee_profile("unsupported-profile")
        self.assertEqual(self.observed, [
            ("MQTT stopped; explicit re-arm required", "0", False),
            ("unsupported referee profile", "0", False),
        ])
        self.assert_cleared()

    def test_manager_identity_change_keeps_immediate_observer_before_stage_reset(self):
        self.manager.set_client_id(7)
        self.assertEqual(self.mqtt.client_id, "7")
        self.assertEqual(self.observed, [
            ("referee robot identity changed", "4", True),
            ("MQTT stopped; explicit re-arm required", "0", False),
        ])
        self.assert_cleared()

    def test_manager_invalid_identity_keeps_immediate_observer_before_stage_reset(self):
        with self.assertRaises(ValueError):
            self.manager.set_client_id("invalid")
        self.assertEqual(self.mqtt.client_id, "3")
        self.assertEqual(self.observed, [
            ("invalid referee robot identity", "4", True),
            ("MQTT stopped; explicit re-arm required", "0", False),
        ])
        self.assert_cleared()

    def test_manager_invalid_profile_preserves_existing_stop_then_lock(self):
        with self.assertRaises(ValueError):
            self.manager.set_referee_profile("unsupported-profile")
        self.assertEqual(self.observed, [
            ("MQTT stopped; explicit re-arm required", "0", False),
            ("unsupported referee profile", "0", False),
        ])
        self.assert_cleared()

    def test_scenario_stage_reset_still_precedes_its_observer(self):
        self.safety.from_scenario(SCENARIOS["LabDebug"])
        self.assertEqual(self.observed, [("scenario changed", "0", False)])
        self.assertEqual(self.safety._publish_at, {})
        self.assert_cleared()

    def test_unchanged_endpoint_identity_and_profile_remain_noops(self):
        before = vars(self.safety).copy()
        self.assertFalse(self.mqtt.set_address(self.mqtt.host, self.mqtt.port))
        self.mqtt.set_referee_profile(DEFAULT_PROFILE)
        self.manager.set_client_id(3)
        self.assertEqual(vars(self.safety), before)
        self.assertEqual(self.observed, [])

    def test_mqtt_stop_does_not_release_estop_or_change_its_timestamp(self):
        self.safety.trigger_estop()
        self.observed.clear()
        timestamp = self.safety.estop_at
        generation = self.safety.control_generation
        self.mqtt.stop(wait=False)
        self.assertTrue(self.safety.estop_active)
        self.assertEqual(self.safety.estop_at, timestamp)
        self.assertEqual(self.safety.control_state.value, "ESTOP")
        self.assertEqual(self.safety.control_generation, generation)
        self.assertEqual((self.safety.current_stage, self.safety._stage_seen), ("0", False))
        self.assertEqual(self.observed, [])


class StageEvidenceOwnerTests(unittest.TestCase):
    def test_owner_changes_only_stage_evidence_and_is_idempotent(self):
        for authority in ("locked", "qualification", "armed", "estop"):
            with self.subTest(authority=authority):
                safety = OfficialSafety()
                safety.update_stage(4)
                if authority == "qualification":
                    safety.begin_qualification({"core_kmc"}, now=100.0)
                elif authority == "armed":
                    safety.arm_match({"core_kmc"})
                elif authority == "estop":
                    safety.trigger_estop()
                safety.mark_published("KeyboardMouseControl", now=123.0)
                events = []
                safety.input_clear_hook = events.append
                expected = {
                    name: value.copy() if isinstance(value, dict) else value
                    for name, value in vars(safety).items()
                }
                expected.update(current_stage="0", _stage_seen=False, _stage_evidence=None)
                safety.clear_stage_evidence()
                self.assertEqual(vars(safety), expected)
                safety.clear_stage_evidence()
                self.assertEqual(vars(safety), expected)
                self.assertEqual(events, [])

    def test_owner_preserves_assignment_order_and_propagates_setter_failure(self):
        class RecordingSafety(OfficialSafety):
            def __setattr__(self, name, value):
                if name in ("current_stage", "_stage_seen"):
                    self.writes.append((name, value))
                    if name == self.fail_on:
                        raise ValueError(name)
                object.__setattr__(self, name, value)

        for field, expected, stage in (
            ("current_stage", [("current_stage", "0")], "4"),
            ("_stage_seen", [("current_stage", "0"), ("_stage_seen", False)], "0"),
        ):
            with self.subTest(field=field):
                safety = object.__new__(RecordingSafety)
                object.__setattr__(safety, "current_stage", "4")
                object.__setattr__(safety, "_stage_seen", True)
                safety.writes, safety.fail_on = [], field
                with self.assertRaisesRegex(ValueError, field):
                    safety.clear_stage_evidence()
                self.assertEqual(safety.writes, expected)
                self.assertEqual(safety.current_stage, stage)
                self.assertTrue(safety._stage_seen)


if __name__ == "__main__":
    unittest.main()
