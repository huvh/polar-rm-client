"""Official ring score and mock percent use separate display paths."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.model import RobotState
from rm_client.ui.rune_display import rune_display
from rm_client.ui.hud_locale import hud_text
from test_hud_display_locale import Host, Painter, QRectF, VisionTarget, ct, ew


class RuneDisplayTests(unittest.TestCase):
    def test_official_average_is_rings_not_percent(self):
        state = RobotState(official_state_active=True, rune_status={'rune_status':2,'average_rings':8.5}, energy_rune_progress=48)
        self.assertEqual(rune_display(state).value, '8.5 rings')
        self.assertIsNone(rune_display(state).progress)
        self.assertEqual(state.energy_rune_progress, 48)
        self.assertEqual(hud_text(rune_display(state).value, True), '8.5 环')

    def test_official_missing_inactive_invalid_score_never_uses_mock(self):
        state = RobotState(official_state_active=True)
        for status in ({}, {'rune_status':1,'average_rings':8.5}, {'rune_status':3,'average_rings':8.5},
                       {'rune_status':'2','average_rings':8.5}, {'rune_status':2},
                       *({'rune_status':2,'average_rings':v} for v in (math.nan,math.inf,-1,True,'8.5'))):
            state.rune_status=status
            display=rune_display(state)
            self.assertNotIn('%',display.value)
            self.assertNotIn('rings',display.value)
            self.assertIsNone(display.progress)
        self.assertEqual(rune_display(RobotState(official_state_active=True)).value,'UNKNOWN')

    def test_explicit_mock_preserves_progress_unknown_sources_do_not(self):
        state=RobotState(energy_rune_progress=48)
        self.assertEqual((rune_display(state).value,rune_display(state).progress),('48%',.48))
        for value in (math.nan,math.inf,'48',True):
            state.energy_rune_progress=value
            self.assertEqual(rune_display(state).value,'UNKNOWN')
        state.energy_rune_progress=48
        state.mock_simulation_enabled=False
        self.assertEqual(rune_display(state).value,'UNKNOWN')
        state.mock_simulation_enabled=True
        state.official_state_active='false'
        self.assertEqual(rune_display(state).value,'UNKNOWN')

    def test_every_target_hud_style_shows_rings_without_progress_bar(self):
        target=VisionTarget(10,20,80,80,.9,'opaque Rune', 'energy')
        for language, score in (('English','8.5 rings'),('中文','8.5 环')):
            for method in ('draw_target_card','draw_target_round_compact','draw_target_bar_only'):
                host=Host(language);painter=Painter()
                host.state.official_state_active=True
                host.state.rune_status={'rune_status':2,'average_rings':8.5}
                try:
                    with patch.object(ct,'draw_bar') as bar:
                        args=[painter,QRectF(10,20,224,82),target]
                        if method=='draw_target_card':args.append('EnergyTargetHUD')
                        getattr(host,method)(*args)
                        self.assertIn(score,[v for _,v in host.texts])
                        self.assertFalse(any('%' in v for _,v in host.texts))
                        bar.assert_not_called()
                    self.assertEqual(host.target_ratio(target),0.)
                finally:painter.close()

    def test_ring_esp_omits_official_marker_but_keeps_detector_confidence(self):
        target=VisionTarget(10,20,80,80,.9,'opaque Rune', 'energy')
        host=Host('English');painter=Painter();host.draw_pill=lambda *args: None
        host.state.official_state_active=True
        host.state.rune_status={'rune_status':2,'average_rings':8.5}
        try:
            with patch.object(ew,'draw_bar') as bar:
                host.draw_rune_ring_lock(painter,QRectF(10,20,80,80),target,None,True)
                bar.assert_not_called()
            self.assertEqual(sum(name=='drawEllipse' for name,_ in painter.geometry),1)
            self.assertEqual(host.target_overlay_label(target),'opaque Rune  90%  18.5m  8.5 rings')
        finally:painter.close()

    def test_mock_ring_marker_and_percent_remain(self):
        target=VisionTarget(10,20,80,80,.9,'opaque Rune', 'energy')
        host=Host('English');painter=Painter();host.draw_pill=lambda *args: None
        try:
            with patch.object(ew,'draw_bar') as bar:
                host.draw_rune_ring_lock(painter,QRectF(10,20,80,80),target,None,True)
                bar.assert_called_once()
            self.assertEqual(sum(name=='drawEllipse' for name,_ in painter.geometry),2)
            self.assertIn('48%',host.target_overlay_label(target))
        finally:painter.close()


if __name__=='__main__':unittest.main()
