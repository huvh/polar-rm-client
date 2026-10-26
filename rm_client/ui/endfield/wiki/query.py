"""按中英文名称、说明和设置搜索，返回原注册表对象。"""
from __future__ import annotations

from rm_client.ui.jello_locale import category_label, description_label, module_label, setting_label


def wiki_modules(registry, category: str | None, query: str):
    """搜索中文名、原 ID、说明及设置名，返回原 Module 对象。"""
    tokens = query.casefold().split()
    if not tokens:
        return tuple(module for module in registry.modules
                     if category is None or module.category == category)
    result = []
    for module in registry.modules:
        if category is not None and module.category != category:
            continue
        words = [module.name, module.description, module_label(module.name, True),
                 category_label(module.category, True), description_label(module.description, True)]
        for setting in module.settings:
            words.extend((setting.name, setting_label(setting.name, True), str(setting.value)))
        haystack = " ".join(words).casefold()
        if all(token in haystack for token in tokens):
            result.append(module)
    return tuple(result)
