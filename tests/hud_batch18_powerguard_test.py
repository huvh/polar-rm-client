"""第 18 批验收：`PowerGuard / Heat Warn`、`Energy Warn` 接通。

这两项是**孤儿名单里的特殊一例**：模块 `PowerGuard` 默认是**关**的，
所以接线本身不改变任何人的画面；但今天一旦有人把它打开，界面上那两个
阈值（热量警告 180 / 能量警告 20%）**什么都不会发生**——一个名叫
"功率保护"的模块开着却没有任何可见效果，这比"滑块没反应"更误导人。

接法（三条都要被断言钉住）：
  1. **只有模块开着才参与**；模块关着 = 与接线前逐值相同。
  2. **只能加严，不能放松**：颜色用 `max(ratio, 0.78)` 顶档，不返外来色，
     所以已在 danger 档时不会被降级成 warning。
  3. 阈值方向：热量与电容**相反**（热量越高越险、电容越低越险），
     两个都必须显式判，不能把 ratio 直接丢给按"高为险"设计的调色函数。

电容阈值有两个来源（`Capacitor/Warn` 与 `PowerGuard/Energy Warn`），
两者都在时取**更严的那个**；这个策略也由断言固定，避免以后被"顺手改成取小"。

配色用的是**真实的** `hud_state_color`（绑真方法 + 桩调色板），不是桩一个
符号色——否则"顶档"这件事根本没被测到。

    python tests/hud_batch18_powerguard_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b18_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.module_list import ModuleListMixin  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402
from rm_client.ui.polar_app import PolarRMWindow  # noqa: E402

FAILED: list[str] = []

ACCENT = "#101010"
WARNING = "#202020"
DANGER = "#303030"


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class FakeConfig:
    def __init__(self, key: str) -> None:
        self.key = key
        self.title = "3v3" if key == "RMUL3v3" else "7v7"


class FakeModeManager:
    def __init__(self, key: str) -> None:
        self.current = FakeConfig(key)


class Host(ModuleListMixin, TacticalMapMixin):
    """最小桩宿主：调色与分档用**真**实现，只桩外部依赖。"""

    hud_state_color = PolarRMWindow.hud_state_color

    def __init__(self, mode_key: str = "RMUL7v7", clean: bool = True) -> None:
        self.registry = build_default_registry()
        self.state = RobotState()
        self.match_mode_manager = FakeModeManager(mode_key)
        self._clean = clean

    # 真 hud_state_color 只依赖这个调色板元组
    def _hud_style_palette(self):
        return ("info", self._clean, ACCENT, WARNING, DANGER, "#404040")

    def hud_clean(self) -> bool:
        return self._clean

    def hud_accent(self):
        return ACCENT

    def hud_warning(self):
        return WARNING

    def hud_danger(self):
        return DANGER

    def get_setting_number(self, module, name: str, default: float) -> float:
        setting = module.get_setting(name) if module is not None else None
        if setting is None:
            return float(default)
        try:
            return float(setting.value)
        except (TypeError, ValueError):
            return float(default)

    def animated_scalar(self, key: str, target: float, rate: float) -> float:
        return float(target)

    # 这两个格式化助手在 widget 层而非本 mixin，桩成确定性输出。
    def short_ring_number(self, value) -> str:
        return str(int(float(value)))

    def short_outpost_value(self) -> str:
        return "7/7"

    def alliance_side(self) -> str:
        return "Red"

    def guard(self, *, enabled: bool, heat_warn=None, energy_warn=None) -> None:
        """配置 PowerGuard：模块开关 + 两个阈值。"""
        module = self.registry.get("PowerGuard")
        assert module is not None
        module.enabled = enabled
        if heat_warn is not None:
            module.get_setting("Heat Warn").value = heat_warn
        if energy_warn is not None:
            module.get_setting("Energy Warn").value = energy_warn

    def row_color(self, rows, label: str):
        for row in rows:
            if row[0] == label:
                return row[3]
        return None


def test_wiring_does_not_change_default_picture() -> None:
    """模块关着时，热量配色必须与接线前**逐值相同**（清爽与遗留两种风格都测）。"""
    for clean in (True, False):
        host = Host(clean=clean)
        host.guard(enabled=False, heat_warn=180)
        for ratio in (0.0, 0.5, 0.77, 0.79, 0.91, 0.95):
            check(f"模块关着、clean={clean} 时比例 {ratio} 配色不变",
                  host.heat_display_color(ratio) == host.hud_state_color("heat", ratio),
                  f"{host.heat_display_color(ratio).name()} vs {host.hud_state_color('heat', ratio).name()}")
        check("默认配置下 PowerGuard 就是关着的", host.registry.get("PowerGuard").enabled is False)


def test_absolute_threshold_escalates_heat() -> None:
    host = Host()
    host.state.max_heat = 240.0
    host.guard(enabled=True, heat_warn=180)

    host.state.current_heat = 100.0
    check("热量 100 未达阈值 180 -> 不额外告警（比例只有 0.42）",
          host.heat_over_warn() is False and host.heat_display_color(100 / 240).name().upper() == ACCENT,
          host.heat_display_color(100 / 240).name())

    host.state.current_heat = 180.0
    check("热量刚到阈值 180 就告警（>= 边界含等号）", host.heat_over_warn() is True)
    check("比例只有 0.75 时被顶到 warning 档",
          host.heat_display_color(180 / 240).name().upper() == WARNING,
          host.heat_display_color(180 / 240).name())

    host.state.current_heat = 235.0
    check("已经在 danger 档时不得被降级成 warning",
          host.heat_display_color(235 / 240).name().upper() == DANGER,
          host.heat_display_color(235 / 240).name())


def test_threshold_direction_and_garbage_values() -> None:
    """方向必须"越高越险"，且垃圾值不能把告警反过来。"""
    host = Host()
    host.state.max_heat = 240.0
    host.guard(enabled=True, heat_warn=180)
    host.state.current_heat = 180.0
    check("阈值 180 时热量 180 告警", host.heat_over_warn() is True)

    host.guard(enabled=True, heat_warn=200)
    check("把阈值**调高**到 200 后不再告警（越高越宽松，方向正确）",
          host.heat_over_warn() is False)

    host.guard(enabled=True, heat_warn=100)
    check("把阈值**调低**到 100 后更早告警", host.heat_over_warn() is True)

    host.guard(enabled=True, heat_warn=0)
    check("阈值 0 = 关掉这项，不强行告警", host.heat_over_warn() is False)

    host.guard(enabled=True, heat_warn="不是数")
    check("垃圾阈值不致崩也不告警", host.heat_over_warn() is False)

    host.guard(enabled=False, heat_warn=1)
    host.state.current_heat = 240.0
    check("模块关闭后即使阈值极低也不参与", host.heat_over_warn() is False)


def test_every_heat_surface_uses_the_same_verdict() -> None:
    """多处热量配色必须同一结论，否则就是"一处有效一处无效"。

    顶栏与圆环行需要先关掉基地/前哨那几行：它们会把热量行挤掉
    （两个构造器都只取 `rows[:4]`）。那个预算限制是**另一个问题**，
    不由本批修，所以本文件末尾把它单独钉住、显式地记下来。
    """
    host = Host()
    host.state.max_heat = 240.0
    host.state.current_heat = 190.0
    host.guard(enabled=True, heat_warn=180)
    host.registry.get("ThermalPowerPanel").enabled = True
    host.registry.get("BaseOutpostStatus").enabled = False
    host.registry.get("EconomyPanel").enabled = False
    ratio = 190 / 240

    surfaces = {
        "小地图遥测行": host.row_color(host.map_telemetry_status_rows(), "HEAT"),
        "顶栏战况行": host.row_color(host.match_status_rows(), "HEAT/PWR"),
        "圆环战况行": host.row_color(host.match_status_ring_rows(), "HEAT"),
        "液态地图 HEAT": host.liquid_status_color("HEAT", ratio, ACCENT),
    }
    for label, color_value in surfaces.items():
        got = color_value.name().upper() if hasattr(color_value, "name") else str(color_value)
        check(f"{label} 同步进入告警色", got == WARNING, str(got))

    v3 = Host("RMUL3v3")
    v3.state.max_heat = 240.0
    v3.state.current_heat = 190.0
    v3.guard(enabled=True, heat_warn=180)
    v3.registry.get("VictoryPointStatus").enabled = False
    v3.registry.get("ThermalPowerPanel").enabled = True
    ring = v3.row_color(v3.match_status_ring_rows(), "HEAT")
    check("3v3 圆环行同样同步", hasattr(ring, "name") and ring.name().upper() == WARNING,
          str([r[0] for r in v3.match_status_ring_rows()]))


def test_power_row_is_not_collateral_damage() -> None:
    """功率行的颜色不得因热量阈值而变——只桩热量自己的判据。"""
    host = Host()
    host.state.max_heat = 240.0
    # 热量比例故意停在 0.42（比 0.78 的 warning 档低）：否则两边本来就是同一色，
    # “没变”与“没接线”看不出差别。
    host.state.current_heat = 100.0
    host.state.chassis_power_w = 100.0
    host.state.power_limit = 200
    host.guard(enabled=False, heat_warn=1)
    rows_off = host.map_telemetry_status_rows()
    host.guard(enabled=True, heat_warn=1)
    rows_on = host.map_telemetry_status_rows()
    power = host.row_color(rows_on, "POWER")
    same = host.row_color(rows_off, "POWER")
    check("打开 PowerGuard 热量阈值不改变功率行颜色",
          power is not None and same is not None and power.name() == same.name(),
          f"{power} vs {same}")
    heat_off = host.row_color(rows_off, "HEAT")
    heat_on = host.row_color(rows_on, "HEAT")
    check("但热量行自己确实变了（证明上面那条不是空比）",
          heat_off is not None and heat_on is not None and heat_off.name() != heat_on.name(),
          f"{heat_off} vs {heat_on}")


def test_known_limitation_row_budget_can_drop_the_heat_row() -> None:
    """已记录的限制（不本批修）：战况行只取前 4 行，默认配下热量行会被挤掉。

    这条断言故意“钉住一个不对的行为”：一旦有人改了预算，它会响，
    而不是让后来人误以为热量行在默认配置下真的看得到。
    """
    host = Host()
    host.state.max_heat = 240.0
    host.state.current_heat = 190.0
    host.guard(enabled=True, heat_warn=180)
    labels = [row[0] for row in host.match_status_rows()]
    check("默认配下 7v7 顶栏拿不到热量行（四行预算限制）",
          "HEAT/PWR" not in labels, str(labels))


def test_capacitor_threshold_takes_the_stricter_of_two() -> None:
    """电容阈值有两个来源，都在时取更严的那个；都关时不告警。"""
    cap = lambda host: host.capacitor_below_warn()

    host = Host()
    host.state.max_buffer_energy = 100
    host.state.current_buffer_energy = 20
    host.guard(enabled=False, energy_warn=20)
    cap_mod = host.registry.get("Capacitor")
    cap_mod.enabled = False
    check("两个模块都关着 -> 不告警（=接线前行为）", cap(host) is False)

    cap_mod.enabled = True
    cap_mod.get_setting("Warn").value = 25
    check("只有 Capacitor(Warn=25)、电容 20% -> 告警（既有行为不回退）", cap(host) is True)

    host.guard(enabled=True, energy_warn=10)
    check("PowerGuard 阈值更松时不得放松结论（仍告警）", cap(host) is True)

    host.state.current_buffer_energy = 28
    check("电容 28%：Cap=25 单独时不告警", cap(host) is False)
    host.guard(enabled=True, energy_warn=30)
    check("再开 PowerGuard(=30) 后取更严的那个 -> 告警", cap(host) is True)

    host.guard(enabled=False, energy_warn=90)
    check("PowerGuard 关掉后它的阈值完全不参与（不会偷偷收紧）", cap(host) is False)

    # 卡片侧与行侧必须同一判据
    host.guard(enabled=True, energy_warn=30)
    check("状态卡片 CAP 与遥测行共用同一结论",
          host.status_card_warning("CAP", 28.0) == cap(host), str(host.status_card_warning("CAP", 28.0)))


def main() -> int:
    for fn in (
        test_wiring_does_not_change_default_picture,
        test_absolute_threshold_escalates_heat,
        test_threshold_direction_and_garbage_values,
        test_every_heat_surface_uses_the_same_verdict,
        test_power_row_is_not_collateral_damage,
        test_known_limitation_row_budget_can_drop_the_heat_row,
        test_capacitor_threshold_takes_the_stricter_of_two,
    ):
        fn()
    print(f"\n合计 {len(FAILED)} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
