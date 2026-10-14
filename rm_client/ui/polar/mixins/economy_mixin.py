"""阶段 3d 大域 mixin 化：经济工作区（D6）→ EconomyMixin。

（REFACTOR_BLUEPRINT §5 阶段 3 表 3d 行 / §2 D6 节 / §5.6 冻结面）

迁移范围（以 grep 重定位后的实际行号为准，蓝图原行号已漂移；七段不连续区块）：
- legacy 绘制：``draw_economy_overlay_legacy``
- 数据/传输：``economy_scale_steps``（staticmethod）/ ``economy_ui_scale`` /
  ``economy_uses_mock_transport`` / ``send_economy_request`` / ``economy_offers`` /
  ``economy_categories`` / ``economy_selected_offer``
- FBO restore 协议提交端：``_finalize_economy_restore``
- 开合状态机：``open_economy_workspace`` / ``close_economy_workspace``
- 交互/状态机：``select_economy_offer`` / ``submit_economy_offer`` /
  ``activate_economy_offer`` / ``begin_economy_hold`` / ``finish_economy_hold``
- 玻璃助手：``_economy_glass_row`` / ``_economy_dim_around`` /
  ``_economy_island_well``
- 绘制总入口：``draw_economy_overlay_compat``（阶段 3c 报告明确属 D6、
  留待本阶段迁入——本次确认迁入）
- GPU 构建：``build_gpu_economy_workspace``（含方法内嵌套的
  ``add_control_center_tile`` 装配闭包，随方法体整体随行搬运）
- 资格赛：``start_economy_qualification_test``

纪律与特别注意（蓝图 3d 行，保守边界中文注明）：
- 方法体**零修改**（含注释、空行与嵌套函数），纯移动进本 Mixin；
- **D2↔D6 FBO restore generation 协议处理**：协议分两端——提交端
  ``_finalize_economy_restore``（D6 冻结面成员，smoke_test 直调）随 D6 整体
  迁入本 Mixin；失效辅助 ``invalidate_transient_overlay_scene`` 被 D1（on_tick）、
  D2（_paint_gpu_frame_cached / paint_direct_gpu_background）、D5、D7、D16
  **多域共用** → 按保守边界决策留在 polar_app.py 原位（参考阶段 2b 对同一
  方法的处理），两端经 ``self.`` 相互调用的调用面不变；
  ``_economy_generation`` / ``_economy_restore_pending_generation`` /
  ``_economy_pending_overlay`` / ``_economy_close_finalized`` 等协议状态字段的
  初始化仍全部在 ``PolarRMWindow.__init__`` 原位（D0 状态 schema 不动），
  D2 侧写入点（on_tick / _paint_gpu_frame_cached）亦保持原位；
- ``economy_lerp_rect`` 已在阶段 1 作为模块级纯函数迁入
  polar/text_metrics.py，不在本轮范围；
- ``rm_client/ui/economy_glass.py``（绘制基元）与
  ``rm_client/ui/economy_workspace.py``（EconomyIslandState /
  EconomyWorkspaceLayer）为域内既有独立模块，此前已迁，不重复处理；
  本 Mixin 仅经 ``self.economy_island`` / ``self.economy_workspace_layer``
  等实例字段继续使用它们；
- ``__qualname__`` 钉回：全部迁入方法（含 staticmethod
  ``economy_scale_steps``）在模块底部把 ``__qualname__`` 钉回
  ``PolarRMWindow.<name>``，api_freeze_test 的 qualname 基线比对不变；
- MRO：EconomyMixin 位于继承列表 ClickGuiBuildersMixin 之后、QOpenGLWidget
  之前，且与既有 Mixin 无同名成员（已逐一核对）→ 属性解析到本 Mixin，
  ``window.<成员>`` 表面不变；
- 共享辅助经继承访问、不重复处理：``get_auto_ui_scale`` / ``current_profile``
  族（PersistenceMixin，阶段 3a）、``setting_bool`` / ``anim_duration`` /
  ``toast`` / ``category_icon``（D19，留 polar_app.py）、``add_hotspot``（D15）、
  ``play_gui_transition_sound`` / ``set_clickgui_visible`` / ``open_match_chat``
  等（各自归属域）均经 ``self`` 继续调用，调用面与每帧开销不变。
"""

from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPainterPath

# 相对导入层级：rm_client/ui/polar/mixins/ → .. = polar、... = rm_client.ui、.... = rm_client
from ...animation import Easings
from ...jello_locale import chinese_enabled
from ...economy_locale import economy_text
from ...clickgui_gpu import ClickGuiDrawList
from ...gpu_frame_compositor import LensMaterial
from ...overlay_coordinator import OverlayKind
from ...paint import rounded_rect, text_width
from ...theme import THEME, color
from ...student_reload import append_reload_details, reload_detail_height, paint_reload_commands
from ...cs2_feedback import BUY_HOVER_SECONDS, _css_ease_in_out, append_buy_feedback, buy_enabled, play_buy_sound
from ...cs2_buy_menu import build_grid, grid_enabled
from ...economy_glass import draw_economy_glass, draw_economy_glass_capsule, draw_economy_glass_well
from ....economy import (
    CATEGORY_TITLES,
    TRANSACTION_LABELS,
    EconomyContext,
    EconomyOffer,
    EconomyRequest,
    available_actions,
)
from ....robot_profiles import profile_by_key
from ..primitives import EconomyScenePhase

__all__ = [
    "EconomyMixin",
]


