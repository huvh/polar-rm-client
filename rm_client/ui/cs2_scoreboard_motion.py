"""Panorama scoreboard curves; no independent clock, timer or frame counter."""
import math


def css_ease_in_out(t):
    t = max(0., min(1., t))
    if t in (0., 1.):
        return t
    lo, hi = 0., 1.
    for _ in range(24):
        u = (lo+hi)/2
        x = 3*(1-u)**2*u*.42 + 3*(1-u)*u*u*.58 + u**3
        if x < t:
            lo = u
        else:
            hi = u
    u = (lo+hi)/2
    return 3*(1-u)*u*u+u**3


def stat_brightness(elapsed):
    """scoreboard.css anim-pulse: 1 -> 3 at 5% -> 1, one second."""
    if not math.isfinite(elapsed) or elapsed < 0 or elapsed >= 1:
        return 1.
    if elapsed <= .05:
        return 1+2*css_ease_in_out(elapsed/.05)
    return 3-2*css_ease_in_out((elapsed-.05)/.95)
