"""搜索输入法的预编辑、提交长度和未接管查询边界。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from rm_client.ui.endfield.wiki import EndfieldWikiState
from rm_client.ui.endfield.wiki.ime import handle_wiki_input_method, wiki_input_method_query


class WikiInputMethodTests(unittest.TestCase):
    def host(self):
        return SimpleNamespace(gui_visible=True, search_focus=True, search_query="装甲",
                               jello_state=EndfieldWikiState(), invalidate_gui_cache=Mock(),
                               frame_scheduler=SimpleNamespace(force=Mock()), update=Mock(),
                               width=lambda: 1280)

    def test_preedit_is_displayed_without_committing_and_commit_is_bounded(self):
        host = self.host()
        event = QInputMethodEvent("mubiao", [])
        self.assertTrue(handle_wiki_input_method(host, event))
        self.assertEqual(host.search_query, "装甲")
        self.assertEqual(host.jello_state.search_preedit, "mubiao")
        event = QInputMethodEvent()
        event.setCommitString("目标" * 100)
        self.assertTrue(handle_wiki_input_method(host, event))
        self.assertEqual(len(host.search_query), 128)
        self.assertEqual(host.jello_state.search_preedit, "")
        self.assertEqual(host.jello_state.focus_index, -1)
        self.assertEqual(host.frame_scheduler.force.call_count, 2)

    def test_unfocused_or_legacy_page_cannot_consume_input_method_events(self):
        host = self.host()
        for mode in ("unfocused", "legacy", "hidden"):
            host.search_focus, host.gui_visible, host.jello_state.legacy_mode = True, True, None
            if mode == "unfocused":
                host.search_focus = False
            elif mode == "legacy":
                host.jello_state.legacy_mode = "JelloSigma"
            else:
                host.gui_visible = False
            event = Mock()
            self.assertFalse(handle_wiki_input_method(host, event))
            event.commitString.assert_not_called()
            self.assertEqual(wiki_input_method_query(host, Qt.InputMethodQuery.ImEnabled), (False, None))

    def test_known_queries_and_unknown_query_fallback_are_distinct(self):
        host = self.host()
        self.assertEqual(wiki_input_method_query(host, Qt.InputMethodQuery.ImSurroundingText), (True, "装甲"))
        self.assertEqual(wiki_input_method_query(host, Qt.InputMethodQuery.ImCursorPosition), (True, 2))
        self.assertEqual(wiki_input_method_query(host, Qt.InputMethodQuery.ImFont), (False, None))
        handled, rect = wiki_input_method_query(host, Qt.InputMethodQuery.ImCursorRectangle)
        self.assertTrue(handled)
        self.assertGreater(rect.width(), 0)
        self.assertGreater(rect.height(), 0)


if __name__ == "__main__":
    unittest.main()
