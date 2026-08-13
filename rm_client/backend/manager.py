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
import time
from typing import Any

from ..model import RobotState
from ..native_viewer_telemetry import (
    find_h264_sps_offset,
    parse_vehicle_telemetry,
    parse_video_0310_chunk,
)
from ..scenarios import SCENARIOS
from . import protocol as proto
from .mqtt_backend import RmMqttBackend
from .safety import OfficialSafety
from .serial_backend import RmSerialBackend
from .video_backend import ContinuousMjpegDecoder, RmVideoBackend

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
        self.workspace = workspace
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
        self._apply_error_count = 0
        self._last_apply_error = ""
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

    def apply_scenario(self, key: str, *, start: bool = True) -> None:
        key = key if key in SCENARIOS else "LabDebug"
        self.shutdown(restart=True)
        self.scenario_key = key
        config = SCENARIOS[key]
        self._apply_config(config)
        # shutdown() deliberately latches local E-stop.  A scenario switch has
        # already emitted the neutral frame and now creates a fresh fail-closed
        # safety epoch; it must not inherit the old software latch forever.
        self.release_estop()
        if not start:
            return
        # 三种模式都启动 MQTT（可收裁判数据；发布按场景门控）
        self.mqtt.start()
        # 三种模式都监听 UDP 图传（codec 检测 + MJPEG 解码 + 统计）
        self.udp.start()
        # 串口：Stub 或真实端口
        self.serial.start()

    def tick(self) -> None:
        if self.state is not None:
            self.safety.update_stage(self.state.current_stage)
        self.serial.tick()

    def sync_frontend_state(self, state: RobotState) -> None:
        """????????????????? HUD ????

        - robot_rows  ? official_robot_health + robot_statics/dynamics/modules
        - map_robots ? robot_positions?????/???????????
        - buff_rows  ? Buff ??
        ???????? mock????????? mock???????
        """
        has_real = bool(state.official_robot_health) or bool(state.robot_positions) or bool(state.robot_statics)
        if not has_real:
            state.backend_frontend_synced = False
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
        robot_ids = list(ally_ids + enemy_ids)
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
            "synthetic",
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
                self._apply_one(state, name, data)
                count += 1
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
                    elif self._native_0310_last_sequence is not None:
                        expected = (self._native_0310_last_sequence + 1) % modulus
                        distance = (sequence - expected) % modulus
                        if distance:
                            if distance < modulus // 2:
                                self._native_0310_dropped_chunks += distance
                                self._native_0310_blocked_until_sps = True
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
                        if self._native_0310_blocked_until_sps:
                            sps_offset = find_h264_sps_offset(video_chunk.payload)
                            if sps_offset is None:
                                self._native_0310_recovery_dropped_chunks += 1
                            else:
                                payload_to_write = video_chunk.payload[sps_offset:]
                                self._native_0310_blocked_until_sps = False
                        else:
                            payload_to_write = video_chunk.payload

                    if payload_to_write:
                        if not self.native_decoder.available:
                            if self._native_0310_decoder_started_once:
                                self._native_0310_decoder_restarts += 1
                            started = self.native_decoder.start()
                            self._native_0310_decoder_started_once = bool(
                                self._native_0310_decoder_started_once or started
                            )
                        if self.native_decoder.available:
                            wrote = self.native_decoder.write(payload_to_write)
                        if not wrote:
                            # A full/non-running decoder queue is equivalent to
                            # a transport gap.  Resume only from a future SPS.
                            self._native_0310_blocked_until_sps = True
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
    def _publish(self, name: str, payload: bytes) -> tuple[bool, str]:
        return self.mqtt.publish_named(name, payload, qos=1)

    def publish_keyboard_mouse(self, mouse_x=0, mouse_y=0, mouse_z=0, *,
                               left=False, right=False, keyboard_value=0, mid=False) -> tuple[bool, str]:
        return self._publish("KeyboardMouseControl", proto.encode_keyboard_mouse_control(
            mouse_x, mouse_y, mouse_z, left, right, keyboard_value, mid))

    def publish_custom_control(self, data: bytes) -> tuple[bool, str]:
        return self._publish("CustomControl", proto.encode_custom_control(data))

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
        return self.publish_custom_control(payload)

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
        return self.publish_custom_control(payload)

    def trigger_estop(self) -> tuple[bool, str]:
        """先尽力发送全零 KMC，再锁死所有上行；断网时仍立即本地锁止。"""
        zero_result = self.mqtt.publish_estop_zero()
        self.safety.trigger_estop()
        self.serial.trigger_estop()
        return zero_result

    def release_estop(self) -> None:
        self.serial.release_estop()
        self.safety.release_estop()

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
        return self._publish("HeroDeployModeEventCommand", proto.encode_hero_deploy_mode_event_command(mode))

    def publish_rune_activate(self, activate: int) -> tuple[bool, str]:
        return self._publish("RuneActivateCommand", proto.encode_rune_activate_command(activate))

    def publish_dart_command(self, target_id: int, open_gate: bool, launch_confirm: bool) -> tuple[bool, str]:
        return self._publish("DartCommand", proto.encode_dart_command(target_id, open_gate, launch_confirm))

    def publish_sentry_command(self, command_id: int) -> tuple[bool, str]:
        return self._publish("SentryCtrlCommand", proto.encode_sentry_ctrl_command(command_id))

    def publish_common_command(self, cmd_type: int, param: int) -> tuple[bool, str]:
        return self._publish("CommonCommand", proto.encode_common_command(cmd_type, param))

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
            },
            "message_apply": {
                "errors": self._apply_error_count,
                "last_error": self._last_apply_error,
            },
        }
