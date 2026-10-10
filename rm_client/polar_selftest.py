"""台架/实车队内链路自检：一条命令产出可分析的验收证据。

    python main.py --polar-selftest --polar-port Auto --polar-seconds 3
    python main.py --polar-selftest --polar-enable-drive --polar-confirm-motion

设计前提（决定了本文件的形状）：

1. **无头运行**。不 import Qt、不建窗口，因此在显卡/OpenGL 有问题的车上机器
   也能跑；也不会在自检时弹出界面抢驾驶员注意力。
2. **只碰队内链路**。直接用 `PolarLinkTransport` + `PolarStateBridge`，不经过
   `BackendManager`，因此不会顺带打开 MQTT/裁判串口 —— 台架上常常没有裁判机。
3. **默认只读**。运动回环需要 `--polar-enable-drive` 与 `--polar-confirm-motion`
   两个开关同时给出，且必须先通过安全前置检查（链路新鲜、机器人无部件错误）。
   任何情况下都不发 fire（编码器签名不暴露该参数）。
4. **输出是证据草稿，不是权威证据**。`authoritative: False` 是刻意的：项目里
   只有带 HMAC 与双人署名的 `QualificationManager` 才能铸造现场证据，自检结果
   不得绕过那条链，否则 fail-closed 设计就白做了。
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backend.polar_bridge import (
    SEGMENT_NAMES,
    PolarControlArbiter,
    PolarMotionVerifier,
    PolarStateBridge,
)
from .backend.polar_link import (
    SEG_IMU,
    SEG_JOINT_STATE,
    SEG_ROBOT_MOTION,
    SEG_ROBOT_STATUS,
)
from .backend.polar_transport import PolarDriveIntent, PolarLinkTransport
from .serial_ports import describe_ports, list_serial_ports, resolve_port

# 运动回环的硬上限：即使开关都打开，也不允许大幅长时驱动。
# 脉冲长度取 0.8s：太短的话机器人还在加速阶段，实测还没进阈值就会
# 被误判为“未响应”；宁可观察久一点，也不靠压低阈值来“判过”。
MOTION_PULSE_MPS = 0.30
MOTION_PULSE_S = 0.80
MOTION_TOTAL_BUDGET_S = 2.50
GIMBAL_PULSE_DEG = 4.0
# 认为“车确实动了”的最小实测速度增量。远高于静止漂移，又远低于指令值。
MOVED_THRESHOLD_MPS = 0.08
GIMBAL_MOVED_THRESHOLD_DEG = 1.0

# 自检通过的判定所需的最小段集合：缺这些就没法确认机器人身份/姿态。
REQUIRED_SEGMENTS = (SEG_ROBOT_STATUS, SEG_IMU, SEG_JOINT_STATE)

EXIT_OK = 0
EXIT_CONNECT_FAILED = 2
EXIT_DOWNLINK_INCOMPLETE = 3
EXIT_NO_MOTION_RESPONSE = 4
EXIT_SAFETY_BLOCKED = 5


@dataclass
class SelftestResult:
    started_at: float = field(default_factory=time.time)
    port_requested: str = ""
    port_resolved: str = ""
    detected_ports: list[str] = field(default_factory=list)
    connected: bool = False
    phases: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    exit_code: int = EXIT_OK
    finished_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        # 规格状态必须出现在自检报告里：代码在规格坏掉时会回退到内置表继续跑，
        # 不回显的话，电控改完 JSON 会看到“一均正常”但自己的修改其实没生效。
        from .backend import polar_link

        spec_status = dict(polar_link.SPEC_STATUS)
        return {
            "kind": "polar_link_selftest",
            "authoritative": False,
            "protocol_spec": {
                "loaded": bool(spec_status.get("ok")),
                "fell_back_to_builtin": bool(spec_status.get("fell_back")),
                "source": spec_status.get("source", ""),
                "errors": spec_status.get("errors", ""),
                "warnings": spec_status.get("warnings", ""),
                "segment_count": len(polar_link._SEGMENT_FORMATS),
            },
            "note": (
                "本文件是台架自检证据草稿。正式现场证据必须由 QualificationManager "
                "以 HMAC 签名记录并经操作员与安全负责人双人署名，不得由自检直接铸造。"
            ),
            "started_at": round(self.started_at, 3),
            "finished_at": round(self.finished_at or time.time(), 3),
            "duration_s": round((self.finished_at or time.time()) - self.started_at, 3),
            "port_requested": self.port_requested,
            "port_resolved": self.port_resolved,
            "detected_ports": self.detected_ports,
            "connected": self.connected,
            "phases": self.phases,
            "problems": self.problems,
            "exit_code": self.exit_code,
        }


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def run_polar_selftest(
    *,
    port: str = "Auto",
    seconds: float = 3.0,
    enable_drive: bool = False,
    confirm_motion: bool = False,
    baud: int = 115200,
    send_hz: float = 50.0,
    log: Any = print,
) -> SelftestResult:
    """跑一次队内链路自检并返回结构化结果。

    无论中途成功、异常还是被中断，`finally` 都会先发归零再关端口 —— 固件侧
    没有断流归零，自检工具绝不能成为把机器人留在运动指令上的那一方。
    """

    result = SelftestResult(port_requested=port)
    result.detected_ports = describe_ports()
    transport = PolarLinkTransport(
        port=port, baud=baud, mock_writes=False, send_hz=send_hz
    )
    bridge = PolarStateBridge()
    arbiter = PolarControlArbiter()
    motion = PolarMotionVerifier()

    try:
        # ---------------- 阶段 1：发现与连接 ----------------
        resolved = resolve_port(port)
        result.port_resolved = resolved
        transport.port = port
        transport.start()
        result.connected = bool(transport.connected)
        result.port_resolved = transport.resolved_port or resolved
        result.phases["connect"] = {
            "connected": result.connected,
            "resolved_port": transport.resolved_port or resolved,
            "error": transport.last_error,
            "error_code": transport.last_error_code,
            "send_hz": transport.send_hz,
            "detected_ports": [
                {
                    "device": str(entry["device"]),
                    "description": str(entry["description"]),
                    "vid": int(entry["vid"]),
                    "pid": int(entry["pid"]),
                }
                for entry in list_serial_ports()
            ],
        }
        if not result.connected:
            result.problems.append(
                f"无法连接机器人串口（请求 {port} → 解析 {result.port_resolved}）："
                f"{transport.last_error}"
            )
            result.exit_code = EXIT_CONNECT_FAILED
            return result
        log(f"[1/5] 已连接 {transport.resolved_port or result.port_resolved}")

        # ---------------- 阶段 2：下行接收 ----------------
        deadline = time.perf_counter() + max(0.5, float(seconds))
        while time.perf_counter() < deadline:
            _pump_once(transport, bridge, motion)
            time.sleep(0.01)

        counts = dict(bridge.segment_counts)
        missing = [
            SEGMENT_NAMES.get(seg, f"0x{seg:02X}")
            for seg in REQUIRED_SEGMENTS
            if counts.get(seg, 0) == 0
        ]
        decode = bridge_stats(transport)
        result.phases["downlink"] = {
            "listened_s": round(float(seconds), 2),
            "segment_counts": {
                SEGMENT_NAMES.get(seg, f"0x{seg:02X}"): int(n) for seg, n in sorted(counts.items())
            },
            "required_missing": missing,
            "dropped": bridge.dropped,
            "link_active": bridge.active,
            "link_age_s": round(bridge.link_age_s, 3),
            "decode_errors": decode,
        }
        log(f"[2/5] 收到 {len(counts)} 类数据段：{sorted(SEGMENT_NAMES.get(s, hex(s)) for s in counts)}")
        if decode.get("crc16_errors", 0) or decode.get("crc8_errors", 0):
            result.problems.append(
                f"下行存在校验错误：CRC8={decode.get('crc8_errors')} CRC16={decode.get('crc16_errors')}"
                "（多为波特率/线缆/接地问题）"
            )
        if missing:
            result.problems.append(f"缺少必需数据段：{missing}")
            result.exit_code = EXIT_DOWNLINK_INCOMPLETE
            return result

        # ---------------- 阶段 3：解码合理性 ----------------
        overlay = bridge.overlay
        sanity: dict[str, Any] = {
            # 机器人自报编号现在存在 polar_reported_robot_id（不再覆盖操作员选的
            # robot_id）；兼容读旧键，避免规格/桥接层版本错配时自检直接拿不到编号。
            "robot_id": int(
                overlay.get("polar_reported_robot_id")
                or overlay.get("robot_id", 0)
                or 0
            ),
            "current_hp": int(overlay.get("current_health", 0) or 0),
            "chassis_power_limit": int(overlay.get("power_limit", 0) or 0),
            "projectile_allowance_17mm": int(overlay.get("projectile_allowance_17mm", 0) or 0),
            "projectile_allowance_42mm": int(overlay.get("projectile_allowance_42mm", 0) or 0),
            "chassis_yaw_deg": round(float(overlay.get("chassis_yaw_deg", 0.0)), 3),
            "gimbal_yaw_deg": round(float(overlay.get("gimbal_yaw_deg", 0.0)), 3),
            "gimbal_pitch_deg": round(float(overlay.get("gimbal_pitch_deg", 0.0)), 3),
            "module_errors": dict(bridge.module_errors),
            "has_motion_feedback": SEG_ROBOT_MOTION in counts,
            # 0x0A 带测速模块 x/y；缺 0x1E 时可用位移作为“车动没动”的证据
            "has_position_feedback": (
                SEG_ROBOT_STATUS in counts
                and _finite(overlay.get("polar_self_x"))
                and _finite(overlay.get("polar_self_y"))
            ),
            "position_evidence_m": round(float(motion.displacement_m), 4),
            "values_finite": all(
                _finite(overlay.get(key))
                for key in ("chassis_yaw_deg", "gimbal_yaw_deg", "gimbal_pitch_deg")
            ),
        }
        result.phases["decode_sanity"] = sanity
        log(
            f"[3/5] 机器人 #{sanity['robot_id']} HP={sanity['current_hp']} "
            f"功率限={sanity['chassis_power_limit']} 云台={sanity['gimbal_yaw_deg']}°"
        )
        if not sanity["values_finite"]:
            result.problems.append("姿态字段出现非有限值（NaN/Inf），解码或固件数据异常")
            result.exit_code = EXIT_DOWNLINK_INCOMPLETE
            return result
        if any(bridge.module_errors.values()):
            result.problems.append(f"机器人上报部件错误：{bridge.module_errors}")

        # ---------------- 阶段 4：控制回环（默认跳过） ----------------
        wants_motion = bool(enable_drive and confirm_motion)
        if not wants_motion:
            result.phases["control_loopback"] = {
                "skipped": True,
                "reason": (
                    "默认只读。运动回环需同时给出 --polar-enable-drive 与 "
                    "--polar-confirm-motion"
                ),
            }
            log("[4/5] 控制回环：跳过（只读模式）")
        else:
            gate = _motion_gate(bridge, sanity)
            if gate:
                result.phases["control_loopback"] = {"skipped": True, "reason": gate}
                result.problems.append(f"控制回环被安全前置拦下：{gate}")
                result.exit_code = EXIT_SAFETY_BLOCKED
                log(f"[4/5] 控制回环：拒绝 —— {gate}")
            else:
                log("[4/5] 控制回环：开始（短脉冲，随后立即归零）")
                outcome = _run_control_loopback(transport, bridge, motion, arbiter, log)
                result.phases["control_loopback"] = outcome
                if outcome.get("verdict") == "NO_MOTION_RESPONSE":
                    result.problems.append(
                        "机器人收到了底盘速度但未响应：固件 GetScCmdChassisSpeed/"
                        "GetScCmdChassisVelocity 无消费者，需电控补接线"
                    )
                    result.exit_code = EXIT_NO_MOTION_RESPONSE

        # ---------------- 阶段 5：急停与归零 ----------------
        transport.trigger_estop()
        estop_frames = _collect_after_zero(transport)
        result.phases["estop"] = {
            "estop_latched": bool(transport._estop_active),
            "zero_frames_written": estop_frames,
            "intent_cleared": transport._intent is None,
        }
        log("[5/5] 急停：已锁存并下发归零帧")
        if estop_frames <= 0:
            result.problems.append("急停后未观察到归零帧写出")
        return result
    finally:
        # 先发归零再关口：绝不能把机器人留在最后一条运动指令上。
        try:
            transport.stop()
        except Exception as exc:  # pragma: no cover
            result.problems.append(f"关闭链路异常：{exc!r}")
        result.finished_at = time.time()


def _motion_gate(bridge: PolarStateBridge, sanity: dict[str, Any]) -> str:
    """运动前置条件。返回非空字符串表示拒绝原因。"""

    if not bridge.active:
        return "链路不新鲜，无法确认机器人当前状态"
    if any(bridge.module_errors.values()):
        return f"机器人上报部件错误：{bridge.module_errors}"
    if int(sanity.get("robot_id", 0) or 0) <= 0:
        return "尚未收到有效的本机机器人编号，无法确认连的是哪台车"
    if not sanity.get("has_motion_feedback") and not sanity.get("has_position_feedback"):
        return (
            "既没有 0x1E 速度回读，也没有 0x0A 测速模块坐标：运动结果无法验证，"
            "为避免盲开拒绝发运动指令"
        )
    return ""


def _run_control_loopback(
    transport: PolarLinkTransport,
    bridge: PolarStateBridge,
    motion: PolarMotionVerifier,
    arbiter: PolarControlArbiter,
    log: Any,
) -> dict[str, Any]:
    """短脉冲底盘 + 云台，观察回读。总时长受 MOTION_TOTAL_BUDGET_S 硬约束。"""

    started = time.perf_counter()
    observed: list[dict[str, Any]] = []
    written_before = transport.frames_sent

    def pump(duration: float, intent_factory: Any) -> None:
        """每个循环轮次都构造一份**新鲜**意图。

        传输层有 0.2s 的本地看门狗：`PolarDriveIntent.produced_at` 太旧会被
        当作“客户端已停止下发”而改发零帧。复用同一个 intent 对象会使得
        脉冲只有前 0.2s 有效 —— 那是看门狗的正确行为，不是它的 bug。
        """

        end = time.perf_counter() + duration
        while time.perf_counter() < end:
            if intent_factory is not None:
                transport.submit(intent_factory())
            _pump_once(transport, bridge, motion)
            time.sleep(0.01)

    zero = lambda: PolarDriveIntent()  # noqa: E731
    try:
        # 先送一段零帧，确认基线静止
        pump(0.20, zero)
        baseline = float(bridge.overlay.get("measured_vx_mps", 0.0) or 0.0)

        pulse = lambda: PolarDriveIntent(vx=MOTION_PULSE_MPS)  # noqa: E731
        pump(
            min(MOTION_PULSE_S, max(0.05, MOTION_TOTAL_BUDGET_S - (time.perf_counter() - started))),
            pulse,
        )
        peak = float(bridge.overlay.get("measured_vx_mps", 0.0) or 0.0)
        # 位移峰值必须在推杆期间取。末尾那段归零会把状态改回 OK，
        # 而 OK 属于“没在推杆”——参考点会被重锁，位移归零，之后就再也读不到了。
        displacement_peak = float(motion.displacement_m)
        observed.append(
            {
                "phase": "forward_pulse",
                "commanded_mps": MOTION_PULSE_MPS,
                "measured_peak_mps": round(peak, 4),
                "displacement_peak_m": round(displacement_peak, 4),
            }
        )
        log(
            f"      前向脉冲：指令 {MOTION_PULSE_MPS} m/s，实测峰值 {peak:.3f} m/s，"
            f"位移 {displacement_peak:.3f} m"
        )

        # 云台小角度阶跃
        arbiter.request_takeover(client_gimbal_enabled=True, vision_nuc_occupied=False)
        target_yaw = float(bridge.overlay.get("gimbal_yaw_deg", 0.0) or 0.0) + GIMBAL_PULSE_DEG
        gimbal_start = float(bridge.overlay.get("gimbal_yaw_deg", 0.0) or 0.0)
        from .backend.polar_link import deg_to_rad

        pump(0.60, lambda: PolarDriveIntent(gimbal_yaw_rad=deg_to_rad(target_yaw), tracking=True))
        gimbal_end = float(bridge.overlay.get("gimbal_yaw_deg", 0.0) or 0.0)
        observed.append(
            {
                "phase": "gimbal_step",
                "commanded_delta_deg": GIMBAL_PULSE_DEG,
                "measured_delta_deg": round(gimbal_end - gimbal_start, 3),
            }
        )
        log(f"      云台阶跃：指令 +{GIMBAL_PULSE_DEG}°，实测 {gimbal_end - gimbal_start:+.2f}°")
    finally:
        # 无论前面是否异常，一律回到零并让机器人静止
        pump(0.25, zero)

    moved_by_speed = abs(peak - baseline) >= MOVED_THRESHOLD_MPS
    moved_by_position = displacement_peak >= PolarMotionVerifier.DISPLACEMENT_THRESHOLD_M
    moved = moved_by_speed or moved_by_position
    gimbal_moved = abs(gimbal_end - gimbal_start) >= GIMBAL_MOVED_THRESHOLD_DEG
    frames_written = transport.frames_sent - written_before
    return {
        "skipped": False,
        "verdict": "OK" if moved else "NO_MOTION_RESPONSE",
        "chassis_responded": moved,
        "responded_by_speed": moved_by_speed,
        "responded_by_position": moved_by_position,
        "gimbal_responded": gimbal_moved,
        "baseline_mps": round(baseline, 4),
        "peak_mps": round(peak, 4),
        "gimbal_delta_deg": round(gimbal_end - gimbal_start, 3),
        "observations": observed,
        "frames_written": frames_written,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "moved_threshold_mps": MOVED_THRESHOLD_MPS,
        "gimbal_moved_threshold_deg": GIMBAL_MOVED_THRESHOLD_DEG,
        "motion_state": motion.state,
        "evidence": motion.stats().get("evidence"),
        "displacement_m": round(displacement_peak, 4),
    }


def _collect_after_zero(transport: PolarLinkTransport) -> int:
    """急停后强制刷出归零突发帧，返回写出的帧数增量。"""

    before = transport.frames_sent
    for _ in range(6):
        transport._pump_tx(time.perf_counter())
        time.sleep(0.005)
    return transport.frames_sent - before


def _pump_once(
    transport: PolarLinkTransport,
    bridge: PolarStateBridge,
    motion: PolarMotionVerifier,
) -> None:
    for segment in transport.drain_segments():
        bridge.apply(segment)
        if segment.segment_id == SEG_ROBOT_MOTION:
            motion.note_motion_segment()
        elif segment.segment_id == SEG_ROBOT_STATUS:
            motion.note_position(
                bridge.overlay.get("polar_self_x", 0.0),
                bridge.overlay.get("polar_self_y", 0.0),
            )
    motion.update(
        link_active=bridge.active,
        commanded_vx=float(transport._intent.vx) if transport._intent else 0.0,
        commanded_vy=float(transport._intent.vy) if transport._intent else 0.0,
        commanded_wz=float(transport._intent.wz) if transport._intent else 0.0,
        measured_vx=bridge.overlay.get("measured_vx_mps"),
        measured_vy=bridge.overlay.get("measured_vy_mps"),
        measured_wz=bridge.overlay.get("measured_wz_rps"),
    )


def bridge_stats(transport: PolarLinkTransport) -> dict[str, int]:
    stats = transport.codec.stats
    return {
        "frames_ok": stats.frames_ok,
        "crc8_errors": stats.crc8_errors,
        "crc16_errors": stats.crc16_errors,
        "unknown_segments": stats.unknown_segments,
        "length_errors": stats.length_errors,
        "buffer_overflows": stats.buffer_overflows,
    }


def write_selftest_report(output: Path, result: SelftestResult) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


__all__ = [
    "EXIT_CONNECT_FAILED",
    "EXIT_DOWNLINK_INCOMPLETE",
    "EXIT_NO_MOTION_RESPONSE",
    "EXIT_OK",
    "EXIT_SAFETY_BLOCKED",
    "SelftestResult",
    "run_polar_selftest",
    "write_selftest_report",
]
