"""Conservative real-match readiness audit.

Unit tests can prove codecs and fail-closed behaviour, but they cannot certify
an untested robot/camera/referee-station installation.  Therefore hardware and
end-to-end gates default to false and the report cannot accidentally label a
desktop mock run as match ready.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ReadinessGate:
    key: str
    passed: bool
    detail: str
    requires_live_validation: bool = False


@dataclass(frozen=True, slots=True)
class BackendReadinessReport:
    gates: tuple[ReadinessGate, ...]

    @property
    def ready(self) -> bool:
        return bool(self.gates) and all(gate.passed for gate in self.gates)

    @property
    def verdict(self) -> str:
        return "READY FOR REAL MATCH" if self.ready else "NOT READY FOR REAL MATCH"

    @property
    def blockers(self) -> tuple[ReadinessGate, ...]:
        return tuple(gate for gate in self.gates if not gate.passed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "verdict": self.verdict,
            "gates": [
                {
                    "key": gate.key,
                    "passed": gate.passed,
                    "detail": gate.detail,
                    "requires_live_validation": gate.requires_live_validation,
                }
                for gate in self.gates
            ],
        }


def audit_backend(
    manager: Any,
    state: Any,
    *,
    live_evidence: Mapping[str, bool] | None = None,
) -> BackendReadinessReport:
    """Build a fail-closed report from runtime status plus explicit evidence."""

    evidence = dict(live_evidence or {})
    stats = manager.stats() if manager is not None and hasattr(manager, "stats") else {}
    mqtt = dict(stats.get("mqtt", {}))
    udp = dict(stats.get("udp", {}))
    serial = dict(stats.get("serial", {}))
    native_video = dict(getattr(state, "backend_stats", {}).get("native_video_0310", {}))
    scenario = str(stats.get("scenario", getattr(manager, "scenario_key", "")))
    video_frames = int(udp.get("frames_received", udp.get("frames", 0)) or 0)
    video_packets = int(udp.get("packets_received", udp.get("packets", 0)) or 0)
    official_feed_at = float(getattr(state, "official_feed_at", 0.0) or 0.0)
    official_fresh = bool(
        getattr(state, "official_events_online", False)
        and official_feed_at > 0.0
        and time.perf_counter() - official_feed_at <= 2.0
    )
    gates = (
        ReadinessGate("official_scenario", scenario == "OfficialEvent", f"scenario={scenario or 'unknown'}"),
        ReadinessGate("mqtt_link", bool(mqtt.get("connected", False)), "referee MQTT downlink connected", True),
        ReadinessGate(
            "mqtt_real_publish",
            bool(mqtt.get("connected", False)) and not bool(mqtt.get("mock_output", True)),
            "official uplink is connected and no longer in mock-output mode",
            True,
        ),
        ReadinessGate(
            "video_link",
            bool(udp.get("connected", False)) and video_packets > 0 and video_frames > 0,
            "live video packets and decoded frame observed",
            True,
        ),
        ReadinessGate("serial_link", bool(serial.get("connected", False)) and not bool(serial.get("mock_writes", True)), "real lower-controller serial link", True),
        ReadinessGate(
            "native_0310_decoder",
            bool(native_video.get("decoder_ready", False)),
            "rm-native-viewer 0x0310 continuous H.264 stream decoded end to end",
            True,
        ),
        ReadinessGate(
            "codec_field_test",
            bool(evidence.get("codec_field_test", False)),
            "configured H.264/H.265 path validated against the match transmitter",
            True,
        ),
        ReadinessGate("fresh_referee_state", official_fresh, "official referee state received within 2 seconds", True),
        ReadinessGate("camera_calibration", bool(getattr(state, "vision_calibrated", False)), "camera calibration loaded and accepted", True),
        ReadinessGate("estop_robot_test", bool(evidence.get("estop_robot_test", False)), "physical E-stop zero-frame and latch test", True),
        ReadinessGate("command_ack_test", bool(evidence.get("command_ack_test", False)), "lower-controller command/ACK semantics validated", True),
        ReadinessGate("loss_recovery_test", bool(evidence.get("loss_recovery_test", False)), "MQTT/video/serial loss and reconnect drill", True),
        ReadinessGate("latency_soak_test", bool(evidence.get("latency_soak_test", False)), "full-duration match latency/thermal soak", True),
        ReadinessGate(
            "hero_lob_live_test",
            bool(evidence.get("hero_lob_live_test", False))
            and bool(getattr(state, "hero_lob_yaw_calibrated", False))
            and bool(getattr(state, "hero_lob_pitch_calibrated", False))
            and bool(getattr(state, "hero_lob_relocalization_valid", False)),
            "Hero lob yaw/pitch/relocalization calibrated and validated on the real robot",
            True,
        ),
        ReadinessGate("field_signoff", bool(evidence.get("field_signoff", False)), "operator and safety lead field sign-off", True),
    )
    return BackendReadinessReport(gates)
