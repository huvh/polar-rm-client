"""CS2 feedback timelines measured from the local compiled Panorama styles.

Absolute time, not frame counts. No camera shake, game hooks or control changes.
The existing glass compositor remains the owner of blur/refraction/materials.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ..top_match_bar_motion import css_ease_out

KILL_FLASH_SECONDS = .7
CARD_REFLOW_SECONDS = .2
PURCHASE_SECONDS = .5
BUY_HOVER_SECONDS = .2


def _unit(age: float, duration: float) -> float:
    if not math.isfinite(age):
        raise ValueError("feedback time must be finite")
    return max(0.0, min(1.0, age / duration))


def kill_brightness(age: float) -> float:
    t = _unit(age, KILL_FLASH_SECONDS)
    return 6.0 if t <= .3 else 6.0 - 5.0 * css_ease_out((t - .3) / .7)


def kill_spotlight(age: float) -> float:
    t = _unit(age, KILL_FLASH_SECONDS)
    if t < .01:
        return .2 * css_ease_out(t / .01)
    return .2 if t <= .3 else .2 * (1 - css_ease_out((t - .3) / .7))


def card_targets(count: int) -> tuple[tuple[float, float, float], ...]:
    """Panorama's 1–5 card fan: x, y, rotateZ, in source CSS pixels."""
    return (
        ((0, 0, 0),),
        ((-2, 2, -6), (2, 0, 6)),
        ((-3, 4, -12), (0, 2, 0), (3, 0, 12)),
        ((-5, 6, -18), (-2, 4, -6), (2, 2, 6), (5, 0, 18)),
        ((-7, 8, -24), (-3, 6, -12), (0, 4, 0), (3, 2, 12), (7, 0, 24)),
    )[max(1, min(5, int(count))) - 1]


@dataclass
class BuyFeedback:
    """A presentation-only terminal transaction observer, never a confirmer."""
    sequence: int = -1
    offer_key: str = ""
    status: str = ""
    started: float = -1e9
    hover_key: str = ""
    hover_at: float = -1e9

    def observe(self, transaction, now: float) -> str | None:
        if transaction is None or transaction.status == "pending" or transaction.sequence == self.sequence:
            return None
        self.sequence = transaction.sequence
        self.offer_key = transaction.offer.key
        self.status = transaction.status
        self.started = now
        # Existing EconomyBridge is solely responsible for authoritative
        # confirmation. Timeout is ambiguous: never play success/rejection.
        return "purchase" if self.status == "succeeded" else "cant_buy" if self.status == "rejected" else None

    def intensity(self, key: str, now: float) -> float:
        if key != self.offer_key or self.status != "succeeded":
            return 0.0
        # purchased keyframes: brightness 2 → 1 over 500ms, ease-in-out.
        t = _unit(now - self.started, PURCHASE_SECONDS)
        return 1 - _css_ease_in_out(t)


def _css_ease_in_out(t: float) -> float:
    # CSS cubic-bezier(.42, 0, .58, 1), deterministic at any refresh rate.
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(18):
        m = (low + high) * .5
        x = 3 * (1-m)**2 * m * .42 + 3 * (1-m) * m*m * .58 + m**3
        if x < t:
            low = m
        else:
            high = m
    m = (low + high) * .5
    return 3 * (1-m) * m*m + m**3


def buy_enabled(owner) -> bool:
    assets = getattr(getattr(getattr(owner, "kill_fx", None), "cs2", None), "assets", None)
    return bool(assets and assets.available and
                owner.setting_bool(owner.registry.get("EconomyPanel"), "CS2 Feedback", True))


def play_buy_sound(owner, key: str) -> bool:
    if not buy_enabled(owner):
        return False
    module = owner.registry.get("AudioFeedback")
    if module is None or not module.enabled or not owner.setting_bool(module, "Enabled", True):
        return False
    return owner.kill_fx.cs2.assets.play(key, owner.get_setting_number(module, "UI Volume", 45.0) / 100)


def notify_buy_hover(owner, key: str, now: float) -> None:
    feedback = getattr(getattr(owner,"economy_workspace_layer",None),"cs2_feedback",None)
    if feedback is None or feedback.hover_key==key:
        return
    feedback.hover_key = key
    if key and now-feedback.hover_at >= .02:
        feedback.hover_at = now
        play_buy_sound(owner,"buy_hover")


def append_buy_feedback(commands, owner, key, rect, clip, hover: float, alpha: float, now: float) -> None:
    if not buy_enabled(owner):
        return
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor
    feedback = getattr(getattr(owner, "economy_workspace_layer", None), "cs2_feedback", None)
    flash = feedback.intensity(key, now) if feedback is not None else 0.0
    # Content-only thin light rim. The lens/material parameters are untouched.
    rim = QColor(255, 255, 255, round(255 * alpha * (.07 * hover + .28 * flash)))
    commands.rect(rect, min(34.0, rect.height()*.5), QColor(0, 0, 0, 0),
                  rim, 1.0, clip=clip)
    source = owner.kill_fx.cs2.assets.paths.get("buy_icon")
    if source is not None:
        icon = QRectF(rect.left()+17, rect.center().y()-10, 20, 20)
        commands.image(icon, source, QColor(255, 215, 115, round(255*alpha)), clip=clip)
