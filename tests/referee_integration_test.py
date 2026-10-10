"""Version/schema isolation and a real paho MQTT loopback, never hardware.

No field evidence is produced. The broker binds ONLY an ephemeral localhost
port; the production defaults and operator configuration are not touched.
"""
from __future__ import annotations

from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.backend.manager import BackendManager
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.qualification import QualificationEvidenceStore, QualificationManager
from rm_client.backend.referee.registry import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, get_profile
from rm_client.backend.referee.rm2026.contract import ALIASES, FIELDS
from rm_client.backend.safety import OfficialSafety
from rm_client.model import RobotState, build_default_registry
from rm_client.config_store import apply_registry_config

CHECKS = 0


def check(value: bool, label: str) -> None:
    global CHECKS
    if not value:
        raise AssertionError(label)
    CHECKS += 1


def varint(value: int) -> bytes:
    value &= (1 << 64) - 1
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out + bytes([value]))


def field(number: int, kind: str, value) -> bytes:
    # Independent reference encoder; never call the application's encoder.
    if kind in {"uint32", "uint64", "int32", "bool"}:
        return varint(number << 3) + varint(int(value))
    if kind == "float":
        return varint((number << 3) | 5) + struct.pack("<f", value)
    value = value.encode() if kind == "string" else bytes(value)
    return varint((number << 3) | 2) + varint(len(value)) + value


def test_official_field_contract() -> None:
    codec = get_profile().codec
    check(len(codec.DOWNLINK_MESSAGES) == 25 and len(codec.UPLINK_MESSAGES) == 11, "correct protocol direction/count")
    for name in sorted(codec.DOWNLINK_MESSAGES):
        payload = b""
        expected = {}
        for number, (key, kind, repeated) in FIELDS[name].items():
            if kind in FIELDS:
                value = {"target_pos_x": 17, "target_pos_y": 18, "is_high_light": 1}
                sub = field(1, "uint32", 17) + field(2, "uint32", 18) + field(3, "uint32", 1)
                payload += field(number, "bytes", sub)
                expected[key] = [value]
                continue
            value = (number + .25) if kind == "float" else "1,101" if kind == "string" else b"abc" if kind == "bytes" else True if kind == "bool" else -number if kind == "int32" else (1 << 40) if kind == "uint64" else number + 100
            if (name, key) == ("GameStatus", "current_stage"):
                value = 4
            if name == "DeployModeStatusSync":
                value = 1
            if repeated:
                values = [value, value + 1]
                payload += field(number, "bytes", b"".join(varint(v) for v in values))
                expected[key] = values
            else:
                payload += field(number, kind, value)
                expected[ALIASES.get((name, key), key)] = value
        decoded = codec.decode_message(name, payload)
        check(bool(decoded), f"{name}: independent packet decoded")
        for key, value in expected.items():
            check(decoded[key] == value, f"{name}.{key}: field number/type")
    for tail in (b"\x80", b"\0", b"\x12\xff", b"\x09\x01", b"\x08" + b"\x80" * 10):
        check(codec.decode_message("GameStatus", field(5, "uint32", 4) + tail) == {}, "malformed suffix cannot grant match authority")
    check(codec.decode_message("GameStatus", field(5, "float", 4.)) == {}, "wrong stage wire type rejected")
    check(codec.decode_message("GameStatus", field(5, "uint32", 99)) == {}, "unknown stage rejected")
    check(codec.decode_message("DeployModeStatusSync", field(1, "uint32", 2)) == {}, "unknown deploy mode rejected")
    check(codec.decode_message("RobotDynamicStatus", field(2, "float", float("nan"))) == {}, "NaN telemetry rejected")
    check(codec.decode_message("Event", field(2, "bytes", b"\xff")) == {}, "bad UTF-8 rejected")
    check(codec.decode_message("GlobalUnitStatus", field(11, "bytes", b"\x80")) == {}, "truncated packed list rejected")
    check(codec.decode_message("GameStatus", field(999, "uint32", 4)) == {}, "unknown-only fields are not authority")


