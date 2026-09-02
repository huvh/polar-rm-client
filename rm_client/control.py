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

# 默认绑定：协议槽位 -> 物理键名。与历史行为一致（硬编码 W/A/S/D…），
# 但现在可以被用户改绑。这里存的是“这个协议槽由哪个物理键触发”，
# 而不是反过来——因为上位机下发的永远是协议槽位，固件按槽位语义解读。
DEFAULT_CONTROL_BINDS: dict[str, str] = {slot: slot for slot in KEYBOARD_BITS}

# 可供绑定的物理键名候选（与 `PolarRMWindow.key_name()` 的输出同一命名体系）。
BINDABLE_KEY_NAMES = (
    "W", "A", "S", "D", "Q", "E", "R", "F", "G", "Z", "X", "C", "V", "B",
    "Shift", "RightShift", "Ctrl", "Space", "Tab", "Enter", "Escape",
    "Backspace", "Delete", "Insert", "Home", "End", "PageUp", "PageDown",
    "Up", "Down", "Left", "Right", "F1", "F2", "F3", "F4", "F5",
    "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "None",
)


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
        # 协议槽 -> 已绑物理键名；可由前端改绑，默认与旧行为一致。
        self.binds: dict[str, str] = dict(DEFAULT_CONTROL_BINDS)
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
        # Active input remains 75 Hz. While an operator-authorized match is
        # idle, send a bounded 4 Hz neutral frame for the robot watchdog.
        self.idle_zero_interval_s = 0.25
        self._dirty = False

    def set_bind(self, slot: str, key_name: str) -> bool:
        """改绑一个协议槽。失败时返回 False 且不改变现有状态。

        不允许两个槽位绑到同一个物理键（会造成一键双动作）；也不允许
        把槽位绑成 "None" 以外的重复值。绑成 "None" 表示该槽不接物理键。
        """

        slot = str(slot).upper()
        if slot not in CONTROL_KEYS:
            return False
        candidate = str(key_name or "None").strip()
        if candidate and candidate not in BINDABLE_KEY_NAMES:
            return False
        if candidate != "None":
            lowered = candidate.lower()
            for other, bound in self.binds.items():
                if other != slot and str(bound).lower() == lowered:
                    return False  # 已被别的槽占用
            # 物理键名与默认槽名相同时，仍要先把旧的同名绑定释放，避免两个槽同时响应
            for other in list(self.binds):
                if other != slot and str(self.binds[other]).lower() == lowered:
                    self.binds[other] = DEFAULT_CONTROL_BINDS[other]
        self.binds[slot] = candidate or "None"
        return True

    def reset_binds(self) -> None:
        self.binds = dict(DEFAULT_CONTROL_BINDS)

    def resolve_slot(self, key_name: str, is_right_shift: bool = False) -> str | None:
        """把按下的物理键解析为它当前驱动的协议槽（可能有多个）。

        返回所有命中的槽位，调用方逐个 set_key。一个物理键可以合法地驱动
        多个协议槽（例如 Shift 与 RightShift 共享同一个物理键），但同一个槽
        只能有一个绑定。
        """

        name = str(key_name or "").strip()
        if not name:
            return ()
        lowered = name.lower()
        hits = tuple(
            slot
            for slot, bound in self.binds.items()
            if slot in CONTROL_KEYS and str(bound).lower() == lowered
        )
        return hits

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
        if not active and not self._dirty and not self._idle_zero_authorized():
            return None
        interval = 1.0 / self.heartbeat_hz if active or self._dirty else self.idle_zero_interval_s
        if now - self.last_send_at < interval:
            return None
        return self.send_from_state(state, registry)

    def _idle_zero_authorized(self) -> bool:
        """Avoid denied heartbeat/log spam while the fail-closed gate is locked."""

        if self.mock_output:
            return True
        safety = getattr(self.publisher, "safety", None)
        control_state = getattr(safety, "control_state", None)
        value = getattr(control_state, "value", control_state)
        if str(value) != "MATCH_ARMED":
            return False
        is_fighting = getattr(safety, "is_fighting", None)
        return not callable(is_fighting) or bool(is_fighting())

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
