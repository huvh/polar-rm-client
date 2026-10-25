"""Actual window keyboard/mouse paths; final transport sinks are inert."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_modal_input_epoch import window_fixture
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QFocusEvent, QImage, QMouseEvent, QPainter, QWheelEvent
from rm_client.ui.cs2_scoreboard import paint_tab_scoreboard


def mouse(kind,point,button=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind,point,point,button,
                       button if kind==QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier)


class TabInputTests(unittest.TestCase):
    def paint(self,window):
        image=QImage(1280,720,QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p=QPainter(image)
        try:paint_tab_scoreboard(window,p,1280,720,10)
        finally:p.end()

    def test_tab_and_rebound_map_key_open_both_repeat_release_and_reverse(self):
        for key in (Qt.Key.Key_Tab,Qt.Key.Key_J):
            with self.subTest(key=key),window_fixture() as (case,w,sink):
                w.economy_island.progress=0  # Fixture starts with the old economy lens open.
                w.registry.get('TacticalMap').enabled=True
                w.registry.get('TacticalMap').keybind='J'
                case.key(key)
                self.assertTrue(w.tactical_map_hold)
                w.tactical_map_state.container.content.progress=1
                self.paint(w)
                self.assertIsNotNone(w._tab_scoreboard_bounds)
                case.key(key,repeat=True,release=True)
                self.assertTrue(w.tactical_map_hold)
                case.key(key,release=True)
                self.assertFalse(w.tactical_map_hold)
                w.tactical_map_state.container.content.progress=.4
                self.paint(w)
                self.assertIsNotNone(w._tab_scoreboard_bounds)
                case.key(key)
                self.assertTrue(w.tactical_map_hold)
                w.tactical_map_state.container.content.progress=0
                case.key(key,release=True)
                self.paint(w)
                self.assertIsNone(w._tab_scoreboard_bounds)

    def test_board_press_move_release_never_clicks_map_fires_or_leaks_hotspot(self):
        with window_fixture() as (case,w,sink):
            w.economy_island.progress=0
            w.registry.get('TacticalMap').enabled=True
            w.tactical_map_state.container.content.progress=1
            self.paint(w)
            point=w._tab_scoreboard_bounds.center()
            from rm_client.ui.polar.primitives import Hotspot
            w.hotspots=[Hotspot(QRectF(point.x()-10,point.y()-10,20,20),'hidden_action')]
            for button in (Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton,Qt.MouseButton.MiddleButton):
                with patch.object(w,'dispatch') as dispatch,patch.object(w,'publish_map_click_from_screen') as mark,\
                     patch.object(w.control,'set_mouse_button') as control,patch.object(w.control,'add_mouse_motion') as motion:
                    w.mousePressEvent(mouse(QEvent.Type.MouseButtonPress,point,button))
                    w.mouseMoveEvent(mouse(QEvent.Type.MouseMove,point+QPointF(2,3),Qt.MouseButton.NoButton))
                    w.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease,point,button))
                    dispatch.assert_not_called();mark.assert_not_called();motion.assert_not_called()
                    self.assertTrue(all(call.args[1] is False for call in control.call_args_list))

    def test_focus_loss_and_modal_entry_retire_both_without_changing_module_settings(self):
        for enter in (lambda w:w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut)),
                      lambda w:w.set_escape_menu_visible(True),
                      lambda w:w.open_match_chat(),
                      lambda w:w.set_clickgui_visible(True,announce=False,play_sound=False)):
            with window_fixture() as (case,w,sink):
                w.economy_island.progress=0
                w.registry.get('TacticalMap').enabled=True
                before={m.name:m.enabled for m in w.registry.modules}
                case.key(Qt.Key.Key_Tab)
                w.tactical_map_state.container.content.progress=1
                self.paint(w)
                self.assertIsNotNone(w._tab_scoreboard_bounds)
                enter(w)
                self.assertFalse(w.tactical_map_hold)
                if not w.menu_overlay_active():
                    # A non-modal focus loss retains only the shared closing
                    # animation, then both surfaces vanish at the same edge.
                    w.tactical_map_state.container.content.progress=0
                self.paint(w)
                self.assertIsNone(w._tab_scoreboard_bounds)
                self.assertEqual(before,{m.name:m.enabled for m in w.registry.modules})

    def test_board_wheel_cannot_scroll_hidden_gui_or_send_control(self):
        with window_fixture() as (case,w,sink):
            w.economy_island.progress=0
            w.registry.get('TacticalMap').enabled=True
            w.tactical_map_state.container.content.progress=1
            self.paint(w)
            point=w._tab_scoreboard_bounds.center()
            event=QWheelEvent(point,point,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            with patch.object(w.control,'add_wheel') as wheel,patch.object(w,'dispatch') as dispatch:
                w.wheelEvent(event)
            wheel.assert_not_called();dispatch.assert_not_called()
            self.assertTrue(event.isAccepted())


if __name__=='__main__':unittest.main()
