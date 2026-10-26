"""Esc is a GPU-treated world backdrop, not another layer over combat chrome."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from rm_client.ui.polar.compositor_plan import BackdropTreatment, OverlayScene
from cached_frame_trace_support import RecordedFrame
from test_cached_window_layers import RasterWindowFrame


class EscBackdropTests(unittest.TestCase):
    def test_escape_uses_gaussian_dimmed_world_without_combat_overlay(self):
        scene = OverlayScene(False, False, False, True)
        treatment = BackdropTreatment.resolve(scene, economy_progress=0., clickgui_progress=0.,
            jello_blur_radius=None, student_panel="damage", student_progress=1.)
        self.assertTrue(treatment.active)
        self.assertEqual(treatment.blur_kernel, "endfield_gaussian")
        self.assertFalse(treatment.include_overlay)
        self.assertGreater(treatment.blur_radius_px, 5.)
        self.assertGreater(treatment.dim_alpha, .25)
        self.assertEqual(scene.glass_owners(radial_visible=True, hero_visible=True), frozenset())

    def test_escape_never_redraws_crisp_combat_or_clickgui_over_treated_background(self):
        runner = RecordedFrame("escape")
        try:
            events, result = runner.run()
            self.assertTrue(result["accepted"])
            names = [row[0] for row in events]
            self.assertNotIn("hud.motion", names)
            self.assertNotIn("clickgui.paint", names)
            self.assertNotIn("vision", names)
            self.assertNotIn("target", names)
            self.assertIn("priority", names)
        finally:
            runner.close()

    def test_actual_layers_empty_in_menu_and_combat_restores_without_setting_changes(self):
        for ratio in (1., 1.5):
            with self.subTest(ratio=ratio):
                runner = RasterWindowFrame("escape", ratio=ratio)
                try:
                    w, c = runner.window, runner.c
                    enabled = [(m.name, m.enabled) for m in w.registry.modules]
                    # A ready native child is drawn by D3D, never into Qt's
                    # foreground FBO. Even stale chat/student state cannot leak.
                    w._endfield_menu = NS(ready=True, error="", backdrop_frame_ready=Mock())
                    w.match_chat.open_input()
                    w.student_ui.open("damage")
                    with patch.object(w, "draw_match_chat") as chat, \
                         patch.object(w, "draw_student_frontend") as student:
                        result = runner.frame()
                    self.assertTrue(result["accepted"])
                    chat.assert_not_called()
                    student.assert_not_called()
                    for layer in ("overlay", "vision", "dynamic", "target"):
                        image = getattr(c, layer + "_fbo").image
                        self.assertFalse(any(bytes(image.constBits())), layer)
                    self.assertEqual(c._static_glass_commands, [])
                    self.assertEqual(c._frame_glass_commands, [])
                    w._endfield_menu = None
                    w.set_escape_menu_visible(False)
                    w.student_ui.close()
                    w.match_chat.close_input()
                    restored = runner.frame(now=101.)
                    self.assertTrue(restored["accepted"])
                    self.assertFalse(c._backdrop_treatment.active)
                    self.assertTrue(any(bytes(c.dynamic_fbo.image.constBits())))
                    self.assertEqual([(m.name, m.enabled) for m in w.registry.modules], enabled)
                finally:
                    runner.close()


if __name__ == "__main__":
    unittest.main()
