from __future__ import annotations

from dataclasses import dataclass
import math
import time

from PySide6.QtCore import QRectF


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _smoothstep(value: float) -> float:
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _lerp_rect(start: QRectF, end: QRectF, progress: float) -> QRectF:
    progress = _clamp(progress, 0.0, 1.0)
    return QRectF(
        start.x() + (end.x() - start.x()) * progress,
        start.y() + (end.y() - start.y()) * progress,
        start.width() + (end.width() - start.width()) * progress,
        start.height() + (end.height() - start.height()) * progress,
    )


class EconomyIslandState:
    """Reversible critically damped island state driven by render time.

    Changing the target never resets progress or velocity. This lets B/Escape
    reverse an in-flight open/close transition without a visible jump.
    """

    def __init__(self) -> None:
        self.progress = 0.0
        self.target = 0.0
        self.velocity = 0.0
        self.duration = 0.62
        self._last_time = time.perf_counter()

    def set_target(
        self,
        target: float,
        duration: float | None = None,
        *,
        now: float | None = None,
    ) -> None:
        self.target = 1.0 if float(target) >= 0.5 else 0.0
        if duration is not None:
            self.duration = max(0.18, float(duration))
        if now is not None and self._last_time <= 0.0:
            self._last_time = float(now)

    def update(self, *, now: float | None = None) -> float:
        timestamp = time.perf_counter() if now is None else float(now)
        dt = _clamp(timestamp - self._last_time, 0.0, 0.05)
        self._last_time = timestamp
        if dt <= 0.0:
            return self.progress

        # Opening reaches an interactive state quickly, then settles softly.
        # Closing is slightly faster while preserving current velocity.
        omega = 13.5 if self.target > self.progress else 16.0
        substeps = max(1, int(math.ceil(dt / (1.0 / 180.0))))
        step = dt / substeps
        stiffness = omega * omega
        damping = 2.0 * omega
        for _ in range(substeps):
            acceleration = (self.target - self.progress) * stiffness - self.velocity * damping
            self.velocity += acceleration * step
            self.progress += self.velocity * step
            self.progress = _clamp(self.progress, 0.0, 1.0)

        if abs(self.target - self.progress) < 0.0005 and abs(self.velocity) < 0.004:
            self.progress = self.target
            self.velocity = 0.0
        return self.progress

    @property
    def active(self) -> bool:
        return abs(self.target - self.progress) > 0.0005 or abs(self.velocity) > 0.004


@dataclass(frozen=True)
class EconomyWorkspaceLayout:
    collapsed: QRectF
    target_panel: QRectF
    panel: QRectF
    header: QRectF
    close_button: QRectF
    link_chip: QRectF
    category_pane: QRectF
    offers_pane: QRectF
    detail_pane: QRectF
    category_viewport: QRectF
    offers_viewport: QRectF
    detail_viewport: QRectF
    action_button: QRectF
    compact: bool
    root_radius: float
    content_alpha: float
    interactive: bool


class EconomyWorkspaceLayer:
    """Responsive geometry for the exclusive economy GPU scene."""

    def layout(self, width: int, height: int, progress: float) -> EconomyWorkspaceLayout:
        width_f = max(1.0, float(width))
        height_f = max(1.0, float(height))
        progress = _clamp(progress, 0.0, 1.0)
        compact = width_f < 1600.0 or height_f < 850.0

        margin_x = 18.0 if compact else 28.0
        margin_y = 18.0 if compact else 28.0
        target_w = min(1510.0, width_f - margin_x * 2.0)
        target_h = min(790.0, height_f - margin_y * 2.0)
        target = QRectF(
            (width_f - target_w) * 0.5,
            (height_f - target_h) * 0.5,
            target_w,
            target_h,
        )

        collapsed_w = min(390.0, max(260.0, width_f * 0.30))
        collapsed_h = 44.0
        collapsed = QRectF((width_f - collapsed_w) * 0.5, 20.0, collapsed_w, collapsed_h)
        shape_progress = 1.0 - pow(1.0 - progress, 3.0)
        panel = _lerp_rect(collapsed, target, shape_progress)
        root_radius = min(
            panel.height() * 0.5,
            collapsed_h * 0.5 + (28.0 - collapsed_h * 0.5) * _smoothstep(progress),
        )
        content_alpha = _smoothstep((progress - 0.18) / 0.42)
        interactive = progress >= 0.48

        header_h = 66.0
        header = QRectF(target.left() + 24.0, target.top() + 16.0, target.width() - 48.0, header_h - 14.0)
        close_button = QRectF(header.right() - 36.0, header.top() + 4.0, 34.0, 34.0)
        link_chip = QRectF(close_button.left() - 122.0, header.top() + 6.0, 108.0, 30.0)

        inner = target.adjusted(18.0, header_h + 8.0, -18.0, -18.0)
        gap = 12.0
        left_w = _clamp(inner.width() * (0.205 if compact else 0.19), 208.0, 274.0)
        category_pane = QRectF(inner.left(), inner.top(), left_w, inner.height())
        remaining_left = category_pane.right() + gap
        remaining_w = inner.right() - remaining_left

        if compact:
            offers_h = max(220.0, inner.height() * 0.52)
            offers_pane = QRectF(remaining_left, inner.top(), remaining_w, offers_h)
            detail_pane = QRectF(
                remaining_left,
                offers_pane.bottom() + gap,
                remaining_w,
                max(80.0, inner.bottom() - offers_pane.bottom() - gap),
            )
        else:
            offers_w = _clamp(remaining_w * 0.46, 390.0, 540.0)
            offers_pane = QRectF(remaining_left, inner.top(), offers_w, inner.height())
            detail_pane = QRectF(
                offers_pane.right() + gap,
                inner.top(),
                max(260.0, inner.right() - offers_pane.right() - gap),
                inner.height(),
            )

        category_viewport = category_pane.adjusted(14.0, 126.0, -14.0, -116.0)
        offers_viewport = offers_pane.adjusted(14.0, 48.0, -14.0, -14.0)
        action_button = QRectF(
            detail_pane.left() + 16.0,
            detail_pane.bottom() - 58.0,
            max(40.0, detail_pane.width() - 32.0),
            44.0,
        )
        detail_viewport = QRectF(
            detail_pane.left() + 16.0,
            detail_pane.top() + 14.0,
            max(20.0, detail_pane.width() - 32.0),
            max(20.0, action_button.top() - detail_pane.top() - 24.0),
        )

        return EconomyWorkspaceLayout(
            collapsed=collapsed,
            target_panel=target,
            panel=panel,
            header=header,
            close_button=close_button,
            link_chip=link_chip,
            category_pane=category_pane,
            offers_pane=offers_pane,
            detail_pane=detail_pane,
            category_viewport=category_viewport,
            offers_viewport=offers_viewport,
            detail_viewport=detail_viewport,
            action_button=action_button,
            compact=compact,
            root_radius=root_radius,
            content_alpha=content_alpha,
            interactive=interactive,
        )
