"""后端管理器：把 SharkClient 风格后端对齐本地三种运行场景。

LabDebug / CampusSimulation / OfficialEvent 各自：
- MQTT：真实连接（可收）、按场景决定是否真实发布（LabDebug mock）
- UDP：监听图传端口、codec 检测、H.264/H.265/MJPEG 解码、统计
- 串口：仅保留非图传链路接口；明确拒绝把 0x0311 写入 115200 串口
- 安全：KMC/CustomControl 75Hz、事件命令 10Hz、阶段门控与急停

同时把全量下行消息解码结果写入 RobotState，并提供 V1.3.1 上行编码入口。
"""

from __future__ import annotations

import logging
import json
import time
from typing import Any, Callable

from ..model import RobotState
from ..native_viewer_telemetry import parse_vehicle_telemetry, parse_video_0310_chunk
from ..scenarios import SCENARIOS
from . import protocol as proto
from .mqtt_backend import RmMqttBackend
from .safety import OfficialSafety
from .serial_backend import RmSerialBackend
from .video_backend import AnnexBRecoveryGate, ContinuousMjpegDecoder, RmVideoBackend
from .field_log import RotatingJsonlLogger
from .qualification import QualificationEvidenceStore, QualificationManager
from ..runtime_paths import RuntimePaths

# 官方性能体系取值（对齐 messages.proto 与 Shark RoboModeSettings）
HERO_MELEE = 3
HERO_RANGE = 4
SHOOTER_COOLING = 1
SHOOTER_BURST = 2
CHASSIS_HEALTH = 1
CHASSIS_POWER = 2
SENTRY_AUTOMATIC = 0
SENTRY_SEMI_AUTO = 1

_RUNE_PHASE = {1: "INACTIVE", 2: "ACTIVATING", 3: "ACTIVE"}
# ??? ID ? ?????? 1-9 / ?? 101-109??? = ?? + 100?
ROBOT_ID_NAMES = {1: "Hero", 2: "Engineer", 3: "Infantry", 4: "Infantry", 5: "Infantry",
                  6: "Aerial", 7: "Sentry", 8: "Dart", 9: "Radar"}
# ?? BuffType??? Shark mqtt_protocol.ts?
BUFF_TYPE_NAMES = {1: "Attack Boost", 2: "Defense Boost", 3: "Heat Cooling",
                   4: "Chassis Power", 5: "Health Regen", 6: "Exchange Ammo", 7: "Terrain"}
DEFAULT_MAX_HEALTH = 600
_STAGE_STR = {0: "NOT_STARTED", 1: "PREPARE", 2: "SELF_CHECK", 3: "COUNTDOWN", 4: "MATCH", 5: "SETTLEMENT"}
_HEALTH_ROLE_ORDER = (1, 2, 3, 4, 7)
_LOG = logging.getLogger(__name__)


