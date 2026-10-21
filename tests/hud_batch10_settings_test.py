"""第 10 批验收：缓冲上限写入状态，以及 RM 指示灯的模块级开关。

两件事都盯"真的生效"而不是"看着接上了"：

1. `max_buffer_energy` 属于 **RobotStaticStatus**（协议字段 13），
   不在动态报文里。上一版把它写进 `RobotDynamicStatus` 分支 —— 那里
   根本没有这个键，`data.get` 永远回退到现值，**一行都不生效**。
   所以本文件直接调 `_apply_one`，喂 `__present__` 位图，验证真值落进状态。

2. `FrictionWheel / Show State`、`BuffStatus / Anti Rotation`、
   `LockState / Show Lock`（指示灯）以前没人读，灯永远亮着。
   隐藏必须是**整颗灯不占位**，而不是画成熄灭——否则操作员分不清
   "模块关了"和"功能没开"。

    python tests/hud_batch10_settings_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b10_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.module_list import ModuleListMixin  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class IndicatorHost(ModuleListMixin):
    def __init__(self) -> None:
        self.registry = build_default_registry()

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value


# ---------------------------------------------------------------------------
def test_buffer_max_lands_via_static_status() -> None:
    """RobotStaticStatus 字段 13 必须真的写进状态。

    这条断言存在的理由是：上一版把它写到了 RobotDynamicStatus 分支，
    那种错在"读代码"时看不出来，只能喂真实位图跑一遍才发现。
    """
    from rm_client.backend.manager import BackendManager

    workspace = tempfile.mkdtemp(prefix="polar_b10_mgr_")
    manager = BackendManager(workspace=workspace, scenario_key="OfficialEvent", client_id="3")
    state = RobotState()
    state.max_buffer_energy = 100          # 默认值，故意与要注入的值不同

    manager._apply_one(state, "RobotStaticStatus", {
        "__present__": [4, 13],
        "robot_id": 3,
        "max_buffer_energy": 260,
    })
    check("静态报文能把缓冲上限写进状态（不再停在默认 100）",
          state.max_buffer_energy == 260, str(state.max_buffer_energy))

    # 电容百分比必须按真实上限算，而不是 current/100
    state.current_buffer_energy = 65
    state.capacitor_percent = 99           # mock 字段，故意不一致
    check("有了真实上限后按 current/max 算比例（65/260=25%）",
          state.effective_capacitor_percent == 25, str(state.effective_capacitor_percent))

    # 字段缺席时不得把已有值清成 0
    state2 = RobotState()
    state2.max_buffer_energy = 260
    manager._apply_one(state2, "RobotStaticStatus", {
        "__present__": [4],
        "robot_id": 3,
    })
    check("字段不在 present 位图里时保持原值（不得被清 0）",
          state2.max_buffer_energy == 260, str(state2.max_buffer_energy))

    # 明确收到的 0 是能力观测，不是缺席；不得继续显示旧正上限。
    state3 = RobotState()
    state3.max_buffer_energy = 260
    manager._apply_one(state3, "RobotStaticStatus", {
        "__present__": [4, 13],
        "robot_id": 3,
        "max_buffer_energy": 0,
    })
    check("显式上限 0 覆盖旧值，缺席才保留",
          state3.max_buffer_energy == 0, str(state3.max_buffer_energy))

    # 动态报文里不该有 max_buffer_energy；确认它不会误改（回归上一版的错）
    state4 = RobotState()
    state4.max_buffer_energy = 300
    manager._apply_one(state4, "RobotDynamicStatus", {
        "__present__": [5],
        "current_buffer_energy": 50,
    })
    check("动态报文只更新 current，不动 max",
          state4.max_buffer_energy == 300 and state4.current_buffer_energy == 50,
          f"max={state4.max_buffer_energy} cur={state4.current_buffer_energy}")

    manager.shutdown()


def test_indicator_switches_hide_the_lamp() -> None:
    """三个开关必须能让对应指示灯消失，且互不串扰。"""
    host = IndicatorHost()
    for mod, key in (("FrictionWheel", "Show State"),
                     ("BuffStatus", "Anti Rotation"),
                     ("LockState", "Show Lock")):
        host.set(mod, key, True)

    for key in ("FRIC", "LOCK", "ANTIRO"):
        check(f"全开时 {key} 灯占位", host.rm_indicator_visible(key) is True)

    host.set("FrictionWheel", "Show State", False)
    check("关掉 Show State 后 FRIC 灯不占位",
          host.rm_indicator_visible("FRIC") is False)
    check("但 LOCK / ANTIRO 不受影响（开关不得串扰）",
          host.rm_indicator_visible("LOCK") is True
          and host.rm_indicator_visible("ANTIRO") is True)

    host.set("BuffStatus", "Anti Rotation", False)
    check("关掉 Anti Rotation 后 ANTIRO 灯不占位",
          host.rm_indicator_visible("ANTIRO") is False)
    check("FRIC 仍是关、LOCK 仍是开（各自独立）",
          host.rm_indicator_visible("FRIC") is False
          and host.rm_indicator_visible("LOCK") is True)

    host.set("LockState", "Show Lock", False)
    check("关掉 Show Lock 后 LOCK 灯不占位",
          host.rm_indicator_visible("LOCK") is False)


def test_unlisted_lamps_are_never_hidden() -> None:
    """没进表的灯必须恒占位，不能被误判隐藏。

    这一条防的是"默认值反了"：新加一个未登记的 key 若返回 False，
    面板上会莫名少几颗灯。
    """
    host = IndicatorHost()
    # ATKBUF/DEFBUF 已从"未登记"变成受 BuffStatus 控制，所以不能再列在这里。
    for key in ("PTE", "JUP", "WHE", "LES", "LNK", "DRV", "GIM",
                "MOT", "完全不认识的key"):
        check(f"{key} 不受模块级开关影响（恒占位）",
              host.rm_indicator_visible(key) is True)


def test_indicator_predicate_fails_open_on_missing_config() -> None:
    """模块缺失、设置项缺失、模块被关时都返回 True —— 不得因配置缺失弄丢灯。"""
    host = IndicatorHost()
    host.set("FrictionWheel", "Show State", True)
    host.registry.get("FrictionWheel").enabled = False
    check("模块关闭时仍占位（判据只看设置项取值，不额外加严）",
          host.rm_indicator_visible("FRIC") is True)

    host2 = IndicatorHost()
    mod = host2.registry.get("BuffStatus")
    try:
        mod.settings.pop("Anti Rotation")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("查不到设置项时占位（不因规格缺失默认隐藏）",
          host2.rm_indicator_visible("ANTIRO") is True)



def test_buff_lamps_map_to_small_and_large_buff() -> None:
    """ATKBUF/DEFBUF 必须分别受 Small Buff / Large Buff 控制。

    映射依据写在本仓库自己的代码里，不是推测：
    `RobotState.buff_indicator_state()` 在无类型数据时的回退分支字面返回
    `(bool(self.small_buff), bool(self.large_buff), "")` —— 第一返回值就是
    ATKBUF（=small_buff），第二返回值就是 DEFBUF（=large_buff）。
    """
    host = IndicatorHost()
    host.set("BuffStatus", "Small Buff", True)
    host.set("BuffStatus", "Large Buff", True)
    check("全开时两颗增益灯都占位",
          host.rm_indicator_visible("ATKBUF") is True
          and host.rm_indicator_visible("DEFBUF") is True)

    host.set("BuffStatus", "Small Buff", False)
    check("关掉 Small Buff 只影响 ATKBUF",
          host.rm_indicator_visible("ATKBUF") is False
          and host.rm_indicator_visible("DEFBUF") is True)

    host.set("BuffStatus", "Small Buff", True)
    host.set("BuffStatus", "Large Buff", False)
    check("关掉 Large Buff 只影响 DEFBUF",
          host.rm_indicator_visible("DEFBUF") is False
          and host.rm_indicator_visible("ATKBUF") is True)

    # ANTIRO 与两颗增益灯同属 BuffStatus，但各自独立可关
    host.set("BuffStatus", "Large Buff", True)
    host.set("BuffStatus", "Anti Rotation", False)
    check("关 Anti Rotation 不牵连两颗增益灯",
          host.rm_indicator_visible("ANTIRO") is False
          and host.rm_indicator_visible("ATKBUF") is True
          and host.rm_indicator_visible("DEFBUF") is True)

    # 与文件开头已确立的设计保持一致：本判据**只看设置项取值**，
    # 模块 disabled 不在这里加严（隐藏整组灯由模块开关在调用侧负责）。
    # 上一版这条断言写成期望 False，与既定设计和第一条测试互相矛盾 ——
    # 错的是断言，不是代码。
    host.registry.get("BuffStatus").enabled = False
    check("模块 disabled 时本判据仍只看设置项（不加严，避免双重判定）",
          host.rm_indicator_visible("ATKBUF") is True)


def main() -> int:
    tests = [
        test_buffer_max_lands_via_static_status,
        test_indicator_switches_hide_the_lamp,
        test_unlisted_lamps_are_never_hidden,
        test_indicator_predicate_fails_open_on_missing_config,
        test_buff_lamps_map_to_small_and_large_buff,
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
    print("ALL BATCH-10 SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
