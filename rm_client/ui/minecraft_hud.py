"""Minecraft 1.21.11 combat-HUD preset built from the local game sprites.

The renderer is isolated from POLAR's liquid-glass paths.  It uses the exact
vanilla hotbar/status sprites with nearest-neighbour sampling and a cached
bitmap-font compositor, so selecting this preset cannot mutate shared glass
materials or lower the normal HUD's frame rate.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter


FUNCTION_SLOT_NAMES = tuple(f"Slot {index}" for index in range(1, 10))
DEFAULT_FUNCTION_SLOTS = (
    "ArmorAutoAim",
    "ArmorLock",
    "FrictionWheel",
    "SpinMode",
    "EconomyPanel",
    "ProjectileShop",
    "TacticalMap",
    "MatchChat",
    "ClickGui",
)


def vanilla_gui_scale(width: int, height: int, override: str = "Auto") -> int:
    """Return Minecraft's integer GUI scale (minimum 320x240 logical area)."""

    if str(override) != "Auto":
        try:
            return max(1, min(8, int(str(override).rstrip("xX"))))
        except ValueError:
            pass
    scale = 1
    while scale < 8 and width // (scale + 1) >= 320 and height // (scale + 1) >= 240:
        scale += 1
    return scale


@dataclass(frozen=True, slots=True)
class MinecraftHudLayout:
    scale: int
    hotbar: QRectF
    slots: tuple[QRectF, ...]
    hearts: tuple[QRectF, ...]
    armor: tuple[QRectF, ...]
    food: tuple[QRectF, ...]
    boss_bars: tuple[QRectF, ...]
    scoreboard: QRectF
    effects_origin: QPointF

    def slot_at(self, point: QPointF) -> int | None:
        for index, rect in enumerate(self.slots):
            if rect.contains(point):
                return index
        return None


