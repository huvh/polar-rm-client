from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor


def color(hex_value: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_value)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


@dataclass
class PolarTheme:
    bg: QColor = field(default_factory=lambda: color("#08090c"))
    panel: QColor = field(default_factory=lambda: color("#101014", 0.94))
    panel_soft: QColor = field(default_factory=lambda: color("#ffffff", 0.08))
    row_hover: QColor = field(default_factory=lambda: color("#ffffff", 0.08))
    text: QColor = field(default_factory=lambda: color("#ffffff"))
    muted: QColor = field(default_factory=lambda: color("#aaaaaa"))
    dim: QColor = field(default_factory=lambda: color("#000000", 0.32))
    green: QColor = field(default_factory=lambda: color("#4caf50"))
    gray: QColor = field(default_factory=lambda: color("#9e9e9e"))
    accent: QColor = field(default_factory=lambda: color("#ffffff"))
    cyan: QColor = field(default_factory=lambda: color("#56fff0"))
    pink: QColor = field(default_factory=lambda: color("#ff65df"))
    blue: QColor = field(default_factory=lambda: color("#2ab4ff"))
    red: QColor = field(default_factory=lambda: color("#ff5555"))
    orange: QColor = field(default_factory=lambda: color("#ff9f43"))


THEME = PolarTheme()
