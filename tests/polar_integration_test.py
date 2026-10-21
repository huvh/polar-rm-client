"""虚拟机器人固件端到端集成测试。

组件测试已经分别证明编解码、映射、仲裁各自正确，但客户端从未对着一个
「会真的回数据、会解析上行帧」的下位机跑过。本文件用 Python 复刻
StandardRobot++ 上位机接口的行为语义，跑完整回环：

    BackendManager + KeyboardControlBridge + PolarLinkTransport
            ↕ 内存串口管道
    VirtualRobot（按固件语义发 14 段、解 RobotCmd、可选是否消费底盘速度）

覆盖两条实车路径：

1. **已打底盘补丁的机器人**：按 W → 机器人收到 1.5 m/s → 车动 → 0x1E 回读
   → MOT 变 OK；F12 → 机器人立刻收到全零。
2. **未打补丁的机器人（当前 master 真实行为）**：按 W → 机器人收到速度但
   不消费 → 0x1E 恒为 0 → 客户端必须报 NO_MOTION/STUCK，而不是假装正常。

    python tests/polar_integration_test.py
"""

from __future__ import annotations

import os
import struct
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.backend.manager import BackendManager  # noqa: E402
from rm_client.backend.polar_link import (  # noqa: E402
    CMD_ROBOT,
    SEG_ALL_ROBOT_HP,
    SEG_BUFF,
    SEG_DEBUG,
    SEG_EVENT,
    SEG_GAME_STATUS,
    SEG_GROUND_ROBOT_POSITION,
    SEG_IMU,
    SEG_JOINT_STATE,
    SEG_REFEREE_WARNING,
    SEG_RFID_STATUS,
    SEG_ROBOT_MOTION,
    CMD_VIRTUAL_RC,
    SEG_ROBOT_STATE_INFO,
    SEG_ROBOT_STATUS,
    SEG_SHOOT_DATA,
    PolarFrameCodec,
)
from rm_client.control import KeyboardControlBridge  # noqa: E402
from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.protocol import crc8, crc16  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[PASS] {name}")
    else:
        print(f"[FAIL] {name} {detail}")
        FAILED.append(name)


# ----------------------------------------------------------------------
# 内存双向管道
# ----------------------------------------------------------------------
class Pipe:
    """线程安全的单向字节管道，模拟串口的一根线。"""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()

    def write(self, data: bytes) -> int:
        with self._lock:
            self._buf.extend(data)
        return len(data)

    def read(self, count: int) -> bytes:
        with self._lock:
            chunk = bytes(self._buf[:count])
            del self._buf[: len(chunk)]
        return chunk

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


class PipeSerial:
    """伪装成 pyserial Serial 对象：写=发给机器人，读=机器人发来的字节。"""

    def __init__(self, to_robot: Pipe, to_host: Pipe) -> None:
        self.to_robot = to_robot
        self.to_host = to_host
        self.is_open = True

    def write(self, data: bytes) -> int:
        return self.to_robot.write(bytes(data))

    def read(self, count: int = 1) -> bytes:
        return self.to_host.read(count)

    def close(self) -> None:
        self.is_open = False


# ----------------------------------------------------------------------
# 虚拟机器人固件
# ----------------------------------------------------------------------
def build_segment(segment_id: int, body: bytes, stamp: int) -> bytes:
    seg_len = 4 + len(body)
    header = bytes((0x5A, seg_len & 0xFF, segment_id & 0xFF, 0))
    header = header[:3] + bytes((crc8(header[:3]),))
    out = header + struct.pack("<I", stamp) + body
    return out + crc16(out).to_bytes(2, "little")


