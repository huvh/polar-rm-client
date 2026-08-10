"""Dedicated Hero deployment/lob operator console.

The console mirrors the rule-level state machine instead of pretending that
enabling ``HeroLob`` immediately deploys or fires the robot.  Entry and exit
are explicit, double-confirmed requests.  In mock scenarios the two-second
deployment delay is simulated; in official mode only
``DeployModeStatusSync`` is authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen


@dataclass(frozen=True, slots=True)
class HeroDeployHitTarget:
    rect: QRectF
    action: str
    enabled: bool = True
    tooltip: str = ""


@dataclass(frozen=True, slots=True)
class HeroDeployLayout:
    panel: QRectF
    header: QRectF
    trajectory: QRectF
    telemetry: QRectF
    rule_card: QRectF
    buttons: tuple[QRectF, ...]
    scale: float

    @classmethod
    def for_viewport(cls, width: int, height: int) -> "HeroDeployLayout":
        width = max(1, int(width))
        height = max(1, int(height))
        scale = max(0.72, min(1.45, min(width / 1280.0, height / 720.0)))
        margin = max(18.0, 28.0 * scale)
        panel = QRectF(margin, margin, width - margin * 2.0, height - margin * 2.0)
        header_h = max(54.0, 62.0 * scale)
        header = QRectF(panel.left(), panel.top(), panel.width(), header_h)
        inner = panel.adjusted(18.0 * scale, header_h + 12.0 * scale, -18.0 * scale, -18.0 * scale)
        button_h = max(34.0, 42.0 * scale)
        button_gap = max(6.0, 8.0 * scale)
        buttons_top = inner.bottom() - button_h * 2.0 - button_gap
        content = QRectF(inner.left(), inner.top(), inner.width(), max(80.0, buttons_top - inner.top() - 12.0 * scale))
        left_w = content.width() * (0.60 if width >= 1180 else 0.56)
        gap = 12.0 * scale
        trajectory = QRectF(content.left(), content.top(), max(100.0, left_w - gap * 0.5), content.height())
        right = QRectF(trajectory.right() + gap, content.top(), max(100.0, content.right() - trajectory.right() - gap), content.height())
        telemetry_h = max(92.0, right.height() * 0.56)
        telemetry = QRectF(right.left(), right.top(), right.width(), min(right.height(), telemetry_h))
        rule_card = QRectF(right.left(), telemetry.bottom() + gap, right.width(), max(0.0, right.bottom() - telemetry.bottom() - gap))
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
        return cls(panel, header, trajectory, telemetry, rule_card, buttons, scale)


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

    def open(self, now: float) -> None:
        self.visible = True
        self.opened_at = float(now)
        self.last_error = ""

    def close(self) -> None:
        self.visible = False
        self.confirm_mode = None
        self.confirm_until = 0.0

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
    """High-DPI vector renderer for the dedicated deployment console."""

    def layout(self, width: int, height: int) -> HeroDeployLayout:
        return HeroDeployLayout.for_viewport(width, height)

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
    ) -> None:
        p.setFont(font)
        p.setPen(colour)
        p.drawText(rect, int(align), str(text))

    @staticmethod
    def _rounded(p: QPainter, rect: QRectF, radius: float, fill: QColor, outline: QColor | None = None) -> None:
        p.setBrush(fill)
        p.setPen(QPen(outline, 1.0) if outline is not None else Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

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
    ) -> tuple[HeroDeployHitTarget, ...]:
        layout = self.layout(width, height)
        scale = layout.scale
        status = int(getattr(state, "deploy_mode", 0))
        phase = interface.phase(status, now)
        deployed = status == 1
        ready = bool(getattr(readiness, "ready", False))
        reachable = bool(getattr(solution, "reachable", False))

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(QRectF(0.0, 0.0, width, height), QColor(0, 6, 12, 186))
        self._rounded(p, layout.panel, 12.0 * scale, QColor(5, 13, 20, 244), QColor(111, 213, 255, 120))
        header_gradient = QLinearGradient(layout.header.topLeft(), layout.header.topRight())
        header_gradient.setColorAt(0.0, QColor(21, 122, 172, 220))
        header_gradient.setColorAt(0.55, QColor(8, 29, 42, 235))
        header_gradient.setColorAt(1.0, QColor(6, 18, 27, 235))
        p.setBrush(header_gradient)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(layout.header, 12.0 * scale, 12.0 * scale)
        p.fillRect(QRectF(layout.header.left(), layout.header.bottom() - 12.0 * scale, layout.header.width(), 12.0 * scale), header_gradient)
        self._text(
            p,
            layout.header.adjusted(20.0 * scale, 0.0, -240.0 * scale, 0.0),
            "HERO DEPLOY / LOB CONSOLE",
            self._font(font_factory, "poppins_bold", 14.0 * scale),
            QColor("#f2fbff"),
        )
        phase_rect = QRectF(layout.header.right() - 220.0 * scale, layout.header.top() + 14.0 * scale, 196.0 * scale, 32.0 * scale)
        phase_colour = QColor("#54e5a7") if deployed else (QColor("#ffd266") if interface.pending_mode is not None else QColor("#6fd5ff"))
        self._rounded(p, phase_rect, 16.0 * scale, QColor(phase_colour.red(), phase_colour.green(), phase_colour.blue(), 35), QColor(phase_colour.red(), phase_colour.green(), phase_colour.blue(), 145))
        self._text(p, phase_rect, phase, self._font(font_factory, "poppins_bold", 9.0 * scale), phase_colour, Qt.AlignmentFlag.AlignCenter)

        self._draw_trajectory(
            p,
            layout.trajectory,
            state=state,
            module=module,
            solution=solution,
            deployed=deployed,
            scale=scale,
            font_factory=font_factory,
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
        )
        self._draw_rule_card(p, layout.rule_card, deployed=deployed, scale=scale, font_factory=font_factory)

        labels = (
            "ENTER DEPLOY MODE",
            "EXIT DEPLOY MODE",
            "PREVIEW TRAJECTORY",
            "ARM ASSIST",
            "DISARM",
            "CLOSE CONSOLE",
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
        hits: list[HeroDeployHitTarget] = []
        for index, (rect, label, action, is_enabled) in enumerate(zip(layout.buttons, labels, actions, enabled)):
            confirm = (
                (action == "hero_deploy_enter" and interface.confirm_mode == 1)
                or (action == "hero_deploy_exit" and interface.confirm_mode == 0)
            )
            accent = QColor("#ffbd59") if confirm else (QColor("#34b8ff") if index in {0, 2, 3} else QColor("#6c8290"))
            alpha = 50 if is_enabled else 16
            self._rounded(
                p,
                rect,
                5.0 * scale,
                QColor(accent.red(), accent.green(), accent.blue(), alpha),
                QColor(accent.red(), accent.green(), accent.blue(), 175 if is_enabled else 55),
            )
            button_label = f"CONFIRM {label}" if confirm else label
            self._text(
                p,
                rect.adjusted(5.0, 0.0, -5.0, 0.0),
                button_label,
                self._font(font_factory, "poppins_bold", 8.0 * scale),
                QColor("#ffffff") if is_enabled else QColor(130, 144, 153),
                Qt.AlignmentFlag.AlignCenter,
            )
            hits.append(HeroDeployHitTarget(QRectF(rect), action, is_enabled, button_label))
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
    ) -> None:
        self._rounded(p, rect, 8.0 * scale, QColor(1, 7, 12, 225), QColor(91, 177, 216, 85))
        title_rect = QRectF(rect.left() + 16.0 * scale, rect.top() + 10.0 * scale, rect.width() - 32.0 * scale, 24.0 * scale)
        self._text(p, title_rect, "BALLISTIC TRAJECTORY / OPERATOR PREVIEW", self._font(font_factory, "poppins_bold", 9.0 * scale), QColor("#8edfff"))
        viewport = rect.adjusted(18.0 * scale, 42.0 * scale, -18.0 * scale, -45.0 * scale)
        p.setPen(QPen(QColor(64, 109, 128, 85), 1.0))
        for index in range(1, 6):
            x = viewport.left() + viewport.width() * index / 6.0
            p.drawLine(QPointF(x, viewport.top()), QPointF(x, viewport.bottom()))
        for index in range(1, 4):
            y = viewport.top() + viewport.height() * index / 4.0
            p.drawLine(QPointF(viewport.left(), y), QPointF(viewport.right(), y))
        baseline = viewport.bottom() - 12.0 * scale
        p.setPen(QPen(QColor("#6fd5ff"), max(1.0, 1.4 * scale)))
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
            p.setPen(QPen(QColor("#ffe06a"), max(1.2, 2.0 * scale)))
            p.drawPath(path)
            p.setBrush(QColor("#ff675e"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(viewport.right() - 8.0 * scale, baseline - 2.0 * scale), 4.0 * scale, 4.0 * scale)
        else:
            self._text(p, viewport, "NO VALID BALLISTIC SOLUTION", self._font(font_factory, "poppins_bold", 11.0 * scale), QColor("#ff7169"), Qt.AlignmentFlag.AlignCenter)
        footer = rect.adjusted(16.0 * scale, rect.height() - 38.0 * scale, -16.0 * scale, -8.0 * scale)
        target_setting = module.get_setting("Target") if module is not None else None
        distance_setting = module.get_setting("Distance") if module is not None else None
        target = str(target_setting.value) if target_setting is not None else "Enemy Base"
        distance = float(distance_setting.value) if distance_setting is not None else 0.0
        text = (
            "VIDEO CUT BY OFFICIAL DEPLOY MODE / CUSTOM UI REMAINS ACTIVE"
            if deployed
            else f"TARGET {target.upper()}  /  RANGE {distance:.1f}m"
        )
        self._text(p, footer, text, self._font(font_factory, "poppins_medium", 7.8 * scale), QColor("#ffce62") if deployed else QColor("#9fb5c1"), Qt.AlignmentFlag.AlignCenter)

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
    ) -> None:
        self._rounded(p, rect, 8.0 * scale, QColor(8, 19, 27, 235), QColor(95, 184, 222, 80))
        self._text(p, rect.adjusted(14.0 * scale, 7.0 * scale, -14.0 * scale, -rect.height() + 31.0 * scale), "DEPLOY / GIMBAL TELEMETRY", self._font(font_factory, "poppins_bold", 8.6 * scale), QColor("#8edfff"))
        values = (
            ("DEPLOY STATUS", interface.phase(int(getattr(state, "deploy_mode", 0)), now)),
            ("SOLUTION", "READY" if bool(getattr(solution, "reachable", False)) else "BLOCKED"),
            ("YAW / PITCH", f"{float(getattr(solution, 'yaw_deg', 0.0)):+.2f} / {float(getattr(solution, 'pitch_deg', 0.0)):+.2f} deg"),
            ("FLIGHT TIME", f"{float(getattr(solution, 'flight_time_s', 0.0)):.2f} s"),
            ("MUZZLE SPEED", f"{float(getattr(state, 'native_bullet_speed', 0.0)):.2f} m/s"),
            ("HEAT / AMMO", f"{int(getattr(state, 'current_heat', 0))}/{int(getattr(state, 'max_heat', 0))}  /  {int(getattr(state, 'remaining_ammo', 0))}"),
            ("GIMBAL LINK", "ONLINE" if bool(getattr(state, "native_gimbal_online", False)) else "OFFLINE"),
        )
        row_h = max(17.0, (rect.height() - 40.0 * scale) / max(1, len(values)))
        for index, (label, value) in enumerate(values):
            row = QRectF(rect.left() + 14.0 * scale, rect.top() + 34.0 * scale + index * row_h, rect.width() - 28.0 * scale, row_h)
            self._text(p, QRectF(row.left(), row.top(), row.width() * 0.46, row.height()), label, self._font(font_factory, "poppins_medium", 7.1 * scale), QColor("#7f98a6"))
            value_colour = QColor("#f0f8fb")
            if value in {"BLOCKED", "OFFLINE"}:
                value_colour = QColor("#ff7169")
            self._text(p, QRectF(row.left() + row.width() * 0.43, row.top(), row.width() * 0.57, row.height()), value, self._font(font_factory, "poppins_bold", 7.2 * scale), value_colour, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        reasons = tuple(getattr(readiness, "reasons", ()) or ())
        if interface.last_error:
            reasons = (interface.last_error, *reasons)
        if reasons:
            self._text(p, rect.adjusted(14.0 * scale, rect.height() - 22.0 * scale, -14.0 * scale, -4.0 * scale), str(reasons[0])[:58], self._font(font_factory, "poppins_medium", 6.8 * scale), QColor("#ff9a78"))

    def _draw_rule_card(
        self,
        p: QPainter,
        rect: QRectF,
        *,
        deployed: bool,
        scale: float,
        font_factory: Callable[[str, float], QFont] | None,
    ) -> None:
        if rect.height() <= 8.0:
            return
        self._rounded(p, rect, 8.0 * scale, QColor(8, 19, 27, 235), QColor(95, 184, 222, 70))
        self._text(p, rect.adjusted(14.0 * scale, 5.0 * scale, -14.0 * scale, -rect.height() + 27.0 * scale), "RM2026 DEPLOY MODE", self._font(font_factory, "poppins_bold", 8.2 * scale), QColor("#ffcf69"))
        lines = (
            "CHASSIS POWER OFF / DEFENCE +25%",
            "VIDEO STREAM CUT / CUSTOM UI + MAP STAY",
            "42mm BASE ATTACK BONUS / MAX 16.5m/s",
        )
        if deployed:
            lines = ("DEPLOYMENT ACTIVE", *lines)
        y = rect.top() + 28.0 * scale
        available = max(1.0, rect.bottom() - y - 5.0 * scale)
        row_h = min(18.0 * scale, available / max(1, len(lines)))
        for index, line in enumerate(lines):
            self._text(p, QRectF(rect.left() + 14.0 * scale, y + index * row_h, rect.width() - 28.0 * scale, row_h), line, self._font(font_factory, "poppins_medium", 6.7 * scale), QColor("#b7c8d1"))

