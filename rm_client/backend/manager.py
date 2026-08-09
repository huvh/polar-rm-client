"""??????? SharkClient ???????????????

LabDebug / CampusSimulation / OfficialEvent ???
- MQTT??????????????????????LabDebug mock?
- UDP????????codec ???MJPEG ?????
- ???Stub ??? PySerial + ???? + ??
- ????????10Hz + ?????? + ???

??????????????? RobotState??? UI ?????????????
?????? 7 ????????????
"""

from __future__ import annotations

import time
from typing import Any

from ..model import RobotState
from ..scenarios import SCENARIOS
from . import protocol as proto
from .mqtt_backend import RmMqttBackend
from .safety import OfficialSafety
from .serial_backend import RmSerialBackend
from .video_backend import RmVideoBackend

# ??????????? messages.proto ? Shark RoboModeSettings?
HERO_MELEE = 3
HERO_RANGE = 4
SHOOTER_COOLING = 1
SHOOTER_BURST = 2
CHASSIS_HEALTH = 1
CHASSIS_POWER = 2
SENTRY_AUTOMATIC = 1
SENTRY_SEMI_AUTO = 2

_RUNE_PHASE = {1: "INACTIVE", 2: "ACTIVATING", 3: "ACTIVE"}
_STAGE_STR = {0: "NOT_STARTED", 1: "PREPARE", 2: "SELF_CHECK", 3: "COUNTDOWN", 4: "MATCH", 5: "SETTLEMENT"}


