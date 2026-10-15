"""阶段 2e 渲染器提取：动态岛族（D11）→ DynamicIslandMixin。

（REFACTOR_BLUEPRINT §5 阶段 2 表 2e 行 / §5.6 冻结面 / §6 性能红线）

迁移范围（grep 重定位后的实际锚点）：
- ``dynamic_island_bottom_anchor``：基地推进条跟随的岛下缘几何；
- ``dynamic_island_payload``：toast / 战斗事件 / 会话信息三态载荷合成；
- ``dynamic_message_kind`` / ``dynamic_message_title``：消息分类与标题；
- ``draw_dynamic_island``：岛体绘制（玻璃 + 图标 + 文案 + 进度条）；
- ``draw_dynamic_island_icon``：图标绘制（GPU 收集优先，CPU 圆形回退）。

纪律与偏差决策：
- 方法体零修改纯移动；``_draw_dynamic_island_legacy`` 为死代码（无调用点，
  阶段 0 审计确认），本次直接删除而非迁移；
- ``dynamic_smooth`` 是跨域通用收敛工具（__init__ 与其他域使用），留在原文件；
- ``begin_gpu_*`` / ``flush_gpu_*`` 家族属 D2 GPU 帧编排域，不迁；
- 状态字段（dynamic_island_state / dynamic_smooth_values /
  dynamic_island_last_event / dynamic_island_event_started）保持
  ``PolarRMWindow.__init__`` 原位初始化，Mixin 只承载方法。

冻结面纪律：api_freeze_test 对方法类成员比对 ``__qualname__``（基线值形如
"PolarRMWindow.<name>"），故在本模块底部把全部迁入方法的 ``__qualname__`` 钉回。
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen

from ...animation import Easings
from ...paint import rounded_rect, with_alpha
from ...theme import THEME, color
from ...island_icon_gpu import IslandIconCommand
from ...jello_locale import chinese_enabled
from ...status_locale import status_event_text, status_text

__all__ = ["DynamicIslandMixin"]


class DynamicIslandMixin:

    def dynamic_island_bottom_anchor(self, width: int, height: int) -> float | None:
        """灵动岛下边缘（物理像素），供基地推进条跟随。

        岛的几何是逐帧动画状态，条读到的是当前形变位置；岛关闭或
        尚未有几何时返回 None，条回落到固定槽位。
        """
        hud = self.registry.get("HUD")
        if not self.setting_bool(hud, "Dynamic Island", True):
            return None
        island = self.dynamic_island_state
        if getattr(island, "height", 0.0) <= 0.0:
            return None
        # 岛在 HUD 逻辑坐标系里绘制，换算回物理像素
        hud_scale = self.get_hud_scale(width, height)
        return (float(island.y) + float(island.height)) * hud_scale

    def dynamic_island_payload(self) -> dict[str, Any]:
        now = time.perf_counter()
        chinese = chinese_enabled(self.registry)
        if self.state.last_event != self.dynamic_island_last_event:
            self.dynamic_island_last_event = self.state.last_event
            self.dynamic_island_event_started = now

        recent_toast = None
        for toast in reversed(self.toasts):
            age = now - float(toast["created"])
            if age < 3.0:
                recent_toast = toast
                break

        if recent_toast is not None:
            age = now - float(recent_toast["created"])
            message = str(recent_toast["message"])
            kind, main = self.dynamic_message_kind(message)
            return {
                "active": True,
                "kind": kind,
                "color": main,
                "title": self.dynamic_message_title(message, kind),
                "description": status_event_text(message, chinese),
                "progress": max(0.0, 1.0 - age / 3.0),
            }

        event_age = now - self.dynamic_island_event_started
        if self.state.last_event and event_age < 2.7:
            kind, main = self.dynamic_message_kind(self.state.last_event)
            duration = max(1.0, float(getattr(self.state, "match_duration_sec", 300)))
            return {
                "active": True,
                "kind": kind,
                "color": main,
                "title": status_text(self.match_mode_manager.current.title, chinese),
                "description": status_event_text(self.state.last_event, chinese),
                "progress": max(0.0, min(1.0, self.state.stage_countdown_sec / duration)),
            }

        from ....student_ui import rune_summary
        rune = self.registry.get("RuneRingStatus")
        summary = rune_summary(self.state)
        if rune and rune.enabled and self.setting_bool(rune, "Show in Island", True) and summary:
            return {"active": True, "kind": "info", "color": self.hud_accent(),
                    "title": "能量机关", "description": summary, "progress": 1.0}
        mqtt = status_text("MQTT live" if self.state.mqtt_connected else "MQTT mock", chinese)
        serial = status_text("SERIAL live" if self.state.serial_connected else "SERIAL mock", chinese)
        match = status_text(self.match_mode_manager.current.title, chinese)
        text = f"{self.scenario_manager.current.title} | {match} | {self.state.fps:.0f} FPS | {mqtt} | {serial}"
        return {"active": False, "kind": "info", "color": self.hud_accent(), "title": "POLAR-RM", "description": text, "progress": 1.0}

    def dynamic_message_kind(self, message: str) -> tuple[str, QColor]:
        lower = message.lower()
        if any(token in lower for token in ("fail", "error", "disabled", "closed")) or any(token in message for token in ("失败", "关闭", "错误")):
            return "warning", self.hud_danger()
        if any(token in lower for token in ("enabled", "ready", "saved", "loaded", "success")) or any(token in message for token in ("启用", "就绪", "保存", "加载", "打开")):
            return "success", self.hud_success()
        if "gui" in lower or "模式" in message or "Scenario" in message or "Match" in message:
            return "module", self.hud_accent()
        return "info", self.hud_accent()

    def dynamic_message_title(self, message: str, kind: str) -> str:
        chinese = chinese_enabled(self.registry)
        if kind == "warning":
            return status_text("Warning", chinese)
        if kind == "success":
            return status_text("Success", chinese)
        if kind == "module":
            return status_text("Client State", chinese)
        if "Radar" in message or "雷达" in message:
            return status_text("Radar", chinese)
        return "POLAR-RM"

    def draw_dynamic_island(self, p: QPainter, width: int) -> None:
        payload = self.dynamic_island_payload()
        title_font = self.font("poppins_bold", 9.4)
        desc_font = self.font("poppins_regular", 8.2)
        title_w = self.text_advance(title_font, payload["title"])
        desc_w = self.text_advance(desc_font, payload["description"])
        content_active = bool(payload["active"])
        collapsed_w = max(300.0, min(580.0, title_w + desc_w + 92.0))
        expanded_w = max(210.0, min(580.0, max(title_w, desc_w) + 66.0))
        target_w = expanded_w if content_active else collapsed_w
        target_h = 46.0 if content_active else 30.0
        self.dynamic_island_state.set_target_geometry(
            (width - target_w) / 2.0,
            17.0,
            target_w,
            target_h,
            target_h / 2.0,
            opening=content_active,
        )
        state = self.dynamic_island_state
        content = state.content.progress
        rect = QRectF(state.x, state.y, state.width, state.height)
        radius = state.height / 2.0

        p.save()
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, radius, surface="LensIsland")
        else:
            rounded_rect(p, rect, radius, self.hud_surface(0.62), self.hud_panel_outline(0.08))
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)

        icon_size = 21.0 + 3.0 * content
        icon_rect = QRectF(rect.left() + 7.0, rect.top() + (rect.height() - icon_size) / 2.0, icon_size, icon_size)
        self.draw_dynamic_island_icon(
            p,
            icon_rect,
            str(payload["kind"]),
            payload["color"],
            max(0.18, 0.72 + 0.28 * content),
        )

        if content < 0.999:
            p.save()
            p.setOpacity(p.opacity() * (1.0 - content))
            p.setPen(QPen(with_alpha(self.hud_accent(), 0.90), 1.4))
            p.drawLine(QPointF(rect.left() + 38.0, rect.top() + 8.0), QPointF(rect.left() + 38.0, rect.bottom() - 8.0))
            self.draw_glass_text(p, QRectF(rect.left() + 46.0, rect.top(), 88.0, rect.height()), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 126.0, rect.top(), rect.width() - 134.0, rect.height()), payload["description"], desc_font, THEME.muted)
            p.restore()

        if content > 0.001:
            p.save()
            p.setOpacity(p.opacity() * content)
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 7.0, rect.width() - 50.0, 16.0), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 22.0, rect.width() - 50.0, 15.0), payload["description"], desc_font, THEME.muted)
            progress = max(0.0, min(1.0, float(payload["progress"])))
            bar_bg = QRectF(rect.left() + 8.0, rect.bottom() - 7.0, rect.width() - 16.0, 3.0)
            rounded_rect(p, bar_bg, 1.5, color("#ffffff", 0.12))
            filled = QRectF(bar_bg)
            filled.setWidth(max(4.0, bar_bg.width() * progress))
            rounded_rect(p, filled, 1.5, with_alpha(payload["color"], 0.95))
            p.restore()
        p.restore()

    def draw_dynamic_island_icon(self, p: QPainter, rect: QRectF, kind: str, main: QColor, amount: float) -> None:
        amount = max(0.0, min(1.0, amount))
        if self._collect_gpu_island_icons and self.island_icon_gpu.available:
            mapped_rect = p.transform().mapRect(rect)
            self._gpu_island_icon_commands.append(
                IslandIconCommand(QRectF(mapped_rect), kind, QColor(main), amount)
            )
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        icon_path = QPainterPath()
        icon_path.addEllipse(rect)
        p.setClipPath(icon_path, Qt.ClipOperation.IntersectClip)
        p.setPen(QPen(color("#ffffff", 0.10), 0.8))
        p.setBrush(with_alpha(main, 0.64))
        p.drawEllipse(rect)
        inner = rect.adjusted(2.0, 2.0, -2.0, -2.0)
        if kind == "module":
            rounded_rect(p, inner.adjusted(0.0, inner.height() * 0.25, 0.0, -inner.height() * 0.25), inner.height() * 0.25, color("#1e2028", 0.88))
            knob = inner.height() * 0.42
            kx = inner.left() + 2.0 + (inner.width() - knob - 4.0) * amount
            rounded_rect(p, QRectF(kx, inner.center().y() - knob / 2.0, knob, knob), knob / 2.0, color("#050507", 0.94))
            p.restore()
            return
        if kind == "success":
            clip = QRectF(rect.left(), rect.top(), rect.width() * amount, rect.height())
            p.save()
            p.setClipRect(clip)
            p.setPen(QPen(color("#ffffff", 0.92), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(rect.left() + rect.width() * 0.28, rect.center().y()), QPointF(rect.left() + rect.width() * 0.43, rect.bottom() - rect.height() * 0.30))
            p.drawLine(QPointF(rect.left() + rect.width() * 0.43, rect.bottom() - rect.height() * 0.30), QPointF(rect.right() - rect.width() * 0.22, rect.top() + rect.height() * 0.30))
            p.restore()
            p.restore()
            return
        if kind == "warning":
            clip = QRectF(rect.left(), rect.bottom() - rect.height() * amount, rect.width(), rect.height() * amount)
            p.save()
            p.setClipRect(clip)
            p.setPen(QPen(color("#ffffff", 0.92), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(rect.center().x(), rect.top() + 5.0), QPointF(rect.center().x(), rect.bottom() - 8.0))
            p.drawPoint(QPointF(rect.center().x(), rect.bottom() - 4.6))
            p.restore()
            p.restore()
            return
        p.setPen(QPen(color("#ffffff", 0.92), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        v = inner.height() * 0.72 * amount
        h = inner.width() * 0.72 * amount
        p.drawLine(QPointF(inner.center().x(), inner.center().y() - v / 2.0), QPointF(inner.center().x(), inner.center().y() + v / 2.0))
        p.drawLine(QPointF(inner.center().x() - h / 2.0, inner.center().y()), QPointF(inner.center().x() + h / 2.0, inner.center().y()))
        p.restore()


    # _draw_dynamic_island_legacy：死代码（无调用点），但属于 API 冻结面成员，
    # 按冻结面纪律保留在 Mixin 内（阶段 2e 迁移时从 HEAD 原样恢复）。
    def _draw_dynamic_island_legacy(self, p: QPainter, width: int) -> None:
        payload = self.dynamic_island_payload()
        title_font = self.font("poppins_bold", 9.4)
        desc_font = self.font("poppins_regular", 8.2)
        p.setFont(title_font)
        title_w = self.text_advance(title_font, payload["title"])
        p.setFont(desc_font)
        desc_w = self.text_advance(desc_font, payload["description"])
        content_active = bool(payload["active"])
        collapsed_w = max(300.0, min(580.0, title_w + desc_w + 92.0))
        expanded_w = max(210.0, min(580.0, max(title_w, desc_w) + 66.0))
        now = time.perf_counter()
        self.dynamic_island_morph.set_target(
            1.0 if content_active else 0.0,
            self.anim_duration(0.42),
            now=now,
        )
        morph = self.dynamic_island_morph.update(now=now)
        island_w = collapsed_w + (expanded_w - collapsed_w) * morph
        island_h = 30.0 + 16.0 * morph
        island_x = (width - island_w) / 2.0
        rect = QRectF(island_x, 17.0, island_w, island_h)
        # 灵动岛必须始终是完整胶囊。旧上限 14.5 会把 46px 的展开态
        # 截成圆角矩形，这正是运行界面里“岛变方”的根因。
        radius = rect.height() / 2.0
        active = self.anim.value("hud.dynamic_island.visible", 1.0, self.anim_duration(0.16), Easings.ease_out_expo, initial=0.0)
        icon_v = self.anim.value(
            "hud.dynamic_island.icon",
            1.0 if content_active else 0.0,
            self.anim_duration(0.17 if content_active else 0.13),
            Easings.ease_out_expo,
        )

        p.save()
        p.setOpacity(active)
        if self.hud_clean():
            self.draw_hud_liquid_glass(p, rect, radius, surface="ProminentGlass")
            # DynamicIslandSystem 的主体本来就是稳定的半透明黑色胶囊；
            # 液态玻璃负责背景折射，暗芯负责让内容在明亮图传上仍清晰。
        else:
            for pad, alpha in ((18.0, 0.045), (10.0, 0.070)):
                rounded_rect(p, rect.adjusted(-pad, -pad, pad, pad), radius + pad, color("#000000", alpha), None)
            rounded_rect(p, rect, radius, self.hud_surface(0.62), self.hud_panel_outline(0.08))
        p.setClipRect(rect.adjusted(0.6, 0.6, -0.6, -0.6))

        icon_size = 24.0 if content_active else 21.0
        icon_rect = QRectF(rect.left() + 7.0, rect.top() + (rect.height() - icon_size) / 2.0, icon_size, icon_size)
        self.draw_dynamic_island_icon(p, icon_rect, str(payload["kind"]), payload["color"], max(0.18, icon_v if content_active else 0.72))

        if content_active:
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 7.0, rect.width() - 50.0, 16.0), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 39.0, rect.top() + 22.0, rect.width() - 50.0, 15.0), payload["description"], desc_font, THEME.muted)
            progress = self.anim.value(
                "hud.dynamic_island.progress",
                max(0.0, min(1.0, float(payload["progress"]))),
                self.anim_duration(0.12),
                Easings.ease_out_expo,
                initial=max(0.0, min(1.0, float(payload["progress"]))),
            )
            bar_bg = QRectF(rect.left() + 8.0, rect.bottom() - 7.0, rect.width() - 16.0, 3.0)
            rounded_rect(p, bar_bg, 1.5, color("#ffffff", 0.12))
            filled = QRectF(bar_bg)
            filled.setWidth(max(4.0, bar_bg.width() * progress))
            rounded_rect(p, filled, 1.5, with_alpha(payload["color"], 0.95))
        else:
            logo_grad = QLinearGradient(icon_rect.left(), icon_rect.top(), icon_rect.right(), icon_rect.bottom())
            logo_grad.setColorAt(0.0, with_alpha(self.hud_accent(), 0.70))
            logo_grad.setColorAt(1.0, with_alpha(self.hud_accent(), 0.95))
            p.setPen(QPen(QBrush(logo_grad), 1.4))
            p.drawLine(QPointF(rect.left() + 38.0, rect.top() + 8.0), QPointF(rect.left() + 38.0, rect.bottom() - 8.0))
            self.draw_glass_text(p, QRectF(rect.left() + 46.0, rect.top(), 88.0, rect.height()), payload["title"], title_font, THEME.text)
            self.draw_glass_text(p, QRectF(rect.left() + 126.0, rect.top(), rect.width() - 134.0, rect.height()), payload["description"], desc_font, THEME.muted)
        p.restore()


# 冻结面纪律：迁入方法的 __qualname__ 钉回 PolarRMWindow.<name>。
for _name in (
    'dynamic_island_bottom_anchor',
    'dynamic_island_payload',
    'dynamic_message_kind',
    'dynamic_message_title',
    'draw_dynamic_island',
    'draw_dynamic_island_icon',
    '_draw_dynamic_island_legacy',
):
    getattr(DynamicIslandMixin, _name).__qualname__ = f"PolarRMWindow.{_name}"


