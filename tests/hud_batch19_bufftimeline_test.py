"""第 19 批验收：`BuffTimeline` 的三个开关（Buffs / Special Mechanism / Timeline）。

这个模块此前**一个消费者都没有**：界面上能开、三个子开关全勾着，屏幕上
什么都不会多出来。数据其实早就到了 —— 裁判的 Buff 报文解码头进
`state.buff_rows`（带名字、剩余秒数、robot_id、buff_type），
`GlobalSpecialMechanism` 解码头进 `state.special_mechanisms` —— 只是全仓没人读。
所以这不是"忘了接线"，是**缺一个面板**。

落位是量出来的，不是猜的：`tools/audit_settings` 那套取证之外，本仓库有
`tactical_map_rect()` / `hud_density()` 这类纯几何函数，先问出
1600x900 / 1920x1080 / 1280x720 下地图面板底部到屏幕底部都有 535px 以上余量，
才把标签带定在地图下方 6px 处。而模块列表本来也有一条"右侧放不下就落在
地图下方"的路径 —— 两处共用 `buff_timeline_band()` 这一个真相源，
所以叠在一起在结构上不可能发生（本文件第 10 组断言钉住）。

不发明比例条：报文只给剩余秒数、不给总时长，用猜出来的满量程画进度
就是在骗操作员。因此 `Timeline` 的含义定为"标签上带不带剩余秒数"。

默认画面必须不变：没有真实数据时这条带**不出现也不占位**（第 1、8 组），
LabDebug 的演示增益行没有 buff_type，会被过滤掉（第 2 组）。

    python tests/hud_batch19_bufftimeline_test.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b19_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.ui.polar.renderers.tactical_map import TacticalMapMixin  # noqa: E402

# 先建 QApplication 再用 QImage/QPainter：没应用程序就开工字体数据库会直接
# 把进程带崩（实测退出码 0xC0000409，而且输出全丢——看起来像“全部通过”）。
_QAPP = QApplication.instance() or QApplication([])

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    # flush：本文件有子进程与真窗口，崩在下一步时已说过的话不能一起丢。
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""), flush=True)


class FakeConfig:
    def __init__(self, key: str = "RMUC7v7") -> None:
        self.key = key
        self.title = "7v7"


class FakeModeManager:
    def __init__(self, key: str = "RMUC7v7") -> None:
        self.current = FakeConfig(key)


class Host(TacticalMapMixin):
    """最小桩宿主。几何与标签构造用**真**实现。"""

    def __init__(self) -> None:
        self.registry = build_default_registry()
        self.state = RobotState()
        self.match_mode_manager = FakeModeManager()
        self.hotspots: list = []

    def _bool_on(self, module_name, setting_name, default=True):   # noqa: D102
        module = self.registry.get(module_name)
        if module is None:
            return default
        setting = module.get_setting(setting_name)
        if setting is None:
            return default
        return bool(getattr(setting, "value", default))

    def tactical_map_rect(self, width: int, height: int) -> QRectF:
        # 实测值：1600x900 逻辑尺寸下地图面板 = (12, 48, 216, 142)
        return QRectF(12.0, 48.0, 216.0, 142.0)

    def hud_density(self) -> str:
        return "Balanced"

    def font(self, name: str, size: float):
        return (name, size)

    def text_advance(self, font, text: str) -> float:
        return len(text) * 4.2

    def draw_text(self, p, rect, text, font, color, align=None) -> None:
        self.drawn.append(text)

    def hud_accent(self):
        return "ACCENT"

    def hud_warning(self):
        return "WARNING"

    def add_hotspot(self, rect, action, payload, tooltip="") -> None:
        self.hotspots.append((action, payload))

    def toggle(self, setting: str, value: bool) -> None:
        module = self.registry.get("BuffTimeline")
        module.enabled = True
        module.get_setting(setting).value = value

    def feed_own_buff(self, name="Attack Boost", remaining=12, robot_id=None):
        self.state.buff_rows = [{
            "name": name, "active": True, "remaining": remaining,
            "buff_type": 1, "robot_id": self.state.robot_id if robot_id is None else robot_id,
        }]

    def feed_mechanism(self, mechanism_id=3, time_sec=45):
        self.state.special_mechanisms = [{"mechanism_id": mechanism_id, "time_sec": time_sec}]


def label_host() -> Host:
    host = Host()
    host.drawn = []
    host.toggle("Buffs", True)
    host.toggle("Special Mechanism", True)
    host.toggle("Timeline", True)
    return host


def test_no_data_means_no_panel_default_picture_unchanged() -> None:
    """没有真实数据时既不出现也不占位——默认画面必须与接线前一致。"""
    host = Host()
    check("默认有 BuffTimeline 模块且开着", host.registry.get("BuffTimeline").enabled is True)
    check("无数据时无标签", host.buff_timeline_rows() == [], str(host.buff_timeline_rows()))
    check("无数据时不占带（不拉高任何面板）",
          host.buff_timeline_band(1333, 750) is None)


def test_laboratory_mock_rows_are_not_presented_as_real_buffs() -> None:
    """LabDebug 的演示行没有 buff_type，必须被过滤——否则会凭空多出一排假标签。"""
    host = label_host()
    host.state.buff_rows = [{"name": "Cooldown", "active": True, "remaining": 26}]
    check("mock 行（无 buff_type）不进标签", host.buff_timeline_rows() == [],
          str(host.buff_timeline_rows()))
    check("因此 mock 演示下也不占带", host.buff_timeline_band(1333, 750) is None)


def test_only_own_robot_buffs_are_shown() -> None:
    """队友/敌方的增益绝不能显示成本机状态。"""
    host = label_host()
    host.state.buff_rows = [{
        "name": "Attack Boost", "active": True, "remaining": 12,
        "buff_type": 1, "robot_id": int(host.state.robot_id) + 4,
    }]
    check("别的机器人的增益被过滤", host.buff_timeline_rows() == [], str(host.buff_timeline_rows()))

    host.feed_own_buff(remaining=0)
    host.state.buff_rows[0]["active"] = False
    check("已不生效的本机增益不出现", host.buff_timeline_rows() == [],
          str(host.buff_timeline_rows()))

    host.feed_own_buff(name="Damage Boost", remaining=9)
    rows = host.buff_timeline_rows()
    check("本机生效增益出现", len(rows) == 1 and rows[0] == ("buff", "Damage Boost", 9), str(rows))


def test_three_switches_each_control_one_thing() -> None:
    """三个开关各自有独立效果，且不互相牵连。"""
    host = label_host()
    host.feed_own_buff(name="Attack Boost", remaining=12)
    host.feed_mechanism(mechanism_id=3, time_sec=45)
    kinds = {row[0] for row in host.buff_timeline_rows()}
    check("两类数据同时在场时都出现", kinds == {"buff", "mechanism"}, str(kinds))

    host.toggle("Buffs", False)
    kinds = {row[0] for row in host.buff_timeline_rows()}
    check("关掉 Buffs 只剩特殊机制", kinds == {"mechanism"}, str(kinds))

    host.toggle("Buffs", True)
    host.toggle("Special Mechanism", False)
    kinds = {row[0] for row in host.buff_timeline_rows()}
    check("关掉 Special Mechanism 只剩增益", kinds == {"buff"}, str(kinds))

    host.toggle("Special Mechanism", True)
    host.drawn = []
    # 用正常尺寸的画布：往 1x1 的 QImage 上画在 Qt 光栅路径里是病态目标，
    # 实测会把进程直接带崩（圆角底会算出零宽度渐变）。
    image = QImage(1400, 800, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    host.draw_buff_timeline_hud(painter, 1333, 750)
    painter.end()
    image = None
    with_time = list(host.drawn)
    check("Timeline 开着时标签带剩余秒数",
          any(t.endswith("12s") for t in with_time) and any(t.endswith("45s") for t in with_time),
          str(with_time))

    host.toggle("Timeline", False)
    host.drawn = []
    image = QImage(1400, 800, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    host.draw_buff_timeline_hud(painter, 1333, 750)
    painter.end()
    image = None
    check("关掉 Timeline 后只剩名字，秒数消失",
          all(not t.endswith("s") for t in host.drawn) and len(host.drawn) == 2, str(host.drawn))
    check("但标签本身仍然在（不变成隐藏信息）", len(host.drawn) == 2, str(host.drawn))


def test_module_disabled_and_garbage_data_are_inert() -> None:
    host = label_host()
    host.feed_own_buff()
    host.feed_mechanism()
    host.registry.get("BuffTimeline").enabled = False
    check("模块整体关掉后无任何标签", host.buff_timeline_rows() == [], str(host.buff_timeline_rows()))
    check("模块关掉后也不占带", host.buff_timeline_band(1333, 750) is None)

    host.registry.get("BuffTimeline").enabled = True
    host.state.buff_rows = [{"name": "X", "active": True, "remaining": "不是数",
                             "buff_type": 1, "robot_id": host.state.robot_id}]
    host.state.special_mechanisms = [{"mechanism_id": 0, "time_sec": 5}, "不是字典"]
    rows = host.buff_timeline_rows()
    check("垃圾剩余秒数按 0 处理而不是崩", any(r[2] == 0 for r in rows), str(rows))
    check("机制 id<=0 与非法条目被跳过", all(r[1] != "MECH0" for r in rows), str(rows))

    host.state.buff_rows = [{"name": f"B{i}", "active": True, "remaining": i,
                             "buff_type": 1, "robot_id": host.state.robot_id} for i in range(9)]
    check("标签数量有上限，不会挤满屏幕",
          len(host.buff_timeline_rows()) == Host.BUFF_TIMELINE_MAX_ITEMS,
          str(len(host.buff_timeline_rows())))


def test_band_sits_below_the_map_and_the_module_list_yields() -> None:
    """几何：带在地图下方且不相交；模块列表落点必须让开这条带。"""
    host = label_host()
    host.feed_own_buff()
    band = host.buff_timeline_band(1333, 750)
    map_rect = host.tactical_map_rect(1333, 750)
    check("带出现在地图下方", band is not None and band.top() >= map_rect.bottom(),
          f"band={band} map.bottom={map_rect.bottom()}")
    check("带与地图面板不相交", band is not None and band.normalized().intersects(map_rect) is False,
          str(band))
    check("带不会跑到屏幕外", band.bottom() < 750.0, f"{band.bottom()}")

    # 模块列表的落点：共用同一个 band，所以它必须从带子下面开始。
    below_start_with_band = band.bottom() + 14
    below_start_without = map_rect.bottom() + 14
    check("有带时模块列表落点被推下", below_start_with_band > below_start_without,
          f"{below_start_with_band} vs {below_start_without}")
    host.registry.get("BuffTimeline").enabled = False
    check("无带时落点回到原值（不改现有布局）",
          host.buff_timeline_band(1333, 750) is None)


def _pixel_probe_child() -> int:
    """子进程入口：用真窗口真字体把带画到 QImage 上，报告亮像素数。

    为什么必须子进程：在同一进程里先建 QImage/QPainter 再构造真
    PolarRMWindow（QOpenGLWidget）会直接带崩整个测试（实测退出码
    0xC0000409，输出全丢）。分开跑之后，即使那边崩了，本文件也能
    把它当成一条失败报出来而不是假绿。
    """
    app = QApplication.instance() or QApplication([])
    del app
    from rm_client.ui.polar_app import PolarRMWindow

    win = PolarRMWindow()
    win.resize(1600, 900)
    scale = win.get_hud_scale(1600, 900)
    lw, lh = int(1600 / scale), int(900 / scale)
    win.state.buff_rows = [{
        "name": "Attack Boost", "active": True, "remaining": 12,
        "buff_type": 1, "robot_id": win.state.robot_id,
    }]
    win.state.special_mechanisms = [{"mechanism_id": 3, "time_sec": 45}]
    band = win.buff_timeline_band(lw, lh)
    if band is None:
        print("BAND None")
        return 3
    # 用逻辑尺寸作为画布尺寸，带坐标才能直接对应到像素上。
    image = QImage(lw, lh, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        win.draw_buff_timeline_hud(painter, lw, lh)
    finally:
        painter.end()
    lit = sum(
        1 for y in range(int(band.top()), min(lh, int(band.bottom()) + 1))
        for x in range(int(band.left()), min(lw, int(band.right()) + 1))
        if image.pixelColor(x, y).alpha() > 8
    )
    print(f"LIT {lit}")
    # 再把模块关掉：带必须消失（否则“关掉”只是说说而已）。
    win.registry.get("BuffTimeline").enabled = False
    gone = win.buff_timeline_band(lw, lh) is None
    print(f"GONE {'yes' if gone else 'no'}")
    win.close()
    return 0 if (lit > 200 and gone) else 4


def test_real_widget_paints_visible_pixels_in_the_band() -> None:
    """真窗口 + 真字体：带里必须真的有像素，而不是只有函数被调用过。"""
    if "--pixel-probe" in sys.argv:
        raise SystemExit(_pixel_probe_child())
    result = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--pixel-probe"],
        capture_output=True, cwd=ROOT,
    )
    out = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    lit = None
    for line in out.splitlines():
        if line.startswith("LIT "):
            lit = int(line.split()[1])
    check("真窗口子进程跑完没崩", result.returncode in (0, 4),
          f"exit={result.returncode} out={out.strip()[:180]}")
    check("带里有真实亮像素（真字体、真圆角底）", lit is not None and lit > 200,
          f"lit={lit} out={out.strip()[:160]}")
    check("真窗口下关掉模块后带消失", "GONE yes" in out, out.strip()[-120:])


def main() -> int:
    for fn in (
        test_no_data_means_no_panel_default_picture_unchanged,
        test_laboratory_mock_rows_are_not_presented_as_real_buffs,
        test_only_own_robot_buffs_are_shown,
        test_three_switches_each_control_one_thing,
        test_module_disabled_and_garbage_data_are_inert,
        test_band_sits_below_the_map_and_the_module_list_yields,
        test_real_widget_paints_visible_pixels_in_the_band,
    ):
        fn()
    print(f"\n合计 {len(FAILED)} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
