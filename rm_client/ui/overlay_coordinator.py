from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OverlayKind(str, Enum):
    CLICKGUI = "clickgui"
    ECONOMY = "economy"
    HERO_DEPLOY = "hero_deploy"
    STUDENT = "student"
    CHAT = "chat"
    RADIAL = "radial"


@dataclass
class OverlayCoordinator:
    """Own the input priority and exclusivity of interactive HUD overlays."""

    modal: OverlayKind | None = None
    chat_input: bool = False
    radial_active: bool = False

    def request_modal(self, kind: OverlayKind) -> OverlayKind | None:
        previous = self.modal
        self.modal = kind
        self.chat_input = False
        self.radial_active = False
        return previous

    def close_modal(self, kind: OverlayKind | None = None) -> bool:
        if self.modal is None or (kind is not None and self.modal != kind):
            return False
        self.modal = None
        return True

    def begin_chat(self) -> OverlayKind | None:
        previous = self.modal
        self.modal = None
        self.radial_active = False
        self.chat_input = True
        return previous

    def end_chat(self) -> None:
        self.chat_input = False

    def begin_radial(self) -> bool:
        if self.chat_input or self.modal is not None:
            return False
        self.radial_active = True
        return True

    def end_radial(self) -> None:
        self.radial_active = False

    @property
    def blocks_combat_input(self) -> bool:
        return self.chat_input or self.modal is not None or self.radial_active