class BackendManager:
    """??????? SharkClient ?????"""

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
        self.config = SCENARIOS.get(scenario_key, SCENARIOS["LabDebug"])
        self._apply_config(self.config)

    # ------------------------------------------------------------------
    # ????
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

    def apply_scenario(self, key: str) -> None:
        key = key if key in SCENARIOS else "LabDebug"
        self.shutdown()
        self.scenario_key = key
        config = SCENARIOS[key]
        self._apply_config(config)
        # ??????? MQTT????????????????
        self.mqtt.start()
        # ??????? UDP ???codec ?? + MJPEG ?? + ???
        self.udp.start()
        # ???Stub ?????
        self.serial.start()

    def tick(self) -> None:
        if self.state is not None:
            self.safety.update_stage(self.state.current_stage)
        self.serial.tick()

    def shutdown(self) -> None:
        self.mqtt.stop()
        self.udp.stop()
        self.serial.stop()

    # ------------------------------------------------------------------
    # ???? ? RobotState
    # ------------------------------------------------------------------
    def apply_updates(self, state: RobotState) -> int:
        """????????? RobotState?????????????"""
        messages = self.mqtt.drain_decoded()
        count = 0
        for _topic, name, data, _ts in messages:
            count += 1
            self._apply_one(state, name, data)
        if messages and state is not None:
            state.backend_stats = self.stats()
        return count

    def _apply_one(self, state: RobotState, name: str, data: dict[str, Any]) -> None:
        if name == "GameStatus":
            state.current_round = int(data.get("current_round", state.current_round))
            state.total_rounds = int(data.get("total_rounds", state.total_rounds))
            state.red_score = int(data.get("red_score", state.red_score))
            state.blue_score = int(data.get("blue_score", state.blue_score))
            stage = int(data.get("current_stage", 0))
            state.current_stage = _STAGE_STR.get(stage, str(stage))
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
        elif name == "GlobalLogisticsStatus":
            state.remaining_economy = int(data.get("remaining_economy", state.remaining_economy))
            state.total_economy_obtained = int(data.get("total_economy_obtained", state.total_economy_obtained))
            state.tech_level = int(data.get("tech_level", state.tech_level))
            state.encryption_level = int(data.get("encryption_level", state.encryption_level))
        elif name == "RobotStaticStatus":
            state.robot_id = int(data.get("robot_id", state.robot_id))
            state.level = int(data.get("level", state.level))
            if data.get("max_health"):
                state.max_health = int(data["max_health"])
                state.current_health = min(state.current_health, state.max_health)
            if data.get("max_heat"):
                state.max_heat = float(data["max_heat"])
            if data.get("heat_cooldown_rate"):
                state.heat_cooldown_rate = float(data["heat_cooldown_rate"])
            if data.get("max_power"):
                state.power_limit = int(data["max_power"])
            state.performance_sync["shooter"] = int(data.get("performance_system_shooter", 0))
            state.performance_sync["chassis"] = int(data.get("performance_system_chassis", 0))
        elif name == "RobotDynamicStatus":
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
            state.robot_module_status = {k: int(v) for k, v in data.items()}
        elif name == "RobotPosition":
            self._upsert_positions(state, data)
        elif name == "Buff":
            self._upsert_buff(state, data)
        elif name == "PenaltyInfo":
            self._upsert_penalty(state, data)
        elif name == "RobotPathPlanInfo":
            state.path_plan = dict(data)
        elif name == "RadarInfoToClient":
            state.radar_detections = [dict(r) for r in data.get("robots", ())]
        elif name == "TechCoreMotionStateSync":
            state.tech_core = dict(data)
        elif name == "RobotPerformanceSelectionSync":
            state.performance_sync = {k: int(v) for k, v in data.items()}
        elif name == "DeployModeStatusSync":
            state.deploy_mode = int(data.get("status", 0))
        elif name == "RuneStatusSync":
            state.rune_status = dict(data)
            state.energy_rune_phase = _RUNE_PHASE.get(int(data.get("rune_status", 1)), "INACTIVE")
            state.energy_rune_progress = int(float(data.get("average_rings", 0)) * 100)
        elif name == "SentryStatusSync":
            state.sentry_status = dict(data)
        elif name == "DartSelectTargetStatusSync":
            state.dart_status = dict(data)
        elif name == "SentryCtrlResult":
            state.sentry_ctrl_result = dict(data)
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
        elif name == "RobotInjuryStat":
            state.injury_stats[int(data.get("killer_id", 0))] = dict(data)
        elif name == "RobotRespawnStatus":
            state.respawn_pending = bool(data.get("is_pending_respawn", state.respawn_pending))
            total = max(1, int(data.get("total_respawn_progress", 1)))
            current = int(data.get("current_respawn_progress", 0))
            state.respawn_progress = min(1.0, current / total)
            state.respawn_can_free = bool(data.get("can_free_respawn", state.respawn_can_free))
            state.respawn_gold_cost = int(data.get("gold_cost_for_respawn", state.respawn_gold_cost))
            state.respawn_can_pay = bool(data.get("can_pay_for_respawn", state.respawn_can_pay))

    def _upsert_positions(self, state: RobotState, data: dict[str, Any]) -> None:
        robot_id = int(data.get("robot_id", 0))
        positions = list(state.robot_positions)
        for index, item in enumerate(positions):
            if int(item.get("robot_id", -1)) == robot_id:
                positions[index] = dict(data)
                break
        else:
            positions.append(dict(data))
        state.robot_positions = positions[-16:]

    def _upsert_buff(self, state: RobotState, data: dict[str, Any]) -> None:
        key = (int(data.get("robot_id", 0)), int(data.get("buff_type", 0)))
        buffs = list(state.buffs)
        for index, item in enumerate(buffs):
            if (int(item.get("robot_id", 0)), int(item.get("buff_type", 0))) == key:
                buffs[index] = dict(data)
                break
        else:
            buffs.append(dict(data))
        state.buffs = buffs[-24:]

    def _upsert_penalty(self, state: RobotState, data: dict[str, Any]) -> None:
        penalty_type = int(data.get("penalty_type", 0))
        penalties = list(state.penalties)
        for index, item in enumerate(penalties):
            if int(item.get("penalty_type", -1)) == penalty_type:
                penalties[index] = dict(data)
                break
        else:
            penalties.append(dict(data))
        state.penalties = penalties[-8:]
        state.active_penalty = dict(data)

    # ------------------------------------------------------------------
    # ??????? SharkClient MqttCommandPanel ?????
    # ------------------------------------------------------------------
    def _publish(self, name: str, payload: bytes) -> tuple[bool, str]:
        return self.mqtt.publish_named(name, payload, qos=1)

    def publish_keyboard_mouse(self, mouse_x=0, mouse_y=0, mouse_z=0, *,
                               left=False, right=False, keyboard_value=0, mid=False) -> tuple[bool, str]:
        return self._publish("KeyboardMouseControl", proto.encode_keyboard_mouse_control(
            mouse_x, mouse_y, mouse_z, left, right, keyboard_value, mid))

    def publish_custom_control(self, data: bytes) -> tuple[bool, str]:
        return self._publish("CustomControl", proto.encode_custom_control(data))

    def publish_map_click_info(self, x: float, y: float, z: float = 0.0) -> tuple[bool, str]:
        return self._publish("MapClickInfo", proto.encode_map_click_info(x, y, z))

    def publish_map_click_notify(self, *, is_send_all=0, robot_id=b"", mode=1,
                                 enemy_id=0, ascii_code=0, mark_type=1,
                                 map_x=0.0, map_y=0.0) -> tuple[bool, str]:
        return self._publish("MapClickInfoNotify", proto.encode_map_click_info_notify(
            is_send_all, robot_id, mode, enemy_id, ascii_code, mark_type, map_x, map_y))

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
    # ?????? RobotProfile ???????????????
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
        return {
            "scenario": self.scenario_key,
            "safety": self.safety.stats(),
            "mqtt": self.mqtt.stats(),
            "udp": self.udp.stats(),
            "serial": self.serial.stats(),
        }
