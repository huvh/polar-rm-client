"""第 8 批设置项接线验收：启动二级页、锁定框、弹药告警、缓冲能量。

四项原本都是装饰（界面上能改，代码里没人读）：

    MatchMode / Second Step        四个跳转点全硬写 "match"，关掉也必须过二级页
    LockState / Show Lock          关掉后锁定框照旧画
    ProjectileAllowance / Warn Low 弹药见底时 AMMO 行颜色完全不变
    ThermalPowerPanel / Buffer     模块描述写着要显示"缓冲能量"，但代码从没发过

本文件同时盯一个反复出现的错误类别：**同一份数据有两个构造器时，
判据必须共用**。`map_status_groups`（6 元组）与 `match_status_rows`
（4 元组）都产 AMMO 行；只改一处会让开关"在一处有效、一处无效"。

    python tests/hud_batch8_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b8_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.esp_wireframe import EspWireframeMixin  # noqa: E402
from rm_client.ui.polar.renderers.startup_scene import StartupSceneMixin  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class BaseHost:
    def __init__(self) -> None:
        self.registry = build_default_registry()
        self.state = RobotState()

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value


class StartupHost(BaseHost, StartupSceneMixin):
    pass


class LockHost(BaseHost, EspWireframeMixin):
    pass


class FakeConfig:
    key = "RMUC7v7"
    title = "7v7"


class FakeModeManager:
    current = FakeConfig()


class MapHost(BaseHost, TacticalMapMixin):
    def __init__(self) -> None:
        super().__init__()
        self.match_mode_manager = FakeModeManager()

    def alliance_side(self) -> str:
        return "Red"

    def hud_state_color(self, key: str, ratio: float | None = None):
        return f"c:{key}"

    def hud_danger(self):
        return "DANGER"

    def hud_warning(self):
        return "WARNING"

    def hud_accent(self):
        return "ACCENT"

    def map_team_color(self, who: str):
        return f"team:{who}"

    def map_control_color(self):
        return "ctrl"

    def short_ring_number(self, value) -> str:
        return str(int(value))

    def short_outpost_value(self) -> str:
        return str(int(self.state.enemy_outpost_health))

    def get_setting_number(self, module, name: str, default: float) -> float:
        setting = module.get_setting(name) if module is not None else None
        try:
            return float(setting.value) if setting is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    def animated_scalar(self, key: str, target: float, rate: float) -> float:
        return float(target)

    def ammo_rows(self) -> list[tuple]:
        return [r for r in self.match_status_rows(compact=False) if r[0] == "AMMO"]

    def ammo_groups(self) -> list[tuple]:
        return [r for r in self.map_status_groups()[0] if r[0] == "AMMO"]

    def heat_rows(self) -> list[tuple]:
        return [r for r in self.match_status_rows(compact=False) if r[0].startswith("HEAT")]


def MapHostFree() -> "MapHost":
    """`match_status_rows` 只返前 4 行（rows[:4]）。

    基地/敌方基地/前哨/金币会把 4 格占满，导致 AMMO 与 HEAT/PWR 行永远进不来。
    这不是 bug，但测这两个行时必须先把前面的行关掉——否则测试会错得
    像是代码坏了。（这恰好也从另一个角度说明了为什么要接行级开关：
    没有行级开关时，用户想看的行可能被全部挡不到。）
    """
    host = MapHost()
    for name in ("BaseOutpostStatus", "EconomyPanel"):
        mod = host.registry.get(name)
        if mod is not None:
            mod.enabled = False
    return host


# ---------------------------------------------------------------------------
def test_second_step_toggle_changes_startup_flow() -> None:
    """`MatchMode / Second Step` 必须真的决定跳不跳二级选择页。

    以前四个跳转点全硬写 "match"，所以这个开关无论怎么设，
    启动流程都必须过二级页 —— 界面上是一个"关不掉"的关。
    """
    host = StartupHost()
    host.set("MatchMode", "Second Step", True)
    check("开启时场景选完进 match 页",
          host.startup_page_after_scenario() == "match",
          host.startup_page_after_scenario())
    check("开启时机器人页回退到 match 页",
          host.startup_page_before_robot() == "match",
          host.startup_page_before_robot())

    host.set("MatchMode", "Second Step", False)
    check("关闭时场景选完直接进 robot 页",
          host.startup_page_after_scenario() == "robot",
          host.startup_page_after_scenario())
    # 回退必须一起变：否则会退回一个本来被跳过的页，流程看起来像坏了
    check("关闭时机器人页回退直接回 scenario（不能退回被跳过的页）",
          host.startup_page_before_robot() == "scenario",
          host.startup_page_before_robot())

    # 三个返回值必须是合法页面名，否则 begin_startup_page_transition 会静默忽略
    for value in (True, False):
        host.set("MatchMode", "Second Step", value)
        pages = {host.startup_page_after_scenario(), host.startup_page_before_robot()}
        check(f"Second Step={value} 时目标页名合法",
              pages <= {"scenario", "match", "robot"}, str(pages))


def test_lock_indicator_can_be_hidden_but_fails_open() -> None:
    """`LockState / Show Lock` 能关掉锁定框；配置缺失时不得让 HUD 元素消失。"""
    host = LockHost()
    host.set("LockState", "Show Lock", True)
    check("开启时锁定框可见", host.lock_indicator_visible() is True)

    host.set("LockState", "Show Lock", False)
    check("关闭时锁定框隐藏", host.lock_indicator_visible() is False)

    # 保守取向：模块整体关闭 -> 视为"不参与判定"，保持原行为（显示）
    host.registry.get("LockState").enabled = False
    check("LockState 模块关闭时保持原行为（显示）",
          host.lock_indicator_visible() is True)

    # 设置项不存在时也不得隐藏 HUD 元素
    host2 = LockHost()
    host2.registry.get("LockState").enabled = True
    try:
        host2.registry.get("LockState").settings.pop("Show Lock")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("查不到设置项时返回可见（不因配置缺失弄丢 HUD 元素）",
          host2.lock_indicator_visible() is True)


def test_warn_low_colors_ammo_row_in_both_builders() -> None:
    """`ProjectileAllowance / Warn Low` 必须让 AMMO 行变色，且两个构造器一致。"""
    host = MapHostFree()
    host.set("ProjectileAllowance", "Warn Low", True)
    host.set("ProjectileShop", "Ammo Type", "17mm")
    host.set("ProjectileShop", "Show Cost", False)

    # 充足：180/180
    host.state.projectile_allowance_17mm = 180
    host.state.projectile_allowance_42mm = 12
    rows = host.ammo_rows()
    groups = host.ammo_groups()
    check("弹药充足时两个构造器都不告警",
          bool(rows) and bool(groups)
          and rows[0][3] != "DANGER" and groups[0][3] != "DANGER",
          f"{rows[0][3] if rows else None}/{groups[0][3] if groups else None}")

    # 见底：10/180 = 0.056 <= 0.25
    host.state.projectile_allowance_17mm = 10
    rows = host.ammo_rows()
    groups = host.ammo_groups()
    check("弹药见底时 match_status_rows 变告警色",
          bool(rows) and rows[0][3] == "DANGER", str(rows[0][3] if rows else None))
    check("弹药见底时 map_status_groups 也变告警色（两处必须一致）",
          bool(groups) and groups[0][3] == "DANGER",
          str(groups[0][3] if groups else None))

    # 关掉开关后即使在低量也不告警
    host.set("ProjectileAllowance", "Warn Low", False)
    rows = host.ammo_rows()
    check("关掉 Warn Low 后低弹药也不告警（开关真能关）",
          bool(rows) and rows[0][3] != "DANGER", str(rows[0][3] if rows else None))

    # 比例取的是"主显示弹种"，切到 42mm 后要跟着变
    host.set("ProjectileAllowance", "Warn Low", True)
    host.set("ProjectileShop", "Ammo Type", "42mm")
    host.state.projectile_allowance_42mm = 30          # 30/30 = 1.0 不低
    host.state.projectile_allowance_17mm = 5           # 17mm 很低但没在主显示
    rows = host.ammo_rows()
    check("告警判据跟着 Ammo Type 走（不是一直盯 17mm）",
          bool(rows) and rows[0][3] != "DANGER", str(rows[0][3] if rows else None))


def test_buffer_text_follows_thermal_panel_toggle() -> None:
    """`ThermalPowerPanel / Buffer`：模块描述承诺了缓冲能量，之前从没显示过。"""
    host = MapHostFree()
    host.set("ThermalPowerPanel", "Heat", True)
    host.set("ThermalPowerPanel", "Buffer", True)
    host.state.max_buffer_energy = 100
    host.state.current_buffer_energy = 62

    text = host.telemetry_buffer_text()
    check("开启时给出缓冲能量文本", "BUF 62%" in text, text)

    rows = host.heat_rows()
    check("HEAT/PWR 行确实带上了缓冲能量",
          bool(rows) and "BUF 62%" in rows[0][1], str(rows[0][1] if rows else None))

    host.set("ThermalPowerPanel", "Buffer", False)
    check("关闭后文本为空（开关真能关）", host.telemetry_buffer_text() == "",
          repr(host.telemetry_buffer_text()))
    rows = host.heat_rows()
    check("关闭后 HEAT/PWR 行不再含缓冲能量，但行本身还在",
          bool(rows) and "BUF" not in rows[0][1], str(rows[0][1] if rows else None))

    # 缓冲数值变化要如实反映，不能是硬编码
    host.set("ThermalPowerPanel", "Buffer", True)
    host.state.current_buffer_energy = 7
    check("缓冲数值跟随状态变化", host.telemetry_buffer_text().strip() == "BUF 7%",
          host.telemetry_buffer_text())


def main() -> int:
    tests = [
        test_second_step_toggle_changes_startup_flow,
        test_lock_indicator_can_be_hidden_but_fails_open,
        test_warn_low_colors_ammo_row_in_both_builders,
        test_buffer_text_follows_thermal_panel_toggle,
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
    print("ALL BATCH-8 SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
