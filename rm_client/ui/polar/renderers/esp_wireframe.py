"""阶段 2b 渲染器提取：目标锁定 / 自瞄 FOV / ESP 线框族（D8）→ EspWireframeMixin。

（REFACTOR_BLUEPRINT §5 阶段 2 表 2b 行 / §5.6 冻结面 / §6 性能红线）

迁移范围（以 grep 重定位后的实际行号为准，蓝图原行号 5283–5429 / 7244–7545 /
7551–8186 已因多轮修复漂移）：
- FOV/锁定判定：``autoaim_logical_size`` / ``autoaim_circle_radius`` /
  ``sync_local_autoaim_fov`` / ``armor_center_in_autoaim_fov`` /
  ``vision_target_in_autoaim_fov`` / ``apply_autoaim_fov_lock`` /
  ``vision_result_for_display`` / ``interpolated_vision_result`` /
  ``vision_result_calibrated``
- ESP 绘制：``draw_target_overlay``、荧光白族 ``draw_fluorescent_white_segments`` /
  ``draw_fluorescent_white_polyline`` / ``rasterize_fluorescent_white_circle`` /
  ``draw_fluorescent_white_ellipse``、``draw_armor_fov_circle``、三种锁框
  ``draw_white_outline_lock`` / ``draw_minimal_bracket_lock`` / ``draw_rune_ring_lock``、
  ``target_overlay_label``、``armor_esp_points`` / ``armor_esp_back_points`` /
  ``draw_3d_esp_box`` / ``constrain_prediction_geometry`` / ``draw_clean_3d_esp_box`` /
  ``draw_polar_mechanical_wire``、GPU 批量线框 ``_vision_wire_key`` /
  ``_append_vision_wire_armor`` / ``build_vision_wire_batch`` /
  ``paint_gpu_vision_layer``、``draw_armor_quad`` / ``smooth_armor_geometry`` /
  ``draw_armor_3d_esp``

纪律与偏差决策（中文记录）：
- 方法体**零修改**（含注释与空行），纯移动进本 Mixin；
- ``has_valid_combat_target`` 属 D8，但被阶段 2a 判定**留在 polar_app.py 原地**
  （跨域使用：CombatTargetHudMixin.paint_combat_target_overlay 经 self 调用）——
  本 Mixin 不承载它；
- ``draw_pill`` 不在蓝图 §2 D8 清单内（属 D5 legacy CPU GUI 家族，被多域复用），
  按边界保守原则留在 polar_app.py；本 Mixin 经 self 继续访问，调用面不变；
- ``alliance_side`` 虽紧邻 D8 区段，但属 D7 同济桥域，同样留在原地；
- ``target_overlay_label`` 仅被 D8 锁框族调用，随域迁入并钉回 qualname；
- 状态字段（``_fluorescent_circle_cache`` / ``_armor_geometry_smooth`` /
  ``_vision_render_result`` / ``_vision_snapshot`` / ``_jello_esp_shadow`` /
  ``_bottom_left_diagnostics`` / ``vision_wire_gpu`` / ``vision_render_interpolator``）
  全部仍在 ``PolarRMWindow.__init__`` 原位置初始化（Mixin 只承载方法，不承载构造）；
- ``rasterize_fluorescent_white_circle`` 的有界缓存淘汰策略是 §6 性能红线的
  现成范本，key 生成逻辑一字未改随方法整体搬迁。

冻结面纪律：与阶段 1（text_metrics.py 底部）/ 阶段 2a（combat_target_hud.py 底部）
一致——api_freeze_test 对方法类成员比对 ``__qualname__``（基线值形如
"PolarRMWindow.<name>"），故在本模块底部把全部迁入方法的 ``__qualname__`` 钉回
``PolarRMWindow.<name>``，使 ``window.<name>`` 签名与迁移前 bit 级一致
（含两个 @staticmethod：constrain_prediction_geometry 被 tests/smoke_test.py 以
``PolarRMWindow.constrain_prediction_geometry`` 直调）。
"""

from __future__ import annotations

import math
import time
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QConicalGradient,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)

# 相对导入层级：rm_client/ui/polar/renderers/ → .... = rm_client、... = rm_client.ui
from ....model import Module
from ....vision import VisionResult, VisionTarget
from ...paint import draw_bar, text_width, with_alpha
# 注意：text_metrics 与本模块同属 ui/polar 子包（阶段 1 迁入），故为单级 ..
from ..text_metrics import painter_device_scale
from ...theme import color
from ...vision_wire_gpu import VisionWireBatch

__all__ = [
    "EspWireframeMixin",
]


