from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any

from .animation import step_damped_spring


ACTION_LABELS: dict[str, str] = {
    "economy": "Economy",
    "economy_ammo": "Ammo",
    "toggle_armor_autoaim": "Auto Aim",
    "toggle_armor_lock": "Armor Lock",
    "match_chat": "Match Chat",
    "toggle_spin": "Spin Mode",
    "toggle_friction": "Friction Wheel",
    "clickgui": "ClickGUI",
}

ACTION_ICONS: dict[str, str] = {
    "economy": "EC",
    "economy_ammo": "AM",
    "toggle_armor_autoaim": "AI",
    "toggle_armor_lock": "LK",
    "match_chat": "CH",
    "toggle_spin": "SP",
    "toggle_friction": "FW",
    "clickgui": "UI",
}

DEFAULT_ACTIONS = (
    "economy",
    "economy_ammo",
    "toggle_armor_autoaim",
    "toggle_armor_lock",
    "match_chat",
    "toggle_spin",
    "toggle_friction",
    "clickgui",
)

SECTOR_INDEXES = {
    4: (0, 2, 4, 6),
    6: (0, 1, 2, 4, 5, 6),
    8: tuple(range(8)),
}


@dataclass(frozen=True)
class QuickActionSector:
    index: int
    action: str
    label: str
    icon: str
    start_angle: float
    span_angle: float