def deliver(manager: BackendManager, topic: str, payload: bytes, client=None) -> None:
    manager.mqtt._on_message(client, None, SimpleNamespace(topic=topic, payload=payload))
    manager.apply_updates(manager.state)


def test_partial_state_and_epochs() -> None:
    state = RobotState()
    manager = BackendManager(state=state, scenario_key="OfficialEvent")
    try:
        deliver(manager, "GameStatus", field(5, "uint32", 4))
        deliver(manager, "GameStatus", field(6, "int32", 200))
        check(state.current_stage == "MATCH" and manager.safety.is_fighting(), "partial countdown preserves phase")
        state.current_heat = 123.
        state.remaining_ammo = 88
        state.can_remote_ammo = True
        state.can_remote_heal = True
        state.current_health = 456
        deliver(manager, "RobotDynamicStatus", field(9, "uint32", 12))
        check((state.current_health, state.current_heat, state.remaining_ammo) == (456, 123., 12), "missing optional telemetry preserves prior values")
        check(state.can_remote_ammo and state.can_remote_heal, "missing permission flags do not fabricate zero")
        deliver(manager, "RobotModuleStatus", field(1, "uint32", 1))
        deliver(manager, "RobotModuleStatus", field(7, "uint32", 2))
        check(state.robot_module_status == {"power_manager": 1, "armor": 2}, "partial module status merged without metadata casting")
        deliver(manager, "RobotPosition", field(1, "float", 3.) + field(2, "float", 4.))
        deliver(manager, "RobotPosition", field(4, "float", 15.))
        check(state.robot_positions[-1] == {"robot_id": 3, "x": 3., "y": 4., "yaw": 15.}, "local position without optional ID; partial coordinates retained")
        deliver(manager, "GlobalUnitStatus", field(11, "bytes", b"".join(varint(600) for _ in range(10))))
        deliver(manager, "RobotDynamicStatus", field(1, "uint32", 0))
        own = next(row for row in state.robot_rows if row["id"] == 3)
        check(own["hp"] == 0 and own["state"] == "DEAD", "valid local death cannot be resurrected by old team HP")
        bad_before = manager.mqtt.invalid_messages
        deliver(manager, "GameStatus", field(5, "uint32", 4) + b"\x80")
        deliver(manager, "RobotDynamicStatus", field(1, "uint32", 500))
        check(state.current_health == 500 and manager.mqtt.invalid_messages == bad_before + 1, "one bad packet does not kill later messages")
        deliver(manager, "wrong/GameStatus", field(5, "uint32", 4))
        deliver(manager, "KeyboardMouseControl", b"\x08\0")
        check(manager.mqtt.ignored_topics == 2, "exact topics only; uplink echoes excluded")
        old = object()
        manager.mqtt.client = old
        manager.mqtt._on_message(old, None, SimpleNamespace(topic="GameStatus", payload=field(5, "uint32", 4)))
        check(bool(manager.mqtt._decoded), "queued old endpoint data")
        generation = manager.mqtt.receive_generation
        manager.mqtt.set_address("localhost", 3333)
        check(manager.mqtt.receive_generation > generation and not manager.mqtt.drain_decoded() and not manager.mqtt.drain_received_messages(), "endpoint change discards decoded and raw queues")
        check(not manager.safety.is_fighting() and manager.safety.control_state.value == "LOCKED", "endpoint switch revokes stage and authorization")
        manager.mqtt.client = None
        deliver(manager, "GameStatus", field(5, "uint32", 4), client=old)
        check(not manager.safety.is_fighting(), "late callback from old client cannot grant authority")
        try:
            manager.set_referee_profile("rm2027-unreviewed")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown profile accepted")
        check(manager.safety.control_state.value == "LOCKED" and not manager.mqtt._started, "unsupported year fails closed")
        registry = build_default_registry()
        apply_registry_config(registry, {"modules": {"MQTTLink": {"settings": {"Referee Profile": "bad-version"}}}})
        check(registry.get("MQTTLink").get_setting("Referee Profile").value == "bad-version", "unknown persisted year never silently becomes default")
        check("Unsupported" in manager.sync_mqtt_link(registry), "invalid persisted profile is not silently normalized")
    finally:
        manager.mqtt.client = None
        manager.shutdown()


