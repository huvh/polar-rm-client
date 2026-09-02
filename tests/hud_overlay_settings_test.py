"""覆盖层与准星设置项接线验收（第 4 批）。

两项原本都是装饰：

    `RobotOverlay / Robot ID`   开开关关，装甲标签上都不显示机器人编号
    `Crosshair / Heat Color`    关掉开关，准星**照样**随枪管热量变红

第二项比一般孤儿更糟：它不是"没人读"，而是"**读不到但行为恒定**"——
界面上摆了一个"能关"的开关，实际关不掉。这种比没有开关更容易骗人。

测法：把两个方法绑到最小桩对象上，直接断言**返回值**（字符串后缀 / 颜色），
不需要 QPainter、也不需要比像素。

    python tests/hud_overlay_settings_test.py
"""

from __future__ import annotations

import os
import dataclasses
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_overlay_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.esp_wireframe import EspWireframeMixin  # noqa: E402
from rm_client.vision import ArmorObservation  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def armor(target_id: int = -1, plate_id: int = 3) -> ArmorObservation:
    return ArmorObservation(
        armor_id=plate_id,
        label="side",
        color="red",
        confidence=0.9,
        points=((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
        plate_id=plate_id,
        target_id=target_id,
    )


class OverlayHost(EspWireframeMixin):
    """只测 robot_overlay_id_suffix：它只需要 registry 与 setting_bool。"""

    def __init__(self) -> None:
        self.registry = build_default_registry()

    def setting_bool(self, module, name: str, default: bool = True) -> bool:
        setting = module.get_setting(name) if module is not None else None
        return bool(setting.value) if setting is not None else default

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value


class CrosshairHost:
    """把 PolarRMWindow.crosshair_color 绑到桩上，避开构造真实窗口（约 14s）。"""

    def __init__(self) -> None:
        from rm_client.ui.polar_app import PolarRMWindow

        self.registry = build_default_registry()
        self.state = RobotState()
        self.crosshair_color = types.MethodType(PolarRMWindow.crosshair_color, self)

    def setting_bool(self, module, name: str, default: bool = True) -> bool:
        setting = module.get_setting(name) if module is not None else None
        return bool(setting.value) if setting is not None else default

    def hud_state_color(self, key: str, ratio: float | None = None):
        return f"heat-color({key},{ratio})"

    def hud_accent(self):
        return "accent-color"

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, f"{module_name}.{setting}"
        st.value = value


# ---------------------------------------------------------------------------
def test_robot_id_suffix_appears_only_when_enabled() -> None:
    host = OverlayHost()
    host.set("RobotOverlay", "Robot ID", True)

    known = armor(target_id=103)
    suffix = host.robot_overlay_id_suffix(known)
    check("开启时后缀含机器人编号", suffix.strip() == "#103", repr(suffix))
    check("后缀自带前导空格（拼在标签后不会粘连）", suffix.startswith(" "), repr(suffix))

    host.set("RobotOverlay", "Robot ID", False)
    check("关闭后返回空串（不是返回 #-1 或 0）",
          host.robot_overlay_id_suffix(known) == "",
          repr(host.robot_overlay_id_suffix(known)))


def test_unknown_robot_id_is_not_rendered() -> None:
    """target_id 未知（-1）时不得拼出 "#-1" 让人误以为是某台车。"""
    host = OverlayHost()
    host.set("RobotOverlay", "Robot ID", True)
    for bad in (-1, 0):
        check(f"target_id={bad} 时不拼后缀",
              host.robot_overlay_id_suffix(armor(target_id=bad)) == "")
    check("target_id 是垃圾值时不抛异常",
          host.robot_overlay_id_suffix(armor(target_id="abc")) == "")
    check("armor 为 None 时不抛异常",
          host.robot_overlay_id_suffix(None) == "")


def test_overlay_module_disabled_yields_no_id() -> None:
    """RobotOverlay 整体关闭时不应再往标签上追加编号。"""
    host = OverlayHost()
    host.set("RobotOverlay", "Robot ID", True)
    host.registry.get("RobotOverlay").enabled = False
    check("模块关闭时无后缀",
          host.robot_overlay_id_suffix(armor(target_id=103)) == "",
          repr(host.robot_overlay_id_suffix(armor(target_id=103))))


def test_crosshair_heat_color_toggle_actually_switches() -> None:
    """关掉 `Heat Color` 后准星必须不再跟热量走 —— 这条以前是假的。"""
    host = CrosshairHost()
    host.set("Crosshair", "Heat Color", True)
    host.state.current_heat = 90
    host.state.max_heat = 100

    hot = host.crosshair_color()
    check("开启时按热量取色（返回热量状态色）",
          str(hot).startswith("heat-color"), str(hot))
    # 比例应如实反映热量
    check("热量比例如实传入（90/100 = 0.9）", "0.9" in str(hot), str(hot))

    host.set("Crosshair", "Heat Color", False)
    off = host.crosshair_color()
    check("关闭后改用 HUD 主色（开关真的能关掉变色）",
          off == "accent-color", str(off))

    # 关了之后，热量再高也不得变色
    host.state.current_heat = 999
    check("关闭后热量拉满也不变色",
          host.crosshair_color() == "accent-color", str(host.crosshair_color()))


def test_crosshair_heat_color_is_ratio_safe() -> None:
    """max_heat 为 0 或垃圾值时不得除崩。"""
    host = CrosshairHost()
    host.set("Crosshair", "Heat Color", True)
    host.state.current_heat = 50
    host.state.max_heat = 0
    try:
        got = host.crosshair_color()
        check("max_heat=0 时不除零", str(got).startswith("heat-color"), str(got))
    except ZeroDivisionError as exc:
        check("max_heat=0 时不除零", False, repr(exc))

    # 开关缺失时按默认（开启）处理，不得抛异常。
    # 上一版这里写了 `check(..., True)` —— 恒真断言，无论代码怎么错都会 PASS。
    removed = False
    mod = self_crosshair = host.registry.get("Crosshair")
    try:
        mod.settings.pop("Heat Color")
        removed = "Heat Color" not in dict(getattr(mod.settings, "items", lambda: {})())
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    try:
        got = host.crosshair_color()
        if removed:
            # 真断言：必须拿到默认开启时的热量色，而不是返个 None 或抛异常
            check("设置项缺失时回退到默认（热量色）而不抛异常",
                  str(got).startswith("heat-color"), str(got))
        else:
            print("  [SKIP] 无法移除设置项（容器不支持 pop），本条未验证")
    except Exception as exc:  # noqa: BLE001
        check("设置项缺失时回退到默认（热量色）而不抛异常", False, repr(exc))


def test_renderer_cpu_choice_blocks_gpu_path() -> None:
    """`Armor3DESP / Renderer` 选 CPU 时必须真的阻止 GPU 路径。

    以前分流只看 `vision_wire_gpu.available`，选 CPU 也没用。
    返回 False 会让调用侧算 `include_vision = not native_vision_owner`，
    从而由已存在的 QPainter 路径接管——不是“什么都不画”。
    """
    host = OverlayHost()
    host.set("Armor3DESP", "Renderer", "GPU Auto")
    check("GPU Auto 不干预（允许 GPU 路径）",
          host.vision_gpu_renderer_allows() is True)

    host.set("Armor3DESP", "Renderer", "CPU")
    check("选 CPU 后阻止 GPU 路径（设置项真的生效）",
          host.vision_gpu_renderer_allows() is False)

    host.set("Armor3DESP", "Renderer", "cpu")
    check("大小写不敏感（8 种写法不应造成两种行为）",
          host.vision_gpu_renderer_allows() is False)

    host.set("Armor3DESP", "Renderer", "GPU Auto")
    check("选回 GPU Auto 后恢复", host.vision_gpu_renderer_allows() is True)

    # 未知取值不得默默阻止渲染
    host.set("Armor3DESP", "Renderer", "乱写的")
    check("未知取值不干预（不能因为脏数据导致 CPU/GPU 乱切）",
          host.vision_gpu_renderer_allows() is True)

    # 本谓词**不管**模块开关：它只回答“Renderer 选了什么”。
    # `module.enabled` 在 `paint_gpu_vision_layer` 里另有判断，两者相加才阻断。
    # 这里把事实测清楚，而不是给谓词扣一个它不应承担的名字。
    host.set("Armor3DESP", "Renderer", "CPU")
    host.registry.get("Armor3DESP").enabled = False
    check("本谓词仅反映 Renderer，不因模块关闭而改口（阻断靠两处叠加）",
          host.vision_gpu_renderer_allows() is False)


def test_armor_boxes_toggle_does_not_step_on_other_switches() -> None:
    """`RobotOverlay / Armor Boxes`：关掉只影响线框本体。

    默认 True 时判据必须为 True（接线不得改变现有观感）。
    分工要钉住：`Armor Boxes` 管"画不画盒子"，`ESP Style` 管"盒子长什么样"，
    `Robot ID` 管标签。我曾以为前两者重叠，查过定义后确认职责不同，
    所以这项是可接的而不是重叠。
    """
    host = OverlayHost()
    host.set("RobotOverlay", "Armor Boxes", True)
    check("默认（开）时判据为 True，与接线前一致",
          host.robot_armor_boxes_visible() is True)

    host.set("RobotOverlay", "Armor Boxes", False)
    check("关掉后判据为 False（线框不再画）",
          host.robot_armor_boxes_visible() is False)
    probe = armor(target_id=105)
    check("但不影响 Robot ID 后缀（各开关互不越权）",
          host.robot_overlay_id_suffix(probe).strip() == "#105",
          host.robot_overlay_id_suffix(probe))

    host2 = OverlayHost()
    host2.set("RobotOverlay", "Armor Boxes", True)
    host2.registry.get("RobotOverlay").enabled = False
    check("模块 disabled 时本判据不加严（保持显示，由模块开关自己负责）",
          host2.robot_armor_boxes_visible() is True)

    host3 = OverlayHost()
    try:
        host3.registry.get("RobotOverlay").settings.pop("Armor Boxes")
    except (TypeError, KeyError, ValueError, AttributeError):
        pass
    check("查不到设置项时保持显示（接线不改变现有观感）",
          host3.robot_armor_boxes_visible() is True)


def test_overlay_distance_switch_owns_the_label_number() -> None:
    """第 17 批：`RobotOverlay / Distance` 真的能管标签里那个“12.3m”。

    这个开关原先被同名项（HeroLob/Distance）洗白在 AMBIGUOUS 档里，
    加了按模块归属的能力才拆出来：标签里的距离一直是写死的。
    """
    host = OverlayHost()

    def labeled(distance: float) -> str:
        # ArmorObservation 是 frozen dataclass，只能 replace，不能直接赋值。
        obs = dataclasses.replace(armor(target_id=101), distance_m=distance)
        return f"{obs.label.upper()}{host.robot_overlay_distance_suffix(obs)}{host.robot_overlay_id_suffix(obs)}"

    host.set("RobotOverlay", "Distance", True)
    text_on = labeled(12.34)
    check("开着时标签带距离，且与接线前逐字节相同",
          text_on == "SIDE 12.3m #101", text_on)

    host.set("RobotOverlay", "Distance", False)
    text_off = labeled(12.34)
    check("关掉后数字真的消失了（而不只是变淡）", text_off == "SIDE #101", text_off)
    check("关掉距离不影响机器人编号", "#101" in text_off, text_off)

    host.set("RobotOverlay", "Distance", True)
    host.registry.get("RobotOverlay").enabled = False
    check("整个模块关掉时仍给距离（fail-open，不顺手抽掉现有画面）",
          host.robot_overlay_distance_suffix(armor()) == " 0.0m",
          host.robot_overlay_distance_suffix(armor()))

    class Broken:
        distance_m = "不是数"

    check("垃圾距离值不致崩", host.robot_overlay_distance_suffix(Broken()) == " 0.0m")


def main() -> int:
    tests = [
        test_robot_id_suffix_appears_only_when_enabled,
        test_unknown_robot_id_is_not_rendered,
        test_overlay_module_disabled_yields_no_id,
        test_crosshair_heat_color_toggle_actually_switches,
        test_crosshair_heat_color_is_ratio_safe,
        test_renderer_cpu_choice_blocks_gpu_path,
        test_armor_boxes_toggle_does_not_step_on_other_switches,
        test_overlay_distance_switch_owns_the_label_number,
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
    print("ALL HUD-OVERLAY SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