class EconomyMixin:
    """D6 经济工作区（数据/传输 + legacy/compat 绘制 + GPU 工作区构建 + 开合状态机/交互）。"""

    def draw_economy_overlay_legacy(self, p: QPainter, width: int, height: int, alpha: float) -> None:
        actions = available_actions(self.state)
        if not actions:
            return
        self.economy_selected = max(0, min(len(actions) - 1, self.economy_selected))
        scale = max(0.78, min(1.18, self.get_auto_ui_scale(width, height, strength=0.34)))
        p.save()
        p.fillRect(QRectF(0, 0, width, height), color("#02050a", 0.34 * alpha))

        island_w = min(620 * scale, width * 0.54)
        collapsed_w = 210 * scale
        morph = Easings.ease_out_expo(max(0.0, min(1.0, alpha)))
        current_w = collapsed_w + (island_w - collapsed_w) * morph
        island = QRectF(width / 2 - current_w / 2, 34 * scale, current_w, 52 * scale)
        self.draw_liquid_glass_panel(p, island, 22 * scale, accent=THEME.cyan, hover=0.25, scale=scale, surface="ModalGlass")
        self.draw_glass_text(p, island.adjusted(22 * scale, 0, -22 * scale, 0), economy_text("ECONOMY  ·  {gold} GOLD", chinese_enabled(self.registry), gold=self.state.remaining_economy), self.font("poppins_bold", 10 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)

        panel_w = min(1080 * scale, width - 70 * scale)
        panel_h = min(520 * scale, height - 150 * scale)
        panel = QRectF(width / 2 - panel_w / 2, 108 * scale + (1.0 - morph) * 24 * scale, panel_w, panel_h)
        self.draw_liquid_glass_panel(p, panel, 20 * scale, accent=THEME.cyan, hover=0.12, scale=scale, surface="ModalGlass")
        self.draw_glass_text(p, panel.adjusted(28 * scale, 20 * scale, -28 * scale, -panel.height() + 54 * scale), "战斗经济操作", self.font("poppins_bold", 16 * scale), THEME.text)
        profile = profile_by_key(self.match_mode_manager.current.key, self.current_robot_profile_key())
        self.draw_glass_text(p, panel.adjusted(28 * scale, 54 * scale, -28 * scale, -panel.height() + 76 * scale), economy_text("{match} · {profile} · 默认 MOCK", chinese_enabled(self.registry), match=self.match_mode_manager.current.title, profile=profile.title), self.font("poppins_regular", 8 * scale), THEME.muted)

        count = len(actions)
        columns = min(3, max(1, count))
        gap = 14 * scale
        cards_left = panel.left() + 26 * scale
        cards_top = panel.top() + 96 * scale
        cards_w = panel.width() - 52 * scale
        card_w = (cards_w - gap * (columns - 1)) / columns
        card_h = 128 * scale
        for index, action in enumerate(actions):
            row, column = divmod(index, columns)
            rect = QRectF(cards_left + column * (card_w + gap), cards_top + row * (card_h + gap), card_w, card_h)
            selected = index == self.economy_selected
            hovered = rect.contains(self.hover_point)
            hover = self.anim.value(f"economy.hover.{action.key}", 1.0 if hovered else 0.0, self.anim_duration(0.14), Easings.ease_out_expo)
            accent = THEME.cyan if action.enabled else color("#9aa3aa", 0.62)
            self.draw_liquid_glass_panel(p, rect.translated(0, -3 * scale * hover), 13 * scale, accent=accent, hover=max(hover, 0.48 if selected else 0.0), scale=scale, surface="SubGlass")
            title_color = THEME.text if action.enabled else color("#b8bec3", 0.74)
            self.draw_glass_text(p, rect.adjusted(16 * scale, 14 * scale, -16 * scale, -rect.height() + 38 * scale), action.short_title, self.font("poppins_bold", 11 * scale), title_color)
            self.draw_glass_text(p, rect.adjusted(16 * scale, 42 * scale, -16 * scale, -rect.height() + 65 * scale), action.title, self.font("poppins_medium", 8 * scale), title_color)
            self.draw_glass_text(p, rect.adjusted(16 * scale, 76 * scale, -16 * scale, -15 * scale), economy_text("{cost} GOLD  ·  {unit}", chinese_enabled(self.registry), cost=action.cost, unit=action.unit), self.font("poppins_bold", 8 * scale), accent)
            if not action.enabled:
                self.draw_glass_text(p, rect.adjusted(16 * scale, 98 * scale, -16 * scale, -5 * scale), action.reason or "当前不可用", self.font("poppins_regular", 6.5 * scale), color("#ffb66e", 0.82))
            self.add_hotspot(rect, "economy_select", index, tooltip=action.reason or action.title)

        footer = QRectF(panel.left() + 26 * scale, panel.bottom() - 66 * scale, panel.width() - 52 * scale, 42 * scale)
        submit = QRectF(footer.right() - 184 * scale, footer.top(), 184 * scale, footer.height())
        close = QRectF(footer.left(), footer.top(), 104 * scale, footer.height())
        self.draw_liquid_glass_panel(p, close, 13 * scale, accent=color("#ffffff", 0.66), hover=0.0, scale=scale, surface="SubGlass")
        self.draw_glass_text(p, close, economy_text("CLOSE  [B]", chinese_enabled(self.registry)), self.font("poppins_bold", 7.5 * scale), THEME.text, Qt.AlignmentFlag.AlignCenter)
        selected_action = actions[self.economy_selected]
        submit_accent = THEME.cyan if selected_action.enabled else color("#8a9298", 0.58)
        self.draw_liquid_glass_panel(p, submit, 13 * scale, accent=submit_accent, hover=0.35 if selected_action.enabled else 0.0, scale=scale, surface="ProminentGlass")
        self.draw_glass_text(p, submit, economy_text("SEND MOCK REQUEST", chinese_enabled(self.registry)), self.font("poppins_bold", 8 * scale), THEME.text if selected_action.enabled else THEME.muted, Qt.AlignmentFlag.AlignCenter)
        self.add_hotspot(close, "economy_close")
        self.add_hotspot(submit, "economy_submit", self.economy_selected)
        p.restore()

    @staticmethod
    def economy_scale_steps() -> tuple[float, ...]:
        """Stable font-page scales used by the responsive economy workspace."""

        return (0.82, 0.90, 1.00, 1.05, 1.10)

    def economy_ui_scale(self, width: int, height: int) -> float:
        requested = max(
            0.82,
            min(
                1.10,
                self.get_auto_ui_scale(
                    max(1, width),
                    max(1, height),
                    strength=0.20,
                ),
            ),
        )
        return min(
            self.economy_scale_steps(),
            key=lambda candidate: abs(candidate - requested),
        )

    def economy_uses_mock_transport(self) -> bool:
        module = self.registry.get("EconomyPanel")
        force_mock = self.setting_bool(module, "Mock Requests", True) if module else True
        return force_mock or self.scenario_manager.current.key != "OfficialEvent"

    def send_economy_request(self, request: EconomyRequest) -> bool:
        """Send a confirmed economy request without mutating local match state."""
        if request.mock:
            return True
        if self.scenario_manager.current.key != "OfficialEvent":
            self.mqtt.last_error = "仅官方赛事场景允许发送正式经济请求"
            return False
        qualification_token = getattr(self, "_economy_qualification_token", None)
        if qualification_token is not None:
            # A qualification capability authorises one supervised attempt,
            # not a 30-second burst of economy commands. Consume the UI copy
            # before publishing and destroy the backend capability immediately
            # afterwards, irrespective of broker acceptance.
            self._economy_qualification_token = None
        try:
            if request.topic == "AirSupportCommand":
                return self.mqtt.publish_air_support_command(
                    request.payload,
                    qualification_token=qualification_token,
                )
            return self.mqtt.publish_common_command(
                request.payload,
                qualification_token=qualification_token,
            )
        finally:
            if qualification_token is not None:
                self.backend.lock_control("economy qualification command attempted")

    def economy_offers(self, category: str | None = None) -> list[EconomyOffer]:
        offers = available_actions(self.state)
        labels = {"rmuc_confirm_respawn": "免费复活 [Y]", "rmuc_gold_respawn": "买活 [F1]"}
        offers = [replace(offer, title=labels[offer.key], short_title=labels[offer.key])
                  if offer.key in labels else offer for offer in offers]
        if category is None:
            return offers
        return [offer for offer in offers if offer.category == category]

    def economy_categories(self, offers: list[EconomyOffer] | None = None) -> list[str]:
        offers = self.economy_offers() if offers is None else offers
        present = {offer.category for offer in offers}
        return [key for key in CATEGORY_TITLES if key in present]

    def economy_selected_offer(self) -> EconomyOffer | None:
        offers = self.economy_offers(self.economy_category)
        if not offers:
            return None
        for offer in offers:
            if offer.key == self.economy_selected_key:
                return offer
        self.economy_selected_key = offers[0].key
        self.economy_selected = 0
        return offers[0]

    def _finalize_economy_restore(self, generation: int) -> None:
        """Commit a close only after the rebuilt normal HUD was presented."""

        if (
            self.economy_phase != EconomyScenePhase.CLOSING
            or generation != self._economy_generation
            or self._economy_restore_pending_generation != generation
        ):
            return
        self._economy_restore_pending_generation = None
        self._economy_closing_generation = None
        self.economy_phase = EconomyScenePhase.CLOSED
        self.economy_visible = False
        self._economy_close_finalized = True
        self.economy_island.progress = 0.0
        self.economy_island.target = 0.0
        self.economy_island.velocity = 0.0
        self.overlay_coordinator.close_modal(OverlayKind.ECONOMY)
        self.frame_scheduler.force()
        pending_overlay = self._economy_pending_overlay
        self._economy_pending_overlay = None
        if pending_overlay is not None:
            def open_pending_overlay() -> None:
                if pending_overlay == OverlayKind.CLICKGUI:
                    self.set_clickgui_visible(True)
                elif pending_overlay == OverlayKind.CHAT:
                    self.open_match_chat()
                elif pending_overlay == OverlayKind.HERO_DEPLOY:
                    self.open_hero_deploy_interface()
                elif pending_overlay == OverlayKind.STUDENT:
                    panel = self._student_pending_panel
                    self._student_pending_panel = None
                    if panel:
                        self.open_student_panel(panel)

            # Present/restore is still on the GL stack here. Defer the next
            # modal request to the event queue so ownership never overlaps.
            QTimer.singleShot(0, open_pending_overlay)

    def open_economy_workspace(self, category: str | None = None) -> None:
        self.close_student_panel(immediate=True)
        if self.hero_deploy_video_cut_active():
            self.open_hero_deploy_interface()
            self.toast("Exit Hero deploy mode before opening Economy")
            return
        now = time.perf_counter()
        if self.hero_deploy_ui.visible:
            self.close_hero_deploy_interface(force=True)
        offers = self.economy_offers()
        categories = self.economy_categories(offers)
        if category in categories:
            self.economy_category = str(category)
        elif self.economy_category not in categories and categories:
            self.economy_category = categories[0]
        if self.gui_visible:
            self.set_clickgui_visible(False, announce=False, play_sound=False)
        self.close_match_chat(clear=False)
        self.cancel_quick_action_wheel()
        self._economy_generation += 1
        self._economy_closing_generation = None
        self._economy_restore_pending_generation = None
        self._economy_pending_overlay = None
        self.overlay_coordinator.request_modal(OverlayKind.ECONOMY)
        self.economy_visible = True
        self._economy_close_finalized = False
        self.economy_phase = EconomyScenePhase.OPENING
        self.economy_opened_at = now
        self.economy_island.set_target(
            1.0,
            self.anim_duration(0.62),
            now=now,
        )
        self._economy_scene_epoch += 1
        self.economy_armed_key = ""
        self.economy_hold_key = ""
        self.economy_category_scroll.position = 0.0
        self.economy_category_scroll.target = 0.0
        self.economy_category_scroll.velocity = 0.0
        self.economy_offers_scroll.position = 0.0
        self.economy_offers_scroll.target = 0.0
        self.economy_offers_scroll.velocity = 0.0
        self.economy_detail_scroll.position = 0.0
        self.economy_detail_scroll.target = 0.0
        self.economy_detail_scroll.velocity = 0.0
        selected = self.economy_selected_offer()
        if selected is not None:
            self.economy_selected_key = selected.key
        # Capture a fresh, complete HUD snapshot for the backdrop treatment.
        self.invalidate_transient_overlay_scene()
        self.play_gui_transition_sound("expand")
        self.frame_scheduler.force()
        self.update()

    def close_economy_workspace(self, *, play_sound: bool = True) -> None:
        if self.economy_phase == EconomyScenePhase.CLOSED:
            self.overlay_coordinator.close_modal(OverlayKind.ECONOMY)
            return
        if self.economy_phase == EconomyScenePhase.CLOSING:
            return
        now = time.perf_counter()
        self._economy_generation += 1
        self._economy_closing_generation = self._economy_generation
        self._economy_restore_pending_generation = None
        self.economy_visible = False
        self._economy_close_finalized = False
        self.economy_phase = EconomyScenePhase.CLOSING
        # Keep the Economy modal until a normal HUD frame has actually been
        # rebuilt and presented.  Releasing it here caused click-through and
        # let a stale transparent FBO become the new cache.
        self.overlay_coordinator.request_modal(OverlayKind.ECONOMY)
        self.economy_island.set_target(
            0.0,
            self.anim_duration(0.48),
            now=now,
        )
        self._economy_scene_epoch += 1
        self.economy_armed_key = ""
        self.economy_hold_key = ""
        self.economy_hold_rect = QRectF()
        self.invalidate_transient_overlay_scene()
        self.hotspots = [
            hotspot
            for hotspot in self.hotspots
            if not str(hotspot.action).startswith("economy")
        ]
        if play_sound:
            self.play_gui_transition_sound("collapse")
        self.frame_scheduler.force()
        self.update()

    def select_economy_offer(self, key: str) -> None:
        offers = self.economy_offers(self.economy_category)
        for index, offer in enumerate(offers):
            if offer.key == key:
                # Only wipe double-confirm arm when the selection *changes*.
                # Clearing on re-select broke the second click on “再次确认”.
                if key != self.economy_selected_key:
                    play_buy_sound(self, "buy_select")
                    self.economy_armed_key = ""
                    self.economy_armed_until = 0.0
                self.economy_selected = index
                self.economy_selected_key = key
                self.frame_scheduler.force()
                return

    def submit_economy_offer(self, offer: EconomyOffer) -> None:
        if not offer.enabled or offer.status_only:
            self.toast(offer.reason or "当前操作不可用")
            return
        latest = self.economy_bridge.latest
        if latest is not None and latest.status == "pending":
            self.toast("上一笔请求仍在等待确认")
            return
        try:
            transaction = self.economy_bridge.submit(
                self.state,
                offer,
                1,
                mock=self.economy_uses_mock_transport(),
            )
        except ValueError as exc:
            self.toast(str(exc))
            return
        self.economy_armed_key = ""
        self.economy_armed_until = 0.0
        self.economy_hold_key = ""
        self.toast(f"{transaction.message} · {offer.short_title}")
        self.frame_scheduler.force()

    def activate_economy_offer(self, offer: EconomyOffer) -> None:
        if not offer.enabled or offer.status_only:
            self.toast(offer.reason or "当前操作不可用")
            return
        if offer.confirmation == "hold":
            self.toast("请按住确认按钮 0.6 秒")
            return
        now = time.perf_counter()
        if self.economy_armed_key == offer.key and now <= self.economy_armed_until:
            self.submit_economy_offer(offer)
            return
        self.economy_armed_key = offer.key
        self.economy_armed_until = now + 2.8
        self.toast(f"再点一次确认购买：{offer.short_title}（{offer.cost} 金币）")
        self.frame_scheduler.force()

    def begin_economy_hold(self, offer: EconomyOffer, rect: QRectF | None = None) -> None:
        if not offer.enabled or offer.status_only:
            self.toast(offer.reason or "当前操作不可用")
            return
        self.economy_hold_key = offer.key
        self.economy_hold_started = time.perf_counter()
        self.economy_hold_rect = QRectF(rect) if rect is not None else QRectF()
        self.frame_scheduler.force()

    def finish_economy_hold(self, point: QPointF | None = None) -> None:
        if not self.economy_hold_key:
            return
        key = self.economy_hold_key
        elapsed = time.perf_counter() - self.economy_hold_started
        inside = point is None or self.economy_hold_rect.isNull() or self.economy_hold_rect.contains(point)
        self.economy_hold_key = ""
        self.economy_hold_rect = QRectF()
        offer = next((item for item in self.economy_offers() if item.key == key), None)
        if offer is not None and inside and elapsed >= 0.60:
            self.submit_economy_offer(offer)
        elif elapsed < 0.60:
            self.toast("需要按住 0.6 秒确认")
        self.frame_scheduler.force()

    def _economy_glass_row(
        self,
        p: QPainter,
        rect: QRectF,
        *,
        hover: float = 0.0,
        active: bool = False,
    ) -> None:
        """Island capsule row — AndroidLiquidGlass-kmp style, no white overlay."""
        draw_economy_glass_capsule(p, rect, hover=hover, active=active)

    def _economy_dim_around(
        self,
        p: QPainter,
        width: int,
        height: int,
        panel: QRectF,
        dim_a: float,
        radius: float,
    ) -> None:
        """Dim only outside the glass shell so Combined Backdrop stays bright under the lens."""
        if dim_a <= 0.001:
            return
        dim = color("#02060c", dim_a)
        path = QPainterPath()
        path.addRect(QRectF(0, 0, float(width), float(height)))
        hole = QPainterPath()
        hole.addRoundedRect(panel, radius, radius)
        p.fillPath(path.subtracted(hole), dim)

    def _economy_island_well(self, p: QPainter, rect: QRectF, radius: float) -> None:
        """Island floating well — AndroidLiquidGlass-kmp recessed glass."""
        draw_economy_glass_well(p, rect, radius)

    def draw_economy_overlay_compat(self, p: QPainter, width: int, height: int, alpha: float) -> None:
        """Economy workspace: liquid glass + Dynamic Island morph + island chrome.

        - Collapse = top LensIsland capsule (radius = half height)
        - Expand = one highly-rounded LensStrong shell (not a hard rectangle)
        - Columns = floating island wells with gaps (no spreadsheet hairlines)
        - Rows / chips / CTA = full capsules (radius = half height)
        """
        all_offers = self.economy_offers()
        categories = self.economy_categories(all_offers)
        if not categories:
            return
        if self.economy_category not in categories:
            self.economy_category = categories[0]
        offers = [offer for offer in all_offers if offer.category == self.economy_category]
        selected = self.economy_selected_offer()
        context = EconomyContext.from_state(self.state)
        scale = self.economy_ui_scale(width, height)
        morph = Easings.ease_out_expo(max(0.0, min(1.0, alpha)))
        content_alpha = Easings.ease_out_expo(max(0.0, min(1.0, (morph - 0.12) / 0.88)))
        compact = width < 1480 or height < 860

        # Keep the fallback sheet anchored to the top island as well. It must
        # never regress into a centered modal when the GPU path is unavailable.
        margin_x = 16.0 * scale if compact else 28.0 * scale
        top_margin = 18.0 * scale if compact else 24.0 * scale
        bottom_margin = 18.0 * scale if compact else 28.0 * scale
        target_w = min(width - margin_x * 2.0, 1510.0 * scale)
        target_h = min(height - top_margin - bottom_margin, 740.0 * scale)
        target = QRectF((width - target_w) * 0.5, top_margin, target_w, target_h)
        island_h = 44.0 * scale
        island_w = min(max(280.0 * scale, 360.0 * scale), width * 0.40)
        collapsed = QRectF(width * 0.5 - island_w * 0.5, top_margin, island_w, island_h)
        # Expanded corner stays very round (squircle-ish), never a hard 12–16 box.
        expand_r = min(40.0 * scale, min(target_w, target_h) * 0.08)
        # Both configured entry styles retain the same top anchor.  The
        # compatibility option may alter content density, but it must never
        # turn the economy workspace back into a centered modal.
        panel = self.economy_lerp_rect(collapsed, target, morph)
        radius = island_h * 0.5 * (1.0 - morph) + expand_r * morph

        p.save()
        # Compatibility scene dim. The caller owns battle-HUD exclusion.
        p.fillRect(QRectF(0, 0, width, height), color("#02060c", 0.36 * alpha))
        # Extra punch around shell so glass still samples a bright Combined Backdrop.
        self._economy_dim_around(p, width, height, panel, 0.10 * alpha, radius)

        draw_economy_glass(
            p,
            panel,
            radius,
            edge_width=12.0 * scale,
            highlight_intensity=0.30 + 0.08 * morph,
            shadow_radius=20.0 * scale,
            shadow_alpha=0.16 * alpha,
            tint_alpha=0.07,
            edge_tint_alpha=0.12,
        )
        if morph > 0.35:
            top_hi = QRectF(
                panel.left() + radius * 0.55,
                panel.top() + 11.0 * scale,
                panel.width() - radius * 1.1,
                1.0,
            )
            rounded_rect(p, top_hi, 0.5, color("#ffffff", 0.14 * content_alpha))

        if morph < 0.88:
            island_label = economy_text("经济  ·  {gold} G", chinese_enabled(self.registry), gold=context.gold)
            if morph < 0.52:
                self.draw_glass_text(
                    p,
                    panel,
                    island_label,
                    self.font("poppins_bold", 10.5 * scale),
                    color("#ffffff", max(0.0, 1.0 - morph * 1.75)),
                    Qt.AlignmentFlag.AlignCenter,
                )

        header_h = 58.0 * scale
        header = QRectF(panel.left() + 26.0 * scale, panel.top() + 16.0 * scale, panel.width() - 52.0 * scale, header_h - 14.0 * scale)
        if content_alpha > 0.02:
            p.save()
            p.setOpacity(p.opacity() * content_alpha)
            self.draw_glass_text(p, header, "战斗经济", self.font("poppins_bold", 17.0 * scale), color("#ffffff"))
            link = "模拟" if context.mock_mode else "裁判"
            profile_title = profile_by_key(context.match_mode, context.robot_profile).title
            subtitle = f"{self.match_mode_manager.current.title}  ·  {profile_title}  ·  {link}"
            self.draw_glass_text(
                p,
                header.adjusted(0, 24.0 * scale, -120.0 * scale, 0),
                subtitle,
                self.font("poppins_medium", 8.2 * scale),
                color("#c8d8e8", 0.88),
            )
            close = QRectF(header.right() - 36.0 * scale, header.top() + 2.0 * scale, 34.0 * scale, 34.0 * scale)
            gold_chip_w = 100.0 * scale
            gold_chip = QRectF(close.left() - 10.0 * scale - gold_chip_w, header.top() + 4.0 * scale, gold_chip_w, 30.0 * scale)
            rounded_rect(p, gold_chip, gold_chip.height() * 0.5, color("#000000", 0.20), color("#ffd56a", 0.40), 1.0)
            self.draw_glass_text(
                p,
                gold_chip,
                economy_text("{gold} G", chinese_enabled(self.registry), gold=context.gold),
                self.font("poppins_bold", 10.0 * scale),
                color("#ffd56a"),
                Qt.AlignmentFlag.AlignCenter,
            )
            rounded_rect(p, close, close.height() * 0.5, color("#000000", 0.18), color("#ffffff", 0.20), 1.0)
            self.draw_glass_text(p, close, "×", self.font("poppins_bold", 15.0 * scale), color("#ffffff"), Qt.AlignmentFlag.AlignCenter)
            self.add_hotspot(close, "economy_close", tooltip="关闭经济工作区 [Esc]")
            p.restore()

        if content_alpha <= 0.01 or panel.height() < 180.0 * scale:
            p.restore()
            return
        p.setOpacity(p.opacity() * content_alpha)

        # Floating island columns with real gaps — not a squared grid with hairlines.
        col_gap = 12.0 * scale
        inner = panel.adjusted(20.0 * scale, header_h + 6.0 * scale, -20.0 * scale, -18.0 * scale)
        left_w = max(172.0 * scale, min(228.0 * scale, inner.width() * 0.20))
        rest = max(40.0, inner.width() - left_w - col_gap)
        well_r = 22.0 * scale
        if compact:
            left = QRectF(inner.left(), inner.top(), left_w, inner.height())
            content = QRectF(left.right() + col_gap, inner.top(), rest, inner.height())
            list_h = max(150.0 * scale, content.height() * 0.44)
            list_rect = QRectF(content.left(), content.top(), content.width(), list_h)
            detail = QRectF(content.left(), list_rect.bottom() + col_gap, content.width(), content.bottom() - list_rect.bottom() - col_gap)
        else:
            list_w = max(280.0 * scale, min(rest * 0.48, rest - 250.0 * scale - col_gap))
            left = QRectF(inner.left(), inner.top(), left_w, inner.height())
            list_rect = QRectF(left.right() + col_gap, inner.top(), list_w, inner.height())
            detail = QRectF(list_rect.right() + col_gap, inner.top(), inner.right() - list_rect.right() - col_gap, inner.height())

        for well in (left, list_rect, detail):
            self._economy_island_well(p, well, well_r)

        pad = 16.0 * scale
        gold_font = self.font("poppins_bold", 28.0 * scale)
        self.draw_glass_text(
            p,
            left.adjusted(pad, 12.0 * scale, -pad, -left.height() + 30.0 * scale),
            "当前金币",
            self.font("poppins_bold", 8.2 * scale),
            color("#aebcc8"),
        )
        gold_text = f"{context.gold}"
        gold_rect = QRectF(left.left() + pad, left.top() + 32.0 * scale, left.width() - pad * 2.0 - 22.0 * scale, 40.0 * scale)
        self.draw_glass_text(p, gold_rect, gold_text, gold_font, color("#ffffff"))
        self.draw_glass_text(
            p,
            QRectF(gold_rect.left() + text_width(p, gold_font, gold_text) + 6.0 * scale, gold_rect.top() + 14.0 * scale, 24.0 * scale, 24.0 * scale),
            economy_text("G", chinese_enabled(self.registry)),
            self.font("poppins_bold", 11.0 * scale),
            color("#ffd56a"),
        )
        economy_ratio = context.gold / max(1.0, float(max(context.total_gold, context.gold)))
        track = QRectF(left.left() + pad, left.top() + 80.0 * scale, left.width() - pad * 2.0, 6.0 * scale)
        rounded_rect(p, track, track.height() * 0.5, color("#ffffff", 0.08), color("#ffffff", 0.04), 0.5)
        rounded_rect(
            p,
            QRectF(track.left(), track.top(), max(6.0, track.width() * economy_ratio), track.height()),
            track.height() * 0.5,
            color("#ffd56a", 0.92),
        )
        pending_cost = self.economy_bridge.latest.request.cost if self.economy_bridge.latest and self.economy_bridge.latest.status == "pending" else 0
        summary = f"累计 {context.total_gold} · 待扣 {pending_cost}"
        self.draw_glass_text(
            p,
            left.adjusted(pad, 92.0 * scale, -pad, -left.height() + 112.0 * scale),
            summary,
            self.font("poppins_medium", 7.4 * scale),
            color("#9aafc0", 0.92),
        )

        status_block_h = 100.0 * scale
        category_top = left.top() + 124.0 * scale
        category_bottom = left.bottom() - status_block_h - 10.0 * scale
        cat_count = max(1, len(categories))
        cat_gap = 8.0 * scale
        cat_avail = max(40.0 * scale, category_bottom - category_top)
        category_h = min(40.0 * scale, max(32.0 * scale, (cat_avail - cat_gap * (cat_count - 1)) / cat_count))
        self.draw_glass_text(
            p,
            QRectF(left.left() + pad, category_top - 18.0 * scale, left.width() - pad * 2.0, 16.0 * scale),
            "分类",
            self.font("poppins_bold", 7.6 * scale),
            color("#8fa3b5"),
        )
        for index, key in enumerate(categories):
            rect = QRectF(left.left() + pad, category_top + index * (category_h + cat_gap), left.width() - pad * 2.0, category_h)
            if rect.bottom() > category_bottom + 1.0:
                break
            active = key == self.economy_category
            draw_economy_glass_capsule(p, rect, hover=0.0, active=active)
            self.draw_glass_text(
                p,
                rect.adjusted(14.0 * scale, 0, -10.0 * scale, 0),
                CATEGORY_TITLES.get(key, key),
                self.font("poppins_bold", 10.0 * scale),
                color("#ffffff") if active else color("#c8d6e4", 0.90),
            )
            self.add_hotspot(rect, "economy_category", key)

        status_y = left.bottom() - status_block_h
        hp_ratio = context.current_health / max(1.0, float(context.max_health))
        ammo_ratio = context.current_ammo / max(1.0, float(context.ammo_capacity or context.current_ammo or 1))
        for row, (label, value, ratio, accent) in enumerate((
            ("血量", f"{context.current_health}/{context.max_health}", hp_ratio, color("#64dda1")),
            ("弹丸", f"{context.current_ammo}/{context.ammo_capacity or '--'}", ammo_ratio, color("#64baff")),
        )):
            y = status_y + row * 46.0 * scale
            self.draw_glass_text(
                p,
                QRectF(left.left() + pad, y, left.width() - pad * 2.0, 16.0 * scale),
                f"{label}  {value}",
                self.font("poppins_medium", 7.8 * scale),
                color("#e8f0f8"),
            )
            bar = QRectF(left.left() + pad, y + 20.0 * scale, left.width() - pad * 2.0, 5.0 * scale)
            rounded_rect(p, bar, bar.height() * 0.5, color("#ffffff", 0.08), color("#ffffff", 0.04), 0.5)
            rounded_rect(
                p,
                QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, ratio)), bar.height()),
                bar.height() * 0.5,
                accent,
            )

        list_pad = 14.0 * scale
        title_h = 28.0 * scale
        self.draw_glass_text(
            p,
            list_rect.adjusted(list_pad, 12.0 * scale, -list_pad, -list_rect.height() + title_h + 4.0 * scale),
            f"可选操作 · {CATEGORY_TITLES.get(self.economy_category, self.economy_category)}",
            self.font("poppins_bold", 10.5 * scale),
            color("#ffffff"),
        )
        viewport = list_rect.adjusted(list_pad, title_h + 6.0 * scale, -list_pad, -list_pad)
        card_h = max(54.0 * scale, min(68.0 * scale, viewport.height() * 0.26 if compact else 62.0 * scale))
        card_gap = 8.0 * scale
        self.economy_offers_scroll.set_bounds(max(0.0, len(offers) * (card_h + card_gap) - card_gap - viewport.height()))
        p.save()
        p.setClipRect(viewport)
        previous_clip = getattr(self, "_hotspot_clip", None)
        self._hotspot_clip = viewport
        scroll = self.economy_offers_scroll.position
        for index, offer in enumerate(offers):
            rect = QRectF(viewport.left(), viewport.top() + index * (card_h + card_gap) - scroll, viewport.width(), card_h)
            if not rect.intersects(viewport):
                continue
            active = selected is not None and offer.key == selected.key
            hovered = rect.contains(self.hover_point)
            hover_v = self.anim.value(
                f"economy.hover.{offer.key}",
                1.0 if hovered or active else 0.0,
                self.anim_duration(0.14),
                Easings.ease_out_expo,
            )
            self._economy_glass_row(p, rect, hover=hover_v, active=active)
            title_color = color("#ffffff") if offer.enabled else color("#9aa3ac", 0.72)
            price_w = 88.0 * scale
            self.draw_glass_text(
                p,
                rect.adjusted(18.0 * scale, 8.0 * scale, -price_w - 10.0 * scale, -rect.height() + 32.0 * scale),
                offer.short_title,
                self.font("poppins_bold", 10.5 * scale),
                title_color,
            )
            price = "仅状态" if offer.status_only else f"{offer.cost} 金币"
            self.draw_glass_text(
                p,
                rect.adjusted(18.0 * scale, 8.0 * scale, -14.0 * scale, -rect.height() + 32.0 * scale),
                price,
                self.font("poppins_bold", 9.5 * scale),
                color("#ffd56a") if offer.enabled else color("#b8a878", 0.55),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            secondary = offer.reason if not offer.enabled else offer.description
            self.draw_glass_text(
                p,
                rect.adjusted(18.0 * scale, 32.0 * scale, -14.0 * scale, -8.0 * scale),
                secondary,
                self.font("poppins_medium", 7.8 * scale),
                color("#b8c8d8", 0.90 if offer.enabled else 0.55),
            )
            self.add_hotspot(rect, "economy_offer", offer.key, tooltip=offer.reason or offer.description)
        self._hotspot_clip = previous_clip
        p.restore()

        detail_pad = 16.0 * scale
        button_h = 46.0 * scale
        button = QRectF(
            detail.left() + detail_pad,
            detail.bottom() - button_h - 14.0 * scale,
            max(40.0, detail.width() - detail_pad * 2.0),
            button_h,
        )
        content_bottom = button.top() - 10.0 * scale
        if selected is not None and detail.height() > 80.0 * scale:
            self.draw_glass_text(
                p,
                QRectF(detail.left() + detail_pad, detail.top() + 14.0 * scale, detail.width() - detail_pad * 2.0, 28.0 * scale),
                selected.title,
                self.font("poppins_bold", 13.5 * scale),
                color("#ffffff"),
            )
            tag = "预计价格" if selected.estimated else ("模拟请求" if context.mock_mode else "裁判系统")
            self.draw_glass_text(
                p,
                QRectF(detail.left() + detail_pad, detail.top() + 44.0 * scale, detail.width() - detail_pad * 2.0, 22.0 * scale),
                f"{selected.unit}  ·  {selected.cost} 金币  ·  {tag}",
                self.font("poppins_medium", 9.0 * scale),
                color("#ffd56a"),
            )
            self.draw_glass_text(
                p,
                QRectF(detail.left() + detail_pad, detail.top() + 70.0 * scale, detail.width() - detail_pad * 2.0, 40.0 * scale),
                selected.description,
                self.font("poppins_medium", 8.4 * scale),
                color("#d0dce8"),
            )
            state_text = selected.reason if not selected.enabled else "可以购买"
            state_color = color("#ffb06f") if not selected.enabled else color("#70e0ae")
            self.draw_glass_text(
                p,
                QRectF(detail.left() + detail_pad, detail.top() + 112.0 * scale, detail.width() - detail_pad * 2.0, 22.0 * scale),
                state_text,
                self.font("poppins_bold", 9.5 * scale),
                state_color,
            )

        history_top = detail.top() + 144.0 * scale
        history_max_bottom = content_bottom - 4.0 * scale
        if self.economy_category == "ammo":
            reload_clip = QRectF(detail.left()+detail_pad, history_top,
                                detail.width()-2*detail_pad, max(0.0, history_max_bottom-history_top))
            reload_commands = ClickGuiDrawList()
            append_reload_details(self, reload_commands, reload_clip, reload_clip, content_alpha, scale, self.economy_visible)
            paint_reload_commands(self, p, reload_commands)
            history_top += reload_detail_height(self)*scale
        if history_top + 40.0 * scale < history_max_bottom:
            self.draw_glass_text(
                p,
                QRectF(detail.left() + detail_pad, history_top, detail.width() - detail_pad * 2.0, 20.0 * scale),
                "最近交易",
                self.font("poppins_bold", 8.6 * scale),
                color("#8fa3b5"),
            )
            history = list(reversed(self.economy_bridge.history[-3:]))
            if not history:
                if history_top + 40.0 * scale < history_max_bottom:
                    self.draw_glass_text(
                        p,
                        QRectF(detail.left() + detail_pad, history_top + 24.0 * scale, detail.width() - detail_pad * 2.0, 18.0 * scale),
                        "暂无记录",
                        self.font("poppins_medium", 8.0 * scale),
                        color("#7a8c9c"),
                    )
            for index, transaction in enumerate(history):
                y = history_top + 24.0 * scale + index * 36.0 * scale
                if y + 32.0 * scale > history_max_bottom:
                    break
                label = TRANSACTION_LABELS.get(transaction.status, transaction.status)
                status_color = (
                    color("#70e0ae")
                    if transaction.status == "succeeded"
                    else color("#ffb96b")
                    if transaction.status in ("rejected", "timed_out")
                    else color("#72bfff")
                )
                self.draw_glass_text(
                    p,
                    QRectF(detail.left() + detail_pad, y, detail.width() - detail_pad * 2.0, 16.0 * scale),
                    f"{label} · {transaction.offer.short_title}",
                    self.font("poppins_bold", 8.2 * scale),
                    status_color,
                )
                self.draw_glass_text(
                    p,
                    QRectF(detail.left() + detail_pad, y + 16.0 * scale, detail.width() - detail_pad * 2.0, 14.0 * scale),
                    transaction.message,
                    self.font("poppins_medium", 7.4 * scale),
                    color("#a8bac8", 0.90),
                )

        now = time.perf_counter()
        pending = self.economy_bridge.latest is not None and self.economy_bridge.latest.status == "pending"
        if selected is None:
            button_text = "请先选择商品"
            button_enabled = False
            action = "economy_confirm"
        elif pending:
            button_text = "请求处理中…"
            button_enabled = False
            action = "economy_confirm"
        elif not selected.enabled or selected.status_only:
            button_text = selected.reason or "当前不可用"
            button_enabled = False
            action = "economy_confirm"
        elif selected.confirmation == "hold":
            hold_progress = (
                max(0.0, min(1.0, (now - self.economy_hold_started) / 0.60))
                if self.economy_hold_key == selected.key
                else 0.0
            )
            button_text = "按住 0.6 秒确认" if hold_progress <= 0.0 else f"确认中 {round(hold_progress * 100)}%"
            button_enabled = True
            action = "economy_confirm_hold"
        else:
            armed = self.economy_armed_key == selected.key and now <= self.economy_armed_until
            if armed:
                remain = max(0.0, self.economy_armed_until - now)
                button_text = f"再点一次确认（{remain:.1f}s）"
            else:
                button_text = f"确认购买 · {selected.cost} 金币"
            button_enabled = True
            action = "economy_confirm"

        draw_economy_glass(
            p,
            button,
            button.height() * 0.5,
            edge_width=6.0 * scale,
            highlight_intensity=0.38 if button_enabled else 0.10,
            shadow_radius=10.0 * scale,
            shadow_alpha=0.12,
            tint_alpha=0.10 if button_enabled else 0.06,
            tint_color="#0a2820" if button_enabled else "#0a1420",
            edge_tint_alpha=0.16 if button_enabled else 0.06,
        )
        if button_enabled:
            rounded_rect(
                p,
                button,
                button.height() * 0.5,
                color("#1a6b58", 0.14),
                color("#5ce7d8", 0.40),
                1.0,
            )
        if selected is not None and selected.confirmation == "hold" and self.economy_hold_key == selected.key:
            progress = max(0.0, min(1.0, (now - self.economy_hold_started) / 0.60))
            fill = QRectF(button.left(), button.top(), max(8.0, button.width() * progress), button.height())
            clip = QPainterPath()
            clip.addRoundedRect(button, button.height() * 0.5, button.height() * 0.5)
            p.save()
            p.setClipPath(clip)
            rounded_rect(p, fill, button.height() * 0.5, color("#65e5d7", 0.40))
            p.restore()
        self.draw_glass_text(
            p,
            button,
            button_text,
            self.font("poppins_bold", 11.0 * scale),
            color("#ffffff") if button_enabled else color("#c5ccd3", 0.72),
            Qt.AlignmentFlag.AlignCenter,
        )
        if selected is not None and button_enabled:
            self.add_hotspot(button, action, selected.key, tooltip=button_text)
        p.restore()

    def build_gpu_economy_workspace(self, width: int, height: int) -> ClickGuiDrawList:
        """Build the exclusive economy GPU scene.

        The scene is deliberately a pull-down, not a modal: a compact top
        island becomes a single downward sheet, then clips its controls into
        view.  Economy rules and command routing remain outside this renderer.
        """
        if grid_enabled(self):
            return build_grid(self, width, height)
        commands = ClickGuiDrawList()
        self.hotspots.clear()
        progress = self.economy_island.progress
        layout = self.economy_workspace_layer.layout(width, height, progress)
        if progress < 0.02:
            return commands

        all_offers = self.economy_offers()
        categories = self.economy_categories(all_offers)
        if not categories:
            return commands
        if self.economy_category not in categories:
            self.economy_category = categories[0]
        offers = [o for o in all_offers if o.category == self.economy_category]
        selected = self.economy_selected_offer()
        context = EconomyContext.from_state(self.state)
        header_alpha = layout.header_alpha
        content_alpha = layout.content_alpha
        category_alpha = layout.category_alpha
        offers_alpha = layout.offers_alpha
        detail_alpha = layout.detail_alpha
        panel = layout.panel
        def add_control_center_tile(
            rect: QRectF,
            opacity: float,
            *,
            material: LensMaterial = LensMaterial.STRONG,
            clip: QRectF | None = None,
        ) -> QRectF:
            tile = QRectF(rect)
            visible = tile.intersected(clip) if clip is not None else QRectF(tile)
            alpha = max(0.0, min(1.0, float(opacity)))
            if visible.isEmpty() or alpha <= 0.01:
                return QRectF()
            radius = min(34.0, tile.height() * 0.5)
            # ControlCenterContent is calibrated on a 68dp minimum tile.
            # Smaller desktop controls must scale both lens depth and travel
            # together; retaining a 48px travel on a 38px strip creates the
            # long horizontal distortion visible in the previous build.
            lens_scale = min(1.0, max(0.20, min(tile.width(), tile.height()) / 68.0))
            self.gpu_compositor.add_glass(
                tile,
                radius,
                strength=1.0,
                surface="clear",
                opacity=alpha,
                material=material,
                refraction_height_px=max(1.0, 24.0 * lens_scale * alpha),
                refraction_amount_px=-max(1.0, 48.0 * lens_scale * alpha),
                chromatic_aberration=0.0,
                depth_effect=1.0,
                frost_amount=0.0,
                vibrancy_amount=alpha,
                clip_rect=clip,
            )
            # ControlCenterContent uses a five-percent black container color.
            commands.rect(tile, radius, color("#000000", 0.05 * alpha), clip=clip)
            return visible

        # Control Center is a group of independent glass modules over one
        # treated backdrop. It never places one giant frosted card behind all
        # controls.
        header = layout.header
        header_tile = QRectF(
            header.left() - 16.0,
            panel.top(),
            header.width() + 32.0,
            min(panel.height(), 68.0),
        )
        add_control_center_tile(
            header_tile,
            header_alpha,
            material=LensMaterial.STRONG,
        )

        # --- Island summary: visible before the body begins to reveal. ---
        scale = self.economy_ui_scale(width, height)
        # This handle belongs to the same root lens. It gives the expanded
        # sheet a clear pull-down affordance without adding another panel.
        handle_alpha = max(0.0, min(0.52, layout.body_progress * 0.52))
        commands.rect(
            layout.grab_handle,
            layout.grab_handle.height() * 0.5,
            color("#ffffff", handle_alpha),
        )
        commands.text(
            QRectF(header.left(), header.top(), header.width() - 160.0, 28.0),
            "战斗经济", self.font("poppins_bold", 17.0 * scale),
            color("#ffffff", header_alpha),
        )
        link = "模拟" if context.mock_mode else "裁判"
        profile_title = profile_by_key(context.match_mode, context.robot_profile).title
        subtitle = f"{self.match_mode_manager.current.title}  ·  {profile_title}  ·  {link}"
        commands.text(
            QRectF(header.left(), header.top() + 26.0, header.width() - 200.0, 18.0),
            subtitle, self.font("poppins_medium", 8.2 * scale),
            color("#c8d8e8", 0.88 * header_alpha),
        )

        # --- Gold chip ---
        gold_chip = layout.link_chip
        commands.rect(
            gold_chip,
            gold_chip.height() * 0.5,
            color("#ffffff", 0.08 * header_alpha),
        )
        commands.text(gold_chip, economy_text("{gold} G", chinese_enabled(self.registry), gold=context.gold), self.font("poppins_bold", 10.0 * scale), color("#ffd56a", header_alpha), Qt.AlignmentFlag.AlignCenter)

        # --- Close button (circle) ---
        close = layout.close_button
        commands.rect(
            close,
            close.height() * 0.5,
            color("#ffffff", 0.10 * header_alpha),
        )
        commands.text(close, "×", self.font("poppins_bold", 15.0 * scale), color("#ffffff", header_alpha), Qt.AlignmentFlag.AlignCenter)
        if self.economy_visible and header_alpha >= 0.38:
            self.add_hotspot(close, "economy_close", tooltip="关闭经济工作区 [Esc]")

        if content_alpha < 0.02 or layout.body_clip.isEmpty():
            return commands

        def body_clip(rect: QRectF) -> QRectF:
            return QRectF(rect).intersected(layout.body_clip)

        strip = layout.status_strip
        status_gap = 8.0
        source_widths = (304.0, 152.0, 152.0)
        source_total = sum(source_widths) + status_gap * 2.0
        status_scale = min(1.0, strip.width() / max(1.0, source_total))
        status_widths = tuple(value * status_scale for value in source_widths)
        status_total = sum(status_widths) + status_gap * 2.0
        status_left = strip.center().x() - status_total * 0.5
        status_tiles = (
            QRectF(status_left, strip.top(), status_widths[0], strip.height()),
            QRectF(
                status_left + status_widths[0] + status_gap,
                strip.top(),
                status_widths[1],
                strip.height(),
            ),
            QRectF(
                status_left + status_widths[0] + status_gap * 2.0 + status_widths[1],
                strip.top(),
                status_widths[2],
                strip.height(),
            ),
        )
        for status_tile in status_tiles:
            add_control_center_tile(
                status_tile,
                category_alpha,
                material=LensMaterial.REGULAR,
                clip=layout.body_clip,
            )
        tab_bar = layout.tab_bar
        tab_gap = 8.0
        tab_width = 0.0
        tab_rects: tuple[QRectF, ...] = ()
        if layout.three_column:
            add_control_center_tile(
                layout.category_pane,
                category_alpha,
                material=LensMaterial.STRONG,
                clip=layout.body_clip,
            )
        else:
            tab_count = max(1, len(categories))
            tab_width = min(
                152.0,
                max(1.0, (tab_bar.width() - tab_gap * (tab_count - 1)) / tab_count),
            )
            tabs_total = tab_width * tab_count + tab_gap * (tab_count - 1)
            tabs_left = tab_bar.center().x() - tabs_total * 0.5
            tab_rects = tuple(
                QRectF(
                    tabs_left + index * (tab_width + tab_gap),
                    tab_bar.top(),
                    tab_width,
                    tab_bar.height(),
                )
                for index in range(tab_count)
            )
            for tab_rect in tab_rects:
                add_control_center_tile(
                    tab_rect,
                    layout.tab_alpha,
                    material=LensMaterial.STRONG,
                    clip=layout.body_clip,
                )

        # --- Status strip (compact gold/HP/ammo info) ---
        strip_clip = body_clip(strip)
        if not strip_clip.isEmpty():
            pad = 14.0
            economy_ratio = context.gold / max(1.0, float(max(context.total_gold, context.gold)))
            hp_ratio = context.current_health / max(1.0, float(context.max_health))
            ammo_ratio = context.current_ammo / max(1.0, float(context.ammo_capacity or context.current_ammo or 1))
            pending_cost = self.economy_bridge.latest.request.cost if self.economy_bridge.latest and self.economy_bridge.latest.status == "pending" else 0
            gold_tile, hp_tile, ammo_tile = status_tiles
            commands.text(
                QRectF(gold_tile.left() + pad, gold_tile.top() + 7.0, gold_tile.width() - pad * 2.0, 20.0),
                economy_text("{gold} G", chinese_enabled(self.registry), gold=context.gold), self.font("poppins_bold", 12.0 * scale), color("#ffd56a", category_alpha), clip=strip_clip,
            )
            commands.text(
                QRectF(gold_tile.left() + pad, gold_tile.top() + 31.0, gold_tile.width() - pad * 2.0, 15.0),
                f"累计 {context.total_gold} · 待扣 {pending_cost}", self.font("poppins_medium", 7.0 * scale), color("#9aafc0", 0.88 * category_alpha), clip=strip_clip,
            )
            for tile, (label, value, ratio, accent_hex) in zip(
                (hp_tile, ammo_tile),
                (
                    ("HP", f"{context.current_health}/{context.max_health}", hp_ratio, "#64dda1"),
                    ("AMMO", f"{context.current_ammo}/{context.ammo_capacity}", ammo_ratio, "#64baff"),
                ),
            ):
                commands.text(
                    QRectF(tile.left() + pad, tile.top() + 8.0, tile.width() - pad * 2.0, 14.0),
                    economy_text(label, chinese_enabled(self.registry)), self.font("poppins_bold", 6.6 * scale), color("#aebcc8", 0.82 * category_alpha), clip=strip_clip,
                )
                commands.text(
                    QRectF(tile.left() + pad, tile.top() + 7.0, tile.width() - pad * 2.0, 15.0),
                    value, self.font("poppins_medium", 7.2 * scale), color("#ffffff", 0.90 * category_alpha),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    strip_clip,
                )
                bar = QRectF(tile.left() + pad, tile.top() + 34.0, tile.width() - pad * 2.0, 4.0)
                commands.rect(bar, 2.0, color("#ffffff", 0.08 * category_alpha), clip=strip_clip)
                commands.rect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, ratio)), bar.height()), 2.0, color(accent_hex, category_alpha), clip=strip_clip)

        # --- Category navigation: bottom tabs at 720/900p; a true third
        # column at 1080p+ as required by the economy interaction document. ---
        tab_bar = layout.tab_bar
        tab_clip = body_clip(tab_bar)
        tab_alpha = layout.tab_alpha
        if layout.three_column:
            category_clip = body_clip(layout.category_pane)
            row_h = 48.0
            row_gap = 8.0
            commands.text(
                QRectF(layout.category_pane.left() + 16.0, layout.category_pane.top() + 12.0, layout.category_pane.width() - 32.0, 24.0),
                "操作分类",
                self.font("poppins_bold", 10.0 * scale),
                color("#ffffff", category_alpha),
                clip=category_clip,
            )
            for index, key in enumerate(categories):
                rect = QRectF(
                    layout.category_pane.left() + 10.0,
                    layout.category_pane.top() + 46.0 + index * (row_h + row_gap),
                    layout.category_pane.width() - 20.0,
                    row_h,
                )
                active = key == self.economy_category
                if active:
                    commands.rect(rect, 18.0, color("#0088ff", 0.84 * category_alpha), clip=category_clip)
                commands.text(
                    rect.adjusted(14.0, 0.0, -12.0, 0.0),
                    CATEGORY_TITLES.get(key, key),
                    self.font("poppins_bold", 9.0 * scale),
                    color("#ffffff", category_alpha) if active else color("#d6e2ec", 0.80 * category_alpha),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    category_clip,
                )
                if self.economy_visible and layout.interactive:
                    self.add_hotspot(rect.intersected(category_clip), "economy_category", key)
        elif not tab_clip.isEmpty() and tab_alpha > 0.01:
            selected_category_index = float(categories.index(self.economy_category))
            animated_category_index = self.anim.value(
                "economy.category.selection",
                selected_category_index,
                self.anim_duration(0.22),
                Easings.ease_out_expo,
                initial=selected_category_index,
            )
            indicator = QRectF(
                tab_rects[0].left() + animated_category_index * (tab_width + tab_gap) + 6.0,
                tab_bar.top() + 6.0,
                max(1.0, tab_width - 12.0),
                tab_bar.height() - 12.0,
            )
            if indicator.intersects(tab_clip):
                commands.rect(
                    indicator,
                    indicator.height() * 0.5,
                    color("#0088ff", 0.84 * tab_alpha),
                    clip=tab_clip,
                )
            for rect, key in zip(tab_rects, categories):
                if not rect.intersects(tab_clip):
                    continue
                active = key == self.economy_category
                commands.text(
                    rect,
                    CATEGORY_TITLES.get(key, key), self.font("poppins_bold", 9.0 * scale),
                    color("#ffffff", tab_alpha) if active else color("#d6e2ec", 0.80 * tab_alpha),
                    Qt.AlignmentFlag.AlignCenter,
                    tab_clip,
                )
                if self.economy_visible and layout.interactive:
                    self.add_hotspot(rect, "economy_category", key)

        # --- Offers pane ---
        offers_pane = layout.offers_pane.translated(0.0, layout.offers_offset)
        offers_clip = body_clip(offers_pane)
        list_pad = 14.0
        viewport = layout.offers_viewport.translated(0.0, layout.offers_offset)
        viewport_clip = body_clip(viewport)
        card_h = 68.0
        card_gap = 8.0
        card_w = min(520.0, viewport.width())
        card_left = viewport.center().x() - card_w * 0.5
        commands.text(
            QRectF(card_left, offers_pane.top() + 12.0, card_w, 24.0),
            f"可选操作 · {CATEGORY_TITLES.get(self.economy_category, self.economy_category)}",
            self.font("poppins_bold", 10.5 * scale), color("#ffffff", offers_alpha), clip=offers_clip,
        )
        self.economy_offers_scroll.set_bounds(max(0.0, len(offers) * (card_h + card_gap) - card_gap - viewport.height()))
        scroll = self.economy_offers_scroll.position
        if selected is not None:
            selected_offer_index = next(
                (index for index, offer in enumerate(offers) if offer.key == selected.key),
                0,
            )
            animated_offer_index = self.anim.value(
                "economy.offer.selection",
                float(selected_offer_index),
                self.anim_duration(0.20),
                Easings.ease_out_expo,
                initial=float(selected_offer_index),
            )
            selection_rect = QRectF(
                card_left,
                viewport.top() + animated_offer_index * (card_h + card_gap) - scroll,
                card_w,
                card_h,
            )
            commands.rect(
                selection_rect,
                min(34.0, selection_rect.height() * 0.5),
                color("#64e0c1", 0.10 * offers_alpha),
                color("#64e0c1", 0.48 * offers_alpha),
                1.0,
                clip=viewport_clip,
            )
        for index, offer in enumerate(offers):
            rect = QRectF(card_left, viewport.top() + index * (card_h + card_gap) - scroll, card_w, card_h)
            if not rect.intersects(viewport_clip):
                continue
            add_control_center_tile(
                rect,
                offers_alpha,
                material=LensMaterial.REGULAR,
                clip=viewport_clip,
            )
            active = selected is not None and offer.key == selected.key
            hovered = rect.contains(self.hover_point)
            hover = self.anim.value(
                f"economy.offer.hover.{offer.key}",
                1.0 if hovered or active else 0.0,
                self.anim_duration(BUY_HOVER_SECONDS if buy_enabled(self) else 0.14),
                _css_ease_in_out if buy_enabled(self) else Easings.ease_out_expo,
            )
            draw_rect = rect if buy_enabled(self) else rect.translated(0.0, -1.4 * hover)
            append_buy_feedback(commands, self, offer.key, rect, viewport_clip,
                                hover, offers_alpha, time.perf_counter())
            title_inset = 48.0 if buy_enabled(self) else 18.0
            title_color = color("#ffffff", offers_alpha) if offer.enabled else color("#9aa3ac", 0.72 * offers_alpha)
            commands.text(
                QRectF(draw_rect.left() + title_inset, draw_rect.top() + 8.0, draw_rect.width() - title_inset - 92.0, 24.0),
                offer.short_title, self.font("poppins_bold", 10.5 * scale), title_color,
                clip=viewport_clip,
            )
            price = "仅状态" if offer.status_only else f"{offer.cost} 金币"
            commands.text(
                QRectF(draw_rect.left() + 18.0, draw_rect.top() + 8.0, draw_rect.width() - 32.0, 24.0),
                price, self.font("poppins_bold", 9.5 * scale),
                color("#ffd56a", offers_alpha) if offer.enabled else color("#b8a878", 0.55 * offers_alpha),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                clip=viewport_clip,
            )
            secondary = offer.reason if not offer.enabled else offer.description
            commands.text(
                QRectF(draw_rect.left() + title_inset, draw_rect.top() + 32.0, draw_rect.width() - title_inset - 14.0, 20.0),
                secondary, self.font("poppins_medium", 7.8 * scale),
                color("#b8c8d8", (0.90 if offer.enabled else 0.55) * offers_alpha),
                clip=viewport_clip,
            )
            if self.economy_visible and layout.interactive:
                self.add_hotspot(rect, "economy_offer", offer.key, tooltip=offer.reason or offer.description)

        # --- Detail pane ---
        detail = layout.detail_pane.translated(0.0, layout.detail_offset)
        detail_clip = body_clip(detail)
        detail_pad = 16.0
        detail_vp = layout.detail_viewport.translated(0.0, layout.detail_offset)
        detail_vp_clip = body_clip(detail_vp)
        # Compute detail content height for scroll bounds
        detail_content_h = 142.0  # selected info module
        detail_content_h += reload_detail_height(self)
        history = list(reversed(self.economy_bridge.history[-3:]))
        detail_content_h += 24.0 + max(1, len(history)) * 52.0 if history else 52.0
        self.economy_detail_scroll.set_bounds(max(0.0, detail_content_h - detail_vp.height()))
        detail_scroll = self.economy_detail_scroll.position
        summary_rect = QRectF(
            detail_vp.left(),
            detail_vp.top() - detail_scroll,
            detail_vp.width(),
            116.0,
        )
        if selected is not None:
            add_control_center_tile(
                summary_rect,
                detail_alpha,
                material=LensMaterial.REGULAR,
                clip=detail_vp_clip,
            )
            commands.text(
                QRectF(summary_rect.left() + detail_pad, summary_rect.top() + 8.0, summary_rect.width() - detail_pad * 2, 26.0),
                selected.title, self.font("poppins_bold", 13.5 * scale), color("#ffffff", detail_alpha),
                clip=detail_vp_clip,
            )
            tag = "预计价格" if selected.estimated else ("模拟请求" if context.mock_mode else "裁判系统")
            commands.text(
                QRectF(summary_rect.left() + detail_pad, summary_rect.top() + 36.0, summary_rect.width() - detail_pad * 2, 20.0),
                f"{selected.unit}  ·  {selected.cost} 金币  ·  {tag}",
                self.font("poppins_medium", 9.0 * scale), color("#ffd56a", detail_alpha),
                clip=detail_vp_clip,
            )
            commands.text(
                QRectF(summary_rect.left() + detail_pad, summary_rect.top() + 60.0, summary_rect.width() - detail_pad * 2, 28.0),
                selected.description, self.font("poppins_medium", 8.4 * scale), color("#d0dce8", detail_alpha),
                clip=detail_vp_clip,
            )
            state_text = selected.reason if not selected.enabled else "可以购买"
            state_color = color("#ffb06f", detail_alpha) if not selected.enabled else color("#70e0ae", detail_alpha)
            commands.text(
                QRectF(summary_rect.left() + detail_pad, summary_rect.top() + 90.0, summary_rect.width() - detail_pad * 2, 18.0),
                state_text, self.font("poppins_bold", 9.5 * scale), state_color,
                clip=detail_vp_clip,
            )

        # Transaction history
        history_top = detail_vp.top() + 128.0 - detail_scroll
        append_reload_details(self, commands,
                              QRectF(detail_vp.left(), history_top, detail_vp.width(), reload_detail_height(self)),
                              detail_vp_clip, detail_alpha, interactive=self.economy_visible and layout.interactive)
        history_top += reload_detail_height(self)
        button = layout.action_button.translated(0.0, layout.detail_offset)
        if history_top + 36.0 < detail_vp_clip.bottom():
            commands.text(
                QRectF(detail.left() + detail_pad, history_top, detail.width() - detail_pad * 2, 18.0),
                "最近交易", self.font("poppins_bold", 8.6 * scale), color("#8fa3b5", detail_alpha),
                clip=detail_vp_clip,
            )
            if not history:
                empty_rect = QRectF(
                    detail_vp.left(),
                    history_top + 22.0,
                    detail_vp.width(),
                    44.0,
                )
                add_control_center_tile(
                    empty_rect,
                    detail_alpha,
                    material=LensMaterial.REGULAR,
                    clip=detail_vp_clip,
                )
                commands.text(
                    empty_rect.adjusted(detail_pad, 0.0, -detail_pad, 0.0),
                    "暂无记录", self.font("poppins_medium", 8.0 * scale), color("#7a8c9c", detail_alpha),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    detail_vp_clip,
                )
            for index, transaction in enumerate(history):
                y = history_top + 22.0 + index * 52.0
                if y + 44.0 > detail_vp_clip.bottom():
                    break
                history_rect = QRectF(detail_vp.left(), y, detail_vp.width(), 44.0)
                add_control_center_tile(
                    history_rect,
                    detail_alpha,
                    material=LensMaterial.REGULAR,
                    clip=detail_vp_clip,
                )
                label = TRANSACTION_LABELS.get(transaction.status, transaction.status)
                status_color = (
                    color("#70e0ae", detail_alpha) if transaction.status == "succeeded"
                    else color("#ffb96b", detail_alpha) if transaction.status in ("rejected", "timed_out")
                    else color("#72bfff", detail_alpha)
                )
                commands.text(
                    QRectF(history_rect.left() + detail_pad, y + 6.0, history_rect.width() - detail_pad * 2, 15.0),
                    f"{label} · {transaction.offer.short_title}",
                    self.font("poppins_bold", 8.2 * scale), status_color,
                    clip=detail_vp_clip,
                )
                commands.text(
                    QRectF(history_rect.left() + detail_pad, y + 22.0, history_rect.width() - detail_pad * 2, 13.0),
                    transaction.message, self.font("poppins_medium", 7.4 * scale), color("#a8bac8", 0.90 * detail_alpha),
                    clip=detail_vp_clip,
                )

        # --- Action button ---
        now = time.perf_counter()
        pending = self.economy_bridge.latest is not None and self.economy_bridge.latest.status == "pending"
        # Availability can change in the same tick that a held respawn request
        # succeeds.  Keep progress defined across every branch so the first
        # post-response GPU frame cannot abort and expose only the camera.
        hold_progress = 0.0
        if selected is None:
            button_text = "请先选择商品"
            button_enabled = False
            action = "economy_confirm"
        elif pending:
            button_text = "请求处理中…"
            button_enabled = False
            action = "economy_confirm"
        elif not selected.enabled or selected.status_only:
            button_text = selected.reason or "当前不可用"
            button_enabled = False
            action = "economy_confirm"
        elif selected.confirmation == "hold":
            hold_progress = (
                max(0.0, min(1.0, (now - self.economy_hold_started) / 0.60))
                if self.economy_hold_key == selected.key else 0.0
            )
            button_text = "按住 0.6 秒确认" if hold_progress <= 0.0 else f"确认中 {round(hold_progress * 100)}%"
            button_enabled = True
            action = "economy_confirm_hold"
        else:
            armed = self.economy_armed_key == selected.key and now <= self.economy_armed_until
            if armed:
                remain = max(0.0, self.economy_armed_until - now)
                button_text = f"再点一次确认（{remain:.1f}s）"
            else:
                button_text = f"确认购买 · {selected.cost} 金币"
            button_enabled = True
            action = "economy_confirm"

        # Press feedback only changes the dynamic geometry. It never rebuilds
        # the combined backdrop, text atlas, or static workspace layout.
        press = self.liquid_press_amount(button)
        hover = self.anim.value(
            "economy.action.hover",
            1.0 if button.contains(self.hover_point) and button_enabled else 0.0,
            self.anim_duration(0.14),
            Easings.ease_out_expo,
        )
        inset = 1.55 * press
        button_draw = button.adjusted(inset, inset, -inset, -inset).translated(0.0, -0.9 * hover)
        button_draw = button_draw.intersected(detail_clip)
        if button_draw.isEmpty():
            return commands
        btn_r = button_draw.height() * 0.5
        if button_enabled:
            fill_alpha = (0.78 + 0.10 * hover - 0.08 * press) * detail_alpha
            button_fill = color("#0088ff", fill_alpha)
        else:
            button_fill = color("#ffffff", 0.14 * detail_alpha)
        commands.rect(
            button_draw,
            btn_r,
            button_fill,
            clip=detail_clip,
        )
        if selected is not None and selected.confirmation == "hold" and hold_progress > 0.0:
            progress_track = QRectF(
                button_draw.left() + 18.0,
                button_draw.bottom() - 8.0,
                max(0.0, button_draw.width() - 36.0),
                2.0,
            )
            commands.rect(progress_track, 1.0, color("#ffffff", 0.18 * detail_alpha), clip=detail_clip)
            commands.rect(
                QRectF(
                    progress_track.left(), progress_track.top(),
                    progress_track.width() * hold_progress, progress_track.height(),
                ),
                1.0,
                color("#ffd56a", 0.96 * detail_alpha), clip=detail_clip,
            )
        commands.text(
            button_draw, button_text, self.font("poppins_bold", 11.0 * scale),
            color("#ffffff", detail_alpha) if button_enabled else color("#c5ccd3", 0.72 * detail_alpha),
            Qt.AlignmentFlag.AlignCenter, detail_clip,
        )
        if selected is not None and button_enabled and self.economy_visible and layout.interactive:
            self.add_hotspot(button, action, selected.key, tooltip=button_text)

        return commands

    def start_economy_qualification_test(self) -> None:
        """Authorize exactly one supervised economy command for 30 seconds.

        This does not mark the capability PASS. The operator still has to use
        the normal Economy workspace, observe authoritative local-state
        confirmation, and then record the lifecycle result.
        """

        if self.scenario_manager.current.key != "OfficialEvent":
            self.toast("Economy qualification requires OfficialEvent")
            return
        if self.backend.qualification.session is None:
            self.toast("Create a qualification session first")
            return
        token = self.backend.begin_qualification({"economy"}, ttl_s=30.0)
        self._economy_qualification_token = token.value
        self.backend.field_log.emit(
            "economy_qualification_window",
            expires_at=token.expires_at,
            session_id=self.backend.qualification.session.session_id,
        )
        self.toast("Economy test window active for 30 s; send one supervised request")


