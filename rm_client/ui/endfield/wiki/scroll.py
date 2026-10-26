"""目录惯性和越界回弹；边界位置与暂态拉伸分开保存，不影响所选模块。"""
from dataclasses import dataclass
import math


@dataclass
class ScrollEdge:
    offset: float = 0
    distance: float = 0
    origin: float = 0
    extent: float = 1
    released_at: float | None = None

    def pull(self, distance, extent):
        self.extent = max(1,extent)
        self.distance = distance
        self.offset = math.copysign((1-1/(abs(distance)*.55/max(1,extent)+1))*extent,distance)
        self.released_at = None

    def release(self, now):
        self.origin, self.released_at = self.offset, now

    def advance(self, now):
        if self.released_at is not None:
            # 源ScrollRect的elasticity=.1秒；临界阻尼回到边界，不因帧率改变总时长。
            t = max(0,now-self.released_at)
            self.offset = self.origin*(1+20*t)*math.exp(-20*t)
            if abs(self.offset)<.05:
                self.offset = self.distance = 0
            else:
                self.distance = math.copysign(abs(self.offset)*self.extent/(.55*(self.extent-abs(self.offset))),self.offset)


def edge_offset(state, key):
    edge = state.list_edges.get(key)
    return edge.offset if edge else 0


def pull_edge(state, key, overflow, extent):
    edge = state.list_edges.setdefault(key,ScrollEdge())
    edge.pull(overflow,extent)
    return edge


def wheel_edge(state, key, current, delta, maximum, extent):
    """滚轮到边界仍给出阻力位移，反向滚动立即交回正常目录。"""
    edge = state.list_edges.get(key)
    raw = current+delta
    overflow = raw-max(0,min(maximum,raw))
    if maximum>0 and overflow:
        distance = overflow+(edge.distance if edge and edge.offset*overflow>0 else 0)
        edge = pull_edge(state,key,distance,extent)
        edge.release(state.clock())
    else:
        state.list_edges.pop(key,None)


def advance_inertia(state):
    for key,edge in tuple(state.list_edges.items()):
        edge.advance(state.clock())
        if edge.released_at is not None and edge.offset==0:
            state.list_edges.pop(key,None)
    if not state.list_fling:
        return
    key,velocity,maximum,at = state.list_fling
    now = state.clock()
    dt = max(0,now-at)
    decay = .135**dt
    delta = velocity*(decay-1)/math.log(.135)
    raw = state.panel_scroll.get(key,0)+delta
    value = max(0,min(maximum,raw))
    state.panel_scroll[key] = value
    if raw!=value:
        # 惯性撞到边缘也要先出现越界位移，再回弹。
        edge = pull_edge(state,key,raw-value,756*state.list_scale)
        edge.release(now)
    state.list_fling = (key,velocity*decay,maximum,now) if abs(velocity*decay)>5 and raw==value else None
