"""Standalone external V2 Air acceptance: real offscreen dialogs and final guard.

Run separately with V2_SOURCE_ROOT set to the read-only source checkout when
this file lives in the candidate overlay. Never imports the window facade,
manager implementation, spin, native media, serial devices or network clients.
The exact manager publish/admission methods and affected narrow mixin methods are
AST-loaded; the entire tactical-map renderer is actually imported. This is
inert Qt/transport evidence, not hardware or native-rendering qualification.
"""
from __future__ import annotations

import ast
from dataclasses import fields, replace
import importlib
import importlib.abc
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

OVERLAY = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("V2_SOURCE_ROOT", str(OVERLAY))).resolve()
os.environ.update(QT_QPA_PLATFORM="offscreen", CI="true", POLAR_AUTOSTART="0",
                  POLAR_DISABLE_LOCAL_CAPTURE="1", POLAR_DISABLE_MEDIA_PRELOAD="1",
                  POLAR_FIRMWARE_READ_ONLY="1")
STORAGE = tempfile.TemporaryDirectory(prefix="v2-air-ui-inert-")
os.environ.update(POLAR_USER_DATA_ROOT=STORAGE.name, XDG_CACHE_HOME=STORAGE.name + "/cache",
                  XDG_CONFIG_HOME=STORAGE.name + "/config", XDG_DATA_HOME=STORAGE.name + "/data")
sys.dont_write_bytecode = True
GUARD_CALLS = []


def denied(*args, **kwargs):
    GUARD_CALLS.append((args, kwargs))
    raise AssertionError("network/process/device activity forbidden in V2 Air UI fixture")


for _method in ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg"):
    if hasattr(socket.socket, _method):
        setattr(socket.socket, _method, denied)
socket.create_connection = denied
subprocess.Popen = denied
os.system = denied
for _method in ("fork", "forkpty", "posix_spawn", "posix_spawnp"):
    if hasattr(os, _method):
        setattr(os, _method, denied)


def audit(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
        denied(event, args)
    if event == "open" and args and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        if path.startswith(("/dev/tty", "/dev/video", "/dev/hid", "/dev/input")):
            denied(event, args)


sys.addaudithook(audit)
FORBIDDEN = ("rm_client.ui.polar_app", "rm_client.backend.manager", "rm_client.control",
             "rm_client.spin", "rm_client.backend.spin", "serial", "paho", "cv2",
             "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.QtNetwork")


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in FORBIDDEN):
            raise AssertionError("forbidden implementation import: " + fullname)
        return None


sys.meta_path.insert(0, ImportGuard())
sys.path.insert(0, str(SOURCE))
import rm_client
rm_client.__path__[:] = [str(OVERLAY / "rm_client"), str(SOURCE / "rm_client")]
# Namespace shells prevent package __init__ from importing unrelated renderers
# or persistence. Both new source and fallback source remain explicit.
for _package in ("rm_client.ui", "rm_client.ui.polar", "rm_client.ui.polar.renderers",
                 "rm_client.backend", "rm_client.backend.referee", "rm_client.backend.referee.rm2026_v2"):
    _module = ModuleType(_package)
    _relative = Path(*_package.split("."))
    _module.__path__ = [str(OVERLAY / _relative), str(SOURCE / _relative)]
    _module.__package__ = _package
    sys.modules[_package] = _module
# Renderer annotations alone need these names. No model/device discovery or
# vision acquisition implementation is imported or exercised by this fixture.
for _package, _symbol in (("rm_client.model", "Module"), ("rm_client.vision", "VisionTarget")):
    _module = ModuleType(_package)
    setattr(_module, _symbol, type(_symbol, (), {}))
    sys.modules[_package] = _module

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QWidget
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.registry import get_profile
from rm_client.backend.referee.wire import encode_uint
from rm_client.backend.safety import ControlState, OfficialSafety
from rm_client.qualification_observations import QualificationEvidence, V2AirAttempt, v2_air_evidence, economy_evidence
from rm_client.referee_profiles import DEFAULT_PROFILE, V2_PROFILE
from rm_client.ui.polar.renderers import tactical_map as dialog

APP = QApplication.instance() or QApplication([])


def source_file(relative):
    candidate = OVERLAY / relative
    return candidate if candidate.is_file() else SOURCE / relative


