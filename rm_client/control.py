from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import time
from typing import Any

from .model import ModuleRegistry, RobotState
from .protocol import encode_custom_control_30


CONTROL_KEYS = {"W", "A", "S", "D", "Q", "E"}


@dataclass
class ChassisCommand:
    seq: int
    timestamp: float
    vx: float
    vy: float
    wz: float
    spin_mode: bool
    speed_limit: int
    power_limit: int
    mock_output: bool
    source: str = "keyboard"
    protocol: str = "rm_control.chassis.v1"

    def to_payload(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    def to_custom_control(self) -> bytes:
        return encode_custom_control_30(
            seq=self.seq,
            vx=self.vx,
            vy=self.vy,
            wz=self.wz,
            speed_limit=self.speed_limit,
            power_limit=self.power_limit,
            spin_mode=self.spin_mode,
        )


class KeyboardControlBridge:
    """把键盘状态转换成可发送的 RM 底盘命令。

    这个桥接层默认优先 mock：它会记录载荷，只有在明确关闭
    mock_output 后才会写入已连接的串口对象。
    """

    def __init__(self, serial_bridge: Any | None = None, mock_output: bool = True) -> None:
        self.serial_bridge = serial_bridge
        self.mock_output = mock_output
        self.key_state: dict[str, bool] = {key: False for key in CONTROL_KEYS}
        self.seq = 0
        self.last_command: ChassisCommand | None = None
        self.last_payload: bytes = b""
        self.last_error = ""

    def set_key(self, key: str, pressed: bool, state: RobotState, registry: ModuleRegistry) -> ChassisCommand | None:
        key = key.upper()
        if key not in CONTROL_KEYS:
            return None
        if self.key_state.get(key, False) == pressed:
            return None
        self.key_state[key] = pressed
        return self.send_from_state(state, registry)

    def send_from_state(self, state: RobotState, registry: ModuleRegistry) -> ChassisCommand:
        command = self.build_command(state, registry)
        self.send_command(command)
        return command

    def build_command(self, state: RobotState, registry: ModuleRegistry) -> ChassisCommand:
        forward = float(self.key_state["W"]) - float(self.key_state["S"])
        strafe = float(self.key_state["D"]) - float(self.key_state["A"])
        yaw = float(self.key_state["E"]) - float(self.key_state["Q"])
        length = math.hypot(forward, strafe)
        if length > 1.0:
            forward /= length
            strafe /= length

        chassis = registry.get("ChassisAssist")
        spin = registry.get("SpinMode")
        power_setting = chassis.get_setting("Power Limit") if chassis else None
        speed_setting = spin.get_setting("Spin Speed") if spin else None
        power_limit = int(power_setting.value) if power_setting else state.power_limit
        speed_limit = int(speed_setting.value) if speed_setting else state.speed_limit

        self.seq += 1
        return ChassisCommand(
            seq=self.seq,
            timestamp=time.time(),
            vx=forward,
            vy=strafe,
            wz=yaw,
            spin_mode=bool(spin and spin.enabled),
            speed_limit=speed_limit,
            power_limit=power_limit,
            mock_output=self.mock_output,
        )

    def send_command(self, command: ChassisCommand) -> None:
        payload = command.to_payload()
        self.last_command = command
        self.last_payload = payload
        self.last_error = ""
        if self.mock_output:
            return
        if self.serial_bridge is None:
            self.last_error = "未连接串口桥接对象"
            return
        try:
            bridge = self.serial_bridge
            if hasattr(bridge, "write_frame"):
                # 真实串口走官方 0x0311 CustomControl 帧，而不是裸 JSON
                ok, reason = bridge.write_frame(0x0311, command.to_custom_control())
                if not ok:
                    self.last_error = reason
            else:
                bridge.write(payload)
        except Exception as exc:
            self.last_error = str(exc)