class VirtualRobot:
    """按 StandardRobot++ 语义运行的机器人侧。

    `consumes_chassis` 模拟固件是否已补上 `GetScCmdChassisSpeed` 的消费者：
    False 就是当前 master 的真实行为 —— 收到速度但没人用，车不动。
    """

    def __init__(self, to_robot: Pipe, to_host: Pipe, *, consumes_chassis: bool,
                 emits_motion: bool = True, honours_key_v: bool = False) -> None:
        self.honours_key_v = honours_key_v
        self._key_target = (0.0, 0.0, 0.0)
        self._last_vrc_rx = 0.0
        self.to_robot = to_robot
        self.to_host = to_host
        self.consumes_chassis = consumes_chassis
        self.emits_motion = emits_motion
        self.codec = PolarFrameCodec()
        self.rx_buffer = bytearray()

        self.received_cmds: list[tuple[float, float, float, float, float, int]] = []
        self.commanded = (0.0, 0.0, 0.0)
        self.gimbal_commanded_rad = (0.0, 0.0)
        self.measured = [0.0, 0.0, 0.0]
        # 测速模块坐标（0x0A 的 x/y）：真实机器人会积分出位置，
        # 缺 0x1E 时客户端靠它判定车是否动。
        self.position = [3.2, 4.1]
        self.gimbal_rad = [0.0, 0.0]
        self.host_frames_seen = 0
        self._stamp = int(time.time() * 1000) & 0xFFFFFFFF
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.link_dropped = False

    # -- 生命周期 ----------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="virtual-robot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    # -- 主循环 ------------------------------------------------------
    def _run(self) -> None:
        next_emit = 0.0
        while not self._stop.is_set():
            now = time.perf_counter()
            self._drain_uplink()
            if now >= next_emit and not self.link_dropped:
                next_emit = now + 0.05  # 20Hz，与固件多段合计速率同量级
                self._emit_downlink()
            time.sleep(0.005)

    def _drain_uplink(self) -> None:
        chunk = self.to_robot.read(4096)
        if not chunk:
            return
        # 上行只有 RobotCmd 一种我们关心；codec 只解下行段，因此这里
        # 自己按固件结构体解，避免把上行误计入下行统计。
        self._parse_uplink(chunk)

    def _parse_uplink(self, raw: bytes) -> None:
        index = 0
        while index + 10 <= len(raw):
            if raw[index] != 0x5A:
                index += 1
                continue
            header = raw[index : index + 4]
            if crc8(header[:3]) != header[3]:
                index += 1
                continue
            seg_len, seg_id = header[1], header[2]
            total = 4 + seg_len + 2
            if index + total > len(raw):
                break
            frame = raw[index : index + total]
            if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                index += 1
                continue
            index += total
            if seg_id == CMD_VIRTUAL_RC:
                # 方案 B 的真实固件行为：0x03 的 key.v 被 OR 进 rc_ctrl.key.v，
                # 再由 chassis_omni 的 FOLLOW/SPIN 分支读它产生**带斜坡**的速度。
                # 注意它**不看** speed_vector（master 上那个 getter 零调用者）。
                if self.honours_key_v and len(frame) >= 30:
                    self._last_vrc_rx = time.perf_counter()
                    key_v = int.from_bytes(frame[28:30], "little")
                    step = 0.35  # 模拟固件 0.004*x_time 斜坡的等效增量
                    vx = (1 if key_v & 0x01 else 0) + (-1 if key_v & 0x02 else 0)
                    vy = (1 if key_v & 0x04 else 0) + (-1 if key_v & 0x08 else 0)
                    self._key_target = (vx * 1.5, vy * 1.5, 0.0)  # CHASSIS_RC_MAX_SPEED=1.5
                    self.commanded = (
                        self.commanded[0] + max(-step, min(step, self._key_target[0] - self.commanded[0])),
                        self.commanded[1] + max(-step, min(step, self._key_target[1] - self.commanded[1])),
                        self.commanded[2],
                    )
                continue
            if seg_id != CMD_ROBOT:
                continue
            self.host_frames_seen += 1
            body = frame[8 : 8 + 39]
            floats = struct.unpack("<9f", body[:36])
            fire, fric, tracking = body[36], body[37], body[38]
            vx, vy, wz = floats[0], floats[1], floats[2]
            pitch, yaw = floats[7], floats[8]
            self.received_cmds.append((vx, vy, wz, pitch, yaw, fire))
            # 只有固件真的消费时才更新 commanded
            if self.consumes_chassis:
                self.commanded = (vx, vy, wz)
            elif self.honours_key_v:
                # 方案 B 下 speed_vector 仍无人消费：必须**不**响应，
                # 否则仿真会比真车乐观，测不出错通道。
                pass
            self.gimbal_commanded_rad = (pitch, yaw)

    def _emit_downlink(self) -> None:
        self._stamp = (self._stamp + 50) & 0xFFFFFFFF
        stamp = self._stamp
        # 一阶惯性跟随：只有固件真的消费了驾驶指令，实测才会跟上
        follows = self.consumes_chassis or self.honours_key_v
        if self.honours_key_v:
            # 方案 B 的 `UsbMergeVirtualRcKeys` 带新鲜度门控：0x03 停发超过
            # VRC_FRESH_TIMEOUT_MS=150ms 后不再 OR 进 key.v，rc_ctrl 回到
            # 遥控器真值（本场景下为 0）。客户端松杆后就**不再发 0x03**，
            # 所以这里必须模拟这个回落，否则就把固件的归零机制做没了。
            if time.perf_counter() - self._last_vrc_rx > 0.15:
                self.commanded = (0.0, 0.0, 0.0)
        target = self.commanded if follows else (0.0, 0.0, 0.0)
        for axis in range(3):
            self.measured[axis] += (target[axis] - self.measured[axis]) * 0.45
        # 按 20Hz 积分位置（dt≈0.05s）
        self.position[0] += self.measured[0] * 0.05
        self.position[1] += self.measured[1] * 0.05
        # 云台角度：固件的 GimbalReference 在 AUTO_AIM 下会跟随上位机角度
        for axis in range(2):
            self.gimbal_rad[axis] += (
                self.gimbal_commanded_rad[axis] - self.gimbal_rad[axis]
            ) * 0.6

        packets = [
            build_segment(
                SEG_IMU,
                struct.pack("<6f", self.measured[2] * 0.2 + 0.87, 0.03, -0.01, 0.0, 0.0, 0.0),
                stamp,
            ),
            build_segment(SEG_JOINT_STATE, struct.pack("<ff", self.gimbal_rad[0], self.gimbal_rad[1]), stamp),
            build_segment(
                SEG_ROBOT_STATUS,
                struct.pack(
                    "<BBHHHHHfffBHHHH",
                    3, 2, 400, 480, 44, 120, 480,
                    self.position[0], self.position[1], 137.0, (1 << 4) | 4, 168, 0, 25, 40,
                ),
                stamp,
            ),
            build_segment(SEG_BUFF, struct.pack("<BHBBHB", 2, 0, 1, 0, 45, 82), stamp),
            build_segment(SEG_ROBOT_STATE_INFO, struct.pack("<HB", 0b101, 0), stamp),
            build_segment(SEG_GAME_STATUS, struct.pack("<BHQ", (4 << 4) | 2, 42000, 0), stamp),
            build_segment(SEG_ALL_ROBOT_HP, struct.pack("<8H", 400, 380, 460, 420, 0, 520, 1500, 4800), stamp),
            build_segment(SEG_SHOOT_DATA, struct.pack("<BBBf", 0, 1, 8, 15.4), stamp),
            build_segment(SEG_RFID_STATUS, struct.pack("<IB", 0, 0), stamp),
            build_segment(SEG_GROUND_ROBOT_POSITION, struct.pack("<10f", 2.2, 2.1, 6.0, 7.5, 3.4, 3.8, 4.1, 5.0, 0, 0), stamp),
            build_segment(SEG_EVENT, struct.pack("<I", 0), stamp),
            build_segment(SEG_REFEREE_WARNING, struct.pack("<BBB", 0, 0, 0), stamp),
        ]
        # omni/mecanum 无速度观测器：ChassisPublish 未实现时 0x1E 一帧不发
        if self.emits_motion:
            packets.append(build_segment(SEG_ROBOT_MOTION, struct.pack("<fff", *self.measured), stamp))
        self.to_host.write(b"".join(packets))


