"""Annual referee isolation, with inert writers only; no devices or broker."""
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.wire import encode_uint
from rm_client.backend.safety import ControlState
from rm_client.backend.serial_backend import RmSerialBackend
from rm_client.protocol import RefereeFrameCodec
from rm_client.model import RobotState
from rm_client.referee_profiles import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, V2_PROFILE
from rm_client.rules_compatibility import normalize_rule_season, official_rule_compatibility


class Client:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos):
        self.sent.append((topic, payload, qos))
        return NS(rc=0)


class SerialDriver:
    def __init__(self):
        self.written = []

    def write(self, payload):
        self.written.append(bytes(payload))
        return len(payload)

    def close(self):
        pass


class LifecycleClient(Client):
    """Paho-shaped inert owner. Network acquisition is forbidden by setUp."""
    def __init__(self, *a, **kw):
        super().__init__()
        self.connections = []
        self.subscriptions = []
        self.loop_starts = self.disconnects = self.loop_stops = 0
        self.closing = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def reconnect_delay_set(self, **kw):
        pass

    def connect_async(self, host, port, **kw):
        self.connections.append((host, port))

    def loop_start(self):
        self.loop_starts += 1
        return 0

    def subscribe(self, topics):
        self.subscriptions.append(topics)
        return 0, 17

    def disconnect(self):
        self.disconnects += 1

    def loop_stop(self):
        self.loop_stops += 1
        self.closing.set()
        if not self.release.wait(3):
            raise AssertionError("inert cleanup release missing")
        return 0


class RuleSeasonBackendTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket", "serial.Serial", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("device/network acquisition forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def backend(self, profile=DEFAULT_PROFILE, *, mock=False):
        b = BackendManager.__new__(BackendManager)
        b.state = RobotState()
        b.rule_season = 2026
        b.mqtt = RmMqttBackend(referee_profile=profile, mock_output=mock)
        b.mqtt.client = Client()
        b.mqtt.connected = b.mqtt._subscriptions_ready = True
        b.safety = b.mqtt.safety
        b.serial = RmSerialBackend(safety=b.safety)
        b.serial.bind_rule_state(b.state)
        b.safety.configure(allow_mqtt_publish=True, mock_writes=mock,
                           enforce_official_limits=True)
        b.referee = b.mqtt.referee
        b.referee_adapter = b.referee.create_state_adapter(b)
        b.state.referee_profile = profile
        b.qualification = NS(session=NS(referee_profile=profile, match_mode="RMUC7v7", robot_id="3"))
        b.mqtt.bind_economy_context(b.state, b.qualification)
        b._backend_transition_blocks_work = lambda: False
        b._drain_input_clear = lambda: None
        b._input_clear_incomplete = lambda: False
        b._official_state_updates_count = b._apply_error_count = 0
        b._last_apply_error = b._referee_view_error = b._last_logged_stage = ""
        b.field_log = NS(emit=lambda *a, **kw: None)
        b.referee_view_observer = None
        b.stats = lambda: {}
        return b

    def receive(self, b, name="GameStatus", payload=None):
        if payload is None:
            payload = encode_uint(5, 4) + encode_uint(6, 120)
        b.mqtt._on_message(b.mqtt.client, None, NS(topic=name, payload=payload))

    def qualify(self, b):
        return b.safety.begin_qualification({"core_kmc", "economy", "control", "settings", "hero"})

    def serial_backend(self, *, mock=False):
        serial = RmSerialBackend(mock_writes=mock)
        serial._serial = driver = SerialDriver()
        serial.connected = True
        return serial, driver

    def paho_factory(self, factory):
        paho, mqtt, client = (ModuleType(n) for n in ("paho", "paho.mqtt", "paho.mqtt.client"))
        paho.mqtt, mqtt.client = mqtt, client
        client.Client = factory
        client.CallbackAPIVersion = NS(VERSION2=2)
        client.MQTTv311, client.MQTT_ERR_SUCCESS = 4, 0
        return patch.dict(sys.modules, {"paho": paho, "paho.mqtt": mqtt, "paho.mqtt.client": client})

    def assert_no_network_owner(self, mqtt):
        self.assertIsNone(mqtt.client)
        self.assertFalse(mqtt.connected)
        self.assertFalse(mqtt._started)
        self.assertFalse(mqtt._pending_start)
        self.assertFalse(mqtt._reconnect_required)
        self.assertFalse(mqtt._zero_after_reconnect)

    def test_only_explicit_integer_seasons_and_legacy_default(self):
        for value in (2026, 2027):
            self.assertEqual(normalize_rule_season(value), value)
        for value in (None, True, "2027", 2027., 2025, 2028, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_rule_season(value)
        self.assertTrue(official_rule_compatibility(2026, 2026, state=NS())[0])
        self.assertFalse(official_rule_compatibility(2027, 2027)[0])
        self.assertFalse(official_rule_compatibility(2026, 2027)[0])

    def test_invalid_setter_cannot_partially_mutate_epoch(self):
        b = self.backend()
        for value in (2028, "2027", True, 2027.):
            before = (b.rule_season, b.state.rules_season, b.mqtt.receive_generation,
                      b.safety.control_generation, b.qualification.session)
            with self.assertRaises(ValueError):
                b.set_rule_season(value)
            self.assertEqual(before, (b.rule_season, b.state.rules_season, b.mqtt.receive_generation,
                                     b.safety.control_generation, b.qualification.session))

    def test_setter_works_before_first_runtime_and_repeats_are_idempotent(self):
        b = self.backend()
        b.state.rules_season = 2027  # Registry seed precedes first runtime call.
        b.set_rule_season(2027)
        self.assertEqual((b.rule_season, b.mqtt.rule_season), (2027, 2027))
        epoch = (b.mqtt.receive_generation, b.safety.control_generation)
        b.set_rule_season(2027)
        self.assertEqual(epoch, (b.mqtt.receive_generation, b.safety.control_generation))
        self.assertFalse(b.mqtt.official_rules_admission()[0])

    def test_switch_retires_phase_token_signed_session_and_all_official_queues(self):
        b = self.backend(V2_PROFILE)
        token = self.qualify(b)
        self.receive(b)
        self.assertTrue(b.safety.is_fighting())
        self.assertIsNotNone(b.mqtt.v2_wire_snapshot())
        old_session = b.qualification.session
        b.set_rule_season(2027)
        self.assertIsNone(b.qualification.session)
        self.assertIsNone(b.safety._qualification)
        self.assertFalse(b.safety.is_fighting())
        self.assertEqual(b.safety.control_state, ControlState.LOCKED)
        self.assertEqual(b.mqtt.drain_decoded(), [])
        self.assertEqual(b.mqtt.drain_received_messages(), [])
        self.assertIsNone(b.mqtt.v2_wire_snapshot())
        b.qualification.session = old_session  # Even restoring signed bytes cannot arm 2027.
        self.assertFalse(b.arm_match_control(firmware_hash="a" * 64)[0])
        with self.assertRaises(ValueError):
            b.begin_qualification({"core_kmc"})
        self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0])

    def test_reentrant_year_edit_during_qualification_or_arm_notification_is_not_success(self):
        for action in ("qualification", "arm"):
            b = self.backend()
            b.qualification.verified_core_ready = lambda: (True, "ok")
            b.qualification.identity_matches = lambda **kw: (True, "ok")
            b.qualification.capabilities = lambda: {"core_kmc"}
            b._canonical_readiness_video_source = lambda: "udp"
            def edit(reason):
                if "epoch started" in reason or "control armed" in reason:
                    b.state.rules_season = 2027
            b.safety.input_clear_hook = edit
            if action == "qualification":
                with self.assertRaises(ValueError):
                    b.begin_qualification({"core_kmc"})
            else:
                self.assertFalse(b.arm_match_control(firmware_hash="a" * 64)[0])
            self.assertEqual(b.safety.control_state, ControlState.LOCKED)
            self.assertIsNone(b.safety._qualification)
            self.assertEqual(b.mqtt.client.sent, [])

    def test_official_observations_are_retired_without_touching_independent_state(self):
        b = self.backend()
        s = b.state
        s.official_state_active = True
        s.official_state_at = s.official_feed_at = 100.
        s.robot_statics[3] = {"max_health": 999}
        s.performance_sync["shooter"] = 2
        s.buff_rows.append({"buff_type": 1})
        s.map_robots.append({"x": 5})
        s.control_zones.append({"owner": "RED", "progress": 1., "observed": True})
        s.polar_overlay = {"current_health": 75}
        s.polar_link_active = True
        independent = (deepcopy(s.polar_overlay), s.polar_link_active)
        b.set_rule_season(2027)
        self.assertFalse(s.official_state_active)
        self.assertEqual((s.current_stage, s.current_health, s.remaining_economy), ("NOT_STARTED", 0, 0))
        self.assertEqual((s.robot_statics, s.performance_sync, s.buff_rows, s.map_robots), ({}, {}, [], []))
        self.assertEqual(s.control_zones, [])
        self.assertEqual((s.polar_overlay, s.polar_link_active), independent)

    def test_failed_state_retirement_cannot_preserve_old_official_authority(self):
        b = self.backend()
        self.qualify(b)
        self.receive(b)
        b.state.official_state_active = True
        b.state.buff_rows = object()  # Deliberately malformed presentation data.
        with self.assertRaises(AttributeError):
            b.set_rule_season(2027)
        self.assertFalse(b.state.official_state_active)
        self.assertFalse(b.safety.is_fighting())
        self.assertEqual(b.safety.control_state, ControlState.LOCKED)
        self.assertIsNone(b.qualification.session)
        self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1)[0])

    def test_season_change_preserves_estop_and_dedicated_zero(self):
        for profile in (DEFAULT_PROFILE, V2_PROFILE):
            b = self.backend(profile)
            b.safety.trigger_estop()
            b.set_rule_season(2027)
            self.assertTrue(b.safety.estop_active)
            self.assertEqual(b.safety.control_state, ControlState.ESTOP)
            self.assertTrue(b.mqtt.publish_estop_zero()[0])
            self.assertEqual(b.mqtt.client.sent, [("KeyboardMouseControl", b.referee.codec.encode_keyboard_mouse_control(), 1)])
            self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1)[0])

    def test_all_profiles_topics_and_wrappers_cannot_write_2027(self):
        for profile in (DEFAULT_PROFILE, V2_PROFILE, STUDENT_PREVIEW_PROFILE):
            for mock in (False, True):
                b = self.backend(profile, mock=mock)
                b.set_rule_season(2027)
                for topic in b.referee.codec.UPLINK_MESSAGES:
                    with self.subTest(profile=profile, mock=mock, topic=topic):
                        self.assertFalse(b.mqtt.publish_topic(topic, b"", intent="estop_zero")[0])
                        self.assertFalse(b.mqtt.publish_named(topic, b"")[0])
                        self.assertFalse(b.mqtt.publish_binary(topic, b""))
                        self.assertFalse(b.mqtt.publish_match_command(topic, b""))
                self.assertEqual(b.mqtt.client.sent, [])
                self.assertEqual(list(b.mqtt.publish_records), [])

    def test_every_old_downlink_is_rejected_before_decode_and_observers(self):
        for profile in (DEFAULT_PROFILE, V2_PROFILE, STUDENT_PREVIEW_PROFILE):
            b = self.backend(profile)
            b.set_rule_season(2027)
            with patch.object(b.referee.codec, "decode_message", side_effect=AssertionError("old annual decoder forbidden")):
                for name in b.referee.codec.DOWNLINK_MESSAGES:
                    self.receive(b, name, b"")
            self.assertEqual(b.mqtt.drain_decoded(), [])
            self.assertEqual(b.mqtt.drain_received_messages(), [])
            self.assertEqual(b.apply_updates(b.state), 0)
            self.assertFalse(b.safety.is_fighting())

    def test_final_enqueue_cannot_bypass_gate_by_omitting_authority_or_forging_intent(self):
        for profile in (DEFAULT_PROFILE, V2_PROFILE):
            b = self.backend(profile)
            b.set_rule_season(2027)
            for topic in b.referee.codec.UPLINK_MESSAGES:
                with self.subTest(profile=profile, topic=topic), self.assertRaises(RuntimeError):
                    b.mqtt._publish_current(b.mqtt.client, b.mqtt._lifecycle_generation, topic,
                                            encode_uint(1, 1), 1)
            self.assertEqual(b.mqtt.client.sent, [])

    def test_paused_publication_season_switch_is_rechecked_at_actual_enqueue(self):
        b = self.backend()
        token = self.qualify(b)
        real = b.mqtt._publish_current
        def pause(*a, **kw):
            b.set_rule_season(2027)
            return real(*a, **kw)
        with patch.object(b.mqtt, "_publish_current", side_effect=pause):
            self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0])
        self.assertEqual(b.mqtt.client.sent, [])

    def test_switch_away_and_back_cannot_resurrect_paused_command(self):
        b = self.backend()
        token = self.qualify(b)
        real = b.mqtt._publish_current
        def pause(*a, **kw):
            b.set_rule_season(2027)
            b.set_rule_season(2026)
            self.qualify(b)
            return real(*a, **kw)
        with patch.object(b.mqtt, "_publish_current", side_effect=pause):
            self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0])
        self.assertEqual(b.mqtt.client.sent, [])

    def test_bound_state_year_is_checked_even_if_caller_omits_setter(self):
        b = self.backend()
        token = self.qualify(b)
        b.state.rules_season = 2027
        self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0])
        self.receive(b)
        self.assertEqual(b.mqtt.drain_decoded(), [])
        with self.assertRaises(RuntimeError):
            b.mqtt._publish_current(b.mqtt.client, b.mqtt._lifecycle_generation,
                                    "CommonCommand", encode_uint(1, 1), 1)

    def test_inflight_decode_cannot_supply_stage_or_old_state_after_switch(self):
        b = self.backend()
        original = b.referee.codec.decode_message
        def decode(*a):
            b.set_rule_season(2027)
            return original(*a)
        with patch.object(b.referee.codec, "decode_message", side_effect=decode):
            self.receive(b)
        self.assertFalse(b.safety.is_fighting())
        self.assertEqual(b.mqtt.drain_decoded(), [])
        self.assertEqual(b.mqtt.drain_received_messages(), [])

    def test_detached_batch_cannot_repopulate_2027_observations_or_view(self):
        b = self.backend()
        self.receive(b, "GlobalLogisticsStatus", encode_uint(1, 123))
        self.receive(b, "GlobalLogisticsStatus", encode_uint(1, 999))
        seen = []
        def observe(*a):
            seen.append(a)
            b.set_rule_season(2027)
        b.referee_view_observer = observe
        self.assertEqual(b.apply_updates(b.state), 1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(b.state.remaining_economy, 0)
        self.assertFalse(b.state.official_state_active)

    def test_direct_manager_adapter_and_frontend_seams_do_not_project_2026_into_2027(self):
        b = self.backend()
        b.state.rules_season = 2027
        before = deepcopy(vars(b.state))
        b._apply_one(b.state, "GlobalLogisticsStatus", {"remaining_economy": 999})
        b.sync_frontend_state(b.state)
        self.assertEqual(vars(b.state), before)

    def test_transport_retirement_drops_old_qos_owner_without_restart(self):
        b = self.backend()
        b.mqtt._started = True
        with patch.object(b.mqtt, "_stop_client_locked") as stop, patch.object(b.mqtt, "_request_start_locked") as restart:
            b.set_rule_season(2027)
        stop.assert_called_once_with()
        restart.assert_not_called()
        self.assertTrue(all(row[0] == "KeyboardMouseControl" and
                            row[1] == b.referee.codec.encode_keyboard_mouse_control()
                            for row in b.mqtt.client.sent))

    def test_background_enqueue_paused_across_switch_is_discarded(self):
        for profile in (DEFAULT_PROFILE, V2_PROFILE):
            b = self.backend(profile)
            self.qualify(b)
            entered, release = threading.Event(), threading.Event()
            original = b.mqtt._publish_current
            result = []
            def pause(*a, **kw):
                entered.set()
                if not release.wait(3):
                    raise AssertionError("missing test release")
                return original(*a, **kw)
            # V2 KMC requires role evidence; test the actual final boundary
            # directly to avoid manufacturing that unrelated authorization.
            def run():
                try:
                    pause(b.mqtt.client, b.mqtt._lifecycle_generation,
                          "CommonCommand", encode_uint(1, 1), 1,
                          authority_generation=b.safety.control_generation)
                except RuntimeError as exc:
                    result.append(str(exc))
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                b.set_rule_season(2027)
            finally:
                release.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(result), 1)
            self.assertEqual(b.mqtt.client.sent, [])
            self.assertIsNone(b.safety._qualification)

    def test_mock_and_protocol_year_diagnostics_do_not_claim_2027_wire_support(self):
        b = self.backend(V2_PROFILE, mock=True)
        b.set_rule_season(2027)
        stats = b.mqtt.stats()
        self.assertEqual((stats["rule_season"], stats["protocol_year"]), (2027, 2026))
        self.assertFalse(stats["rule_protocol_compatible"])
        self.assertIn("no reviewed", stats["rule_protocol_reason"])
        self.assertTrue(b.mqtt.publish_estop_zero()[0])
        self.assertTrue(b.mqtt.publish_records[-1].mock_output)
        self.assertEqual(b.mqtt.messages_sent, 0)

    def test_2026_default_still_requires_existing_lock_token_and_stage_policy(self):
        b = self.backend()
        self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1)[0])
        token = self.qualify(b)
        self.assertTrue(b.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0])
        self.assertEqual(len(b.mqtt.client.sent), 1)
        self.receive(b, "GlobalLogisticsStatus", encode_uint(1, 99))
        self.assertEqual(b.apply_updates(b.state), 1)
        self.assertEqual(b.state.remaining_economy, 99)
        b.set_rule_season(2027)
        b.set_rule_season(2026)
        self.assertIsNone(b.qualification.session)
        self.assertFalse(b.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0])

    def test_serial_2026_raw_send_and_frame_apis_keep_original_wire(self):
        serial, driver = self.serial_backend()
        frame = RefereeFrameCodec().encode(0x0201, b"ok")
        self.assertEqual(serial.write(frame), (True, "ok"))
        self.assertEqual(serial.send(frame), (True, "ok"))
        self.assertEqual(serial.write_frame(0x0201, b"ok"), (True, "ok"))
        self.assertEqual(len(driver.written), 3)
        self.assertEqual(driver.written[:2], [frame, frame])
        self.assertEqual(RefereeFrameCodec().decode(driver.written[-1])[0].data, b"ok")
        self.assertEqual(serial.frames_written, 3)
        self.assertFalse(serial.write_stop_command()[0])
        self.assertFalse(serial.write_frame(0x0311, b"\x00" * 30)[0])

    def test_serial_2027_all_real_routes_and_valid_zero_frames_stay_locked(self):
        serial, driver = self.serial_backend()
        serial.set_rule_season(2027)
        frame = RefereeFrameCodec().encode(0x0201, b"\x00" * 30)
        for call in (lambda: serial.write(frame), lambda: serial.send(frame),
                     lambda: serial.write_frame(0x0201, b"\x00" * 30),
                     lambda: serial._write_payload(frame, bypass_estop=True),
                     lambda: serial.write(frame + frame)):
            self.assertFalse(call()[0])
        self.assertEqual(driver.written, [])
        self.assertEqual((serial.frames_written, serial.last_write_at), (0, 0.))
        self.assertEqual(serial.stats()["protocol_year"], 2026)
        self.assertFalse(serial.stats()["rule_protocol_compatible"])

    def test_serial_mock_is_diagnostic_not_annual_protocol_or_wire_evidence(self):
        serial, driver = self.serial_backend(mock=True)
        serial.set_rule_season(2027)
        result = serial.write_frame(0x0201, b"ok")
        self.assertTrue(result[0])
        self.assertIn("mock", result[1])
        self.assertIn("no reviewed", result[1])
        self.assertTrue(serial.last_write.startswith(b"\xa5"))
        self.assertEqual(driver.written, [])
        self.assertEqual((serial.frames_written, serial.last_write_at), (0, 0.))
        self.assertFalse(serial.stats()["rule_protocol_compatible"])

    def test_manager_syncs_serial_owner_and_direct_state_edit_cannot_bypass(self):
        b = self.backend()
        b.serial.mock_writes = False
        b.serial._serial = driver = SerialDriver()
        b.serial.connected = True
        b.set_rule_season(2027)
        self.assertEqual(b.serial.rule_season, 2027)
        self.assertFalse(b.serial.write_frame(0x0201, b"ok")[0])
        b.set_rule_season(2026)
        b.state.rules_season = 2027  # A stale owner setting is not authority.
        self.assertFalse(b.serial.write_frame(0x0201, b"ok")[0])
        self.assertEqual(driver.written, [])

    def test_serial_invalid_season_does_not_release_latch_or_change_epoch(self):
        serial, driver = self.serial_backend()
        serial.request_estop()
        before = serial._rule_context
        for value in (2028, "2027", True, 2027.):
            with self.assertRaises(ValueError):
                serial.set_rule_season(value)
            self.assertIs(serial._rule_context, before)
        for season in (2027, 2026):
            serial.set_rule_season(season)
            self.assertTrue(serial.estop_active)
            self.assertFalse(serial._write_payload(RefereeFrameCodec().encode(0x0201), bypass_estop=True)[0])
        self.assertEqual(driver.written, [])

    def test_serial_capture_precedes_encoding_and_payload_conversion(self):
        for route in ("frame", "raw"):
            serial, driver = self.serial_backend()
            def switch():
                serial.set_rule_season(2027)
                serial.set_rule_season(2026)
            if route == "frame":
                original = serial.codec.encode
                def encode(*a, **kw):
                    switch()
                    return original(*a, **kw)
                with patch.object(serial.codec, "encode", side_effect=encode):
                    self.assertFalse(serial.write_frame(0x0201, b"ok")[0])
            else:
                class Payload:
                    def __bytes__(self):
                        switch()
                        return RefereeFrameCodec().encode(0x0201, b"ok")
                self.assertFalse(serial.write(Payload())[0])
            self.assertEqual(driver.written, [])

    def test_serial_final_driver_resolution_cannot_replay_request_after_aba(self):
        for boundary in ("driver_method", "final_safety_read"):
            serial, driver = self.serial_backend()
            def switch():
                serial.set_rule_season(2027)
                serial.set_rule_season(2026)
            if boundary == "driver_method":
                class DriverOwner:
                    @property
                    def write(self):
                        switch()
                        return driver.write
                serial._serial = DriverOwner()
            else:
                class SafetyRead:
                    reads = 0
                    @property
                    def estop_active(self):
                        self.reads += 1
                        if self.reads == 2:
                            switch()
                        return False
                serial.safety = SafetyRead()
            self.assertFalse(serial.write_frame(0x0201, b"ok")[0])
            self.assertEqual(driver.written, [])

    def test_serial_queued_raw_and_send_keep_pre_wait_epoch(self):
        for route in ("write", "send", "private"):
            serial, driver = self.serial_backend()
            entered = threading.Event()
            original = serial._write_payload
            result = []
            def observed(*a, **kw):
                entered.set()
                return original(*a, **kw)
            frame = RefereeFrameCodec().encode(0x0201, b"ok")
            def run():
                result.append(getattr(serial, route)(frame))
            if route == "private":
                # Exercise the private method's own capture via a traced lock.
                owner = threading.get_ident()
                lock = serial._write_lock
                class TracedLock:
                    def __enter__(self):
                        if threading.get_ident() != owner:
                            entered.set()
                        lock.acquire()
                    def __exit__(self, *a):
                        lock.release()
                serial._write_lock = TracedLock()
                run = lambda: result.append(serial._write_payload(frame, bypass_estop=True))
            observation = (patch.object(serial, "_write_payload", side_effect=observed)
                           if route != "private" else nullcontext())
            with observation:
                with serial._write_lock:
                    worker = threading.Thread(target=run, daemon=True)
                    worker.start()
                    self.assertTrue(entered.wait(3))
                    before = time.monotonic()
                    serial.set_rule_season(2027)
                    serial.set_rule_season(2026)
                    self.assertLess(time.monotonic() - before, .2)
                worker.join(3)
                self.assertFalse(worker.is_alive())
            self.assertEqual(len(result), 1)
            self.assertFalse(result[0][0])
            self.assertEqual(driver.written, [])

    def test_serial_in_driver_bytes_are_not_recalled_but_next_waiter_is_retired(self):
        serial, driver = self.serial_backend()
        entered, release, queued = threading.Event(), threading.Event(), threading.Event()
        def blocked(payload):
            driver.written.append(bytes(payload))
            entered.set()
            if not release.wait(3):
                raise AssertionError("missing inert driver release")
            return len(payload)
        serial._serial = NS(write=blocked)
        frame = RefereeFrameCodec().encode(0x0201, b"ok")
        results = [None, None]
        first = threading.Thread(target=lambda: results.__setitem__(0, serial.write(frame)), daemon=True)
        first.start()
        self.assertTrue(entered.wait(3))
        original = serial._write_payload
        def waiting(*a, **kw):
            queued.set()
            return original(*a, **kw)
        try:
            with patch.object(serial, "_write_payload", side_effect=waiting):
                second = threading.Thread(target=lambda: results.__setitem__(1, serial.write(frame)), daemon=True)
                second.start()
                self.assertTrue(queued.wait(3))
                before = time.monotonic()
                serial.set_rule_season(2027)
                serial.set_rule_season(2026)
                self.assertLess(time.monotonic() - before, .2)
                release.set()
                first.join(3)
                second.join(3)
        finally:
            release.set()
            first.join(3)
        self.assertEqual([ok for ok, _reason in results], [True, False])
        self.assertEqual(driver.written, [frame])

    def test_2027_start_and_private_acquisition_never_construct_paho_even_in_mock(self):
        for profile in (DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, V2_PROFILE):
            for mock in (False, True):
                mqtt = RmMqttBackend(referee_profile=profile, mock_output=mock)
                mqtt.set_rule_season(2027)
                factory = Mock(side_effect=AssertionError("Paho acquisition forbidden"))
                with self.paho_factory(factory):
                    mqtt.start()
                    with mqtt._lifecycle_lock:
                        mqtt._request_start_locked()
                        mqtt._start_client_locked()
                    mqtt.poll_connection()
                    zero = mqtt.publish_estop_zero()
                    if mock and not mqtt.referee.read_only:
                        self.assertEqual(zero, (True, "mock"))
                        self.assertTrue(mqtt.publish_records[-1].mock_output)
                    else:
                        self.assertFalse(zero[0])
                    self.assertEqual(mqtt.messages_sent, 0)
                factory.assert_not_called()
                self.assert_no_network_owner(mqtt)
                self.assertFalse(mqtt.stats()["rule_protocol_compatible"])

    def test_bound_2027_state_blocks_start_without_explicit_setter(self):
        mqtt = RmMqttBackend(mock_output=False)
        mqtt.bind_economy_context(NS(rules_season=2027), None)
        factory = Mock(side_effect=AssertionError("Paho acquisition forbidden"))
        with self.paho_factory(factory):
            mqtt.start()
            mqtt._reconnect_required = True
            mqtt._next_reconnect_at = 0
            mqtt.poll_connection()
        factory.assert_not_called()
        self.assert_no_network_owner(mqtt)

    def test_2027_retry_endpoint_profile_and_failure_callback_cannot_reacquire(self):
        mqtt = RmMqttBackend(mock_output=False)
        mqtt.set_rule_season(2027)
        factory = Mock(side_effect=AssertionError("Paho acquisition forbidden"))
        with self.paho_factory(factory):
            mqtt._started = mqtt._reconnect_required = mqtt._zero_after_reconnect = True
            mqtt._next_reconnect_at = 0
            mqtt.poll_connection()
            mqtt._started = True
            mqtt.set_address("2026-only.invalid", 3333)
            mqtt._started = True
            mqtt.set_referee_profile(V2_PROFILE)
            mqtt._on_connect_fail(None, None)
            mqtt.poll_connection()
        factory.assert_not_called()
        self.assert_no_network_owner(mqtt)

    def test_pending_cleanup_callback_cannot_restore_canceled_2027_start(self):
        for mode in ("setter", "stale_pending", "state_edit"):
            clients = []
            def make(*a, **kw):
                value = LifecycleClient()
                clients.append(value)
                return value
            mqtt = RmMqttBackend(mock_output=False)
            state = NS(rules_season=2026)
            mqtt.bind_economy_context(state, None)
            with self.paho_factory(make):
                try:
                    mqtt.start()
                    old = clients[0]
                    old.release.clear()
                    mqtt.stop(wait=False)
                    self.assertTrue(old.closing.wait(3))
                    mqtt.start()
                    self.assertTrue(mqtt._pending_start)
                    if mode == "state_edit":
                        state.rules_season = 2027
                    else:
                        mqtt.set_rule_season(2027)
                        if mode == "stale_pending":
                            mqtt._pending_start = mqtt._started = True
                    old.release.set()
                    self.assertTrue(mqtt.wait_stopped(3))
                    mqtt.poll_connection()
                    self.assert_no_network_owner(mqtt)
                    self.assertEqual(len(clients), 1)
                    self.assertEqual((old.connections, old.loop_starts), ([("127.0.0.1", 3333)], 1))
                    self.assertEqual(old.sent, [])
                finally:
                    for owner in clients:
                        owner.release.set()
                    mqtt.stop()

    def test_return_to_2026_requires_explicit_start_and_never_restores_motion(self):
        clients = []
        def make(*a, **kw):
            value = LifecycleClient()
            clients.append(value)
            return value
        mqtt = RmMqttBackend(mock_output=False)
        with self.paho_factory(make):
            try:
                mqtt.start()
                old = mqtt.client
                token = mqtt.safety.begin_qualification({"core_kmc"})
                mqtt.set_rule_season(2027)
                self.assertTrue(mqtt.wait_stopped(3))
                mqtt.start()
                mqtt.poll_connection()
                self.assertEqual(len(clients), 1)
                mqtt.set_rule_season(2026)
                mqtt.poll_connection()
                self.assert_no_network_owner(mqtt)
                self.assertEqual(len(clients), 1)
                mqtt.start()
                self.assertEqual(len(clients), 2)
                self.assertIsNot(mqtt.client, old)
                mqtt._on_connect(mqtt.client, None, {}, 0)
                mqtt._on_subscribe(mqtt.client, None, 17, [0] * len(mqtt.referee.codec.DOWNLINK_MESSAGES))
                self.assertEqual(mqtt.safety.control_state, ControlState.LOCKED)
                self.assertIsNone(mqtt.safety._qualification)
                self.assertFalse(mqtt.publish_topic("KeyboardMouseControl",
                    mqtt.referee.codec.encode_keyboard_mouse_control(keyboard_value=1),
                    qualification_token=token.value, intent="core_kmc")[0])
                self.assertEqual(clients[-1].sent, [])
            finally:
                mqtt.stop()

    def test_connect_event_year_edit_cannot_subscribe_2026_topics_or_call_login_hook(self):
        mqtt = RmMqttBackend(mock_output=False)
        state = NS(rules_season=2026)
        mqtt.bind_economy_context(state, None)
        with self.paho_factory(LifecycleClient):
            try:
                mqtt.start()
                client = mqtt.client
                mqtt._on_connect_hook = Mock()
                def event(kind, **kw):
                    if kind == "mqtt_connect":
                        state.rules_season = 2027
                mqtt.event_hook = event
                mqtt._on_connect(client, None, {}, 0)
                self.assertTrue(mqtt.wait_stopped(3))
                self.assertEqual(client.subscriptions, [])
                self.assertEqual(client.sent, [])
                mqtt._on_connect_hook.assert_not_called()
                self.assert_no_network_owner(mqtt)
            finally:
                mqtt.stop()

    def test_paho_constructor_year_change_never_connects_or_starts_loop(self):
        for aba in (False, True):
            mqtt = RmMqttBackend(mock_output=False)
            clients = []
            def make(*a, **kw):
                value = LifecycleClient()
                clients.append(value)
                mqtt.set_rule_season(2027)
                if aba:
                    mqtt.set_rule_season(2026)
                return value
            with self.paho_factory(make):
                try:
                    mqtt.start()
                    self.assertTrue(mqtt.wait_stopped(3))
                    self.assertEqual(len(clients), 1)
                    self.assertEqual(clients[0].connections, [])
                    self.assertEqual(clients[0].loop_starts, 0)
                    self.assert_no_network_owner(mqtt)
                finally:
                    mqtt.stop()

    def test_actual_official_request_scenario_2027_does_not_acquire_mqtt(self):
        factory = Mock(side_effect=AssertionError("Paho acquisition forbidden"))
        # Full manager/lifecycle, but all device starters are inert and guarded.
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"POLAR_USER_DATA_ROOT": root}), \
                patch.object(BackendManager, "_build_commit", return_value="SEASON_TEST"), self.paho_factory(factory):
            state = RobotState()
            state.rules_season = 2027
            manager = BackendManager(state=state)
            with patch.object(manager.udp, "start"), patch.object(manager.serial, "start"), \
                    patch.object(manager.polar, "request_start"):
                try:
                    manager.request_scenario("OfficialEvent", start=True)
                    deadline = time.monotonic() + 3
                    while manager.lifecycle_pending and time.monotonic() < deadline:
                        manager.poll_lifecycle()
                        time.sleep(.001)
                    self.assertFalse(manager.lifecycle_pending)
                    self.assertEqual(manager.scenario_key, "OfficialEvent")
                    manager.mqtt.poll_connection()
                    factory.assert_not_called()
                    self.assert_no_network_owner(manager.mqtt)
                    self.assertFalse(manager.mqtt.stats()["rule_protocol_compatible"])
                finally:
                    manager.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
