from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF


@dataclass
class HudAnchorStack:
    """Allocates bottom-left HUD elements without fixed, overlapping offsets."""

    left: float
    bottom: float
    gap: float = 8.0

    def take(self, width: float, height: float) -> QRectF:
        rect = QRectF(self.left, self.bottom - height, width, height)
        self.bottom = rect.top() - self.gap
        return rect