_QUALNAME_PINNED_MEMBERS = (
    EconomyMixin.draw_economy_overlay_legacy,
    EconomyMixin.economy_scale_steps,
    EconomyMixin.economy_ui_scale,
    EconomyMixin.economy_uses_mock_transport,
    EconomyMixin.send_economy_request,
    EconomyMixin.economy_offers,
    EconomyMixin.economy_categories,
    EconomyMixin.economy_selected_offer,
    EconomyMixin._finalize_economy_restore,
    EconomyMixin.open_economy_workspace,
    EconomyMixin.close_economy_workspace,
    EconomyMixin.select_economy_offer,
    EconomyMixin.submit_economy_offer,
    EconomyMixin.activate_economy_offer,
    EconomyMixin.begin_economy_hold,
    EconomyMixin.finish_economy_hold,
    EconomyMixin._economy_glass_row,
    EconomyMixin._economy_dim_around,
    EconomyMixin._economy_island_well,
    EconomyMixin.draw_economy_overlay_compat,
    EconomyMixin.build_gpu_economy_workspace,
    EconomyMixin.start_economy_qualification_test,
)

for _fn in _QUALNAME_PINNED_MEMBERS:
    _fn.__qualname__ = f"PolarRMWindow.{_fn.__name__}"
del _fn, _QUALNAME_PINNED_MEMBERS
