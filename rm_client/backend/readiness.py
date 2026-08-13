"""Conservative real-match readiness audit.

Unit tests can prove codecs and fail-closed behaviour, but they cannot certify
an untested robot/camera/referee-station installation.  Therefore hardware and
end-to-end gates default to false and the report cannot accidentally label a
desktop mock run as match ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import time
from typing import Any, Mapping

from .protocol import PROTOCOL_VERSION
from .video_backend import resolve_ffmpeg_executable


@lru_cache(maxsize=1)
def _ffmpeg_available() -> bool:
    """Cache the install-level decoder gate for cheap runtime audits."""

    return bool(resolve_ffmpeg_executable())


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
    live_evidence: Mapping[str, Any] | None = None,
) -> BackendReadinessReport:
    """Build a fail-closed report from runtime status plus explicit evidence."""

    evidence = dict(live_evidence or {})
    stats = manager.stats() if manager is not None and hasattr(manager, "stats") else {}
    mqtt = dict(stats.get("mqtt", {}))
    udp = dict(stats.get("udp", {}))
    native_video = dict(stats.get("native_0310", {}))
    # Compatibility with a manager snapshot taken before native stats were
    # promoted to the top level.
    native_video.update(
        dict(getattr(state, "backend_stats", {}).get("native_video_0310", {}))
    )
    scenario = str(stats.get("scenario", getattr(manager, "scenario_key", "")))
    selected_video_source = str(evidence.get("video_source", "")).strip().lower()
    selected_video_source = {
        "native": "native_0310",
        "native 0x0310": "native_0310",
        "0x0310": "native_0310",
        "shark udp": "udp",
        "udp hevc": "udp",
        "h265": "udp",
        "hevc": "udp",
    }.get(selected_video_source, selected_video_source)
    source_declared = selected_video_source in {"udp", "native_0310"}
    udp_decoded = bool(
        udp.get("connected", False)
        and udp.get("decoded_connected", False)
        and int(udp.get("decoded_frames", 0) or 0) > 0
    )
    native_decoded = bool(
        native_video.get("decoder_ready", False)
        and native_video.get("decoded_connected", False)
        and int(native_video.get("decoded_frames", 0) or 0) > 0
    )
    configured_video_ready = bool(
        (selected_video_source == "udp" and udp_decoded)
        or (selected_video_source == "native_0310" and native_decoded)
    )
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
            "protocol_v1_3_1",
            PROTOCOL_VERSION == "1.3.1",
            f"protocol={PROTOCOL_VERSION}; MapClickInfo downlink / MapClickCmd uplink",
        ),
        ReadinessGate(
            "ffmpeg_decoder",
            _ffmpeg_available(),
            "bundled/system ffmpeg decoder is resolvable without runtime download",
        ),
        ReadinessGate(
            "video_source_declared",
            source_declared,
            "live_evidence.video_source must explicitly be udp or native_0310",
            True,
        ),
        ReadinessGate(
            "video_link",
            configured_video_ready,
            f"configured {selected_video_source or 'undeclared'} path has a fresh decoded frame",
            True,
        ),
        ReadinessGate(
            "control_transport",
            bool(mqtt.get("connected", False)) and not bool(mqtt.get("mock_output", True)),
            "KeyboardMouseControl/CustomControl use official MQTT video-link uplink; 0x0311 is blocked on 115200 serial",
            True,
        ),
        ReadinessGate(
            "native_0310_decoder",
            selected_video_source != "native_0310" or native_decoded,
            (
                "rm-native-viewer 0x0310 continuous H.264 stream decoded end to end"
                if selected_video_source == "native_0310"
                else "not selected; UDP field path must satisfy video_link"
            ),
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
        ReadinessGate(
            "control_heartbeat_test",
            bool(evidence.get("control_heartbeat_test", False)),
            "75 Hz KeyboardMouseControl heartbeat and robot-side timeout validated",
            True,
        ),
        ReadinessGate(
            "projectile_hit_spin_test",
            bool(evidence.get("projectile_hit_spin_test", False))
            and bool(getattr(state, "injury_stats_initialized", False))
            and int(getattr(state, "projectile_hit_revision", 0)) > 0,
            "live RobotInjuryStat 17/42 mm delta triggers bounded SpinMode without false first-sample activation",
            True,
        ),
        ReadinessGate(
            "spin_firmware_schema",
            bool(evidence.get("spin_firmware_schema", False)),
            "robot firmware parses PRM1 kind=2 enable/disable, direction and speed with a watchdog timeout",
            True,
        ),
        ReadinessGate(
            "hero_deploy_status_test",
            bool(evidence.get("hero_deploy_status_test", False))
            and float(getattr(state, "deploy_status_at", 0.0) or 0.0) > 0.0,
            "Hero enter/exit command and DeployModeStatusSync/video-cut lifecycle validated on field hardware",
            True,
        ),
        ReadinessGate("loss_recovery_test", bool(evidence.get("loss_recovery_test", False)), "MQTT/video/decoder loss and reconnect drill", True),
        ReadinessGate(
            "robot_firmware_schema",
            bool(evidence.get("robot_firmware_schema", False)),
            "robot firmware parses PRM1 kind=1 vision payload and never treats it as a fire command",
            True,
        ),
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
