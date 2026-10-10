"""rm_client.ui.polar.mixins 子包（REFACTOR_BLUEPRINT §5 阶段 3：大域 mixin 化）。

每个模块承载一个大功能域的 Mixin（方法体自 polar_app.py 机械迁入、零修改），
由 ``polar_app.PolarRMWindow`` 继承装配，保持 ``window.<成员>`` 冻结面不变。
"""

from .persistence_mixin import PersistenceMixin

__all__ = [
    "PersistenceMixin",
]