class EspWireframeMixin:
    """D8 目标锁定 / 自瞄 FOV / ESP 线框绘制族（CPU QPainter + GPU 批量线框）。"""

    def autoaim_logical_size(self) -> tuple[float, float]:
        width = max(1.0, float(self.width()))
        height = max(1.0, float(self.height()))
        scale = max(0.001, self.get_hud_scale(int(width), int(height)))
        return width / scale, height / scale

    def autoaim_circle_radius(self) -> float:
        """Logical-pixel FOV radius from ArmorAutoAim Circle Size."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return 0.0
        return max(8.0, self.get_setting_number(module, "Circle Size", 160.0))

    def sync_local_autoaim_fov(self, source_width: int = 0, source_height: int = 0) -> None:
        """Push FOV ellipse into local YOLO selector (source pixel space)."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            self.local_vision.configure_autoaim_fov(None)
            return
        logical_w, logical_h = self.autoaim_logical_size()
        radius = self.autoaim_circle_radius()
        frame_w = max(1, int(source_width) if source_width > 0 else int(round(logical_w)))
        frame_h = max(1, int(source_height) if source_height > 0 else int(round(logical_h)))
        # Map HUD circle into source so the on-screen FOV matches lock gate.
        radius_x = radius * (frame_w / max(1.0, logical_w))
        radius_y = radius * (frame_h / max(1.0, logical_h))
        self.local_vision.configure_autoaim_fov(radius_x, radius_y)

    def armor_center_in_autoaim_fov(self, armor, result: VisionResult) -> bool:
        """True when armor plate center lies inside the fluorescent FOV circle."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return True
        if armor is None or len(getattr(armor, "points", ())) < 2:
            return False
        logical_w, logical_h = self.autoaim_logical_size()
        radius = self.autoaim_circle_radius()
        points = self.armor_esp_points(armor.points, result, int(round(logical_w)), int(round(logical_h)))
        if not points:
            return False
        cx = sum(point.x() for point in points) / len(points)
        cy = sum(point.y() for point in points) / len(points)
        return math.hypot(cx - logical_w * 0.5, cy - logical_h * 0.5) <= radius

    def vision_target_in_autoaim_fov(self, target: VisionTarget, width: int, height: int) -> bool:
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return True
        radius = self.autoaim_circle_radius()
        cx = target.x + target.w * 0.5
        cy = target.y + target.h * 0.5
        return math.hypot(cx - width * 0.5, cy - height * 0.5) <= radius

    def apply_autoaim_fov_lock(self, result: VisionResult) -> VisionResult:
        """Keep all ESP detections; only plates inside FOV may be aim_armor / locked."""
        module = self.registry.get("ArmorAutoAim")
        if module is None or not module.enabled:
            return result
        aim = result.aim_armor
        if aim is not None and not self.armor_center_in_autoaim_fov(aim, result):
            aim = None
        if aim is None:
            candidates = [
                armor
                for armor in result.detections
                if len(armor.points) == 4 and self.armor_center_in_autoaim_fov(armor, result)
            ]
            if candidates:
                aim = max(candidates, key=lambda armor: float(armor.confidence))
        # Predicted plates of the locked target may still draw; aim face only when in FOV.
        tracking = result.tracking_state
        if aim is None and (result.detections or result.predicted_armors):
            if tracking.lower() in ("locked", "tracking"):
                tracking = "detected"
        return replace(result, aim_armor=aim, tracking_state=tracking)

    def vision_result_for_display(self, result: VisionResult | None) -> VisionResult | None:
        """将灭灯或已确认战亡目标从可视层移除，原始结果继续供 detector 使用。

        Autoaim FOV only strips / reassigns aim_armor; detections stay for full-screen 3D ESP.
        """
        if result is None:
            return None
        detector = self.vision_kill_detector
        hidden_targets = {
            detector.target_identity(armor)
            for armor in result.detections
            if detector.is_extinguished(armor) or detector.is_suppressed(armor)
        }

        def hidden(armor) -> bool:
            return (
                armor.held
                or
                detector.is_extinguished(armor)
                or detector.is_suppressed(armor)
                or detector.target_identity(armor) in hidden_targets
            )

        detections = tuple(armor for armor in result.detections if not hidden(armor))
        predicted = tuple(armor for armor in result.predicted_armors if not hidden(armor))
        aim = result.aim_armor
        if aim is not None and hidden(aim):
            aim = None
        has_visible_target = bool(detections or predicted or aim)
        tracking_state = result.tracking_state if has_visible_target else "lost"
        filtered = replace(
            result,
            detections=detections,
            predicted_armors=predicted,
            aim_armor=aim,
            tracking_state=tracking_state,
        )
        return self.apply_autoaim_fov_lock(filtered)

    def interpolated_vision_result(self, now: float | None = None) -> VisionResult | None:
        """Return geometry sampled on the display clock, never on the camera clock."""
        self._vision_render_result = self.vision_render_interpolator.sample(now)
        return self._vision_render_result

    def vision_result_calibrated(self, result: VisionResult | None) -> bool:
        if result is None or not result.calibrated:
            return False
        return self.calibration.is_valid_for(result.source_width, result.source_height)

    def draw_target_overlay(self, p: QPainter, target: VisionTarget, module: Module | None = None) -> None:
        rect = QRectF(target.x, target.y, target.w, target.h)
        locked = self.state.energy_target_locked if target.kind == "energy" else self.state.target_locked
        setting = module.get_setting("Lock Style") if module else None
        style = str(setting.value) if setting else "Polar Corner"
        main = self.hud_accent() if locked else self.hud_danger()
        if style == "White Outline":
            self.draw_white_outline_lock(p, rect, target, locked)
            return
        if style == "Minimal Bracket":
            self.draw_minimal_bracket_lock(p, rect, target, locked)
            return
        if style == "Rune Ring":
            self.draw_rune_ring_lock(p, rect, target, module, locked)
            return
        if style == "Heli Gimbal":
            # T1（gd656 移植）：第 5 种 Lock Style。实现放在模块级函数
            # _heli_gimbal_lock_draw —— 不新增 PolarRMWindow 成员，
            # api_freeze_test 冻结面保持不变。
            _heli_gimbal_lock_draw(self, p, rect, target, module, locked)
            return

        p.setPen(QPen(with_alpha(main, 0.92), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        p.setPen(QPen(main, 3.2))
        corner = min(28.0, rect.width() * 0.28)
        p.drawLine(rect.topLeft(), rect.topLeft() + QPointF(corner, 0))
        p.drawLine(rect.topLeft(), rect.topLeft() + QPointF(0, corner))
        p.drawLine(rect.topRight(), rect.topRight() + QPointF(-corner, 0))
        p.drawLine(rect.topRight(), rect.topRight() + QPointF(0, corner))
        p.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPointF(corner, 0))
        p.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPointF(0, -corner))
        p.drawLine(rect.bottomRight(), rect.bottomRight() + QPointF(-corner, 0))
        p.drawLine(rect.bottomRight(), rect.bottomRight() + QPointF(0, -corner))
        label = self.target_overlay_label(target)
        self.draw_pill(p, QPointF(rect.left(), rect.top() - 27), label, main)

    def draw_fluorescent_white_segments(
        self,
        p: QPainter,
        segments: list[tuple[QPointF, QPointF]],
        *,
        line_width: float = 1.0,
        glow: float = 0.35,
        alpha: float = 1.0,
        dashed: bool = False,
    ) -> None:
        """Debug 3D Box ESP fluorescent white (visual-demo esp-box-white.html).

        Pure #FFFFFF core at ``line_width`` (~1.0 jar). Soft pass:
        alpha = 0.22 * glow, width = line_width + 2.5 * glow, round caps.
        No fill, no pulse, no cyan tint.
        """
        if not segments:
            return
        base_w = max(0.5, float(line_width))
        glow = max(0.0, min(1.0, float(glow)))
        alpha = max(0.0, min(1.0, float(alpha)))
        style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)

        def stroke(a: float, width: float) -> None:
            if a <= 0.001 or width <= 0.01:
                return
            pen = QPen(QColor(255, 255, 255, max(1, min(255, round(255.0 * a)))), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setStyle(style)
            p.setPen(pen)
            for start, end in segments:
                p.drawLine(start, end)

        if glow > 0.01:
            # Multi-pass pure white bloom (CPU/raster-safe; avoid fat single AA pass).
            stroke(0.06 * glow * alpha, base_w + 8.0 * glow)
            stroke(0.12 * glow * alpha, base_w + 4.0 * glow)
            stroke(0.28 * glow * alpha, base_w + 1.8 * glow)
        # Core jar stroke — RGB 1,1,1.
        stroke(1.0 * alpha, base_w)
        stroke(0.55 * alpha, max(0.55, base_w * 0.45))
        p.restore()

    def draw_fluorescent_white_polyline(
        self,
        p: QPainter,
        points: list[QPointF],
        *,
        closed: bool = True,
        line_width: float = 1.0,
        glow: float = 0.35,
        alpha: float = 1.0,
        dashed: bool = False,
    ) -> None:
        if len(points) < 2:
            return
        limit = len(points) if closed else len(points) - 1
        segments = [(points[i], points[(i + 1) % len(points)]) for i in range(limit)]
        self.draw_fluorescent_white_segments(
            p, segments, line_width=line_width, glow=glow, alpha=alpha, dashed=dashed,
        )

    def rasterize_fluorescent_white_circle(
        self,
        radius: float,
        *,
        line_width: float = 1.15,
        glow: float = 0.85,
        alpha: float = 1.0,
        device_scale: float = 1.0,
    ) -> tuple[QImage, float]:
        """CPU fluorescent white ring at device pixels (sharp on 2K).

        Never drawEllipse on OpenGL (white square atlas). Rasterize 1:1 for the
        current painter scale — no Smooth downscale mush.
        """
        glow = max(0.0, min(1.0, float(glow)))
        alpha = max(0.0, min(1.0, float(alpha)))
        px = max(1.0, float(device_scale))
        cache_key = (
            int(round(float(radius) * px * 2.0)),
            int(round(float(line_width) * px * 100.0)),
            int(round(glow * 100.0)),
            int(round(px * 100.0)),
        )
        if alpha >= 0.999 and cache_key in self._fluorescent_circle_cache:
            return self._fluorescent_circle_cache[cache_key]

        r = max(0.5, float(radius) * px)
        base_w = max(0.75, float(line_width) * px)
        pad = base_w * 0.5 + (2.5 * glow + 8.0 * glow) * 0.5 * px + 3.0 * px
        half = int(math.ceil(r + pad))
        size = max(8, half * 2)
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        ip = QPainter(image)
        ip.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ip.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        ip.setBrush(Qt.BrushStyle.NoBrush)
        center = QPointF(size * 0.5, size * 0.5)

        def stroke(a: float, width: float) -> None:
            if a <= 0.001 or width <= 0.05:
                return
            pen = QPen(QColor(255, 255, 255, max(1, min(255, round(255.0 * a)))), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            ip.setPen(pen)
            ip.drawEllipse(center, r, r)

        if glow > 0.01:
            stroke(0.05 * glow * alpha, base_w + 12.0 * glow * px / max(1.0, px))
            stroke(0.10 * glow * alpha, base_w + 7.0 * glow)
            stroke(0.18 * glow * alpha, base_w + 3.8 * glow)
            stroke(0.32 * glow * alpha, base_w + 1.8 * glow)
        stroke(1.00 * alpha, base_w)
        stroke(0.70 * alpha, max(0.65 * px, base_w * 0.48))
        ip.end()
        half_logical = size * 0.5 / px
        if alpha >= 0.999:
            self._fluorescent_circle_cache[cache_key] = (image, half_logical)
            if len(self._fluorescent_circle_cache) > 48:
                oldest = next(iter(self._fluorescent_circle_cache))
                if oldest != cache_key:
                    self._fluorescent_circle_cache.pop(oldest, None)
        return image, half_logical

    def draw_fluorescent_white_ellipse(
        self,
        p: QPainter,
        center: QPointF,
        radius_x: float,
        radius_y: float | None = None,
        *,
        line_width: float = 1.15,
        glow: float = 0.85,
        alpha: float = 1.0,
    ) -> None:
        """Fluorescent white ellipse via device-scale CPU raster + crisp blit."""
        rx = max(0.5, float(radius_x))
        ry = max(0.5, float(radius_x if radius_y is None else radius_y))
        radius = max(rx, ry)
        device_scale = self.painter_device_scale(p)
        image, half = self.rasterize_fluorescent_white_circle(
            radius, line_width=line_width, glow=glow, alpha=alpha, device_scale=device_scale,
        )
        if rx != ry and ry > 0.5:
            target = QRectF(
                center.x() - half * (rx / radius),
                center.y() - half * (ry / radius),
                half * 2.0 * (rx / radius),
                half * 2.0 * (ry / radius),
            )
        else:
            target = QRectF(center.x() - half, center.y() - half, half * 2.0, half * 2.0)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # No SmoothPixmapTransform — 2K soft upscale was the blur.
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(target, image)
        p.restore()

    def draw_armor_fov_circle(self, p: QPainter, width: int, height: int, module: Module | None) -> None:
        """Screen-center fluorescent white FOV ring; size from ClickGUI Circle Size.

        CPU-rasterized so the OpenGL paint engine cannot leave a white square
        atlas around the ring.
        """
        if module is None or not module.enabled:
            return
        if not self.setting_bool(module, "Draw Fov", True):
            return
        radius = max(8.0, self.get_setting_number(module, "Circle Size", 160.0))
        center = QPointF(width * 0.5, height * 0.5)
        # Stronger glow than thin canvas default so it reads as jar fluorescent white.
        self.draw_fluorescent_white_ellipse(
            p, center, radius, line_width=1.15, glow=0.90, alpha=1.0,
        )

    def draw_white_outline_lock(self, p: QPainter, rect: QRectF, target: VisionTarget, locked: bool) -> None:
        alpha = 0.94 if locked else 0.62
        accent = self.hud_accent() if locked else self.hud_danger()
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Full fluorescent white box outline (Debug Box ESP recipe).
        corners = [
            rect.topLeft() + QPointF(0.5, 0.5),
            rect.topRight() + QPointF(-0.5, 0.5),
            rect.bottomRight() + QPointF(-0.5, -0.5),
            rect.bottomLeft() + QPointF(0.5, -0.5),
        ]
        self.draw_fluorescent_white_polyline(
            p, corners, closed=True, line_width=1.0, glow=0.85, alpha=alpha,
        )
        corner = min(22.0, rect.width() * 0.22)
        corner_segs: list[tuple[QPointF, QPointF]] = []
        for start, dx, dy in (
            (rect.topLeft(), corner, 0),
            (rect.topLeft(), 0, corner),
            (rect.topRight(), -corner, 0),
            (rect.topRight(), 0, corner),
            (rect.bottomLeft(), corner, 0),
            (rect.bottomLeft(), 0, -corner),
            (rect.bottomRight(), -corner, 0),
            (rect.bottomRight(), 0, -corner),
        ):
            corner_segs.append((start, start + QPointF(dx, dy)))
        self.draw_fluorescent_white_segments(
            p, corner_segs, line_width=1.15, glow=0.85, alpha=alpha,
        )
        check_origin = QPointF(rect.right() - 18, rect.top() + 12)
        p.setPen(QPen(accent, 1.8))
        p.drawLine(check_origin + QPointF(-7, 0), check_origin + QPointF(-2, 5))
        p.drawLine(check_origin + QPointF(-2, 5), check_origin + QPointF(8, -7))
        self.draw_pill(
            p,
            QPointF(rect.left(), rect.top() - 27),
            self.target_overlay_label(target),
            color("#ffffff", alpha),
        )
        p.restore()

    def draw_minimal_bracket_lock(self, p: QPainter, rect: QRectF, target: VisionTarget, locked: bool) -> None:
        main = color("#ffffff", 0.88) if locked else with_alpha(self.hud_danger(), 0.88)
        corner = min(30.0, rect.width() * 0.24)
        inset = 2.0
        p.save()
        p.setPen(QPen(main, 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        tl = rect.topLeft() + QPointF(inset, inset)
        tr = rect.topRight() + QPointF(-inset, inset)
        bl = rect.bottomLeft() + QPointF(inset, -inset)
        br = rect.bottomRight() + QPointF(-inset, -inset)
        for point, hx, vy in ((tl, corner, corner), (tr, -corner, corner), (bl, corner, -corner), (br, -corner, -corner)):
            p.drawLine(point, point + QPointF(hx, 0))
            p.drawLine(point, point + QPointF(0, vy))
        self.draw_pill(p, QPointF(rect.left(), rect.top() - 27), self.target_overlay_label(target), main)
        p.restore()

    def draw_rune_ring_lock(self, p: QPainter, rect: QRectF, target: VisionTarget, module: Module | None, locked: bool) -> None:
        main = self.hud_accent() if locked else color("#ffffff", 0.58)
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2.0
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(with_alpha(main, 0.82), 1.4))
        p.drawEllipse(center, radius, radius)
        p.setPen(QPen(with_alpha(main, 0.95), 2.3))
        sweep = 16.0
        for angle in (0, 90, 180, 270):
            rad = math.radians(angle)
            outer = QPointF(center.x() + math.cos(rad) * (radius + 7), center.y() + math.sin(rad) * (radius + 7))
            inner = QPointF(center.x() + math.cos(rad) * (radius - sweep), center.y() + math.sin(rad) * (radius - sweep))
            p.drawLine(inner, outer)
        p.setPen(QPen(self.hud_warning() if self.state.energy_rune_rotation == "CCW" else self.hud_accent(), 2.4))
        progress = self.state.energy_rune_progress / 100.0 if target.kind == "energy" else target.confidence
        marker_angle = progress * math.tau - math.pi / 2.0
        marker = QPointF(center.x() + math.cos(marker_angle) * radius, center.y() + math.sin(marker_angle) * radius)
        p.drawEllipse(marker, 4.0, 4.0)
        show_progress = self.setting_bool(module, "Show Progress", True)
        if show_progress and target.kind == "energy":
            bar = QRectF(rect.left(), rect.bottom() + 8, rect.width(), 5)
            draw_bar(p, bar, progress, self.hud_accent(), color("#ffffff", 0.18), 2.5)
        self.draw_pill(p, QPointF(rect.left(), rect.top() - 27), self.target_overlay_label(target), main)
        p.restore()

    def target_overlay_label(self, target: VisionTarget) -> str:
        if target.kind == "energy":
            return f"{target.label}  {target.confidence:.0%}  {self.state.energy_target_distance_m:.1f}m  {self.state.energy_rune_progress}%"
        return f"{target.label}  {target.confidence:.0%}  {self.state.target_distance_m:.1f}m"

    def armor_esp_points(self, points: tuple[tuple[float, float], ...], result: VisionResult, width: int, height: int) -> list[QPointF]:
        camera_module = self.registry.get("CameraFeed")
        mirror = self.setting_bool(camera_module, "Mirror", False)
        x_scale = width / max(1.0, float(result.source_width))
        y_scale = height / max(1.0, float(result.source_height))
        return [QPointF(width - x * x_scale if mirror else x * x_scale, y * y_scale) for x, y in points]

    def armor_esp_back_points(self, armor, result: VisionResult, width: int, height: int, depth: float) -> list[QPointF]:
        if len(armor.back_points) == 4:
            return self.armor_esp_points(armor.back_points, result, width, height)
        front = self.armor_esp_points(armor.points, result, width, height)
        if len(front) != 4:
            return []
        center = QPolygonF(front).boundingRect().center()
        thickness = max(5.0, min(32.0, QPolygonF(front).boundingRect().width() * depth))
        angle = armor.yaw_rad
        offset = QPointF(-math.sin(angle) * thickness, math.cos(angle) * thickness * 0.34)
        return [center + (point - center) * 0.90 + offset for point in front]

    def draw_3d_esp_box(self, p: QPainter, front: list[QPointF], back: list[QPointF], c: QColor, line_width: float, *, glass: bool, ghost: bool, label: str | None = None) -> None:
        if len(front) != 4 or len(back) != 4:
            return
        front_poly = QPolygonF(front)
        # jar base width 1.0; module Line Width defaults to 2.0 → map to ~1.0.
        base_w = max(0.75, float(line_width) * 0.5)
        alpha = max(0.15, min(1.0, c.alphaF() if isinstance(c, QColor) else 1.0))
        if ghost:
            alpha *= 0.72
        # Full 12-edge outlined box — fluorescent white only (no fill default).
        edges: list[tuple[QPointF, QPointF]] = []
        for i in range(4):
            edges.append((front[i], front[(i + 1) % 4]))
            edges.append((back[i], back[(i + 1) % 4]))
            edges.append((front[i], back[i]))
        self.draw_fluorescent_white_segments(
            p, edges, line_width=base_w, glow=0.85, alpha=alpha, dashed=ghost,
        )
        if label:
            box = front_poly.boundingRect()
            white = color("#ffffff", alpha)
            if ghost:
                self.draw_text(p, QRectF(box.left(), box.top() - 16, 44, 13), label, self.font("poppins_medium", 7.0), white)
            else:
                self.draw_pill(p, QPointF(box.left(), box.top() - 22), label, white)

    @staticmethod
    def constrain_prediction_geometry(
        front: list[QPointF],
        back: list[QPointF],
        reference: list[QPointF],
    ) -> tuple[list[QPointF], list[QPointF]]:
        """限制未标定 PnP 偶发的超大投影，但不改预测板中心位置。"""
        if len(front) != 4 or len(reference) != 4:
            return front, back
        box = QPolygonF(front).boundingRect()
        reference_box = QPolygonF(reference).boundingRect()
        if box.width() <= 0.01 or box.height() <= 0.01 or reference_box.isEmpty():
            return front, back
        max_w = max(18.0, reference_box.width() * 1.35)
        max_h = max(10.0, reference_box.height() * 1.45)
        scale = min(1.0, max_w / box.width(), max_h / box.height())
        if scale >= 0.999:
            return front, back
        center = box.center()

        def scaled(points: list[QPointF]) -> list[QPointF]:
            return [center + (point - center) * scale for point in points]

        return scaled(front), scaled(back) if len(back) == 4 else back

    def draw_clean_3d_esp_box(
        self,
        p: QPainter,
        front: list[QPointF],
        back: list[QPointF],
        c: QColor,
        line_width: float,
        *,
        glass: bool,
        ghost: bool,
        label: str | None = None,
    ) -> None:
        """Outlined 3D armor box — fluorescent white wire only (no solid faces)."""
        if len(front) != 4 or len(back) != 4:
            return
        front_poly = QPolygonF(front)
        base_w = max(0.75, float(line_width) * 0.5)
        alpha = max(0.15, min(1.0, c.alphaF() if isinstance(c, QColor) else 1.0))
        if ghost:
            alpha *= 0.72
        edges: list[tuple[QPointF, QPointF]] = []
        for i in range(4):
            edges.append((front[i], front[(i + 1) % 4]))
            edges.append((back[i], back[(i + 1) % 4]))
            edges.append((front[i], back[i]))
        self.draw_fluorescent_white_segments(
            p, edges, line_width=base_w, glow=0.85, alpha=alpha, dashed=ghost,
        )
        if label:
            box = front_poly.boundingRect()
            white = color("#ffffff", alpha)
            if ghost:
                self.draw_text(p, QRectF(box.left(), box.top() - 16, 44, 13), label, self.font("poppins_medium", 7.0), white)
            else:
                self.draw_pill(p, QPointF(box.left(), box.top() - 22), label, white)

    def draw_polar_mechanical_wire(
        self,
        p: QPainter,
        front: list[QPointF],
        back: list[QPointF],
        accent: QColor,
        line_width: float,
        *,
        predicted: bool,
        label: str | None = None,
    ) -> None:
        """Mechanical armor wireframe — Debug Box ESP fluorescent white 1:1.

        Pure #FFFFFF soft+core strokes only; no fill faces. Matches
        visual-demo/esp-box-white.html (glow=0.35, base width ~1.0).
        """
        if len(front) != 4:
            return

        def lerp(a: QPointF, b: QPointF, amount: float) -> QPointF:
            return QPointF(
                a.x() + (b.x() - a.x()) * amount,
                a.y() + (b.y() - a.y()) * amount,
            )

        front_poly = QPolygonF(front)
        alpha = 0.46 if predicted else 1.0
        # jar glLineWidth(1.0); module default Line Width 2.0 → base 1.0.
        base_w = max(0.75, float(line_width) * 0.5 * (0.85 if predicted else 1.0))
        glow = 0.85

        if len(back) == 4:
            back_edges = [(back[i], back[(i + 1) % 4]) for i in range(4)]
            depth_edges = [(front[i], back[i]) for i in range(4)]
            self.draw_fluorescent_white_segments(
                p, back_edges, line_width=base_w * 0.85, glow=glow, alpha=alpha * 0.55, dashed=True,
            )
            self.draw_fluorescent_white_segments(
                p, depth_edges, line_width=base_w * 0.9, glow=glow, alpha=alpha * 0.65, dashed=True,
            )

        self.draw_fluorescent_white_polyline(
            p, front, closed=True, line_width=base_w, glow=glow, alpha=alpha, dashed=predicted,
        )

        edge_lengths = [
            math.hypot(front[(index + 1) % 4].x() - front[index].x(), front[(index + 1) % 4].y() - front[index].y())
            for index in range(4)
        ]
        brace: list[tuple[QPointF, QPointF]] = []
        if edge_lengths[0] + edge_lengths[2] >= edge_lengths[1] + edge_lengths[3]:
            for amount in (0.24, 0.76):
                brace.append((lerp(front[0], front[1], amount), lerp(front[3], front[2], amount)))
        else:
            for amount in (0.24, 0.76):
                brace.append((lerp(front[1], front[2], amount), lerp(front[0], front[3], amount)))
        self.draw_fluorescent_white_segments(
            p, brace, line_width=max(0.65, base_w * 0.72), glow=glow, alpha=alpha * 0.68, dashed=predicted,
        )

        if label:
            box = front_poly.boundingRect()
            label_width = max(42.0, text_width(p, self.font("poppins_medium", 6.4), label) + 4.0)
            self.draw_text(
                p,
                QRectF(box.left(), box.top() - 15, label_width, 13),
                label,
                self.font("poppins_medium", 6.4),
                color("#ffffff", 0.72 if predicted else 0.96),
            )

    @staticmethod
    def _vision_wire_key(armor) -> tuple[int, int, bool]:
        target_id = armor.target_id if armor.target_id >= 0 else armor.armor_id
        plate_id = armor.plate_id if armor.plate_id >= 0 else armor.armor_id
        return target_id, plate_id, bool(armor.predicted)

    def _append_vision_wire_armor(
        self,
        batch: VisionWireBatch,
        front: list[QPointF],
        back: list[QPointF],
        *,
        width: float,
        alpha: float,
        predicted: bool,
        label: str | None = None,
        label_scale: float = 1.0,
    ) -> None:
        """Append fluorescent white linework without any filled geometry.

        Formula matches visual-demo/esp-box-white.html (glow=0.35, pure #FFFFFF).
        """
        if len(front) != 4:
            return
        alpha = max(0.0, min(1.0, float(alpha)))
        # jar lineWidth 1.0; module Line Width default 2.0 → base ~1.0.
        core_width = max(0.75, float(width) * 0.5 * (0.85 if predicted else 1.0))
        glow = 0.85
        if len(back) == 4:
            batch.fluorescent_polyline(
                back,
                width=max(0.6, core_width * 0.85),
                alpha=alpha * 0.55,
                closed=True,
                dashed=True,
                glow=glow,
            )
            for index in range(4):
                batch.fluorescent_line(
                    front[index],
                    back[index],
                    width=max(0.65, core_width * 0.9),
                    alpha=alpha * 0.65,
                    dashed=True,
                    glow=glow,
                )
        batch.fluorescent_polyline(
            front,
            width=core_width,
            alpha=alpha,
            closed=True,
            dashed=predicted,
            glow=glow,
        )

        def lerp(a: QPointF, b: QPointF, amount: float) -> QPointF:
            return QPointF(
                a.x() + (b.x() - a.x()) * amount,
                a.y() + (b.y() - a.y()) * amount,
            )

        lengths = [
            math.hypot(
                front[(index + 1) % 4].x() - front[index].x(),
                front[(index + 1) % 4].y() - front[index].y(),
            )
            for index in range(4)
        ]
        for amount in (0.24, 0.76):
            if lengths[0] + lengths[2] >= lengths[1] + lengths[3]:
                start, end = lerp(front[0], front[1], amount), lerp(front[3], front[2], amount)
            else:
                start, end = lerp(front[1], front[2], amount), lerp(front[0], front[3], amount)
            batch.fluorescent_line(
                start,
                end,
                width=max(0.6, core_width * 0.72),
                alpha=alpha * 0.68,
                dashed=predicted,
                glow=glow,
            )

        if label:
            box = QPolygonF(front).boundingRect()
            font = self.font("poppins_medium", 6.4 * max(1.0, label_scale))
            label_width = max(52.0 * label_scale, len(label) * 6.6 * label_scale)
            batch.labels.text(
                QRectF(
                    box.left(),
                    box.top() - 16.0 * label_scale,
                    label_width,
                    13.0 * label_scale,
                ),
                label,
                font,
                QColor(255, 255, 255, round(245 * alpha)),
            )

    def build_vision_wire_batch(
        self,
        width: int,
        height: int,
        result: VisionResult,
        module: Module,
    ) -> VisionWireBatch:
        batch = VisionWireBatch()
        overlay = self.registry.get("RobotOverlay")
        line_width = self.get_setting_number(module, "Line Width", 2.0)
        opacity = self.get_setting_number(module, "Opacity", 0.82)
        scale = self.get_hud_scale(width, height)
        line_width *= scale
        depth = self.get_setting_number(overlay, "3D Depth", 0.22)
        max_targets = int(self.get_setting_number(overlay, "Max Targets", 6))
        calibrated = self.vision_result_calibrated(result)
        local_pnp = bool(self._vision_snapshot and self._vision_snapshot.source == "Local") and any(
            len(armor.back_points) == 4
            for armor in result.detections + result.predicted_armors
        )
        show_prediction = (
            self.setting_bool(module, "Show Prediction", True)
            and self.setting_bool(overlay, "Predict Plates", True)
            and (calibrated or local_pnp)
        )
        show_labels = self.setting_bool(module, "Show Labels", True)
        prediction_labels = self.setting_bool(module, "Prediction Labels", False)
        observed = [armor for armor in result.detections if len(armor.points) == 4]
        predicted = [armor for armor in result.predicted_armors if len(armor.points) == 4]
        aim = result.aim_armor if result.aim_armor and len(result.aim_armor.points) == 4 else None
        aim_front = self.armor_esp_points(aim.points, result, width, height) if aim is not None else []
        aim_box = QPolygonF(aim_front).boundingRect() if aim_front else QRectF()
        emitted: set[tuple[int, int, bool]] = set()

        def prediction_alpha(armor) -> float:
            armor_depth = armor.depth_m if armor.depth_m > 0 else armor.distance_m
            if armor_depth <= 0:
                return 0.58
            return max(0.24, min(0.62, 6.5 / max(1.0, armor_depth)))

        for armor in (observed + (predicted if show_prediction else []))[:max_targets]:
            key = self._vision_wire_key(armor)
            if key in emitted:
                continue
            front = self.armor_esp_points(armor.points, result, width, height)
            if len(front) != 4:
                continue
            if aim is not None and not armor.predicted:
                box = QPolygonF(front).boundingRect()
                if math.dist(
                    (box.center().x(), box.center().y()),
                    (aim_box.center().x(), aim_box.center().y()),
                ) < max(12.0 * scale, aim_box.width() * 0.45):
                    continue
            back = self.armor_esp_back_points(armor, result, width, height, depth)
            if armor.predicted and aim_front:
                front, back = self.constrain_prediction_geometry(front, back, aim_front)
            label = f"P{armor.plate_id}" if armor.predicted and prediction_labels else None
            self._append_vision_wire_armor(
                batch,
                front,
                back,
                width=line_width,
                alpha=prediction_alpha(armor) if armor.predicted else opacity,
                predicted=bool(armor.predicted),
                label=label,
                label_scale=scale,
            )
            emitted.add(key)

        if aim is not None:
            aim_key = self._vision_wire_key(aim)
            back = self.armor_esp_back_points(aim, result, width, height, depth)
            distance = aim.distance_m if aim.distance_m > 0 else aim.depth_m
            label = None
            if show_labels:
                label = f"DIST {distance:.1f}m" if distance > 0 else "DIST --"
            self._append_vision_wire_armor(
                batch,
                aim_front,
                back,
                width=line_width + 0.35 * scale,
                alpha=1.0,
                predicted=False,
                label=label,
                label_scale=scale,
            )
            emitted.add(aim_key)
        return batch

    def paint_gpu_vision_layer(
        self,
        functions,
        width: int,
        height: int,
        ratio: float,
    ) -> bool:
        """Clear and optionally populate the sole mechanical ESP layer."""
        module = self.registry.get("Armor3DESP")
        armor_module = self.registry.get("ArmorAutoAim")
        overlay = self.registry.get("RobotOverlay")
        native_owner = bool(
            not self.home_visible
            and module
            and module.enabled
            and armor_module
            and armor_module.enabled
            and self.setting_mode(module, "Style", "PolarMechanicalWire") == "PolarMechanicalWire"
            and self.setting_mode(overlay, "ESP Style", "3D Wire") != "Polar Outline"
            and self._vision_source != "Mock"
            and self.vision_wire_gpu.available
            and self.clickgui_gpu.available
        )
        result = self.interpolated_vision_result(time.perf_counter()) if native_owner else None
        batch = self.build_vision_wire_batch(width, height, result, module) if result is not None and module is not None else VisionWireBatch()
        if batch.labels.commands:
            self.clickgui_gpu.prepare_frame(batch.labels, ratio)
        if not self.gpu_compositor.begin_vision_layer(functions):
            return False
        try:
            if not native_owner or result is None:
                return native_owner
            if not self.vision_wire_gpu.render(functions, batch, width, height, ratio):
                return False
            if batch.labels.commands and not self.clickgui_gpu.render(
                functions,
                batch.labels,
                width,
                height,
                ratio,
                atlas_prepared=True,
            ):
                return False
            return True
        finally:
            self.gpu_compositor.end_vision_layer()

    def draw_armor_quad(self, p: QPainter, points: list[QPointF], c: QColor, line_width: float, *, dashed: bool = False, aim: bool = False) -> None:
        if len(points) != 4:
            return
        polygon = QPolygonF(points)
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color("#000000", 0.72), line_width + 2.0, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(polygon)
        p.setPen(QPen(c, line_width, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(polygon)
        if aim:
            center = polygon.boundingRect().center()
            p.setPen(QPen(c, max(1.0, line_width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(center + QPointF(-7, 0), center + QPointF(7, 0))
            p.drawLine(center + QPointF(0, -7), center + QPointF(0, 7))
        p.restore()

    def smooth_armor_geometry(self, armor, result: VisionResult):
        """只平滑连续结果的几何位置；没有结果时不保留任何绘制状态。"""
        if len(armor.points) != 4:
            return armor
        key = (armor.armor_id, armor.plate_id, armor.predicted, armor.label)
        if not result.detections and not result.predicted_armors:
            self._armor_geometry_smooth.clear()
            return armor

        previous = self._armor_geometry_smooth.get(key)
        if previous is None:
            self._armor_geometry_smooth[key] = (armor.points, armor.back_points)
            return armor

        # 约 55ms 的响应时间；识别结果落后相机帧时提高追赶速度，但不制造旧目标。
        alpha = 1.0 - math.exp(-max(0.001, min(0.12, self.frame_dt)) / 0.055)
        frame_lag = max(0, self._last_capture_sequence - result.sequence)
        alpha = max(alpha, min(0.72, frame_lag * 0.12))

        def blend_points(
            current: tuple[tuple[float, float], ...],
            old: tuple[tuple[float, float], ...],
        ) -> tuple[tuple[float, float], ...]:
            if len(current) != len(old):
                return current
            return tuple(
                (
                    before[0] + (after[0] - before[0]) * alpha,
                    before[1] + (after[1] - before[1]) * alpha,
                )
                for before, after in zip(old, current)
            )

        points = blend_points(armor.points, previous[0])
        back_points = blend_points(armor.back_points, previous[1]) if len(armor.back_points) == 4 and len(previous[1]) == 4 else armor.back_points
        self._armor_geometry_smooth[key] = (points, back_points)
        return replace(armor, points=points, back_points=back_points)

    def draw_armor_3d_esp(self, p: QPainter, width: int, height: int, result: VisionResult, module: Module) -> None:
        if not result.detections and not result.predicted_armors:
            self._armor_geometry_smooth.clear()
        overlay = self.registry.get("RobotOverlay")
        overlay_style = self.setting_mode(overlay, "ESP Style", "3D Wire")
        style = self.setting_mode(module, "Style", "PolarMechanicalWire")
        line_width = self.get_setting_number(module, "Line Width", 2.0)
        opacity = self.get_setting_number(module, "Opacity", 0.82)
        calibrated = self.vision_result_calibrated(result)
        local_pnp = bool(self._vision_snapshot and self._vision_snapshot.source == "Local") and any(len(armor.back_points) == 4 for armor in result.detections + result.predicted_armors)
        show_prediction = self.setting_bool(module, "Show Prediction", True) and self.setting_bool(overlay, "Predict Plates", True) and (calibrated or local_pnp)
        show_labels = self.setting_bool(module, "Show Labels", True)
        prediction_labels = self.setting_bool(module, "Prediction Labels", False)
        depth = self.get_setting_number(overlay, "3D Depth", 0.22)
        max_targets = int(self.get_setting_number(overlay, "Max Targets", 6))
        only_secondary = self.setting_bool(overlay, "Only Secondary", True)
        primary = color("#ffffff", opacity)
        aim_color = color("#ffffff")

        # VisionRenderInterpolator 已按视觉时间戳在显示帧间插值。这里必须直接使用
        # 插值结果，不能再做一次追赶平滑，否则低频推理会呈现明显拖滞和阶梯感。
        observed = [armor for armor in result.detections if len(armor.points) == 4]
        predicted = [armor for armor in result.predicted_armors if len(armor.points) == 4]
        aim = result.aim_armor if result.aim_armor and len(result.aim_armor.points) == 4 else None

        if style == "JelloShadow":
            # Sigma ShadowESP: LIGHT_GREYISH_BLUE (#fefefe), literal 2 px
            # outline and the original alt/shadow.png billboard.  The host
            # bridge exposes projected armor quads rather than a Minecraft
            # entity mesh, so each quad is the available silhouette source;
            # labels, prediction racks and POLAR mechanical decorations are
            # intentionally omitted.
            shadow = getattr(self, "_jello_esp_shadow", None)
            if shadow is None:
                shadow = QImage(
                    str(self._client_asset_path("assets", "jello", "hud_shadow.png"))
                ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                self._jello_esp_shadow = shadow
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            for armor in observed[:max_targets]:
                points = self.armor_esp_points(armor.points, result, width, height)
                if len(points) != 4:
                    continue
                polygon = QPolygonF(points)
                box = polygon.boundingRect()
                billboard_w = max(42.0, box.width() * 2.8)
                billboard_h = billboard_w * (411.0 / 330.0)
                billboard = QRectF(
                    box.center().x() - billboard_w * 0.5,
                    box.center().y() - billboard_h * 0.42,
                    billboard_w,
                    billboard_h,
                )
                if shadow is not None and not shadow.isNull():
                    p.save()
                    p.setOpacity(max(0.0, min(1.0, 0.80 * opacity)))
                    p.drawImage(billboard, shadow)
                    p.restore()
                pen = QPen(QColor(254, 254, 254, max(0, min(255, int(255 * opacity)))), line_width)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(polygon)
            p.restore()
            return

        def prediction_alpha(armor) -> float:
            """按桥接器回传的真实深度衰减预测线框；旧桥接器无深度时保持默认透明度。"""
            depth = armor.depth_m if armor.depth_m > 0 else armor.distance_m
            if depth <= 0:
                return 0.72
            return max(0.28, min(0.86, 7.5 / max(1.0, depth)))

        if overlay_style == "Polar Outline" or style == "PolarOutline2D":
            source = observed if observed or not calibrated else predicted
            for armor in source:
                points = self.armor_esp_points(armor.points, result, width, height)
                xs = [point.x() for point in points]
                ys = [point.y() for point in points]
                rect = QRectF(min(xs), min(ys), max(4.0, max(xs) - min(xs)), max(4.0, max(ys) - min(ys)))
                c = aim_color if armor.aim else primary
                self.draw_minimal_bracket_lock(p, rect, VisionTarget(rect.x(), rect.y(), rect.width(), rect.height(), armor.confidence, armor.label), armor.aim)
                if show_labels:
                    self.draw_pill(p, QPointF(rect.left(), rect.top() - 22), f"{armor.label.upper()} {armor.confidence:.0%}", c)
            return

        glass = overlay_style == "3D Glass"
        aim_front = self.armor_esp_points(aim.points, result, width, height) if aim is not None else []
        for armor in (observed + (predicted if show_prediction else []))[:max_targets]:
            front = self.armor_esp_points(armor.points, result, width, height)
            if len(front) != 4:
                continue
            box = QPolygonF(front).boundingRect()
            if aim is not None and not armor.predicted:
                aim_box = QPolygonF(self.armor_esp_points(aim.points, result, width, height)).boundingRect()
                if math.dist((box.center().x(), box.center().y()), (aim_box.center().x(), aim_box.center().y())) < max(12.0, aim_box.width() * 0.45):
                    # 主目标由下方的 Aim Face 单独绘制，不能再作为 RobotOverlay 重复画一次。
                    continue
            ghost = armor.predicted
            display_color = color("#ffffff", prediction_alpha(armor) * 0.72) if ghost else primary
            back = self.armor_esp_back_points(armor, result, width, height, depth)
            if ghost and aim_front:
                front, back = self.constrain_prediction_geometry(front, back, aim_front)
            if style == "PolarMechanicalWire":
                label = f"P{armor.plate_id}" if ghost and prediction_labels else None
                self.draw_polar_mechanical_wire(
                    p,
                    front,
                    back,
                    display_color,
                    line_width,
                    predicted=ghost,
                    label=label,
                )
            else:
                self.draw_clean_3d_esp_box(
                    p,
                    front,
                    back,
                    display_color,
                    line_width,
                    glass=glass,
                    ghost=ghost,
                    label=(f"P{armor.plate_id}" if ghost else f"{armor.label.upper()} {armor.distance_m:.1f}m") if show_labels else None,
                )
        if aim is not None:
            points = aim_front
            back = self.armor_esp_back_points(aim, result, width, height, depth)
            if style == "PolarMechanicalWire":
                self.draw_polar_mechanical_wire(
                    p,
                    points,
                    back,
                    aim_color,
                    line_width + 0.35,
                    predicted=False,
                )
            else:
                self.draw_clean_3d_esp_box(p, points, back, aim_color, line_width + 0.35, glass=glass, ghost=False, label=None)
            if show_labels:
                box = QPolygonF(points).boundingRect()
                distance = aim.distance_m if aim.distance_m > 0 else aim.depth_m
                label = f"DIST {distance:.1f}m" if distance > 0 else "DIST --"
                if style == "PolarMechanicalWire":
                    label_width = max(62.0, text_width(p, self.font("poppins_medium", 6.4), label) + 4.0)
                    self.draw_text(
                        p,
                        QRectF(box.left(), box.top() - 16, label_width, 13),
                        label,
                        self.font("poppins_medium", 6.4),
                        color("#ffffff", 0.96),
                    )
                else:
                    self.draw_pill(p, QPointF(box.left(), box.top() - 24), label, aim_color)
        if local_pnp and not calibrated:
            self._bottom_left_diagnostics.append(("DESKTOP PNP | APPROX FOV", self.hud_accent(), 1))
        elif not calibrated:
            self._bottom_left_diagnostics.append(("UNCALIBRATED | detection only", self.hud_warning(), 1))
        kill_status = getattr(self.state, "vision_kill_status", "IDLE")
        if kill_status not in ("IDLE", "NO_DETECTION"):
            status_color = self.hud_accent() if kill_status in (
                "LIT_TRACKED", "MODEL_CONFIRMED", "REFLECTION_IGNORED",
                "WAITING_FRESH_FRAMES", "VISION_CONFIRMED",
            ) else self.hud_warning()
            self._bottom_left_diagnostics.append((f"KILL VISION | {kill_status}", status_color, 2))



# ---------------------------------------------------------------------------
# T1（gd656 移植）：第 5 种 Lock Style "Heli Gimbal"（直升机吊舱瞄准镜风格）。
#
# 开源侧没有可直接移植的吊舱 reticle 实现（AUDIT_gd656_integration.md §1.4），
# 本样式为 QPainter 程序化新造：雷达扫掠扇形 + 外圈旋转双弧 + 边角向心括号
# （0.25s ease-out-cubic 入场）+ 中央十字 + 测距刻度 + 目标距离读数 + AIR LOCK pill，
# 配色全部走 hud_accent / hud_danger 体系。
#
# 刻意实现为**模块级函数**而非 Mixin 方法：不向 PolarRMWindow 增加 dir() 成员，
# api_freeze_test 冻结面（§5.6）保持 bit 级不变；host 即窗口实例，经参数传入。
# ---------------------------------------------------------------------------

_HELI_GIMBAL_ENTRY_S = 0.25


def _heli_gimbal_entry_progress(host, key: tuple[str, str], now: float) -> float:
    """目标首次出现起的入场进度（ease-out-cubic），复用 kill_fx 同款缓动手感。"""
    entries = getattr(host, "_heli_gimbal_entries", None)
    if entries is None:
        entries = {}
        setattr(host, "_heli_gimbal_entries", entries)
    started = entries.get(key)
    if started is None:
        entries[key] = now
        started = now
    if len(entries) > 24:
        for stale in [item for item, ts in entries.items() if now - ts > 6.0]:
            entries.pop(stale, None)
    t = min(1.0, (now - started) / _HELI_GIMBAL_ENTRY_S)
    return 1.0 - (1.0 - t) ** 3


def _heli_gimbal_lock_draw(host, p: QPainter, rect: QRectF, target: VisionTarget, module: Module | None, locked: bool) -> None:
    now = time.perf_counter()
    main = host.hud_accent() if locked else host.hud_danger()
    center = rect.center()
    radius = max(8.0, min(rect.width(), rect.height()) / 2.0)
    enter = _heli_gimbal_entry_progress(host, (target.kind, target.label), now)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # 雷达扫掠扇形：低 alpha 锥形渐变楔形绕中心连续旋转；
    # 转速由 confidence 驱动，energy 目标用符文进度做相位偏移。
    confidence = max(0.0, min(1.0, float(target.confidence)))
    sweep_deg = (now * (60.0 + 240.0 * confidence)) % 360.0
    if target.kind == "energy":
        sweep_deg = (sweep_deg + float(getattr(host.state, "energy_rune_progress", 0)) * 3.6) % 360.0
    sweep_radius = radius * 1.45
    scan = QConicalGradient(center, -sweep_deg)
    scan_head = QColor(main)
    scan_head.setAlphaF(0.30 if locked else 0.16)
    scan_tail = QColor(main)
    scan_tail.setAlphaF(0.0)
    scan.setColorAt(0.0, scan_head)
    scan.setColorAt(0.16, scan_tail)
    scan.setColorAt(1.0, scan_tail)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(scan)
    p.drawEllipse(center, sweep_radius, sweep_radius)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # 外圈双弧括号：持续旋转，锁定时减速（近似“停正”的吊舱锁定语言）。
    spin_deg = (now * (36.0 if locked else 140.0)) % 360.0
    arc_radius = radius * 1.22
    arc_rect = QRectF(center.x() - arc_radius, center.y() - arc_radius, arc_radius * 2.0, arc_radius * 2.0)
    p.setPen(QPen(with_alpha(main, 0.95 if locked else 0.62), 2.0))
    arc_start = int(-spin_deg) % 360 * 16
    for offset in (0, 180):
        p.drawArc(arc_rect, arc_start + offset * 16, 70 * 16)

    # 边角括号：入场时自外向心收缩（enter 0→1）。
    corner = min(26.0, rect.width() * 0.24)
    slide = (1.0 - enter) * radius * 0.55
    p.setPen(QPen(main, 2.6))
    for point, hx, vy in (
        (rect.topLeft(), corner, corner),
        (rect.topRight(), -corner, corner),
        (rect.bottomLeft(), corner, -corner),
        (rect.bottomRight(), -corner, -corner),
    ):
        origin = point + QPointF(math.copysign(slide, hx), math.copysign(slide, vy))
        p.drawLine(origin, origin + QPointF(hx, 0))
        p.drawLine(origin, origin + QPointF(0, vy))

    # 中央十字（带中心间隙与驻留点）。
    gap = max(4.0, radius * 0.16)
    arm = max(10.0, radius * 0.55)
    p.setPen(QPen(with_alpha(main, 0.96), 1.7))
    p.drawLine(center + QPointF(gap, 0), center + QPointF(gap + arm, 0))
    p.drawLine(center - QPointF(gap, 0), center - QPointF(gap + arm, 0))
    p.drawLine(center + QPointF(0, gap), center + QPointF(0, gap + arm))
    p.drawLine(center - QPointF(0, gap), center - QPointF(0, gap + arm))
    p.setPen(QPen(main, 1.4))
    p.drawEllipse(center, 1.8, 1.8)

    # 测距刻度：右下侧 mil 分划（长短交替）。
    tick_x = center.x() + radius * 0.78
    p.setPen(QPen(with_alpha(main, 0.72), 1.2))
    for index in range(5):
        y = center.y() + gap + 10.0 + index * 8.0
        half = 6.0 if index % 2 == 0 else 3.5
        p.drawLine(QPointF(tick_x - half, y), QPointF(tick_x + half, y))

    # 目标距离读数（框下居中）。
    distance = float(
        host.state.energy_target_distance_m if target.kind == "energy" else host.state.target_distance_m
    )
    host.draw_text(
        p,
        QRectF(rect.center().x() - 70.0, rect.bottom() + 6.0, 140.0, 14.0),
        f"DIST {distance:.1f}M",
        host.font("poppins_medium", 7.0),
        color("#ffffff", 0.92 if locked else 0.66),
    )

    # 顶部 AIR LOCK 小 pill（沿用现有 pill 标签槽位）。
    host.draw_pill(
        p,
        QPointF(rect.left(), rect.top() - 27),
        f"AIR LOCK · {target.label.upper()} {target.confidence:.0%}",
        main,
    )
    p.restore()


# ---------------------------------------------------------------------------
# API 冻结面 qualname 固定（见模块 docstring「冻结面纪律」；先例：
# ui/polar/text_metrics.py 底部与 renderers/combat_target_hud.py 底部同一手法）。
# ---------------------------------------------------------------------------

_QUALNAME_PINNED_MEMBERS = (
    EspWireframeMixin.autoaim_logical_size,
    EspWireframeMixin.autoaim_circle_radius,
    EspWireframeMixin.sync_local_autoaim_fov,
    EspWireframeMixin.armor_center_in_autoaim_fov,
    EspWireframeMixin.vision_target_in_autoaim_fov,
    EspWireframeMixin.apply_autoaim_fov_lock,
    EspWireframeMixin.vision_result_for_display,
    EspWireframeMixin.interpolated_vision_result,
    EspWireframeMixin.vision_result_calibrated,
    EspWireframeMixin.draw_target_overlay,
    EspWireframeMixin.draw_fluorescent_white_segments,
    EspWireframeMixin.draw_fluorescent_white_polyline,
    EspWireframeMixin.rasterize_fluorescent_white_circle,
    EspWireframeMixin.draw_fluorescent_white_ellipse,
    EspWireframeMixin.draw_armor_fov_circle,
    EspWireframeMixin.draw_white_outline_lock,
    EspWireframeMixin.draw_minimal_bracket_lock,
    EspWireframeMixin.draw_rune_ring_lock,
    EspWireframeMixin.target_overlay_label,
    EspWireframeMixin.armor_esp_points,
    EspWireframeMixin.armor_esp_back_points,
    EspWireframeMixin.draw_3d_esp_box,
    EspWireframeMixin.constrain_prediction_geometry,
    EspWireframeMixin.draw_clean_3d_esp_box,
    EspWireframeMixin.draw_polar_mechanical_wire,
    EspWireframeMixin._vision_wire_key,
    EspWireframeMixin._append_vision_wire_armor,
    EspWireframeMixin.build_vision_wire_batch,
    EspWireframeMixin.paint_gpu_vision_layer,
    EspWireframeMixin.draw_armor_quad,
    EspWireframeMixin.smooth_armor_geometry,
    EspWireframeMixin.draw_armor_3d_esp,
)

for _fn in _QUALNAME_PINNED_MEMBERS:
    _fn.__qualname__ = f"PolarRMWindow.{_fn.__name__}"
del _fn, _QUALNAME_PINNED_MEMBERS
