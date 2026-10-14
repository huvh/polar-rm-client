"""阶段 4 窗口壳收编（REFACTOR_BLUEPRINT §5 阶段 4 / 目标子包结构）：应用装配入口。

``main()``（QApplication GL 3.3 Core 装配 + 创建 PolarRMWindow）自
``rm_client/ui/polar_app.py`` 尾部机械迁入本模块（语句序列零修改）；
``polar_app`` 尾部以 ``from .polar.app_entry import main`` re-export，
维持 §5.6 模块级冻结符号 ``rm_client.ui.polar_app.main`` 的 import 兼容面：
外部触点仅 ``main.py:59`` 与 ``rm_client/app.py:655`` 两处（均经 polar_app
路径），``tests/api_freeze_test.py`` 对模块符号记录 kind=function +
sig=__qualname__，而模块级函数的 __qualname__ 恒为 ``"main"``，与基线一致。

终态决策（方案 A，保守；论证摘要）
----------------------------------
D0 构造/生命周期、D1 主循环 tick 编排、D2 GPU 帧编排/FBO 层管理、D3
paint_overlay CPU 绘制总线**保留在 polar_app.py 的 PolarRMWindow 原位**，
不做 WindowShellMixin 化：

1. 蓝图 §5 阶段 4 对最终形态的定义即"PolarRMWindow 壳（__init__/on_tick/
   paintGL/paint_overlay 分发器/VisionViewport/PolarHudOverlay）+ main()
   移至 app_entry 并 re-export"——D0-D3 本就是壳的核心编排，留原位符合蓝图；
2. ``__init__`` 是全文件事实上的状态 schema（~150 个状态字段、~60 个协作
   对象装配），且构造期直接调用多个 Mixin 方法（setting_bool /
   sync_quick_action_wheel_settings / apply_match_mode / load_startup_config
   等），初始化顺序由当前 MRO 保证；整体搬移属纯搬运高风险、零行为收益
   （蓝图对阶段 4 标注风险：高，缓解手段是"构造即冒烟"，而非鼓励搬移）；
3. 风险最小原则：本阶段唯一实质变更是 main() 的机械移动 + re-export，
   类成员零改动，冻结面（§5.6）不动。

循环依赖说明
------------
本模块顶层禁止 import ``rm_client.ui.polar_app``：polar_app 尾部的 re-export
会在其模块加载过程中执行本模块顶层代码，若彼处再 import polar_app 将命中
半初始化模块。因此 PolarRMWindow 采用**函数内延迟 import**——main() 被
调用时 polar_app 必已完整加载（无论调用方先 import 的是哪个模块）。
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication


def main() -> None:
    # 延迟 import：见模块 docstring"循环依赖说明"。放在函数体首行，
    # 其余语句保持自 polar_app.py 迁出时的原顺序（零修改）。
    from rm_client.ui.polar_app import PolarRMWindow

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        surface = QSurfaceFormat()
        surface.setVersion(3, 3)
        surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
        # 不让 30/60 Hz 图传或错误报告为 60 Hz 的桌面刷新率锁住 HUD。
        # 呈现节奏由 FrameScheduler 控制，视频纹理只在源帧变化时上传。
        # Present at the display cadence.  Unthrottled swaps were racing the
        # launcher FBO lifecycle on high-DPR Windows surfaces.
        from ..cs2_video_settings import configure_surface
        configure_surface(surface)
        surface.setDepthBufferSize(0)
        surface.setStencilBufferSize(0)
        QSurfaceFormat.setDefaultFormat(surface)
        app = QApplication(sys.argv)
    app.setApplicationName("POLAR-RM Custom Client")
    window = PolarRMWindow()
    window.show()
    from ..cs2_video_settings import restore_startup_window
    restore_startup_window(window)
    if owns_app:
        raise SystemExit(app.exec())
