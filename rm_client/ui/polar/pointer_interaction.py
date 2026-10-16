"""Pointer capture and binding state, independent of a window or backend."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from PySide6.QtCore import QPointF


class BindingTarget(Protocol):
    name: str
    keybind: str


@dataclass(frozen=True)
class BackgroundRelease:
    consumed: bool = False
    dismiss: bool = False


@dataclass
class PointerInteraction:
    drag: dict[str, Any] | None = None
    binding_module: BindingTarget | None = None
    background_press: QPointF | None = None
    background_dragged: bool = False
    background_release_owned: bool = False

    def begin_press(self, *, left_button: bool) -> None:
        self.background_press = None
        if left_button:
            self.background_release_owned = False

    def own_background_press(self, point: QPointF) -> None:
        self.background_press = QPointF(point)
        self.background_dragged = False
        self.background_release_owned = True

    def own_release(self) -> None:
        self.background_release_owned = True

    def cancel_background_press(self) -> None:
        # Keyboard navigation cancels dismissal, but the eventual mouse release
        # remains owned by the GUI and must not escape to combat controls.
        self.background_press = None

    def track_owned_pointer(self, point: QPointF) -> bool:
        if not self.background_release_owned:
            return False
        if self.background_press is not None and (point - self.background_press).manhattanLength() > 6.0:
            self.background_dragged = True
        return True

    def release_background(self, point: QPointF, *, left_button: bool,
                           gui_visible: bool, background_target: bool) -> BackgroundRelease:
        if not self.background_release_owned or not left_button:
            return BackgroundRelease()
        press = self.background_press
        self.background_release_owned = False
        self.background_press = None
        dismiss = bool(press is not None and gui_visible and background_target
                       and not self.background_dragged and (point - press).manhattanLength() <= 6.0)
        return BackgroundRelease(consumed=True, dismiss=dismiss)

    def cancel_epoch(self) -> None:
        self.background_release_owned = bool(
            self.background_release_owned or self.drag or self.background_press is not None)
        self.drag = None
        self.binding_module = None
        self.background_press = None

    def finish_binding(self, key: str) -> BindingTarget | None:
        module = self.binding_module
        if module is not None:
            module.keybind = key
            self.binding_module = None
        return module


class PointerField:
    """Explicit legacy window field forwarding; the state remains single-owned.

    Old renderers and extension hosts may still assign the historical fields.
    Input production paths use PointerInteraction's grouped capture actions.
    This adapter never scans or copies a window's attributes.
    """
    def __init__(self, field_name: str):
        if field_name not in PointerInteraction.__dataclass_fields__:
            raise ValueError(f"Unknown pointer field: {field_name}")
        self.field_name = field_name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return getattr(instance.pointer_interaction, self.field_name)

    def __set__(self, instance, value):
        setattr(instance.pointer_interaction, self.field_name, value)
