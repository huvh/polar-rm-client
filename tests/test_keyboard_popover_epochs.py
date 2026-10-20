"""Actual Qt stale-popover gestures and picker construction ownership.

No failing callback is injected: stale Add supplies None to the existing
picker, and its actual binding validation raises after QObject acquisition.
Bindings remain local drafts; no transport or physical output is started.
"""
import os
from pathlib import Path
import sys
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid
from test_cs2_settings_center import APP, Host
from rm_client.ui import jello_keybinds as keyboard


def flush():
    APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.processEvents()
    APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class KeyboardPopoverEpochTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.dialog = keyboard.build_keyboard_manager(self.host)
        self.dialog.show()
        self.dialog.timeline.reset(1)
        self.dialog._advance()
        APP.processEvents()
        self.canvas = self.dialog.canvas
        self.entry = next(entry for entry in self.dialog.session.entries
                          if entry.identity == ('module', 'ArmorAutoAim'))
        self.dialog.session.assign(self.entry, 'F10')
        self.original_bind = self.host.registry.get('ArmorAutoAim').keybind

    def tearDown(self):
        self.dialog.hide()
        self.host.deleteLater()
        flush()

    def render_popover(self):
        key = next(key for key in keyboard.ALL_KEYS if key.name == 'F10')
        if self.canvas.selected != key.name:
            self.canvas.select_key(key)
        self.canvas.pop_started = time.perf_counter() - 1
        self.canvas.grab()
        self.canvas._motion_timer.stop()

    def point(self, action):
        rect = next(rect for rect, name, payload in self.canvas.hotspots
                    if name == action and (name != 'remove' or payload == self.entry))
        x, y, scale = self.canvas.mapping()
        return QPointF(x + rect.center().x() * scale, y + rect.center().y() * scale)

    def press(self, point, button=Qt.MouseButton.LeftButton):
        APP.sendEvent(self.canvas, QMouseEvent(QEvent.Type.MouseButtonPress,
                      point, point, button, button, Qt.KeyboardModifier.NoModifier))

    def dismiss(self):
        APP.sendEvent(self.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                           Qt.KeyboardModifier.NoModifier))

    def test_escape_retires_remove_hit_before_the_next_paint(self):
        self.render_popover()
        point = self.point('remove')
        self.dismiss()
        self.assertIsNone(self.canvas.selected)
        self.press(point)
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'F10')
        self.assertEqual(self.host.registry.get('ArmorAutoAim').keybind, self.original_bind)

    def test_escape_retires_add_hit_without_exception_or_partial_picker(self):
        for _ in range(2):
            self.render_popover()
            point = self.point('add')
            self.dismiss()
            errors = []
            try:
                self.press(point)
            except Exception as error:
                errors.append(error)
            flush()
            self.assertEqual(errors, [])
            self.assertEqual(self.dialog.findChildren(keyboard.BindingPicker), [])

    def test_right_click_and_replacement_retire_old_popover_targets(self):
        for transition in ('right_click', 'blank_click', 'replace'):
            with self.subTest(transition=transition):
                self.dialog.session.assign(self.entry, 'F10')
                self.canvas.removed_rows.clear()
                self.canvas.pending_removals.clear()
                self.render_popover()
                point = self.point('remove')
                if transition == 'right_click':
                    self.press(QPointF(2, 2), Qt.MouseButton.RightButton)
                elif transition == 'blank_click':
                    self.press(QPointF(2, 2))
                else:
                    key = next(key for key in keyboard.ALL_KEYS if key.name == 'F6')
                    self.canvas.select_key(key)
                self.press(point)
                self.assertEqual(self.dialog.session.values[self.entry.identity], 'F10')

    def test_fresh_repaint_and_new_gesture_can_still_remove_binding(self):
        self.render_popover()
        self.dismiss()
        self.render_popover()
        self.press(self.point('remove'))
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'None')
        self.assertEqual(self.host.registry.get('ArmorAutoAim').keybind, self.original_bind)
        self.host.auto_save_config.assert_not_called()

    def test_scroll_retires_prior_row_geometry_until_repaint(self):
        entries = [entry for entry in self.dialog.session.entries
                   if entry.identity[0] == 'module' and not entry.readonly][:6]
        # Loading retains historical priority overlaps. New assignments cannot
        # create them, so load this multi-row state through BindingSession.
        for entry in entries:
            self.host.registry.get(entry.identity[1]).keybind = 'F10'
        self.dialog.session = keyboard.BindingSession(self.host)
        self.canvas.session = self.dialog.session
        self.render_popover()
        self.assertTrue(any(action == 'remove' for _, action, _ in self.canvas.hotspots))
        point = self.point('add')
        APP.sendEvent(self.canvas, QWheelEvent(point, point, QPoint(), QPoint(0, -120),
                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                      Qt.ScrollPhase.NoScrollPhase, False))
        self.assertGreater(self.canvas.pop_scroll, 0)
        self.assertTrue(all(action == 'done' for _, action, _ in self.canvas.hotspots))
        self.canvas.grab()
        self.assertTrue(any(action == 'remove' for _, action, _ in self.canvas.hotspots))

    def test_resize_retires_popover_hits_before_the_next_paint(self):
        self.render_popover()
        rect = next(rect for rect, action, entry in self.canvas.hotspots
                    if action == 'remove' and entry == self.entry)
        self.canvas.resize(self.canvas.width() - 80, self.canvas.height() - 60)
        x, y, scale = self.canvas.mapping()
        self.press(QPointF(x + rect.center().x() * scale, y + rect.center().y() * scale))
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'F10')
        self.canvas.grab()
        self.press(self.point('remove'))
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'None')

    def test_fresh_add_picker_still_applies_only_the_selected_draft(self):
        self.dialog.session.clear(self.entry)
        self.render_popover()
        errors = []
        def choose():
            picker = self.dialog.findChild(keyboard.BindingPicker)
            try:
                self.assertIsNotNone(picker)
                index = next(index for index, item in enumerate(picker.items)
                             if item.data(Qt.ItemDataRole.UserRole) == self.entry)
                picker.list.setCurrentRow(index)
                picker.add_selected()
            except Exception as error:
                errors.append(error)
                if picker is not None:
                    picker.reject()
        QTimer.singleShot(0, choose)
        self.press(self.point('add'))
        self.assertEqual(errors, [])
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'F10')
        self.assertEqual(self.host.registry.get('ArmorAutoAim').keybind, self.original_bind)
        self.host.auto_save_config.assert_not_called()
        flush()
        self.assertEqual(self.dialog.findChildren(keyboard.BindingPicker), [])

    def test_picker_owner_repaint_cannot_reactivate_pre_assignment_remove(self):
        # Historical overlaps can be restored without creating a new conflict.
        self.host.registry.get('Scenario').keybind = 'F10'
        self.host.registry.get('ArmorAutoAim').keybind = 'F10'
        self.dialog.session = keyboard.BindingSession(self.host)
        self.canvas.session = self.dialog.session
        earlier = next(entry for entry in self.dialog.session.entries
                       if entry.identity == ('module', 'Scenario'))
        self.dialog.session.clear(earlier)
        self.render_popover()
        stale_remove = self.point('remove')
        errors = []
        def choose():
            picker = self.dialog.findChild(keyboard.BindingPicker)
            try:
                self.assertIsNotNone(picker)
                self.canvas.grab()  # A normal owner paint during the nested loop.
                self.assertTrue(any(action == 'remove' for _, action, _ in self.canvas.hotspots))
                index = next(index for index, item in enumerate(picker.items)
                             if item.data(Qt.ItemDataRole.UserRole) == earlier)
                picker.list.setCurrentRow(index)
                picker.add_selected()
                picker.timeline.reset(0)
                picker._advance()  # Deterministically finish the real close animation.
            except Exception as error:
                errors.append(error)
                if picker is not None:
                    picker.reject()
        QTimer.singleShot(0, choose)
        self.press(self.point('add'))
        self.assertEqual(errors, [])
        self.assertEqual(self.dialog.session.values[earlier.identity], 'F10')
        self.press(stale_remove)
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'F10')
        self.host.auto_save_config.assert_not_called()

    def test_done_stays_live_after_popover_dismissal_before_repaint(self):
        self.render_popover()
        done = self.point('done')
        self.dismiss()
        self.assertTrue(any(action == 'done' for _, action, _ in self.canvas.hotspots))
        self.press(done)
        self.assertEqual(self.dialog._result, QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.timeline.target, 0)

    def test_cancelled_picker_retires_nested_repaint_hits_and_keeps_draft(self):
        self.render_popover()
        before = dict(self.dialog.session.values)
        errors = []
        def cancel():
            picker = self.dialog.findChild(keyboard.BindingPicker)
            try:
                self.assertIsNotNone(picker)
                self.canvas.grab()
                picker.reject()
                picker.timeline.reset(0)
                picker._advance()
            except Exception as error:
                errors.append(error)
                if picker is not None:
                    picker.reject()
        QTimer.singleShot(0, cancel)
        self.press(self.point('add'))
        self.assertEqual(errors, [])
        self.assertEqual(self.dialog.session.values, before)
        self.assertTrue(all(action == 'done' for _, action, _ in self.canvas.hotspots))
        self.render_popover()
        self.press(self.point('remove'))
        self.assertEqual(self.dialog.session.values[self.entry.identity], 'None')
        flush()
        self.assertEqual(self.dialog.findChildren(keyboard.BindingPicker), [])

    def test_actual_invalid_picker_key_retires_acquired_tree_and_keeps_siblings(self):
        sibling = QDialog(self.dialog)
        for _ in range(2):
            with self.assertRaises(AttributeError):
                keyboard.BindingPicker(self.dialog, None)
            flush()
            self.assertEqual(self.dialog.findChildren(keyboard.BindingPicker), [])
            self.assertTrue(isValid(sibling))
            self.assertTrue(isValid(self.dialog))
        picker = keyboard.BindingPicker(self.dialog, 'F10')
        self.assertTrue(isValid(picker))
        self.assertTrue(picker.items)
        picker.deleteLater()
        flush()
        self.assertTrue(isValid(sibling))


if __name__ == '__main__':
    unittest.main()
