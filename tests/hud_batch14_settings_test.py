"""第 14 批验收：状态卡片三处共用判据 + GimbalPower 三项接通。

覆盖两个目的不同的修复：

A) 我自己前几轮留下的不一致。`Show Bar` / `Show Limit` / `Show Speed`
   只在 tactical_map 的两个构造器里接了，而 `module_list.draw_status_cards_hud`
   是第三个消费点、原先无条件建 4 张卡。本文件断言这三处对同一开关结论一致。

B) 上一轮我断言"全仓找不到云台电压字段"——第三次同类错误（用猜的词搜）。
   字段是 `state.gimbal_power`，且早就在 GIMPOWER 卡上以 `{...}V` 显示。
   现在 `Show Voltage` / `Warn Below` / `Glow Alert` 三项接通。

安全约束：全部默认值下，卡片集合、配色、发光量必须与改动前一致。

    python tests/hud_batch14_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b14_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.module_list import ModuleListMixin  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402

FAILED: list[str] = []
CARDS = ("GIMPOWER", "POWERLIM", "SPEEDLIM", "CAP")


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class Host(ModuleListMixin, TacticalMapMixin):
    """两个 mixin 都混进来：CAP 的告警判据在 TacticalMapMixin 上。"""

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

    # `get_setting_number` / `hud_clean` 在真实 widget 上由其它 mixin 提供，
    # 这里标出最小实现，保持与 widget 行为一致。
    def get_setting_number(self, module, name: str, default: float) -> float:
        setting = module.get_setting(name) if module is not None else None
        if setting is None:
            return float(default)
        try:
            return float(setting.value)
        except (TypeError, ValueError):
            return float(default)

    def hud_clean(self) -> bool:
        return False


# ---------------------------------------------------------------------------
def test_default_card_set_and_colors_unchanged() -> None:
    """默认配置下卡片集合、配色、发光必须与改动前一致。"""
    host = Host()
    shown = [label for label in CARDS if host.status_card_visible(label)]
    check("默认四张卡都出现（与改动前无条件建卡一致）", shown == list(CARDS), str(shown))

    clean = host.hud_clean()
    # 改动前：无告警时发光恒为 clean?0.05:0.10
    expected_glow = 0.05 if clean else 0.10
    for label in CARDS:
        check(f"{label} 默认发光量未变",
              abs(host.status_card_glow(label, False, clean) - expected_glow) < 1e-9,
              str(host.status_card_glow(label, False, clean)))

    # 配色判据：默认电压 24V >= Warn Below 18V -> 不告警（改动前也无告警）
    host.state.gimbal_power = 24
    check("默认电压 24V 不告警（改动前该卡从不告警）",
          host.status_card_warning("GIMPOWER", 24 / 30.0) is False)
    check("默认电容不告警（电容默认高于阈值）",
          host.status_card_warning("CAP", host.state.effective_capacitor_percent / 100.0) is False)
    # POWERLIM/SPEEDLIM 保留原有 0.78 规则
    check("POWERLIM 保留原有 ratio>0.78 规则",
          host.status_card_warning("POWERLIM", 0.9) is True
          and host.status_card_warning("POWERLIM", 0.5) is False)


def test_gimbal_power_three_settings_work() -> None:
    """GimbalPower 的三项必须各自有真实效果。"""
    host = Host()
    host.set("GimbalPower", "Show Voltage", True)
    host.set("GimbalPower", "Warn Below", 18)
    host.set("GimbalPower", "Glow Alert", True)

    host.set("GimbalPower", "Show Voltage", False)
    check("关掉 Show Voltage 后 GIMPOWER 卡消失",
          host.status_card_visible("GIMPOWER") is False)
    check("但不影响其他三张卡",
          all(host.status_card_visible(c) for c in ("POWERLIM", "SPEEDLIM", "CAP")))

    host.set("GimbalPower", "Show Voltage", True)
    host.state.gimbal_power = 12
    check("电压 12V 低于阈值 18V 时告警（方向：低为险）",
          host.status_card_warning("GIMPOWER", 12 / 30.0) is True)
    host.state.gimbal_power = 25
    check("电压回升到 25V 后不告警",
          host.status_card_warning("GIMPOWER", 25 / 30.0) is False)

    # 告警时发光加强；关掉 Glow Alert 则回到基线
    host.state.gimbal_power = 10
    boosted = host.status_card_glow("GIMPOWER", True, False)
    check("告警且开 Glow Alert 时发光加强", boosted > 0.10, str(boosted))
    host.set("GimbalPower", "Glow Alert", False)
    check("关掉 Glow Alert 后发光回到基线（开关真能关）",
          abs(host.status_card_glow("GIMPOWER", True, False) - 0.10) < 1e-9)

    # 阈值 0 = 关闭告警
    host.set("GimbalPower", "Warn Below", 0)
    check("阈值 0 视为关闭告警，而不是永远告警",
          host.status_card_warning("GIMPOWER", 0.0) is False)

    # 垃圾阈值不得崩
    host.set("GimbalPower", "Warn Below", "abc")
    try:
        check("垃圾阈值不抛异常且归为不告警",
              host.status_card_warning("GIMPOWER", 0.5) is False)
    except (TypeError, ValueError) as exc:
        check("垃圾阈值不抛异常且归为不告警", False, repr(exc))


def test_three_consumers_agree_on_show_switches() -> None:
    """同一个 Show 开关在三个消费点结论必须一致。

    这正是我前几轮留下的错：只接了 tactical_map 两个构造器，
    漏了 module_list 这第三个。
    """
    host = Host()
    cases = (
        ("Capacitor", "Show Bar", "CAP"),
        ("PowerLimit", "Show Limit", "POWERLIM"),
        ("SpeedLimit", "Show Speed", "SPEEDLIM"),
    )
    for module, setting, card in cases:
        host.set(module, setting, True)
        host.set("Capacitor", "Show Bar", True)
        host.set("PowerLimit", "Show Limit", True)
        host.set("SpeedLimit", "Show Speed", True)
        on_card = host.status_card_visible(card)
        on_telemetry = host.telemetry_panel_visible(host.registry.get(module), setting)
        check(f"{module}.{setting}=True 时三处都显示", on_card and on_telemetry,
              f"card={on_card} telemetry={on_telemetry}")

        host.set(module, setting, False)
        check(f"{module}.{setting}=False 时两处一起消失（不再一处有效一处无效）",
              host.status_card_visible(card) is False
              and host.telemetry_panel_visible(host.registry.get(module), setting) is False)

        host.set(module, setting, True)


def test_missing_config_fails_open() -> None:
    """查不到设置项时不得让卡片凭空消失。"""
    host = Host()
    mod = host.registry.get("Capacitor")
    try:
        mod.settings.pop("Show Bar")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("设置项缺失时卡片仍显示", host.status_card_visible("CAP") is True)

    host2 = Host()
    check("未登记的卡片标签默认显示（不误伤）",
          host2.status_card_visible("不存在的卡") is True)


def main() -> int:
    tests = [
        test_default_card_set_and_colors_unchanged,
        test_gimbal_power_three_settings_work,
        test_three_consumers_agree_on_show_switches,
        test_missing_config_fails_open,
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
    print("ALL BATCH-14 STATUS-CARD TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