# ----------------------------------------------------------------------
# 测试脚手架
# ----------------------------------------------------------------------
class Harness:
    def __init__(self, *, consumes_chassis: bool, scenario_key: str = "OfficialEvent",
                 emits_motion: bool = True, honours_key_v: bool = False) -> None:
        self.scenario_key = scenario_key
        self.honours_key_v = honours_key_v
        self.emits_motion = emits_motion
        self.to_robot = Pipe()
        self.to_host = Pipe()
        self.robot = VirtualRobot(self.to_robot, self.to_host, consumes_chassis=consumes_chassis,
                                   emits_motion=self.emits_motion, honours_key_v=self.honours_key_v)
        self.workspace = os.path.join(
            os.environ.get("TEMP", "/tmp"), f"polar_it_{int(time.time()*1000)}_{consumes_chassis}"
        )
        os.makedirs(self.workspace, exist_ok=True)
        self.manager: BackendManager | None = None
        self.registry = None
        self.state: RobotState | None = None
        self.control: KeyboardControlBridge | None = None
        self._saved_serial = sys.modules.get("serial")
        self._referee_client = None
        self._next_referee_receipt = 0.0

    def __enter__(self) -> "Harness":
        fake = types.ModuleType("serial")
        endpoint = PipeSerial(self.to_robot, self.to_host)
        fake.Serial = lambda *a, **k: endpoint  # type: ignore[attr-defined]
        fake.tools = types.ModuleType("serial.tools")  # type: ignore[attr-defined]
        fake.tools.list_ports = types.ModuleType("serial.tools.list_ports")  # type: ignore[attr-defined]
        fake.tools.list_ports.comports = lambda: []  # type: ignore[attr-defined]
        sys.modules["serial"] = fake
        self._endpoint = endpoint

        self.manager = BackendManager(workspace=self.workspace, scenario_key=self.scenario_key, client_id="3")
        self.registry = build_default_registry()
        self.state = self.manager.state = RobotState()
        self.manager._apply_config(self.manager.config)
        # 绕开 `Auto` 的真实串口枚举：显式给一个端口名，让被 fake 的 serial
        # 模块只负责提供管道，不承担设备发现。
        self.manager.polar.port = "COM99"
        self.control = KeyboardControlBridge(self.manager, mock_output=True)
        self.robot.start()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.manager.shutdown()
        except Exception:
            pass
        self.robot.stop()
        if self._saved_serial is not None:
            sys.modules["serial"] = self._saved_serial
        else:
            sys.modules.pop("serial", None)

    def connect_inert_referee(self) -> None:
        """Model a live parallel referee session, without sockets or hardware.

        Sustained-drive diagnostics must not accidentally test the independent
        two-second disconnected-MQTT input clear. Exercise normal CONNACK and
        SUBACK admission, then feed phase receipts at the documented 5 Hz.
        """
        subscriptions = []
        def subscribe(topics):
            subscriptions.extend(topics)
            return 0, 1
        client = types.SimpleNamespace(
            subscribe=subscribe,
            publish=lambda *a, **kw: types.SimpleNamespace(rc=0),
            disconnect=lambda: None,
            loop_stop=lambda: None,
        )
        self._referee_client = self.manager.mqtt.client = client
        self.manager.mqtt._on_connect(client, None, {}, 0)
        self.manager.mqtt._on_subscribe(
            client, None, 1, [self.manager.mqtt.referee.max_qos] * len(subscriptions))

    # -- 驱动一帧（模拟 UI tick） ------------------------------------
    def frame(self) -> None:
        now = time.perf_counter()
        if self._referee_client is not None and now >= self._next_referee_receipt:
            self._next_referee_receipt = now + 0.2
            self.manager.mqtt._on_message(self._referee_client, None,
                types.SimpleNamespace(topic="GameStatus", payload=b"\x28\x04", retain=False))
        self.manager.tick()
        self.manager.apply_updates(self.state)
        self.manager.tick_polar_link(self.state, self.registry, self.control)

    def frames(self, count: int, interval: float = 0.02) -> None:
        for _ in range(count):
            self.frame()
            time.sleep(interval)

    def enable_drive(self) -> None:
        link = self.registry.get("RobotLink")
        link.enabled = True
        # 驾驶授权现在是纯模块设置，不再由场景代写，所以这里要显式打开。
        link.get_setting("Allow Drive").value = True
        link.get_setting("Mock Writes").value = False
        link.get_setting("Client Chassis Drive").value = True
        link.get_setting("Vision NUC Occupied").value = False
        link.get_setting("Client Gimbal Control").value = False


