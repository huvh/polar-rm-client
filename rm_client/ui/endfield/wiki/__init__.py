"""Endfield Wiki 终端功能包；窗口只依赖这里导出的界面与输入接口。"""
from rm_client.ui.endfield.wiki.renderer import EndfieldWikiRenderer
from rm_client.ui.endfield.wiki.state import EndfieldWikiState, EndfieldWikiTimeline
from rm_client.ui.endfield.wiki.navigation import (
    handle_wiki_action, handle_wiki_key, wiki_active, prepare_module_selection,
)
from rm_client.ui.endfield.wiki.list_input import handle_list_pointer, note_wiki_wheel
from rm_client.ui.endfield.wiki.ime import handle_wiki_input_method, wiki_input_method_query

__all__ = (
    "EndfieldWikiRenderer", "EndfieldWikiState", "EndfieldWikiTimeline",
    "handle_wiki_action", "handle_wiki_key", "wiki_active", "prepare_module_selection",
    "handle_list_pointer",
    "note_wiki_wheel",
    "handle_wiki_input_method", "wiki_input_method_query",
)
