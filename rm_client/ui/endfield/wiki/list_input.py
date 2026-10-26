"""二级列表的单击/上下拖动/惯性归属；拖动不得选中模块或触发控制输出。"""
from PySide6.QtCore import QPointF, Qt
from rm_client.ui.endfield.wiki.state import EndfieldWikiState
from rm_client.ui.endfield.wiki.scroll import edge_offset, pull_edge, wheel_edge


def note_wiki_wheel(host, key, delta, maximum, *, settings=False):
    """在原滚轮路由前记录边界反馈，原路由继续持有实际滚动位置。"""
    state = host.jello_state
    if not isinstance(state,EndfieldWikiState):
        return
    viewport = next((v for v in host.gui_scroll_viewports if v["key"]==key),None)
    if viewport:
        current = state.settings_scroll_target(key) if settings else state.panel_scroll.get(key,0)
        wheel_edge(state,key,current,delta,maximum,viewport["rect"].height())


def handle_list_pointer(host, event, phase):
    state = getattr(host,"jello_state",None)
    if not isinstance(state,EndfieldWikiState):
        return False
    interaction = host.pointer_interaction
    drag = interaction.drag
    point = event.position()
    if phase == "press":
        if not host.gui_visible or event.button() != Qt.MouseButton.LeftButton or state.dropdown_key:
            return False
        viewport = next((v for v in reversed(host.gui_scroll_viewports)
                         if v["mode"] == "jello_panel" and v["rect"].contains(point)),None)
        if viewport is None:
            return False
        target = next((h for h in reversed(host.hotspots) if h.rect.contains(point)
                       and h.action in ("jello_open_settings","wiki_search_select")),None)
        state.list_fling = None
        edge = state.list_edges.get(viewport["key"])
        if edge:
            edge.advance(state.clock())
            edge.released_at = None
        interaction.drag = {"type":"wiki_list","viewport":dict(viewport),"start":QPointF(point),
            "last":QPointF(point),"at":state.clock(),"scroll":state.panel_scroll.get(viewport["key"],0)+(edge.distance if edge else 0),
            "moved":False,"velocity":0,"target":target}
        interaction.own_release()
        event.accept()
        return True
    if not drag or drag.get("type") != "wiki_list":
        return False
    if phase == "release" and event.button() != Qt.MouseButton.LeftButton:
        event.accept()
        return True
    viewport = drag["viewport"]
    distance = point.y()-drag["start"].y()
    if (point-drag["start"]).manhattanLength() >= 6:
        drag["moved"] = True
    if phase == "move" and drag["moved"]:
        now = state.clock()
        dt = max(.001,now-drag["at"])
        drag["velocity"] = max(-2500,min(2500,-(point.y()-drag["last"].y())/dt))
        drag["last"],drag["at"] = QPointF(point),now
        host.hover_point = QPointF(point)
        host.hover_tooltip = ""
        raw = drag["scroll"]-distance
        bounded = max(0,min(viewport["maximum"],raw))
        state.panel_scroll[viewport["key"]] = bounded
        pull_edge(state,viewport["key"],raw-bounded if viewport["maximum"]>0 else 0,viewport["rect"].height())
        state.focus_index,state.reveal_module = -1,False
    if phase == "release":
        interaction.take_drag()
        interaction.background_release_owned = False
        if drag["moved"]:
            velocity = drag["velocity"] if state.clock()-drag["at"] < .15 else 0
            if edge_offset(state,viewport["key"]):
                state.list_edges[viewport["key"]].release(state.clock())
            else:
                state.list_fling = (viewport["key"],velocity,viewport["maximum"],state.clock())
        elif drag["target"] and drag["target"].rect.contains(point):
            target = drag["target"]
            try:
                host.dispatch(target.action,target.payload,point,1,target.rect)
            finally:
                # 动作通常在press执行并登记待消费release；列表在release才分发，须在本次收尾。
                # 回调若建立了新的拖动，不能清掉新捕获的所有权。
                if interaction.drag is None:
                    interaction.release_background(point,left_button=True,
                        gui_visible=host.gui_visible,background_target=False)
        elif edge_offset(state,viewport["key"]):
            state.list_edges[viewport["key"]].release(state.clock())
    host.invalidate_gui_cache()
    host.frame_scheduler.force()
    host.update()
    event.accept()
    return True
