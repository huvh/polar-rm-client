"""rm_client.ui.polar 子包（REFACTOR_BLUEPRINT §5 阶段 1 起逐步承接 polar_app.py 外迁符号）。

兼容面以 ``rm_client.ui.polar_app`` 为准；本包当前只做最小 re-export。
"""

from .primitives import (
    EconomyScenePhase,
    FrameScheduler,
    Hotspot,
    InertialScroll,
    ModuleListLayout,
    StartupLayerCache,
)
from .text_metrics import TextMetricsMixin

__all__ = [
    "EconomyScenePhase",
    "FrameScheduler",
    "Hotspot",
    "InertialScroll",
    "ModuleListLayout",
    "StartupLayerCache",
    "TextMetricsMixin",
]
