"""Hero deployment/lob interface using the client's existing glass language.

The operator workflow is still the rule-level state machine: deployment is an
explicit, double-confirmed request and official ``DeployModeStatusSync`` is
authoritative.  The presentation deliberately reuses the same two primitives
already used by the battle HUD and economy workspace:

* an Apple-style top Dynamic Island that grows into the working surface;
* AndroidLiquidGlass lenses for the root, telemetry cards and controls.

No opaque, sci-fi themed "second application" is introduced here.  The
renderer accepts the owning window's glass/text/icon callbacks so GPU
refraction, press feedback, font protection and animation stay identical to
the rest of the client, while retaining a QPainter fallback for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from .economy_workspace import EconomyIslandState


GlassDrawer = Callable[..., None]
TextDrawer = Callable[..., None]
IslandIconDrawer = Callable[..., None]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _smoothstep(value: float) -> float:
    value = _clamp(value)
    return value * value * (3.0 - 2.0 * value)


def _lerp_rect(start: QRectF, end: QRectF, amount: float) -> QRectF:
    amount = _clamp(amount)
    return QRectF(
        start.x() + (end.x() - start.x()) * amount,
        start.y() + (end.y() - start.y()) * amount,
        start.width() + (end.width() - start.width()) * amount,
        start.height() + (end.height() - start.height()) * amount,
    )


def _alpha(colour: QColor, amount: float) -> QColor:
    result = QColor(colour)
    result.setAlpha(round(_clamp(amount) * 255.0))
    return result


@dataclass(frozen=True, slots=True)
class HeroDeployHitTarget:
    rect: QRectF
    action: str
    enabled: bool = True
    tooltip: str = ""


@dataclass(frozen=True, slots=True)
class HeroDeployLayout:
    collapsed: QRectF
    target_panel: QRectF
    panel: QRectF
    header: QRectF
    status_chip: QRectF
    close_button: QRectF
    trajectory: QRectF
    telemetry: QRectF
    rule_card: QRectF
    buttons: tuple[QRectF, ...]
    body_clip: QRectF
    scale: float
    root_radius: float
    island_progress: float
    body_progress: float
    header_alpha: float
    content_alpha: float
    interactive: bool

    @classmethod
    def for_viewport(
        cls,
        width: int,
        height: int,
        progress: float = 1.0,
    ) -> "HeroDeployLayout":
        width_f = max(1.0, float(width))
        height_f = max(1.0, float(height))
        raw_progress = _clamp(progress, -0.02, 1.12)
        progress = _clamp(raw_progress)
        scale = _clamp(min(width_f / 1280.0, height_f / 720.0), 0.72, 1.45)

        margin_x = max(14.0, 24.0 * scale)
        top_margin = max(10.0, 14.0 * scale)
        bottom_margin = max(14.0, 20.0 * scale)
        target_w = min(1140.0 * scale, width_f - margin_x * 2.0)
        target_h = min(680.0 * scale, height_f - top_margin - bottom_margin)
        target_w = max(320.0, target_w)
        target_h = max(300.0, target_h)
        target = QRectF(
            (width_f - target_w) * 0.5,
            top_margin,
            target_w,
            target_h,
        )

        collapsed_w = min(target_w, max(300.0 * scale, min(460.0 * scale, width_f * 0.36)))
        collapsed_h = max(38.0, 46.0 * scale)
        collapsed = QRectF(
            (width_f - collapsed_w) * 0.5,
            top_margin,
            collapsed_w,
            collapsed_h,
        )
        island_target_w = min(target_w, max(collapsed_w, 610.0 * scale))
        island_target = QRectF(
            (width_f - island_target_w) * 0.5,
            top_margin,
            island_target_w,
            max(collapsed_h, 76.0 * scale),
        )

        # Match the economy Control Center's ordering: establish the island,
        # then let that exact material grow down into a sheet.
        island_progress = _smoothstep(progress / 0.24)
        body_progress = _smoothstep((progress - 0.18) / 0.82)
        island = _lerp_rect(collapsed, island_target, island_progress)
        panel = _lerp_rect(island, target, body_progress)
        root_radius = min(
            panel.height() * 0.5,
            island.height() * 0.5 + (28.0 * scale - island.height() * 0.5) * body_progress,
        )
        header_alpha = _clamp(progress * progress)
        content_alpha = _smoothstep((body_progress - 0.28) / 0.54)

        header_margin = max(8.0, 12.0 * scale)
        header_h = min(panel.height() - header_margin * 2.0, max(32.0, 52.0 * scale))
        header = QRectF(
            panel.left() + header_margin,
            panel.top() + header_margin,
            max(20.0, panel.width() - header_margin * 2.0),
            max(20.0, header_h),
        )
        close_size = max(28.0, 34.0 * scale)
        close_button = QRectF(
            header.right() - close_size,
            header.center().y() - close_size * 0.5,
            close_size,
            close_size,
        )
        chip_w = min(max(104.0, 156.0 * scale), max(104.0, header.width() * 0.32))
        status_chip = QRectF(
            close_button.left() - chip_w - 8.0 * scale,
            header.center().y() - close_size * 0.5,
            chip_w,
            close_size,
        )

        # Working controls retain their final geometry and are revealed by the
        # growing root.  This avoids compressed text/cards during the morph.
        inner = target.adjusted(
            18.0 * scale,
            72.0 * scale,
            -18.0 * scale,
            -18.0 * scale,
        )
        gap = max(8.0, 12.0 * scale)
        button_h = max(34.0, 42.0 * scale)
        button_gap = max(6.0, 8.0 * scale)
        buttons_top = inner.bottom() - button_h * 2.0 - button_gap
        content = QRectF(
            inner.left(),
            inner.top(),
            inner.width(),
            max(80.0, buttons_top - inner.top() - gap),
        )
        left_ratio = 0.60 if target.width() >= 900.0 else 0.56
        left_w = max(180.0, content.width() * left_ratio - gap * 0.5)
        trajectory = QRectF(content.left(), content.top(), left_w, content.height())
        right = QRectF(
            trajectory.right() + gap,
            content.top(),
            max(120.0, content.right() - trajectory.right() - gap),
            content.height(),
        )
        telemetry_h = max(92.0, right.height() * 0.57)
        telemetry = QRectF(right.left(), right.top(), right.width(), min(right.height(), telemetry_h))
        rule_card = QRectF(
            right.left(),
            telemetry.bottom() + gap,
            right.width(),
            max(0.0, right.bottom() - telemetry.bottom() - gap),
        )
        button_w = (inner.width() - button_gap * 2.0) / 3.0
        buttons = tuple(
            QRectF(
                inner.left() + (index % 3) * (button_w + button_gap),
                buttons_top + (index // 3) * (button_h + button_gap),
                button_w,
                button_h,
            )
            for index in range(6)
        )
        final_body = QRectF(
            target.left(),
            target.top() + 64.0 * scale,
            target.width(),
            max(0.0, target.height() - 64.0 * scale),
        )
        body_clip = final_body.intersected(panel.adjusted(1.0, 1.0, -1.0, -1.0))
        return cls(
            collapsed=collapsed,
            target_panel=target,
            panel=panel,
            header=header,
            status_chip=status_chip,
            close_button=close_button,
            trajectory=trajectory,
            telemetry=telemetry,
            rule_card=rule_card,
            buttons=buttons,
            body_clip=body_clip,
            scale=scale,
            root_radius=max(4.0, root_radius),
            island_progress=island_progress,
            body_progress=body_progress,
            header_alpha=header_alpha,
            content_alpha=content_alpha,
            interactive=bool(progress >= 0.82 and body_progress >= 0.72),
        )


class HeroDeployInterfaceState:
    CONFIRM_WINDOW_S = 3.0
    RULE_DELAY_S = 2.0
    STATUS_TIMEOUT_S = 5.0

    def __init__(self) -> None:
        self.visible = False
        self.opened_at = 0.0
        self.confirm_mode: int | None = None
        self.confirm_until = 0.0
        self.pending_mode: int | None = None
        self.pending_at = 0.0
        self.pending_mock = False
        self.last_error = ""
        self.last_ack_at = 0.0
        # Reuse the exact reversible spring used by the existing iOS-style
        # economy Control Center instead of inventing another animation curve.
        self.presentation = EconomyIslandState()

    @property
    def progress(self) -> float:
        return _clamp(self.presentation.progress, -0.02, 1.12)

    @property
    def render_visible(self) -> bool:
        return bool(self.visible or self.presentation.progress > 0.001 or self.presentation.active)

    @property
    def active(self) -> bool:
        return bool(self.presentation.active or self.render_visible)

    def update_presentation(self, now: float | None = None) -> float:
        return self.presentation.update(now=now)

    def open(self, now: float) -> None:
        self.visible = True
        self.opened_at = float(now)
        self.last_error = ""
        self.presentation.set_target(1.0, 0.62, now=float(now))

    def close(self, now: float | None = None, *, immediate: bool = False) -> None:
        self.visible = False
        self.confirm_mode = None
        self.confirm_until = 0.0
        if immediate:
            self.presentation.target = 0.0
            self.presentation.progress = 0.0
            self.presentation.velocity = 0.0
        else:
            self.presentation.set_target(0.0, 0.48, now=now)

    def arm_confirmation(self, mode: int, now: float) -> bool:
        mode = 1 if int(mode) else 0
        now = float(now)
        if self.confirm_mode == mode and now <= self.confirm_until:
            self.confirm_mode = None
            self.confirm_until = 0.0
            return True
        self.confirm_mode = mode
        self.confirm_until = now + self.CONFIRM_WINDOW_S
        return False

    def begin_request(self, mode: int, now: float, *, mock: bool) -> None:
        self.pending_mode = 1 if int(mode) else 0
        self.pending_at = float(now)
        self.pending_mock = bool(mock)
        self.last_error = ""

    def cancel_request(self, reason: str) -> None:
        self.pending_mode = None
        self.pending_at = 0.0
        self.pending_mock = False
        self.last_error = str(reason)

    def sync(self, official_status: int, now: float) -> int | None:
        """Advance state and return a mock-only authoritative status change."""

        now = float(now)
        official_status = 1 if int(official_status) else 0
        if self.confirm_mode is not None and now > self.confirm_until:
            self.confirm_mode = None
            self.confirm_until = 0.0
        if self.pending_mode is None:
            return None
        if official_status == self.pending_mode and not self.pending_mock:
            self.pending_mode = None
            self.pending_at = 0.0
            self.last_ack_at = now
            self.last_error = ""
            return None
        elapsed = max(0.0, now - self.pending_at)
        if self.pending_mock and elapsed >= self.RULE_DELAY_S:
            value = self.pending_mode
            self.pending_mode = None
            self.pending_at = 0.0
            self.pending_mock = False
            self.last_ack_at = now
            return value
        if elapsed >= self.STATUS_TIMEOUT_S:
            self.cancel_request("DeployModeStatusSync timeout")
        return None

    def countdown(self, now: float) -> float:
        if self.pending_mode is None:
            return 0.0
        return max(0.0, self.RULE_DELAY_S - (float(now) - self.pending_at))

    def phase(self, status: int, now: float) -> str:
        if self.pending_mode == 1:
            return f"ENTERING {self.countdown(now):.1f}s"
        if self.pending_mode == 0:
            return f"EXITING {self.countdown(now):.1f}s"
        return "DEPLOYED" if int(status) == 1 else "MOBILE"


class HeroDeployRenderer:
    """Responsive Dynamic-Island-to-Liquid-Glass Hero control surface."""

    def layout(self, width: int, height: int, progress: float = 1.0) -> HeroDeployLayout:
        return HeroDeployLayout.for_viewport(width, height, progress)

    @staticmethod
    def _font(font_factory: Callable[[str, float], QFont] | None, key: str, size: float) -> QFont:
        if font_factory is not None:
            return font_factory(key, size)
        font = QFont("Segoe UI")
        font.setPointSizeF(size)
        return font

    @staticmethod
    def _text(
        p: QPainter,
        rect: QRectF,
        text: str,
        font: QFont,
        colour: QColor,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        text_drawer: TextDrawer | None = None,
    ) -> None:
        if rect.isEmpty() or not text:
            return
        if text_drawer is not None:
            text_drawer(p, rect, str(text), font, colour, align)
            return
        p.setFont(font)
        p.setPen(colour)
        elided = QFontMetricsF(font).elidedText(
            str(text),
            Qt.TextElideMode.ElideRight,
            max(1.0, rect.width()),
        )
        p.drawText(rect, int(align), elided)

    @staticmethod
    def _rounded(
        p: QPainter,
        rect: QRectF,
        radius: float,
        fill: QColor,
        outline: QColor | None = None,
        width: float = 1.0,
    ) -> None:
        p.setBrush(fill)
        p.setPen(QPen(outline, width) if outline is not None else Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

    def _glass(
        self,
        p: QPainter,
        rect: QRectF,
        radius: float,
        glass_drawer: GlassDrawer | None,
        *,
        surface: str,
        hover: float = 0.0,
        clip_rect: QRectF | None = None,
    ) -> None:
        if rect.isEmpty():
            return
        if glass_drawer is not None:
            glass_drawer(
                p,
                rect,
                radius,
                surface=surface,
                hover=hover,
                clip_rect=clip_rect,
            )
        else:
            fill_alpha = 0.73 if surface in {"ProminentGlass", "LensIsland"} else 0.48
            self._rounded(
                p,
                rect,
                radius,
                _alpha(QColor("#080b10"), fill_alpha),
                _alpha(QColor("#ffffff"), 0.13),
            )

    def draw(
        self,
        p: QPainter,
        width: int,
        height: int,
        *,
        state: Any,
        module: Any,
        interface: HeroDeployInterfaceState,
        solution: Any,
        readiness: Any,
        now: float,
        font_factory: Callable[[str, float], QFont] | None = None,
        glass_drawer: GlassDrawer | None = None,
        text_drawer: TextDrawer | None = None,
        island_icon_drawer: IslandIconDrawer | None = None,
        pointer: QPointF | None = None,
    ) -> tuple[HeroDeployHitTarget, ...]:
        # Presentation is advanced exactly once by PolarClientWindow.on_tick.
        # Direct tests/tools explicitly advance the state before drawing.
        layout = self.layout(width, height, interface.progress)
        progress = _clamp(interface.progress)
        if progress <= 0.001 and not interface.visible:
            return ()

        scale = layout.scale
        status = int(getattr(state, "deploy_mode", 0))
        deployed = status == 1
        phase = interface.phase(status, now)
        ready = bool(getattr(readiness, "ready", False))
        reachable = bool(getattr(solution, "reachable", False))
        pending = interface.pending_mode is not None
        phase_colour = QColor("#62e6ad") if deployed else QColor("#ffd36b") if pending else QColor("#7bd8ff")
        icon_kind = "success" if deployed else "warning" if pending or not ready else "module"
        pointer = pointer or QPointF(-10000.0, -10000.0)

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # Same restrained dim amount as the Control Center.  When deployed the
        # backdrop is exclusively the Native 0x0310 compressed frame.
        p.fillRect(QRectF(0.0, 0.0, width, height), _alpha(QColor("#000000"), 0.38 * layout.body_progress))

        p.save()
        p.setOpacity(max(0.05, layout.header_alpha))
        root_surface = "LensIsland" if layout.body_progress < 0.08 else "ProminentGlass"
        self._glass(
            p,
            layout.panel,
            layout.root_radius,
            glass_drawer,
            surface=root_surface,
            hover=0.0,
        )
        # AndroidLiquidGlass supplies refraction; this neutral five-percent
        # container tint is the same readability layer used by Control Center.
        self._rounded(
            p,
            layout.panel,
            layout.root_radius,
            _alpha(QColor("#000000"), 0.05),
            _alpha(QColor("#ffffff"), 0.11),
            max(0.7, 0.85 * scale),
        )
        p.restore()

        root_clip = QPainterPath()
        root_clip.addRoundedRect(layout.panel, layout.root_radius, layout.root_radius)
        p.setClipPath(root_clip, Qt.ClipOperation.IntersectClip)

        # Dynamic Island header.  It remains readable before the body starts
        # revealing and uses the existing animated island icon renderer.
        p.save()
        p.setOpacity(layout.header_alpha)
        icon_size = min(layout.header.height(), max(24.0, 34.0 * scale))
        icon_rect = QRectF(
            layout.header.left() + 4.0 * scale,
            layout.header.center().y() - icon_size * 0.5,
            icon_size,
            icon_size,
        )
        if island_icon_drawer is not None:
            island_icon_drawer(p, icon_rect, icon_kind, phase_colour, max(0.25, progress))
        else:
            self._rounded(p, icon_rect, icon_size * 0.5, _alpha(phase_colour, 0.72), _alpha(QColor("#ffffff"), 0.18))
            self._text(
                p,
                icon_rect,
                "✓" if deployed else "!" if pending else "H",
                self._font(font_factory, "poppins_bold", 10.0 * scale),
                QColor("#ffffff"),
                Qt.AlignmentFlag.AlignCenter,
                text_drawer,
            )

        title_left = icon_rect.right() + 11.0 * scale
        reserved = max(0.0, layout.header.right() - layout.status_chip.left())
        title_w = max(40.0, layout.header.width() - (title_left - layout.header.left()) - reserved - 10.0 * scale)
        if layout.body_progress < 0.10:
            self._text(
                p,
                QRectF(title_left, layout.header.top(), title_w, layout.header.height()),
                "HERO LOB",
                self._font(font_factory, "poppins_bold", 10.2 * scale),
                QColor("#ffffff"),
                text_drawer=text_drawer,
            )
        else:
            self._text(
                p,
                QRectF(title_left, layout.header.top() + 2.0 * scale, title_w, 22.0 * scale),
                "HERO LOB",
                self._font(font_factory, "poppins_bold", 13.0 * scale),
                QColor("#ffffff"),
                text_drawer=text_drawer,
            )
            self._text(
                p,
                QRectF(title_left, layout.header.top() + 24.0 * scale, title_w, 18.0 * scale),
                "Range deployment · ballistic assist",
                self._font(font_factory, "poppins_regular", 7.2 * scale),
                QColor("#c8d4dc"),
                text_drawer=text_drawer,
            )

        chip_hover = 1.0 if layout.status_chip.contains(pointer) else 0.0
        self._glass(
            p,
            layout.status_chip,
            layout.status_chip.height() * 0.5,
            glass_drawer,
            surface="SubGlass",
            hover=chip_hover * 0.25,
            clip_rect=layout.panel,
        )
        self._rounded(
            p,
            layout.status_chip,
            layout.status_chip.height() * 0.5,
            _alpha(phase_colour, 0.10),
            _alpha(phase_colour, 0.42),
            max(0.7, scale * 0.8),
        )
        self._text(
            p,
            layout.status_chip.adjusted(6.0 * scale, 0.0, -6.0 * scale, 0.0),
            phase,
            self._font(font_factory, "poppins_bold", 7.6 * scale),
            phase_colour,
            Qt.AlignmentFlag.AlignCenter,
            text_drawer,
        )
        close_hover = 1.0 if layout.close_button.contains(pointer) else 0.0
        self._glass(
            p,
            layout.close_button,
            layout.close_button.height() * 0.5,
            glass_drawer,
            surface="SubGlass",
            hover=close_hover,
            clip_rect=layout.panel,
        )
        self._rounded(
            p,
            layout.close_button,
            layout.close_button.height() * 0.5,
            _alpha(QColor("#ffffff"), 0.05 + 0.06 * close_hover),
            _alpha(QColor("#ffffff"), 0.14 + 0.10 * close_hover),
        )
        self._text(
            p,
            layout.close_button,
            "×",
            self._font(font_factory, "poppins_medium", 12.0 * scale),
            QColor("#ffffff"),
            Qt.AlignmentFlag.AlignCenter,
            text_drawer,
        )
        p.restore()

        hits: list[HeroDeployHitTarget] = []
        if layout.content_alpha > 0.001 and not layout.body_clip.isEmpty():
            p.save()
            p.setClipRect(layout.body_clip, Qt.ClipOperation.IntersectClip)
            p.setOpacity(layout.content_alpha)
            self._draw_trajectory(
                p,
                layout.trajectory,
                state=state,
                module=module,
                solution=solution,
                deployed=deployed,
                scale=scale,
                font_factory=font_factory,
                glass_drawer=glass_drawer,
                text_drawer=text_drawer,
                clip_rect=layout.body_clip,
            )
            self._draw_telemetry(
                p,
                layout.telemetry,
                state=state,
                solution=solution,
                readiness=readiness,
                interface=interface,
                now=now,
                scale=scale,
                font_factory=font_factory,
                glass_drawer=glass_drawer,
                text_drawer=text_drawer,
                clip_rect=layout.body_clip,
            )
            self._draw_rule_card(
                p,
                layout.rule_card,
                deployed=deployed,
                scale=scale,
                font_factory=font_factory,
                glass_drawer=glass_drawer,
                text_drawer=text_drawer,
                clip_rect=layout.body_clip,
            )

            labels = (
                "ENTER DEPLOY",
                "EXIT DEPLOY",
                "PREVIEW",
                "ARM ASSIST",
                "DISARM",
                "CLOSE",
            )
            actions = (
                "hero_deploy_enter",
                "hero_deploy_exit",
                "hero_lob_preview",
                "hero_lob_arm",
                "hero_lob_disarm",
                "hero_deploy_close",
            )
            enabled = (
                status == 0 and interface.pending_mode is None,
                status == 1 and interface.pending_mode is None,
                True,
                reachable and ready,
                bool(getattr(state, "hero_lob_armed", False)),
                status == 0 and interface.pending_mode is None,
            )
            for index, (rect, label, action, action_enabled) in enumerate(zip(layout.buttons, labels, actions, enabled)):
                confirm = (
                    (action == "hero_deploy_enter" and interface.confirm_mode == 1)
                    or (action == "hero_deploy_exit" and interface.confirm_mode == 0)
                )
                accent = QColor("#ffd36b") if confirm else QColor("#55c8ff") if index in {0, 2, 3} else QColor("#b8c4cc")
                hovered = rect.contains(pointer) and action_enabled and layout.interactive
                self._glass(
                    p,
                    rect,
                    min(rect.height() * 0.5, 16.0 * scale),
                    glass_drawer,
                    surface="SubGlass",
                    hover=1.0 if hovered else 0.0,
                    clip_rect=layout.body_clip,
                )
                self._rounded(
                    p,
                    rect,
                    min(rect.height() * 0.5, 16.0 * scale),
                    _alpha(accent, (0.14 if hovered else 0.08) if action_enabled else 0.025),
                    _alpha(accent, (0.54 if hovered else 0.32) if action_enabled else 0.12),
                    max(0.7, 0.8 * scale),
                )
                button_label = f"CONFIRM {label}" if confirm else label
                self._text(
                    p,
                    rect.adjusted(6.0 * scale, 0.0, -6.0 * scale, 0.0),
                    button_label,
                    self._font(font_factory, "poppins_bold", 7.4 * scale),
                    QColor("#ffffff") if action_enabled else QColor("#7d8991"),
                    Qt.AlignmentFlag.AlignCenter,
                    text_drawer,
                )
                hits.append(
                    HeroDeployHitTarget(
                        QRectF(rect),
                        action,
                        bool(action_enabled and layout.interactive and interface.visible),
                        button_label,
                    )
                )
            p.restore()

        # Preserve the six stable action targets during the island phase.  They
        # remain disabled until the sheet has finished revealing, which keeps
        # tests/layout tooling deterministic and prevents click-through.
        if not hits:
            labels = ("ENTER DEPLOY", "EXIT DEPLOY", "PREVIEW", "ARM ASSIST", "DISARM", "CLOSE")
            actions = (
                "hero_deploy_enter",
                "hero_deploy_exit",
                "hero_lob_preview",
                "hero_lob_arm",
                "hero_lob_disarm",
                "hero_deploy_close",
            )
            hits.extend(
                HeroDeployHitTarget(QRectF(rect), action, False, label)
                for rect, action, label in zip(layout.buttons, actions, labels)
            )
        p.restore()
        return tuple(hits)

    def _draw_trajectory(
        self,
        p: QPainter,
        rect: QRectF,
        *,
        state: Any,
        module: Any,
        solution: Any,
        deployed: bool,
        scale: float,
        font_factory: Callable[[str, float], QFont] | None,
        glass_drawer: GlassDrawer | None,
        text_drawer: TextDrawer | None,
        clip_rect: QRectF | None,
    ) -> None:
        self._glass(
            p,
            rect,
            18.0 * scale,
            glass_drawer,
            surface="MainGlass",
            clip_rect=clip_rect,
        )
        self._rounded(p, rect, 18.0 * scale, _alpha(QColor("#000000"), 0.055), _alpha(QColor("#ffffff"), 0.10))
        title = rect.adjusted(16.0 * scale, 8.0 * scale, -16.0 * scale, -rect.height() + 34.0 * scale)
        self._text(
            p,
            title,
            "BALLISTIC PREVIEW",
            self._font(font_factory, "poppins_bold", 8.6 * scale),
            QColor("#f3f8fb"),
            text_drawer=text_drawer,
        )
        viewport = rect.adjusted(18.0 * scale, 42.0 * scale, -18.0 * scale, -45.0 * scale)
        p.setPen(QPen(_alpha(QColor("#ffffff"), 0.10), max(0.65, scale * 0.7)))
        for index in range(1, 6):
            x = viewport.left() + viewport.width() * index / 6.0
            p.drawLine(QPointF(x, viewport.top()), QPointF(x, viewport.bottom()))
        for index in range(1, 4):
            y = viewport.top() + viewport.height() * index / 4.0
            p.drawLine(QPointF(viewport.left(), y), QPointF(viewport.right(), y))
        baseline = viewport.bottom() - 12.0 * scale
        p.setPen(QPen(_alpha(QColor("#8addff"), 0.76), max(1.0, 1.3 * scale)))
        p.drawLine(QPointF(viewport.left(), baseline), QPointF(viewport.right(), baseline))
        if bool(getattr(solution, "reachable", False)):
            pitch = math.radians(float(getattr(solution, "pitch_deg", 45.0)))
            peak = max(32.0 * scale, min(viewport.height() * 0.82, viewport.width() * math.tan(max(0.05, pitch)) * 0.18))
            path = QPainterPath(QPointF(viewport.left() + 8.0 * scale, baseline))
            path.cubicTo(
                QPointF(viewport.left() + viewport.width() * 0.28, baseline - peak),
                QPointF(viewport.left() + viewport.width() * 0.66, baseline - peak * 0.92),
                QPointF(viewport.right() - 8.0 * scale, baseline - 2.0 * scale),
            )
            p.setPen(QPen(QColor("#ffe06e"), max(1.2, 2.0 * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setBrush(QColor("#ff7169"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(viewport.right() - 8.0 * scale, baseline - 2.0 * scale), 4.0 * scale, 4.0 * scale)
        else:
            self._text(
                p,
                viewport,
                "NO VALID BALLISTIC SOLUTION",
                self._font(font_factory, "poppins_bold", 10.0 * scale),
                QColor("#ff817a"),
                Qt.AlignmentFlag.AlignCenter,
                text_drawer,
            )
        footer = rect.adjusted(16.0 * scale, rect.height() - 38.0 * scale, -16.0 * scale, -8.0 * scale)
        target_setting = module.get_setting("Target") if module is not None else None
        distance_setting = module.get_setting("Distance") if module is not None else None
        target = str(target_setting.value) if target_setting is not None else "Enemy Base"
        distance = float(distance_setting.value) if distance_setting is not None else 0.0
        footer_text = (
            "OFFICIAL VIDEO CUT · CUSTOM UI + MAP STAY ACTIVE"
            if deployed
            else f"TARGET {target.upper()}  ·  RANGE {distance:.1f} m"
        )
        self._text(
            p,
            footer,
            footer_text,
            self._font(font_factory, "poppins_medium", 7.2 * scale),
            QColor("#ffd878") if deployed else QColor("#bac7cf"),
            Qt.AlignmentFlag.AlignCenter,
            text_drawer,
        )

    def _draw_telemetry(
        self,
        p: QPainter,
        rect: QRectF,
        *,
        state: Any,
        solution: Any,
        readiness: Any,
        interface: HeroDeployInterfaceState,
        now: float,
        scale: float,
        font_factory: Callable[[str, float], QFont] | None,
        glass_drawer: GlassDrawer | None,
        text_drawer: TextDrawer | None,
        clip_rect: QRectF | None,
    ) -> None:
        self._glass(
            p,
            rect,
            18.0 * scale,
            glass_drawer,
            surface="SubGlass",
            clip_rect=clip_rect,
        )
        self._rounded(p, rect, 18.0 * scale, _alpha(QColor("#000000"), 0.045), _alpha(QColor("#ffffff"), 0.10))
        self._text(
            p,
            rect.adjusted(14.0 * scale, 6.0 * scale, -14.0 * scale, -rect.height() + 30.0 * scale),
            "DEPLOY / GIMBAL",
            self._font(font_factory, "poppins_bold", 8.0 * scale),
            QColor("#f3f8fb"),
            text_drawer=text_drawer,
        )
        values = (
            ("STATUS", interface.phase(int(getattr(state, "deploy_mode", 0)), now)),
            ("SOLUTION", "READY" if bool(getattr(solution, "reachable", False)) else "BLOCKED"),
            ("YAW / PITCH", f"{float(getattr(solution, 'yaw_deg', 0.0)):+.2f} / {float(getattr(solution, 'pitch_deg', 0.0)):+.2f}°"),
            ("FLIGHT", f"{float(getattr(solution, 'flight_time_s', 0.0)):.2f} s"),
            ("MUZZLE", f"{float(getattr(state, 'native_bullet_speed', 0.0)):.2f} m/s"),
            ("HEAT / AMMO", f"{int(getattr(state, 'current_heat', 0))}/{int(getattr(state, 'max_heat', 0))} · {int(getattr(state, 'remaining_ammo', 0))}"),
            ("GIMBAL", "ONLINE" if bool(getattr(state, "native_gimbal_online", False)) else "OFFLINE"),
        )
        row_h = max(15.0, (rect.height() - 38.0 * scale) / max(1, len(values)))
        for index, (label, value) in enumerate(values):
            row = QRectF(
                rect.left() + 14.0 * scale,
                rect.top() + 31.0 * scale + index * row_h,
                rect.width() - 28.0 * scale,
                row_h,
            )
            self._text(
                p,
                QRectF(row.left(), row.top(), row.width() * 0.43, row.height()),
                label,
                self._font(font_factory, "poppins_medium", 6.7 * scale),
                QColor("#9eabb3"),
                text_drawer=text_drawer,
            )
            value_colour = QColor("#f4f8fa") if value not in {"BLOCKED", "OFFLINE"} else QColor("#ff817a")
            self._text(
                p,
                QRectF(row.left() + row.width() * 0.40, row.top(), row.width() * 0.60, row.height()),
                value,
                self._font(font_factory, "poppins_bold", 6.8 * scale),
                value_colour,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text_drawer,
            )
        reasons = tuple(getattr(readiness, "reasons", ()) or ())
        if interface.last_error:
            reasons = (interface.last_error, *reasons)
        if reasons:
            self._text(
                p,
                rect.adjusted(14.0 * scale, rect.height() - 21.0 * scale, -14.0 * scale, -3.0 * scale),
                str(reasons[0]),
                self._font(font_factory, "poppins_medium", 6.3 * scale),
                QColor("#ffac84"),
                text_drawer=text_drawer,
            )

    def _draw_rule_card(
        self,
        p: QPainter,
        rect: QRectF,
        *,
        deployed: bool,
        scale: float,
        font_factory: Callable[[str, float], QFont] | None,
        glass_drawer: GlassDrawer | None,
        text_drawer: TextDrawer | None,
        clip_rect: QRectF | None,
    ) -> None:
        if rect.height() <= 8.0:
            return
        self._glass(
            p,
            rect,
            18.0 * scale,
            glass_drawer,
            surface="SubGlass",
            clip_rect=clip_rect,
        )
        self._rounded(p, rect, 18.0 * scale, _alpha(QColor("#000000"), 0.045), _alpha(QColor("#ffffff"), 0.10))
        self._text(
            p,
            rect.adjusted(14.0 * scale, 5.0 * scale, -14.0 * scale, -rect.height() + 28.0 * scale),
            "RM2026 DEPLOY MODE",
            self._font(font_factory, "poppins_bold", 7.7 * scale),
            QColor("#ffd878"),
            text_drawer=text_drawer,
        )
        lines = (
            "CHASSIS POWER OFF · DEFENCE +25%",
            "OFFICIAL VIDEO CUT · UI + MAP STAY",
            "42 mm BASE BONUS · MAX 16.5 m/s",
        )
        if deployed:
            lines = ("DEPLOYMENT ACTIVE", *lines)
        y = rect.top() + 28.0 * scale
        available = max(1.0, rect.bottom() - y - 5.0 * scale)
        row_h = min(18.0 * scale, available / max(1, len(lines)))
        for index, line in enumerate(lines):
            colour = QColor("#66e6ae") if deployed and index == 0 else QColor("#d5dde2")
            self._text(
                p,
                QRectF(rect.left() + 14.0 * scale, y + index * row_h, rect.width() - 28.0 * scale, row_h),
                line,
                self._font(font_factory, "poppins_medium", 6.4 * scale),
                colour,
                text_drawer=text_drawer,
            )
