"""第 21 批验收：`RadarOverlay / Map`（雷达叠加画在哪）接通。

接线前的实际行为是**缩略态与展开态都画**，而设置项默认写的是 `Mini`——
从来没对应过任何行为。`MapMarker / Send All`、`RobotOverlay / Color` 的
同型问题，同一处理：**把默认改成等于今天的画面（Both），再逐项接上**。

展开判定不另造阈值：`draw_radar_overlay` 自己已经在算 `detail`
（0=缩略、1=长按展开），Mini/Full 就用它，两处面板（经典 / 液态玻璃）
共用同一个门，不会出现“开关一处有效一处无效”。

本文件钉住的安全约束：
  * 默认 Both：返回值、热区、图元与接线前逐值相同——升级不改画面。
  * 值不认识/设置项缺失：回落 Both（宁可多画，绝不静默吞情报）。
  * 本仓雷达数据只有一个消费者（本函数）；防未来第二处手写画雷达绕过开关。

    python tests/hud_batch21_radaroverlay_map_test.py
"""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b21_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rm_client.match_modes import FieldLayout  # noqa: E402
from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import (  # noqa: E402
    TacticalMapMixin,
    draw_radar_overlay,
)

# 先建 QApplication 再用 QImage/QPainter（batch19 的教训：没应用就碰
# 字体数据库会把进程整带崩，退出码 0xC0000409，输出全丢）。
_QAPP = QApplication.instance() or QApplication([])

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""), flush=True)


FIELD = FieldLayout(key="RMUC7v7", title="7v7", asset_path="", width_m=28.0, height_m=15.0)
MAP_RECT = QRectF(10.0, 10.0, 300.0, 180.0)


class Host(TacticalMapMixin):
    """最小桩宿主：几何、高亮判定、TTL 全部用真实现。"""

    def __init__(self) -> None:
        self.registry = build_default_registry()
        self.state = RobotState()
        self.hotspots: list = []
        self.texts: list = []
        self.state.radar_detections = [
            {"target_pos_x": 1400.0, "target_pos_y": 750.0, "is_high_light": 0}
        ]
        self.state.radar_detections_at = time.perf_counter()

    def setting_bool(self, module, name, default):  # 真实现依赖持久化层，桩掉
        if module is None:
            return default
        setting = module.get_setting(name)
        return bool(setting.value) if setting else default

    def alliance_side(self) -> str:
        return "Red"  # 不镜像，点位可直接预期

    def add_hotspot(self, rect, kind, index, tooltip=""):
        self.hotspots.append((kind, index))

    def draw_text(self, p, rect, text, font, color_, *a):
        self.texts.append(str(text))

    def hud_warning(self) -> QColor:
        return QColor(255, 165, 0)

    def hud_accent(self) -> QColor:
        return QColor(0, 200, 255)

    def font(self, name, size):
        return (name, size)

    def set_map_mode(self, value: str) -> None:
        module = self.registry.get("RadarOverlay")
        assert module is not None
        setting = module.get_setting("Map")
        assert setting is not None
        setting.value = value

    def draw(self, **kw) -> int:
        image = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            return draw_radar_overlay(self, painter, MAP_RECT, FIELD, **kw)
        finally:
            painter.end()


def test_default_both_reproduces_pre_wiring_picture() -> None:
    host = Host()
    setting = host.registry.get("RadarOverlay").get_setting("Map")
    check("默认值是 Both（不是从没生效过的 Mini）", setting.value == "Both", str(setting.value))
    check("值域含 Both/Mini/Full/Hidden 四档",
          set(setting.options) >= {"Both", "Mini", "Full", "Hidden"}, str(setting.options))
    check("Both：缩略态照画，返回值与热区不变",
          host.draw(detail_progress=0.0) == 1 and host.hotspots == [("radar_blip", 0)], str(host.hotspots))
    host2 = Host()
    check("Both：展开态也照画（=接线前两张图都画）",
          host2.draw(detail_progress=1.0) == 1 and host2.radar_map_reason == "", str(host2.radar_map_actual))
    host3 = Host()
    check("Both：经典面板（不传 detail，compact 决定）仍按原样画",
          host3.draw(compact=False) == 1 and host3.draw(compact=True) == 1)


