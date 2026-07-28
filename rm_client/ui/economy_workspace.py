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


def adaptive_backdrop_dim(scene_luminance: float, progress: float) -> float:
    """Return the fixed dim layer used by the reference Control Center."""
    del scene_luminance
    return 0.40 * _clamp(progress, 0.0, 1.0)


def _lerp_rect(start: QRectF, end: QRectF, progress: float) -> QRectF:
    progress = _clamp(progress, 0.0, 1.0)
    return QRectF(
        start.x() + (end.x() - start.x()) * progress,
        start.y() + (end.y() - start.y()) * progress,
        start.width() + (end.width() - start.width()) * progress,
        start.height() + (end.height() - start.height()) * progress,
    )


def _layer_transform_rect(
    rect: QRectF,
    pivot_x: float,
    pivot_y: float,
    scale_x: float,
    scale_y: float,
    translate_y: float,
) -> QRectF:
    """Apply the control-center layer transform to one logical rectangle."""
    return QRectF(
        pivot_x + (rect.x() - pivot_x) * scale_x,
        pivot_y + (rect.y() - pivot_y) * scale_y + translate_y,
        rect.width() * scale_x,
        rect.height() * scale_y,
    )


class EconomyIslandState:
    """Reversible spring matching the reference Control Center motion."""

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

        opening = self.target > self.progress
        reference_duration = 0.62 if opening else 0.48
        time_scale = reference_duration / max(0.18, self.duration)
        stiffness = 300.0 * time_scale * time_scale
        damping_ratio = 0.5 if opening else 1.0
        damping = 2.0 * damping_ratio * math.sqrt(stiffness)
        substeps = max(1, int(math.ceil(dt / (1.0 / 180.0))))
        step = dt / substeps
        for _ in range(substeps):
            acceleration = (self.target - self.progress) * stiffness - self.velocity * damping
            self.velocity += acceleration * step
            self.progress += self.velocity * step
            self.progress = _clamp(self.progress, -0.02, 1.12)

        if abs(self.target - self.progress) < 0.0005 and abs(self.velocity) < 0.008:
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
    grab_handle: QRectF
    close_button: QRectF
    link_chip: QRectF
    offers_pane: QRectF
    detail_pane: QRectF
    offers_viewport: QRectF
    detail_viewport: QRectF
    action_button: QRectF
    tab_bar: QRectF
    status_strip: QRectF
    compact: bool
    root_radius: float
    island_progress: float
    body_progress: float
    header_alpha: float
    content_alpha: float
    category_alpha: float
    offers_alpha: float
    detail_alpha: float
    tab_alpha: float
    offers_offset: float
    detail_offset: float
    body_clip: QRectF
    interactive: bool


