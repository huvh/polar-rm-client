"""rm_client.ui.polar.renderers 子包（REFACTOR_BLUEPRINT §5 阶段 2：渲染器提取）。

每个模块承载一个渲染域的 Mixin（方法体自 polar_app.py 机械迁入、零修改），
由 ``polar_app.PolarRMWindow`` 继承装配，保持 ``window.<成员>`` 冻结面不变。
"""

from .combat_target_hud import CombatTargetHudMixin

__all__ = [
    "CombatTargetHudMixin",
]