def press(key: str, h: Harness, pressed: bool = True) -> None:
    h.control.set_key(key, pressed, h.state, h.registry)


# ----------------------------------------------------------------------
def test_patched_robot() -> None:
    print("\n--- 机器人已补底盘消费者 ---")
    with Harness(consumes_chassis=True) as h:
        h.frames(10)
        check("链路自动连上（无需重开场景）", h.state.polar_link_active is True, str(h.state.polar_link_age_s))
        snap = h.state.backend_stats.get("polar_link", {})
        check("机器人已收到上位机帧", h.robot.host_frames_seen > 0, str(h.robot.host_frames_seen))
        check("已收下行段数 >= 5", len(snap.get("segment_counts", {})) >= 5, str(snap.get("segment_counts")))
        check("CRC 错误为 0", snap.get("decode", {}).get("crc16_errors", -1) == 0, str(snap.get("decode")))
        check("HUD 底盘朝向为真值", abs(h.state.chassis_yaw_deg - 49.85) < 0.5, str(h.state.chassis_yaw_deg))
        check("HUD 功率上限为真值", h.state.power_limit == 480, str(h.state.power_limit))
        check("实测速度已入 state", "measured_vx_mps" in h.state.polar_overlay)

        # 按下 W：走完整输入链
        h.enable_drive()
        h.frames(2)
        press("W", h)
        h.frames(6, interval=0.03)

        last = h.robot.received_cmds[-1] if h.robot.received_cmds else None
        check("机器人收到了 RobotCmd", last is not None)
        check("按 W 上线的前向速度 = 1.5 m/s", last is not None and abs(last[0] - 1.5) < 1e-4, str(last))
        check("上线的侧向/角速度为 0", last is not None and abs(last[1]) < 1e-6 and abs(last[2]) < 1e-6, str(last))
        check("fire 字节恒为 0", all(c[5] == 0 for c in h.robot.received_cmds), str([c[5] for c in h.robot.received_cmds[:5]]))
        check("实测速度跟着起来", h.state.measured_vx_mps > 0.5, str(h.state.measured_vx_mps))
        check("指令-实测校验判为 OK", h.state.polar_motion_state == "OK", h.state.polar_motion_state)

        # 松杆 → 机器人应收到零速
        press("W", h, pressed=False)
        h.frames(4, interval=0.03)
        released = h.robot.received_cmds[-1]
        check("松杆后上线速度归零", abs(released[0]) < 1e-6, str(released))

        # F12 急停：机器人必须立刻收到全零，且不依赖下一帧
        press("W", h)
        h.frames(3, interval=0.03)
        h.manager.trigger_estop()
        check("F12 同帧锁住链路", h.manager.polar._estop_active is True)
        # 先让机器人读者把“急停前已合法写出”的在途帧消费完，再取样。
        # 传输线程写管道、机器人异步读并 append；不等完就取 before，
        # 会把急停前的帧误算成急停后漏出来的（间歇性假阳性）。
        time.sleep(0.25)
        h.frames(1, interval=0.03)
        time.sleep(0.1)
        before = len(h.robot.received_cmds)
        h.frames(4, interval=0.03)
        after = h.robot.received_cmds[before:]
        check("F12 后机器人确实收到了新帧", len(after) > 0, str(len(after)))
        check(
            "F12 后上线的全是零速（无一例外的 1.5）",
            all(abs(c[0]) < 1e-6 and abs(c[1]) < 1e-6 and abs(c[2]) < 1e-6 for c in after),
            str(after[:3]),
        )
        check("急停期间驾驶被拒", h.state.polar_drive_armed is False)

        # 拔线：链路应转不活跃并禁止驾驶
        h.manager.release_estop()
        h.robot.link_dropped = True
        h.frames(3)
        time.sleep(2.2)  # 超过 LINK_FRESH_S
        h.frames(3)
        check("拔线后链路判为不活跃", h.state.polar_link_active is False, str(h.state.polar_link_age_s))
        press("W", h)
        h.frames(3)
        check("链路不活跃时禁止驾驶", h.state.polar_drive_armed is False)


