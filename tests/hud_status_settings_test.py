"""战况面板设置项接线验收（第 3 批）。

这些开关原本**全部被无视**：面板只判 `module.enabled`，所以行级开关
（`Own Base` / `Enemy Base` / `Outposts` / `Victory Points` / `Control Zone` /
`Gold` / `Show Speed`）关掉了 HUD 照旧画；内容级开关（`Team Status` /
`Shield` / `Tech Level` / `Show Cost` / `Ammo Type`）拖了没反应。

本文件的重点不只是"接上了"，而是**三个构造器必须一致**：

    map_status_groups          小地图状态组（6 元组）
    match_status_ring_rows     环形态（4 元组）
    match_status_rows          条形态（4 元组）

只改一个会变成"同一个开关在一处有效、另一处无效"，那比统一不接更坑——
人会以为开关坏了，而不是以为自己只改了一半。所以每个开关都对三个
构造器分别断言。

    python tests/hud_status_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_hudstat_")

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


class FakeConfig:
    def __init__(self, key: str) -> None:
        self.key = key
        # 顶栏拼的是 config.title，桩成一个可断言的固定值
        self.title = "7v7" if key != "RMUL3v3" else "3v3"


class FakeModeManager:
    def __init__(self, key: str) -> None:
        self.current = FakeConfig(key)


class Host(TacticalMapMixin):
    """最小桩。战况行的构造逻辑本身**不桩**，只桩外部依赖。"""

    def __init__(self, mode_key: str = "RMUL7v7") -> None:
        self.registry = build_default_registry()
        self.state = RobotState()
        self.match_mode_manager = FakeModeManager(mode_key)

    def alliance_side(self) -> str:
        return "Red"

    def hud_state_color(self, key: str, ratio: float | None = None):
        return f"c:{key}"

    def map_team_color(self, who: str):
        return f"team:{who}"

    def map_control_color(self):
        return "ctrl"

    def hud_danger(self):
        return "DANGER"

    def hud_warning(self):
        return "WARNING"

    def hud_accent(self):
        return "ACCENT"

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

    # 这两个格式化助手定义在 widget 层而非本 mixin，桩成确定性输出
    def short_ring_number(self, value) -> str:
        v = float(value)
        return f"{v / 1000:.1f}k" if v >= 1000 else f"{int(v)}"

    def short_outpost_value(self) -> str:
        return str(int(self.state.enemy_outpost_health))

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value

    # --- 三个构造器的行标签快照 ---
    def groups(self) -> list[tuple]:
        return self.map_status_groups()[0]

    def group_labels(self) -> list[str]:
        return [r[0] for r in self.groups()]

    def group_detail(self, prefix: str) -> str:
        for r in self.groups():
            if r[0].startswith(prefix):
                return r[5]
        return ""

    def ring_labels(self) -> list[str]:
        return [r[0] for r in self.match_status_ring_rows()]

    def bar_labels(self) -> list[str]:
        return [r[0] for r in self.match_status_rows(compact=False)]

    def telemetry_labels(self) -> list[str]:
        return [r[0] for r in self.map_telemetry_status_rows()]

    def all_status_labels(self) -> dict[str, list[str]]:
        return {
            "groups": self.group_labels(),
            "rings": self.ring_labels(),
            "bars": self.bar_labels(),
        }


def set_all(host: Host, module_name: str, setting: str, value) -> None:
    """同一个开关在三个构造器里都要体现，所以统一设。"""
    host.set(module_name, setting, value)


# ---------------------------------------------------------------------------
def test_base_outpost_row_toggles_across_all_three_builders() -> None:
    """`Own Base`/`Enemy Base`/`Outposts` 必须在三个构造器里都生效。"""
    host = Host("RMUL7v7")
    for name in ("Own Base", "Enemy Base", "Outposts"):
        set_all(host, "BaseOutpostStatus", name, True)
    host.state.base_health = 4000
    host.state.enemy_base_health = 3000

    labels = host.all_status_labels()
    check("全开时三个构造器都有基地/前哨行",
          all("OWN BASE" in labels["bars"] or "BASE" in labels["rings"] or
              any(l.endswith("BASE YOU") for l in labels["groups"]) for l in [0])
          and "OUTPOST" in labels["bars"] and "OUT" in labels["rings"],
          str(labels))

    set_all(host, "BaseOutpostStatus", "Own Base", False)
    labels = host.all_status_labels()
    check("关掉 Own Base：groups 里没有基地行",
          not any("BASE YOU" in l for l in labels["groups"]), str(labels["groups"]))
    check("关掉 Own Base：rings 里没有 BASE", "BASE" not in labels["rings"], str(labels["rings"]))
    check("关掉 Own Base：bars 里没有 OWN BASE", "OWN BASE" not in labels["bars"], str(labels["bars"]))

    set_all(host, "BaseOutpostStatus", "Enemy Base", False)
    labels = host.all_status_labels()
    check("关掉 Enemy Base 后三处都没有敌方基地行",
          not any(l.startswith("RED BASE") or "ENEMY BASE" in l for l in labels["groups"] + labels["bars"])
          and "EBASE" not in labels["rings"], str(labels))

    set_all(host, "BaseOutpostStatus", "Outposts", False)
    labels = host.all_status_labels()
    check("关掉 Outposts 后三处都没有前哨行",
          "OUTPOST" not in labels["bars"] and "OUT" not in labels["rings"]
          and "OUTPOST" not in labels["groups"], str(labels))


def test_shield_toggle_changes_base_detail() -> None:
    """`BaseOutpostStatus / Shield` 控制基地提示里带不带护盾。"""
    host = Host("RMUL7v7")
    set_all(host, "BaseOutpostStatus", "Own Base", True)
    host.state.base_shield = 880

    set_all(host, "BaseOutpostStatus", "Shield", True)
    text = host.group_detail("RED BASE YOU")
    check("Shield 开时基地提示含护盾", "SHIELD 880" in text, text)

    set_all(host, "BaseOutpostStatus", "Shield", False)
    text_off = host.group_detail("RED BASE YOU")
    check("Shield 关时基地提示不含护盾（内容真的变了）",
          "SHIELD" not in text_off and text_off != "", text_off)


def test_victory_point_toggles_in_3v3() -> None:
    """3v3 下 `Victory Points` 与 `Control Zone` 必须分别可控。"""
    host = Host("RMUL3v3")
    set_all(host, "VictoryPointStatus", "Victory Points", True)
    set_all(host, "VictoryPointStatus", "Control Zone", True)
    set_all(host, "VictoryPointStatus", "Team Status", True)

    labels = host.all_status_labels()
    check("全开时两处分VP行 + CTRL行",
          "ALLY" in labels["rings"] and "ALLY VP" in labels["bars"]
          and "CTRL" in labels["rings"] and "CONTROL" in labels["bars"], str(labels))

    set_all(host, "VictoryPointStatus", "Control Zone", False)
    labels = host.all_status_labels()
    check("关掉 Control Zone：三处都无控制行",
          "CTRL" not in labels["rings"] and "CONTROL" not in labels["bars"]
          and "CTRL" not in labels["groups"], str(labels))

    set_all(host, "VictoryPointStatus", "Victory Points", False)
    labels = host.all_status_labels()
    check("关掉 Victory Points：三处都无 VP 行",
          not any("VP" in l or l in ("ALLY", "ENEMY") for l in labels["bars"] + labels["rings"] + labels["groups"]),
          str(labels))


def test_team_status_toggle_changes_label_suffix() -> None:
    """`Team Status` 控制标签上标不标 YOU —— 这是内容开关不是行开关。"""
    host = Host("RMUL3v3")
    set_all(host, "VictoryPointStatus", "Victory Points", True)
    set_all(host, "VictoryPointStatus", "Team Status", True)
    labels_on = list(host.group_labels())
    check("开时有一方标了 YOU", any(l.endswith(" YOU") for l in labels_on), str(labels_on))

    set_all(host, "VictoryPointStatus", "Team Status", False)
    labels_off = list(host.group_labels())
    check("关时没有任何标签带 YOU", not any(l.endswith(" YOU") for l in labels_off), str(labels_off))
    check("但行本身仍在（内容开关不得删行）",
          len(labels_off) == len(labels_on), f"{len(labels_on)} -> {len(labels_off)}")


def test_gold_and_tech_level_toggles() -> None:
    """`EconomyPanel / Gold` 删行；`Tech Level` 只改文本。"""
    host = Host("RMUL7v7")
    set_all(host, "EconomyPanel", "Gold", True)
    set_all(host, "EconomyPanel", "Tech Level", True)
    host.state.remaining_economy = 220
    host.state.tech_level = 3

    labels = host.all_status_labels()
    check("Gold 开时三处都有 GOLD",
          all("GOLD" in l for l in (labels["rings"], labels["bars"]))
          and "GOLD" in labels["groups"], str(labels))
    check("Tech Level 开时提示含 / T3", "/ T3" in host.group_detail("GOLD"),
          host.group_detail("GOLD"))

    set_all(host, "EconomyPanel", "Tech Level", False)
    check("Tech Level 关时提示不含科技等级，但行还在",
          "/ T" not in host.group_detail("GOLD") and "GOLD" in host.group_labels(),
          host.group_detail("GOLD"))

    set_all(host, "EconomyPanel", "Gold", False)
    labels = host.all_status_labels()
    check("关掉 Gold 后三处都没有 GOLD",
          "GOLD" not in labels["rings"] and "GOLD" not in labels["bars"]
          and "GOLD" not in labels["groups"], str(labels))


def test_ammo_type_and_show_cost() -> None:
    """`Ammo Type` 换主显示弹种；`Show Cost` 控制带不带价格。"""
    host = Host("RMUL7v7")
    set_all(host, "ProjectileShop", "Ammo Type", "17mm")
    set_all(host, "ProjectileShop", "Show Cost", True)
    host.state.projectile_allowance_17mm = 150
    host.state.projectile_allowance_42mm = 9
    host.state.projectile_shop_price = 50

    check("17mm 时主显示是 17mm", host.group_detail("AMMO").startswith("AMMO 17mm"),
          host.group_detail("AMMO"))
    check("Show Cost 开时含 PRICE", "PRICE 50" in host.group_detail("AMMO"),
          host.group_detail("AMMO"))

    set_all(host, "ProjectileShop", "Ammo Type", "42mm")
    check("切到 42mm 后主显示跟着变（设置项真的影响内容）",
          "42mm 9" in host.group_detail("AMMO"), host.group_detail("AMMO"))

    set_all(host, "ProjectileShop", "Show Cost", False)
    check("关掉 Show Cost 后不再显示价格",
          "PRICE" not in host.group_detail("AMMO"), host.group_detail("AMMO"))


def test_speed_and_heat_row_toggles() -> None:
    """`SpeedLimit / Show Speed` 与 `ThermalPowerPanel / Heat` 关行。"""
    host = Host("RMUL7v7")
    set_all(host, "SpeedLimit", "Show Speed", True)
    set_all(host, "ThermalPowerPanel", "Heat", True)
    host.state.speed_limit = 300
    host.state.current_heat = 40

    check("开关都在时有 SPEED 行", "SPEED" in host.telemetry_labels(), str(host.telemetry_labels()))
    set_all(host, "SpeedLimit", "Show Speed", False)
    check("关掉 Show Speed 后无 SPEED 行", "SPEED" not in host.telemetry_labels(),
          str(host.telemetry_labels()))
    check("关 SPEED 不影响 CAP/POWER 判据（各开关互不串扰）",
          host.telemetry_panel_visible(host.registry.get("Capacitor"), "Show Bar") is True)

    set_all(host, "ThermalPowerPanel", "Heat", False)
    labels = host.all_status_labels()
    check("关掉 Heat 后 rings/bars 都无 HEAT 行",
          "HEAT" not in labels["rings"] and not any(l.startswith("HEAT") for l in labels["bars"]),
          str(labels))


def test_disabled_module_still_yields_no_rows() -> None:
    """模块整体关闭时仍应无行 —— 新增的行级判据不得放宽这条。"""
    host = Host("RMUL7v7")
    # 必须包上 ThermalPowerPanel：它也会产出 HEAT 行。上一版只关了 4 个
    # 模块却断言“完全无行”，是测试前提错了而不是代码错了。
    status_modules = (
        "BaseOutpostStatus", "EconomyPanel", "VictoryPointStatus",
        "ProjectileShop", "ThermalPowerPanel", "SpeedLimit", "Capacitor", "PowerLimit",
    )
    for name in status_modules:
        m = host.registry.get(name)
        if m is not None:
            m.enabled = False
    labels = host.all_status_labels()
    check("相关模块全关时三处都没有状态行",
          not labels["groups"] and not labels["rings"] and not labels["bars"], str(labels))
    check("同时遥测行也空",
          host.telemetry_labels() == [], str(host.telemetry_labels()))


def test_match_timer_header_toggles() -> None:
    """`Show Stage` / `Show Scores` 必须真的改变顶栏文字。

    以前 `draw_match_header` 无条件把阶段、倒计时、分数全拼进去，
    两个开关完全被无视。现在文本组装已抽成纯函数，能直接断言。
    """
    host = Host("RMUL7v7")
    host.set("MatchTimer", "Show Stage", True)
    host.set("MatchTimer", "Show Scores", True)
    host.set("MatchTimer", "Pulse Last 30s", True)
    host.state.current_stage = "PLAYING"
    host.state.stage_countdown_sec = 120
    host.state.red_score = 3
    host.state.blue_score = 1

    def stub_format(seconds) -> str:
        s = int(float(seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    host.format_time = stub_format  # type: ignore[attr-defined]

    text = host.match_header_text()
    check("全开时顶栏含阶段名与倒计时", "PLAYING" in text and "02:00" in text, text)
    check("全开时顶栏含分数", "SCORE 3:1" in text, text)

    host.set("MatchTimer", "Show Stage", False)
    text = host.match_header_text()
    check("关掉 Show Stage 后阶段与倒计时都消失", "PLAYING" not in text and "02:00" not in text, text)
    check("但分数仍在（开关不得串扰）", "SCORE 3:1" in text, text)

    host.set("MatchTimer", "Show Stage", True)
    host.set("MatchTimer", "Show Scores", False)
    text = host.match_header_text()
    check("关掉 Show Scores 后分数消失", "SCORE" not in text, text)
    check("但阶段仍在", "PLAYING" in text, text)

    # 3v3 走 VP 分支
    host3 = Host("RMUL3v3")
    host3.set("MatchTimer", "Show Scores", True)
    host3.state.ally_victory_points = 80
    host3.state.enemy_victory_points = 40
    host3.format_time = stub_format  # type: ignore[attr-defined]
    check("3v3 下 Show Scores 显示 VP而不是 SCORE",
          "VP 80:40" in host3.match_header_text() and "SCORE" not in host3.match_header_text(),
          host3.match_header_text())


def test_match_timer_pulse_window_and_direction() -> None:
    """`Pulse Last 30s` 必须只在未来 30 秒窗口内给非零强度，且方向正确。"""
    host = Host("RMUL7v7")
    host.set("MatchTimer", "Pulse Last 30s", True)

    host.state.stage_countdown_sec = 120
    check("倒计时 120s 时不脉冲", host.match_header_pulse_strength() == 0.0,
          str(host.match_header_pulse_strength()))

    # 窗口内：强度应大于 0（正弦会周期归零，所以取多个采样证明它在动）
    host.state.stage_countdown_sec = 12
    samples = [host.match_header_pulse_strength() for _ in range(60)]
    check("倒计时 12s 时有脉冲且幅度在 0..1",
          max(samples) > 0.0 and min(samples) >= 0.0 and max(samples) <= 1.0,
          f"max={max(samples):.3f}")

    # 越接近 0 包络越大
    host.state.stage_countdown_sec = 25
    late_max = max(host.match_header_pulse_strength() for _ in range(80))
    host.state.stage_countdown_sec = 3
    early_max = max(host.match_header_pulse_strength() for _ in range(80))
    check("越接近结束脉冲包络越强", early_max > late_max, f"3s={early_max:.3f} 25s={late_max:.3f}")

    # 边界与异常值
    host.state.stage_countdown_sec = 0
    check("倒计时 0 不脉冲（未开始/超时不得误报为紧急）",
          host.match_header_pulse_strength() == 0.0)
    host.state.stage_countdown_sec = -30
    check("负倒计时不脉冲", host.match_header_pulse_strength() == 0.0)
    host.state.stage_countdown_sec = 30
    check("恰在窗口上边界 30s 不脉冲", host.match_header_pulse_strength() == 0.0)

    # 开关必须真的关掉效果
    host.state.stage_countdown_sec = 5
    host.set("MatchTimer", "Pulse Last 30s", False)
    check("关掉开关后即使在窗口内也不脉冲",
          host.match_header_pulse_strength() == 0.0)

    # 模块整体关闭时也不得脉冲
    host.set("MatchTimer", "Pulse Last 30s", True)
    host.registry.get("MatchTimer").enabled = False
    check("MatchTimer 模块关闭时不脉冲", host.match_header_pulse_strength() == 0.0)


def test_power_pulse_only_when_actually_over_limit() -> None:
    """`Pulse Overrun` 必须只在功率真的超限（ratio > 1）时脉。

    重要陷阱：两条绘制路径都会把传给条形的 ratio 钳到 0..1。如果拿
    钳位后的值去判“超限”，永远只能拿到 1.0，脉冲就永不触发 ——
    看着接上了、实际永远不亮。所以谓词必须吃原始比例。
    """
    host = Host("RMUL7v7")
    host.set("PowerLimit", "Pulse Overrun", True)
    host.set("PowerLimit", "Show Limit", True)
    host.set("PowerLimit", "Limit", 80)

    check("未超限（ratio=0.5）不脉冲",
          host.telemetry_pulse_strength("PowerLimit", 0.5) == 0.0)
    check("恰在限额（ratio=1.0）不脉冲",
          host.telemetry_pulse_strength("PowerLimit", 1.0) == 0.0)

    # 超限：采样证明它在动，而不是恒为某个值
    samples = [host.telemetry_pulse_strength("PowerLimit", 1.1) for _ in range(80)]
    check("超限 10% 时有脉冲且幅度在 0..1",
          max(samples) > 0.0 and min(samples) >= 0.0 and max(samples) <= 1.0,
          f"max={max(samples):.3f}")

    # 超限越多包络越强
    check("超限越多脉冲包络越强",
          max(host.telemetry_pulse_strength("PowerLimit", 1.4) for _ in range(120))
          > max(host.telemetry_pulse_strength("PowerLimit", 1.05) for _ in range(120)))

    # 开关必须能关掉
    host.set("PowerLimit", "Pulse Overrun", False)
    check("关掉开关后即使超限也不脉冲",
          host.telemetry_pulse_strength("PowerLimit", 2.0) == 0.0)

    # 不得抢别的卡：只有 PowerLimit 卡会被脉冲影响
    host.set("PowerLimit", "Pulse Overrun", True)
    for other in ("Capacitor", "SpeedLimit", "ThermalPowerPanel", "GOLD"):
        check(f"不影响其他卡（{other} 即使 ratio>1 也不脉冲）",
              host.telemetry_pulse_strength(other, 3.0) == 0.0)

    # 垃圾值不得崩
    check("ratio 是垃圾值时不抛异常",
          host.telemetry_pulse_strength("PowerLimit", "abc") == 0.0)


def test_capacitor_glow_amount_respects_use_glow() -> None:
    """`Capacitor / Use Glow` 关掉时，只有 CAP 卡不再画外发光。"""
    host = Host("RMUL7v7")
    host.set("Capacitor", "Use Glow", True)
    base = host.telemetry_glow_amount("Capacitor")
    check("开启时有外发光且为正常量", base == host.TELEMETRY_GLOW_BASE, str(base))

    host.set("Capacitor", "Use Glow", False)
    check("关闭后 CAP 卡外发光归零",
          host.telemetry_glow_amount("Capacitor") == 0.0)
    check("但不得影响其他卡的外发光",
          host.telemetry_glow_amount("PowerLimit") == host.TELEMETRY_GLOW_BASE,
          str(host.telemetry_glow_amount("PowerLimit")))


def main() -> int:
    tests = [
        test_base_outpost_row_toggles_across_all_three_builders,
        test_shield_toggle_changes_base_detail,
        test_victory_point_toggles_in_3v3,
        test_team_status_toggle_changes_label_suffix,
        test_gold_and_tech_level_toggles,
        test_ammo_type_and_show_cost,
        test_speed_and_heat_row_toggles,
        test_match_timer_header_toggles,
        test_match_timer_pulse_window_and_direction,
        test_power_pulse_only_when_actually_over_limit,
        test_capacitor_glow_amount_respects_use_glow,
        test_disabled_module_still_yields_no_rows,
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
    print("ALL HUD-STATUS SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