class MinecraftBitmapFont:
    """Small cached renderer for Mojang's exact ``ascii.png`` glyph sheet."""

    def __init__(self, texture: Path, cache_limit: int = 320) -> None:
        self.texture_path = Path(texture)
        self.texture = QImage(str(self.texture_path)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.cache_limit = max(32, int(cache_limit))
        self._cache: OrderedDict[tuple[str, int, int, bool], QImage] = OrderedDict()
        self._widths = self._scan_widths()

    @property
    def available(self) -> bool:
        return not self.texture.isNull()

    def _scan_widths(self) -> tuple[int, ...]:
        widths: list[int] = []
        if self.texture.isNull():
            return tuple(6 for _ in range(256))
        for code in range(256):
            sx = (code & 15) * 8
            sy = (code >> 4) * 8
            right = -1
            for x in range(8):
                if any(self.texture.pixelColor(sx + x, sy + y).alpha() > 8 for y in range(8)):
                    right = x
            widths.append(4 if code == 32 else max(2, min(8, right + 2)))
        return tuple(widths)

    @staticmethod
    def _code(char: str) -> int:
        value = ord(char)
        return value if 0 <= value <= 255 else ord("?")

    def logical_width(self, text: str) -> int:
        if not text:
            return 0
        return sum(self._widths[self._code(char)] for char in str(text))

    def _plain_layer(self, text: str, scale: int, packed_color: int) -> QImage:
        width = max(1, self.logical_width(text) * scale)
        layer = QImage(width, 8 * scale, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        x = 0
        for char in str(text):
            code = self._code(char)
            source = QRect((code & 15) * 8, (code >> 4) * 8, 8, 8)
            painter.drawImage(QRect(x, 0, 8 * scale, 8 * scale), self.texture, source)
            x += self._widths[code] * scale
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(layer.rect(), QColor.fromRgba(packed_color))
        painter.end()
        return layer

    def image(self, text: str, color: QColor, scale: int, shadow: bool = True) -> QImage:
        scale = max(1, int(scale))
        key = (str(text), int(color.rgba()), scale, bool(shadow))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        main = self._plain_layer(key[0], scale, key[1])
        if shadow:
            out = QImage(main.width() + scale, main.height() + scale, QImage.Format.Format_ARGB32_Premultiplied)
            out.fill(Qt.GlobalColor.transparent)
            painter = QPainter(out)
            shadow_color = QColor(max(0, color.red() // 4), max(0, color.green() // 4), max(0, color.blue() // 4), color.alpha())
            painter.drawImage(scale, scale, self._plain_layer(key[0], scale, int(shadow_color.rgba())))
            painter.drawImage(0, 0, main)
            painter.end()
        else:
            out = main
        self._cache[key] = out
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_limit:
            self._cache.popitem(last=False)
        return out

    def draw(self, painter: QPainter, x: float, y: float, text: str, color: QColor, scale: int, *, shadow: bool = True) -> float:
        image = self.image(str(text), color, scale, shadow)
        painter.drawImage(int(round(x)), int(round(y)), image)
        return float(image.width())


class MinecraftCombatHudRenderer:
    SPRITES = (
        "hotbar",
        "hotbar_selection",
        "heart_container",
        "heart_full",
        "heart_half",
        "armor_empty",
        "armor_half",
        "armor_full",
        "food_empty",
        "food_half",
        "food_full",
        "effect_background",
        "boss_red_background",
        "boss_red_progress",
        "boss_blue_background",
        "boss_blue_progress",
        "boss_yellow_background",
        "boss_yellow_progress",
        "boss_green_background",
        "boss_green_progress",
    )

    def __init__(self, asset_root: Path) -> None:
        self.asset_root = Path(asset_root)
        self.images = {
            name: QImage(str(self.asset_root / f"{name}.png")).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            for name in self.SPRITES
        }
        self.font = MinecraftBitmapFont(self.asset_root / "ascii.png")
        self.selected_slot = 0

    @property
    def available(self) -> bool:
        return self.font.available and all(not image.isNull() for image in self.images.values())

    def layout(self, width: int, height: int, scale_override: str = "Auto", scoreboard_lines: Iterable[str] = ()) -> MinecraftHudLayout:
        scale = vanilla_gui_scale(int(width), int(height), scale_override)
        hotbar = QRectF((width - 182 * scale) // 2, height - 22 * scale, 182 * scale, 22 * scale)
        slots = tuple(
            QRectF(hotbar.left() + (3 + index * 20) * scale, hotbar.top() + 3 * scale, 16 * scale, 16 * scale)
            for index in range(9)
        )
        hearts_y = hotbar.top() - 11 * scale
        hearts = tuple(QRectF(hotbar.left() + index * 8 * scale, hearts_y, 9 * scale, 9 * scale) for index in range(10))
        armor_y = hearts_y - 10 * scale
        armor = tuple(QRectF(hotbar.left() + index * 8 * scale, armor_y, 9 * scale, 9 * scale) for index in range(10))
        food = tuple(
            QRectF(hotbar.right() - (index + 1) * 8 * scale - scale, hearts_y, 9 * scale, 9 * scale)
            for index in range(10)
        )
        boss = tuple(QRectF((width - 182 * scale) // 2, (15 + index * 15) * scale, 182 * scale, 5 * scale) for index in range(3))
        lines = tuple(str(line) for line in scoreboard_lines)
        logical_score_w = max((self.font.logical_width(line) for line in lines), default=112)
        score_w = max(120, logical_score_w + 8) * scale
        score_h = max(12, len(lines) * 9 + 5) * scale
        scoreboard = QRectF(width - score_w - 4 * scale, max(58 * scale, (height - score_h) * 0.46), score_w, score_h)
        # Keep effect tiles below the three boss bars.  At 2K/Auto scale 6 a
        # vanilla 6-slot effect row is 936 px wide; placing it at y=4 clipped
        # the ALLY BASE title even though every individual rect was on-screen.
        return MinecraftHudLayout(
            scale,
            hotbar,
            slots,
            hearts,
            armor,
            food,
            boss,
            scoreboard,
            QPointF(4 * scale, 58 * scale),
        )

    @staticmethod
    def assignments(module: Any) -> tuple[str, ...]:
        result: list[str] = []
        for index, fallback in enumerate(DEFAULT_FUNCTION_SLOTS, 1):
            setting = module.get_setting(f"Slot {index}") if module is not None else None
            result.append(str(setting.value) if setting is not None else fallback)
        return tuple(result)

    @staticmethod
    def abbreviation(name: str) -> str:
        if not name or name == "Empty":
            return "--"
        capitals = "".join(char for char in name if char.isupper() or char.isdigit())
        return (capitals or name[:3]).upper()[:3]

    @staticmethod
    def _team_rows(state: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return bounded ally/enemy status rows in local-team order."""

        local_id = int(getattr(state, "robot_id", 0) or 0)
        local_red = local_id < 100
        rows = [dict(row) for row in getattr(state, "robot_rows", ()) if int(row.get("id", 0) or 0) > 0]
        # Official sync provides both teams in robot_rows.  The simulator's
        # legacy robot_rows contains allies only, so supplement its opponent
        # side from the tactical-map feed without duplicating robot IDs.
        by_id = {int(row.get("id", 0)): row for row in rows}
        for row in getattr(state, "map_robots", ()):
            robot_id = int(row.get("id", 0) or 0)
            if robot_id > 0 and robot_id not in by_id:
                copy = dict(row)
                copy.setdefault("state", "ALIVE" if int(copy.get("hp", 0)) > 0 else "DEAD")
                by_id[robot_id] = copy
        allies = [
            row for robot_id, row in by_id.items()
            if (robot_id < 100) == local_red
        ]
        enemies = [
            row for robot_id, row in by_id.items()
            if (robot_id < 100) != local_red
        ]
        allies.sort(key=lambda row: (int(row.get("id", 0)) != local_id, int(row.get("id", 0))))
        enemies.sort(key=lambda row: (int(row.get("hp", 0)) <= 0, int(row.get("id", 0))))
        return allies[:4], enemies[:4]

    @classmethod
    def _robot_status_line(cls, prefix: str, row: dict[str, Any]) -> str:
        robot_id = int(row.get("id", 0) or 0)
        hp = max(0, int(row.get("hp", 0) or 0))
        # Tactical-map fallback rows may omit max HP.  Never display nonsense
        # such as 580/1; the current sample is the safest bounded fallback.
        maximum = max(1, hp, int(row.get("max", 1) or 1))
        state = str(row.get("state", "ALIVE" if hp > 0 else "DEAD")).upper()
        name = cls.abbreviation(str(row.get("name", "ROBOT")))
        return f"{prefix}{robot_id:03d} {name} {hp}/{maximum} {state[:5]}"

    @staticmethod
    def scoreboard_lines(state: Any) -> tuple[tuple[str, QColor], ...]:
        seconds = max(0, int(getattr(state, "stage_countdown_sec", 0)))
        allies, enemies = MinecraftCombatHudRenderer._team_rows(state)
        ally_alive = sum(1 for row in allies if int(row.get("hp", 0)) > 0 and str(row.get("state", "")).upper() not in {"DOWN", "DEAD"})
        enemy_alive = sum(1 for row in enemies if int(row.get("hp", 0)) > 0 and str(row.get("state", "")).upper() not in {"DOWN", "DEAD"})
        target = f"TARGET {int(getattr(state, 'target_id', 0))} {int(getattr(state, 'target_health', 0))}HP"
        lob_status = str(getattr(state, "hero_lob_status", "OFF"))[:28].upper()
        lines: list[tuple[str, QColor]] = [
            (str(getattr(state, "match_title", "RM MATCH")).upper(), QColor("#55ffff")),
            (f"TIME {seconds // 60:02d}:{seconds % 60:02d}", QColor("#ffffff")),
            (f"ALLY {ally_alive}  ENEMY {enemy_alive}", QColor("#55ff55")),
            (f"BASE {int(getattr(state, 'base_health', 0))} SH{int(getattr(state, 'base_shield', 0))}% {str(getattr(state, 'base_status', ''))}", QColor("#55ffff")),
            (f"OUTPOST {int(getattr(state, 'outpost_health', 0))} {str(getattr(state, 'outpost_status', ''))}", QColor("#55ffff")),
            (f"E BASE {int(getattr(state, 'enemy_base_health', 0))} SH{int(getattr(state, 'enemy_base_shield', 0))}% {str(getattr(state, 'enemy_base_status', ''))}", QColor("#ff5555")),
            (f"E OUTPOST {int(getattr(state, 'enemy_outpost_health', 0))} {str(getattr(state, 'enemy_outpost_status', ''))}", QColor("#ff5555")),
        ]
        lines.extend(
            (MinecraftCombatHudRenderer._robot_status_line("A", row), QColor("#55ff55"))
            for row in allies
        )
        lines.extend(
            (MinecraftCombatHudRenderer._robot_status_line("E", row), QColor("#ff5555"))
            for row in enemies
        )
        lines.extend(
            (
                (target, QColor("#ffff55") if bool(getattr(state, "target_locked", False)) else QColor("#aaaaaa")),
                (f"AMMO {int(getattr(state, 'remaining_ammo', 0))}", QColor("#ffaa00")),
                (f"LOB {lob_status}", QColor("#ff55ff") if bool(getattr(state, "hero_lob_armed", False)) else QColor("#aaaaaa")),
            )
        )
        return tuple(lines)

    def draw(self, painter: QPainter, width: int, height: int, state: Any, registry: Any, module: Any) -> MinecraftHudLayout:
        lines = self.scoreboard_lines(state)
        override_setting = module.get_setting("GUI Scale") if module is not None else None
        override = str(override_setting.value) if override_setting is not None else "Auto"
        layout = self.layout(width, height, override, (text for text, _ in lines))
        scale = layout.scale
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        self._sprite(painter, "hotbar", layout.hotbar)
        selection = QRectF(
            layout.hotbar.left() + (-1 + self.selected_slot * 20) * scale,
            layout.hotbar.top() - scale,
            24 * scale,
            23 * scale,
        )
        self._sprite(painter, "hotbar_selection", selection)
        assignments = self.assignments(module)
        for index, (rect, name) in enumerate(zip(layout.slots, assignments)):
            target = registry.get(name) if registry is not None and name != "Empty" else None
            enabled = bool(target and target.enabled)
            label = self.abbreviation(name)
            label_width = self.font.logical_width(label) * scale
            self.font.draw(
                painter,
                rect.center().x() - label_width * 0.5,
                rect.top() + 4 * scale,
                label,
                QColor("#55ff55") if enabled else QColor("#ffffff"),
                scale,
            )
            self.font.draw(painter, rect.left(), rect.top(), str(index + 1), QColor("#ffff55") if index == self.selected_slot else QColor("#aaaaaa"), max(1, scale // 2), shadow=True)

        hp_ratio = self._ratio(getattr(state, "current_health", 0), getattr(state, "max_health", 1))
        thermal_margin = 1.0 - self._ratio(getattr(state, "current_heat", 0.0), getattr(state, "max_heat", 1.0))
        # The requested Minecraft mapping is literal: hunger represents live
        # chassis power, not the energy-buffer percentage used by POLAR's
        # normal HUD.
        chassis_ratio = self._ratio(
            getattr(state, "chassis_power_w", 0),
            getattr(state, "power_limit", 1),
        )
        self._draw_meter(painter, layout.hearts, hp_ratio, "heart_container", "heart_half", "heart_full")
        self._draw_meter(painter, layout.armor, thermal_margin, "armor_empty", "armor_half", "armor_full")
        self._draw_meter(painter, layout.food, chassis_ratio, "food_empty", "food_half", "food_full")
        label_scale = max(1, scale // 2)
        self.font.draw(painter, layout.armor[0].left(), layout.armor[0].top() - 7 * label_scale, f"HEAT {int(getattr(state, 'current_heat', 0))}/{int(getattr(state, 'max_heat', 0))} COOL {int(getattr(state, 'heat_cooldown_rate', 0))}/S", QColor("#55ffff"), label_scale)
        power_text = f"POWER {int(getattr(state, 'chassis_power_w', 0))}/{int(getattr(state, 'power_limit', 0))}W"
        power_w = self.font.logical_width(power_text) * label_scale
        self.font.draw(painter, layout.hotbar.right() - power_w, layout.food[-1].top() - 7 * label_scale, power_text, QColor("#ffff55"), label_scale)

        self._draw_boss_bar(painter, layout.boss_bars[0], "blue", self._ratio(getattr(state, "base_health", 0), getattr(state, "base_max_health", 1)), f"ALLY BASE  SHIELD {int(getattr(state, 'base_shield', 0))}%")
        self._draw_boss_bar(painter, layout.boss_bars[1], "red", self._ratio(getattr(state, "enemy_base_health", 0), getattr(state, "enemy_base_max_health", 1)), f"ENEMY BASE  SHIELD {int(getattr(state, 'enemy_base_shield', 0))}%")
        self._draw_boss_bar(painter, layout.boss_bars[2], "yellow", self._ratio(getattr(state, "target_health", 0), getattr(state, "target_max_health", 1)), f"TARGET {int(getattr(state, 'target_id', 0))}")

        self._draw_scoreboard(painter, layout.scoreboard, lines, scale)
        effects = (
            ("JUP", bool(getattr(state, "jump_ready", False))),
            ("PTE", bool(getattr(state, "pte_ready", False))),
            ("WHE", bool(getattr(state, "wheel_online", False))),
            ("LES", bool(getattr(state, "les_online", False))),
            ("SBF", bool(getattr(state, "small_buff", False))),
            ("LBF", bool(getattr(state, "large_buff", False))),
        )
        self._draw_effects(painter, layout.effects_origin, effects, scale)
        painter.restore()
        return layout

    @staticmethod
    def _ratio(value: float, maximum: float) -> float:
        return max(0.0, min(1.0, float(value) / max(1.0, float(maximum))))

    def _sprite(self, painter: QPainter, name: str, destination: QRectF, source: QRect | None = None) -> None:
        image = self.images.get(name)
        if image is None or image.isNull() or destination.isEmpty():
            return
        painter.drawImage(destination.toRect(), image, source or image.rect())

    def _draw_meter(self, painter: QPainter, rects: tuple[QRectF, ...], ratio: float, empty: str, half: str, full: str) -> None:
        units = max(0, min(20, int(round(ratio * 20.0))))
        for index, rect in enumerate(rects):
            self._sprite(painter, empty, rect)
            fill = units - index * 2
            if fill >= 2:
                self._sprite(painter, full, rect)
            elif fill == 1:
                self._sprite(painter, half, rect)

    def _draw_boss_bar(self, painter: QPainter, rect: QRectF, palette: str, ratio: float, title: str) -> None:
        self._sprite(painter, f"boss_{palette}_background", rect)
        image = self.images[f"boss_{palette}_progress"]
        source_width = max(0, min(image.width(), int(round(image.width() * ratio))))
        if source_width:
            destination = QRectF(rect.left(), rect.top(), source_width * rect.width() / image.width(), rect.height())
            self._sprite(painter, f"boss_{palette}_progress", destination, QRect(0, 0, source_width, image.height()))
        scale = max(1, int(round(rect.height() / 5.0)))
        text_width = self.font.logical_width(title) * scale
        self.font.draw(painter, rect.center().x() - text_width * 0.5, rect.top() - 9 * scale, title, QColor("#ffffff"), scale)

    def _draw_scoreboard(self, painter: QPainter, rect: QRectF, lines: tuple[tuple[str, QColor], ...], scale: int) -> None:
        row_h = 9 * scale
        y = rect.top() + 2 * scale
        for index, (text, text_color) in enumerate(lines):
            row = QRectF(rect.left(), y + index * row_h, rect.width(), row_h)
            painter.fillRect(row, QColor(0, 0, 0, 105 if index else 150))
            if index == 0:
                painter.fillRect(QRectF(row.left(), row.top(), 2 * scale, row.height()), QColor("#55ffff"))
            text_w = self.font.logical_width(text) * scale
            self.font.draw(painter, row.right() - text_w - 2 * scale, row.top(), text, text_color, scale)

    def _draw_effects(self, painter: QPainter, origin: QPointF, effects: tuple[tuple[str, bool], ...], scale: int) -> None:
        for index, (label, active) in enumerate(effects):
            rect = QRectF(origin.x() + index * 26 * scale, origin.y(), 24 * scale, 24 * scale)
            self._sprite(painter, "effect_background", rect)
            label_w = self.font.logical_width(label) * scale
            self.font.draw(painter, rect.center().x() - label_w * 0.5, rect.top() + 8 * scale, label, QColor("#55ff55") if active else QColor("#ff5555"), scale)

    def append_drop_overlay(
        self,
        commands: Any,
        width: int,
        height: int,
        dragged_name: str,
        point: QPointF,
        assignments: tuple[str, ...],
        font: Any,
        scale_override: str = "Auto",
    ) -> MinecraftHudLayout:
        """Append an exact hotbar drop target to either GPU/compat draw list."""

        layout = self.layout(width, height, scale_override)
        scale = layout.scale
        commands.image(layout.hotbar, self.asset_root / "hotbar.png", QColor(255, 255, 255, 255))
        hovered = layout.slot_at(point)
        if hovered is not None:
            selection = QRectF(layout.hotbar.left() + (-1 + hovered * 20) * scale, layout.hotbar.top() - scale, 24 * scale, 23 * scale)
            commands.image(selection, self.asset_root / "hotbar_selection.png", QColor(255, 255, 255, 255))
        for index, (slot, name) in enumerate(zip(layout.slots, assignments)):
            commands.text(slot, self.abbreviation(name), font, QColor("#ffffff"), Qt.AlignmentFlag.AlignCenter)
            commands.text(QRectF(slot.left(), slot.top(), 8 * scale, 8 * scale), str(index + 1), font, QColor("#ffff55"), Qt.AlignmentFlag.AlignCenter)
        ghost = QRectF(point.x() + 14.0, point.y() + 10.0, 190.0, 28.0)
        commands.rect(ghost, 3.0, QColor(0, 0, 0, 175), QColor(255, 255, 255, 90), 1.0)
        commands.text(ghost.adjusted(8.0, 0.0, -8.0, 0.0), f"DROP {dragged_name}", font, QColor("#ffffff"), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return layout