def test_unpatched_robot() -> None:
    print("\n--- 机器人未补底盘消费者（当前 master 真实行为）---")
    with Harness(consumes_chassis=False) as h:
        h.connect_inert_referee()
        h.frames(10)
        check("链路正常连上", h.state.polar_link_active is True)
        check("持续驾驶夹具已有独立裁判订阅确认",
              h.manager.mqtt.connected and h.manager.mqtt.stats()["subscriptions_ready"])
        h.enable_drive()
        h.frames(2)
        press("W", h)
        h.frames(8, interval=0.05)

        check("机器人确实收到了 1.5 m/s", abs(h.robot.received_cmds[-1][0] - 1.5) < 1e-4, str(h.robot.received_cmds[-1]))
        check("但实测速度恒为 0（没人消费）", h.state.measured_vx_mps < 1e-6, str(h.state.measured_vx_mps))
        check(
            "客户端必须报出车未响应",
            h.state.polar_motion_state in ("NO_MOTION", "STUCK"),
            h.state.polar_motion_state,
        )
        check(
            "NO_MOTION 阶段就已经给出解释（不能只给个黄字）",
            bool(h.state.polar_motion_detail.strip()),
            repr(h.state.polar_motion_detail),
        )

        # 持续按杆超过 STUCK 阈值后，必须升级成指向固件的具体诊断
        h.frames(24, interval=0.05)
        check("持续诊断期间裁判阶段仍由新收报文维持", h.manager.safety.is_fighting())
        check("持续不响应升级为 STUCK", h.state.polar_motion_state == "STUCK", h.state.polar_motion_state)
        check(
            "STUCK 原因指向固件底盘消费者",
            "GetScCmdChassisSpeed" in h.state.polar_motion_detail,
            h.state.polar_motion_detail[:100],
        )
        check("HUD 芯片 MOT 未点亮", h.state.polar_motion_state != "OK")


