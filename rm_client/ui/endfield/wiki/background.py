"""场景装饰的页面生命周期；原切换曲线与持续循环使用各自的时钟。"""
from dataclasses import dataclass, field
import math


CLIPS = ("wiki_uideco_in", "wiki_uideco_out", "wiki_uideco_grouppanel_in", "wiki_uideco_grouppanel_out")


@dataclass
class WikiBackground:
    clip: str = "wiki_uideco_in"
    started_at: float | None = None
    serial: int = -1
    route: str = "home"
    home_at: float | None = None
    closing: bool = False
    loop_epoch: float = 0
    held: dict = field(default_factory=dict)

    def sample(self, motion, path, attribute, now, default=0, axis=None):
        elapsed = max(0,now-self.started_at) if self.started_at is not None else motion.durations[self.clip]
        keys = motion.tracks.get((self.clip,path,attribute),())
        loop_path = path.removeprefix("HudNode/BgDecoLayout/")
        loop_key = "wiki_uideco_loop",loop_path,attribute
        if loop_key in motion.tracks and (not keys or elapsed>=keys[-1]["time"]):
            at = (now-self.loop_epoch)%motion.durations["wiki_uideco_loop"]
            return motion.sample(*loop_key,at,default,axis)
        if keys:
            return motion.sample(self.clip,path,attribute,elapsed,default,axis)
        return self.held.get((path,attribute,axis),default)

    def play(self, motion, clip, at):
        # Unity只写新片段绑定的属性，其余姿态保留；不能用默认值抹掉上一页已展开的图层。
        held = {}
        for (name,path,attribute),keys in motion.tracks.items():
            if name not in CLIPS or not keys:
                continue
            axes = tuple(keys[0]["value"]) if isinstance(keys[0]["value"],dict) else (None,)
            for axis in axes:
                held[path,attribute,axis] = self.sample(motion,path,attribute,at,0,axis)
        self.held,self.clip,self.started_at = held,clip,at

    def sync(self, motion, state, now, *, closing=False):
        self.loop_epoch = now-state.session_time
        if self.serial!=state.background_serial:
            old_route = self.route
            self.route,self.serial = state.background_route,state.background_serial
            self.home_at = None
            self.closing = False
            if self.route=="home" and old_route=="group" and self.started_at is not None:
                self.play(motion,"wiki_uideco_grouppanel_out",state.background_changed_at)
                # 当前页面退场1/6秒后，首页OnShow重新播放自身背景入场。
                self.home_at = state.background_changed_at+1/6
            else:
                self.play(motion,"wiki_uideco_grouppanel_in" if self.route=="group" else "wiki_uideco_in",
                          state.background_changed_at)
        if self.home_at is not None and now>=self.home_at:
            self.play(motion,"wiki_uideco_in",self.home_at)
            self.home_at = None
        if closing and not self.closing:
            self.play(motion,"wiki_uideco_out",now)
            self.home_at,self.closing = None,True

    def projection(self, motion, ground, now):
        """用Main/Common相同的透视镜头换算根Canvas位移、深度和缩放，保留终端首页基准位置。"""
        def value(attribute,default,axis=None):
            return self.sample(motion,"",attribute,now,default,axis)
        reference = [motion.sample("wiki_uideco_in","","m_AnchoredPosition."+axis,3,default)
                     for axis,default in (("x",-.43),("y",1.08))]
        x,y = (value("m_AnchoredPosition."+axis,base) for axis,base in zip("xy",reference))
        z = value("m_LocalPosition.z",0)
        base_scale = motion.sample("wiki_uideco_in","","m_ScaleCurves",3,.003,"x")
        scale = value("m_ScaleCurves",base_scale,"x")/base_scale
        camera = ground["camera_position"]
        depth = max(.1,camera["z"]-z)
        focal = 540/math.tan(math.radians(ground["source_uniforms"]["fov"])/2)
        cx = 960+focal*((camera["x"]-x)/depth-(camera["x"]-reference[0])/camera["z"])
        cy = 540-focal*((y-camera["y"])/depth-(reference[1]-camera["y"])/camera["z"])
        alpha = self.sample(motion,"HudNode","m_Alpha",now,1)
        return cx,cy,scale*camera["z"]/depth,alpha
