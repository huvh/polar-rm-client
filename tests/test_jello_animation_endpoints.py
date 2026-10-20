"""Exact Jello endpoints without early snapping or changing native durations."""
import os
from pathlib import Path
import sys
from time import monotonic
import math
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rm_client.ui import jello_widgets
from rm_client.ui.jello_clickgui import JelloMainTimeline, JelloReversibleAnimation

APP = QApplication.instance() or QApplication([])


class TimelineEndpointTests(unittest.TestCase):
    def test_near_endpoints_remain_active_until_the_elapsed_time_crosses_them(self):
        # Checkbox, native dialogs, and ClickGUI panel/hover/dropdown timelines.
        for forward, reverse in ((.09, .07), (.45, .125), (.2, .125),
                                 (.2, .12), (.24, .2), (.22, .22), (.114, .114)):
            for start, target, duration in ((0., 1., forward), (1., 0., reverse)):
                with self.subTest(durations=(forward, reverse), target=target):
                    motion = JelloReversibleAnimation(forward, reverse)
                    motion.reset(start); motion.set_target(target)
                    motion.update(duration * .99995)
                    self.assertNotEqual(motion.progress, target)
                    self.assertTrue(motion.active())
                    near = motion.progress
                    motion.update(0)
                    self.assertEqual(motion.progress, near)
                    self.assertTrue(motion.active())
                    motion.update(duration * .0001)
                    self.assertEqual(motion.progress, target)
                    self.assertFalse(motion.active())

    def test_original_durations_reach_exact_endpoints(self):
        self.assertEqual((JelloMainTimeline().forward_duration,
                          JelloMainTimeline().reverse_duration), (.45, .125))
        motion = JelloReversibleAnimation(.09, .07)
        motion.set_target(1); motion.update(.09)
        self.assertEqual(motion.progress, 1); self.assertFalse(motion.active())
        motion.set_target(0); motion.update(.07)
        self.assertEqual(motion.progress, 0); self.assertFalse(motion.active())

    def test_reversal_preserves_progress_and_direction_specific_rate(self):
        motion = JelloReversibleAnimation(.09, .07)
        motion.set_target(1); motion.update(.045)
        self.assertEqual(motion.progress, .5)
        motion.set_target(0)
        self.assertEqual(motion.progress, .5)
        motion.update(.035)
        self.assertEqual(motion.progress, 0); self.assertFalse(motion.active())
        motion.set_target(1); motion.update(.09)
        self.assertEqual(motion.progress, 1); self.assertFalse(motion.active())

    def test_zero_and_negative_durations_keep_existing_one_ms_floor(self):
        for duration in (0., -1.):
            with self.subTest(duration=duration):
                motion = JelloReversibleAnimation(duration, duration)
                motion.set_target(1); motion.update(0)
                self.assertEqual(motion.progress, 0); self.assertTrue(motion.active())
                motion.update(.0005)
                self.assertEqual(motion.progress, .5); self.assertTrue(motion.active())
                motion.update(.0005)
                self.assertEqual(motion.progress, 1); self.assertFalse(motion.active())
                motion.set_target(0); motion.update(.001)
                self.assertEqual(motion.progress, 0); self.assertFalse(motion.active())

    def test_negative_dt_and_large_dt_preserve_clamping(self):
        motion = JelloReversibleAnimation(.09, .07)
        motion.set_target(1); motion.update(-1)
        self.assertEqual(motion.progress, 0); self.assertTrue(motion.active())
        motion.update(1000)
        self.assertEqual(motion.progress, 1); self.assertFalse(motion.active())
        motion.set_target(0); motion.update(1000)
        self.assertEqual(motion.progress, 0); self.assertFalse(motion.active())

    def test_one_ulp_remainders_finish_on_a_positive_clock_step(self):
        for target in (0., 1.):
            with self.subTest(target=target):
                motion = JelloReversibleAnimation(.09, .07)
                motion.reset(math.nextafter(target, 1. - target))
                motion.set_target(target)
                self.assertTrue(motion.active())
                motion.update(.001)
                self.assertEqual(motion.progress, target)
                self.assertFalse(motion.active())
        motion.reset(.37)
        self.assertEqual(motion.progress, motion.target)
        self.assertFalse(motion.active())