def test_mini_and_full_split_by_expansion() -> None:
    host = Host()
    host.set_map_mode("Mini")
    check("Mini：缩略态画", host.draw(detail_progress=0.0) == 1, str(host.hotspots))
    host = Host()
    host.set_map_mode("Mini")
    check("Mini：展开态不画（返回 0、零热区）",
          host.draw(detail_progress=1.0) == 0 and not host.hotspots, str(host.hotspots))
    host = Host()
    host.set_map_mode("Full")
    check("Full：缩略态不画", host.draw(detail_progress=0.0) == 0, str(host.hotspots))
    host = Host()
    host.set_map_mode("Full")
    check("Full：展开态画", host.draw(detail_progress=1.0) == 1, str(host.hotspots))


def test_hidden_hides_both_forms_only_drawing() -> None:
    host = Host()
    host.set_map_mode("Hidden")
    check("Hidden：两种形态都不画",
          host.draw(detail_progress=0.0) == 0 and host.draw(detail_progress=1.0) == 0, str(host.hotspots))
    check("Hidden：数据与 TTL 不受影响（state 仍在，只是不显示）",
          len(host.state.radar_detections) == 1 and host.state.radar_detections_at > 0)


def test_broken_values_fall_back_to_drawing() -> None:
    host = Host()
    host.set_map_mode("Nonsense")
    drawn = host.draw(detail_progress=1.0)
    check("未知取值回落 Both（宁可多画不吞情报）且记原因",
          drawn == 1 and "unknown" in host.radar_map_reason, host.radar_map_reason)
    host2 = Host()
    mod = host2.registry.get("RadarOverlay")
    mod.settings = [s for s in mod.settings if s.name != "Map"]
    check("设置项整个缺失也回落画", host2.draw(detail_progress=0.0) == 1)


def test_stale_data_path_untouched() -> None:
    host = Host()
    host.set_map_mode("Mini")
    host.state.radar_detections = []
    check("无数据：返回 0 与接线前一致（开关不改变空数据路径）", host.draw(detail_progress=0.0) == 0)
    host.state.radar_detections = [{"target_pos_x": 100.0, "target_pos_y": 100.0, "is_high_light": 0}]
    host.state.radar_detections_at = time.perf_counter() - 999.0
    check("过期数据：TTL 依旧先于开关拦下（返回 0）", host.draw(detail_progress=0.0) == 0)


def test_single_consumer_guard() -> None:
    """雷达数据全仓只允许 draw_radar_overlay 一个绘制消费者，防止未来绕过开关。"""
    src = os.path.join(ROOT, "rm_client", "ui", "polar", "renderers", "tactical_map.py")
    text = io.open(src, encoding="utf-8").read()
    body = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    calls = len(re.findall(r"draw_radar_overlay\(\s*self", body))
    seg = body.split("def draw_radar_overlay")[1].split("def draw_penalty_strip")[0]
    outside = body.count("state.radar_detections") - seg.count("state.radar_detections")
    check("state.radar_detections 在本文件里只被 draw_radar_overlay 引用",
          seg.count("state.radar_detections") >= 1 and outside == 0, f"outside={outside}")
    check("两个面板路径共用 draw_radar_overlay（恰好 2 处调用）", calls == 2, f"calls={calls}")
    other = [p for p in ("ui/polar_app.py", "ui/polar/mixins/persistence_mixin.py")
             if "radar_detections" in io.open(os.path.join(ROOT, "rm_client", *p.split("/")), encoding="utf-8").read()]
    check("除 tactical_map 外无第二个读取 radar_detections 的 UI 文件", not other, str(other))


def main() -> int:
    test_default_both_reproduces_pre_wiring_picture()
    test_mini_and_full_split_by_expansion()
    test_hidden_hides_both_forms_only_drawing()
    test_broken_values_fall_back_to_drawing()
    test_stale_data_path_untouched()
    test_single_consumer_guard()
    print(f"\n合计 {len(FAILED)} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
