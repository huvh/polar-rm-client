"""Wiki 搜索的输入法提交、预编辑和候选框查询；窗口只转发 Qt 事件。"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt

from .navigation import wiki_active


def handle_wiki_input_method(host, event) -> bool:
    """仅搜索拥有焦点时消费输入法事件，其他界面继续走原有窗口处理。"""
    if not wiki_active(host) or not host.search_focus:
        return False
    host.search_query = (host.search_query + event.commitString())[:128]
    host.jello_state.search_preedit = event.preeditString()
    host.jello_state.focus_index = -1
    host.invalidate_gui_cache()
    host.frame_scheduler.force()
    host.update()
    event.accept()
    return True


def wiki_input_method_query(host, query) -> tuple[bool, object]:
    """返回是否接管及查询结果，避免把合法的 False/空字符串误判为未处理。"""
    if not wiki_active(host) or not host.search_focus:
        return False, None
    if query == Qt.InputMethodQuery.ImEnabled:
        return True, True
    if query == Qt.InputMethodQuery.ImSurroundingText:
        return True, host.search_query
    if query in (Qt.InputMethodQuery.ImCursorPosition, Qt.InputMethodQuery.ImAnchorPosition):
        return True, len(host.search_query)
    if query == Qt.InputMethodQuery.ImCursorRectangle:
        # 延续当前候选框位置；定位策略与 Wiki 搜索一起维护。
        return True, QRectF(host.width() * 0.83, 60, 1, 30)
    return False, None