class EconomyWorkspaceLayer:
    """Responsive geometry for the exclusive economy GPU scene."""

    def layout(self, width: int, height: int, progress: float) -> EconomyWorkspaceLayout:
        width_f = max(1.0, float(width))
        height_f = max(1.0, float(height))
        raw_progress = _clamp(progress, -0.02, 1.12)
        progress = _clamp(raw_progress, 0.0, 1.0)
        compact = width_f < 1600.0 or height_f < 850.0

        # The workspace follows the same hierarchy as a system pull-down:
        # first form a compact, readable island, then grow the *same* material
        # downward and reveal the working controls through its rounded clip.
        # Keeping the top edge fixed avoids the centred-modal feeling.
        margin_x = 16.0 if compact else 28.0
        top_margin = 12.0 if compact else 16.0
        bottom_margin = 18.0 if compact else 28.0
        # A pull-down workspace should retain a clear relationship with its
        # presenting island.  The previous 1240px sheet filled most of a
        # 1600px window and read as a centred desktop modal instead.
        target_w = min(1100.0, width_f - margin_x * 2.0)
        target_h = min(640.0, height_f - top_margin - bottom_margin)
        target = QRectF(
            (width_f - target_w) * 0.5,
            top_margin,
            target_w,
            target_h,
        )

        collapsed_w = min(390.0, max(260.0, width_f * 0.30))
        collapsed_h = 46.0
        collapsed = QRectF(
            (width_f - collapsed_w) * 0.5,
            top_margin,
            collapsed_w,
            collapsed_h,
        )
        # Stage 1 makes the anchor itself legible.  Stage 2 expands that
        # exact island into a sheet.  A single direct collapsed->target lerp
        # made the current UI read as a generic modal instead of a pull-down.
        island_target = QRectF(
            (width_f - min(560.0, max(collapsed_w, width_f * 0.42))) * 0.5,
            top_margin,
            min(560.0, max(collapsed_w, width_f * 0.42)),
            84.0,
        )
        island_progress = _smoothstep(progress / 0.24)
        body_progress = _smoothstep((progress - 0.20) / 0.80)
        island = _lerp_rect(collapsed, island_target, island_progress)
        panel = _lerp_rect(island, target, body_progress)
        root_radius = min(
            panel.height() * 0.5,
            collapsed_h * 0.5 + (30.0 - collapsed_h * 0.5) * body_progress,
        )
        # ControlCenterContent applies EaseIn to the complete glass layer.
        # Keeping the same source curve here prevents the early island from
        # flashing fully opaque before its downward motion has settled.
        header_alpha = progress * progress
        # Keep the final content geometry intact.  iOS pull-down surfaces
        # reveal their controls after the container has formed; squeezing
        # every column into the in-between island produces the modal-like
        # distortion seen in the old implementation.
        category_alpha = _smoothstep((body_progress - 0.42) / 0.26)
        offers_alpha = _smoothstep((body_progress - 0.56) / 0.26)
        detail_alpha = _smoothstep((body_progress - 0.68) / 0.24)
        content_alpha = max(category_alpha, offers_alpha, detail_alpha)
        interactive = body_progress >= 0.72

        # The control-center sample keeps each group at its final size, then
        # reveals it through the sheet while it settles from a short upward
        # offset.  It avoids the desktop-modal look caused by squeezing the
        # final columns into the early island geometry.
        category_offset = -20.0 * (1.0 - category_alpha)
        offers_offset = -18.0 * (1.0 - offers_alpha)
        detail_offset = -16.0 * (1.0 - detail_alpha)

        # Header follows the morphing root.  The working content itself uses
        # final geometry and is revealed by the root/body clips below.
        header_h = 66.0
        header = QRectF(panel.left() + 24.0, panel.top() + 16.0, panel.width() - 48.0, header_h - 14.0)
        grab_handle = QRectF(
            panel.center().x() - 18.0,
            panel.top() + 8.0,
            36.0,
            3.0,
        )
        close_button = QRectF(header.right() - 36.0, header.top() + 4.0, 34.0, 34.0)
        link_chip = QRectF(close_button.left() - 122.0, header.top() + 6.0, 108.0, 30.0)

        inner = target.adjusted(18.0, header_h + 8.0, -18.0, -18.0)
        gap = 16.0

        # Bottom tab bar replaces the old left category pane (LiquidBottomTabs style).
        tab_h = 48.0 if compact else 56.0
        tab_bar = QRectF(inner.left(), inner.bottom() - tab_h, inner.width(), tab_h)
        tab_alpha = _smoothstep((body_progress - 0.42) / 0.26)
        # Status strip: compact gold/HP/ammo info between header and content.
        status_strip = QRectF(inner.left(), inner.top(), inner.width(), 38.0)
        content_top = status_strip.bottom() + 8.0
        content_bottom = tab_bar.top() - 8.0
        content_h = max(60.0, content_bottom - content_top)

        if compact:
            offers_h = max(180.0, content_h * 0.52)
            offers_pane = QRectF(inner.left(), content_top, inner.width(), offers_h)
            detail_pane = QRectF(
                inner.left(),
                offers_pane.bottom() + gap,
                inner.width(),
                max(80.0, content_bottom - offers_pane.bottom() - gap),
            )
        else:
            offers_w = _clamp(inner.width() * 0.50, 390.0, 560.0)
            offers_pane = QRectF(inner.left(), content_top, offers_w, content_h)
            detail_pane = QRectF(
                offers_pane.right() + gap,
                content_top,
                max(260.0, inner.right() - offers_pane.right() - gap),
                content_h,
            )

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
        panel_body = panel.adjusted(18.0, header_h + 8.0, -18.0, -18.0)
        revealed_body = QRectF(
            inner.left(),
            inner.top(),
            inner.width(),
            max(0.0, inner.height() * body_progress),
        )
        body_clip = revealed_body.intersected(panel_body)

        # ControlCenterContent starts 48dp above its resting position. Shape
        # deformation happens only while the opening spring overshoots.
        safe_progress = min(raw_progress, 1.0)
        overshoot = max(0.0, raw_progress - 1.0)
        layer_scale = 1.0 + 0.10 * overshoot
        layer_scale_x = 1.0 / layer_scale
        layer_scale_y = layer_scale
        layer_translate_y = -48.0 * (1.0 - safe_progress)
        pivot_x = panel.center().x()
        pivot_y = panel.center().y()

        def present(rect: QRectF) -> QRectF:
            return _layer_transform_rect(
                rect,
                pivot_x,
                pivot_y,
                layer_scale_x,
                layer_scale_y,
                layer_translate_y,
            )

        panel = present(panel)
        header = present(header)
        grab_handle = present(grab_handle)
        close_button = present(close_button)
        link_chip = present(link_chip)
        offers_pane = present(offers_pane)
        detail_pane = present(detail_pane)
        offers_viewport = present(offers_viewport)
        detail_viewport = present(detail_viewport)
        action_button = present(action_button)
        tab_bar = present(tab_bar)
        status_strip = present(status_strip)
        body_clip = present(body_clip).intersected(panel)
        root_radius *= layer_scale_y

        return EconomyWorkspaceLayout(
            collapsed=collapsed,
            target_panel=target,
            panel=panel,
            header=header,
            grab_handle=grab_handle,
            close_button=close_button,
            link_chip=link_chip,
            offers_pane=offers_pane,
            detail_pane=detail_pane,
            offers_viewport=offers_viewport,
            detail_viewport=detail_viewport,
            action_button=action_button,
            tab_bar=tab_bar,
            status_strip=status_strip,
            compact=compact,
            root_radius=root_radius,
            island_progress=island_progress,
            body_progress=body_progress,
            header_alpha=header_alpha,
            content_alpha=content_alpha,
            category_alpha=category_alpha,
            offers_alpha=offers_alpha,
            detail_alpha=detail_alpha,
            tab_alpha=tab_alpha,
            offers_offset=offers_offset,
            detail_offset=detail_offset,
            body_clip=body_clip,
            interactive=interactive,
        )
