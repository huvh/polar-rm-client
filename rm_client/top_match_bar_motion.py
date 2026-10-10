"""Small source-evidenced motion primitives; gameplay timing remains unverified.

Reference: SteamTracking CS2 hudteamcounter.css, retrieved 2026-10-10.
The stylesheet defines on-kill: 0.3s, ease-out, scale 1.2 -> identity.
No death-opacity duration is declared for AvatarL__ImageBG; do not invent one.
"""
from __future__ import annotations
import math

KILL_POP_SECONDS = 0.3
KILL_POP_INITIAL_SCALE = 1.2
DEAD_OPACITY = 0.2
DEAD_CONTRAST = 0.9


def css_ease_out(t: float) -> float:
    """CSS cubic-bezier(0, 0, .58, 1), solved in x rather than parametric time."""
    if not math.isfinite(t):
        raise ValueError("animation time must be finite")
    t = min(1.0, max(0.0, t))
    if t in (0.0, 1.0):
        return t
    low, high = 0.0, 1.0
    for _ in range(24):
        u = (low + high) / 2
        x = 3 * (1 - u) * u * u * .58 + u * u * u
        if x < t:
            low = u
        else:
            high = u
    u = (low + high) / 2
    return 3 * (1 - u) * u * u + u * u * u


def kill_pop_scale(elapsed: float) -> float:
    if not math.isfinite(elapsed):
        raise ValueError("animation time must be finite")
    return 1.0 + (KILL_POP_INITIAL_SCALE - 1.0) * (1.0 - css_ease_out(elapsed / KILL_POP_SECONDS))