def method_slice(relative, class_name, methods, *, extra=None):
    """Execute only selected actual function ASTs, never their enclosing facade."""
    tree = ast.parse(source_file(relative).read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    nodes = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    assert {node.name for node in nodes} == set(methods)
    ns = {"Any": object, "V2_PROFILE": V2_PROFILE, "time": dialog.time,
          "__package__": ".".join(Path(relative).parts[:-1])}
    if extra:
        ns.update(extra)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source_file(relative)), "exec"), ns)
    return {name: ns[name] for name in methods}


_MANAGER_METHODS = method_slice("rm_client/backend/manager.py", "BackendManager",
    {"_publish", "_v2_action_admission", "publish_air_support"})


class InertClient:
    def __init__(self):
        self.sent = []
        self.rc = 0
        self.at_publish = None

    def subscribe(self, topics):
        return 0, 77

    def publish(self, topic, payload, qos):
        self.sent.append((topic, bytes(payload), qos))
        if self.at_publish:
            self.at_publish()
        return SimpleNamespace(rc=self.rc)


class ManagerPort:
    _publish = _MANAGER_METHODS["_publish"]
    _v2_action_admission = _MANAGER_METHODS["_v2_action_admission"]
    publish_air_support = _MANAGER_METHODS["publish_air_support"]

    def __init__(self, mqtt, session):
        self.mqtt = mqtt
        self.referee = mqtt.referee
        self.qualification = SimpleNamespace(session=session)
        self.safety = mqtt.safety
        self.locks = []
        self.field_log = SimpleNamespace(emit=lambda *args, **kwargs: None)

    def lock_control(self, reason):
        self.locks.append(reason)
        self.safety.lock_control(reason)

    def begin_qualification(self, intents, ttl_s):
        return self.safety.begin_qualification(intents, ttl_s=ttl_s)


class Host(QWidget):
    open_event_command_menu = dialog.TacticalMapMixin.open_event_command_menu

    def __init__(self, mqtt):
        super().__init__()
        session = SimpleNamespace(session_id="session-1", operator="Named Operator", robot_id="6",
                                  referee_profile=V2_PROFILE, match_mode="RMUC7v7")
        self.backend = ManagerPort(mqtt, session)
        self.mqtt = mqtt
        self.registry = SimpleNamespace(get=lambda _name: None)
        self.scenario_manager = SimpleNamespace(current=SimpleNamespace(key="OfficialEvent"))
        self.match_mode_manager = SimpleNamespace(current=SimpleNamespace(key="RMUC7v7"))
        self.state = SimpleNamespace(referee_profile=V2_PROFILE, match_mode="RMUC7v7", robot_id=6, robot_profile="Aerial", current_round=1,
            current_stage="MATCH", air_support_active=False, air_support_free_time_sec=30,
            air_support_cost_coins=0, air_support_is_being_targeted=0, air_support_shooter_status=1)
        self.backend.state = self.state
        mqtt.bind_economy_context(self.state, self.backend.qualification)
        self.messages = []
        self._economy_qualification_token = None
        self._v2_air_qualification_attempt = None

    def toast(self, message):
        self.messages.append(str(message))