class TimerConsumerEndpointTests(unittest.TestCase):
    def setUp(self):
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            timer = getattr(widget, '_timer', None)
            if timer is None:
                timer = widget._transition_timer
            timer.stop(); widget.hide(); widget.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def wait_for(self, predicate):
        # Observe actual Qt timer callbacks. This deadline is not a timing
        # benchmark; the controlled monotonic clock below specifies elapsed dt.
        deadline = monotonic() + 1
        while not predicate():
            if monotonic() >= deadline:
                self.fail('Expected real Qt timer callback did not arrive')
            QTest.qWait(1)

    def test_checkbox_timer_remains_live_inside_both_old_epsilon_boundaries(self):
        for checked, duration in ((True, .09), (False, .07)):
            with self.subTest(checked=checked):
                box = jello_widgets.JelloCheckBox(); self.widgets.append(box)
                box.setChecked(not checked)  # Hidden setup snaps intentionally.
                box.show(); APP.processEvents()
                start = float(not checked)
                with patch.object(jello_widgets.time, 'perf_counter', return_value=0.):
                    box.setChecked(checked)
                with patch.object(jello_widgets.time, 'perf_counter',
                                  return_value=duration * .99995):
                    self.wait_for(lambda: box.motion.progress != start)
                    self.assertNotEqual(box.motion.progress, float(checked))
                    self.assertTrue(box.motion.active())
                    self.assertTrue(box._timer.isActive())
                with patch.object(jello_widgets.time, 'perf_counter',
                                  return_value=duration + .001):
                    self.wait_for(lambda: not box._timer.isActive())
                self.assertEqual(box.motion.progress, float(checked))
                self.assertFalse(box.motion.active())

    def test_checkbox_reversal_keeps_timer_live_until_reverse_endpoint(self):
        box = jello_widgets.JelloCheckBox(); self.widgets.append(box)
        box.show(); APP.processEvents()
        with patch.object(jello_widgets.time, 'perf_counter', return_value=0.):
            box.setChecked(True)
        with patch.object(jello_widgets.time, 'perf_counter', return_value=.045):
            self.wait_for(lambda: box.motion.progress > 0)
            self.assertEqual(box.motion.progress, .5)
            box.setChecked(False)
            self.assertEqual(box.motion.progress, .5)
        with patch.object(jello_widgets.time, 'perf_counter', return_value=.0799965):
            self.wait_for(lambda: box.motion.progress < .5)
            self.assertGreater(box.motion.progress, 0)
            self.assertLess(box.motion.progress, .0001)
            self.assertTrue(box.motion.active()); self.assertTrue(box._timer.isActive())
        with patch.object(jello_widgets.time, 'perf_counter', return_value=.081):
            self.wait_for(lambda: not box._timer.isActive())
        self.assertEqual(box.motion.progress, 0)

    def test_native_dialogs_finish_both_directions_only_at_exact_endpoints(self):
        for keyboard, forward in ((False, .45), (True, .2)):
            with self.subTest(keyboard=keyboard):
                dialog = jello_widgets.JelloDialog(keyboard=keyboard)
                self.widgets.append(dialog); dialog.resize(400, 300)
                with patch.object(jello_widgets.time, 'perf_counter', return_value=0.):
                    dialog.show()
                with patch.object(jello_widgets.time, 'perf_counter',
                                  return_value=forward * .99995):
                    self.wait_for(lambda: dialog.timeline.progress > 0)
                    self.assertLess(dialog.timeline.progress, 1)
                    self.assertTrue(dialog.timeline.active())
                    self.assertTrue(dialog._transition_timer.isActive())
                    self.assertFalse(dialog.panel.isVisible())
                with patch.object(jello_widgets.time, 'perf_counter',
                                  return_value=forward + .001):
                    self.wait_for(lambda: not dialog._transition_timer.isActive())
                self.assertEqual(dialog.timeline.progress, 1)
                self.assertTrue(dialog.panel.isVisible())
                with patch.object(jello_widgets.time, 'perf_counter', return_value=1.):
                    dialog.reject()
                with patch.object(jello_widgets.time, 'perf_counter',
                                  return_value=1. + .125 * .99995):
                    self.wait_for(lambda: dialog.timeline.progress < 1)
                    self.assertGreater(dialog.timeline.progress, 0)
                    self.assertTrue(dialog.timeline.active())
                    self.assertTrue(dialog._transition_timer.isActive())
                    self.assertTrue(dialog.isVisible())
                with patch.object(jello_widgets.time, 'perf_counter', return_value=1.126):
                    self.wait_for(lambda: not dialog._transition_timer.isActive())
                self.assertEqual(dialog.timeline.progress, 0)
                self.assertFalse(dialog.isVisible())


if __name__ == '__main__':
    unittest.main()
