"""Pure qualification observations, never a source of runtime authority.

Each evaluator receives explicit measured values and session baselines. The
qualification store still owns identity binding, signing and durable evidence;
these functions neither record a result nor change an output gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualificationEvidence:
    key: str
    passed: bool
    measured: dict[str, Any]
    threshold: dict[str, Any] | str


def video_evidence(*, source: str, session_exists: bool, session_age: float,
                   decoded_frames: int, baseline_frames: int, fresh: bool,
                   continuous_seconds: float) -> QualificationEvidence:
    passed = (session_exists and source in {"udp", "native_0310"} and fresh
              and decoded_frames > baseline_frames and continuous_seconds >= 60.0 and session_age >= 60.0)
    return QualificationEvidence("codec_field_test", passed, {
        "source": source, "frames": decoded_frames,
        "frames_since_baseline": max(0, decoded_frames - baseline_frames),
        "seconds": continuous_seconds, "session_age_seconds": session_age,
    }, {"seconds": 60, "fresh": True, "new_frames": True})


def _runtime_evidence(key: str, passed: bool) -> QualificationEvidence:
    return QualificationEvidence(key, passed, {"runtime_observed": passed}, "live lifecycle observed")


def estop_evidence(*, estop_at: float, baseline_estop_at: float, zero_published: bool) -> QualificationEvidence:
    return _runtime_evidence("estop_robot_test", estop_at > baseline_estop_at and zero_published)


def firmware_zero_evidence(*, estop_at: float, baseline_estop_at: float,
                           observed_ms: float) -> QualificationEvidence:
    passed = estop_at > baseline_estop_at and bool(observed_ms) and observed_ms <= 500.0
    return QualificationEvidence("firmware_loss_zero_test", passed,
        {"zero_observed_ms": observed_ms}, {"maximum_ms": 500, "physical_observer_required": True})


def recovery_evidence(*, reconnect_count: int, baseline_reconnect_count: int,
                      disconnect_lock_at: float, reconnected_locked_at: float,
                      baseline_at: float, control_locked: bool) -> QualificationEvidence:
    passed = (reconnect_count > baseline_reconnect_count and disconnect_lock_at > baseline_at
              and reconnected_locked_at > baseline_at and control_locked)
    return _runtime_evidence("loss_recovery_test", passed)


def hero_evidence(*, revision: int, baseline_revision: int, observed_at: float,
                  baseline_at: float, deploy_mode: int) -> QualificationEvidence:
    passed = revision >= baseline_revision + 2 and observed_at > baseline_at and deploy_mode == 0
    return _runtime_evidence("hero_deploy_status_test", passed)


def economy_evidence(*, succeeded: bool, request_is_mock: bool, request_at: float,
                     baseline_at: float, revision: int, baseline_revision: int,
                     transport_is_mock: bool) -> QualificationEvidence:
    passed = (succeeded and not request_is_mock and request_at >= baseline_at
              and revision > baseline_revision and not transport_is_mock)
    return _runtime_evidence("economy_live_test", passed)


def soak_evidence(*, started_at: float, now: float, match_duration: float) -> QualificationEvidence:
    elapsed = now - started_at if started_at > 0.0 else 0.0
    required = max(420.0, match_duration)
    return QualificationEvidence("latency_soak_test", elapsed >= required,
                                 {"seconds": elapsed}, {"minimum_seconds": required})

@dataclass(frozen=True)
class V2AirAttempt:
    """One transient supervised enqueue, with no reusable authorization token.

    Owners are (manager, MQTT, manager profile, MQTT profile, client, session).
    They are held by identity only until explicit observation or retirement.
    Only the serializable measured facts below are written as evidence.
    """
    owners: tuple[Any, ...]
    scope_revision: int
    session_id: str
    operator: str
    profile_id: str
    receive_generation: int
    client_id: str
    robot_id: int
    current_round: int
    command_id: int
    old_status: int
    returned_at: float


def same_v2_air_owners(before: tuple[Any, ...], after: tuple[Any, ...]) -> bool:
    return len(before) == len(after) == 6 and all(a is b for a, b in zip(before, after))


def v2_air_evidence(*, attempt: V2AirAttempt | None, snapshot: Any,
                    owners: tuple[Any, ...], session_id: str, operator: str,
                    session_profile: str, session_robot_id: str,
                    profile_id: str, receive_generation: int, client_id: str,
                    connected: bool, transport_is_mock: bool, now: float
                    ) -> QualificationEvidence:
    """Current later status-path evidence, never a per-request/payment ACK.

    The caller retires a mismatched attempt, and consumes a successful
    observation. An unchanged status can be observed again while still fresh.
    """
    import math
    from .referee_profiles import V2_PROFILE
    from .backend.referee.rm2026_v2.observations import WireSnapshot

    measured: dict[str, Any] = {"path": "supervised Air request and status",
        "unique_request_ack": False, "retire_attempt": False}
    threshold = {"later_current_status_transition": True, "maximum_age_s": 2.0,
                 "named_session_operator": True, "unique_request_ack": False}

    def result(reason: str, *, passed: bool = False, retire: bool = False) -> QualificationEvidence:
        measured.update(reason=reason, retire_attempt=retire)
        return QualificationEvidence("economy_live_test", passed, measured, threshold)

    if type(attempt) is not V2AirAttempt:
        return result("no accepted nonmock supervised Air attempt", retire=True)
    measured.update(session_id=attempt.session_id, operator=attempt.operator,
        profile_id=attempt.profile_id, receive_generation=attempt.receive_generation,
        scope_revision=attempt.scope_revision,
        client_id=attempt.client_id, robot_id=attempt.robot_id, current_round=attempt.current_round,
        command_id=attempt.command_id, previous_status=attempt.old_status,
        post_return_lower_bound=attempt.returned_at)
    if (not same_v2_air_owners(attempt.owners, owners)
            or not connected or transport_is_mock
            or profile_id != V2_PROFILE or attempt.profile_id != V2_PROFILE
            or session_profile != V2_PROFILE or not operator.strip()
            or (session_id, operator) != (attempt.session_id, attempt.operator)
            or session_robot_id != str(attempt.robot_id)
            or (receive_generation, client_id) != (attempt.receive_generation, attempt.client_id)
            or type(snapshot) is not WireSnapshot
            or (snapshot.profile_id, snapshot.receive_generation, snapshot.client_id)
               != (profile_id, receive_generation, client_id)):
        return result("Air attempt owner/session/profile/transport changed", retire=True)
    if (type(now) not in (int, float) or not math.isfinite(now)
            or type(attempt.returned_at) not in (int, float)
            or not math.isfinite(attempt.returned_at) or not 0 <= attempt.returned_at <= now):
        return result("invalid observation clock", retire=True)

    def fresh(message: str, field: str):
        observation = snapshot.get(message, field)
        if (observation is None or type(observation.value) is not int
                or type(observation.received_at) not in (int, float)
                or not math.isfinite(observation.received_at)
                or not 0 <= observation.received_at <= now
                or now - observation.received_at > 2.0):
            return None
        return observation

    # This reducer-owned revision advances on actual scope retirement, not
    # ordinary refresh. It rejects round/identity ABA without freezing receipts.
    if snapshot.scope_revision != attempt.scope_revision:
        return result("Air attempt scope retired; start a new test window", retire=True)
    stage = fresh("GameStatus", "current_stage")
    round_ = fresh("GameStatus", "current_round")
    robot = fresh("RobotStaticStatus", "robot_id")
    if (stage is None or stage.value != 4 or round_ is None
            or round_.value != attempt.current_round or robot is None
            or robot.value != attempt.robot_id or robot.value not in {6, 106}
            or client_id != str(robot.value)):
        return result("Air attempt requires fresh matching MATCH/round/robot scope", retire=True)
    transition = {0: ("airsupport_status", 1, 0),
                  1: ("airsupport_status", 0, 1),
                  2: ("airsupport_status", 0, 1),
                  3: ("shooter_status", 2, 1)}.get(attempt.command_id)
    if transition is None or attempt.old_status != transition[1]:
        return result("pre-request status cannot establish this transition", retire=True)
    status = fresh("AirSupportStatusSync", transition[0])
    measured["status_field"] = transition[0]
    if status is None:
        return result("missing/stale current command-relevant status")
    measured.update(observed_status=status.value, observed_at=status.received_at)
    if status.received_at <= attempt.returned_at:
        return result("status is not later than the accepted enqueue return")
    if status.value != transition[2]:
        return result("command-relevant status transition not observed")
    return result("supervised request and later status path observed; no unique ACK", passed=True, retire=True)
