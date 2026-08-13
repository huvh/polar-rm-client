from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import time
from typing import Any

from .model import ModuleRegistry, RobotState


# 官方 V1.3.1 KeyboardMouseControl.keyboard_value 位序。
KEYBOARD_BITS = {
    "W": 0,
    "S": 1,
    "A": 2,
    "D": 3,
    "SHIFT": 4,
    "CTRL": 5,
    "Q": 6,
    "E": 7,
    "R": 8,
    "F": 9,
    "G": 10,
    "Z": 11,
    "X": 12,
    "C": 13,
    "V": 14,
    "B": 15,
}
CONTROL_KEYS = frozenset(KEYBOARD_BITS)


@dataclass
class ChassisCommand:
    """可审计的本地键鼠快照；实际 wire 使用 KeyboardMouseControl protobuf。"""

    seq: int
    timestamp: float
    vx: float
    vy: float
    wz: float
    spin_mode: bool
    speed_limit: int
    power_limit: int
    mock_output: bool
    keyboard_value: int = 0
    mouse_x: int = 0
    mouse_y: int = 0
    mouse_z: int = 0
    left_button_down: bool = False
    right_button_down: bool = False
    mid_button_down: bool = False
    source: str = "keyboard_mouse"
    protocol: str = "rm2026.KeyboardMouseControl.v1.3.1"

    def to_payload(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class KeyboardControlBridge:
    """采集键鼠并经 BackendManager 的官方 MQTT 上行发送。

    0x0311 属于图传链路；这里绝不直接写 115200 串口。BackendManager
    会编码 KeyboardMouseControl，MQTT/图传模块再转发给机器人。
    """

    def __init__(self, publisher: Any | None = None, mock_output: bool = True) -> None:
        self.publisher = publisher
        self.mock_output = bool(mock_output)
        self.key_state: dict[str, bool] = {key: False for key in CONTROL_KEYS}
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_z = 0
        self.left_button_down = False
        self.right_button_down = False
        self.mid_button_down = False
        self.seq = 0
        self.last_command: ChassisCommand | None = None
        self.last_payload: bytes = b""
        self.last_error = ""
        self.last_send_at = 0.0
        self.heartbeat_hz = 75.0
        self._dirty = False

    def set_key(self, key: str, pressed: bool, state: RobotState, registry: ModuleRegistry) -> ChassisCommand | None:
        key = key.upper()
        if key not in CONTROL_KEYS:
            return None
        if self.key_state.get(key, False) == bool(pressed):
            return None
        self.key_state[key] = bool(pressed)
        self._dirty = True
        return self.send_from_state(state, registry)

    def set_mouse_button(
        self,
        button: int,
        pressed: bool,
        state: RobotState,
        registry: ModuleRegistry,
    ) -> ChassisCommand | None:
        attr = {1: "left_button_down", 2: "mid_button_down", 3: "right_button_down"}.get(int(button))
        if attr is None or bool(getattr(self, attr)) == bool(pressed):
            return None
        setattr(self, attr, bool(pressed))
        self._dirty = True
        return self.send_from_state(state, registry)

    def add_mouse_motion(self, dx: float, dy: float) -> None:
        self.mouse_x = self._clamp_i32(self.mouse_x + int(round(dx)))
        # Qt y 向下为正；官方协议 y 负值表示向下，故取反。
        self.mouse_y = self._clamp_i32(self.mouse_y - int(round(dy)))
        self._dirty = True

    def add_wheel(self, delta: float) -> None:
        self.mouse_z = self._clamp_i32(self.mouse_z + int(round(delta)))
        self._dirty = True

    def reset_inputs(self) -> None:
        for key in self.key_state:
            self.key_state[key] = False
        self.mouse_x = self.mouse_y = self.mouse_z = 0
        self.left_button_down = self.right_button_down = self.mid_button_down = False
        self._dirty = True

    def release_all(self, state: RobotState, registry: ModuleRegistry) -> ChassisCommand:
        """Clear local input and immediately publish one neutral KMC snapshot."""

        self.reset_inputs()
        return self.send_from_state(state, registry)

    def clear_pending(self) -> None:
        """急停已走专用零帧后清除普通发送重试。"""
        self._dirty = False

    def send_from_state(self, state: RobotState, registry: ModuleRegistry) -> ChassisCommand:
        command = self.build_command(state, registry)
        self.send_command(command)
        return command

    def tick(self, state: RobotState, registry: ModuleRegistry, now: float | None = None) -> ChassisCommand | None:
        now = time.perf_counter() if now is None else float(now)
        active = (
            any(self.key_state.values())
            or self.left_button_down
            or self.right_button_down
            or self.mid_button_down
            or self.mouse_x != 0
            or self.mouse_y != 0
            or self.mouse_z != 0
        )
        if (not active and not self._dirty) or now - self.last_send_at < 1.0 / self.heartbeat_hz:
            return None
        return self.send_from_state(state, registry)

    def build_command(self, state: RobotState, registry: ModuleRegistry) -> ChassisCommand:
        forward = float(self.key_state["W"]) - float(self.key_state["S"])
        strafe = float(self.key_state["D"]) - float(self.key_state["A"])
        yaw = float(self.key_state["E"]) - float(self.key_state["Q"])
        length = math.hypot(forward, strafe)
        if length > 1.0:
            forward /= length
            strafe /= length
        keyboard_value = sum(1 << bit for key, bit in KEYBOARD_BITS.items() if self.key_state[key])
        chassis = registry.get("ChassisAssist")
        spin = registry.get("SpinMode")
        power_setting = chassis.get_setting("Power Limit") if chassis else None
        speed_setting = spin.get_setting("Spin Speed") if spin else None
        self.seq += 1
        return ChassisCommand(
            seq=self.seq,
            timestamp=time.time(),
            vx=forward,
            vy=strafe,
            wz=yaw,
            spin_mode=bool(spin and spin.enabled),
            speed_limit=int(speed_setting.value) if speed_setting else state.speed_limit,
            power_limit=int(power_setting.value) if power_setting else state.power_limit,
            mock_output=self.mock_output,
            keyboard_value=keyboard_value,
            mouse_x=self.mouse_x,
            mouse_y=self.mouse_y,
            mouse_z=self.mouse_z,
            left_button_down=self.left_button_down,
            right_button_down=self.right_button_down,
            mid_button_down=self.mid_button_down,
        )

    def send_command(self, command: ChassisCommand) -> None:
        self.last_command = command
        self.last_payload = command.to_payload()
        self.last_error = ""
        now = time.perf_counter()
        self.last_send_at = now
        if self.mock_output:
            self._dirty = False
            self._consume_relative_motion()
            return
        if self.publisher is None or not hasattr(self.publisher, "publish_keyboard_mouse"):
            self.last_error = "未连接 KeyboardMouseControl MQTT 发布器"
            self._consume_relative_motion()
            return
        try:
            ok, reason = self.publisher.publish_keyboard_mouse(
                command.mouse_x,
                command.mouse_y,
                command.mouse_z,
                left=command.left_button_down,
                right=command.right_button_down,
                keyboard_value=command.keyboard_value,
                mid=command.mid_button_down,
            )
            if not ok:
                self.last_error = str(reason)
            else:
                self._dirty = False
                self._consume_relative_motion()
        except Exception as exc:
            self.last_error = str(exc)

    def _consume_relative_motion(self) -> None:
        self.mouse_x = self.mouse_y = self.mouse_z = 0

    @staticmethod
    def _clamp_i32(value: int) -> int:
        return max(-(1 << 31), min((1 << 31) - 1, int(value)))
