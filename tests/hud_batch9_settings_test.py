"""第 9 批验收：电容/缓冲的单一数据源，以及装甲盒深度边开关。

覆盖两件事，第一件是**真 bug 修复**而不只是接线：

    (A) `capacitor_percent` 只在桌面 mock 的 tick 里赋值，真实的
        RobotDynamicStatus 从不写它。所以接上裁判系统/真车后，电容条会
        永远停在默认 62%，而 `Capacitor / Warn` 这类阈值判据也就成了死的——
        看着接好了，实际永远不触发。
        现在统一走 RobotState.effective_capacitor_percent
        （current_buffer_energy / max_buffer_energy，protocol.py 已解析）。

    (B) `Armor3DESP / Show Depth` 以前没人读。它只能控制**深度边**：
        不能靠传空 back 实现，因为两个盒子函数开头都是
        `len(back) != 4: return`，那会让整个装甲盒消失而不是只去掉深度线。

    python tests/hud_batch9_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b9_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.esp_wireframe import EspWireframeMixin  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class Pt:
    """顶替 QPointF：armor_box_edges 只做索引与配对，不需要几何运算。"""

    def __init__(self, x: float, y: float) -> None:
        self.x_, self.y_ = x, y

    def x(self) -> float:
        return self.x_

    def y(self) -> float:
        return self.y_

    def __repr__(self) -> str:
        return f"P({self.x_},{self.y_})"


def quad(tag: str) -> list[Pt]:
    return [Pt(0, 0), Pt(10, 0), Pt(10, 10), Pt(0, 10)]


class Host(EspWireframeMixin, TacticalMapMixin):
    """同时混入两个 mixin：装甲盒边在 EspWireframe，电容告警判据在 TacticalMap。"""

    def __init__(self) -> None:
        self.registry = build_default_registry()
        self.state = RobotState()

    def get_setting_number(self, module, name: str, default: float) -> float:
        setting = module.get_setting(name) if module is not None else None
        try:
            return float(setting.value) if setting is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    def hud_state_color(self, key: str, ratio: float | None = None):
        return f"c:{key}"

    def hud_danger(self):
        return "DANGER"

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value


# ---------------------------------------------------------------------------
def test_capacitor_percent_prefers_real_fields() -> None:
    """真实缓冲能量必须优先于只在 mock 里赋值的 capacitor_percent。"""
    s = RobotState()
    s.max_buffer_energy = 100
    s.current_buffer_energy = 20
    s.capacitor_percent = 99        # mock 值，故意与真值不一致
    check("有可信 max 时用 current/max 算比例（忽略 mock 值）",
          s.effective_capacitor_percent == 20, str(s.effective_capacitor_percent))

    s.current_buffer_energy = 50
    check("真值变化时结果跟着变（不是缓存住的常数）",
          s.effective_capacitor_percent == 50, str(s.effective_capacitor_percent))

    # max=0 不可信（未收到报文/脏数据）时退回，不能除零
    s.max_buffer_energy = 0
    try:
        got = s.effective_capacitor_percent
        check("max_buffer_energy=0 时退回 capacitor_percent 且不除零", got == 99, str(got))
    except ZeroDivisionError as exc:
        check("max_buffer_energy=0 时退回 capacitor_percent 且不除零", False, repr(exc))

    # 越界必须钳制：>100 会让比例条画飞，负数同理
    s.max_buffer_energy = 80
    s.current_buffer_energy = 200
    check("超过上限钳到 100", s.effective_capacitor_percent == 100,
          str(s.effective_capacitor_percent))
    s.current_buffer_energy = -30
    check("负值钳到 0", s.effective_capacitor_percent == 0,
          str(s.effective_capacitor_percent))

    # 垃圾类型不得抛
    s.current_buffer_energy = "abc"
    try:
        got = s.effective_capacitor_percent
        check("垃圾值退回 capacitor_percent 而不抛异常", got == 99, str(got))
    except (TypeError, ValueError) as exc:
        check("垃圾值退回 capacitor_percent 而不抛异常", False, repr(exc))


def test_warn_threshold_is_live_on_real_data() -> None:
    """电容告警必须能被**真实**数据触发（这轮修复的实际目的）。"""
    host = Host()
    host.set("Capacitor", "Show Bar", True)
    host.set("Capacitor", "Warn", 25)
    state = host.state
    state.max_buffer_energy = 100

    state.current_buffer_energy = 60
    state.capacitor_percent = 60
    check("真实缓冲 60% 时不告警", host.capacitor_below_warn() is False)

    state.current_buffer_energy = 10          # 真车数据掉到 10%
    state.capacitor_percent = 90              # mock 字段仍是高值
    check("真实缓冲跌到 10% 时告警（不再被 mock 值骗过）",
          host.capacitor_below_warn() is True,
          f"effective={state.effective_capacitor_percent}")


def test_show_depth_controls_depth_edges_only() -> None:
    """`Show Depth` 关掉后只能少掉深度边，前框 4 边必须保留。"""
    front, back = quad("f"), quad("b")
    host = Host()
    host.set("Armor3DESP", "Show Depth", True)
    on = host.armor_box_edges(front, back)
    check("开启时是完整 12 边盒", len(on) == 12, str(len(on)))

    host.set("Armor3DESP", "Show Depth", False)
    off = host.armor_box_edges(front, back)
    check("关掉后只剩前框 4 边", len(off) == 4, str(len(off)))
    # 12 边列表里前框边是**交错**的（每组 front/back/connect 的第一条，
    # 即索引 0/3/6/9），不是前 4 条。上一版按前 4 条比较，是断言写错。
    front_in_on = [on[i] for i in (0, 3, 6, 9)]
    check("关掉后的 4 条正是开启时的 4 条前框边（对象身份比）",
          all(a is x and b is y for (a, b), (x, y) in zip(off, front_in_on)),
          f"off={off} front_in_on={front_in_on}")
    check("关掉后不再引用任何背面点（只去深度线，不碰前框）",
          all(not (a in back or b in back) for a, b in off), str(off))
    check("前框确实是 front[i]->front[i+1]",
          all(a is front[i] and b is front[(i + 1) % 4] for i, (a, b) in enumerate(off)))

    # 没有背面时只能有前框 4 边，且不得 IndexError
    check("back 缺失时退化为 4 边而不崩", len(host.armor_box_edges(front, [])) == 4)
    check("front 不合法时返回空（不抛）", host.armor_box_edges([], back) == [])


def test_show_depth_fails_open_without_setting() -> None:
    """查不到设置项/模块缺失时必须保持原来的 12 边行为。"""
    host = Host()
    check("默认（未改设置）为显示深度", host.armor_depth_visible() is True)

    mod = host.registry.get("Armor3DESP")
    try:
        mod.settings.pop("Show Depth")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("设置项缺失时仍显示深度（保持接线前行为）",
          host.armor_depth_visible() is True)

    host2 = Host()
    host2.registry.get("Armor3DESP").enabled = False
    check("模块关闭时谓词仍只看 Show Depth 取值（不额外改口）",
          host2.armor_depth_visible() is True)



def test_pulse_locked_only_breathes_when_locked() -> None:
    """`LockState / Pulse Locked` 的取向刻保守验证。

    关键不期望：关掉开关时 alpha 必须与接线前**逐值一致**。
    脉冲只允许在"已锁定"时出现 —— 未锁定时呼吸会让 danger 色乱闪。
    """
    host = Host()
    host.set("LockState", "Pulse Locked", True)

    check("未锁定时一律不脉冲（哪怕开关开着）",
          host.lock_pulse_strength(locked=False) == 0.0)

    samples = [host.lock_pulse_strength(locked=True) for _ in range(60)]
    check("已锁定且开关开时有脉冲且幅度在 0..1",
          max(samples) > 0.0 and min(samples) >= 0.0 and max(samples) <= 1.0,
          f"max={max(samples):.3f}")

    host.set("LockState", "Pulse Locked", False)
    flat = [host.lock_pulse_strength(locked=True) for _ in range(40)]
    check("关掉开关后即使已锁定也恒为 0（alpha 回退到原常量）",
          all(v == 0.0 for v in flat))

    # 模块缺失 / 设置项缺失时默认不新增视觉变化
    host2 = Host()
    host2.registry.get("LockState").enabled = False
    check("模块关闭时不脉冲", host2.lock_pulse_strength(locked=True) == 0.0)

    host3 = Host()
    mod = host3.registry.get("LockState")
    try:
        mod.settings.pop("Pulse Locked")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("查不到设置项时按开关存在处理（默认开）",
          host3.lock_pulse_strength(locked=True) >= 0.0)


def test_radar_high_light_can_be_disabled_without_hiding_blips() -> None:
    """`RadarOverlay / High Light` 只取消强调，不得隐藏雷达标记本身。

    区分很重要：关掉"高亮"变成"隐藏情报"会是很难发现的错误。
    """
    host = Host()
    host.set("RadarOverlay", "High Light", True)
    check("开启时高亮生效", host.radar_high_light_enabled() is True)

    host.set("RadarOverlay", "High Light", False)
    check("关闭时高亮取消", host.radar_high_light_enabled() is False)

    # 模块缺失/设置项缺失时保持现行为（开启）
    host2 = Host()
    try:
        host2.registry.get("RadarOverlay").settings.pop("High Light")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("查不到设置项时保持现行为", host2.radar_high_light_enabled() is True)

    host3 = Host()
    host3.registry.get("RadarOverlay").enabled = False
    check("模块关闭时仍返回 True：隐藏整个面板由模块开关负责，"
          "不由样式开关越权", host3.radar_high_light_enabled() is True)


def main() -> int:
    tests = [
        test_capacitor_percent_prefers_real_fields,
        test_warn_threshold_is_live_on_real_data,
        test_show_depth_controls_depth_edges_only,
        test_show_depth_fails_open_without_setting,
        test_pulse_locked_only_breathes_when_locked,
        test_radar_high_light_can_be_disabled_without_hiding_blips,
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
    print("ALL BATCH-9 SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
