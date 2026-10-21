"""Presentation policies: no game installation or live robot required."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.endfield_feedback import BootProgress, PowerAnnouncement, EndfieldFeedback


class EndfieldPolicies(unittest.TestCase):
    def test_boot_uses_completed_work_not_elapsed_time(self):
        boot = BootProgress()
        self.assertEqual(boot.progress, 0)
        self.assertTrue(boot.visible(100000))
        self.assertFalse(boot.take_announcement())
        boot.mark("configuration", 10)
        boot.mark("graphics", 11)
        self.assertAlmostEqual(boot.progress, 2 / 3)
        self.assertFalse(boot.take_announcement())
        boot.mark("atlases", 12)
        self.assertTrue(boot.take_announcement())
        self.assertFalse(boot.take_announcement())
        boot.mark("atlases", 99)
        self.assertEqual(boot.finished_at, 12)
        self.assertFalse(boot.visible(15))
        with self.assertRaises(ValueError):
            boot.mark("robot qualified", 20)

    def sample(self, policy, now, reserve=5, fresh=True, enabled=True):
        return policy.observe(now=now, reserve=reserve, maximum=100, threshold=20,
                              fresh=fresh, enabled=enabled)

    def test_power_debounce_hysteresis_and_cooldown(self):
        power = PowerAnnouncement()
        self.assertFalse(self.sample(power, 1))
        self.assertFalse(self.sample(power, 1.64))
        self.assertTrue(self.sample(power, 1.66))
        self.assertFalse(self.sample(power, 2))
        self.assertFalse(self.sample(power, 60))  # Still low: no spam.
        self.sample(power, 61, 40)
        self.sample(power, 63.1, 40)
        self.sample(power, 64)
        self.assertTrue(self.sample(power, 64.7))

    def test_unknown_stale_disabled_nan_and_out_of_range_never_warn(self):
        for value, fresh, enabled in ((5, False, True), (5, True, False),
                                       (float("nan"), True, True), (-1, True, True), (101, True, True)):
            power = PowerAnnouncement()
            for now in (1, 2, 30):
                self.assertFalse(self.sample(power, now, value, fresh, enabled))

    def test_disconnect_interrupts_low_observation_window(self):
        power = PowerAnnouncement()
        self.sample(power, 1)
        self.sample(power, 1.5, fresh=False)
        self.assertFalse(self.sample(power, 2))
        self.assertTrue(self.sample(power, 2.7))

    def test_dips_during_cooldown_do_not_retrigger(self):
        power = PowerAnnouncement()
        self.sample(power, 0)
        self.assertTrue(self.sample(power, 1))
        self.sample(power, 2, 40)
        self.sample(power, 5, 40)
        self.sample(power, 6)
        self.assertFalse(self.sample(power, 7))
        self.assertTrue(self.sample(power, 32))

    def make_feedback(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        feedback = EndfieldFeedback(Path(tmp.name))
        feedback.voice = Mock()
        return feedback

    def tick(self, feedback, now, identity=("rm2026-v1.3.1", 3), **kw):
        feedback.tick(now=now, identity=identity, connected=True, enabled=True,
                      threshold=20, **kw)

    def test_no_default_mock_values_are_consumed_as_measurements(self):
        feedback = self.make_feedback()
        for now in (1, 10, 100):
            self.tick(feedback, now)
        feedback.voice.play.assert_not_called()

    def test_presence_freshness_and_robot_switch(self):
        f = self.make_feedback()
        identity = ("rm2026-v1.3.1", 3)
        f.observe_referee("RobotStaticStatus", {"max_buffer_energy": 100}, 1, identity=identity)
        f.observe_referee("RobotDynamicStatus", {"current_buffer_energy": 5, "**present**": frozenset({1})}, 1, identity=identity)
        self.assertIsNone(f.reserve)
        f.observe_referee("RobotDynamicStatus", {"current_buffer_energy": 5, "**present**": frozenset({5})}, 10, identity=identity)
        self.tick(f, 10)
        self.tick(f, 10.7)
        f.voice.play.assert_called_once_with("power", volume=80)
        self.tick(f, 11, identity=("rm2026-v1.3.1", 4))
        self.assertIsNone(f.reserve)
        self.assertIsNone(f.maximum)

    def test_startup_announcement_once_and_muting(self):
        f = self.make_feedback()
        for phase in f.boot.PHASES:
            f.boot.mark(phase, 1)
        self.tick(f, 1)
        self.tick(f, 2)
        f.voice.play.assert_called_once_with("startup", volume=80)
        f = self.make_feedback()
        for phase in f.boot.PHASES:
            f.boot.mark(phase, 1)
        self.tick(f, 1, audio_enabled=False)
        self.tick(f, 2)
        f.voice.play.assert_not_called()  # No delayed surprise after unmuting.


if __name__ == "__main__":
    unittest.main()