@dataclass
class QuickActionWheelState:
    center_x: float = 0.0
    center_y: float = 0.0
    radius: float = 118.0
    dead_zone: float = 38.0
    sector_count: int = 8
    show_labels: bool = True
    label_style: str = "Action"
    icon_style: str = "Initials"
    actions: list[str] = field(default_factory=lambda: list(DEFAULT_ACTIONS))
    custom_labels: list[str] = field(default_factory=lambda: [""] * 8)
    custom_icons: list[str] = field(default_factory=lambda: [""] * 8)
    active: bool = False
    selected_index: int = -1
    progress: float = 0.0
    velocity: float = 0.0
    pointer_x: float = 0.0
    pointer_y: float = 0.0
    opened_at: float = 0.0

    def configure(
        self,
        *,
        sector_count: int | None = None,
        radius: float | None = None,
        dead_zone: float | None = None,
        show_labels: bool | None = None,
        label_style: str | None = None,
        icon_style: str | None = None,
        actions: list[str] | tuple[str, ...] | None = None,
        custom_labels: list[str] | tuple[str, ...] | None = None,
        custom_icons: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        if sector_count is not None:
            self.sector_count = min((4, 6, 8), key=lambda item: abs(item - int(sector_count)))
        if radius is not None:
            self.radius = max(72.0, min(180.0, float(radius)))
        if dead_zone is not None:
            self.dead_zone = max(18.0, min(self.radius * 0.72, float(dead_zone)))
        if show_labels is not None:
            self.show_labels = bool(show_labels)
        if label_style is not None:
            value = str(label_style)
            self.label_style = value if value in {"Action", "Compact", "Off"} else "Action"
        if icon_style is not None:
            value = str(icon_style)
            self.icon_style = value if value in {"Initials", "Dot", "Off"} else "Initials"
        if actions is not None:
            clean = [action if action in ACTION_LABELS else DEFAULT_ACTIONS[index % 8] for index, action in enumerate(actions)]
            self.actions = (clean + list(DEFAULT_ACTIONS))[:8]
        if custom_labels is not None:
            labels = [str(value)[:24] for value in custom_labels]
            self.custom_labels = (labels + [""] * 8)[:8]
        if custom_icons is not None:
            icons = [str(value)[:4] for value in custom_icons]
            self.custom_icons = (icons + [""] * 8)[:8]

    def open(
        self,
        pointer_x: float,
        pointer_y: float,
        width: float,
        height: float,
        now: float | None = None,
    ) -> None:
        padding = self.radius + 18.0
        self.center_x = max(padding, min(max(padding, width - padding), float(pointer_x)))
        self.center_y = max(padding, min(max(padding, height - padding), float(pointer_y)))
        self.pointer_x = float(pointer_x)
        self.pointer_y = float(pointer_y)
        self.active = True
        self.selected_index = -1
        self.opened_at = time.perf_counter() if now is None else float(now)

    def cancel(self) -> None:
        self.active = False
        self.selected_index = -1

    def update_pointer(self, pointer_x: float, pointer_y: float) -> int:
        self.pointer_x = float(pointer_x)
        self.pointer_y = float(pointer_y)
        dx = self.pointer_x - self.center_x
        dy = self.pointer_y - self.center_y
        if math.hypot(dx, dy) < self.dead_zone:
            self.selected_index = -1
            return -1
        angle = (math.atan2(dx, -dy) + math.tau) % math.tau
        span = math.tau / self.sector_count
        self.selected_index = int((angle + span * 0.5) // span) % self.sector_count
        return self.selected_index

    def release(self) -> str | None:
        action = None
        sectors = self.sectors()
        if 0 <= self.selected_index < len(sectors):
            action = sectors[self.selected_index].action
        self.active = False
        self.selected_index = -1
        return action

    def update(self, dt: float) -> float:
        target = 1.0 if self.active else 0.0
        stiffness = 300.0
        ratio = 0.62 if self.active else 1.0
        self.progress, self.velocity = step_damped_spring(
            self.progress,
            self.velocity,
            target,
            dt,
            stiffness=stiffness,
            damping_ratio=ratio,
        )
        self.progress = max(0.0, min(1.08, self.progress))
        if abs(target - self.progress) < 0.001 and abs(self.velocity) < 0.01:
            self.progress = target
            self.velocity = 0.0
        return self.progress

    @property
    def visible(self) -> bool:
        return self.active or self.progress > 0.005

    def sectors(self) -> tuple[QuickActionSector, ...]:
        indexes = SECTOR_INDEXES[self.sector_count]
        span = math.tau / self.sector_count
        result = []
        for sector_index, action_index in enumerate(indexes):
            action = self.actions[action_index]
            default_label = ACTION_LABELS.get(action, action)
            if self.label_style == "Compact":
                default_label = default_label.replace(" ", "\n")
            label = "" if self.label_style == "Off" else self.custom_labels[action_index] or default_label
            icon = self.custom_icons[action_index] or ACTION_ICONS.get(action, "")
            if self.icon_style == "Dot":
                icon = ""
            elif self.icon_style == "Off":
                icon = ""
            result.append(
                QuickActionSector(
                    index=sector_index,
                    action=action,
                    label=label,
                    icon=icon,
                    start_angle=-math.pi * 0.5 - span * 0.5 + sector_index * span,
                    span_angle=span,
                )
            )
        return tuple(result)

    def export_config(self) -> dict[str, Any]:
        return {
            "sectors": self.sector_count,
            "radius": round(self.radius, 2),
            "dead_zone": round(self.dead_zone, 2),
            "show_labels": self.show_labels,
            "label_style": self.label_style,
            "icon_style": self.icon_style,
            "actions": list(self.actions),
            "labels": list(self.custom_labels),
            "icons": list(self.custom_icons),
        }

    def load_config(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        from ..config_store import validate_client_config

        validate_client_config({"quick_action_wheel": data})
        actions = data.get("actions")
        labels = data.get("labels")
        icons = data.get("icons")
        self.configure(
            sector_count=int(data.get("sectors", self.sector_count)),
            radius=float(data.get("radius", self.radius)),
            dead_zone=float(data.get("dead_zone", self.dead_zone)),
            show_labels=bool(data.get("show_labels", self.show_labels)),
            label_style=str(data.get("label_style", self.label_style)),
            icon_style=str(data.get("icon_style", self.icon_style)),
            actions=actions if isinstance(actions, (list, tuple)) else None,
            custom_labels=labels if isinstance(labels, (list, tuple)) else None,
            custom_icons=icons if isinstance(icons, (list, tuple)) else None,
        )
