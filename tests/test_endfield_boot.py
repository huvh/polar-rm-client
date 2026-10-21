"""Original prefab geometry/curve math; no private game asset required."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRectF
from rm_client.ui.endfield_boot import child_rect, rotation_degrees


class BootMathTests(unittest.TestCase):
    def test_unity_bottom_anchor_stretches_without_overflow(self):
        node = {"transform": {"m_AnchorMin": {"x": 0, "y": 0}, "m_AnchorMax": {"x": 1, "y": 0},
                              "m_Pivot": {"x": .5, "y": .5}, "m_AnchoredPosition": {"x": 0, "y": 54},
                              "m_SizeDelta": {"x": -660, "y": 5}}}
        for scale in (.5, 1, 1.25, 1.5, 2):
            parent = QRectF(0, 960*scale, 1920*scale, 120*scale)
            rect = child_rect(node, parent, scale)
            self.assertAlmostEqual(rect.x(), 330*scale)
            self.assertAlmostEqual(rect.width(), 1260*scale)
            self.assertAlmostEqual(rect.center().y(), 1026*scale)
            self.assertTrue(parent.contains(rect))

    def test_quaternion_curve_uses_authored_slopes_and_loops(self):
        a = {"time": 0., "value": {"z": 0., "w": 1.}, "inSlope": {"z": 0., "w": 0.}, "outSlope": {"z": 0., "w": 0.}}
        b = {"time": 1., "value": {"z": -1., "w": 0.}, "inSlope": {"z": 0., "w": 0.}, "outSlope": {"z": 0., "w": 0.}}
        self.assertAlmostEqual(rotation_degrees([a,b], .5), 90.)
        self.assertAlmostEqual(rotation_degrees([a,b], 1.5), 90.)
        self.assertAlmostEqual(rotation_degrees([a,b], 0), 0.)


if __name__ == "__main__":
    unittest.main()