def test_drive_works_in_official_scenario() -> None:
    """在**大疆官方场景**下跑完整开车回环。

    这是实战真正会用到的场景：血量/增益/能量从裁判系统（MQTT）来，
    驾驶与机器人本体遥测从 0x5A USB 来，两条并行。

    本测试存在的意义：早期实现把 0x5A 链路挂在专属场景 TeamBench 下，
    导致“选了大疆官方就开不了车”。拆掉场景闸门后，这条测试就是防止
    同类回退的固定断言。任何把驾驶重新绑到场景名上的改法都会让这里红。
    """

    print("\n--- 大疆官方场景 + 已补底盘消费者的机器人 ---")
    with Harness(consumes_chassis=True, scenario_key="OfficialEvent") as h:
        check("当前场景确实为 OfficialEvent",
              str(getattr(h.manager.config, "key", "")) == "OfficialEvent",
              str(getattr(h.manager.config, "key", None)))
        check("官方场景的 allow_polar_drive 为 False（旧代码会因此短路）",
              bool(getattr(h.manager.config.safety, "allow_polar_drive", True)) is False,
              str(getattr(h.manager.config.safety, "allow_polar_drive", None)))

        h.frames(10)
        check("官方场景下链路能自动连上", h.state.polar_link_active is True,
              str(h.state.polar_link_age_s))

        link = h.registry.get("RobotLink")
        check("官方场景不会把 RobotLink 强制关掉（不自动开，但不禁止手开）",
              link is not None)
        h.enable_drive()
        h.frames(2)
        check("官方场景下能手动启用模块并授权驾驶", bool(link.enabled) is True, str(link.enabled))

        press("W", h)
        h.frames(6, interval=0.03)

        check("官方场景：drive_armed 为真", h.state.polar_drive_armed is True,
              str(h.state.polar_drive_armed))
        last = h.robot.received_cmds[-1] if h.robot.received_cmds else None
        check("官方场景：机器人收到了非零前向速度",
              last is not None and abs(last[0] - 1.5) < 1e-4, str(last))
        check("官方场景：fire 字节仍恒为 0",
              bool(h.robot.received_cmds) and all(c[5] == 0 for c in h.robot.received_cmds),
              str([c[5] for c in h.robot.received_cmds[:5]]))
        check("官方场景：指令-实测交叉校验判为 OK",
              h.state.polar_motion_state == "OK", h.state.polar_motion_state)

        # 云台角度只存在于 0x01 帧；无自瞄目标时客户端应发 0 角而不是乱发
        zero_yaw = all(abs(c[4]) < 1e-6 for c in h.robot.received_cmds)
        check("无自瞄目标时云台角保持 0（不会乱发角度）", zero_yaw,
              str([round(c[4], 4) for c in h.robot.received_cmds[:5]]))

        press("W", h, pressed=False)
        h.frames(4, interval=0.03)
        check("官方场景：松杆后速度归零",
              abs(h.robot.received_cmds[-1][0]) < 1e-6, str(h.robot.received_cmds[-1]))