class V2AirDialogTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        patcher = patch("time.perf_counter", side_effect=lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dialog_texts = []

    def host(self, command=1, *, supervised=True, mock=False):
        safety = OfficialSafety("OfficialEvent")
        safety.configure(mock_writes=mock, allow_mqtt_publish=True, enforce_official_limits=True)
        mqtt = RmMqttBackend(client_id="6", mock_output=mock, safety=safety, referee_profile=V2_PROFILE)
        self.assertIs(mqtt.referee, get_profile(V2_PROFILE))
        mqtt.client = InertClient()
        mqtt._on_connect(mqtt.client, None, {}, 0)
        mqtt._on_subscribe(mqtt.client, None, 77, [0] * len(mqtt.referee.codec.DOWNLINK_MESSAGES))
        host = Host(mqtt)
        self.addCleanup(host.close)
        self.seed(host, command)
        if supervised:
            host._economy_qualification_token = safety.begin_qualification({"economy"}, now=100.0).value
        else:
            # This fixture tests the already-armed UI dispatch. It makes no
            # claim to normal V2 arming eligibility; parent owns that pending gate.
            safety.arm_match({"core_kmc", "economy"})
        return host

    def feed(self, host, topic, pairs):
        host.mqtt._on_message(host.mqtt.client, None, SimpleNamespace(topic=topic,
            payload=b"".join(encode_uint(number, value) for number, value in pairs)))

    def seed(self, host, command=1):
        for topic, pairs in (("GameStatus", [(1, 1)]),
            ("RobotStaticStatus", [(4, 6), (5, 91)]),
            ("GameStatus", [(5, 4), (6, 360)]),
            ("RobotStaticStatus", [(1, 1), (2, 0), (8, 3)]),
            ("AirSupportStatusSync", [(1, int(command == 0)), (2, 30), (3, 0), (4, 0),
                                      (5, 2 if command == 3 else 1)]),
            ("GlobalLogisticsStatus", [(1, 1000)])):
            self.feed(host, topic, pairs)
        host.state.air_support_active = command == 0
        host.state.air_support_shooter_status = 2 if command == 3 else 1

    def drive(self, host, steps):
        """Operate real modal Qt widgets; no monkeypatch of dialog functions."""
        remaining = list(steps)
        errors = []
        seen = set()
        seen_widgets = []  # Keep Qt wrappers alive; object IDs must not be reused between modals.
        timer = QTimer()
        timer.setInterval(5)

        def dispatch():
            widget = APP.activeModalWidget()
            if widget is None or id(widget) in seen:
                return
            seen.add(id(widget))
            seen_widgets.append(widget)
            try:
                if not remaining:
                    raise AssertionError("unexpected additional modal dialog")
                kind, value, change = remaining.pop(0)
                if change:
                    change()
                if kind == "choice":
                    self.assertIsInstance(widget, QInputDialog)
                    self.dialog_texts.append(widget.labelText())
                    if value is None:
                        widget.reject()
                    else:
                        widget.setTextValue(dialog._V2_AIR_CHOICES[value])
                        widget.accept()
                else:
                    self.assertIsInstance(widget, QMessageBox)
                    self.dialog_texts.append(widget.text())
                    widget.button(QMessageBox.StandardButton.Yes if value else QMessageBox.StandardButton.No).click()
            except BaseException as exc:
                errors.append(exc)
                widget.reject()

        timer.timeout.connect(dispatch)
        timer.start()
        watchdog = QTimer()
        watchdog.setSingleShot(True)

        def timeout():
            errors.append(AssertionError("offscreen modal fixture timed out"))
            widget = APP.activeModalWidget()
            if widget is not None:
                widget.reject()

        watchdog.timeout.connect(timeout)
        watchdog.start(3000)
        try:
            host.open_event_command_menu()
        finally:
            timer.stop()
            watchdog.stop()
        if errors:
            raise errors[0]
        self.assertFalse(remaining, "not all expected real dialogs opened")

    def confirm(self, host, command=1, change=None, second=None):
        steps = [("choice", command, None), ("confirm", True, change)]
        if second is not None:
            steps.append(("confirm", True, second))
        self.drive(host, steps)

    def evidence(self, host, **overrides):
        session = host.backend.qualification.session
        args = dict(attempt=host._v2_air_qualification_attempt, snapshot=host.mqtt.v2_wire_snapshot(),
            owners=(host.backend, host.mqtt, host.backend.referee, host.mqtt.referee, host.mqtt.client, session),
            session_id=getattr(session, "session_id", ""), operator=getattr(session, "operator", ""),
            session_profile=getattr(session, "referee_profile", ""), session_robot_id=getattr(session, "robot_id", ""),
            profile_id=host.backend.referee.profile_id, receive_generation=host.mqtt.receive_generation,
            client_id=str(host.mqtt.client_id), connected=host.mqtt.connected,
            transport_is_mock=host.mqtt.mock_output, now=self.clock[0])
        return v2_air_evidence(**(args | overrides))

    def test_all_four_real_dialog_choices_one_token_one_enqueue_later_status(self):
        for command in range(4):
            with self.subTest(command=command):
                self.clock[0] = 100.0
                host = self.host(command)
                self.confirm(host, command)
                self.assertEqual(host.mqtt.client.sent, [("AirSupportCommand", encode_uint(1, command), 1)])
                self.assertIsNone(host._economy_qualification_token)
                self.assertEqual(len(host.backend.locks), 1)
                self.assertIs(host.backend.safety.control_state, ControlState.LOCKED)
                attempt = host._v2_air_qualification_attempt
                self.assertIsInstance(attempt, V2AirAttempt)
                self.assertFalse(any("token" in field.name for field in fields(attempt)))
                self.assertFalse(self.evidence(host).passed)
                self.clock[0] = 100.1
                self.feed(host, "AirSupportStatusSync", [(5 if command == 3 else 1, 0 if command == 0 else 1)])
                evidence = self.evidence(host)
                self.assertTrue(evidence.passed, evidence.measured)
                self.assertFalse(evidence.measured["unique_request_ack"])
                self.assertEqual(evidence.measured["command_id"], command)
                self.assertIn("未取得逐请求确认", host.messages[-1])
        self.assertTrue(any("1 coin/second" in text and "no fixed total" in text for text in self.dialog_texts))
        self.assertTrue(any("Estimated release fee only" in text and "total are unconfirmed" in text for text in self.dialog_texts))

    def test_air3_already_active_can_observe_shooter_transition(self):
        host = self.host(3)
        self.feed(host, "AirSupportStatusSync", [(1, 1)])
        self.confirm(host, 3)
        self.clock[0] += .1
        self.feed(host, "AirSupportStatusSync", [(5, 1)])
        self.assertTrue(self.evidence(host).passed)

    def test_cancel_selection_and_confirmation_preserve_token_without_lock(self):
        for steps in ([('choice', None, None)], [('choice', 1, None), ('confirm', False, None)]):
            host = self.host()
            token = host._economy_qualification_token
            self.drive(host, steps)
            self.assertEqual(host._economy_qualification_token, token)
            self.assertEqual(host.mqtt.client.sent, [])
            self.assertEqual(host.backend.locks, [])

    def test_ordinary_armed_path_calls_actual_manager_methods(self):
        host = self.host(supervised=False)
        snapshot = host.mqtt.v2_wire_snapshot()
        with patch.object(host.backend, "publish_air_support", wraps=host.backend.publish_air_support) as publish:
            self.confirm(host)
        publish.assert_called_once_with(1, expected_economy_snapshot=snapshot)
        self.assertEqual(len(host.mqtt.client.sent), 1)
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertEqual(host.backend.locks, [])

    def test_final_guard_rejection_and_exception_consume_token_and_lock_once(self):
        for raises in (False, True):
            host = self.host()
            original = host.mqtt._publish_current

            def rejected(*args, **kwargs):
                if raises:
                    raise RuntimeError("inert enqueue failure")
                host.mqtt.safety.lock_control("changed after UI confirmation")
                return original(*args, **kwargs)

            with patch.object(host.mqtt, "_publish_current", side_effect=rejected):
                self.confirm(host)
            self.assertIsNone(host._economy_qualification_token)
            self.assertIsNone(host._v2_air_qualification_attempt)
            self.assertEqual(host.mqtt.client.sent, [])
            self.assertEqual(len(host.backend.locks), 1)
            self.assertNotIn("请求已提交", host.messages[-1])

    def test_mock_and_rejected_enqueue_never_create_observation_record(self):
        host = self.host(mock=True)
        self.confirm(host)
        self.assertEqual(host.mqtt.client.sent, [])
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertIn("MOCK", host.messages[-1])
        host = self.host()
        host.mqtt.client.rc = 4
        self.confirm(host)
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertEqual(len(host.backend.locks), 1)

    def test_replacement_profile_session_client_generation_rejects_held_dialog(self):
        changes = (
            lambda h: setattr(h.backend, "referee", get_profile(DEFAULT_PROFILE)),
            lambda h: setattr(h.backend, "referee", replace(h.backend.referee)),
            lambda h: setattr(h.backend.qualification, "session", SimpleNamespace(**vars(h.backend.qualification.session))),
            lambda h: setattr(h.mqtt, "client", InertClient()),
            lambda h: setattr(h.mqtt, "receive_generation", h.mqtt.receive_generation + 1),
        )
        for change in changes:
            host = self.host()
            client = host.mqtt.client
            token = host._economy_qualification_token
            self.confirm(host, change=lambda: change(host))
            self.assertEqual(client.sent, [])
            self.assertEqual(host._economy_qualification_token, token)
            self.assertIsNone(host._v2_air_qualification_attempt)

    def test_scope_round_identity_aba_rejects_held_dialog_and_pending_attempt(self):
        for topic, pairs in (("GameStatus", [(1, 2)]),
                             ("RobotStaticStatus", [(4, 106)]),
                             ("RobotStaticStatus", [(5, 92)])):
            def change(host):
                self.feed(host, topic, pairs)
                self.seed(host)
            host = self.host()
            old_scope = host.mqtt.v2_wire_snapshot().scope_revision
            self.confirm(host, change=lambda: change(host))
            self.assertGreater(host.mqtt.v2_wire_snapshot().scope_revision, old_scope)
            self.assertEqual(host.mqtt.client.sent, [])
            host = self.host()
            self.confirm(host)
            change(host)
            self.clock[0] += .1
            self.feed(host, "AirSupportStatusSync", [(1, 1)])
            evidence = self.evidence(host)
            self.assertFalse(evidence.passed)
            self.assertTrue(evidence.measured["retire_attempt"])
            self.clock[0] = 100.

    def test_same_value_scope_refresh_does_not_retire_dialog_or_attempt(self):
        host = self.host()
        old_scope = host.mqtt.v2_wire_snapshot().scope_revision
        self.confirm(host, change=lambda: self.seed(host))
        self.assertEqual(host.mqtt.v2_wire_snapshot().scope_revision, old_scope)
        self.assertEqual(len(host.mqtt.client.sent), 1)
        self.clock[0] += .1
        self.seed(host)
        self.feed(host, "AirSupportStatusSync", [(1, 1)])
        self.assertTrue(self.evidence(host).passed)

    def test_release_estimate_refresh_requires_new_confirmation_bounded(self):
        host = self.host(3)
        self.confirm(host, 3, change=lambda: self.feed(host, "GameStatus", [(6, 300)]), second=lambda: None)
        confirmations = [text for text in self.dialog_texts if "Estimated release fee only" in text]
        self.assertEqual(len(confirmations), 2)
        self.assertIn("280 coins", confirmations[0])
        self.assertIn("440 coins", confirmations[1])
        self.assertEqual(len(host.mqtt.client.sent), 1)
        host = self.host(3)
        self.confirm(host, 3, change=lambda: self.feed(host, "GameStatus", [(6, 300)]),
                     second=lambda: self.feed(host, "GameStatus", [(6, 240)]))
        self.assertEqual(host.mqtt.client.sent, [])
        self.assertIsNotNone(host._economy_qualification_token)

    def test_stale_or_unavailable_prerequisites_do_not_consume_token(self):
        host = self.host()
        self.confirm(host, change=lambda: self.clock.__setitem__(0, 102.001))
        self.assertEqual(host.mqtt.client.sent, [])
        self.assertIsNotNone(host._economy_qualification_token)
        self.clock[0] = 100.
        host = self.host()
        self.feed(host, "AirSupportStatusSync", [(5, 0)])
        self.drive(host, [("choice", 1, None)])
        self.assertEqual(host.mqtt.client.sent, [])
        self.assertIsNotNone(host._economy_qualification_token)

    def test_pre_return_response_unrelated_status_and_invalid_evidence_fail(self):
        host = self.host()
        host.mqtt.event_hook = lambda event, **payload: (
            self.feed(host, "AirSupportStatusSync", [(1, 1)]) if event == "publish_result" else None)
        self.confirm(host)
        self.assertFalse(self.evidence(host).passed)
        self.clock[0] += .1
        self.feed(host, "AirSupportStatusSync", [(3, 5)])
        self.assertFalse(self.evidence(host).passed)
        self.feed(host, "AirSupportStatusSync", [(1, 1)])
        good = self.evidence(host)
        self.assertTrue(good.passed)
        for override in ({"connected": False}, {"transport_is_mock": True}, {"operator": ""},
                         {"session_id": "other"}, {"session_robot_id": "106"},
                         {"session_profile": DEFAULT_PROFILE}, {"now": 102.101}, {"now": 99.},
                         {"attempt": replace(host._v2_air_qualification_attempt, old_status=1)}):
            self.assertFalse(self.evidence(host, **override).passed, override)
        self.clock[0] = 102.0
        self.assertTrue(self.evidence(host).passed)  # original scope exactly 2 seconds

    def test_legacy_workspace_and_forged_mock_offer_are_directly_rejected(self):
        methods = method_slice("rm_client/ui/polar/mixins/economy_mixin.py", "EconomyMixin",
                               {"open_economy_workspace", "submit_economy_offer", "send_economy_request",
                                "start_economy_qualification_test"})
        host = self.host()
        with patch("rm_client.ui.polar.renderers.v2_economy_dialog._open_v2_economy_dialog") as common:
            methods["open_economy_workspace"](host)
        common.assert_called_once_with(host, "CommonCommand")
        methods["submit_economy_offer"](host, object())
        self.assertFalse(methods["send_economy_request"](host, SimpleNamespace(mock=True)))
        self.assertEqual(host.mqtt.client.sent, [])
        host._v2_air_qualification_attempt = object()
        methods["start_economy_qualification_test"](host)
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertIn("during MATCH", host.messages[-1])
        self.assertIn("not a unique request/payment ACK", host.messages[-1])

    def test_actual_observer_consumes_one_pass_and_retires_mismatched_attempt(self):
        relative = "rm_client/ui/polar/mixins/config_actions_mixin.py"
        tree = ast.parse(source_file(relative).read_text())
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_observe_v2_air_evidence")
        namespace = {"Any": object, "QualificationEvidence": QualificationEvidence, "v2_air_evidence": v2_air_evidence, "time": dialog.time}
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), helper], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source_file(relative)), "exec"), namespace)
        methods = method_slice(relative, "ConfigActionsMixin", {"_observe_economy_evidence"}, extra={
            "_observe_v2_air_evidence": namespace["_observe_v2_air_evidence"], "economy_evidence": economy_evidence})
        observe = methods["_observe_economy_evidence"]
        host = self.host()
        self.confirm(host)
        # Unchanged observations do not consume the pending attempt.
        self.assertFalse(observe(host, {}).passed)
        self.assertIsNotNone(host._v2_air_qualification_attempt)
        self.clock[0] += .1
        self.feed(host, "AirSupportStatusSync", [(1, 1)])
        self.assertTrue(observe(host, {}).passed)
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertFalse(observe(host, {}).passed)
        self.clock[0] = 100.
        for mutate in (
            lambda h: setattr(h.backend.qualification, "session", SimpleNamespace(**vars(h.backend.qualification.session))),
            lambda h: setattr(h.backend, "referee", replace(h.backend.referee)),
            lambda h: setattr(h.mqtt, "receive_generation", h.mqtt.receive_generation + 1),
            lambda h: setattr(h.mqtt, "mock_output", True),
        ):
            host = self.host()
            self.confirm(host)
            mutate(host)
            self.assertFalse(observe(host, {}).passed)
            self.assertIsNone(host._v2_air_qualification_attempt)
        # Original V1 succeeded/revision criterion is untouched.
        host.backend.referee = get_profile(DEFAULT_PROFILE)
        host.economy_bridge = SimpleNamespace(latest=SimpleNamespace(status="succeeded",
            request=SimpleNamespace(mock=False, timestamp=100.)))
        host.state.economy_status_revision = 2
        host.economy_uses_mock_transport = lambda: False
        self.assertTrue(observe(host, {"captured_at_wall": 100., "economy_revision": 1}).passed)

    def test_observer_rechecks_current_snapshot_and_preserves_replacement_attempt(self):
        relative = "rm_client/ui/polar/mixins/config_actions_mixin.py"
        tree = ast.parse(source_file(relative).read_text())
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_observe_v2_air_evidence")
        namespace = {"Any": object, "QualificationEvidence": QualificationEvidence,
                     "v2_air_evidence": v2_air_evidence, "time": dialog.time}
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), helper], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source_file(relative)), "exec"), namespace)
        observe = namespace[helper.name]
        for mutation in ("stage_exit", "scope_aba", "session", "replacement_attempt", "aged_during_second_read", "same_scope_refresh"):
            self.clock[0] = 100.
            host = self.host()
            self.confirm(host)
            self.clock[0] += .1
            self.feed(host, "AirSupportStatusSync", [(1, 1)])
            original = host.mqtt.v2_wire_snapshot
            reads = [0]
            replacement_attempt = object()

            def held():
                old = original()
                reads[0] += 1
                if reads[0] == 1 and mutation != "aged_during_second_read":
                    if mutation == "stage_exit":
                        self.feed(host, "GameStatus", [(5, 5)])
                    elif mutation == "scope_aba":
                        self.feed(host, "GameStatus", [(1, 2)])
                        self.seed(host)
                        self.feed(host, "AirSupportStatusSync", [(1, 1)])
                    elif mutation == "same_scope_refresh":
                        self.feed(host, "AirSupportStatusSync", [(1, 1)])
                    elif mutation == "session":
                        host.backend.qualification.session = SimpleNamespace(**vars(host.backend.qualification.session))
                    else:
                        host._v2_air_qualification_attempt = replacement_attempt
                elif reads[0] == 2 and mutation == "aged_during_second_read":
                    self.clock[0] = 102.001
                return old

            with patch.object(host.mqtt, "v2_wire_snapshot", side_effect=held):
                result = observe(host)
            self.assertFalse(result.passed, mutation)
            if mutation == "replacement_attempt":
                self.assertIs(host._v2_air_qualification_attempt, replacement_attempt)
            elif mutation == "same_scope_refresh":
                self.assertIsNotNone(host._v2_air_qualification_attempt)
                self.assertTrue(observe(host).passed)
                self.assertIsNone(host._v2_air_qualification_attempt)
            else:
                self.assertIsNone(host._v2_air_qualification_attempt)

    def test_reset_clears_attempt_without_new_qualification_policy(self):
        marker = object()
        host = self.host()
        host._v2_air_qualification_attempt = marker
        host.backend.qualification.reset = lambda: setattr(host.backend.qualification, "session", None)
        host._capture_qualification_runtime_baseline = lambda: {"captured_at_perf": self.clock[0]}
        reset = method_slice("rm_client/ui/polar/mixins/config_actions_mixin.py", "ConfigActionsMixin",
            {"_reset_qualification_session"}, extra={"QualificationRefresh": SimpleNamespace(REQUIRED="required")})
        self.assertEqual(reset["_reset_qualification_session"](host), "required")
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertIsNone(host.backend.qualification.session)

    def test_observer_failure_after_enqueue_never_reports_request_as_unsent(self):
        host = self.host()
        submitted = [False]
        host.mqtt.event_hook = lambda event, **payload: submitted.__setitem__(0, True) if event == "publish_result" else None
        original = dialog._v2_air_context

        def context(window):
            if submitted[0]:
                raise RuntimeError("inert observation failure")
            return original(window)

        with patch.object(dialog, "_v2_air_context", side_effect=context):
            self.confirm(host)
        self.assertEqual(len(host.mqtt.client.sent), 1)
        self.assertIsNone(host._v2_air_qualification_attempt)
        self.assertIn("请求已提交", host.messages[-1])
        self.assertIn("observation unavailable", host.messages[-1])
        self.assertEqual(len(host.backend.locks), 1)

    def test_api_members_unchanged_and_no_new_ui_publish_or_policy_owner(self):
        for relative, class_name in (("rm_client/ui/polar/renderers/tactical_map.py", "TacticalMapMixin"),
            ("rm_client/ui/polar/mixins/economy_mixin.py", "EconomyMixin"),
            ("rm_client/ui/polar/mixins/config_actions_mixin.py", "ConfigActionsMixin")):
            def members(path):
                tree = ast.parse(path.read_text())
                cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
                return {n.name: ast.dump(n.args) for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            self.assertEqual(members(SOURCE / relative), members(OVERLAY / relative))
        tree = ast.parse(source_file("rm_client/ui/polar/renderers/tactical_map.py").read_text())
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_open_v2_air_dialog")
        calls = [n.func.attr for n in ast.walk(helper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertNotIn("publish", calls)
        self.assertNotIn("arm_match", calls)
        self.assertNotIn("record_automatic", calls)
        self.assertNotIn("getInt", calls)
        self.assertEqual(calls.count("publish_air_support_command"), 1)
        self.assertEqual(calls.count("publish_air_support"), 1)
        self.assertEqual(GUARD_CALLS, [])
        self.assertFalse(any(any(name == p or name.startswith(p + ".") for p in FORBIDDEN) for name in sys.modules))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        print("IMPORT_LEDGER", "\n".join(sorted(name for name in sys.modules if name.startswith("rm_client"))))
        print("GUARD_CALL_COUNT", len(GUARD_CALLS))
        STORAGE.cleanup()
