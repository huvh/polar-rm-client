"""Freeze diagnostic precedence and paint/error order before caption extraction."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import test_hud_display_locale as fixture
from rm_client.ui.polar.renderers import module_list as production
from rm_client.ui.hud_locale import hud_text

namespace = dict(vars(production))
exec(compile((ROOT / 'tests/fixtures/rm_indicators_caption_baseline.py.txt').read_text(),
             'rm_indicators_caption_baseline.py.txt', 'exec'), namespace)
BASELINE = namespace['draw_rm_indicators_hud']


def stats(**changes):
    value = dict(port='COM7', resolved_port='COM9', link_alive=True,
                 role_hud_code='INF', role_id=3, role_max_linear_mps=2.5,
                 role_selected_id=3, role_reported_id=4, segments_received=12,
                 authority={'state': 'CLIENT', 'reason': 'operator'},
                 motion={'state': 'IDLE', 'detail': 'idle'})
    value.update(changes)
    return value


class RmIndicatorCaptionContractTests(unittest.TestCase):
    def capture(self, draw, values, language):
        host = fixture.Host(language)
        host.state.polar_link_active = True
        host.state.backend_stats = {'polar_link': deepcopy(values)}
        painter = fixture.Painter()
        colors = []
        original = host.draw_text
        def text(p, rect, caption, font, color, *args):
            colors.append((str(caption), color.rgba()))
            return original(p, rect, caption, font, color, *args)
        host.draw_text = text
        error = None
        try:
            with patch('time.perf_counter', return_value=1000.), patch('time.time', return_value=1000.):
                draw(host, painter, 1280)
        except (TypeError, ValueError) as exc:
            error = (type(exc).__name__, str(exc))
            painter.painter.restore()  # release the interrupted draw's save
        finally:
            painter.close()
        pixels = hashlib.sha256(bytes(painter.image.constBits())).hexdigest()
        self.assertEqual(host.state.backend_stats, {'polar_link': values})
        return host.texts, colors, host.hotspots, painter.geometry, error, pixels

    def compare(self, values, language='English'):
        baseline = self.capture(BASELINE, values, language)
        candidate = self.capture(production.ModuleListMixin.draw_rm_indicators_hud, values, language)
        self.assertEqual(candidate, baseline)
        return candidate

    def test_warning_priority_and_authority_in_both_languages(self):
        cases = [
            (dict(role_mismatch='wrong role', role_drive_block='blocked', motion={'state':'STUCK'}), 'MISMATCH', 'warning'),
            (dict(role_drive_block='blocked', motion={'state':'STUCK'}), 'DRIVE BLOCKED', 'warning'),
            *[(dict(motion={'state': value}), value, 'warning') for value in ('STUCK','NO_FEEDBACK','STALE_FEEDBACK','NO_MOTION')],
            (dict(motion={'state':'OK'}), 'CLIENT', 'success'),
            (dict(motion={'state':'IDLE'}), 'CLIENT', 'accent'),
        ]
        for language in ('English', '简体中文'):
            for changes, word, severity in cases:
                with self.subTest(language=language, changes=changes):
                    result = self.compare(stats(**changes), language)
                    self.assertIsNone(result[4])
                    captions = [(text, color) for text, color in result[1] if 'INF#3' in text]
                    self.assertEqual(len(captions), 1)
                    text, color = captions[0]
                    host = fixture.Host(language)
                    self.assertEqual(color, getattr(host, 'hud_' + severity)().rgba())
                    if word == 'MISMATCH':
                        self.assertIn('UI#3!=ROBOT#4' if language == 'English' else '界面#3!=机器人#4', text)
                    else:
                        self.assertIn(hud_text(word, language != 'English'), text)

    def test_disconnected_defaults_and_supported_malformed_authority(self):
        for language in ('English', '简体中文'):
            for authority in (None, 'bad', [], {'state':None}):
                with self.subTest(language=language, authority=authority):
                    result = self.compare(stats(authority=authority), language)
                    self.assertIsNone(result[4])
                    self.assertTrue(any('INF#3' in text and text.endswith(' · -') for _,text in result[0]))
            result = self.compare(stats(link_alive=False, last_error_code='', port='Auto'), language)
            self.assertTrue(any('NO_STREAM · Auto' in text for _,text in result[0]))
            self.assertFalse(any(h[2]=='telemetry' for h in result[2]))

    def test_tooltip_keeps_warning_order_and_500_character_limit(self):
        values = stats(role_known=False, role_mismatch='mismatch detail', role_drive_block='drive detail',
                       last_error='long reason ' * 100)
        result = self.compare(values)
        tooltip = next(h[3] for h in result[2] if h[2]=='diagnostics')
        self.assertEqual(len(tooltip), 500)
        self.assertLess(tooltip.index('mismatch detail'), tooltip.index('drive detail'))
        self.assertIn('固件参数未能查证', tooltip)

    def test_bad_tooltip_numeric_raises_after_caption_but_before_hotspot(self):
        for key in ('role_max_yaw_rps', 'frames_sent'):
            with self.subTest(field=key):
                result = self.compare(stats(**{key:'not-a-number'}))
                self.assertEqual(result[4][0], 'ValueError')
                self.assertTrue(any('INF#3' in text for _,text in result[0]))
                self.assertFalse(any(h[2]=='diagnostics' for h in result[2]))

    def test_bad_caption_numeric_raises_before_caption(self):
        for key in ('role_id', 'role_max_linear_mps', 'segments_received'):
            with self.subTest(field=key):
                result = self.compare(stats(**{key:'not-a-number'}))
                self.assertEqual(result[4][0], 'ValueError')
                self.assertFalse(any('INF#' in text for _,text in result[0]))
                self.assertFalse(any(h[2]=='diagnostics' for h in result[2]))


if __name__ == '__main__':
    unittest.main()