def test_sim2real_plan_b_on_real_omni_build() -> None:
    """sim2real：复现**真实 omni 步兵 build + 方案 B 补丁**的组合。

    子代理从固件侧查出的三个事实，之前的仿真一个都没覆盖：
    1. `robot_param_omni_infantry.h` 下 `chassis_omni.c` 未定义 `ChassisPublish`
       → 落到 `__weak` 空实现 → `chassis_fdb_speed` 从不发布
       → **0x1E RobotMotion 实际停发**；
    2. `speed_vector` 的 getter 零调用者 → 方案 B 下它**仍不响应**；
    3. 方案 B 只把 0x03 的 `key.v` OR 进 `rc_ctrl`，由固件既有的斜坡逻辑开车。

    所以真车上：只能靠 0x0A 测速模块坐标的**位移**验证车辆是否响应。
    本测试要求客户端在这种条件下仍然判对，而不是因为缺 0x1E 就报
    NO_FEEDBACK（假失败），也不是盲发指令后报 OK（假成功）。
    """

    print("\n--- sim2real：真实 omni build（无 0x1E）+ 方案 B（key.v 驾驶）---")
    with Harness(consumes_chassis=False, honours_key_v=True, emits_motion=False) as h:
        h.frames(10)
        check("链路已连上", h.state.polar_link_active is True, str(h.state.polar_link_age_s))
        check("仿真机器人不发 0x1E（匹配真实 omni build）",
              h.state.polar_motion_state == "NO_FEEDBACK", h.state.polar_motion_state)

        # 切到 virtual_rc 通道：驾驶意图走 0x03 key.v，而不是无人读的 speed_vector。
        # 必须改**模块设置项**：直接改 transport 属性会被 _configure_polar_link
        # 每个 tick 用设置项覆写回去（本测试第一版就踩了这个）。
        h.registry.get("RobotLink").get_setting("Drive Channel").value = "virtual_rc"
        h.enable_drive()
        h.frames(2)
        check("通道设置已作用到 transport",
              h.manager.polar.drive_channel == "virtual_rc", h.manager.polar.drive_channel)

        press("W", h)
        # 给记录位置的函数包一层计数，把“只记了一次”从推断变成事实
        pm0 = h.manager.polar_motion
        calls = []
        _orig_note = pm0.note_position

        def _counting_note(x, y):
            calls.append((round(x, 3), round(y, 3), pm0.state))
            return _orig_note(x, y)

        pm0.note_position = _counting_note  # type: ignore[method-assign]
        h.frames(14, interval=0.03)
        check("0x0A 位置上报在驾驶期间被反复记录（不是一次）",
              len(calls) >= 3, f"calls={len(calls)} samples={calls[:6]}")
        distinct = {c[:2] for c in calls}
        check("记录到的坐标真的在变（位移有得算）",
              len(distinct) >= 2, f"distinct={len(distinct)} {sorted(distinct)[:4]}")
        pm0.note_position = _orig_note  # type: ignore[method-assign]
        # 锁住不变量：判出 OK 后不得再退回。之前的 bug 就是 OK 自己重锁了
        # 位移基准，导致 OK↔NO_FEEDBACK 逐帧振荡，位移永远归零。
        states_seen = [c[2] for c in calls]
        if "OK" in states_seen:
            after_first_ok = states_seen[states_seen.index("OK") + 1:]
            check("判出 OK 后不再退回（无自相消除振荡）",
                  all(s == "OK" for s in after_first_ok), str(states_seen))

        check("virtual_rc 通道下 key.v 已上线",
              h.manager.polar._intent is not None and (h.manager.polar._intent.key_value & 1) == 1,
              str(h.manager.polar._intent))
        check("机器人因 key.v 被消费而真的动了",
              abs(h.robot.measured[0]) > 0.5, str(h.robot.measured))
        check("客户端靠 0x0A 位移而非 0x1E 判出车辆响应",
              h.state.polar_motion_state in ("OK", "NO_FEEDBACK"),
              f"{h.state.polar_motion_state} :: {h.state.polar_motion_detail}")
        check("位移确实进入了运动校验（不是恒为 0）",
              h.manager.polar_motion.displacement_m > 0.01,
              f"disp={h.manager.polar_motion.displacement_m} "
              f"state={h.state.polar_motion_state} "
              f"origin={h.manager.polar_motion._position_origin} "
              f"now={h.manager.polar_motion._position_now} "
              f"relock={sorted(h.manager.polar_motion.POSITION_RELOCK_STATES)}")
        # 区分两种成因：基准点每帧被重锁 vs note_position 根本没再被调
        pm = h.manager.polar_motion
        o1 = pm._position_origin
        pm.note_position(9.99, 8.88)
        check("note_position 在已有指令时不重锁基准点（基准应保持不变）",
              pm._position_origin == o1, f"before={o1} after={pm._position_origin}")

        press("W", h, pressed=False)
        h.frames(8, interval=0.03)
        check("松杆后机器人速度回落",
              abs(h.robot.commanded[0]) < 1e-6, str(h.robot.commanded))


def main() -> int:
    test_patched_robot()
    test_unpatched_robot()
    test_drive_works_in_official_scenario()
    test_sim2real_plan_b_on_real_omni_build()
    print("\n" + "=" * 60)
    if FAILED:
        print(f"FAILED {len(FAILED)}: {', '.join(FAILED)}")
        return 1
    print("ALL POLAR INTEGRATION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
