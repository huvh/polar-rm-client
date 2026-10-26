"""本体UIScrollRect参数驱动的滚动状态；位置与边界外弹性位移统一以逻辑像素保存。"""
from __future__ import annotations

import math


def rubber_distance(distance, extent):
    """Unity ScrollRect 的 .55 边界阻力，方向保持不变。"""
    return math.copysign(extent*(1-1/(abs(distance)*.55/max(1,extent)+1)),distance)


class ScrollMotion:
    def __init__(self, config):
        if config["smoothScrollTweenEase"] != 3:
            raise ValueError("设置资源的滚动缓动类型尚未支持")
        self.config = config
        self.position = self.target = self.velocity = 0.0
        self.mode = "idle"
        self.maximum = 0.0
        self.extent = 1.0
        self.scale = 1.0
        self._previous = 0.0
        self._elapsed = 0.0

    def bound(self, value):
        return max(0,min(self.maximum,value))

    def stop(self, *, clamp=False):
        self.mode = "idle"
        self.velocity = 0.0
        if clamp:
            self.position = self.bound(self.position)
        self.target = self.position

    def smooth_to(self, target, *, elastic=False):
        if self.maximum <= 0:
            self.stop(clamp=True)
            return
        boundary = self.bound(target)
        self.target = boundary + (rubber_distance(target-boundary,self.extent) if elastic else 0)
        self._origin = self.position
        self._elapsed = 0.0
        self._duration = min(self.config["smoothScrollTweenMaxDur"],
                             abs(self.target-self.position)/max(1,self.config["smoothScrollTweenSpd"]*self.scale))
        self.velocity = 0.0
        self.mode = "tween" if self._duration>0 else "idle"

    def wheel(self, delta):
        pending = self.target if self.mode == "tween" else self.position
        if (pending-self.position)*delta < 0:
            pending = self.position
        self.smooth_to(pending+delta,elastic=self.config["m_MovementType"] == 1)

    def begin_drag(self):
        self.stop()
        boundary = self.bound(self.position)
        edge = self.position-boundary
        # 反解RubberDelta，边界外重新按下时不让内容跳回边界。
        raw = math.copysign(abs(edge)*self.extent/(.55*max(.001,self.extent-abs(edge))),edge)
        self._drag_origin = boundary+raw
        self._previous = self.position
        self.mode = "drag"

    def drag(self, distance):
        raw = self._drag_origin+distance
        boundary = self.bound(raw)
        self.position = boundary+rubber_distance(raw-boundary,self.extent)

    def release(self):
        self.mode = "elastic" if self.position != self.bound(self.position) else "inertia"
        if not self.config["m_Inertia"]:
            self.velocity = 0.0

    def advance(self, dt):
        if dt <= 0 or self.mode == "idle":
            return
        if self.mode == "drag":
            current = (self.position-self._previous)/dt
            self.velocity += (current-self.velocity)*min(1,dt*10)
            self._previous = self.position
            return
        if self.mode == "tween":
            self._elapsed += dt
            progress = min(1,self._elapsed/max(.000001,self._duration))
            # 本体 smoothScrollTweenEase=3，对应DG.Tweening.Ease.OutSine。
            eased = math.sin(progress*math.pi/2)
            self.position = self._origin+(self.target-self._origin)*eased
            if progress >= 1:
                self.mode = "elastic" if self.position != self.bound(self.position) else "idle"
            return
        boundary = self.bound(self.position)
        if self.position != boundary:
            self.mode = "elastic"
            omega = 2/max(.0001,self.config["m_Elasticity"])
            x = omega*dt
            decay = 1/(1+x+.48*x*x+.235*x*x*x)
            change = self.position-boundary
            temporary = (self.velocity+omega*change)*dt
            self.velocity = (self.velocity-omega*temporary)*decay
            self.position = boundary+(change+temporary)*decay
            if abs(self.position-boundary)<.05 and abs(self.velocity)<self.scale:
                self.position = boundary
                self.stop()
            return
        old_velocity = self.velocity
        rate = self.config["m_DecelerationRate"]
        self.velocity *= rate**dt
        self.position += old_velocity*(rate**dt-1)/math.log(rate)
        if abs(self.velocity)<self.scale:
            if self.position == self.bound(self.position):
                self.stop()
            else:
                self.mode = "elastic"