class BackendManager:
    """本地三种模式的 SharkClient 对齐后端。"""

    def __init__(
        self,
        workspace: Any = None,
        state: RobotState | None = None,
        client_id: str = "3",
        scenario_key: str = "LabDebug",
    ) -> None:
        self.paths = RuntimePaths.discover()
        self.workspace = workspace if workspace is not None else self.paths.workspace_root
        self.state = state
        self.scenario_key = scenario_key
        self.safety = OfficialSafety(scenario_key)
        self.mqtt = RmMqttBackend(
            host="127.0.0.1", port=3333, client_id=client_id,
            mock_output=True, safety=self.safety,
        )
        self.udp = RmVideoBackend(host="127.0.0.1", port=3334)
        self.serial = RmSerialBackend(port="Stub", baud=115200, mock_writes=True, safety=self.safety)
        self.native_decoder = ContinuousMjpegDecoder("h264")
        self._native_recovery = AnnexBRecoveryGate("h264")
        # Native 0x0310 is a continuous stream.  Retaining every payload in a
        # bytearray caused unbounded memory growth during a full match even
        # though ffmpeg already consumes the bytes.  Keep counters and sequence
        # recovery state only.
        self._native_0310_bytes_since_reset = 0
        self._native_0310_last_sequence: int | None = None
        self._native_0310_dropped_chunks = 0
        self._native_0310_out_of_order_chunks = 0
        self._native_0310_recovery_dropped_chunks = 0
        self._native_0310_blocked_until_sps = True
        self._native_0310_decoder_restarts = 0
        self._native_0310_decoder_started_once = False
        self._native_next_restart_at = 0.0
        self._native_restart_backoff_s = 0.5
        self._native_failure_epoch_handled = False
        self._apply_error_count = 0
        self._last_apply_error = ""
        self._official_state_updates_count = 0
        self._mqtt_disconnect_lock_applied = False
        self._mqtt_disconnect_lock_at = 0.0
        self._mqtt_reconnected_locked_at = 0.0
        self._active_video_source = ""
        self._normal_video_source = ""
        self._hero_native_override = False
        self._estop_triggered_at = 0.0
        self._last_estop_zero_ok = False
        self._last_estop_zero_reason = "not run"
        self._input_clear_generation = 0
        self.input_clear_hook: Callable[[str], None] | None = None
        self._last_logged_stage = ""
        self.field_log = RotatingJsonlLogger(self.paths.logs_root)
        self.safety.input_clear_hook = self._request_input_clear
        self.mqtt.event_hook = self._log_backend_event
        self.udp.event_hook = self._log_backend_event
        build_commit = self._build_commit()
        self.qualification = QualificationManager(
            QualificationEvidenceStore(self.paths.evidence_root, build_commit=build_commit)
        )
        self.config = SCENARIOS.get(scenario_key, SCENARIOS["LabDebug"])
        self._apply_config(self.config)

    # ------------------------------------------------------------------
    # 场景应用
    # ------------------------------------------------------------------
    def _apply_config(self, config: Any) -> None:
        self.config = config
        self.safety.from_scenario(config)
        self.mqtt.host = config.connection.mqtt_host
        self.mqtt.port = int(config.connection.mqtt_port)
        self.mqtt.mock_output = not bool(config.safety.allow_mqtt_publish)
        self.udp.host = config.connection.udp_host
        self.udp.port = int(config.connection.udp_port)
        self.serial.port = config.connection.serial_port
        self.serial.baud = int(config.connection.serial_baud)
        self.serial.mock_writes = bool(config.safety.mock_writes)
        if self.state is not None:
            self.state.mock_simulation_enabled = config.key == "LabDebug"
            if config.key != "LabDebug" and not self.state.official_state_active:
                self._clear_mock_frontend_state(self.state)
        self.set_active_video_source(config.connection.video_source)

    @staticmethod
    def _clear_mock_frontend_state(state: RobotState) -> None:
        state.robot_rows.clear()
        state.map_robots.clear()
        state.map_markers.clear()
        state.buff_rows.clear()
        state.backend_frontend_synced = False

    def _begin_official_state(self, state: RobotState, timestamp: float) -> None:
        if not state.official_state_active:
            self._clear_mock_frontend_state(state)
        state.official_state_active = True
        state.official_state_at = max(float(state.official_state_at), float(timestamp))

    def apply_scenario(self, key: str, *, start: bool = True) -> None:
        key = key if key in SCENARIOS else "LabDebug"
        self.shutdown(restart=True)
        self.scenario_key = key
        self._hero_native_override = False
        self._normal_video_source = ""
        if self.state is not None:
            self._reset_state_for_scenario(self.state)
        config = SCENARIOS[key]
        self._apply_config(config)
        # shutdown() deliberately latches local E-stop.  A scenario switch has
        # already emitted the neutral frame and now creates a fresh fail-closed
        # safety epoch; it must not inherit the old software latch forever.
        self.safety.release_estop()
        if not start:
            return
        # 三种模式都启动 MQTT（可收裁判数据；发布按场景门控）
        self.mqtt.start()
        # UDP socket/HEVC decoder are started only when that source is selected.
        # Native 0x0310 arrives on MQTT and owns its own lazy decoder.
        if self._active_video_source in {"shark udp", "udp", "udp hevc", "hevc", "h265"}:
            self.udp.start()
        # 串口：Stub 或真实端口
        self.serial.start()

    def _reset_state_for_scenario(self, state: RobotState) -> None:
        """Discard data from the previous transport epoch before reconnecting."""

        self._clear_mock_frontend_state(state)
        state.official_state_active = False
        state.official_state_at = 0.0
        state.official_robot_health.clear()
        state.robot_positions.clear()
        state.buffs.clear()
        state.penalties.clear()
        state.active_penalty.clear()
        state.radar_detections.clear()
        state.radar_detections_at = 0.0
        state.path_plan.clear()
        state.tech_core.clear()
        state.performance_sync.clear()
        state.rune_status.clear()
        state.sentry_status.clear()
        state.dart_status.clear()
        state.sentry_ctrl_result.clear()
        state.special_mechanisms.clear()
        state.robot_statics.clear()
        state.robot_dynamics.clear()
        state.robot_modules.clear()
        state.robot_module_status.clear()
        state.injury_stats.clear()
        state.injury_stats_initialized = False
        state.projectile_damage_small_total = 0
        state.projectile_damage_large_total = 0
        state.last_projectile_hit_at = 0.0
        state.last_projectile_damage_delta = 0
        state.last_projectile_kind = ""
        state.last_projectile_killer_id = 0
        state.deploy_mode = 0
        state.deploy_status_revision += 1
        state.deploy_status_at = 0.0
        state.current_stage = "NOT_STARTED"

    def tick(self) -> None:
        if self.state is not None:
            self.safety.update_stage(self.state.current_stage)
        self.serial.tick()
        if not self.mqtt.connected and self.mqtt.disconnected_at > 0.0:
            if time.perf_counter() - self.mqtt.disconnected_at > 2.0 and not self._mqtt_disconnect_lock_applied:
                self.lock_control("MQTT disconnected for more than 2 seconds")
                self._mqtt_disconnect_lock_applied = True
                self._mqtt_disconnect_lock_at = time.perf_counter()
        elif self.mqtt.connected:
            # Reconnect clears the detection edge, but intentionally never
            # restores MATCH_ARMED.
            if self._mqtt_disconnect_lock_applied:
                self._mqtt_reconnected_locked_at = time.perf_counter()
                self.field_log.emit(
                    "mqtt_reconnected_locked",
                    disconnected_lock_at=self._mqtt_disconnect_lock_at,
                    safety_state=self.safety.control_state.value,
                )
            self._mqtt_disconnect_lock_applied = False
        self._recover_video_decoders()

    def _recover_video_decoders(self) -> None:
        """Apply decoder health timeouts off the transport callback path.

        An ffmpeg process can remain alive while producing no frame (bad GOP,
        transmitter reset) or can leave a stale last image. Both conditions
        are treated exactly like packet loss: reset the bounded Annex-B gate,
        restart with backoff, and wait for a fresh parameter-set/keyframe.
        """

        if self.udp.decode_h265 and self.udp.running and self.udp.h265_decoder is not None:
            health = self.udp.h265_decoder.health()
            if health.get("first_frame_timeout") or health.get("stale"):
                self.udp.h265_recovery.reset()
                self.udp._request_h265_restart()

        native_selected = self._active_video_source in {
            "native", "native 0x0310", "0x0310",
        } or int(getattr(self.state, "deploy_mode", 0) if self.state is not None else 0) == 1
        if not native_selected:
            return
        health = self.native_decoder.health()
        crashed = bool(
            self._native_0310_decoder_started_once
            and not self.native_decoder.available
            and self._native_0310_bytes_since_reset > 0
            and not self._native_failure_epoch_handled
        )
        if not (crashed or health.get("first_frame_timeout") or health.get("stale")):
            return
        now = time.perf_counter()
        if now < self._native_next_restart_at:
            return
        restarted = self.native_decoder.restart(clear_latest=True)
        self._native_failure_epoch_handled = bool(restarted)
        self._native_recovery.reset()
        self._native_0310_blocked_until_sps = True
        if restarted:
            self._native_0310_decoder_restarts += 1
            self._native_0310_decoder_started_once = True
            self._native_restart_backoff_s = 0.5
            self._native_next_restart_at = 0.0
        else:
            self._native_next_restart_at = now + self._native_restart_backoff_s
            self._native_restart_backoff_s = min(5.0, self._native_restart_backoff_s * 2.0)
        self.field_log.emit(
            "decoder_restart",
            source="native_0310",
            restarted=restarted,
            health=health,
        )

    def _build_commit(self) -> str:
        try:
            if self.paths.manifest_path.is_file():
                data = json.loads(self.paths.manifest_path.read_text(encoding="utf-8-sig"))
                return str(data.get("git_commit", "UNKNOWN"))
            marker = self.paths.app_root / "BUILD_COMMIT.txt"
            if marker.is_file():
                return marker.read_text(encoding="ascii").strip()
        except Exception:
            pass
        # Source runs are explicitly not field-certifiable, but binding them
        # to HEAD still makes tests and local evidence deterministic.
        try:
            import subprocess
            result = subprocess.run(
                ["git", "-C", str(self.paths.app_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "UNKNOWN"

    def _log_backend_event(self, event: str, **payload: Any) -> None:
        if event == "referee_rx" and isinstance(payload.get("payload"), bytes):
            self.field_log.referee_payload(str(payload.get("topic", "")), payload["payload"])
            return
        self.field_log.emit(event, **payload)

    def _request_input_clear(self, reason: str) -> None:
        """Clear host input whenever a control authorization epoch ends.

        The backend deliberately owns the request so disconnect and scenario
        transitions cannot depend on a particular GUI path.  The callback is
        optional for headless tests; production installs it immediately after
        constructing ``KeyboardControlBridge``.
        """

        self._input_clear_generation += 1
        hook = self.input_clear_hook
        if hook is not None:
            try:
                hook(str(reason))
            except Exception as exc:
                self.field_log.emit(
                    "input_clear_error",
                    reason=reason,
                    generation=self._input_clear_generation,
                    error=f"{type(exc).__name__}: {exc}",
                )
                return
        self.field_log.emit(
            "input_clear",
            reason=reason,
            generation=self._input_clear_generation,
            callback_installed=hook is not None,
        )

    def set_active_video_source(self, source_mode: str, *, _hero_transition: bool = False) -> None:
        normalized = str(source_mode or "").strip().lower()
        normalized = {
            "shark udp": "udp hevc",
            "udp": "udp hevc",
            "hevc": "udp hevc",
            "h265": "udp hevc",
            "native": "native 0x0310",
            "0x0310": "native 0x0310",
        }.get(normalized, normalized)
        if not _hero_transition:
            self._normal_video_source = normalized
        # DeployModeStatusSync=1 owns the video path regardless of the normal
        # CameraFeed setting. The UDP socket/decoder is stopped during that
        # authoritative interval, while Native 0x0310 remains lazy until its
        # first complete SPS/PPS/IDR is received.
        if self._hero_native_override:
            normalized = "native 0x0310"
        udp_selected = normalized in {"shark udp", "udp", "udp hevc", "hevc", "h265"}
        if (
            normalized == self._active_video_source
            and (not udp_selected or self.udp.running)
        ):
            return
        self._active_video_source = normalized
        if udp_selected and not self.udp.running:
            # The socket and decoder are both lazy. This avoids an unused HEVC
            # process and an unnecessary UDP bind in Webcam/Native sessions.
            self.udp.start()
        elif not udp_selected and self.udp.running:
            self.udp.stop()
        self.udp.set_decode_enabled(udp_selected)
        if normalized not in {"native", "native 0x0310", "0x0310"} and int(
            getattr(self.state, "deploy_mode", 0) if self.state is not None else 0
        ) != 1:
            self.native_decoder.stop()
            self._native_recovery.reset()
            self._native_0310_blocked_until_sps = True

    def sync_frontend_state(self, state: RobotState) -> None:
        """????????????????? HUD ????

        - robot_rows  ? official_robot_health + robot_statics/dynamics/modules
        - map_robots ? robot_positions?????/???????????
        - buff_rows  ? Buff ??
        ???????? mock????????? mock???????
        """
        has_real = (
            bool(state.official_robot_health)
            or bool(state.robot_positions)
            or bool(state.robot_statics)
            or bool(state.robot_dynamics)
            or bool(state.robot_modules)
        )
        if not has_real:
            return
        state.backend_frontend_synced = True

        health = [int(v) for v in state.official_robot_health[:10]]
        own_blue = int(state.robot_id) >= 100 or str(state.alliance_color).lower() == "blue"
        ally_ids = tuple(role + (100 if own_blue else 0) for role in _HEALTH_ROLE_ORDER)
        enemy_ids = tuple(role + (0 if own_blue else 100) for role in _HEALTH_ROLE_ORDER)
        health_by_id = {
            robot_id: health[index]
            for index, robot_id in enumerate(ally_ids + enemy_ids)
            if index < len(health)
        }
        observed_ids = {
            *(int(key) for key in state.robot_statics),
            *(int(key) for key in state.robot_dynamics),
            *(int(key) for key in state.robot_modules),
            *(int(item.get("robot_id", 0)) for item in state.robot_positions),
        }
        robot_ids = list(ally_ids + enemy_ids) if health else []
        robot_ids.extend(sorted(robot_id for robot_id in observed_ids if robot_id > 0 and robot_id not in robot_ids))
        rows: list[dict[str, Any]] = []
        for robot_id in robot_ids:
            base = robot_id if robot_id < 100 else robot_id - 100
            statics = state.robot_statics.get(robot_id, {})
            dynamics = state.robot_dynamics.get(robot_id, {})
            global_hp = max(0, int(health_by_id.get(robot_id, 0)))
            dynamic_hp = int(dynamics.get("current_health", 0))
            # ??? 10Hz RobotDynamicStatus??????????? 1Hz ??????
            hp = dynamic_hp if robot_id == int(state.robot_id) and dynamic_hp > 0 else global_hp or dynamic_hp
            hp_max = int(statics.get("max_health", 0)) or DEFAULT_MAX_HEALTH
            alive_state = int(statics.get("alive_state", 1))
            if alive_state == 2 or hp <= 0:
                row_state = "DEAD"
            elif robot_id == int(state.robot_id):
                row_state = "LOCAL"
            else:
                row_state = "ALIVE"
            rows.append({
                "id": robot_id,
                "name": ROBOT_ID_NAMES.get(base, "Robot"),
                "hp": max(0, hp),
                "max": max(1, hp_max),
                "state": row_state,
                "x": None,
                "y": None,
                "modules": state.robot_modules.get(robot_id, {}),
            })
        positions = {int(p.get("robot_id", -1)): p for p in state.robot_positions}
        for row in rows:
            pos = positions.get(int(row["id"]))
            if pos:
                row["x"] = float(pos.get("x", 0.0))
                row["y"] = float(pos.get("y", 0.0))
                row["yaw"] = float(pos.get("yaw", 0.0))
        state.robot_rows = rows

        if positions:
            map_robots: list[dict[str, Any]] = []
            for robot_id, pos in positions.items():
                base = robot_id if robot_id < 100 else robot_id - 100
                global_hp = max(0, int(health_by_id.get(robot_id, 0)))
                dynamic_hp = int(state.robot_dynamics.get(robot_id, {}).get("current_health", 0))
                hp = dynamic_hp if robot_id == int(state.robot_id) and dynamic_hp > 0 else global_hp or dynamic_hp
                hp_max = int(state.robot_statics.get(robot_id, {}).get("max_health", 0)) or DEFAULT_MAX_HEALTH
                map_robots.append({
                    "id": robot_id,
                    "team": "ally" if robot_id in ally_ids else "enemy",
                    "name": ROBOT_ID_NAMES.get(base, "Robot"),
                    "x": float(pos.get("x", 0.0)),
                    "y": float(pos.get("y", 0.0)),
                    "hp": max(0, hp),
                    "max": max(1, hp_max),
                    "highlight": False,
                })
            state.map_robots = map_robots

        if state.buffs:
            buff_rows: list[dict[str, Any]] = []
            for buff in state.buffs:
                buff_type = int(buff.get("buff_type", 0))
                remaining = max(0, int(buff.get("buff_left_time", 0)))
                buff_rows.append({
                    "name": BUFF_TYPE_NAMES.get(buff_type, f"Buff {buff_type}"),
                    "active": remaining > 0,
                    "remaining": remaining,
                    "buff_type": buff_type,
                    "robot_id": int(buff.get("robot_id", 0)),
                })
            state.buff_rows = buff_rows

    def set_client_id(self, robot_id: int) -> None:
        """机器人档案变更后同步 MQTT client_id 并重建连接。"""
        new_id = str(int(robot_id))
        if new_id == self.mqtt.client_id:
            return
        was_started = self.mqtt._started
        self.mqtt.stop(publish_status=False)
        self.mqtt.client_id = new_id
        if was_started:
            self.mqtt.start()

    def shutdown(self, *, restart: bool = False) -> None:
        # Best-effort neutral KMC before disconnect.  This does not replace the
        # robot-side watchdog or F12 E-stop, but prevents an ordinary app exit
        # or scenario switch from leaving the last movement key latched.
        if self.mqtt.connected and not self.mqtt.mock_output:
            self.mqtt.publish_estop_zero()
        self.safety.trigger_estop()
        self.serial.trigger_estop()
        # Scenario changes are reconnects, not process shutdowns.  Do not let a
        # retained offline status race the replacement connection.  A genuine
        # application exit still publishes the retained offline status.
        self.mqtt.stop(publish_status=not restart)
        self.udp.stop()
        self.serial.stop()
        self.native_decoder.stop()
        self._native_recovery.reset()
        self.field_log.emit("backend_shutdown", restart=restart)

    def apply_readiness(
        self,
        state: RobotState | None = None,
        *,
        live_evidence: Any = None,
    ) -> dict[str, Any]:
        """Run and store the fail-closed match audit for non-UI consumers."""

        from .readiness import audit_backend

        target = state or self.state
        if target is None:
            raise ValueError("RobotState is required for readiness audit")
        report = audit_backend(self, target, live_evidence=live_evidence)
        payload = report.as_dict()
        payload["audited_at"] = time.perf_counter()
        payload["blockers"] = [gate.key for gate in report.blockers]
        target.backend_stats["readiness"] = payload
        return payload

    def latest_video_frame(
        self,
        timeout_s: float = 0.5,
        source_mode: str = "Auto",
    ) -> tuple[Any, float, str]:
        """Return the requested/freshest backend frame on one monotonic clock.

        Explicit ``Native 0x0310`` and UDP modes remain deterministic.  ``Auto``
        compares the latest decoded native and UDP frames, which also gives
        callers a safe fallback during source transitions.
        """

        mode = str(source_mode or "Auto").strip().lower()
        want_native = mode in {"auto", "native", "native 0x0310", "0x0310"}
        want_udp = mode in {
            "auto",
            "shark udp",
            "udp",
            "udp hevc",
            "hevc",
            "h265",
        }
        candidates: list[tuple[Any, float, str]] = []
        if want_native and self.native_decoder.available:
            frame, frame_at = self.native_decoder.latest_with_timestamp(timeout_s)
            if frame is not None:
                candidates.append((frame, frame_at, "native-0x0310"))
        if want_udp:
            frame, frame_at = self.udp.latest_video_frame(timeout_s)
            if frame is not None:
                candidates.append((frame, frame_at, "udp"))
        if not candidates:
            return None, 0.0, "none"
        return max(candidates, key=lambda item: item[1])

    # ------------------------------------------------------------------
    # 下行消息 → RobotState
    # ------------------------------------------------------------------
    def apply_updates(self, state: RobotState) -> int:
        """消费解码队列并写入 RobotState；返回本次应用的消息条数。"""
        messages = self.mqtt.drain_decoded()
        count = 0
        for _topic, name, data, _ts in messages:
            try:
                # Disable synthetic state before applying the first official
                # message. This preserves a first MapClick/Buff update instead
                # of clearing it immediately after it was written.
                self._begin_official_state(state, _ts)
                self._apply_one(state, name, data)
                count += 1
                self._official_state_updates_count += 1
            except Exception as exc:
                # 单条坏消息不能中断本帧，更不能让 Qt timer 永久假死。
                self._apply_error_count += 1
                self._last_apply_error = f"{name}: {type(exc).__name__}: {exc}"
                _LOG.warning(
                    "discarding malformed referee message %s: %s",
                    name,
                    self._last_apply_error,
                )
        if messages and state is not None:
            runtime_stats = self.stats()
            for key, value in state.backend_stats.items():
                if key not in runtime_stats:
                    runtime_stats[key] = value
            state.backend_stats = runtime_stats
            self.sync_frontend_state(state)
        return count

    @staticmethod
    def _clean(data: dict[str, Any]) -> dict[str, Any]:
        """去掉协议层附加的 __present__ 元数据后再存入 state。"""
        return {k: v for k, v in data.items() if k != "__present__"}

    def _apply_one(self, state: RobotState, name: str, data: dict[str, Any]) -> None:
        present = frozenset(data.get("__present__", ()))
        economy_before = self._economy_signature(state)
        if name == "GameStatus":
            state.current_round = int(data.get("current_round", state.current_round))
            state.total_rounds = int(data.get("total_rounds", state.total_rounds))
            state.red_score = int(data.get("red_score", state.red_score))
            state.blue_score = int(data.get("blue_score", state.blue_score))
            stage = int(data.get("current_stage", 0))
            state.current_stage = _STAGE_STR.get(stage, str(stage))
            self.safety.update_stage(stage)
            if state.current_stage != self._last_logged_stage:
                self._last_logged_stage = state.current_stage
                self.field_log.emit(
                    "match_stage",
                    raw_stage=stage,
                    stage=state.current_stage,
                    round=state.current_round,
                )
            state.stage_countdown_sec = max(0, int(data.get("stage_countdown_sec", state.stage_countdown_sec)))
            state.stage_elapsed_sec = max(0, int(data.get("stage_elapsed_sec", state.stage_elapsed_sec)))
        elif name == "GlobalUnitStatus":
            state.base_health = int(data.get("base_health", state.base_health))
            state.base_status = str(data.get("base_status", state.base_status))
            state.base_shield = int(data.get("base_shield", state.base_shield))
            state.outpost_health = int(data.get("outpost_health", state.outpost_health))
            state.outpost_status = str(data.get("outpost_status", state.outpost_status))
            state.enemy_base_health = int(data.get("enemy_base_health", state.enemy_base_health))
            state.enemy_base_status = str(data.get("enemy_base_status", state.enemy_base_status))
            state.enemy_base_shield = int(data.get("enemy_base_shield", state.enemy_base_shield))
            state.enemy_outpost_health = int(data.get("enemy_outpost_health", state.enemy_outpost_health))
            state.enemy_outpost_status = str(data.get("enemy_outpost_status", state.enemy_outpost_status))
            health = [int(v) for v in data.get("robot_health", ()) if isinstance(v, int)]
            if health:
                state.official_robot_health = health
            bullets = [int(v) for v in data.get("robot_bullets", ()) if isinstance(v, int)]
            if bullets:
                state.backend_stats["robot_bullets"] = bullets
        elif name == "GlobalLogisticsStatus":
            state.remaining_economy = int(data.get("remaining_economy", state.remaining_economy))
            state.total_economy_obtained = int(data.get("total_economy_obtained", state.total_economy_obtained))
            state.tech_level = int(data.get("tech_level", state.tech_level))
            state.encryption_level = int(data.get("encryption_level", state.encryption_level))
        elif name == "RobotStaticStatus":
            if 4 in present and data["robot_id"]:
                state.robot_id = int(data["robot_id"])
                state.robot_statics[state.robot_id] = self._clean(data)
            if 8 in present and data["level"]:
                state.level = int(data["level"])
            if 9 in present and data["max_health"]:
                state.max_health = int(data["max_health"])
                state.current_health = min(state.current_health, state.max_health)
            if 10 in present and data["max_heat"]:
                state.max_heat = float(data["max_heat"])
            if 11 in present and data["heat_cooldown_rate"]:
                state.heat_cooldown_rate = float(data["heat_cooldown_rate"])
            if 12 in present and data["max_power"]:
                state.power_limit = int(data["max_power"])
            if 6 in present:
                state.performance_sync["shooter"] = int(data["performance_system_shooter"])
            if 7 in present:
                state.performance_sync["chassis"] = int(data["performance_system_chassis"])
        elif name == "RobotDynamicStatus":
            state.robot_dynamics[state.robot_id] = self._clean(data)
            state.current_health = int(data.get("current_health", state.current_health))
            state.current_heat = float(data.get("current_heat", state.current_heat))
            state.current_chassis_energy = int(data.get("current_chassis_energy", state.current_chassis_energy))
            state.current_buffer_energy = int(data.get("current_buffer_energy", state.current_buffer_energy))
            state.total_projectiles_fired = int(data.get("total_projectiles_fired", state.total_projectiles_fired))
            state.remaining_ammo = int(data.get("remaining_ammo", state.remaining_ammo))
            state.out_of_combat = bool(data.get("is_out_of_combat", state.out_of_combat))
            state.can_remote_heal = bool(data.get("can_remote_heal", state.can_remote_heal))
            state.can_remote_ammo = bool(data.get("can_remote_ammo", state.can_remote_ammo))
        elif name == "RobotModuleStatus":
            clean = self._clean(data)
            state.robot_module_status = {k: int(v) for k, v in clean.items()}
            state.robot_modules[state.robot_id] = clean
        elif name == "RobotPosition":
            self._upsert_positions(state, data)
        elif name == "Buff":
            self._upsert_buff(state, data)
        elif name == "PenaltyInfo":
            self._upsert_penalty(state, data)
        elif name == "RobotPathPlanInfo":
            state.path_plan = self._clean(data)
        elif name == "MapClickInfo":
            clean = self._clean(data)
            marker = {
                "label": chr(int(clean.get("ascii", 0))) if 32 <= int(clean.get("ascii", 0)) <= 126 else "MARK",
                "x": float(clean.get("map_x", 0.0)),
                "y": float(clean.get("map_y", 0.0)),
                "kind": "attack" if int(clean.get("type", 0)) == 1 else "marker",
                "pulse": True,
                **clean,
            }
            state.map_markers = [*state.map_markers[-15:], marker]
        elif name == "RadarInfoToClient":
            state.radar_detections = [dict(r) for r in data.get("robots", ())]
            state.radar_detections_at = time.perf_counter()
        elif name == "TechCoreMotionStateSync":
            state.tech_core = self._clean(data)
        elif name == "RobotPerformanceSelectionSync":
            clean = self._clean(data)
            state.performance_sync = {k: int(v) for k, v in clean.items()}
        elif name == "DeployModeStatusSync":
            next_status = 1 if int(data.get("status", 0)) else 0
            if next_status != int(state.deploy_mode):
                state.deploy_status_revision += 1
            state.deploy_mode = next_status
            state.deploy_status_at = time.perf_counter()
            if bool(next_status) != self._hero_native_override:
                self._hero_native_override = bool(next_status)
                if self._hero_native_override:
                    self.set_active_video_source("Native 0x0310", _hero_transition=True)
                else:
                    self.set_active_video_source(
                        self._normal_video_source or self.config.connection.video_source,
                        _hero_transition=True,
                    )
                self.field_log.emit(
                    "hero_video_source",
                    deployed=bool(next_status),
                    active_source=self._active_video_source,
                )
        elif name == "RuneStatusSync":
            state.rune_status = self._clean(data)
            state.energy_rune_phase = _RUNE_PHASE.get(int(data.get("rune_status", 1)), "INACTIVE")
            state.energy_rune_progress = int(float(data.get("average_rings", 0)) * 100)
        elif name == "SentryStatusSync":
            state.sentry_status = self._clean(data)
        elif name == "DartSelectTargetStatusSync":
            state.dart_status = self._clean(data)
        elif name == "SentryCtrlResult":
            state.sentry_ctrl_result = self._clean(data)
        elif name == "AirSupportStatusSync":
            state.air_support_active = int(data.get("airsupport_status", 0)) == 1
            state.air_support_free_time_sec = int(data.get("left_time", 0))
            state.air_support_cost_coins = int(data.get("cost_coins", 0))
        elif name == "GlobalSpecialMechanism":
            ids = [int(v) for v in data.get("mechanism_id", ())]
            times = [int(v) for v in data.get("mechanism_time_sec", ())]
            state.special_mechanisms = [
                {"mechanism_id": i, "time_sec": t}
                for i, t in zip(ids, times)
            ]
        elif name == "Event":
            state.backend_stats["last_event"] = {
                "event_id": int(data.get("event_id", 0)),
                "param": data.get("param", ""),
            }
        elif name == "CustomByteBlock":
            block = bytes(data.get("data", b""))
            state.backend_stats["last_custom_block"] = {
                "len": len(block),
            }
            telemetry = parse_vehicle_telemetry(block)
            if telemetry is not None:
                previous_sequence = int(state.native_telemetry_frame_seq)
                status_upper = telemetry.status_text.upper()
                # Treat a short backward jump as a producer restart/replay,
                # but do not invalidate calibration at the natural uint32
                # wrap from 0xffffffff to zero.
                sequence_restarted = bool(
                    previous_sequence > 0
                    and telemetry.frame_seq < previous_sequence
                    and (previous_sequence - telemetry.frame_seq) < 0x80000000
                )
                localisation_reset = bool(
                    sequence_restarted
                    or any(
                        marker in status_upper
                        for marker in (
                            "LOCALIZATION LOST",
                            "LOCALISATION LOST",
                            "RELOCALIZING",
                            "RELOCALISING",
                            "POSE RESET",
                            "MAP RESET",
                        )
                    )
                )
                state.native_telemetry_at = time.perf_counter()
                state.native_telemetry_unix_ms = telemetry.unix_ms
                state.native_telemetry_frame_seq = telemetry.frame_seq
                state.native_camera_online = telemetry.camera_online
                state.native_gimbal_online = telemetry.gimbal_online
                state.native_gimbal_mode = telemetry.gimbal_mode_name
                state.native_bullet_count = telemetry.bullet_count
                state.native_bullet_speed = telemetry.bullet_speed
                state.native_yaw_deg = telemetry.yaw
                state.native_yaw_velocity = telemetry.yaw_vel
                state.native_pitch_deg = telemetry.pitch
                state.native_pitch_velocity = telemetry.pitch_vel
                state.native_quaternion = telemetry.quaternion
                state.native_status_text = telemetry.status_text
                if localisation_reset:
                    state.hero_lob_relocalization_valid = False
                    state.hero_lob_armed = False
                    state.hero_lob_status = "BLOCKED: relocalization invalidated by telemetry reset"
                state.backend_stats["native_telemetry"] = {
                    "version": telemetry.version,
                    "frame_seq": telemetry.frame_seq,
                    "camera_online": telemetry.camera_online,
                    "gimbal_online": telemetry.gimbal_online,
                    "gimbal_mode": telemetry.gimbal_mode_name,
                    "bullet_speed": telemetry.bullet_speed,
                    "status": telemetry.status_text,
                }
            else:
                video_chunk = parse_video_0310_chunk(block)
                if video_chunk is not None:
                    native_selected = self._active_video_source in {
                        "native", "native 0x0310", "0x0310",
                    } or int(getattr(state, "deploy_mode", 0)) == 1
                    if not native_selected:
                        # An unselected Native stream must not wake ffmpeg or
                        # retain a partial recovery epoch in the background.
                        # Selecting Native later waits for fresh SPS/PPS/IDR.
                        self._native_0310_last_sequence = None
                        self._native_0310_blocked_until_sps = True
                        self._native_recovery.reset()
                        return
                    # 0x0310 原生 H.264 流：不保留无限增长的历史码流。
                    # reset 或向前序号缺口后停止喂流，直到下一个 Annex-B
                    # SPS；这与 rm-native-viewer 的正式链路恢复策略一致，
                    # 也避免在 UI tick 内同步 stop/restart ffmpeg。重复/迟到
                    # 分块直接丢弃，防止同一 payload 破坏 NAL 边界。
                    modulus = max(1, int(video_chunk.sequence_modulus))
                    sequence = int(video_chunk.sequence) % modulus
                    accept_payload = True
                    if video_chunk.reset:
                        self._native_0310_bytes_since_reset = 0
                        self._native_0310_last_sequence = None
                        self._native_0310_blocked_until_sps = True
                        self._native_failure_epoch_handled = False
                        self._native_recovery.reset()
                    elif self._native_0310_last_sequence is not None:
                        expected = (self._native_0310_last_sequence + 1) % modulus
                        distance = (sequence - expected) % modulus
                        if distance:
                            if distance < modulus // 2:
                                self._native_0310_dropped_chunks += distance
                                self._native_0310_blocked_until_sps = True
                                self._native_failure_epoch_handled = False
                                self._native_recovery.reset()
                            else:
                                self._native_0310_out_of_order_chunks += 1
                                accept_payload = False

                    wrote = False
                    payload_to_write = b""
                    if accept_payload:
                        self._native_0310_bytes_since_reset += len(video_chunk.payload)
                        self._native_0310_last_sequence = sequence
                        if (
                            self._native_0310_decoder_started_once
                            and not self.native_decoder.available
                        ):
                            # A crashed decoder has lost its SPS/PPS parser
                            # state even if transport sequence is continuous.
                            self._native_0310_blocked_until_sps = True
                            if not self._native_failure_epoch_handled:
                                self._native_recovery.reset()
                        payload_to_write = self._native_recovery.feed(video_chunk.payload) or b""
                        self._native_0310_blocked_until_sps = self._native_recovery.blocked
                        if not payload_to_write:
                            self._native_0310_recovery_dropped_chunks += 1

                    if payload_to_write:
                        if not self.native_decoder.available:
                            if self._native_0310_decoder_started_once:
                                self._native_0310_decoder_restarts += 1
                            started = self.native_decoder.start()
                            self._native_0310_decoder_started_once = bool(
                                self._native_0310_decoder_started_once or started
                            )
                            if started:
                                self._native_failure_epoch_handled = False
                        if self.native_decoder.available:
                            wrote = self.native_decoder.write(payload_to_write)
                            if not wrote:
                                # Yield briefly to the dedicated stdin writer.
                                # The MQTT callback remains bounded (<10 ms),
                                # while a synthetic burst cannot overflow a
                                # queue that is sized for live 0x0310 cadence.
                                deadline = time.perf_counter() + 0.010
                                while not wrote and time.perf_counter() < deadline:
                                    time.sleep(0.0005)
                                    wrote = self.native_decoder.write(payload_to_write)
                        if not wrote:
                            # A full/non-running decoder queue is equivalent to
                            # a transport gap.  Resume only from a future SPS.
                            self._native_0310_blocked_until_sps = True
                            self._native_failure_epoch_handled = False
                            self._native_recovery.reset()
                    state.backend_stats["native_video_0310"] = {
                        "sequence": sequence,
                        "reset": video_chunk.reset,
                        "payload_len": len(video_chunk.payload),
                        "bytes_since_reset": self._native_0310_bytes_since_reset,
                        "dropped_chunks": self._native_0310_dropped_chunks,
                        "out_of_order_chunks": self._native_0310_out_of_order_chunks,
                        "recovery_dropped_chunks": self._native_0310_recovery_dropped_chunks,
                        "blocked_until_sps": self._native_0310_blocked_until_sps,
                        "decoder_restarts": self._native_0310_decoder_restarts,
                        "payload_accepted": bool(payload_to_write),
                        "payload_input_len": len(video_chunk.payload),
                        "payload_decoder_len": len(payload_to_write),
                        "payload_written": wrote,
                        "payload_queued": wrote,
                        "decoder_input_queue": self.native_decoder.input_queue_depth(),
                        "decoder_input_dropped": self.native_decoder.input_chunks_dropped,
                        "decoder_ready": self.native_decoder.available,
                        "decoded_frames": self.native_decoder.frames_decoded,
                    }
                    # The decoder thread advances independently after this
                    # message snapshot; stats() is the authoritative live
                    # source for decoded-frame counters.
        elif name == "RobotInjuryStat":
            clean = self._clean(data)
            killer_id = int(data.get("killer_id", 0))
            state.injury_stats[killer_id] = clean
            small_total = max(0, int(data.get("small_projectile_damage", 0)))
            large_total = max(0, int(data.get("large_projectile_damage", 0)))
            if state.injury_stats_initialized:
                # Cumulative counters can reset after respawn/reconnect.  A
                # backwards jump establishes a new baseline and must never be
                # interpreted as an enormous fresh hit.
                counters_monotonic = bool(
                    small_total >= state.projectile_damage_small_total
                    and large_total >= state.projectile_damage_large_total
                )
                if counters_monotonic:
                    small_delta = small_total - state.projectile_damage_small_total
                    large_delta = large_total - state.projectile_damage_large_total
                    damage_delta = small_delta + large_delta
                    if damage_delta > 0:
                        state.projectile_hit_revision += 1
                        state.last_projectile_hit_at = time.perf_counter()
                        state.last_projectile_damage_delta = damage_delta
                        state.last_projectile_kind = (
                            "17mm+42mm"
                            if small_delta > 0 and large_delta > 0
                            else ("42mm" if large_delta > 0 else "17mm")
                        )
                        state.last_projectile_killer_id = killer_id
            else:
                # RobotInjuryStat is a cumulative 1 Hz report.  Never trigger
                # an automatic action from the first sample after startup.
                state.injury_stats_initialized = True
            state.projectile_damage_small_total = small_total
            state.projectile_damage_large_total = large_total
        elif name == "RobotRespawnStatus":
            state.respawn_pending = bool(data.get("is_pending_respawn", state.respawn_pending))
            total = max(1, int(data.get("total_respawn_progress", 1)))
            current = int(data.get("current_respawn_progress", 0))
            state.respawn_progress = min(1.0, current / total)
            state.respawn_can_free = bool(data.get("can_free_respawn", state.respawn_can_free))
            state.respawn_gold_cost = int(data.get("gold_cost_for_respawn", state.respawn_gold_cost))
            state.respawn_can_pay = bool(data.get("can_pay_for_respawn", state.respawn_can_pay))

        # Economy confirmation is driven by an actual relevant field change,
        # not by the arrival count of unrelated team messages.  This prevents
        # a teammate's purchase from acknowledging our pending request.
        if self._economy_signature(state) != economy_before:
            state.economy_status_revision = int(state.economy_status_revision) + 1
            state.economy_command_status = ""

    @staticmethod
    def _economy_signature(state: RobotState) -> tuple[Any, ...]:
        return (
            int(state.remaining_economy),
            int(state.remaining_ammo),
            int(state.current_health),
            bool(state.respawn_pending),
            bool(state.air_support_active),
        )

    def _upsert_positions(self, state: RobotState, data: dict[str, Any]) -> None:
        robot_id = int(data.get("robot_id", 0))
        positions = list(state.robot_positions)
        clean = self._clean(data)
        for index, item in enumerate(positions):
            if int(item.get("robot_id", -1)) == robot_id:
                positions[index] = clean
                break
        else:
            positions.append(clean)
        state.robot_positions = positions[-16:]

    def _upsert_buff(self, state: RobotState, data: dict[str, Any]) -> None:
        key = (int(data.get("robot_id", 0)), int(data.get("buff_type", 0)))
        buffs = list(state.buffs)
        clean = self._clean(data)
        for index, item in enumerate(buffs):
            if (int(item.get("robot_id", 0)), int(item.get("buff_type", 0))) == key:
                buffs[index] = clean
                break
        else:
            buffs.append(clean)
        state.buffs = buffs[-24:]

    def _upsert_penalty(self, state: RobotState, data: dict[str, Any]) -> None:
        penalty_type = int(data.get("penalty_type", 0))
        penalties = list(state.penalties)
        clean = self._clean(data)
        for index, item in enumerate(penalties):
            if int(item.get("penalty_type", -1)) == penalty_type:
                penalties[index] = clean
                break
        else:
            penalties.append(clean)
        state.penalties = penalties[-8:]
        state.active_penalty = clean

    # ------------------------------------------------------------------
    # 上行指令（对齐 SharkClient MqttCommandPanel 全部命令）
    # ------------------------------------------------------------------
    def _publish(
        self,
        name: str,
        payload: bytes,
        *,
        intent: str = "control",
        qualification_token: str | None = None,
    ) -> tuple[bool, str]:
        return self.mqtt.publish_named(
            name,
            payload,
            qos=1,
            intent=intent,
            qualification_token=qualification_token,
        )

    def publish_keyboard_mouse(self, mouse_x=0, mouse_y=0, mouse_z=0, *,
                               left=False, right=False, keyboard_value=0, mid=False,
                               qualification_token: str | None = None) -> tuple[bool, str]:
        return self._publish(
            "KeyboardMouseControl",
            proto.encode_keyboard_mouse_control(
                mouse_x, mouse_y, mouse_z, left, right, keyboard_value, mid
            ),
            intent="core_kmc",
            qualification_token=qualification_token,
        )

    def publish_custom_control(self, data: bytes, *, intent: str = "control") -> tuple[bool, str]:
        return self._publish("CustomControl", proto.encode_custom_control(data), intent=intent)

    def publish_qualification_custom_control(
        self,
        data: bytes,
        *,
        intent: str,
        qualification_token: str,
    ) -> tuple[bool, str]:
        """Qualification-only CustomControl path bound to a live token.

        Normal vision/spin publishers intentionally do not accept tokens, so a
        UI toggle or config value cannot smuggle qualification privileges into
        ordinary operation.
        """

        if intent not in {"prm1_vision", "prm1_spin"}:
            return False, "unsupported qualification CustomControl intent"
        return self._publish(
            "CustomControl",
            proto.encode_custom_control(data),
            intent=intent,
            qualification_token=qualification_token,
        )

    def publish_vision_control(
        self, *, sequence: int, yaw_deg: float, pitch_deg: float,
        target_id: int = 0, tracking: bool = False,
    ) -> tuple[bool, str]:
        payload = proto.encode_vision_control_payload(
            sequence=sequence,
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
            target_id=target_id,
            tracking=tracking,
            fire=False,
        )
        return self.publish_custom_control(payload, intent="prm1_vision")

    def publish_spin_control(
        self, *, sequence: int, enabled: bool, direction: str = "Auto",
        speed_dps: float = 420.0, power_guard: bool = True,
    ) -> tuple[bool, str]:
        """Publish the reviewed team spin schema through official CustomControl."""
        payload = proto.encode_spin_control_payload(
            sequence=sequence,
            enabled=enabled,
            direction=direction,
            speed_dps=speed_dps,
            power_guard=power_guard,
        )
        return self.publish_custom_control(payload, intent="prm1_spin")

    def trigger_estop(self) -> tuple[bool, str]:
        """先尽力发送全零 KMC，再锁死所有上行；断网时仍立即本地锁止。"""
        zero_result = self.mqtt.publish_estop_zero()
        self._last_estop_zero_ok, self._last_estop_zero_reason = zero_result
        self._estop_triggered_at = time.perf_counter()
        self.safety.trigger_estop()
        self.serial.trigger_estop()
        self.field_log.emit(
            "estop",
            zero_publish_ok=self._last_estop_zero_ok,
            zero_publish_reason=self._last_estop_zero_reason,
        )
        return zero_result

    def record_firmware_zero_observation(self, observed_at: float | None = None) -> float:
        """Record a physical observer/test fixture's neutral-output timestamp."""

        if self._estop_triggered_at <= 0.0:
            raise ValueError("trigger E-stop before recording firmware zero")
        elapsed_ms = max(
            0.0,
            ((time.perf_counter() if observed_at is None else float(observed_at)) - self._estop_triggered_at)
            * 1000.0,
        )
        if self.state is not None:
            self.state.backend_stats["firmware_zero_observed_ms"] = elapsed_ms
        self.field_log.emit("firmware_zero_observed", elapsed_ms=elapsed_ms)
        return elapsed_ms

    def release_estop(self) -> None:
        self.serial.release_estop()
        self.safety.release_estop()

    def lock_control(self, reason: str = "operator lock") -> None:
        self.safety.lock_control(reason)
        self.field_log.emit("control_lock", reason=reason)

    def begin_qualification(self, intents: Any, *, ttl_s: float = 30.0):
        token = self.safety.begin_qualification(intents, ttl_s=ttl_s)
        self.field_log.emit(
            "qualification_begin",
            intents=sorted(token.intents),
            expires_at=token.expires_at,
        )
        return token

    def arm_match_control(
        self,
        *,
        robot_id: str | None = None,
        firmware_hash: str,
        match_mode: str | None = None,
        video_source: str | None = None,
    ) -> tuple[bool, str]:
        # Evidence must be minted over the real transport. A mock bridge
        # reports every publish as OK, so a LabDebug/mock session could
        # otherwise produce valid-looking KMC/E-stop evidence without a
        # single byte reaching the referee system.
        if self.mqtt.mock_output or not self.safety.allow_mqtt_publish:
            self.safety.lock_control("arm requires a real MQTT output scenario (mock evidence is not signable)")
            return False, self.safety.last_reason
        if not self.mqtt.connected:
            self.safety.lock_control("arm requires a live MQTT referee connection")
            return False, self.safety.last_reason
        ready, reason = self.qualification.verified_core_ready()
        if not ready:
            self.safety.lock_control(reason)
            return False, reason
        session = self.qualification.session
        if session is None:
            self.safety.lock_control("qualification session disappeared")
            return False, self.safety.last_reason
        identity_ready, identity_reason = self.qualification.identity_matches(
            robot_id=str(
                robot_id
                if robot_id is not None
                else getattr(self.state, "robot_id", session.robot_id)
            ),
            firmware_hash=firmware_hash,
            match_mode=match_mode or getattr(self.state, "match_mode", session.match_mode),
            video_source=video_source or self._canonical_readiness_video_source(),
        )
        if not identity_ready:
            self.safety.lock_control(identity_reason)
            return False, identity_reason
        capabilities = self.qualification.capabilities()
        try:
            self.safety.arm_match(capabilities)
        except ValueError as exc:
            return False, str(exc)
        self.field_log.emit("control_arm", capabilities=sorted(capabilities))
        return True, "MATCH_ARMED"

    def _canonical_readiness_video_source(self) -> str:
        source = str(self._active_video_source).strip().lower()
        if source in {"native", "native 0x0310", "0x0310"}:
            return "native_0310"
        if source in {"shark udp", "udp", "udp hevc", "hevc", "h265"}:
            return "udp"
        return ""

    def publish_map_click_cmd(self, *, is_send_all=0, robot_id=b"", mode=1,
                              enemy_id=0, ascii_code=0, mark_type=1,
                              map_x=0.0, map_y=0.0) -> tuple[bool, str]:
        return self._publish("MapClickCmd", proto.encode_map_click_cmd(
            is_send_all, robot_id, mode, enemy_id, ascii_code, mark_type, map_x, map_y))

    # 旧内部调用兼容，但不再发布已废弃/方向错误的 topic。
    publish_map_click_notify = publish_map_click_cmd

    def publish_assembly_command(self, operation: int, difficulty: int) -> tuple[bool, str]:
        return self._publish("AssemblyCommand", proto.encode_assembly_command(operation, difficulty))

    def publish_robot_performance(self, shooter: int, chassis: int,
                                  sentry_control: int = 0) -> tuple[bool, str]:
        return self._publish("RobotPerformanceSelectionCommand",
                             proto.encode_robot_performance_selection_command(shooter, chassis, sentry_control))

    def publish_hero_deploy(self, mode: int) -> tuple[bool, str]:
        return self._publish(
            "HeroDeployModeEventCommand",
            proto.encode_hero_deploy_mode_event_command(mode),
            intent="hero",
        )

    def publish_rune_activate(self, activate: int) -> tuple[bool, str]:
        return self._publish("RuneActivateCommand", proto.encode_rune_activate_command(activate))

    def publish_dart_command(self, target_id: int, open_gate: bool, launch_confirm: bool) -> tuple[bool, str]:
        return self._publish("DartCommand", proto.encode_dart_command(target_id, open_gate, launch_confirm))

    def publish_sentry_command(self, command_id: int) -> tuple[bool, str]:
        return self._publish("SentryCtrlCommand", proto.encode_sentry_ctrl_command(command_id))

    def publish_common_command(self, cmd_type: int, param: int) -> tuple[bool, str]:
        return self._publish(
            "CommonCommand", proto.encode_common_command(cmd_type, param), intent="economy"
        )

    def publish_air_support(self, command_id: int) -> tuple[bool, str]:
        return self._publish("AirSupportCommand", proto.encode_air_support_command(command_id))

    # ------------------------------------------------------------------
    # 工具：从本地 RobotProfile 设置推导官方性能体系取值并发布
    # ------------------------------------------------------------------
    @staticmethod
    def performance_values(registry: Any) -> dict[str, int]:
        profile = registry.get("RobotProfile")
        if profile is None:
            return {"shooter": 0, "chassis": 0, "sentry_control": 0}
        role = str(getattr(profile.get_setting("Role"), "value", "") or "")
        hero_type = str(getattr(profile.get_setting("Hero Type"), "value", "") or "")
        shooter = str(getattr(profile.get_setting("Infantry Shooter"), "value", "") or "")
        chassis = str(getattr(profile.get_setting("Infantry Chassis"), "value", "") or "")
        sentry = str(getattr(profile.get_setting("Sentinel Control"), "value", "") or "")
        if role == "Hero":
            return {
                "shooter": HERO_MELEE if hero_type == "Melee" else HERO_RANGE,
                "chassis": HERO_MELEE if hero_type == "Melee" else HERO_RANGE,
                "sentry_control": 0,
            }
        if role.startswith("Infantry"):
            return {
                "shooter": SHOOTER_BURST if shooter == "Burst" else SHOOTER_COOLING,
                "chassis": CHASSIS_POWER if chassis == "Power" else CHASSIS_HEALTH,
                "sentry_control": 0,
            }
        if role == "Sentinel":
            return {
                "shooter": 0, "chassis": 0,
                "sentry_control": SENTRY_SEMI_AUTO if sentry == "SemiAuto" else SENTRY_AUTOMATIC,
            }
        return {"shooter": 0, "chassis": 0, "sentry_control": 0}

    def publish_performance_from_registry(self, registry: Any) -> tuple[bool, str]:
        values = self.performance_values(registry)
        return self.publish_robot_performance(
            values["shooter"], values["chassis"], values["sentry_control"])

    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        native_at = self.native_decoder.latest_timestamp()
        native_width, native_height = self.native_decoder.frame_size()
        if self.state is not None:
            native_info = self.state.backend_stats.get("native_video_0310")
            if isinstance(native_info, dict):
                native_info["decoded_frames"] = self.native_decoder.frames_decoded
                native_info["decoder_ready"] = self.native_decoder.available
                native_info["decoded_frame_at"] = native_at
        return {
            "scenario": self.scenario_key,
            "safety": self.safety.stats(),
            "mqtt": self.mqtt.stats(),
            "udp": self.udp.stats(),
            "serial": self.serial.stats(),
            "native_0310": {
                "decoder_ready": self.native_decoder.available,
                "decoded_connected": bool(
                    native_at > 0.0 and time.perf_counter() - native_at <= 2.0
                ),
                "decoded_frames": self.native_decoder.frames_decoded,
                "continuous_decoded_seconds": self.native_decoder.continuous_decoded_seconds,
                "decoded_frame_at": native_at,
                "output_width": native_width,
                "output_height": native_height,
                "bytes_since_reset": self._native_0310_bytes_since_reset,
                "dropped_chunks": self._native_0310_dropped_chunks,
                "out_of_order_chunks": self._native_0310_out_of_order_chunks,
                "recovery_dropped_chunks": self._native_0310_recovery_dropped_chunks,
                "blocked_until_sps": self._native_0310_blocked_until_sps,
                "decoder_restarts": self._native_0310_decoder_restarts,
                "input_queue": self.native_decoder.input_queue_depth(),
                "input_dropped": self.native_decoder.input_chunks_dropped,
                "input_chunks_written": self.native_decoder.input_chunks_written,
                "input_bytes_written": self.native_decoder.input_bytes_written,
                "last_error": self.native_decoder.last_error,
                "decoder_health": self.native_decoder.health(),
            },
            "qualification": {
                "session_id": self.qualification.session.session_id if self.qualification.session else "",
                "core_ready": self.qualification.core_ready()[0],
                "reason": self.qualification.core_ready()[1],
                "capabilities": sorted(self.qualification.capabilities()),
                "evidence_error": self.qualification.store.last_error,
            },
            "safety_evidence": {
                "estop_triggered_at": self._estop_triggered_at,
                "estop_zero_publish_ok": self._last_estop_zero_ok,
                "estop_zero_publish_reason": self._last_estop_zero_reason,
                "mqtt_disconnect_lock_at": self._mqtt_disconnect_lock_at,
                "mqtt_reconnected_locked_at": self._mqtt_reconnected_locked_at,
                "input_clear_generation": self._input_clear_generation,
            },
            "field_log": {
                "path": str(self.field_log.path),
                "last_error": self.field_log.last_error,
            },
            "message_apply": {
                "errors": self._apply_error_count,
                "last_error": self._last_apply_error,
                "updates": self._official_state_updates_count,
            },
        }
