"""Offline DT7 authorization integration. No COM/MQTT socket is ever opened.

Signed fixture records prove software behavior, NOT field match readiness.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["POLAR_DISABLE_LOCAL_CAPTURE"] = "1"
os.environ["POLAR_DISABLE_MEDIA_PRELOAD"] = "1"

from rm_client.backend.dt7_link import Dt7KeyMouseLink, load_profile, profile_digest, decode_dt7_frame
from rm_client.backend.dt7_qualification import Dt7Probe, PROBE_BITS
from rm_client.backend.manager import BackendManager
from rm_client.backend.polar_bridge import PolarStateBridge
from rm_client.backend.qualification import CORE_TESTS, QualificationEvidenceStore, QualificationManager
from rm_client.backend.safety import OfficialSafety, ControlState
from rm_client.control import KeyboardControlBridge
from rm_client.model import RobotState, build_default_registry
from rm_client.runtime_paths import RuntimePaths

CHECKS = 0
FW = "A" * 64


def check(value, label):
    global CHECKS
    assert value, label
    CHECKS += 1
    print("  ok", label)


def refused(callback, label):
    try:
        callback()
    except ValueError:
        check(True, label)
    else:
        check(False, label)


def complete_probe(*, held=False):
    probe = Dt7Probe(10.0)
    seq = 0
    for phase, samples, end, frames in (
        ("baseline", [(10.2, 0), (10.8, 0)], 11.0, 0),
        ("press", [(11.2, PROBE_BITS), (11.7, PROBE_BITS)], 11.91, 20),
        ("hold", [(12.2, PROBE_BITS if held else 0), (13.2, PROBE_BITS if held else 0)], 13.52, 20),
    ):
        check(probe.phase == phase, "probe phase " + phase)
        for at, key in samples:
            seq += 1
            probe.observe(key, at, seq, at)
        probe.advance(end, frames)
    check(probe.result["baseline"] == 0 and probe.result["verdict"] == "PASS", "pre-send baseline proves key transition")
    check(probe.result["hold_verdict"] == ("STUCK" if held else "EXPIRES"), "no-send hold remains separate from physical stop")
    return probe


def core_fixture(q):
    q.new_session(robot_id="3", firmware_hash=FW, match_mode="RMUC 7v7", video_source="udp", operator="Offline fixture operator")
    for key in CORE_TESTS:
        if key != "field_signoff":
            q.record_automatic(key, True, measured={"OFFLINE_FIXTURE_ONLY": True}, source="offline-test-fixture")


def dt7_fixture(q, prof):
    core_fixture(q)
    q.record_dt7_probe(complete_probe(), profile_sha256=profile_digest(prof), real_transport=True)
    q.record_supervised_dt7_safety(observer="Offline physical-observer fixture", firmware_hash=FW,
        profile_sha256=profile_digest(prof), measured={
            "physical_estop_observed": True, "physical_loss_zero_observed": True,
            "reconnect_stayed_neutral": True, "estop_zero_ms": 150, "loss_zero_ms": 300,
            "OFFLINE_FIXTURE_ONLY": True})
    q.sign_off("Offline second-person fixture")


def keys(frame):
    return struct.unpack_from("<H", decode_dt7_frame(frame)["payload"], 8)[0]


def test_policy():
    prof = load_profile()
    out = []
    policy = OfficialSafety("OfficialEvent")
    link = Dt7KeyMouseLink(port="NO_HARDWARE", profile=prof, mock_output=False, write_bytes=out.append)
    check(not link.send(pressed_bits=1)[0] and not out, "unbound real writer is locked")
    link.safety = policy
    check(not link.send(pressed_bits=1)[0] and not out, "flags cannot bypass startup LOCKED")
    policy.arm_match({"core_kmc", "dt7_control"})
    check(not link.send(pressed_bits=1)[0], "DT7 requires authoritative stage even outside official limit mode")
    policy.update_stage("4")
    policy.arm_match({"core_kmc"})
    check(not link.send(pressed_bits=1)[0], "MQTT qualification cannot authorize DT7")
    policy.arm_match({"core_kmc", "dt7_control"})
    check(link.send(pressed_bits=1, now=100)[0], "independent capability authorizes transport")
    check(not link.send(pressed_bits=2, now=100.001)[0], "writer owns 30 Hz limiter")
    check(link.release(now=100.002)[0] and keys(out[-1]) == 0, "release preempts rate limit")
    policy.trigger_estop()
    refused(lambda: policy.arm_match({"core_kmc", "dt7_control"}), "Arm cannot release E-stop")
    refused(lambda: policy.begin_qualification({"dt7_selftest"}), "qualification cannot release E-stop")
    check(not link.send(pressed_bits=1, now=101)[0], "ESTOP denies motion")
    check(link.release(now=101)[0] and keys(out[-1]) == 0, "dedicated neutral bypass works in ESTOP")
    check(not link.send(pressed_bits=1, _neutral_release=True)[0], "neutral bypass cannot forge nonzero input")
    policy.release_estop()
    check(not link.send(pressed_bits=1)[0], "E-stop release never resumes movement")
    token = policy.begin_qualification({"dt7_selftest"}, now=200, ttl_s=2)
    check(link.send(pressed_bits=PROBE_BITS, qualification_token=token.value, now=200)[0], "qualification allows X")
    for kw in ({"pressed_bits": 1}, {"pressed_bits": PROBE_BITS | 1}, {"mouse_dx": 1},
               {"left": True}, {"right": True}, {"mid": True}):
        check(not link.send(**kw, qualification_token=token.value, now=200.1)[0], "probe cannot include motion/firing " + str(kw))
    check(not link.send(pressed_bits=PROBE_BITS, qualification_token="wrong", now=200.2)[0], "wrong token denied")
    check(not link.send(pressed_bits=PROBE_BITS, qualification_token=token.value, now=202.1)[0], "expired token locks")
    token = policy.begin_qualification({"core_kmc"}, now=300)
    check(not link.send(pressed_bits=PROBE_BITS, qualification_token=token.value, now=300)[0], "KMC token has no DT7 scope")
    policy.arm_match({"core_kmc", "dt7_control"})
    link.authorization_guard = lambda _: (_ for _ in ()).throw(OSError("corrupt evidence"))
    check(not link.send(pressed_bits=1)[0] and policy.control_state == ControlState.LOCKED, "evidence exception fails closed")


def test_samples():
    complete_probe(held=True)
    probe = Dt7Probe(10)
    for key, at, sequence, now in ((0, 9, 1, 10), (0, 11, 2, 10), (True, 10.2, 3, 10.2),
                                   (0, None, 4, 10.3), (0, 10.1, 5, 11), (0, 10.2, True, 10.3)):
        probe.observe(key, at, sequence, now)
    check(not probe.samples["baseline"], "stale/future/non-numeric samples rejected")
    probe.observe(0, 10.2, 1, 10.2)
    probe.observe(0, 10.2, 1, 10.4)
    probe.advance(11, 0)
    check(probe.result["verdict"] == "NO-READBACK", "cached sample cannot establish baseline")
    probe = Dt7Probe(10)
    probe.observe(PROBE_BITS, 10.1, 1, 10.1)
    probe.observe(0, 10.8, 2, 10.8)
    probe.advance(11, 0)
    check(probe.result["verdict"] == "BLOCKED", "already-held probe cannot self-certify")
    bridge = PolarStateBridge(clock=lambda: 20.0)
    bridge._handle_debug({"packages": {"km_key": 17.0}})
    check(bridge.debug_key_sequence == 1 and bridge.debug_key_at == 20, "real debug key packet advances identity")
    for value in ("abc", float("nan"), 1.5, True, 65536, -1):
        bridge._handle_debug({"packages": {"km_key": value}})
        check(bridge.debug_key_sequence == 1 and "km_key" not in bridge.debug_packages, "invalid readback cannot become neutral/fresh")
    bridge._handle_debug({"packages": {"km_rx": 5}})
    check(bridge.debug_key_at == 0, "unrelated telemetry does not refresh key sample")
    refused(lambda: Dt7Probe(10, hold_s=float("inf")), "probe duration is bounded")


def test_evidence(root):
    prof = load_profile()
    q = QualificationManager(QualificationEvidenceStore(root, build_commit="OFFLINE_FIXTURE"))
    dt7_fixture(q, prof)
    check("dt7_control" in q.capabilities(), "signed robot/profile-bound fixture grants independent capability")
    check(q.verified_core_ready()[0], "fixture reload is authenticated")
    refused(lambda: q.record_automatic("dt7_link_test", True), "generic runner cannot mint DT7 link proof")
    refused(lambda: q.record_automatic("dt7_robot_safety_test", True, source="config"), "configuration cannot mint safety proof")
    refused(lambda: q.record_dt7_probe(complete_probe(), profile_sha256=profile_digest(prof), real_transport=False), "mock probe cannot mint field proof")
    refused(lambda: q.record_supervised_dt7_safety(observer="observer", firmware_hash="B"*64,
        profile_sha256=profile_digest(prof), measured={}), "different firmware rejected")
    refused(lambda: q.record_supervised_dt7_safety(observer="observer", firmware_hash=FW,
        profile_sha256="B"*64, measured={}), "different profile rejected")
    for bad in (True, float("nan"), 501, -1):
        result = q.record_supervised_dt7_safety(observer="observer", firmware_hash=FW,
            profile_sha256=profile_digest(prof), measured={"physical_estop_observed": True,
                "physical_loss_zero_observed": True, "reconnect_stayed_neutral": True,
                "estop_zero_ms": bad, "loss_zero_ms": 200})
        check(result.status == "FAIL" and "dt7_control" not in q.capabilities(), "invalid physical bound cannot pass " + str(bad))
    q.session.tests["dt7_link_test"].recorded_at = time.time()-86401
    check(not q.test_passed("dt7_link_test"), "DT7 dynamic evidence expires at 24 hours")
    refused(lambda: q.record_supervised_dt7_safety(observer="observer", firmware_hash=FW,
        profile_sha256=profile_digest(prof), measured={}), "expired link proof cannot support safety proof")


def test_integration(root):
    manager = BackendManager(workspace=root, scenario_key="OfficialEvent", client_id="3")
    state, registry = RobotState(), build_default_registry()
    state.robot_id, state.match_mode = 3, "RMUC 7v7"
    manager.state = state
    manager._active_video_source = "udp"
    manager.safety.update_stage("4")
    module = registry.get("RobotLink")
    module.enabled = True
    for name, value in (("Allow Drive", True), ("Direct DT7 Egress", True), ("DT7 Real TX", True), ("DT7 Port", "NO_HARDWARE")):
        module.get_setting(name).value = value
    output = []
    prof = load_profile()
    link = Dt7KeyMouseLink(port="NO_HARDWARE", profile=prof, mock_output=False, write_bytes=output.append)
    manager._dt7_link = link
    control = KeyboardControlBridge(publisher=manager, mock_output=False)
    manager.tick_polar_link(state, registry, control)
    control.set_key("W", True, state, registry)
    control.send_from_state(state, registry)
    check(not output and not control.dt7_enabled, "all UI flags still cannot transmit while locked")
    report = manager.apply_readiness(state, registry=registry)
    check("dt7_control" in report["blockers"] and "dt7_runtime_route" in report["blockers"], "readiness consumes both DT7 authorization and live route")
    dt7_fixture(manager.qualification, prof)
    manager.mqtt.connected = True  # only a boolean test endpoint; no socket/publish
    check(manager.arm_match_control(firmware_hash=FW, video_source="udp")[0], "manager arms only authenticated DT7 fixtures")
    manager.tick_polar_link(state, registry, control)
    control.set_key("W", True, state, registry)
    control.left_button_down = control.right_button_down = True
    report = manager.apply_readiness(state, registry=registry)
    check("dt7_control" not in report["blockers"] and "dt7_runtime_route" not in report["blockers"], "authorized real DT7 fixture satisfies DT7 gates only")
    module.get_setting("DT7 Real TX").value = False
    report = manager.apply_readiness(state, registry=registry)
    check("dt7_runtime_route" in report["blockers"], "real TX disabled cannot claim usable DT7 route")
    module.get_setting("DT7 Real TX").value = True
    control.send_from_state(state, registry)
    check(keys(output[-1]) == 1, "W traverses runtime endpoint")
    check(decode_dt7_frame(output[-1])["payload"][6:8] == b"\0\0", "default fire gate blocks mouse buttons")
    module.get_setting("DT7 Allow Fire Keys").value = True
    manager.tick_polar_link(state, registry, control)
    link._next_due = 0
    control.send_from_state(state, registry)
    check(decode_dt7_frame(output[-1])["payload"][6:8] == b"\1\1", "explicit fire gate enables both mouse buttons")
    manager.lock_control("window lost focus")
    check(keys(output[-1]) == 0 and not any(control.key_state.values()), "lock clears local and wire inputs")
    check(not link.send(pressed_bits=1)[0], "direct writer cannot bypass manager lock")
    check(manager.arm_match_control(firmware_hash=FW, video_source="udp")[0], "manual re-arm required")
    manager.tick_polar_link(state, registry, control)
    link._next_due = 0
    control.set_key("W", True, state, registry)
    fail = {"on": True}
    def writer(frame):
        if fail["on"]:
            return 1  # short write of motion AND the first neutral retry
        output.append(frame)
        return len(frame)
    link.write_bytes = writer
    link._next_due = 0
    control.send_from_state(state, registry)
    check(manager.safety.control_state == ControlState.LOCKED and control.dt7_release_pending, "short write preserves neutral retry through callback")
    fail["on"] = False
    control.tick(state, registry, now=time.perf_counter()+1)
    check(not control.dt7_release_pending and keys(output[-1]) == 0, "locked reconnect transmits only pending neutral")
    manager.tick_polar_link(state, registry, control)
    check(not control.dt7_enabled and not link.send(pressed_bits=1)[0], "reconnect never replays old movement")
    manager.safety.arm_match({"core_kmc", "dt7_control"})
    manager.tick_polar_link(state, registry, control)
    state.robot_id = 4
    check(not link.send(pressed_bits=1)[0] and manager.safety.control_state == ControlState.LOCKED, "runtime robot identity change revokes DT7")
    state.robot_id = 3
    manager.safety.arm_match({"core_kmc", "dt7_control"})
    manager.tick_polar_link(state, registry, control)
    link._next_due = 0
    check(link.send(pressed_bits=1)[0], "fixture can explicitly re-arm after identity restored")
    fail["on"] = True
    module.get_setting("DT7 Port").value = "OTHER_NO_HARDWARE"
    manager.tick_polar_link(state, registry, control)
    check(manager._dt7_link is link and control.dt7_release_pending, "failed old-port release retains the original writer")
    check(not control.dt7_enabled and manager.safety.control_state == ControlState.LOCKED, "failed port change cannot arm or discard pending zero")
    fail["on"] = False
    control.tick(state, registry, now=time.perf_counter()+1)
    manager.tick_polar_link(state, registry, control)
    check(keys(output[-1]) == 0 and manager.safety.control_state == ControlState.LOCKED, "port replacement neutralizes old writer then locks")
    check(manager._dt7_link is not link and not control.dt7_enabled, "new port remains locked")
    current = manager._dt7_link
    # Port replacement now creates the production async facade. Inject the
    # writer into its codec, not a shadow attribute on the facade; no COM opens.
    getattr(current, "_link", current).write_bytes = output.append
    manager.safety.arm_match({"core_kmc", "dt7_control"})
    manager.tick_polar_link(state, registry, control)
    before = len(output)
    # Queue acceptance is NOT physical delivery. Advance the wall clock while
    # retaining authenticated records, then observe the actual worker outcome.
    with patch("rm_client.backend.qualification.time.time", return_value=time.time()+86401):
        accepted, _ = current.send(pressed_bits=1)
        if getattr(current, "asynchronous", False):
            deadline = time.perf_counter()+2
            while time.perf_counter() < deadline and manager.safety.control_state != ControlState.LOCKED:
                current.poll()
                time.sleep(.005)
        else:
            check(not accepted, "synchronous writer refuses expired evidence immediately")
    check(all(keys(frame) == 0 for frame in output[before:]), "expired evidence emits no physical motion frame")
    check(manager.safety.control_state == ControlState.LOCKED, "worker expiry notification locks without a manager tick")
    manager.shutdown()
    if getattr(current, "asynchronous", False):
        check(current.wait_closed(2), "async fixture worker exits after neutral cleanup")


def test_lab_debug_drive(root):
    """LabDebug (bench scene) opens DT7 real egress only; the match state machine stays LOCKED."""
    manager = BackendManager(workspace=root, scenario_key="LabDebug", client_id="3")
    state, registry = RobotState(), build_default_registry()
    state.robot_id, state.match_mode = 3, "RMUC 7v7"
    manager.state = state
    manager._active_video_source = "udp"
    module = registry.get("RobotLink")
    module.enabled = True
    for name, value in (("Allow Drive", True), ("Direct DT7 Egress", True),
                        ("DT7 Real TX", True), ("DT7 Port", "NO_HARDWARE")):
        module.get_setting(name).value = value
    output = []
    prof = load_profile()
    link = Dt7KeyMouseLink(port="NO_HARDWARE", profile=prof, mock_output=False,
                           write_bytes=output.append)
    manager._dt7_link = link
    # LabDebug keeps the MQTT uplink mocked: only the physical DT7 port is opened.
    control = KeyboardControlBridge(publisher=manager, mock_output=True)
    check(bool(manager.safety.allow_dt7_drive) and bool(manager.safety.stats()["allow_dt7_drive"]),
          "LabDebug scenario exposes the lab DT7 drive switch")
    official = BackendManager(workspace=root/"official-fixture", scenario_key="OfficialEvent", client_id="3")
    check(not official.safety.allow_dt7_drive, "OfficialEvent keeps the lab DT7 drive switch closed")
    check(not official.safety.can_transmit_dt7()[0], "OfficialEvent still refuses DT7 transport while LOCKED")
    campus = BackendManager(workspace=root/"campus-fixture", scenario_key="CampusSimulation", client_id="3")
    check(not campus.safety.allow_dt7_drive and not campus.safety.can_transmit_dt7()[0],
          "CampusSimulation keeps DT7 drive closed and transport denied")
    campus.shutdown()
    manager.tick_polar_link(state, registry, control)
    check(manager.safety.control_state == ControlState.LOCKED and bool(control.dt7_enabled),
          "lab drive opens DT7 egress while the match state machine stays LOCKED")
    check(manager._dt7_evidence_gate(prof)[0], "lab drive waives the qualification evidence gate")
    official.safety.update_stage("4")
    official.safety.arm_match({"core_kmc"})
    check(not official.safety.can_transmit_dt7()[0],
          "OfficialEvent still denies DT7 without its own dt7_control capability")
    official.shutdown()
    control.set_key("W", True, state, registry)
    check(bool(output) and keys(output[-1]) == 1, "W reaches the DT7 wire without any qualification fixture")
    before = len(output)
    control.send_from_state(state, registry)
    check(len(output) == before and link.last_send_rate_limited, "lab drive still obeys the 30 Hz writer limit")
    link._next_due = 0
    control.left_button_down = control.right_button_down = True
    control.send_from_state(state, registry)
    check(decode_dt7_frame(output[-1])["payload"][6:8] == b"\0\0", "lab drive keeps the fire gate closed by default")
    module.get_setting("DT7 Allow Fire Keys").value = True
    manager.tick_polar_link(state, registry, control)
    link._next_due = 0
    control.send_from_state(state, registry)
    check(decode_dt7_frame(output[-1])["payload"][6:8] == b"\1\1", "explicit fire gate still controls lab mouse buttons")
    check(not manager.safety.can_publish("KeyboardMouseControl")[0],
          "lab switch never opens the MQTT driving topic")
    control.set_mouse_button(1, False, state, registry)
    control.set_mouse_button(3, False, state, registry)
    control.set_key("W", False, state, registry)
    control.tick(state, registry, now=time.perf_counter()+1)
    check(keys(output[-1]) == 0 and link.wire_neutral, "release lands a neutral frame on the DT7 wire")
    manager.safety.trigger_estop()
    link._next_due = 0
    ok, why = link.send(pressed_bits=1)
    check(not ok and "E-stop" in str(why), "E-stop still denies lab DT7 drive")
    manager.tick_polar_link(state, registry, control)
    check(not control.dt7_enabled and keys(output[-1]) == 0, "E-stop drops the lab route and lands neutral")
    manager.shutdown()



def test_portable(root):
    paths = RuntimePaths.discover(executable=root/"POLAR-RM.exe", environ={}, frozen=True)
    check(paths.defaults_root == root/"defaults", "portable DT7 profile belongs in defaults")
    with patch("rm_client.backend.dt7_link.PROFILE_FILE", paths.defaults_root/"dt7_profile.json"):
        check(bool(load_profile()["_profile_error"]), "missing portable profile is fail-closed")
    a = load_profile()
    b = dict(a, _profile_path="different location", description="comment only")
    check(profile_digest(a) == profile_digest(b), "profile binding ignores metadata/path only")
    b["reserved_value"] = 0
    check(profile_digest(a) != profile_digest(b), "wire-semantic profile changes invalidate proof")
    script = (Path(__file__).resolve().parents[1]/"tools/build_release.ps1").read_text(encoding="utf-8-sig")
    check('"defaults\\dt7_profile.json"' in script, "release explicitly copies profile from build commit")


def main():
    with tempfile.TemporaryDirectory(prefix="dt7-alignment-") as folder:
        root = Path(folder)
        with patch.dict(os.environ, {"POLAR_USER_DATA_ROOT": str(root/"userdata")}):
            test_policy()
            test_samples()
            test_evidence(root/"evidence-fixture")
            test_integration(root/"backend-fixture")
            test_lab_debug_drive(root/"lab-fixture")
            test_portable(root/"portable-fixture")
    print(f"DT7 alignment PASS: {CHECKS} checks; OFFLINE ONLY / NOT READY FOR REAL MATCH")


if __name__ == "__main__":
    main()