def test_student_preview() -> None:
    state = RobotState()
    manager = BackendManager(state=state, scenario_key="OfficialEvent")
    try:
        manager.mqtt._decoded.append(("GameStatus", "GameStatus", {"current_stage": 4}, time.perf_counter()))
        manager.set_referee_profile(STUDENT_PREVIEW_PROFILE)
        check(state.referee_profile == STUDENT_PREVIEW_PROFILE and not manager.mqtt.drain_decoded(), "profile switch resets state/queue epoch")
        deliver(manager, "GameStatus", field(5, "uint32", 4))
        deliver(manager, "RobotDynamicStatus", field(1, "uint32", 432) + field(2, "float", 12.5))
        check(state.current_stage == "MATCH" and state.current_health == 432 and state.current_heat == 12.5, "old Student stable scalar preview")
        deliver(manager, "GlobalUnitStatus", field(1, "uint32", 4500) + field(6, "bytes", b"".join(varint(111 + i) for i in range(14))))
        check(state.base_health == 4500 and not state.official_robot_health, "legacy arrays cannot poison current 5+5 roster")
        check(len(state.backend_stats["student_legacy_roster"]["robot_health"]) == 14, "unverified legacy roster retained only as raw diagnostic")
        check(manager.referee.available_actions(state) == [], "no economy offer on preview profile")
        for mock in (True, False):
            manager.mqtt.mock_output = mock
            for topic in ("RemoteControl", "KeyboardMouseControl", "CustomControl", "CommonCommand"):
                check(not manager.mqtt.publish_named(topic, b"")[0], "all old preview uplink paths forbidden")
            check(not manager.mqtt.publish_estop_zero()[0], "preview cannot synthesize wrong-year emergency KMC")
        manager.set_referee_profile(DEFAULT_PROFILE)
        check(state.referee_profile == DEFAULT_PROFILE and manager.safety.control_state.value == "LOCKED", "switch back does not auto-arm")
        with tempfile.TemporaryDirectory() as tmp:
            store = QualificationEvidenceStore(Path(tmp), build_commit="test", referee_profile=STUDENT_PREVIEW_PROFILE, protocol_version="1.1.0")
            qual = QualificationManager(store)
            session = qual.new_session(robot_id="3", firmware_hash="a" * 64, match_mode="RMUC7v7", video_source="udp", operator="test")
            check(session.referee_profile == STUDENT_PREVIEW_PROFILE and "read-only" in qual.core_ready()[1], "old preview evidence can never become match-qualified")
            store.referee_profile = DEFAULT_PROFILE
            store.protocol_version = "1.3.1"
            check("protocol mismatch" == qual.core_ready()[1], "evidence cannot cross a protocol profile")
    finally:
        manager.shutdown()


