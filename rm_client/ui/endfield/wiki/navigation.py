"""Wiki 页面导航、搜索模态及输入路由；通过原 host 分发设置动作。"""
from __future__ import annotations

from PySide6.QtCore import Qt

from rm_client.model import CATEGORIES
from rm_client.ui.endfield.wiki.state import EndfieldWikiState
from rm_client.ui.endfield.wiki.query import wiki_modules


def prepare_module_selection(host, module, point, button, rect) -> bool:
    """准备原模块选择；搜索退场或重复选择已消费动作时返回True。"""
    if not isinstance(host.jello_state, EndfieldWikiState):
        return False
    if host.pointer_interaction.drag and host.pointer_interaction.drag.get("type") == "wiki_list":
        host.pointer_interaction.cancel_epoch()
    host.jello_state.list_fling = None
    host.jello_state.list_edges.clear()
    if host.jello_state.search_open:
        if host.jello_state.search_closing_at is None:
            host.jello_state.remember_search(host.search_query)
            host.jello_state.search_last_query = host.search_query
            host.jello_state.close_search()
            host.jello_state.search_on_closed = lambda: host.dispatch(
                "jello_open_settings", module.name, point, button, rect)
            host.search_focus = False
            host.frame_scheduler.force()
        return True
    if host.jello_state.settings_module == module.name and host.jello_state.category == module.category:
        host.jello_state.remember_search(host.search_query)
        host.search_focus = False
        host.search_query = ""
        host.hover_tooltip = ""
        host.jello_state.search_preedit = ""
        host.frame_scheduler.force()
        return True
    host.jello_state.prepare_selection(module.category, module.name)
    host.jello_state.search_open = False
    host.jello_state.search_closing_at = None
    host.jello_state.remember_search(host.search_query)
    host.search_focus = False
    host.search_query = ""
    host.hover_tooltip = ""
    host.jello_state.search_preedit = ""
    if host.jello_state.category != module.category:
        host.jello_state.category_time = 0.0
    host.jello_state.category = module.category
    host.jello_state.category_selection[module.category] = module.name
    host.jello_state.reveal_module = True
    return False


def wiki_active(host) -> bool:
    state = getattr(host, "jello_state", None)
    return bool(getattr(host, "gui_visible", False)
                and isinstance(state, EndfieldWikiState) and state.legacy_mode is None)


def wiki_enter_category(host, category: str) -> None:
    """一级入口直接打开二级目录及其三级设置，复用原模块选择路由。"""
    modules = wiki_modules(host.registry, category, "")
    if category not in CATEGORIES:
        return
    state = host.jello_state
    previous = state.settings_module if state.category == category else state.category_selection.get(category)
    state.navigate(category)
    if modules:
        module = next((m for m in modules if m.name == previous), modules[0])
        host.dispatch("jello_open_settings", module.name, host.hover_point, 1, host.rect())


def wiki_back(host) -> None:
    state = host.jello_state
    state.advance_visuals()
    if state.page_from is not None and state.clock() - state.page_changed_at < 1 / 6:
        return
    if state.dropdown_key is not None:
        state.close_dropdown(immediate=True)
    elif state.search_open or host.search_focus or host.search_query:
        state.search_on_closed = None
        if not state.search_open:
            state.open_search()
        if state.search_closing_at is None:
            state.search_last_query = host.search_query
        state.close_search()
        host.search_focus = False
        host.search_query = ""
        state.focus_index = -1
    elif state.category is not None or state.settings_active:
        state.navigate(None)
    else:
        close_to_escape(host)


def close_to_escape(host) -> None:
    """终端退出返回 Esc 模态，沿用原输入清空与原生菜单生命周期。"""
    host.set_clickgui_visible(False)
    host.set_escape_menu_visible(True)


def handle_wiki_action(host, action, payload, button: int) -> bool:
    if not action.startswith("wiki_") or not wiki_active(host):
        return False
    if button != 1:
        return True
    host.pointer_interaction.own_release()
    state = host.jello_state
    state.list_fling = None
    state.list_edges.clear()
    if action == "wiki_category":
        state.search_open = False
        state.search_closing_at = None
        host.search_focus = False
        host.search_query = ""
        wiki_enter_category(host, str(payload))
    elif action == "wiki_home":
        state.search_open = False
        state.search_closing_at = None
        host.search_focus = False
        host.search_query = ""
        state.navigate(None)
    elif action == "wiki_back":
        wiki_back(host)
    elif action == "wiki_close":
        if state.category is not None or state.search_open:
            wiki_back(host)
        else:
            close_to_escape(host)
    elif action == "wiki_search":
        state.close_dropdown(immediate=True)
        state.open_search()
        host.search_focus = True
        state.focus_index = -1
        state.page_time = 0.0
    elif action == "wiki_search_select":
        results = wiki_modules(host.registry, None, host.search_query)
        state.focus_index = next((i for i, module in enumerate(results) if module.name == payload), 0)
        state.select_search(str(payload))
    elif action == "wiki_clear_search":
        host.search_query = ""
        host.search_focus = True
        state.focus_index = -1
    elif action == "wiki_submit_search":
        state.remember_search(host.search_query)
        state.search_content_at = state.clock()
        state.focus_index = 0
        host.search_focus = False
    elif action == "wiki_history":
        host.search_query = str(payload)
        host.search_focus = True
        state.focus_index = -1
    elif action == "wiki_copy_text":
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(str(payload))
    host.hover_tooltip = ""
    if not host.search_focus:
        state.search_preedit = ""
    host.invalidate_gui_cache()
    host.frame_scheduler.force()
    host.update()
    return True


