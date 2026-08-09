"""??????????? SharkClient ??????? + ????????

???
- ????LabDebug / CampusSimulation / OfficialEvent???????????
- ??????? 10Hz ??????????? FIGHTING ??????????
- ???e-stop??????
- ???????????????
"""

from __future__ import annotations

import time
from typing import Any

# GameStatus.current_stage ?????0=??? 1=?? 2=?? 3=5???? 4=?? 5=??
FIGHTING_STAGES = frozenset({"4", "MATCH"})
# ???????????????
CONTROL_TOPICS = frozenset({
    "KeyboardMouseControl",
    "CustomControl",
    "MapClickInfoNotify",
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
    """???????????/?????"""

    def __init__(self, scenario_key: str = "LabDebug") -> None:
        self.scenario_key = scenario_key
        self.mock_writes = True
        self.allow_mqtt_publish = False
        self.enforce_official_limits = False
        self.estop_active = False
        self.estop_at = 0.0
        self._publish_at: dict[str, float] = {}
        self._publish_limit_hz = 10.0
        self.last_reason = ""

    # ------------------------------------------------------------------
    # ????
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

    # ------------------------------------------------------------------
    # ????
    # ------------------------------------------------------------------
    def update_stage(self, current_stage: Any) -> None:
        stage = str(current_stage).strip()
        if stage.isdigit() and len(stage) <= 2:
            stage = str(int(stage))
        self.current_stage = stage

    def is_fighting(self) -> bool:
        return getattr(self, "current_stage", "0") in FIGHTING_STAGES

    # ------------------------------------------------------------------
    # ??
    # ------------------------------------------------------------------
    def can_publish(self, topic: str, now: float | None = None) -> tuple[bool, str]:
        """?? (??????, ??)?"""
        name = str(topic).strip().rstrip("/").rsplit("/", 1)[-1]
        now = time.perf_counter() if now is None else now
        if self.estop_active:
            self.last_reason = "?????????????"
            return False, self.last_reason
        if not self.allow_mqtt_publish:
            self.last_reason = "????????? MQTT ???mock ???"
            return False, self.last_reason
        if self.enforce_official_limits and name in CONTROL_TOPICS:
            if not self.is_fighting():
                self.last_reason = "???????????????"
                return False, self.last_reason
            previous = self._publish_at.get(name, -1.0)
            if previous >= 0.0 and now - previous < 1.0 / self._publish_limit_hz:
                self.last_reason = f"{name} ?????? {self._publish_limit_hz:g}Hz"
                return False, self.last_reason
        return True, "ok"

    def mark_published(self, topic: str, now: float | None = None) -> None:
        self._publish_at[str(topic).strip()] = time.perf_counter() if now is None else now

    # ------------------------------------------------------------------
    # ??
    # ------------------------------------------------------------------
    def trigger_estop(self) -> None:
        self.estop_active = True
        self.estop_at = time.perf_counter()
        self.last_reason = "?????"

    def release_estop(self) -> None:
        self.estop_active = False

    def estop_elapsed(self, now: float | None = None) -> float:
        return (time.perf_counter() if now is None else now) - self.estop_at

    # ------------------------------------------------------------------
    # ??/????????????
    # ------------------------------------------------------------------
    def heartbeat_deadline(self, last_write_at: float, now: float | None = None,
                           timeout_s: float = 0.5) -> bool:
        """??????? timeout_s ????????"""
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