class LoopbackBroker:
    """Minimal MQTT 3.1.1 test peer; not shipped as a production broker."""
    def __init__(self, *, ack_publications: bool = True) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(3.)
        self.port = self.listener.getsockname()[1]
        self.peer = None
        self.client_id = ""
        self.connect_flags = 0
        self.subscriptions = set()
        self.publications = []
        self.ack_publications = ack_publications
        self.error = ""
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def exact(self, length: int) -> bytes:
        result = b""
        while len(result) < length:
            chunk = self.peer.recv(length - len(result))
            if not chunk:
                raise EOFError
            result += chunk
        return result

    def packet(self) -> tuple[int, bytes]:
        header = self.exact(1)[0]
        size, multiplier = 0, 1
        for _ in range(4):
            byte = self.exact(1)[0]
            size += (byte & 127) * multiplier
            if byte < 128:
                return header, self.exact(size)
            multiplier *= 128
        raise AssertionError("bad MQTT size")

    def send(self, header: int, payload: bytes) -> None:
        self.peer.sendall(bytes([header]) + varint(len(payload)) + payload)

    def run(self) -> None:
        try:
            self.peer, _ = self.listener.accept()
            self.peer.settimeout(5.)
            while True:
                header, payload = self.packet()
                kind = header >> 4
                if kind == 1:
                    check(payload[:7] == b"\0\x04MQTT\x04", "real MQTT 3.1.1 connect")
                    self.connect_flags = payload[7]
                    length = int.from_bytes(payload[10:12], "big")
                    self.client_id = payload[12:12 + length].decode()
                    self.send(0x20, b"\0\0")
                elif kind == 8:
                    index, granted = 2, []
                    while index < len(payload):
                        length = int.from_bytes(payload[index:index + 2], "big")
                        index += 2
                        topic = payload[index:index + length].decode()
                        index += length
                        qos = payload[index]
                        index += 1
                        self.subscriptions.add(topic)
                        granted.append(qos)
                    self.send(0x90, payload[:2] + bytes(granted))
                    for ident, topic, data in (
                        (1, "GameStatus", field(5, "uint32", 4)),
                        (2, "RobotDynamicStatus", field(1, "uint32", 478)),
                    ):
                        self.send(0x32, len(topic).to_bytes(2, "big") + topic.encode() + ident.to_bytes(2, "big") + data)
                    self.ready.set()
                elif kind == 3:
                    length = int.from_bytes(payload[:2], "big")
                    topic = payload[2:2 + length].decode()
                    index = 2 + length
                    qos = (header >> 1) & 3
                    if qos:
                        if self.ack_publications:
                            self.send(0x40, payload[index:index + 2])
                        index += 2
                    self.publications.append((topic, payload[index:], qos, bool(header & 1)))
                elif kind == 12:
                    self.send(0xd0, b"")
                elif kind == 14:
                    return
        except (EOFError, OSError):
            return
        except Exception as exc:
            self.error = repr(exc)

    def close(self) -> None:
        if self.peer is not None:
            self.peer.close()
        self.listener.close()
        self.thread.join(6.)


def wait_until(predicate, label: str) -> None:
    deadline = time.perf_counter() + 3.
    while not predicate() and time.perf_counter() < deadline:
        time.sleep(.01)
    check(bool(predicate()), label)


