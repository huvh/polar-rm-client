"""Economy-panel liquid glass renderer inspired by AndroidLiquidGlass-kmp.

Implements the key visual principles from Kyant's backdrop library:
- Transparent center (no white fill)
- Edge refraction band (simulated with gradient ring)
- Directional highlight (45-degree light, SDF-gradient dot product)
- Outer shadow for depth
- Inner shadow for glass thickness
- No hard white borders

This module is ONLY used by the EconomyPanel workspace. It does NOT modify
the shared liquid_glass.py or draw_liquid_glass_panel used elsewhere.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)


def _sdf_gradient_angle(cx: float, cy: float, half_w: float, half_h: float, radius: float) -> float:
    """Approximate the SDF gradient direction at a point on the rounded rect edge.

    Returns angle in radians pointing outward from the shape center.
    """
    # Clamp to corner region
    dx = max(0.0, abs(cx) - (half_w - radius))
    dy = max(0.0, abs(cy) - (half_h - radius))
    if dx > 0.0 or dy > 0.0:
        return math.atan2(math.copysign(dy, cy), math.copysign(dx, cx))
    # Flat edge region
    if abs(cx) / max(1.0, half_w) > abs(cy) / max(1.0, half_h):
        return 0.0 if cx > 0 else math.pi
    return math.pi * 0.5 if cy > 0 else -math.pi * 0.5


def draw_economy_glass(
    p: QPainter,
    rect: QRectF,
    radius: float,
    *,
    edge_width: float = 10.0,
    highlight_angle: float = math.pi * 0.25,  # 45 degrees (top-left light)
    highlight_intensity: float = 0.32,
    shadow_radius: float = 18.0,
    shadow_alpha: float = 0.14,
    inner_shadow_alpha: float = 0.10,
    tint_alpha: float = 0.06,
    tint_color: str = "#0a1420",
    edge_tint_alpha: float = 0.10,
) -> None:
    """Draw a liquid glass panel in the AndroidLiquidGlass-kmp style.

    Layers (bottom to top):
    1. Outer shadow (soft, offset down)
    2. Transparent center with subtle dark tint
    3. Edge refraction band (gradient ring, brighter at outer edge)
    4. Directional highlight (45-degree light on the edge)
    5. Inner shadow (dark edge inside for depth)
    6. Ultra-thin edge outline (NOT white — subtle cool tone)
    """
    if rect.width() < 4.0 or rect.height() < 4.0:
        return

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    # --- 1. Outer shadow ---
    if shadow_alpha > 0.001:
        shadow_path = QPainterPath()
        shadow_rect = rect.adjusted(-shadow_radius * 0.3, -shadow_radius * 0.1, shadow_radius * 0.3, shadow_radius * 0.5)
        shadow_path.addRoundedRect(shadow_rect, radius + shadow_radius * 0.2, radius + shadow_radius * 0.2)
        shadow_only = shadow_path.subtracted(path)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        # Layered soft shadow
        for i, (pad, alpha) in enumerate((
            (shadow_radius * 0.5, shadow_alpha * 0.3),
            (shadow_radius * 0.25, shadow_alpha * 0.5),
            (0.0, shadow_alpha * 0.7),
        )):
            sr = rect.adjusted(-pad, -pad * 0.3 + shadow_radius * 0.15, pad, pad * 0.5 + shadow_radius * 0.2)
            sp = QPainterPath()
            sp.addRoundedRect(sr, radius + pad * 0.5, radius + pad * 0.5)
            sp = sp.subtracted(path)
            p.setBrush(QColor(0, 0, 0, int(255 * alpha)))
            p.drawPath(sp)
        p.restore()

    # --- 2. Transparent center with subtle tint ---
    p.save()
    p.setClipPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    tc = QColor(tint_color)
    tc.setAlphaF(tint_alpha)
    p.setBrush(tc)
    p.drawRoundedRect(rect, radius, radius)
    p.restore()

    # --- 3. Edge refraction band ---
    # Simulates the refraction zone from AndroidLiquidGlass-kmp Lens.kt:
    # edge band where background bends, brighter at outer edge fading inward.
    if edge_width > 1.0:
        inner_rect = rect.adjusted(edge_width, edge_width, -edge_width, -edge_width)
        inner_radius = max(1.0, radius - edge_width)
        outer_path = QPainterPath()
        outer_path.addRoundedRect(rect, radius, radius)
        inner_path = QPainterPath()
        inner_path.addRoundedRect(inner_rect, inner_radius, inner_radius)
        edge_band = outer_path.subtracted(inner_path)

        p.save()
        p.setClipPath(edge_band)
        p.setPen(Qt.PenStyle.NoPen)
        # Radial-ish gradient from edge inward (simulated with 4 linear gradients)
        edge_color = QColor(180, 220, 255, int(255 * edge_tint_alpha))
        edge_inner = QColor(180, 220, 255, 0)
        # Top edge
        g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + edge_width)
        g.setColorAt(0.0, edge_color)
        g.setColorAt(1.0, edge_inner)
        p.setBrush(g)
        p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), edge_width))
        # Bottom edge
        g = QLinearGradient(rect.left(), rect.bottom(), rect.left(), rect.bottom() - edge_width)
        g.setColorAt(0.0, edge_color)
        g.setColorAt(1.0, edge_inner)
        p.setBrush(g)
        p.drawRect(QRectF(rect.left(), rect.bottom() - edge_width, rect.width(), edge_width))
        # Left edge
        g = QLinearGradient(rect.left(), rect.top(), rect.left() + edge_width, rect.top())
        g.setColorAt(0.0, edge_color)
        g.setColorAt(1.0, edge_inner)
        p.setBrush(g)
        p.drawRect(QRectF(rect.left(), rect.top(), edge_width, rect.height()))
        # Right edge
        g = QLinearGradient(rect.right(), rect.top(), rect.right() - edge_width, rect.top())
        g.setColorAt(0.0, edge_color)
        g.setColorAt(1.0, edge_inner)
        p.setBrush(g)
        p.drawRect(QRectF(rect.right() - edge_width, rect.top(), edge_width, rect.height()))
        p.restore()

    # --- 4. Directional highlight (AndroidLiquidGlass-kmp HighlightStyle.Default) ---
    # Simulates: intensity = pow(abs(dot(sdf_gradient, light_normal)), falloff)
    # Light comes from top-left (45 degrees). Highlight is strongest on the
    # top and left edges, fading to zero on bottom-right.
    if highlight_intensity > 0.001:
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        light_dx = math.cos(highlight_angle)
        light_dy = -math.sin(highlight_angle)  # Y is flipped in screen coords
        # Top-left highlight arc
        hl_rect = rect.adjusted(-1, -1, 1, 1)
        # Use a linear gradient across the panel in the light direction
        start = QPointF(
            rect.center().x() - light_dx * rect.width() * 0.5,
            rect.center().y() - light_dy * rect.height() * 0.5,
        )
        end = QPointF(
            rect.center().x() + light_dx * rect.width() * 0.5,
            rect.center().y() + light_dy * rect.height() * 0.5,
        )
        g = QLinearGradient(start, end)
        hi_color = QColor(255, 255, 255, int(255 * highlight_intensity))
        hi_mid = QColor(240, 248, 255, int(255 * highlight_intensity * 0.3))
        g.setColorAt(0.0, hi_color)
        g.setColorAt(0.18, hi_mid)
        g.setColorAt(0.45, QColor(240, 248, 255, 0))
        g.setColorAt(1.0, QColor(240, 248, 255, 0))
        # Only apply to edge band (not center)
        inner_rect = rect.adjusted(edge_width * 1.5, edge_width * 1.5, -edge_width * 1.5, -edge_width * 1.5)
        inner_path = QPainterPath()
        inner_path.addRoundedRect(inner_rect, max(1.0, radius - edge_width * 1.5), max(1.0, radius - edge_width * 1.5))
        edge_only = path.subtracted(inner_path)
        p.setClipPath(edge_only)
        p.setBrush(g)
        p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
        p.restore()

    # --- 5. Inner shadow (depth) ---
    if inner_shadow_alpha > 0.001:
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        # Dark gradient from bottom-right edge inward (opposite to light)
        inner_w = edge_width * 0.7
        inner_rect = rect.adjusted(inner_w, inner_w, -inner_w, -inner_w)
        inner_p = QPainterPath()
        inner_p.addRoundedRect(inner_rect, max(1.0, radius - inner_w), max(1.0, radius - inner_w))
        inner_band = path.subtracted(inner_p)
        p.setClipPath(inner_band)
        # Bottom-right dark edge
        g = QLinearGradient(
            QPointF(rect.center().x() + light_dx * rect.width() * 0.5, rect.center().y() + light_dy * rect.height() * 0.5),
            QPointF(rect.center().x() - light_dx * rect.width() * 0.5, rect.center().y() - light_dy * rect.height() * 0.5),
        )
        g.setColorAt(0.0, QColor(0, 4, 12, int(255 * inner_shadow_alpha)))
        g.setColorAt(0.3, QColor(0, 4, 12, int(255 * inner_shadow_alpha * 0.4)))
        g.setColorAt(0.6, QColor(0, 4, 12, 0))
        g.setColorAt(1.0, QColor(0, 4, 12, 0))
        p.setBrush(g)
        p.drawRoundedRect(rect, radius, radius)
        p.restore()

    # --- 6. Ultra-thin edge outline (cool tone, NOT white) ---
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(160, 200, 230, int(255 * 0.14)), 0.7))
    p.drawRoundedRect(rect.adjusted(0.35, 0.35, -0.35, -0.35), radius, radius)
    p.restore()


def draw_economy_glass_capsule(
    p: QPainter,
    rect: QRectF,
    *,
    hover: float = 0.0,
    active: bool = False,
    edge_width: float = 4.0,
) -> None:
    """Draw a capsule-shaped liquid glass row (offer items, category chips).

    Uses the same AndroidLiquidGlass-kmp principles at smaller scale:
    - Dark transparent center
    - Subtle edge refraction
    - Directional highlight on top-left
    - No white fill or white border
    """
    h = max(0.0, min(1.0, hover))
    radius = rect.height() * 0.5
    if rect.width() < 4.0 or rect.height() < 4.0:
        return

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    # Dark glass center
    tint_a = 0.08 + 0.06 * h + (0.08 if active else 0.0)
    p.save()
    p.setClipPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(10, 20, 32, int(255 * tint_a)))
    p.drawRoundedRect(rect, radius, radius)

    # Edge refraction band (subtle)
    ew = max(2.0, edge_width)
    inner_rect = rect.adjusted(ew, ew, -ew, -ew)
    inner_path = QPainterPath()
    inner_path.addRoundedRect(inner_rect, max(1.0, radius - ew), max(1.0, radius - ew))
    edge_band = path.subtracted(inner_path)
    p.setClipPath(edge_band)
    edge_a = 0.06 + 0.08 * h + (0.12 if active else 0.0)
    # Top highlight (light from above-left)
    g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + ew * 2)
    g.setColorAt(0.0, QColor(180, 225, 255, int(255 * edge_a)))
    g.setColorAt(1.0, QColor(180, 225, 255, 0))
    p.setBrush(g)
    p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), ew * 2))
    # Bottom subtle shadow
    g = QLinearGradient(rect.left(), rect.bottom(), rect.left(), rect.bottom() - ew * 1.5)
    g.setColorAt(0.0, QColor(0, 8, 16, int(255 * edge_a * 0.6)))
    g.setColorAt(1.0, QColor(0, 8, 16, 0))
    p.setBrush(g)
    p.drawRect(QRectF(rect.left(), rect.bottom() - ew * 1.5, rect.width(), ew * 1.5))
    p.restore()

    # Teal edge outline for active/hover (NOT white)
    outline_a = 0.08 + 0.16 * h + (0.28 if active else 0.0)
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(92, 231, 216, int(255 * outline_a)), 0.8))
    p.drawRoundedRect(rect.adjusted(0.4, 0.4, -0.4, -0.4), radius, radius)
    p.restore()

def draw_economy_glass_well(
    p: QPainter,
    rect: QRectF,
    radius: float,
) -> None:
    """Draw a floating island well (left/list/detail columns).

    Subtle recessed glass container — darker than the main panel,
    with soft inner shadow to indicate depth.
    """
    if rect.width() < 4.0 or rect.height() < 4.0:
        return

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    # Recessed dark fill
    p.save()
    p.setClipPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(6, 12, 22, int(255 * 0.18)))
    p.drawRoundedRect(rect, radius, radius)

    # Inner shadow from top (recessed look)
    g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + radius * 1.2)
    g.setColorAt(0.0, QColor(0, 0, 0, int(255 * 0.12)))
    g.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setBrush(g)
    p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), radius * 1.2))

    # Bottom inner highlight (light bouncing from below)
    g = QLinearGradient(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius * 0.8)
    g.setColorAt(0.0, QColor(140, 200, 240, int(255 * 0.04)))
    g.setColorAt(1.0, QColor(140, 200, 240, 0))
    p.setBrush(g)
    p.drawRect(QRectF(rect.left(), rect.bottom() - radius * 0.8, rect.width(), radius * 0.8))
    p.restore()

    # Ultra-subtle edge
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(120, 180, 220, int(255 * 0.08)), 0.6))
    p.drawRoundedRect(rect.adjusted(0.3, 0.3, -0.3, -0.3), radius, radius)
    p.restore()
