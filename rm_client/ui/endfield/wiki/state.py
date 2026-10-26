"""终端 Wiki 页面状态与过渡生命周期；配置值由原模块注册表持有。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import time

from rm_client.model import CATEGORIES
from rm_client.ui.jello_clickgui import JelloClickGuiState, JelloReversibleAnimation
from rm_client.ui.endfield.wiki.motion import WikiHomeHover
from rm_client.ui.endfield.wiki.scroll import advance_inertia


@dataclass
class EndfieldWikiState(JelloClickGuiState):
    clock: Callable[[], float] = field(default_factory=lambda: time.perf_counter, repr=False)
    page_from: tuple[str | None, str | None] | None = None
    page_changed_at: float = -100.0
    module_from: str | None = None
    module_changed_at: float = -100.0
    row_changes: dict[str, tuple[bool, float]] = field(default_factory=dict)
    row_hovers: dict[str, tuple[bool, float]] = field(default_factory=dict)
    search_open: bool = False
    search_started_at: float = -100.0
    search_closing_at: float | None = None
    search_last_query: str = ""
    search_content_at: float = -100.0
    search_on_closed: Callable[[], None] | None = field(default=None, repr=False)
    category: str | None = None
    category_time: float = 0.0
    category_selection: dict[str, str] = field(default_factory=dict)
    reveal_module: bool = False
    page_time: float = 0.0
    session_time: float = 0.0
    focus_index: int = -1
    search_history: list[str] = field(default_factory=list)
    search_preedit: str = ""
    search_selection: str = ""
    search_from: str | None = None
    search_changed_at: float = -100.0
    dropdown_focus: int = -1
    home_hovers: dict[str, WikiHomeHover] = field(default_factory=dict)
    list_fling: tuple | None = None
    list_edges: dict = field(default_factory=dict)
    list_scale: float = 1
    background_route: str = "home"
    background_changed_at: float = -100
    background_serial: int = 0

    def begin_session(self, now=None) -> None:
        super().begin_session(now)
        self.category = None
        self.category_time = 0.0
        self.page_time = 0.0
        self.session_time = 0.0
        self.background_route = "home"
        self.background_changed_at = self.clock()
        self.background_serial += 1
        self.focus_index = -1
        self.search_preedit = ""
        self.search_selection = ""
        self.search_from = None
        self.search_changed_at = -100.0
        self.home_hovers.clear()
        self.list_fling = None
        self.list_edges.clear()
        self.page_from = None
        self.page_changed_at = -100.0
        self.module_from = None
        self.module_changed_at = -100.0
        self.row_changes.clear()
        self.row_hovers.clear()
        self.search_open = False
        self.search_closing_at = None
        self.search_on_closed = None
        self.search_last_query = ""

    def update(self, dt: float) -> None:
        super().update(dt)
        self.page_time += max(0.0, dt)
        self.category_time += max(0.0, dt)
        self.session_time += max(0.0, dt)
        self.advance_visuals()

    def advance_visuals(self) -> None:
        """退场结束后执行路由回调；由 UI 更新周期调用，不在绘制中跳转。"""
        advance_inertia(self)
        if self.search_closing_at is not None and self.clock() - self.search_closing_at >= 1 / 6:
            callback = self.search_on_closed
            self.search_open = False
            self.search_closing_at = None
            self.search_on_closed = None
            if callback:
                callback()

    def request_reset(self) -> None:
        self.list_fling = None
        self.list_edges.clear()
        self.search_on_closed = None
        super().request_reset()

    def home_hover(self, category: str, hovered: bool, now: float, motion=None):
        if category not in self.home_hovers:
            self.home_hovers[category] = WikiHomeHover(changed_at=now)
        return self.home_hovers[category].sample(hovered, now, motion)

    def navigate(self, category: str | None) -> None:
        self.list_fling = None
        self.list_edges.clear()
        if category is not None and category not in CATEGORIES:
            return
        self.prepare_selection(category, None)
        self.close_settings(immediate=True)
        self.category = category
        self.category_time = 0.0
        self.page_time = 0.0
        self.focus_index = -1
        self.reveal_module = True

    def prepare_selection(self, category: str | None, module: str | None) -> None:
        """逻辑目标立即更新，旧页面保留到原退场曲线结束，绘制期间不改配置。"""
        now = self.clock()
        if category != self.category:
            self.background_route = "group" if category is not None else "home"
            self.background_changed_at = now
            self.background_serial += 1
            self.page_from = (self.category, self.settings_module)
            self.page_changed_at = now
            self.module_from = None
            self.row_changes.clear()
        elif module and self.settings_module and module != self.settings_module:
            # 本体 ItemBig 的淡入为 1/3 秒；连续选择共用当前过渡，避免旧内容重新闪亮。
            if not self.module_from or now - self.module_changed_at >= 1 / 3:
                self.module_from = self.settings_module
                self.module_changed_at = now
            self.row_changes[self.settings_module] = (False, now)
            self.row_changes[module] = (True, now)

    def open_search(self) -> None:
        if not self.search_open or self.search_closing_at is not None:
            self.search_started_at = self.clock()
            self.search_content_at = self.search_started_at
            self.reset_search_selection()
        self.search_open = True
        self.search_closing_at = None

    def close_search(self) -> None:
        if self.search_open and self.search_closing_at is None:
            self.search_closing_at = self.clock()

    def reset_search_selection(self) -> None:
        """查询和覆盖层生命周期变更时，不把旧结果的预览带入新列表。"""
        self.search_selection = ""
        self.search_from = None
        self.search_changed_at = -100.0
        self.row_changes = {k:v for k,v in self.row_changes.items() if not k.startswith("search:")}

    def select_search(self, module_name: str) -> None:
        """鼠标和键盘共用预览切换；快速连续选择保持最初淡出的内容与同一时钟。"""
        if module_name == self.search_selection:
            return
        now = self.clock()
        if self.search_selection:
            if not self.search_from or now-self.search_changed_at >= 1/3:
                self.search_from,self.search_changed_at = self.search_selection,now
            self.row_changes["search:"+self.search_selection] = (False,now)
            self.row_changes["search:"+module_name] = (True,now)
        self.search_selection = module_name

    def row_hover(self, module: str, hovered: bool, now: float) -> float:
        previous, changed = self.row_hovers.get(module, (False, now - .1))
        if hovered != previous:
            changed = now
            self.row_hovers[module] = (hovered, changed)
        return 1.0 if hovered else max(0.0, 1.0 - (now - changed) / .1)

    def open_settings(self, module_name: str) -> None:
        if self.settings_module == module_name and not self.settings_closing:
            return
        super().open_settings(module_name)
        self.page_time = 0.0
        self.focus_index = -1

    def remember_search(self, query: str) -> None:
        query = query.strip()
        if query:
            self.search_history[:] = [query, *(v for v in self.search_history if v != query)][:3]

    def toggle_dropdown(self, key: str) -> None:
        super().toggle_dropdown(key)
        self.dropdown_focus = -1


class EndfieldWikiTimeline(JelloReversibleAnimation):
    """Wiki 的淡入淡出时钟；不使用原 ClickGUI 的弹性缩放。"""
    def __init__(self, enter: float = 0.75, leave: float = 1 / 6) -> None:
        super().__init__(enter, leave)

    def visual_factor(self) -> float:
        return 1.0 - (1.0 - self.progress) ** 3

    def blur_radius(self) -> float:
        return 0.0
