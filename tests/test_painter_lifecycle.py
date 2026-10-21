"""Preserve rejection semantics except Qt's documented OpenGL end quirk."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QPaintEngine
from rm_client.ui.painter_lifecycle import finish_painter


class PainterRetirementTests(unittest.TestCase):
    def painter(self, *, opengl=True, before=True, after=False, device_busy=False):
        p = Mock()
        p.isActive.side_effect = [before, after]
        p.paintEngine.return_value.type.return_value = (
            QPaintEngine.Type.OpenGL2 if opengl else QPaintEngine.Type.Raster)
        p.device.return_value.paintingActive.return_value = device_busy
        p.end.return_value = False
        return p

    def test_opengl_false_is_accepted_only_after_complete_retirement(self):
        self.assertTrue(finish_painter(self.painter()))
        self.assertFalse(finish_painter(self.painter(after=True)))
        self.assertFalse(finish_painter(self.painter(device_busy=True)))

    def test_raster_and_inactive_rejections_remain_rejections(self):
        self.assertFalse(finish_painter(self.painter(opengl=False)))
        self.assertFalse(finish_painter(self.painter(before=False)))

    def test_exceptions_propagate_for_existing_pass_diagnostics(self):
        painter = self.painter()
        painter.end.side_effect = OSError("real cleanup fault")
        with self.assertRaisesRegex(OSError, "real cleanup fault"):
            finish_painter(painter)


if __name__ == "__main__":
    unittest.main()
