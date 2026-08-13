"""官方赛事安全策略（对齐 SharkClient 后端的安全边界 + 本地三种场景）。

职责：
    - 按场景（LabDebug / CampusSimulation / OfficialEvent）控制是否允许真实发布
    - 官方限幅：KMC/CustomControl 75Hz、事件指令 10Hz、比赛阶段门控
    - 急停（e-stop）与断连保护
    - 急停锁止；机器人侧仍必须实现控制超时归零
"""

from __future__ import annotations

import time
from typing import Any

# GameStatus.current_stage 官方取值：0=未开始 1=准备 2=自检 3=5秒倒计时 4=比赛 5=结算
FIGHTING_STAGES = frozenset({"4", "MATCH"})
# 控制类消息只允许在比赛阶段发布
CONTROL_TOPICS = frozenset({
    "KeyboardMouseControl",
    "CustomControl",
    "MapClickCmd",
    "AssemblyCommand",
    "RobotPerformanceSelectionCommand",
    "CommonCommand",
    "HeroDeployModeEventCommand",
    "RuneActivateCommand",
    "DartCommand",
    "SentryCtrlCommand",
    "AirSupportCommand",
})


class OfficialSafety:
    """按场景与官方规则做发布/控制门控。"""

    def __init__(self, scenario_key: str = "LabDebug") -> None:
        self.scenario_key = scenario_key
        self.mock_writes = True
        self.allow_mqtt_publish = False
        self.enforce_official_limits = False
        self.estop_active = False
        self.estop_at = 0.0
        self.current_stage = "0"
        self._stage_seen = False  # 收到真实 GameStatus 前 fail-closed
        self._publish_at: dict[str, float] = {}
        self._publish_limit_hz = 10.0
        self._topic_limit_hz = {
            "KeyboardMouseControl": 75.0,
            "CustomControl": 75.0,
        }
        self.last_reason = ""

    # ------------------------------------------------------------------
    # 场景配置
    # ------------------------------------------------------------------
    def configure(self, *, mock_writes: bool, allow_mqtt_publish: bool,
                  enforce_official_limits: bool) -> None:
        self.mock_writes = bool(mock_writes)
        self.allow_mqtt_publish = bool(allow_mqtt_publish)
        self.enforce_official_limits = bool(enforce_official_limits)

    def from_scenario(self, config: Any) -> None:
        self.scenario_key = str(config.key)
        self.configure(
            mock_writes=bool(config.safety.mock_writes),
            allow_mqtt_publish=bool(config.safety.allow_mqtt_publish),
            enforce_official_limits=bool(config.safety.enforce_official_limits),
        )
        # 切场景时重置阶段与限频状态，避免继承上一场景的“比赛中”状态
        self.current_stage = "0"
        self._stage_seen = False
        self._publish_at.clear()

    # ------------------------------------------------------------------
    # 比赛阶段
    # ------------------------------------------------------------------
    def update_stage(self, current_stage: Any) -> None:
        """只有官方数字阶段或已确认过的 MATCH 才更新；默认保持 fail-closed。"""
        stage = str(current_stage).strip()
        if stage.isdigit() and len(stage) <= 2:
            self.current_stage = str(int(stage))
            self._stage_seen = True
        elif stage == "MATCH" and self._stage_seen:
            self.current_stage = "4"

    def is_fighting(self) -> bool:
        return self._stage_seen and self.current_stage in FIGHTING_STAGES

    # ------------------------------------------------------------------
    # 发布门控与限频
    # ------------------------------------------------------------------
    def can_publish(self, topic: str, now: float | None = None) -> tuple[bool, str]:
        """返回 (是否允许发布, 原因)。"""
        name = str(topic).strip().rstrip("/").rsplit("/", 1)[-1]
        now = time.perf_counter() if now is None else now
        if self.estop_active:
            self.last_reason = "急停激活，禁止发布控制指令"
            return False, self.last_reason
        if not self.allow_mqtt_publish:
            self.last_reason = "当前场景不允许真实 MQTT 发布（mock 记录）"
            return False, self.last_reason
        if self.enforce_official_limits and name in CONTROL_TOPICS:
            if not self.is_fighting():
                self.last_reason = "非比赛阶段，禁止发布控制类指令"
                return False, self.last_reason
            previous = self._publish_at.get(name, -1.0)
            limit_hz = self._topic_limit_hz.get(name, self._publish_limit_hz)
            if previous >= 0.0 and now - previous < 1.0 / limit_hz:
                self.last_reason = f"{name} 发布频率超过 {limit_hz:g}Hz"
                return False, self.last_reason
        return True, "ok"

    def mark_published(self, topic: str, now: float | None = None) -> None:
        # 与 can_publish 使用相同的归一化键（取最后一段消息名），避免层级 topic 绕过 10Hz
        name = str(topic).strip().rstrip("/").rsplit("/", 1)[-1]
        self._publish_at[name] = time.perf_counter() if now is None else now

    # ------------------------------------------------------------------
    # 急停
    # ------------------------------------------------------------------
    def trigger_estop(self) -> None:
        self.estop_active = True
        self.estop_at = time.perf_counter()
        self.last_reason = "急停已触发"

    def release_estop(self) -> None:
        self.estop_active = False

    def estop_elapsed(self, now: float | None = None) -> float:
        return (time.perf_counter() if now is None else now) - self.estop_at

    # ------------------------------------------------------------------
    # 兼容旧调用方的超时判断工具；实际看门狗必须由机器人固件实现。
    # ------------------------------------------------------------------
    def heartbeat_deadline(self, last_write_at: float, now: float | None = None,
                           timeout_s: float = 0.5) -> bool:
        """距上次写入超过 timeout_s 即认为需要归零。"""
        return (time.perf_counter() if now is None else now) - last_write_at > timeout_s

    def stats(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_key,
            "mock_writes": self.mock_writes,
            "allow_mqtt_publish": self.allow_mqtt_publish,
            "enforce_official_limits": self.enforce_official_limits,
            "estop_active": self.estop_active,
            "fighting": self.is_fighting(),
            "stage": getattr(self, "current_stage", "0"),
        }
