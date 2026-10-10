import math
import unittest
from rm_client.top_match_bar_motion import css_ease_out, kill_pop_scale, DEAD_OPACITY, DEAD_CONTRAST


class SourceMotionTests(unittest.TestCase):
    def test_stylesheet_death_constants(self):
        self.assertEqual(DEAD_OPACITY, .2)
        self.assertEqual(DEAD_CONTRAST, .9)

    def test_css_ease_out_endpoints_and_midpoint(self):
        self.assertEqual(css_ease_out(0), 0)
        self.assertEqual(css_ease_out(1), 1)
        self.assertAlmostEqual(css_ease_out(.5), .684643, places=5)

    def test_kill_pop_300ms_endpoint(self):
        self.assertEqual(kill_pop_scale(0), 1.2)
        self.assertEqual(kill_pop_scale(.3), 1.0)
        self.assertEqual(kill_pop_scale(5), 1.0)

    def test_curve_has_no_overshoot_or_time_dependent_fps(self):
        values = [kill_pop_scale(i / 60) for i in range(19)]
        self.assertTrue(all(1 <= value <= 1.2 for value in values))
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertAlmostEqual(kill_pop_scale(9 / 60), kill_pop_scale(18 / 120))

    def test_initial_time_is_clamped(self):
        self.assertEqual(kill_pop_scale(-1), 1.2)

    def test_invalid_time_is_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                kill_pop_scale(bad)


if __name__ == "__main__":
    unittest.main()
