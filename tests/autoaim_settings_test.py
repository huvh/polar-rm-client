"""ArmorAutoAim 的 `Fov` / `Priority` 接线验收。

这两个设置项原本是**纯装饰**：

    `Fov`       界面上能拖 10~180 度，全仓没人读它。实际锁定范围只由
                像素半径 `Circle Size` 决定，拖这个数什么都不变。
    `Priority`  下拉框有 Armor/Distance/Health/Radar 四个选项，但选靶代码
                写死 `max(..., key=confidence)`，选哪个都一样。

本文件断言它们现在**真的影响结果**，并且断言它们在数据不足时
**如实降级**而不是假装生效。

不构造真实窗口：只把 EspWireframeMixin 的这几个方法绑到最小桩对象上，
这样测试不依赖 Qt 事件循环，也能精确控制内参与血量表。

    python tests/autoaim_settings_test.py
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 本测试不构造窗口，但仍隔离用户数据目录，避免任何配置写入开发机存档。
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_autoaim_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.model import build_default_registry  # noqa: E402
from rm_client.vision import ArmorObservation, VisionResult  # noqa: E402
from rm_client.ui.polar.renderers.esp_wireframe import EspWireframeMixin  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class FakeProfile:
    def __init__(self, fx: float, width: int = 1280, height: int = 720) -> None:
        # camera_matrix 是行主序 3x3：[0]=fx, [4]=fy, [2]=cx, [5]=cy
        self.camera_matrix = [fx, 0.0, width / 2.0, 0.0, fx, height / 2.0, 0.0, 0.0, 1.0]
        self.width = width
        self.height = height
        self.sample_count = 12
        self.rms_error_px = 0.5


class FakeCalibration:
    """可切换"已标定/未标定"的桩。"""

    def __init__(self, profile=None) -> None:
        self.profile = profile
        self.valid = profile is not None

    def is_valid_for(self, width: int, height: int) -> bool:
        return bool(
            self.valid
            and self.profile is not None
            and self.profile.width == width
            and self.profile.height == height
        )


class StubPoint:
    """只为了顶替 QPointF：真实的 armor_center_in_autoaim_fov 调 .x()/.y()。"""

    __slots__ = ("_x", "_y")

    def __init__(self, x: float, y: float) -> None:
        self._x = float(x)
        self._y = float(y)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class Host(EspWireframeMixin):
    """最小桩：只提供被测方法用到的依赖。

    注意：`armor_center_in_autoaim_fov` / `apply_autoaim_fov_lock` 本身**不桩**，
    只桩它们外面的 QWidget 尺寸与坐标变换。否则测不到真实链路。
    """

    def __init__(self, calibration=None, state=None) -> None:
        self.registry = build_default_registry()
        self.calibration = calibration or FakeCalibration()
        self.state = state
        self._numbers: dict[str, float] = {}
        self._bools: dict[str, bool] = {}

    # QWidget / 坐标变换边界
    def width(self) -> int:
        return 1280

    def height(self) -> int:
        return 720

    def get_hud_scale(self, width: int, height: int) -> float:
        return 1.0  # 逻辑尺寸 == 控件尺寸 == 源尺寸，避开多余换算误差

    def armor_esp_points(self, points, result, width: int, height: int):
        return [StubPoint(x, y) for x, y in points]

    # 覆盖 mixin 依赖的两个辅助函数，直接返回我们塞进去的值
    def get_setting_number(self, module, name: str, default: float) -> float:
        key = f"{getattr(module, 'name', '?')}/{name}"
        if key in self._numbers:
            return self._numbers[key]
        setting = module.get_setting(name) if module is not None else None
        if setting is None:
            return float(default)
        try:
            return float(setting.value)
        except (TypeError, ValueError):
            return float(default)

    def set(self, module_name: str, setting: str, value) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = True
        st = mod.get_setting(setting)
        assert st is not None, setting
        st.value = value

    def enable(self, module_name: str, on: bool = True) -> None:
        mod = self.registry.get(module_name)
        assert mod is not None, module_name
        mod.enabled = on


def armor(
    cx: float,
    cy: float,
    *,
    confidence: float = 0.8,
    distance_m: float = 0.0,
    depth_m: float = 0.0,
    target_id: int = -1,
    plate_id: int = -1,
    size: float = 20.0,
) -> ArmorObservation:
    return ArmorObservation(
        armor_id=max(0, plate_id),
        label="normal",
        color="red",
        confidence=confidence,
        points=(
            (cx - size, cy - size),
            (cx + size, cy - size),
            (cx + size, cy + size),
            (cx - size, cy + size),
        ),
        distance_m=distance_m,
        depth_m=depth_m,
        target_id=target_id,
        plate_id=plate_id,
    )


def result(dets, *, w: int = 1280, h: int = 720, aim=None, tracked: str = "detected") -> VisionResult:
    return VisionResult(
        sequence=1,
        timestamp_ns=1,
        source_width=w,
        source_height=h,
        detections=tuple(dets),
        aim_armor=aim,
        tracking_state=tracked,
        calibrated=True,
    )


# ---------------------------------------------------------------------------
def test_fov_setting_changes_lock_eligibility() -> None:
    """`Fov` 必须真的改变"哪些装甲板可以被锁定"。"""
    host = Host(calibration=FakeCalibration(FakeProfile(fx=600.0)))
    host.set("ArmorAutoAim", "Circle Size", 100000.0)  # 放开像素圆，单测角度门
    host.set("ArmorAutoAim", "Fov", 85.0)
    host.set("ArmorAutoAim", "Draw Fov", True)

    # 中心偏右 400px 的一块装甲（源图 1280x720，中心 640,360）
    far = armor(1040.0, 360.0, plate_id=1)
    centre = armor(650.0, 365.0, plate_id=2)

    r = host.autoaim_fov_radius_source_px()
    check("Fov 能换算出像素半径", r is not None and r > 0.0, str(r))
    # 期望值：fx * tan(fov/2)
    expected = 600.0 * math.tan(math.radians(85.0) * 0.5)
    check("换算式是 fx*tan(fov/2)（针孔模型精确关系）",
          r is not None and abs(r - expected) < 1e-6, f"{r} vs {expected}")

    # 85 度时半径 ~550px，400px 偏移在门内
    check("85 度时偏 400px 的靶仍可锁定",
          host.armor_center_in_autoaim_fov_angle(far, result([far, centre])))

    # 收窄到 20 度：半径 ~107px，400px 偏移应被排除
    host.set("ArmorAutoAim", "Fov", 20.0)
    check("收窄到 20 度后，同一个靶被排除（设置项真的影响行为）",
          not host.armor_center_in_autoaim_fov_angle(far, result([far, centre])),
          str(host.autoaim_fov_radius_source_px()))
    check("中心靶不受影响",
          host.armor_center_in_autoaim_fov_angle(centre, result([far, centre])))

    # 端到端：20 度时选靶只能选到中心那块
    host.set("ArmorAutoAim", "Priority", "Armor")
    # 让"远"靶置信度更高，证明它确实是被角度门排除而不是被排名挤掉
    out = host.apply_autoaim_fov_lock(
        result([armor(1040.0, 360.0, confidence=0.99, plate_id=1),
                armor(650.0, 365.0, confidence=0.10, plate_id=2)]))
    check("端到端：窄视场角下高置信度的门外靶不会被选中",
          out.aim_armor is not None and int(out.aim_armor.plate_id) == 2,
          str(None if out.aim_armor is None else out.aim_armor.plate_id))


def test_fov_fails_open_without_calibration() -> None:
    """拿不到内参时必须"不加这道门"，而不是猜一个换算系数。"""
    host = Host(calibration=FakeCalibration(None))
    host.set("ArmorAutoAim", "Circle Size", 100000.0)
    host.set("ArmorAutoAim", "Fov", 20.0)
    far = armor(1040.0, 360.0, plate_id=1)
    check("未标定时算不出像素半径", host.autoaim_fov_radius_source_px() is None)
    check("未标定时不加角度门槛（行为与接线前一致）",
          host.armor_center_in_autoaim_fov_angle(far, result([far])))

    # 分辨率与标定时不一致 -> 内参不适用，同样不得瞎换算
    host2 = Host(calibration=FakeCalibration(FakeProfile(600.0, width=1920, height=1080)))
    host2.set("ArmorAutoAim", "Circle Size", 100000.0)
    host2.set("ArmorAutoAim", "Fov", 20.0)
    check("标定分辨率与当前帧不符时不加门",
          host2.armor_center_in_autoaim_fov_angle(far, result([far])))

    # 垃圾值不得把自瞄整个关掉
    for bad in (0.0, -30.0, 400.0, "abc"):
        host.set("ArmorAutoAim", "Fov", bad)
        try:
            got = host.autoaim_fov_radius_source_px()
        except Exception as exc:  # noqa: BLE001
            check(f"垃圾 Fov={bad!r} 不抛异常", False, repr(exc))
            continue
        check(f"垃圾 Fov={bad!r} 归为不加门", got is None, str(got))


def test_priority_changes_target_selection() -> None:
    """`Priority` 必须真的改变选中的靶，而不是写死按置信度。"""
    host = Host(calibration=FakeCalibration(FakeProfile(600.0)))
    host.set("ArmorAutoAim", "Circle Size", 100000.0)
    host.set("ArmorAutoAim", "Fov", 180.0)  # 放到最宽，角度门不干扰排名

    # 近处一块低置信度靶 + 远处一块高置信度靶
    near = armor(600.0, 360.0, confidence=0.20, distance_m=2.0, plate_id=11, target_id=101)
    far = armor(700.0, 360.0, confidence=0.95, distance_m=15.0, plate_id=12, target_id=102)

    host.set("ArmorAutoAim", "Priority", "Armor")
    picked = host.pick_autoaim_armor([near, far], "Armor")
    check("Armor 优先级按置信度选（保持原行为）",
          picked is far, str(getattr(picked, "plate_id", None)))

    picked = host.pick_autoaim_armor([near, far], "Distance")
    check("Distance 优先级按距离选（结果与 Armor 不同 => 设置项生效）",
          picked is near, str(getattr(picked, "plate_id", None)))
    check("Distance 生效时记录 actual，不留旧值",
          host.autoaim_priority_actual == "Distance", host.autoaim_priority_actual)
    check("Distance 生效时无降级原因",
          host.autoaim_priority_reason == "", host.autoaim_priority_reason)


def test_priority_degrades_honestly_without_data() -> None:
    """数据不足时必须降级并**说明原因**，不能假装按血量/雷达选了。"""

    class FakeState:
        def __init__(self, rows) -> None:
            self.robot_rows = rows

    near = armor(600.0, 360.0, confidence=0.20, distance_m=2.0, plate_id=11, target_id=101)
    far = armor(700.0, 360.0, confidence=0.95, distance_m=15.0, plate_id=12, target_id=102)

    # 1) 没有裁判系统血量（台架常态）
    host = Host(calibration=FakeCalibration(FakeProfile(600.0)), state=FakeState([]))
    picked = host.pick_autoaim_armor([near, far], "Health")
    check("无血量数据时降级为按置信度", picked is far)
    check("降级原因非空（不能静默）", host.autoaim_priority_reason != "",
          host.autoaim_priority_reason)
    check("降级后 actual 报 Armor 而不是谎称 Health",
          host.autoaim_priority_actual == "Armor", host.autoaim_priority_actual)

    # 2) 有血量：应选残血那台，即使另一块置信度更高
    host2 = Host(
        calibration=FakeCalibration(FakeProfile(600.0)),
        state=FakeState([
            {"id": 101, "hp": 60, "max": 450, "state": "ALIVE"},
            {"id": 102, "hp": 430, "max": 450, "state": "ALIVE"},
        ]),
    )
    picked = host2.pick_autoaim_armor([near, far], "Health")
    check("有血量数据时优先打残血靶（覆盖置信度排名）",
          picked is near, str(getattr(picked, "plate_id", None)))
    check("Health 真的生效时 actual=Health 且无降级原因",
          host2.autoaim_priority_actual == "Health"
          and host2.autoaim_priority_reason == "",
          f"{host2.autoaim_priority_actual}/{host2.autoaim_priority_reason}")

    # 3) 阵亡目标不能因为"血量低"被选中（那是死车）
    host3 = Host(
        calibration=FakeCalibration(FakeProfile(600.0)),
        state=FakeState([
            {"id": 101, "hp": 0, "max": 450, "state": "DEAD"},
            {"id": 102, "hp": 430, "max": 450, "state": "ALIVE"},
        ]),
    )
    picked = host3.pick_autoaim_armor([near, far], "Health")
    check("已阵亡的靶不按低血量优先", picked is far,
          str(getattr(picked, "plate_id", None)))

    # 4) Radar 是刻意未实现的，必须明说而不是静默按置信度
    picked = host2.pick_autoaim_armor([near, far], "Radar")
    check("Radar 未实现时降级为置信度", picked is far)
    check("Radar 的降级原因点明了未实现",
          "未实现" in host2.autoaim_priority_reason, host2.autoaim_priority_reason)

    # 5) 未知取值不得崩，也不得乱选
    picked = host2.pick_autoaim_armor([near, far], "随便写的")
    check("未知优先级归为置信度且记录原因",
          picked is far and host2.autoaim_priority_actual == "Armor")

    # 6) 空候选集不得崩
    check("空候选集返回 None 不抛异常", host2.pick_autoaim_armor([], "Distance") is None)


def test_distance_missing_data_does_not_become_nearest() -> None:
    """距离取不到时必须是"最远"而不是 0（0 会被当成贴脸插到最前）。"""
    host = Host(calibration=FakeCalibration(FakeProfile(600.0)))
    unknown = armor(600.0, 360.0, confidence=0.99, plate_id=21)      # 没有距离
    known = armor(700.0, 360.0, confidence=0.10, distance_m=9.0, plate_id=22)

    check("缺距离时返回 inf 而不是 0",
          host._armor_distance_m(unknown) == float("inf"),
          str(host._armor_distance_m(unknown)))
    picked = host.pick_autoaim_armor([unknown, known], "Distance")
    check("缺距离的靶不会被误判成最近而抢到优先",
          picked is known, str(getattr(picked, "plate_id", None)))


def test_module_disabled_keeps_previous_behavior() -> None:
    """ArmorAutoAim 关闭时不得对结果做任何裁剪。"""
    host = Host(calibration=FakeCalibration(FakeProfile(600.0)))
    host.set("ArmorAutoAim", "Circle Size", 100000.0)
    host.set("ArmorAutoAim", "Fov", 20.0)
    host.enable("ArmorAutoAim", False)
    far = armor(1040.0, 360.0, plate_id=1)
    res = result([far], aim=far, tracked="locked")
    out = host.apply_autoaim_fov_lock(res)
    check("模块关闭时原样返回，不裁目标、不改锁定状态",
          out is res or (out.aim_armor is far and out.tracking_state == "locked"))
    check("模块关闭时算不出像素半径（不参与判定）",
          host.autoaim_fov_radius_source_px() is None)


def main() -> int:
    tests = [
        test_fov_setting_changes_lock_eligibility,
        test_fov_fails_open_without_calibration,
        test_priority_changes_target_selection,
        test_priority_degrades_honestly_without_data,
        test_distance_missing_data_does_not_become_nearest,
        test_module_disabled_keeps_previous_behavior,
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
    print("ALL AUTOAIM-SETTINGS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
