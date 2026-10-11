"""队内 0x5A 链路（polar_link）离线单元验证。

不依赖 Qt / OpenGL / 串口硬件，纯 Python 可跑：

    python tests/polar_link_test.py

三件关键事情：
1. CRC 三方对拍 —— 本项目的 `crc8/crc16` vs 队内上位机工具
   `Serial_Port_Assistant/lib/CRC8_CRC16.py`（同一份 DJI C 查表实现的 Python 移植）。
   对拍通过才说明客户端与下位机用的是同一个校验函数。
2. 14 个「固件当前真的在发」的段，逐段构造固件形态的字节流再解码，字段级比对。
3. fire 位不变量 —— 无论怎么调用，上行 RobotCmd 的 fire 字节必须恒为 0。
"""

from __future__ import annotations

import io
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):  # Windows GBK 控制台兼容
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.backend import polar_link as pl  # noqa: E402
from rm_client.protocol import crc16, crc8  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[PASS] {name}")
    else:
        print(f"[FAIL] {name} {detail}")
        FAILED.append(name)


def load_team_crc():
    """尽力加载队内参考实现；缺失时返回 None（对拍降级为跳过，不算失败）。"""

    explicit = os.environ.get("POLAR_TEAM_CRC_REFERENCE")
    if explicit and not os.path.isfile(explicit):
        raise FileNotFoundError(f"Configured POLAR_TEAM_CRC_REFERENCE does not exist: {explicit}")
    candidates = [explicit] if explicit else [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            os.pardir, "tmp_polarbear", "Serial_Port_Assistant", "lib", "CRC8_CRC16.py",
        ),
    ]
    for path in candidates:
        if os.path.isfile(path):
            import importlib.util

            spec = importlib.util.spec_from_file_location("team_crc_ref", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            return module
    return None


# ----------------------------------------------------------------------
# 1. CRC 对拍
# ----------------------------------------------------------------------
def test_crc_cross_check() -> None:
    team = load_team_crc()
    if team is None:
        print("[SKIP] 未找到队内 CRC8_CRC16.py 参考实现，跳过三方对拍")
        return

    random.seed(20260901)
    crc8_ok = crc16_ok = True
    for _ in range(2000):
        size = random.randint(1, 40)
        data = bytes(random.randrange(256) for _ in range(size))
        if crc8(data) != team.GetCRC8(data):
            crc8_ok = False
        if crc16(data) != team.GetCRC16(data):
            crc16_ok = False
    check("CRC8 与队内实现逐字节一致", crc8_ok)
    check("CRC16 与队内实现逐字节一致", crc16_ok)


# ----------------------------------------------------------------------
# 帧构造工具：完全按固件的 len/校验语义拼字节
# ----------------------------------------------------------------------
def build_segment(segment_id: int, raw_timestamp: int, body: bytes) -> bytes:
    seg_len = 4 + len(body)
    header = bytes((pl.POLAR_SOF, seg_len & 0xFF, segment_id & 0xFF, 0x00))
    header = header[:3] + bytes((crc8(header[:3]),))
    frame = header + struct.pack("<I", raw_timestamp) + body
    return frame + crc16(frame).to_bytes(2, "little")


def decode_one(frame: bytes) -> pl.PolarSegment | None:
    codec = pl.PolarFrameCodec()
    segments, consumed = codec.decode_with_consumed(frame)
    check(
        f"段 0x{frame[2]:02X} 整帧一次性消费",
        consumed == len(frame),
        f"consumed={consumed} len={len(frame)}",
    )
    return segments[0] if segments else None


# ----------------------------------------------------------------------
# 2. 逐段解码
# ----------------------------------------------------------------------
def test_joint_state() -> None:
    body = struct.pack("<ff", 0.25, -1.5)  # pitch, yaw（顺序按 usb_typdef.h）
    segment = decode_one(build_segment(pl.SEG_JOINT_STATE, 12345, body))
    check("0x1D JointState 解出", segment is not None)
    if segment:
        check(
            "0x1D 字段与符号",
            abs(segment.fields["pitch_rad"] - 0.25) < 1e-6
            and abs(segment.fields["yaw_rad"] + 1.5) < 1e-6
            and segment.raw_timestamp == 12345,
            str(segment.fields),
        )


def test_imu() -> None:
    values = (0.1, -0.2, 0.3, 10.0, -20.0, 30.0)
    body = struct.pack("<6f", *values)
    segment = decode_one(build_segment(pl.SEG_IMU, 1, body))
    check("0x02 IMU 解出 6 个量", segment is not None and len(segment.fields) == 6)
    if segment:
        check(
            "0x02 yaw 与角速度",
            abs(segment.fields["yaw_rad"] - 0.1) < 1e-6
            and abs(segment.fields["roll_vel_rps"] - 30.0) < 1e-4,
            str(segment.fields),
        )


def test_robot_status() -> None:
    # robot_id, level, hp, maxhp, cooling, heat_limit, power, x, y, angle,
    # armor_packed, 17mm, 42mm, gold, fortress
    body = struct.pack(
        "<BBHHHHHfffBHHHH",
        1,
        3,
        400,
        480,
        40,
        120,
        280,
        3.5,
        -2.25,
        90.5,
        (7 << 4) | 5,  # armor_id=5, hp_deduction_reason=7
        300,
        40,
        12,
        60,
    )
    segment = decode_one(build_segment(pl.SEG_ROBOT_STATUS, 7, body))
    check("0x0A RobotStatus 解出", segment is not None)
    if segment:
        fields = segment.fields
        checks = {
            "robot_id": (fields["robot_id"], 1),
            "current_hp": (fields["current_hp"], 400),
            "barrel_heat_limit": (fields["barrel_heat_limit"], 120),
            "chassis_power_limit": (fields["chassis_power_limit"], 280),
            "x": (round(fields["x"], 4), 3.5),
            "angle_deg": (round(fields["angle_deg"], 4), 90.5),
            "armor_id": (fields["armor_id"], 5),
            "hp_deduction_reason": (fields["hp_deduction_reason"], 7),
            "projectile_allowance_42mm": (fields["projectile_allowance_42mm"], 40),
            "remaining_gold_coin": (fields["remaining_gold_coin"], 12),
        }
        bad = {k: v for k, v in checks.items() if v[0] != v[1]}
        check("0x0A 位域与全字段", not bad, str(bad))


def test_robot_state_info_bitfields() -> None:
    # chassis=2 gimbal=1 shoot=3 arm=0 custom=0 -> 2 | 1<<3 | 3<<6
    type_bits = 2 | (1 << 3) | (3 << 6)
    state_bits = 0b00010  # gimbal_error
    body = struct.pack("<HB", type_bits, state_bits)
    segment = decode_one(build_segment(pl.SEG_ROBOT_STATE_INFO, 5, body))
    check("0x03 解出", segment is not None)
    if segment:
        fields = segment.fields
        check(
            "0x03 位域按 LSB-first 拆分（与队内 data_procecss.py 同序）",
            fields["chassis_type"] == 2
            and fields["gimbal_type"] == 1
            and fields["shoot_type"] == 3
            and fields["arm_type"] == 0
            and fields["gimbal_error"] is True
            and fields["chassis_error"] is False,
            str(fields),
        )


def test_game_status_and_buff_and_extras() -> None:
    segment = decode_one(
        build_segment(pl.SEG_GAME_STATUS, 1, struct.pack("<BHQ", (4 << 4) | 2, 55000, 999))
    )
    check(
        "0x04 game_type/game_progress 位域",
        segment is not None
        and segment.fields["game_progress"] == 4
        and segment.fields["game_type"] == 2
        and segment.fields["stage_remain_time"] == 55000,
        str(segment.fields if segment else None),
    )

    segment = decode_one(
        build_segment(pl.SEG_BUFF, 1, struct.pack("<BHBBHB", 1, 2, 3, 0, 40, 60))
    )
    check(
        "0x0D Buff 字段",
        segment is not None
        and segment.fields["remaining_energy"] == 60
        and segment.fields["attack_buff"] == 40,
        str(segment.fields if segment else None),
    )

    segment = decode_one(
        build_segment(pl.SEG_SHOOT_DATA, 1, struct.pack("<BBBf", 0, 1, 10, 15.5))
    )
    check(
        "0x0F ShootData 初速/射速（自瞄与吊射标定真值）",
        segment is not None
        and segment.fields["initial_speed_mps"] == 15.5
        and segment.fields["launching_frequency_hz"] == 10,
        str(segment.fields if segment else None),
    )

    segment = decode_one(build_segment(pl.SEG_ALL_ROBOT_HP, 1, struct.pack("<8H", 1, 2, 3, 4, 0, 7, 80, 400)))
    check(
        "0x06 全场 HP 按 ally 序（仅己方）",
        segment is not None
        and segment.fields["ally_7_hp"] == 7
        and segment.fields["ally_base_hp"] == 400,
        str(segment.fields if segment else None),
    )

    segment = decode_one(build_segment(pl.SEG_RFID_STATUS, 1, struct.pack("<IB", 0x0000_0004, 1)))
    check(
        "0x11 RFID 状态",
        segment is not None and segment.fields["rfid_status"] == 4,
        str(segment.fields if segment else None),
    )

    segment = decode_one(build_segment(pl.SEG_GROUND_ROBOT_POSITION, 1, struct.pack("<10f", *([1.0] * 10))))
    check(
        "0x13 地面机器人位置",
        segment is not None and segment.fields["hero_x"] == 1.0,
        str(segment.fields if segment else None),
    )

    segment = decode_one(build_segment(pl.SEG_ROBOT_MOTION, 1, struct.pack("<fff", 1.0, 2.0, 3.0)))
    check(
        "0x1E RobotMotion vx/vy/wz",
        segment is not None and segment.fields["wz_rps"] == 3.0,
        str(segment.fields if segment else None),
    )

    segment = decode_one(build_segment(pl.SEG_EVENT, 1, struct.pack("<I", 0x1234)))
    check("0x07 Event", segment is not None and segment.fields["event_data"] == 0x1234)

    segment = decode_one(build_segment(pl.SEG_REFEREE_WARNING, 1, struct.pack("<BBB", 2, 5, 3)))
    check(
        "0x08 裁判警告",
        segment is not None and segment.fields["offending_robot_id"] == 5,
        str(segment.fields if segment else None),
    )


def test_debug_segment() -> None:
    body = b""
    for name, kind, value in ((b"loop_time", 1, 1.5), (b"counter", 0, 7.0), (b"", 1, 9.0)):
        chunk = bytearray(15)
        chunk[0:10] = name.ljust(10, b"\x00")[:10]
        chunk[10] = kind
        chunk[11:15] = struct.pack("<f", value)
        body += bytes(chunk)
    body += b"\x00" * (15 * 10 - len(body))
    segment = decode_one(build_segment(pl.SEG_DEBUG, 1, bytes(body)))
    check("0x01 Debug 解出", segment is not None)
    if segment:
        packages = segment.fields["packages"]
        check(
            "0x01 具名浮点位（空名被丢弃）",
            packages.get("loop_time") == 1.5 and "counter" in packages and "" not in packages,
            str(packages),
        )


# ----------------------------------------------------------------------
# 3. 流式与异常输入
# ----------------------------------------------------------------------
def test_stream_split_and_resync() -> None:
    good = build_segment(pl.SEG_JOINT_STATE, 1, struct.pack("<ff", 0.5, 0.5))
    # 噪声里故意掺入 0x5A，才能真正走到「SOF 对但 CRC8 错」的重同步分支
    noise = bytes((0x00, 0xFF, pl.POLAR_SOF, 0x2B, 0x0A, 0x00, 0x5A, 0x11))
    stream = noise + good + good

    # 逐字节喂入，模拟串口分片
    codec = pl.PolarFrameCodec()
    buffer = bytearray()
    found = 0
    for byte in stream:
        buffer.append(byte)
        segments, consumed = codec.decode_with_consumed(bytes(buffer))
        found += len(segments)
        if consumed:
            del buffer[:consumed]
    check("噪声前缀 + 逐字节分片仍解出 2 段", found == 2, f"found={found}")
    check(
        "假 SOF 只造成有限次 crc8 失败，不崩不丢后续帧",
        codec.stats.crc8_errors >= 2,
        str(codec.stats.__dict__),
    )

    # 半帧必须保留、不误消费
    codec = pl.PolarFrameCodec()
    segments, consumed = codec.decode_with_consumed(good[:-1])
    check("半帧不消费", segments == [] and consumed == 0, f"consumed={consumed}")

    # 篡改一字节 -> CRC16 失败并计数，不抛异常
    corrupt = bytearray(good)
    corrupt[6] ^= 0x01
    codec = pl.PolarFrameCodec()
    try:
        segments, _ = codec.decode_with_consumed(bytes(corrupt))
        check("损坏帧被丢弃且计数", segments == [] and codec.stats.crc16_errors >= 1, str(codec.stats.__dict__))
    except Exception as exc:  # pragma: no cover
        check("损坏帧被丢弃且计数", False, f"抛异常 {exc!r}")

    # 未知段（固件已定义但当前注释不发）应安全跳过
    codec = pl.PolarFrameCodec()
    segments, _ = codec.decode_with_consumed(build_segment(0x0B, 1, struct.pack("<HHfHH", 1, 2, 3.0, 4, 5)))
    check("未启用段跳过不报错", segments == [] and codec.stats.unknown_segments == 1)

    # 长度不符
    codec = pl.PolarFrameCodec()
    segments, _ = codec.decode_with_consumed(build_segment(pl.SEG_JOINT_STATE, 1, struct.pack("<fff", 1, 2, 3)))
    check("载荷长度不符被拒", segments == [] and codec.stats.length_errors == 1)


# ----------------------------------------------------------------------
# 4. 上行 RobotCmd 布局与 fire 不变量
# ----------------------------------------------------------------------
ROBOT_CMD_FRAME_LEN = 49
FIRE_BYTE_OFFSET = 4 + 4 + 36  # 帧头 + 时间戳 + 9 个 float


def _field_bytes(frame: bytes) -> dict[str, float]:
    body = frame[8:8 + 39]
    (vx, vy, wz, roll, pitch, yaw, leg, g_pitch, g_yaw) = struct.unpack("<9f", body[:36])
    fire, fric, tracking = body[36], body[37], body[38]
    return {
        "vx": vx, "vy": vy, "wz": wz,
        "roll": roll, "chassis_pitch": pitch, "chassis_yaw": yaw, "leg": leg,
        "gimbal_pitch": g_pitch, "gimbal_yaw": g_yaw,
        "fire": fire, "fric_on": fric, "tracking": tracking,
    }


def test_robot_cmd_layout() -> None:
    codec = pl.PolarFrameCodec()
    frame = codec.encode_robot_cmd(
        raw_timestamp=42,
        gimbal_pitch_rad=0.1,
        gimbal_yaw_rad=-0.2,
        chassis_vx=1.0,
        chassis_vy=-0.5,
        chassis_wz=0.25,
        friction_on=True,
        tracking=True,
    )
    check("RobotCmd 整帧 49 字节", len(frame) == ROBOT_CMD_FRAME_LEN, str(len(frame)))
    check("SOF 为 0x5A", frame[0] == pl.POLAR_SOF)
    check("len 字段 = 4 + 39 = 43", frame[1] == 43, str(frame[1]))
    check("id 字段 = 0x01 且位于帧头内", frame[2] == pl.CMD_ROBOT)
    check("帧头 CRC8 自校验通过", crc8(frame[:3]) == frame[3])
    check("整帧 CRC16 自校验通过", crc16(frame[:-2]) == struct.unpack("<H", frame[-2:])[0])

    fields = _field_bytes(frame)
    check(
        "9 个浮点字段顺序正确",
        (fields["vx"], fields["vy"], fields["wz"]) == (1.0, -0.5, 0.25)
        and abs(fields["gimbal_pitch"] - 0.1) < 1e-6
        and abs(fields["gimbal_yaw"] + 0.2) < 1e-6,
        str(fields),
    )
    check("fric_on / tracking 可置位", fields["fric_on"] == 1 and fields["tracking"] == 1)
    check("未显式给的 chassis 姿态/腿长保持 0", fields["leg"] == 0.0 and fields["roll"] == 0.0)


def test_fire_bit_invariant() -> None:
    """无论怎么调，fire 必须恒 0；且签名不得暴露 fire 参数。"""

    codec = pl.PolarFrameCodec()
    import inspect

    signature = inspect.signature(codec.encode_robot_cmd)
    check("encode_robot_cmd 签名不含 fire 参数", "fire" not in signature.parameters)

    random.seed(7)
    violations = 0
    for _ in range(500):
        frame = codec.encode_robot_cmd(
            raw_timestamp=random.randrange(1 << 32),
            gimbal_pitch_rad=random.uniform(-3.14, 3.14),
            gimbal_yaw_rad=random.uniform(-3.14, 3.14),
            chassis_vx=random.uniform(-4, 4),
            chassis_vy=random.uniform(-4, 4),
            chassis_wz=random.uniform(-4, 4),
            friction_on=random.random() < 0.5,
            tracking=random.random() < 0.5,
        )
        if frame[FIRE_BYTE_OFFSET] != 0:
            violations += 1
    check("500 组随机输入 fire 字节恒为 0", violations == 0, f"violation={violations}")


def test_timestamp_monotonic_contract() -> None:
    """固件 RECEIVE_TIME 只在帧内 time_stamp 严格递增时刷新（usb_task.c:699-702），
    因此客户端必须提供跨重启仍单调的毫秒时间戳。这里锁住该契约。"""

    from rm_client.backend.polar_transport import PolarTimestamp

    stamp = PolarTimestamp()
    values = [stamp.next() for _ in range(2000)]
    check("2000 次调用严格递增", all(b > a for a, b in zip(values, values[1:])))
    check(
        "发出的值始终可打包为 u32",
        all(0 <= v <= 0xFFFFFFFF for v in values),
        str(values[:3]),
    )
    check("未跨回绕边界时不报 roll", stamp.roll_detected is False)

    # 同一毫秒内连续调用也必须严格变大（系统时钟粒度不够时靠虚拟计数器）
    same_ms = PolarTimestamp()
    fast = [same_ms.next() for _ in range(3)]
    check("同一实例连续调用仍逐次变大", fast[0] < fast[1] < fast[2], str(fast))

    # 模拟「上一会话已发到很高值 / 时钟被往回调」：用持久化的 floor 续接
    last_from_previous_session = 0xFFFF_FFF0
    restart = PolarTimestamp(floor=last_from_previous_session)
    first = restart.next()
    check(
        "带 floor 续接后仍大于上一会话末值",
        first > last_from_previous_session,
        f"first={first} floor={last_from_previous_session}",
    )

    # 跨过 u32 边界：回绕无法在 u32 线缆上隐瞒，必须标出来让链路停驾驶
    wrap = PolarTimestamp(floor=0xFFFF_FFFD)
    seq = [wrap.next() for _ in range(4)]
    check("跨 u32 边界时 roll_detected 置位", wrap.roll_detected is True, str(seq))
    check("回绕后发出的值仍是合法 u32", all(0 <= v <= 0xFFFFFFFF for v in seq), str(seq))

    # 急停/退出用的零帧也必须带递增时间戳，否则零帧会被固件当旧帧丢掉
    codec = pl.PolarFrameCodec()
    clock = PolarTimestamp()
    stamps = []
    for _ in range(5):
        frame = codec.encode_robot_cmd(
            raw_timestamp=clock.next(), gimbal_pitch_rad=0.0, gimbal_yaw_rad=0.0
        )
        stamps.append(struct.unpack_from("<I", frame, 4)[0])
    check("零帧时间戳序列也严格递增", all(b > a for a, b in zip(stamps, stamps[1:])), str(stamps))


def test_unit_conversion_guard() -> None:
    """PRM1 用百分度、固件 RobotCmd 用弧度 —— 混用会差 57.3 倍。"""

    check("deg->rad 正确", abs(pl.deg_to_rad(180.0) - 3.141592653589793) < 1e-9)
    check("rad->deg 正确", abs(pl.rad_to_deg(1.0) - 57.29577951308232) < 1e-9)
    check("往返一致", abs(pl.rad_to_deg(pl.deg_to_rad(37.5)) - 37.5) < 1e-9)


def test_virtual_rc_layout() -> None:
    """上行 0x03 虚拟遥控器帧：必须与固件 `RC_ctrl_t` 逐字节对齐。

    固件只需把这一帧的 `key.v` 灌进 `rc_ctrl`，就能复用 chassis_omni.c 里
    已经生效的 WASD 驾驶（带斜坡与限幅），代价远小于新写 speed_vector 消费者。
    """

    codec = pl.PolarFrameCodec()
    frame = codec.encode_virtual_rc(raw_timestamp=0x11223344, key_value=0x000F,
                                    channels=(100, -200, 300, -400, 500),
                                    switches=(1, 3))
    check("VirtualRC 整帧 32 字节", len(frame) == 32, str(len(frame)))
    check("SOF=0x5A", frame[0] == pl.POLAR_SOF)
    check("len 字段 = 26", frame[1] == 26, str(frame[1]))
    check("id 字段 = 0x03", frame[2] == pl.CMD_VIRTUAL_RC)
    check("帧头 CRC8 自洽", crc8(frame[:3]) == frame[3])
    check("整帧 CRC16 自洽", crc16(frame[:-2]) == struct.unpack("<H", frame[-2:])[0])
    check("时间戳落在偏移 4", struct.unpack_from("<I", frame, 4)[0] == 0x11223344)
    ch = struct.unpack_from("<5h", frame, 8)
    check("ch[5] 为 int16 LE", ch == (100, -200, 300, -400, 500), str(ch))
    s = struct.unpack_from("<2b", frame, 18)
    check("s[2] 为 int8", s == (1, 3), str(s))
    key = struct.unpack_from("<H", frame, 28)[0]
    check("key.v 在偏移 28、为 u16", key == 0x000F, hex(key))
    check("mouse/press 默认全零", frame[20:28] == bytes(8), frame[20:28].hex())


def test_key_bit_order_matches_official_keyboard() -> None:
    """固件 `rc_ctrl.key.v` 位序必须与官方 keyboard_value 位序一致。

    否则客户端算好的位图塞进 0x03 会按错键位开车（比如 W 变成 A）。
    """

    from rm_client.control import KEYBOARD_BITS

    mismatched = {k: (v, pl.RC_KEY_BITS.get(k)) for k, v in KEYBOARD_BITS.items()
                  if pl.RC_KEY_BITS.get(k) != v}
    check("RC_KEY_BITS 与官方 KEYBOARD_BITS 位序逐项一致", not mismatched, str(mismatched))

    # 实际打包：W+D 应该置 bit0|bit3 = 0x09
    packed = pl.rc_key_value({"W": True, "D": True, "A": False, "S": False})
    check("W+D 打包为 0x09", packed == 0x09, hex(packed))
    check("空输入为 0", pl.rc_key_value({}) == 0)

    # 安全掩码：固件对 Q/E/SHIFT/F 有真实动作（Q 启动摩擦轮 = 开火前置执行器），
    # 客户端绝不允许把这些位透传过去。
    check("掩码只含 W/S/A/D 四位", pl.RC_DRIVE_KEY_MASK == 0x000F, hex(pl.RC_DRIVE_KEY_MASK))
    for name in ("Q", "E", "SHIFT", "F", "CTRL", "R", "G", "Z", "X", "C", "V", "B"):
        value = pl.rc_key_value({name: True})
        if value != 0:
            check(f"{name} 被掩码拦下", False, hex(value))
            break
    else:
        check("Q/E/SHIFT/F 等所有非驾驶键均被掩码拦下", True)
    check(
        "全 16 键同时按下也只漏出 W/S/A/D",
        pl.rc_key_value({k: True for k in pl.RC_KEY_BITS}) == 0x0F,
        hex(pl.rc_key_value({k: True for k in pl.RC_KEY_BITS})),
    )

    # 编码器边界也要拦：不能只靠调用方自觉
    codec = pl.PolarFrameCodec()
    frame = codec.encode_virtual_rc(raw_timestamp=1, key_value=0xFFFF)
    leaked = struct.unpack_from("<H", frame, 28)[0]
    check("encode_virtual_rc 在字节层也强制裁到 0x0F", leaked == 0x0F, hex(leaked))


def main() -> int:
    tests = [
        test_crc_cross_check,
        test_joint_state,
        test_imu,
        test_robot_status,
        test_robot_state_info_bitfields,
        test_game_status_and_buff_and_extras,
        test_debug_segment,
        test_stream_split_and_resync,
        test_robot_cmd_layout,
        test_fire_bit_invariant,
        test_timestamp_monotonic_contract,
        test_unit_conversion_guard,
        test_virtual_rc_layout,
        test_key_bit_order_matches_official_keyboard,
    ]
    for test in tests:
        print(f"\n--- {test.__name__} ---")
        test()
    print("\n" + "=" * 60)
    if FAILED:
        print(f"FAILED {len(FAILED)}: {', '.join(FAILED)}")
        return 1
    print("ALL POLAR_LINK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

