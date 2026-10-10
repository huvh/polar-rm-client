"""第 20 批验收：`RobotOverlay / Color`（装甲盒配色）接通。

接线前的画面是**纯白**（`primary = color("#ffffff", opacity)`），而设置项
默认值写的是 `Team`——那个默认从来没对应过任何行为。与 `MapMarker / Send All`
同型问题，同一处理：**把默认改成等于今天的实际行为（White）**，再逐项接上。

本文件钉住的安全约束：
  * 默认 White 时三个消费点（观测盒 / Polar Outline 路径 / 主目标面）
    的颜色必须与接线前**逐值相同**——升级不会让任何人的装甲盒突变。
  * Team 只在看得出装甲板颜色（red/blue）时用阵营色；
    `purple` / `extinguish` 回落纯白——把认不出的板涂成"敌方红"比不涂危险得多。
  * Threat 无威胁度数据源：**降级回 Team 并记下原因**（与
    `ArmorAutoAim / Priority` 的 Radar 选项同一先例），绝不静默。
  * 三个消费点必须共用同一个助手：上一版把主目标面传了 None、Polar Outline
    路径留着旧 `primary`，都是"开关一处有效一处无效"的同型缺陷，本文件
    用 Team 档下"红板变色 / 紫板不变色"的组合把它们各钉一枚断言。

    python tests/hud_batch20_robotoverlay_color_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b20_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

from rm_client.model import build_default_registry  # noqa: E402
from rm_client.ui.polar_app import PolarRMWindow  # noqa: E402
from rm_client.vision import ArmorObservation, VisionResult  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def make_armor(x: float, *, color_name: str = "red", aim: bool = False, armor_id: int = 1) -> ArmorObservation:
    return ArmorObservation(
        armor_id=armor_id,
        label="enemy",
        color=color_name,
        confidence=0.9,
        points=((x, 100.0), (x + 40.0, 100.0), (x + 40.0, 140.0), (x, 140.0)),
        distance_m=5.0,
        aim=aim,
        depth_m=5.0,
        plate_id=armor_id,
    )


class Host:
    """只借真方法的桩宿主：不建窗口，不碰 GPU。"""

    robot_overlay_color_mode = PolarRMWindow.robot_overlay_color_mode
    robot_overlay_armor_color = PolarRMWindow.robot_overlay_armor_color
    robot_overlay_id_suffix = PolarRMWindow.robot_overlay_id_suffix
    robot_overlay_distance_suffix = PolarRMWindow.robot_overlay_distance_suffix
    draw_armor_3d_esp = PolarRMWindow.draw_armor_3d_esp
    ROBOT_OVERLAY_COLOR_DEFAULT = PolarRMWindow.ROBOT_OVERLAY_COLOR_DEFAULT

    RED_SENTINEL = QColor(255, 0, 0)
    BLUE_SENTINEL = QColor(0, 0, 255)
    ACCENT_SENTINEL = QColor(0, 255, 0)

    def __init__(self) -> None:
        self.registry = build_default_registry()
        self.records: list[tuple] = []
        self._vision_snapshot = None
        self._vision_render_result = None
        self._bottom_left_diagnostics: list = []
        self._armor_geometry_smooth: dict = {}

        class _State:
            vision_kill_status = "IDLE"

        self.state = _State()
        esp = self.registry.get("Armor3DESP")
        if esp is not None:
            style = esp.get_setting("Style")
            if style is not None:
                style.value = "CleanBox"  # 避开 PolarMechanicalWire 的 text_width 依赖
        self.robot_overlay_color_actual = "White"
        self.robot_overlay_color_reason = ""

    def setting_mode(self, module, setting_name: str, default: str) -> str:
        setting = module.get_setting(setting_name) if module else None
        return str(setting.value) if setting else default

    def setting_bool(self, module, setting_name: str, default: bool) -> bool:
        setting = module.get_setting(setting_name) if module else None
        return bool(setting.value) if setting else default

    def get_setting_number(self, module, setting_name: str, default: float) -> float:
        setting = module.get_setting(setting_name) if module else None
        try:
            return float(setting.value) if setting else default
        except (TypeError, ValueError):
            return default

    # —— 被借方法依赖的取值点：全部换成哨兵，让"接到哪"一眼可辨 ——
    def vision_result_calibrated(self, result) -> bool:
        return True

    def armor_esp_points(self, points, result, width, height):
        return [QPointF(x, y) for x, y in points]

    def armor_esp_back_points(self, armor, result, width, height, depth):
        return [QPointF(x, y) for x, y in armor.points]

    def robot_armor_boxes_visible(self) -> bool:
        return True

    def map_team_color(self, relation: str) -> QColor:
        return self.RED_SENTINEL if relation.lower() == "red" else self.BLUE_SENTINEL

    def hud_accent(self) -> QColor:
        return QColor(self.ACCENT_SENTINEL)

    def hud_warning(self) -> QColor:
        return QColor(255, 165, 0)

    def font(self, name, size):
        return None

    # —— 绘制出口：只记颜色与位置，不碰任何真实画布 ——
    def draw_clean_3d_esp_box(self, p, front, back, c, lw, glass=False, ghost=False, label=None):
        self.records.append(("box", int(front[0].x()), QColor(c)))

    def draw_polar_mechanical_wire(self, p, front, back, c, lw, predicted=False, label=None):
        self.records.append(("wire", int(front[0].x()), QColor(c)))

    def draw_minimal_bracket_lock(self, p, rect, target, aim):
        self.records.append(("bracket", int(rect.x()), bool(aim)))

    def draw_pill(self, p, pos, text, c):
        self.records.append(("pill", int(pos.x()), QColor(c), text))

    def draw_text(self, p, rect, text, font, c, *a):
        self.records.append(("text", int(rect.x()), QColor(c), text))

    def set_color(self, mode: str) -> None:
        overlay = self.registry.get("RobotOverlay")
        assert overlay is not None
        setting = overlay.get_setting("Color")
        assert setting is not None
        setting.value = mode

    def set_overlay_style(self, mode: str) -> None:
        overlay = self.registry.get("RobotOverlay")
        assert overlay is not None
        overlay.get_setting("ESP Style").value = mode

    def run_draw(self, armors, aim=None) -> None:
        result = VisionResult(
            sequence=1, timestamp_ns=1, source_width=1280, source_height=720,
            detections=tuple(armors), predicted_armors=(),
            aim_armor=aim, calibrated=True,
        )
        module = self.registry.get("Armor3DESP")
        self.records.clear()
        self.draw_armor_3d_esp(None, 1280, 720, result, module)

    def colors_at(self, x: int) -> list[QColor]:
        return [r[2] for r in self.records if len(r) >= 3 and r[1] == x and isinstance(r[2], QColor)]


def test_default_white_is_pixel_unchanged() -> None:
    """默认档 = 接线前画面：所有板纯白，透明度沿用各自接线前的值。"""
    host = Host()
    check("默认取值就是 White（不是从没生效过的 Team）",
          host.setting_mode(host.registry.get("RobotOverlay"), "Color", "") == "White")
    mode, reason = host.robot_overlay_color_mode()
    check("默认不产生降级原因", mode == "White" and reason == "", f"{mode}/{reason}")

    red = make_armor(100.0, color_name="red")
    aim = make_armor(900.0, color_name="red", aim=True)
    host.run_draw([red, aim], aim=aim)
    opacity = float(host.registry.get("Armor3DESP").get_setting("Opacity").value)
    plate_colors = host.colors_at(100)
    check("默认观测盒仍是纯白+opacity",
          plate_colors and all(c.name().upper() == "#FFFFFF" and abs(c.alphaF() - opacity) < 1e-3 for c in plate_colors),
          str(plate_colors))
    aim_face = host.colors_at(900)
    check("默认主目标面仍是纯白不透明",
          aim_face and all(c.name().upper() == "#FFFFFF" and c.alphaF() == 1.0 for c in aim_face),
          str(aim_face))


def test_team_uses_plate_color_only_when_identifiable() -> None:
    host = Host()
    host.set_color("Team")
    red = make_armor(100.0, color_name="red")
    blue = make_armor(300.0, color_name="blue")
    purple = make_armor(500.0, color_name="purple")
    extinguish = make_armor(700.0, color_name="extinguish")
    aim = make_armor(900.0, color_name="red", aim=True)
    host.run_draw([red, blue, purple, extinguish, aim], aim=aim)
    def is_sentinel(got, sentinel):
        return any(c.red() == sentinel.red() and c.green() == sentinel.green() and c.blue() == sentinel.blue()
                   for c in got)
    check("Team：红板变阵营红", is_sentinel(host.colors_at(100), host.RED_SENTINEL), str(host.colors_at(100)))
    check("Team：蓝板变阵营蓝", is_sentinel(host.colors_at(300), host.BLUE_SENTINEL), str(host.colors_at(300)))
    check("Team：认不出的板回落纯白（涂错比不涂危险）",
          all(c.name().upper() == "#FFFFFF" for c in host.colors_at(500) + host.colors_at(700)),
          str(host.colors_at(500) + host.colors_at(700)))
    aim_face = host.colors_at(900)
    check("Team：主目标面用 aim 板自己的颜色（旧版传 None 测不出这条）",
          any(c.red() == 255 and c.green() == 0 and c.blue() == 0 and c.alphaF() == 1.0 for c in aim_face),
          str(aim_face))


def test_accent_routes_through_hud_accent() -> None:
    host = Host()
    host.set_color("Accent")
    plate = make_armor(100.0, color_name="red")
    host.run_draw([plate])
    got = host.colors_at(100)
    check("Accent：全部消费点吃到主题强调色",
          got and all(c.red() == 0 and c.green() == 255 and c.blue() == 0 for c in got), str(got))


def test_polar_outline_path_shares_the_helper() -> None:
    """Polar Outline 路径以前留着旧 primary——开关在这条路径必须同样生效。"""
    host = Host()
    esp = host.registry.get("Armor3DESP")
    show_labels = esp.get_setting("Show Labels")
    if show_labels is not None:
        show_labels.value = True  # 标签 pill 只在 Show Labels 下出现
    host.set_overlay_style("Polar Outline")
    host.set_color("Team")
    red = make_armor(100.0, color_name="red")
    purple = make_armor(500.0, color_name="purple")
    host.run_draw([red, purple])
    pills = [r[2] for r in host.records if r[0] == "pill"]
    check("Polar Outline：标签按板色（红板变色）",
          any(c.red() == 255 and c.green() == 0 and c.blue() == 0 for c in pills), str(pills))
    check("Polar Outline：认不出的板仍纯白",
          any(c.name().upper() == "#FFFFFF" for c in pills), str(pills))


def test_threat_degrades_with_a_reason() -> None:
    host = Host()
    host.set_color("Threat")
    mode, reason = host.robot_overlay_color_mode()
    check("Threat 降级为 Team（无威胁度数据，不谎称按威胁着色）",
          mode == "Team" and "no data source" in reason, f"{mode}/{reason}")
    aim = make_armor(900.0, color_name="red", aim=True)
    host.run_draw([aim], aim=aim)
    check("降级后诊断字段每帧都写（不能停在上帧旧值）",
          host.robot_overlay_color_actual == "Team" and host.robot_overlay_color_reason != "",
          f"{host.robot_overlay_color_actual}/{host.robot_overlay_color_reason}")


def test_broken_values_fall_back_never_crash() -> None:
    host = Host()
    host.set_color("Nonsense")
    mode, reason = host.robot_overlay_color_mode()
    check("未知取值回落 White 且记录原因",
          mode == "White" and "Nonsense" in reason, f"{mode}/{reason}")
    host2 = Host()
    overlay = host2.registry.get("RobotOverlay")
    overlay.settings = [s for s in overlay.settings if s.name != "Color"]
    mode2, reason2 = host2.robot_overlay_color_mode()
    check("设置项整个缺失时按默认 White 回落且不抛异常",
          mode2 == "White" and reason2 == "", f"{mode2}/{reason2}")


def main() -> int:
    test_default_white_is_pixel_unchanged()
    test_team_uses_plate_color_only_when_identifiable()
    test_accent_routes_through_hud_accent()
    test_polar_outline_path_shares_the_helper()
    test_threat_degrades_with_a_reason()
    test_broken_values_fall_back_never_crash()
    print(f"\n合计 {len(FAILED)} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