def handle_wiki_key(host, event) -> bool:
    """在其他模块快捷键之前接管整页输入，保留最外层 F12 急停优先级。"""
    if not wiki_active(host):
        return False
    state, key = host.jello_state, event.key()
    if host.pointer_interaction.drag and host.pointer_interaction.drag.get("type") == "wiki_list":
        host.pointer_interaction.cancel_epoch()
    state.list_fling = None
    state.list_edges.clear()
    module = host.registry.get(state.settings_module or "")
    dropdown = next((setting for setting in module.settings
                     if f"{module.name}:{setting.name}" == state.dropdown_key), None) if module else None
    releases = getattr(host, "_wiki_key_releases", set())
    releases.add(key)
    host._wiki_key_releases = releases
    if (host.search_focus or host.search_query.strip()) and not state.search_open:
        state.open_search()
    transitioning = (state.search_closing_at is not None or
                     state.page_from is not None and state.clock() - state.page_changed_at < 1 / 6)
    if transitioning and key not in (Qt.Key.Key_F8, Qt.Key.Key_Escape) and not host.is_right_shift_event(event):
        event.accept()
        return True
    if key == Qt.Key.Key_F8 or host.is_right_shift_event(event):
        if not event.isAutoRepeat():
            host.set_clickgui_visible(False)
    elif key == Qt.Key.Key_Escape:
        if not event.isAutoRepeat():
            wiki_back(host)
    elif key == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        state.open_search()
        host.search_focus = True
        state.page_time = 0.0
    elif key == Qt.Key.Key_Backspace:
        if host.search_focus:
            host.search_query = host.search_query[:-1]
            state.focus_index = -1
        elif not event.isAutoRepeat():
            wiki_back(host)
    elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Tab):
        searching = bool(host.search_query.strip()) or host.search_focus
        items = wiki_modules(host.registry, None if searching else state.category, host.search_query)
        count = len(dropdown.options) if dropdown else (
            6 if state.category is None and not searching and not state.settings_active else len(items))
        if count:
            backwards = key in (Qt.Key.Key_Left, Qt.Key.Key_Up) or (
                key == Qt.Key.Key_Tab and event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if dropdown:
                current = (state.dropdown_focus if state.dropdown_focus >= 0 else
                           next((i for i,v in enumerate(dropdown.options) if v == dropdown.value), 0))
                state.dropdown_focus = (current + (-1 if backwards else 1)) % count
            else:
                current = state.focus_index
                if state.category is not None and not searching:
                    current = next((i for i, m in enumerate(items) if m.name == state.settings_module), 0)
                index = (current + (-1 if backwards else 1)) % count
                if state.category is not None and not searching:
                    host.dispatch("jello_open_settings", items[index].name, host.hover_point, 1, host.rect())
                elif searching:
                    state.select_search(items[index].name)
                state.focus_index = index
            # 滚动焦点进入可视区域；由绘制层按实际布局计算范围。
    elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        if not event.isAutoRepeat():
            searching = bool(host.search_query.strip()) or host.search_focus
            if dropdown:
                index = state.dropdown_focus if state.dropdown_focus >= 0 else next(
                    (i for i,v in enumerate(dropdown.options) if v == dropdown.value), 0)
                host.dispatch("jello_mode_select", (dropdown, dropdown.options[index]), host.hover_point, 1, host.rect())
            elif state.category is None and not searching and not state.settings_active:
                wiki_enter_category(host, CATEGORIES[max(0, state.focus_index)])
            elif not state.settings_active or searching:
                items = wiki_modules(host.registry, None if searching else state.category, host.search_query)
                if items:
                    index = state.focus_index if state.focus_index >= 0 else next(
                        (i for i,m in enumerate(items) if searching and m.name == state.search_selection), 0)
                    module = items[index % len(items)]
                    host.dispatch("jello_open_settings", module.name, host.hover_point, 1, host.rect())
    elif host.search_focus:
        if event.text() and event.text().isprintable():
            host.search_query = (host.search_query + event.text())[:128]
            state.focus_index = -1
    host.hover_tooltip = ""
    if not host.search_focus:
        state.search_preedit = ""
    host.invalidate_gui_cache()
    host.frame_scheduler.force()
    host.update()
    event.accept()
    return True
