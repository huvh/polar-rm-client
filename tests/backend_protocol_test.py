"""?????????????? / ??????? / UDP codec ?? / ?????

???
    .\\.venv\\Scripts\\python.exe tests\\backend_protocol_test.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rm_client.backend import protocol as proto  # noqa: E402
from rm_client.backend.manager import BackendManager  # noqa: E402
from rm_client.backend.safety import OfficialSafety  # noqa: E402
from rm_client.backend.video_backend import detect_frame_codec  # noqa: E402
from rm_client.backend.serial_backend import RmSerialBackend  # noqa: E402
from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.scenarios import SCENARIOS  # noqa: E402

PASS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS
    if not condition:
        raise AssertionError(f"FAIL {name}: {detail}")
    PASS += 1
    print(f"  ok {name}")


def test_uplink_roundtrip() -> None:
    print("[protocol] uplink roundtrip")
    payload = proto.encode_robot_performance_selection_command(shooter=3, chassis=4, sentry_control=0)
    fields = proto.decode_fields(payload)
    check("perf shooter=3", proto._u(fields, 1) == 3)
    check("perf chassis=4", proto._u(fields, 2) == 4)

    payload = proto.encode_dart_command(target_id=5, open_gate=True, launch_confirm=False)
    fields = proto.decode_fields(payload)
    check("dart target=5", proto._u(fields, 1) == 5)
    check("dart open", proto._bool(fields, 2) is True)
    check("dart confirm", proto._bool(fields, 3) is False)

    payload = proto.encode_map_click_info_notify(
        is_send_all=1, robot_id=bytes([1, 3]), mode=2, enemy_id=103,
        ascii_code=65, mark_type=3, map_x=12.5, map_y=7.25,
    )
    fields = proto.decode_fields(payload)
    check("map is_send_all", proto._u(fields, 1) == 1)
    check("map robot_id", proto._b(fields, 2) == bytes([1, 3]))
    check("map mode", proto._u(fields, 3) == 2)
    check("map enemy", proto._u(fields, 4) == 103)
    check("map ascii", proto._u(fields, 5) == 65)
    check("map type", proto._u(fields, 6) == 3)
    check("map x", abs(proto._f(fields, 7) - 12.5) < 1e-4)
    check("map y", abs(proto._f(fields, 8) - 7.25) < 1e-4)

    payload = proto.encode_keyboard_mouse_control(
        mouse_x=100, mouse_y=-200, left_button_down=True, keyboard_value=0b1010,
    )
    fields = proto.decode_fields(payload)
    check("km mouse_x", proto._i(fields, 1) == 100)
    check("km mouse_y", proto._i(fields, 2) == -200)
    check("km left", proto._bool(fields, 4) is True)
    check("km key", proto._u(fields, 6) == 0b1010)

    payload = proto.encode_custom_control(bytes([1, 2, 3]) * 10)
    fields = proto.decode_fields(payload)
    check("cc len", len(proto._b(fields, 1)) == 30)

    for name, fn in [
        ("AssemblyCommand", lambda: proto.encode_assembly_command(1, 3)),
        ("HeroDeployModeEventCommand", lambda: proto.encode_hero_deploy_mode_event_command(1)),
        ("RuneActivateCommand", lambda: proto.encode_rune_activate_command(1)),
        ("SentryCtrlCommand", lambda: proto.encode_sentry_ctrl_command(2)),
        ("AirSupportCommand", lambda: proto.encode_air_support_command(1)),
        ("CommonCommand", lambda: proto.encode_common_command(1, 100)),
        ("MapClickInfo", lambda: proto.encode_map_click_info(1.0, 2.0, 0.0)),
    ]:
        check(f"{name} encodes", len(fn()) > 0)


def test_downlink_decode() -> None:
    print("[protocol] downlink decode")
    payload = b"".join([
        proto.encode_uint(1, 2),   # current_round
        proto.encode_uint(2, 3),   # total_rounds
        proto.encode_uint(3, 42),  # red_score
        proto.encode_uint(4, 33),  # blue_score
        proto.encode_uint(5, 4),   # stage = FIGHTING
        proto.encode_int(6, 90),   # countdown
        proto.encode_int(7, 10),   # elapsed
        proto.encode_bool(8, True),
    ])
    data = proto.decode_message("GameStatus", payload)
    check("GameStatus round", data["current_round"] == 2)
    check("GameStatus stage", data["current_stage"] == 4)
    check("GameStatus countdown", data["stage_countdown_sec"] == 90)
    check("GameStatus paused", data["is_paused"] is True)

    payload = b"".join([
        proto.encode_uint(1, 5000),
        proto.encode_uint(2, 1),
        proto.encode_uint(4, 1500),
        proto.encode_uint(6, 4900),
        proto.encode_uint(9, 1200),
        proto.encode_packed_uints(11, [600, 520, 400, 100]),
        proto.encode_packed_ints(12, [10, 20, 30]),
    ])
    data = proto.decode_message("GlobalUnitStatus", payload)
    check("GUS base", data["base_health"] == 5000)
    check("GUS outpost", data["outpost_health"] == 1500)
    check("GUS enemy base", data["enemy_base_health"] == 4900)
    check("GUS robot_health", data["robot_health"] == [600, 520, 400, 100])
    check("GUS bullets", data["robot_bullets"] == [10, 20, 30])

    payload = b"".join([
        proto.encode_uint(1, 7),
        proto.encode_float(2, 42.5),
        proto.encode_uint(4, 58),
        proto.encode_uint(9, 180),
        proto.encode_bool(10, False),
        proto.encode_bool(12, True),
    ])
    data = proto.decode_message("RobotDynamicStatus", payload)
    check("RDS health", data["current_health"] == 7)
    check("RDS heat", abs(data["current_heat"] - 42.5) < 1e-4)
    check("RDS ammo", data["remaining_ammo"] == 180)
    check("RDS remote_heal", data["can_remote_heal"] is True)

    payload = b"".join([
        proto.encode_float(1, 10.5),   # x
        proto.encode_float(2, 7.25),   # y
        proto.encode_float(4, 90.0),   # yaw
        proto.encode_uint(5, 4),       # robot_id
    ])
    data = proto.decode_message("RobotPosition", payload)
    check("POS id", data["robot_id"] == 4)
    check("POS x", abs(data["x"] - 10.5) < 1e-4)
    check("POS yaw", abs(data["yaw"] - 90.0) < 1e-4)

    # RadarInfoToClient ????
    sub = b"".join([
        proto.encode_uint(1, 10),
        proto.encode_uint(2, 20),
        proto.encode_uint(3, 1),
    ])
    payload = proto.encode_bytes(1, sub) + proto.encode_bytes(1, sub)
    data = proto.decode_message("RadarInfoToClient", payload)
    check("Radar count", len(data["robots"]) == 2)
    check("Radar highlight", data["robots"][0]["is_high_light"] == 1)

    payload = b"".join([
        proto.encode_uint(1, 3),
        proto.encode_uint(2, 8),
        proto.encode_float(3, 2.5),
    ])
    data = proto.decode_message("RuneStatusSync", payload)
    check("Rune status", data["rune_status"] == 3)
    check("Rune rings", abs(data["average_rings"] - 2.5) < 1e-4)


def test_safety_modes() -> None:
    print("[safety] three-mode gating")
    lab = SCENARIOS["LabDebug"]
    campus = SCENARIOS["CampusSimulation"]
    official = SCENARIOS["OfficialEvent"]

    s = OfficialSafety("LabDebug")
    s.from_scenario(lab)
    ok, reason = s.can_publish("DartCommand")
    check("LabDebug blocks real publish", ok is False and "mock" in reason)

    s = OfficialSafety("CampusSimulation")
    s.from_scenario(campus)
    s.update_stage("0")
    ok, reason = s.can_publish("CommonCommand")
    check("Campus non-fighting blocked (official limits)", ok is False and "??" in reason)
    s.update_stage("4")
    ok, reason = s.can_publish("CommonCommand")
    check("Campus fighting allowed", ok is True)

    s = OfficialSafety("OfficialEvent")
    s.from_scenario(official)
    s.update_stage("0")
    ok, reason = s.can_publish("DartCommand")
    check("Official non-fighting blocked", ok is False and "??" in reason)
    s.update_stage("4")
    ok, reason = s.can_publish("DartCommand")
    check("Official fighting allowed", ok is True)
    s.mark_published("DartCommand")  # ???????????
    ok, reason = s.can_publish("DartCommand")
    check("Official 10Hz limited", ok is False and "10Hz" in reason)

    s.trigger_estop()
    ok, reason = s.can_publish("DartCommand")
    check("Estop blocks", ok is False and "??" in reason)
    s.release_estop()
    ok, _ = s.can_publish("CommonCommand")
    check("Estop release", ok is True)


def test_video_codec_detect() -> None:
    print("[video] codec detect")
    check("mjpeg detect", detect_frame_codec(b"\xff\xd8\xff\xe0rest") == "mjpeg")
    nal = b"\x00\x00\x00\x01" + bytes([(32 << 1) | 1]) + b"\\x01\\x02"
    check("h265 detect", detect_frame_codec(nal) == "h265")
    check("unknown detect", detect_frame_codec(b"hello") == "unknown")


def test_serial_backend() -> None:
    print("[serial] mock + stop frame")
    serial = RmSerialBackend(port="Stub", baud=115200, mock_writes=True)
    serial.start()
    check("stub not connected", serial.connected is False)
    ok, reason = serial.write_frame(0x0311, b"\x00" * 30)
    check("mock write ok", ok is True and reason == "mock")
    serial.stop()


def test_manager_updates_state() -> None:
    print("[manager] apply_updates -> RobotState")
    state = RobotState()
    manager = BackendManager(state=state, client_id="3", scenario_key="LabDebug")
    # ????????????? MQTT?
    from collections import deque
    import threading as _t
    manager.mqtt._decoded.append(("GameStatus", "GameStatus", {
        "current_round": 1, "total_rounds": 3, "red_score": 10, "blue_score": 8,
        "current_stage": 4, "stage_countdown_sec": 300, "stage_elapsed_sec": 120,
    }, time.perf_counter()))
    manager.mqtt._decoded.append(("GlobalUnitStatus", "GlobalUnitStatus", {
        "base_health": 5000, "outpost_health": 1500, "enemy_base_health": 4800,
        "robot_health": [600, 520], "robot_bullets": [10, 20],
    }, time.perf_counter()))
    manager.mqtt._decoded.append(("RobotModuleStatus", "RobotModuleStatus", {
        "power_manager": 1, "rfid": 1, "capacitor": 1,
    }, time.perf_counter()))
    manager.mqtt._decoded.append(("RobotPosition", "RobotPosition", {
        "robot_id": 103, "x": 12.0, "y": 7.0, "yaw": 90.0,
    }, time.perf_counter()))
    manager.mqtt._decoded.append(("RuneStatusSync", "RuneStatusSync", {
        "rune_status": 3, "activated_arms": 4, "average_rings": 2.5,
    }, time.perf_counter()))
    manager.mqtt._decoded.append(("PenaltyInfo", "PenaltyInfo", {
        "penalty_type": 1, "penalty_effect_sec": 30, "total_penalty_num": 1,
    }, time.perf_counter()))
    count = manager.apply_updates(state)
    check("applied 6 messages", count == 6)
    check("state stage MATCH", state.current_stage == "MATCH")
    check("state red_score", state.red_score == 10)
    check("state base_health", state.base_health == 5000)
    check("state official_robot_health", state.official_robot_health == [600, 520])
    check("state module_status", state.robot_module_status.get("power_manager") == 1)
    check("state positions", state.robot_positions[0]["robot_id"] == 103)
    check("state rune phase", state.energy_rune_phase == "ACTIVE")
    check("state rune progress", state.energy_rune_progress == 250)
    check("state active_penalty", state.active_penalty["penalty_type"] == 1)

    # ?????????? ? shooter=chassis=3?
    registry = build_default_registry()
    values = BackendManager.performance_values(registry)
    check("perf default infantry", values["shooter"] == 2 and values["chassis"] == 2)
    manager.shutdown()


def main() -> None:
    test_uplink_roundtrip()
    test_downlink_decode()
    test_safety_modes()
    test_video_codec_detect()
    test_serial_backend()
    test_manager_updates_state()
    print(f"\\nALL PASSED ({PASS} checks)")


if __name__ == "__main__":
    main()
