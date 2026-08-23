"""阶段 1 叶子外迁：polar_app.py 顶层小类原样迁入（REFACTOR_BLUEPRINT §5 阶段 1）。

六个类体一行未改，纯机械移动；`rm_client.ui.polar_app` 顶部仍 re-export 全部
符号，`from rm_client.ui.polar_app import FrameScheduler` 等外部 import 面不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QLinearGradient, QPainter

from ..animation import step_damped_spring
from ..theme import color

__all__ = [
    "EconomyScenePhase",
    "Hotspot",
    "ModuleListLayout",
    "StartupLayerCache",
    "FrameScheduler",
    "InertialScroll",
]


class EconomyScenePhase(str, Enum):
    CLOSED = "closed"
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"


@dataclass
class Hotspot:
    rect: QRectF
    action: str
    payload: Any = None
    button: int | None = None
    tooltip: str = ""


@dataclass(frozen=True)
class ModuleListLayout:
    """ModuleList 使用的统一逻辑像素安全区。"""

    anchor_x: float
    anchor_y: float
    available_height: float
    row_height: float
    row_gap: float
    right_margin: float
    top_margin: float
    clip_rect: QRectF


class StartupLayerCache:
    def __init__(self) -> None:
        self._vignettes: dict[tuple[int, int], QImage] = {}

    def vignette(self, width: int, height: int) -> QImage:
        key = (width, height)
        image = self._vignettes.get(key)
        if image is not None:
            return image
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.fillRect(QRectF(0, 0, width, height), color("#56fff0", 0.018))
        center_glow = QLinearGradient(width * 0.5, height * 0.18, width * 0.5, height * 0.78)
        center_glow.setColorAt(0.0, color("#56fff0", 0.10))
        center_glow.setColorAt(0.45, color("#ff65df", 0.045))
        center_glow.setColorAt(1.0, color("#000000", 0.0))
        painter.fillRect(QRectF(0, 0, width, height), center_glow)
        painter.fillRect(QRectF(0, 0, width, height), color("#000000", 0.08))
        painter.end()
        if len(self._vignettes) > 4:
            self._vignettes.clear()
        self._vignettes[key] = image
        return image


class FrameScheduler:
    def __init__(self) -> None:
        self.last_request = 0.0
        self.next_request = 0.0

    def should_request(self, now: float, high_rate: bool, target_fps: float = 60.0) -> bool:
        interval = 1.0 / (max(30.0, target_fps) if high_rate else 15.0)
        # Keep an absolute deadline instead of measuring from the last timer
        # callback.  The old 0.86 threshold combined with a 5 ms QTimer made a
        # nominal 144 Hz render request miss every other tick (roughly 100 Hz
        # with an uneven 5/10 ms cadence).  A small early allowance absorbs
        # Windows timer quantisation without accumulating phase drift.
        if self.next_request <= 0.0:
            self.last_request = now
            self.next_request = now + interval
            return True
        early_allowance = min(0.0015, interval * 0.12)
        if now + early_allowance < self.next_request:
            return False
        self.last_request = now
        while self.next_request <= now + early_allowance:
            self.next_request += interval
        return True

    def force(self) -> None:
        self.last_request = 0.0
        self.next_request = 0.0


class InertialScroll:
    """单调时钟驱动的临界阻尼滚动，不依赖视频源帧率。"""

    def __init__(self) -> None:
        self.position = 0.0
        self.target = 0.0
        self.velocity = 0.0
        self.maximum = 0.0

    def set_bounds(self, maximum: float) -> None:
        self.maximum = max(0.0, float(maximum))
        self.target = max(0.0, min(self.maximum, self.target))
        self.position = max(0.0, min(self.maximum, self.position))

    def add_wheel(self, delta: float) -> None:
        self.target = max(0.0, min(self.maximum, self.target + float(delta)))

    def update(self, dt: float) -> float:
        # DynamicIsland 风格的快速临界阻尼：滚轮停止后约 220 ms 收敛。
        stiffness = 235.0
        self.position, self.velocity = step_damped_spring(
            self.position,
            self.velocity,
            self.target,
            dt,
            stiffness=stiffness,
            damping_ratio=1.0,
        )
        if abs(self.target - self.position) < 0.03 and abs(self.velocity) < 0.1:
            self.position = self.target
            self.velocity = 0.0
        return self.position

    @property
    def active(self) -> bool:
        return abs(self.target - self.position) > 0.03 or abs(self.velocity) > 0.1
