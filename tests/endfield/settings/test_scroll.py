"""本体参数、帧率一致性、真实Qt事件路由与滚动生命周期。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT),str(ROOT/"tests")]
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from test_cs2_settings_center import APP
from rm_client.ui.endfield.settings.resources import source
from rm_client.ui.endfield.settings.scroll import EndfieldScrollArea
from rm_client.ui.endfield.settings.scroll_motion import ScrollMotion
from rm_client.ui.endfield.settings.widgets import EndfieldComboBox


class MotionTests(unittest.TestCase):
    def motion(self):
        motion = ScrollMotion(source()["scroll"])
        motion.maximum = 10000
        motion.extent = 500
        return motion

    def test_wheel_has_intermediate_frames_and_reverses_from_current_position(self):
        motion = self.motion()
        motion.wheel(450)
        self.assertEqual(motion.position,0)
        motion.advance(.1)
        self.assertGreater(motion.position,0)
        self.assertLess(motion.position,450)
        previous = motion.position
        motion.wheel(-45)
        self.assertEqual(motion.position,previous)
        motion.advance(.02)
        self.assertLess(motion.position,previous)

    def test_inertia_decay_and_distance_match_at_30_60_144_hz(self):
        positions = []
        for fps in (30,60,144):
            motion = self.motion()
            motion.position = 1000
            motion.velocity = 500
            motion.mode = "inertia"
            for _ in range(fps):
                motion.advance(1/fps)
            self.assertAlmostEqual(motion.velocity,500*.13500000536441803,places=6)
            positions.append(motion.position)
        self.assertLess(max(positions)-min(positions),.001)

    def test_drag_uses_rubber_boundary_and_returns_after_release(self):
        motion = self.motion()
        motion.begin_drag()
        motion.drag(-150)
        self.assertGreater(motion.position,-150)
        self.assertLess(motion.position,0)
        motion.advance(.016)
        motion.release()
        for _ in range(150):
            motion.advance(1/120)
        self.assertEqual(motion.position,0)
        self.assertEqual(motion.mode,"idle")

    def test_regrab_of_overscroll_does_not_jump(self):
        motion = self.motion()
        motion.position = -25
        motion.begin_drag()
        motion.drag(0)
        self.assertAlmostEqual(motion.position,-25)


class QtScrollTests(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.window.resize(1000,620)
        layout = QVBoxLayout(self.window)
        self.scroll = EndfieldScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        content = QWidget()
        rows = QVBoxLayout(content)
        self.combo = EndfieldComboBox()
        self.combo.addItems(("一","二","三"))
        rows.addWidget(self.combo)
        self.label = QLabel("拖动此设置行")
        rows.addWidget(self.label)
        for i in range(40):
            label = QLabel(str(i))
            label.setMinimumHeight(40)
            rows.addWidget(label)
        self.scroll.setWidget(content)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def wheel(self, target, delta):
        local = target.rect().center()
        event = QWheelEvent(QPointF(local),QPointF(target.mapToGlobal(local)),QPoint(),QPoint(0,delta),
                            Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        APP.sendEvent(target,event)

    def test_wheel_over_combo_scrolls_page_without_editing_setting(self):
        now = [10.0]
        with patch.object(self.scroll,"clock",side_effect=lambda:now[0]):
            self.wheel(self.combo,-120)
            target = self.scroll.motion.target
            self.assertGreater(target,0)
            self.assertEqual(self.scroll.verticalScrollBar().value(),0)
            now[0] += .015
            self.scroll._tick()
            self.assertGreater(self.scroll.motion.position,0)
            self.assertLess(self.scroll.motion.position,target)
            now[0] += .1
            self.scroll._tick()
        self.assertEqual(self.combo.currentIndex(),0)

    def mouse(self, target, kind, global_point, button, buttons):
        local = target.mapFromGlobal(global_point.toPoint())
        APP.sendEvent(target,QMouseEvent(kind,QPointF(local),global_point,button,buttons,Qt.KeyboardModifier.NoModifier))

    def test_drag_on_label_reaches_scroll_owner_and_releases_with_inertia(self):
        start = QPointF(self.label.mapToGlobal(self.label.rect().center()))
        self.mouse(self.label,QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton)
        for i in range(1,7):
            self.mouse(self.scroll.viewport(),QEvent.Type.MouseMove,start-QPointF(0,i*12),
                       Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton)
            QTest.qWait(16)
        self.mouse(self.scroll.viewport(),QEvent.Type.MouseButtonRelease,start-QPointF(0,72),
                   Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)
        released = self.scroll.motion.position
        QTest.qWait(80)
        self.assertGreater(self.scroll.motion.position,released)
        self.assertEqual(self.scroll.motion.mode,"inertia")

    def test_scrollbar_and_hide_cancel_animation_and_restore_content_position(self):
        self.wheel(self.label,-120)
        self.scroll.verticalScrollBar().setValue(100)
        self.assertEqual(self.scroll.motion.mode,"idle")
        self.assertFalse(self.scroll._timer.isActive())
        self.wheel(self.label,-120)
        self.window.hide()
        self.assertFalse(self.scroll._timer.isActive())
        self.assertEqual(self.scroll.widget().y(),-self.scroll.verticalScrollBar().value())

    def test_nested_scroll_areas_deliver_wheel_only_to_innermost_owner(self):
        inner = EndfieldScrollArea()
        inner.setFixedHeight(150)
        inner.setWidgetResizable(True)
        content = QWidget()
        content.setMinimumHeight(700)
        inner.setWidget(content)
        self.scroll.widget().layout().insertWidget(0,inner)
        APP.processEvents()
        self.wheel(content,-120)
        self.assertEqual(inner.motion.mode,"tween")
        self.assertEqual(self.scroll.motion.mode,"idle")


if __name__ == "__main__":
    unittest.main()
