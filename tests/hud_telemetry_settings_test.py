"""HUD 遥测面板设置项接线验收（第 2 批）。

覆盖 4 个原本是装饰的设置项：

    Capacitor / Show Bar     关掉后 CAP 行仍然照画
    Capacitor / Warn         拖 0~100% 无人读，电容见底也不变色
    PowerLimit / Show Limit  关掉后 POWER 行仍然照画
    （PowerLimit / Pulse Overrun 本批**未做**，见 tools/SETTINGS_GAPS.md）

关键要求不只是"接上"，而是**两个构造器行为一致**：
`map_telemetry_status_rows`（小地图侧）与 `draw_telemetry_strip`（遥测条）
各建一份卡片。如果只改一处，同一个滑块会"在一处有效、一处无效"——
那比统一不接更坑，因为它会让人以为开关坏了。

不构造真实窗口：只子类化 TacticalMapMixin，桩掉颜色与读值辅助函数。

    python tests/hud_telemetry_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_hudset_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class Host(TacticalMapMixin):
    """最小桩：只提供被测函数用到的依赖。"""

    def __init__(self) -> None:
        self.registry = build_default_registry()
        self.state = RobotState()
        self._animated: dict[str, float] = {}

    def get_setting_number(self, module, name: str, default: float) -> float:
        setting = module.get_setting(name) if module is not None else None
        if setting is None:
            return float(default)
        try:
            return float(setting.value)
        except (TypeError, ValueError):
            return float(default)

    def setting_bool(self, module, name: str, default: bool = True) -> bool:
        setting = module.get_setting(name) if module is not None else None
        return bool(setting.value) if setting is not None else default

    def hud_state_color(self, key: str, ratio: float | None = None):
        return f"state:{key}"

    def hud_danger(self):
        return "DANGER"

    def hud_warning(self):
        return "WARNING"

    def hud_accent(self):
        return "ACCENT"

    def animated_scalar(self, key: str, target: float, rate: float) -> float:
        return float(target)

    def opacity(self) -> float:
        return 1.0

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value

    def labels(self) -> list[str]:
        return [row[0] for row in self.map_telemetry_status_rows()]

    def cap_row(self):
        for row in self.map_telemetry_status_rows():
            if row[0] == "CAP":
                return row
        return None

    def power_row(self):
        for row in self.map_telemetry_status_rows():
            if row[0] == "POWER":
                return row
        return None


def set_capacitor(host, percent: int) -> None:
    """驱动电容/缓冲百分比的**真实来源**。

    `capacitor_percent` 只在 mock tick 里赋值，真实 RobotDynamicStatus 从不写它；
    现在统一走 RobotState.effective_capacitor_percent（current/max_buffer_energy）。
    上一版测试直接改 capacitor_percent，等于把"接真车后电容是死的"这个 bug
    固化成了期望值。
    """
    host.state.max_buffer_energy = 100
    host.state.current_buffer_energy = int(percent)
    host.state.capacitor_percent = int(percent)


# ---------------------------------------------------------------------------
def test_show_bar_toggle_hides_the_capacitor_row() -> None:
    """`Capacitor / Show Bar` 关掉后，CAP 行必须从小地图遥测里消失。"""
    host = Host()
    host.set("Capacitor", "Show Bar", True)
    set_capacitor(host, 60)
    check("Show Bar 打开时有 CAP 行", "CAP" in host.labels(), str(host.labels()))

    host.set("Capacitor", "Show Bar", False)
    check("Show Bar 关闭后 CAP 行消失（开关真的影响画面）",
          "CAP" not in host.labels(), str(host.labels()))

    # 关掉 CAP 不能连带影响别的行
    host.set("PowerLimit", "Show Limit", True)
    check("关掉 CAP 不影响 POWER 行", "POWER" in host.labels(), str(host.labels()))

    # 模块整体关闭时本来就不该有
    self_off = Host()
    self_off.registry.get("Capacitor").enabled = False
    check("Capacitor 模块关闭时也没有 CAP 行",
          "CAP" not in self_off.labels(), str(self_off.labels()))


def test_show_limit_toggle_hides_the_power_row() -> None:
    """`PowerLimit / Show Limit` 关掉后，POWER 行必须消失。"""
    host = Host()
    host.set("PowerLimit", "Show Limit", True)
    host.state.chassis_power_w = 50
    host.set("PowerLimit", "Limit", 80)
    check("Show Limit 打开时有 POWER 行", "POWER" in host.labels(), str(host.labels()))

    host.set("PowerLimit", "Show Limit", False)
    check("Show Limit 关闭后 POWER 行消失",
          "POWER" not in host.labels(), str(host.labels()))
    check("关掉 POWER 不影响 CAP 行", "CAP" in host.labels(), str(host.labels()))


def test_capacitor_warn_threshold_forces_danger_color() -> None:
    """`Capacitor / Warn` 必须真的改变颜色，且方向正确（低=危险）。"""
    host = Host()
    host.set("Capacitor", "Show Bar", True)
    host.set("Capacitor", "Warn", 25)

    # 40% > 25% -> 不告警
    set_capacitor(host, 40)
    row = host.cap_row()
    check("电容 40% 高于阈值 25% 时不告警",
          row is not None and row[3] != "DANGER", str(None if row is None else row[3]))

    # 20% < 25% -> 告警
    set_capacitor(host, 20)
    row = host.cap_row()
    check("电容 20% 低于阈值 25% 时用告警色（阈值真的生效）",
          row is not None and row[3] == "DANGER", str(None if row is None else row[3]))

    # 把阈值调高，应该更容易告警 —— 方向不能反
    set_capacitor(host, 40)
    host.set("Capacitor", "Warn", 50)
    row = host.cap_row()
    check("调高阈值到 50% 后，40% 电容也告警（方向正确）",
          row is not None and row[3] == "DANGER", str(None if row is None else row[3]))

    # Warn=0 表示关闭告警
    host.set("Capacitor", "Warn", 0)
    check("阈值 0 = 关闭告警，不因为等于 0 就永远告警",
          not host.capacitor_below_warn())

    # 垃圾值不得崩
    host.set("Capacitor", "Warn", "abc")
    try:
        below = host.capacitor_below_warn()
        check("垃圾阈值归为不告警且不抛异常", below is False, str(below))
    except Exception as exc:  # noqa: BLE001
        check("垃圾阈值归为不告警且不抛异常", False, repr(exc))


def test_both_telemetry_builders_agree() -> None:
    """两个构造器必须对同一套开关给出一致结论。

    `draw_telemetry_strip` 会真的画到屏幕上（需要 QPainter），这里只验证
    它使用的两个判据函数与行构造器共用同一实现，从而行为必然一致。
    """
    host = Host()
    cap = host.registry.get("Capacitor")
    power = host.registry.get("PowerLimit")

    for show_bar, show_limit in ((True, True), (False, True), (True, False), (False, False)):
        host.set("Capacitor", "Show Bar", show_bar)
        host.set("PowerLimit", "Show Limit", show_limit)
        set_capacitor(host, 10)
        host.set("Capacitor", "Warn", 25)

        labels = set(host.labels())
        # 判据函数（strip 用的就是这两个）
        visible_cap = host.telemetry_panel_visible(cap, "Show Bar")
        visible_power = host.telemetry_panel_visible(power, "Show Limit")
        check(
            f"开关组合 (Bar={show_bar}, Limit={show_limit}) 下行构造器与判据函数一致",
            (("CAP" in labels) == visible_cap) and (("POWER" in labels) == visible_power),
            f"labels={sorted(labels)} cap_visible={visible_cap} power_visible={visible_power}",
        )
        # 告警谓词与“是否显示”无关：模块开着、电容 10% <= 阈值 25%，它就是该告警。
        # 上一版把两者相乘去判，是错的：隐藏时谓词仍应为 True，只是没人看而已。
        check(
            f"({show_bar}/{show_limit}) 告警谓词与 Show Bar 无关（电容 10% 低于 25% 就为 True）",
            host.capacitor_below_warn() is True,
            str(host.capacitor_below_warn()),
        )
        # 真正该验的是可见性：行存在时颜色必须是 DANGER；行不存在时不应存在
        row = host.cap_row()
        if visible_cap:
            check(f"({show_bar}/{show_limit}) CAP 行可见且为告警色",
                  row is not None and row[3] == "DANGER",
                  str(None if row is None else row[3]))
        else:
            check(f"({show_bar}/{show_limit}) CAP 行隐藏时不产出任何颜色",
                  row is None, str(row))


def test_module_with_no_show_setting_stays_visible() -> None:
    """没有"显示"开关的模块不得因查不到设置而被默认隐藏。"""
    host = Host()
    speed = host.registry.get("SpeedLimit")
    host.state.speed_limit = 5
    visible = host.telemetry_panel_visible(speed, "这个开关根本不存在")
    check("查不到 Show * 设置时返回 True（不默认隐藏）", visible is True, str(visible))
    check("模块为 None 时返回 False",
          host.telemetry_panel_visible(None, "Show Bar") is False)


def main() -> int:
    tests = [
        test_show_bar_toggle_hides_the_capacitor_row,
        test_show_limit_toggle_hides_the_power_row,
        test_capacitor_warn_threshold_forces_danger_color,
        test_both_telemetry_builders_agree,
        test_module_with_no_show_setting_stays_visible,
    ]
    for test in tests:
        print(f"\n--- {test.__name__} ---")
        test()
    print("\n" + "=" * 60)
    if FAILED:
        print(f"FAILED {len(FAILED)}")
        for name in FAILED:
            print(f"  - {name[:120]}")
        return 1
    print("ALL HUD-TELEMETRY SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
