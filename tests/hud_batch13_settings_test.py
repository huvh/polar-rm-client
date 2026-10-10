"""第 13 批验收：地图标记的 Mark Type / Send All 接到真实报文上。

上一轮我断言"地图标记连协议编码都没有"——那是错的。我搜的是
`map_command` / `0x0106` 这两个本仓库根本不存在的名字；真实报文叫
`MapClickCmd`，编码器、发布函数、点击入口都在，而且一直在发。
所以那 3 项被错分成"B 类无法接"。

本文件最重要的两条断言是：

    1. 默认配置下编出来的字节，与接线前那对硬编码值逐字节相同。
       这条守住"接线不得顺带改变比赛行为"。
    2. 改设置项后，字段真的变了，且 decode(encode(x)) == x
       —— 证明改动真的落到了线上，而不是只写了个返回值。

    python tests/hud_batch13_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b13_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.backend import protocol as proto  # noqa: E402
from rm_client.model import build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class Host(TacticalMapMixin):
    def __init__(self) -> None:
        self.registry = build_default_registry()

    def set(self, setting: str, value) -> None:
        mod = self.registry.get("MapMarker")
        assert mod is not None
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, setting
        st.value = value


def field(payload: bytes, number: int):
    """把编码结果按 wire 编号读回单个值。

    用本仓库自己的 `decode_fields`，不另写一套 protobuf 解析。
    它返回 dict[int, list[value]]，所以取 [0]。
    """
    fields = proto.decode_fields(payload)
    values = fields.get(number)
    return values[0] if values else None


# ---------------------------------------------------------------------------
def test_default_bytes_are_unchanged_by_wiring() -> None:
    """默认设置编出的字节必须与接线前硬编码值逐字节相同。

    这是本批的核心安全约束：发送处原先硬写 `is_send_all=1`（全队广播）。
    如果照设置项原来的默认 False 去接，就会把广播变成单发——
    一个"接线"顺手改掉了比赛行为，而且没人会往这上面怀疑。
    """
    host = Host()
    is_send_all, mark_type = host.map_click_command_values()
    check("默认 Send All 推导出广播（与接线前硬编码 1 一致）",
          is_send_all == 1, str(is_send_all))
    check("默认 Mark Type 推导出 1（与接线前硬编码 1 一致）",
          mark_type == 1, str(mark_type))

    legacy = proto.encode_map_click_cmd(
        is_send_all=1, mode=1, mark_type=1, map_x=12.5, map_y=3.25
    )
    now = proto.encode_map_click_cmd(
        is_send_all=is_send_all, mode=1, mark_type=mark_type, map_x=12.5, map_y=3.25
    )
    check("默认配置下 MapClickCmd 逐字节不变",
          legacy == now, f"{legacy.hex()} vs {now.hex()}")


def test_settings_change_the_actual_wire_fields() -> None:
    """改设置项必须真的落到报文里（编完再解回来核对）。"""
    host = Host()

    host.set("Send All", False)
    is_send_all, _ = host.map_click_command_values()
    check("关掉 Send All 推导出 0（单发）", is_send_all == 0, str(is_send_all))

    host.set("Send All", True)
    assert host.map_click_command_values()[0] == 1

    for label, code in (("Attack", 1), ("Defense", 2), ("Warning", 3), ("Custom", 4)):
        host.set("Mark Type", label)
        got = host.map_click_command_values()[1]
        check(f"Mark Type={label} 推导出 type={code}", got == code, str(got))

    # 端到端：编码 -> 解码，字段值确实在线上
    host.set("Mark Type", "Warning")
    send_all, mark_type = host.map_click_command_values()
    payload = proto.encode_map_click_cmd(
        is_send_all=send_all, mode=1, mark_type=mark_type, map_x=8.0, map_y=4.0
    )
    check("编码结果里字段 6（type）确实是 3",
          field(payload, 6) == 3, str(field(payload, 6)))
    check("编码结果里字段 1（is_send_all）确实是 1",
          field(payload, 1) == 1, str(field(payload, 1)))

    # 关掉广播后线上字段也要跟着变
    host.set("Send All", False)
    send_all, mark_type = host.map_click_command_values()
    payload = proto.encode_map_click_cmd(
        is_send_all=send_all, mode=1, mark_type=mark_type, map_x=8.0, map_y=4.0
    )
    check("关掉广播后字段 1 变成 0", field(payload, 1) == 0, str(field(payload, 1)))
    check("关掉广播不影响 type（字段之间不得串扰）",
          field(payload, 6) == 3, str(field(payload, 6)))


def test_unknown_or_missing_values_fall_back_to_legacy_bytes() -> None:
    """脏值/缺设置时必须回落到接线前那对硬编码值，不得发出去路不明的 type。"""
    host = Host()
    host.set("Mark Type", "没这个选项")
    send_all, mark_type = host.map_click_command_values()
    check("未知 Mark Type 回落到 1（Attack，等于接线前）",
          mark_type == 1, str(mark_type))
    check("回落时广播仍保持默认开", send_all == 1, str(send_all))

    host.set("Mark Type", "Defense")
    host.set("Send All", "不是布尔")
    send_all, _ = host.map_click_command_values()
    check("Send All 是垃圾值时按真值判断，不抛异常",
          send_all in (0, 1), str(send_all))

    # 模块被禁用时本谓词不改口：是否允许外发由发送入口与安全层判定，
    # 不在这个取值函数里做双重判断。
    probe = Host()
    probe.registry.get("MapMarker").enabled = False
    check("模块 disabled 时谓词仍只看设置项（避免双重判定）",
          probe.map_click_command_values()[1] == 1)


def main() -> int:
    tests = [
        test_default_bytes_are_unchanged_by_wiring,
        test_settings_change_the_actual_wire_fields,
        test_unknown_or_missing_values_fall_back_to_legacy_bytes,
    ]
    for test in tests:
        print(f"\n--- {test.__name__} ---")
        test()
    print("\n" + "=" * 60)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for name in FAILED:
            print(f"  - {name[:130]}")
        return 1
    print("ALL BATCH-13 MAP-MARKER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