def test_real_mqtt_loopback() -> None:
    broker = LoopbackBroker()
    manager = BackendManager(state=RobotState(), scenario_key="OfficialEvent")
    try:
        manager.mqtt.set_address("127.0.0.1", broker.port)
        manager.mqtt.start()
        wait_until(lambda: broker.ready.is_set(), "real paho subscribe completed")
        wait_until(lambda: manager.mqtt.messages_received >= 2, "real binary downlink received")
        manager.apply_updates(manager.state)
        check(not broker.error, "broker test peer healthy")
        check(broker.client_id == "3" and not broker.connect_flags & 4, "robot ClientId; no undocumented Last Will")
        check(broker.subscriptions == get_profile().codec.DOWNLINK_MESSAGES, "exact downlink topic subscription; no wildcard")
        check(manager.state.current_health == 478 and manager.state.current_stage == "MATCH", "MQTT bytes -> stable RobotState")
        check(manager.safety.control_state.value == "LOCKED", "receiving match phase does not arm control")
        check(not manager.publish_keyboard_mouse(keyboard_value=1)[0], "locked motion cannot reach loopback")
        token = manager.safety.begin_qualification({"core_kmc"})
        check(manager.publish_keyboard_mouse(keyboard_value=0x1000, qualification_token=token.value)[0], "scoped KMC intent reaches isolated test broker")
        wait_until(lambda: bool(broker.publications), "QoS1 uplink on wire")
        topic, payload, qos, retained = broker.publications[0]
        check(topic == "KeyboardMouseControl" and qos == 1 and not retained, "official binary topic/QoS/non-retained format")
        check(get_profile().codec._u(get_profile().codec.decode_fields(payload), 6) == 0x1000, "official key mask preserved")
        for topic in ("ClientStatus", "MapClickInfo", "MapClickInfoNotify", "unknown"):
            check(not manager.mqtt.publish_named(topic, b"")[0], "no undocumented/downlink uplink bypass")
        check(not manager.mqtt.publish_named("DartCommand", b"\x80")[0], "malformed uplink refused before socket")
        check(not manager.mqtt.publish_named("DartCommand", b"", qos=2)[0], "QoS2 exceeds official ceiling")
        check(not manager.mqtt.publish_named("CustomControl", field(1, "bytes", bytes(31)))[0], "oversized custom control blocked")
        manager.trigger_estop()
        wait_until(lambda: len(broker.publications) >= 2, "dedicated emergency zero on wire")
        last = broker.publications[-1]
        check(last[0] == "KeyboardMouseControl" and last[1] == get_profile().codec.encode_keyboard_mouse_control(), "fixed zero bypass; no arbitrary estop payload")
    finally:
        manager.shutdown()
        broker.close()


def test_schema_import_is_lightweight() -> None:
    script = "import sys; from rm_client.backend.referee.registry import get_profile; assert 'PySide6' not in sys.modules; assert 'cv2' not in sys.modules; assert 'rm_client.backend.manager' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True)
    check(result.returncode == 0, "pure schema import never creates hardware/GUI dependencies")
    for value in ("0", "259", "0x0103", "uuid", "３"):
        try:
            get_profile().validate_client_id(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad ClientId accepted: {value}")
        check(True, "player-end/non-robot ClientId refused")


def test_fresh_client_reconnect() -> None:
    broker = LoopbackBroker(ack_publications=False)
    manager = BackendManager(state=RobotState(), scenario_key="OfficialEvent")
    try:
        manager.mqtt.set_address("127.0.0.1", broker.port)
        manager.mqtt.start()
        wait_until(lambda: broker.ready.is_set(), "reconnect fixture connected")
        token = manager.safety.begin_qualification({"core_kmc"})
        check(manager.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0], "unacknowledged motion queued on old client")
        wait_until(lambda: len(broker.publications) == 1, "old unacknowledged motion reached peer")
        old_client = manager.mqtt.client
        check(bool(old_client._out_messages), "QoS1 command really remains unacknowledged")
        broker.peer.shutdown(socket.SHUT_RDWR)
        broker.peer.close()
        broker.thread.join(3.)
        wait_until(lambda: manager.mqtt._reconnect_required, "disconnect schedules fresh client")
        check(manager.safety.control_state.value == "LOCKED" and not manager.safety._stage_seen, "disconnect revokes token and authoritative phase")
        check(not manager.mqtt.drain_decoded(), "pre-disconnect telemetry epoch discarded")
        broker.ready.clear()
        broker.peer = None
        broker.thread = threading.Thread(target=broker.run, daemon=True)
        broker.thread.start()
        manager.mqtt._next_reconnect_at = 0.
        manager.mqtt.poll_connection()
        wait_until(lambda: broker.ready.is_set() and manager.mqtt.connected, "fresh MQTT connection established")
        check(manager.mqtt.client is not old_client, "client object, not only socket, is replaced")
        wait_until(lambda: len(broker.publications) >= 2, "neutral KMC sent on fresh connection")
        time.sleep(.08)
        check(len(broker.publications) == 2 and broker.publications[-1][1] == get_profile().codec.encode_keyboard_mouse_control(), "only zero is sent; old QoS1 motion never replayed")
        check(manager.safety.control_state.value == "LOCKED", "fresh match-stage downlink never re-arms")
        check(not manager.publish_keyboard_mouse(keyboard_value=1, qualification_token=token.value)[0], "expired pre-disconnect token remains invalid")
        manager.mqtt.stop()
        manager.mqtt.poll_connection()
        check(not manager.mqtt._started and not manager.mqtt._reconnect_required, "operator stop never reconnects automatically")
    finally:
        manager.shutdown()
        broker.close()

    backend = RmMqttBackend(safety=OfficialSafety())
    backend.client = object()
    backend._started = True
    backend._on_connect_fail(backend.client, None)
    check(backend._reconnect_required and backend._reconnect_backoff_s == 1., "first connection failure retries with bounded backoff")
    backend._on_connect(backend.client, None, {}, SimpleNamespace(value=5))
    check(backend._reconnect_required and not backend.connected, "broker rejection stays locked and schedules retry")
    backend.stop()


