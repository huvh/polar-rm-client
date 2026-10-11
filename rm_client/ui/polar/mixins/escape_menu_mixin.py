"""Esc second-level menu. No timers, device work, or CPU backdrop copies."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen


class EscapeMenuMixin:
    @property
    def escape_menu_visible(self) -> bool:
        return bool(getattr(self, "_escape_menu_visible", False))

    def set_escape_menu_visible(self, visible: bool) -> None:
        if visible == self.escape_menu_visible or (visible and self.home_visible):
            return
        # Neutralize held input immediately; backend tick/telemetry/estop keep
        # running. Closing never restores a captured key/button or arms control.
        self.control.mock_output = bool(self.backend.mqtt.mock_output)
        self.control.release_all(self.state, self.registry)
        # Preserve failed neutral-send retry state for the normal backend tick.
        self._control_mouse_point = None
        self.tactical_map_hold = False
        self.drag = None
        self._escape_menu_visible = visible
        self._escape_menu_confirm_exit = False
        self._escape_menu_selected = 0
        self._escape_menu_pressed = None
        self.hotspots.clear()
        self.invalidate_transient_overlay_scene()
        self.frame_scheduler.force()
        self.update()

    def escape_menu_choices(self):
        return ("Cancel", "Exit client") if getattr(self, "_escape_menu_confirm_exit", False) else (
            "Continue", "Return to startup", "Exit client")

    def activate_escape_menu_choice(self, index: int) -> None:
        if not self.escape_menu_visible:
            return
        if getattr(self, "_escape_menu_confirm_exit", False):
            if index == 0:
                self._escape_menu_confirm_exit = False
                self._escape_menu_selected = 0
            elif index == 1:
                # Existing closeEvent owns neutral/lock/estop/resource teardown.
                self.close()
        elif index == 0:
            self.set_escape_menu_visible(False)
        elif index == 1:
            # The startup route is fail closed even if the scene is re-entered.
            self.backend.lock_control("return to startup")
            self.set_escape_menu_visible(False)
            self.home_visible = True
            self.startup_step = "scenario"
            self.finish_startup_page_transition()
            self.reset_startup_page_animation("scenario")
            self.invalidate_transient_overlay_scene()
        elif index == 2:
            self._escape_menu_confirm_exit = True
            self._escape_menu_selected = 0  # Safe default: Cancel.
        self.frame_scheduler.force()
        self.update()

    def handle_escape_menu_key(self, event) -> bool:
        if not self.escape_menu_visible:
            return False
        pending = getattr(self, "_escape_menu_key_releases", set())
        pending.add(event.key())
        self._escape_menu_key_releases = pending
        if not event.isAutoRepeat():
            if event.key() == Qt.Key.Key_Escape:
                if getattr(self, "_escape_menu_confirm_exit", False):
                    self._escape_menu_confirm_exit = False
                    self._escape_menu_selected = 0
                else:
                    self.set_escape_menu_visible(False)
            elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Tab):
                step = -1 if event.key() == Qt.Key.Key_Up or (event.key() == Qt.Key.Key_Tab and event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
                self._escape_menu_selected = (self._escape_menu_selected + step) % len(self.escape_menu_choices())
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.activate_escape_menu_choice(self._escape_menu_selected)
        self.frame_scheduler.force()
        event.accept()
        return True

    def escape_menu_layout(self, width, height):
        scale = min(1.0, width / 720.0, height / 540.0)
        panel = QRectF((width - 440 * scale) / 2, (height - 340 * scale) / 2, 440 * scale, 340 * scale)
        rows = [QRectF(panel.x() + 34 * scale, panel.y() + (111 + i * 56) * scale, panel.width() - 68 * scale, 44 * scale) for i in range(len(self.escape_menu_choices()))]
        return panel, rows, scale

    def handle_escape_menu_mouse(self, event, phase) -> bool:
        if not self.escape_menu_visible:
            return False
        _, rows, _ = self.escape_menu_layout(self.width(), self.height())
        index = next((i for i, rect in enumerate(rows) if rect.contains(event.position())), None)
        if index is not None:
            self._escape_menu_selected = index
        if phase == "press":
            self._escape_menu_pressed = index if event.button() == Qt.MouseButton.LeftButton else None
        elif phase == "release":
            pressed = self._escape_menu_pressed
            self._escape_menu_pressed = None
            if event.button() == Qt.MouseButton.LeftButton and index is not None and index == pressed:
                self.activate_escape_menu_choice(index)
        self.frame_scheduler.force()
        event.accept()
        return True

    def draw_escape_menu(self, painter, width, height) -> None:
        if not self.escape_menu_visible:
            return
        panel, rows, scale = self.escape_menu_layout(width, height)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(QRectF(0, 0, width, height), QColor(0, 0, 0, 100))
        # Unified GPU uses the compositor's existing Jello blur. Emergency
        # compatibility draws this translucent card without CPU blur/readback.
        painter.setBrush(QColor(25, 28, 33, 220))
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
        painter.drawRoundedRect(panel, 12 * scale, 12 * scale)
        fonts = getattr(self, "fonts", None)
        font = (fonts.font("jello_light", max(10, round(27 * scale)))
                if fonts is not None else QFont("Helvetica Neue", max(10, round(27 * scale))))
        font.setWeight(QFont.Weight.Light)
        painter.setFont(font)
        painter.setPen(QColor(254, 254, 254))
        confirm = getattr(self, "_escape_menu_confirm_exit", False)
        painter.drawText(QRectF(panel.x(), panel.y() + 24 * scale, panel.width(), 45 * scale), Qt.AlignmentFlag.AlignCenter, "Exit client?" if confirm else "POLAR · Jello")
        font.setPointSize(max(8, round(10 * scale)))
        painter.setFont(font)
        painter.setPen(QColor(195, 202, 213))
        painter.drawText(QRectF(panel.x(), panel.y() + 75 * scale, panel.width(), 24 * scale), Qt.AlignmentFlag.AlignCenter, "Controls will lock before shutdown" if confirm else "Telemetry and safety monitoring remain active")
        for index, (rect, label) in enumerate(zip(rows, self.escape_menu_choices())):
            selected = index == self._escape_menu_selected
            painter.setPen(QPen(QColor(255, 255, 255, 95 if selected else 25), 1))
            painter.setBrush(QColor(255, 255, 255, 40 if selected else 12))
            painter.drawRoundedRect(rect, 5 * scale, 5 * scale)
            font.setPointSize(max(9, round(14 * scale)))
            painter.setFont(font)
            painter.setPen(QColor(254, 254, 254))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        font.setPointSize(max(8, round(10 * scale)))
        painter.setFont(font)
        painter.setPen(QColor(180, 188, 200))
        painter.drawText(QRectF(panel.x(), panel.bottom() - 36 * scale, panel.width(), 22 * scale), Qt.AlignmentFlag.AlignCenter, "Esc  Back     ↑ ↓  Select     Enter  Confirm")
        painter.restore()