def test_team_source_audit() -> None:
    from tools.audit_team_protocol import MCU_SYMBOLS, ROS_SEMANTICS, audit
    from rm_client.backend import polar_link
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        firmware, ros = root / "firmware", root / "ros"
        header = firmware / "application/typedef/usb_typdef.h"
        header.parent.mkdir(parents=True)
        declarations = [f"constexpr uint8_t {symbol} = {getattr(polar_link, client)};" for symbol, client in MCU_SYMBOLS.items()]
        header.write_text("// obsolete GAME_STATUS_SEND_ID = 99;\n" + "\n".join(declarations), encoding="utf-8")
        ros_header = ros / "include/standard_robot_pp_ros2/packet_typedef.hpp"
        ros_header.parent.mkdir(parents=True)
        ros_header.write_text("\n".join(f"constexpr uint8_t {symbol} = {getattr(polar_link, client) + (symbol == 'ID_GAME_STATUS')};" for symbol, client in ROS_SEMANTICS.items()), encoding="utf-8")
        report = audit(firmware, ros)
        check(report["firmware"]["all_ids_match"], "source audit ignores commented old constants")
        check(not report["ros_driver"]["all_ids_match"], "same SOF/different ROS semantics cannot silently pass")
        check(not any(report["capabilities"].values()), "unpatched upstream never claims PRM1/spin implementation")
        check(report["verdict"] == "NOT READY FOR REAL MATCH", "source audit cannot self-certify field readiness")
        header.write_text("\n".join(declarations).replace("GAME_STATUS_SEND_ID = 4;", "GAME_STATUS_SEND_ID = 99;"), encoding="utf-8")
        check(not audit(firmware)["firmware"]["all_ids_match"], "MCU ID drift is a real failure")


def test_arm_identity_binding() -> None:
    manager = BackendManager(state=RobotState(), scenario_key="OfficialEvent")
    try:
        # No session/evidence is minted, and no socket is opened. Exercise the
        # identity gate before the independent evidence verification gate.
        manager.mqtt.connected = True
        manager.mqtt.mock_output = False
        manager.state.robot_id = 4
        ok, reason = manager.arm_match_control(firmware_hash="a" * 64)
        check(not ok and "MQTT ClientId" in reason, "mismatched downlink robot cannot arm another MQTT identity")
        manager.state.robot_id = 3
        ok, reason = manager.arm_match_control(robot_id="4", firmware_hash="a" * 64)
        check(not ok and "MQTT ClientId" in reason, "explicit arm argument cannot bypass transport identity")
        manager.mqtt.connected = False
    finally:
        manager.shutdown()


def main() -> None:
    test_official_field_contract()
    test_partial_state_and_epochs()
    test_student_preview()
    test_real_mqtt_loopback()
    test_fresh_client_reconnect()
    test_team_source_audit()
    test_arm_identity_binding()
    test_schema_import_is_lightweight()
    print(f"ALL PASSED ({CHECKS} checks; localhost only; NOT field qualification)")


if __name__ == "__main__":
    main()
