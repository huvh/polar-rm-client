"""Input fixtures keep real feedback routing without native playback voices."""
import unittest
from unittest.mock import patch

import test_window_economy_commands as fixtures
from PySide6.QtCore import QObject
from rm_client import ui_audio


class InputFixtureAudioIsolationTests(unittest.TestCase):
    def test_window_and_transition_never_construct_native_playback(self):
        # Fake constructors make the baseline safe too: an attempted native
        # voice is recorded, never allowed to reach a device or source loader.
        with patch.object(ui_audio, "QSoundEffect") as effect, \
                patch.object(ui_audio, "QMediaPlayer") as player, \
                patch.object(ui_audio, "QAudioOutput") as output:
            fixture = fixtures.WindowEconomyCommands()
            try:
                fixture.setUp()
                window = fixture.window
                self.assertIsInstance(window.ui_audio.pool, QObject)
                window.economy_visible = False
                window.open_hero_deploy_interface()
                effect.assert_not_called()
                player.assert_not_called()
                output.assert_not_called()
                self.assertTrue(fixture.audio_preloads)
                self.assertIn("polar_ui/panel_transition.wav",
                              [name for name, _volume in fixture.audio_plays])
                self.assertFalse(window.ui_audio.pool._effects)
                self.assertFalse(window.ui_audio.pool._media_effects)
                self.assertFalse(window.ui_audio.pool._fallback)
            finally:
                self.assertTrue(fixture.doCleanups())

    def test_compressed_preload_and_play_are_recorded_without_native_voices(self):
        with patch.object(ui_audio, "QSoundEffect") as effect, \
                patch.object(ui_audio, "QMediaPlayer") as player, \
                patch.object(ui_audio, "QAudioOutput") as output:
            fixture = fixtures.WindowEconomyCommands()
            try:
                fixture.setUp()
                pool = fixture.window.ui_audio.pool
                pool.preload_media(iter(("jello/activate.mp3",)), voices_per_sound=3)
                self.assertTrue(pool.play("jello/activate.mp3", 37))
                effect.assert_not_called()
                player.assert_not_called()
                output.assert_not_called()
                self.assertEqual(fixture.audio_media_preloads[-1],
                                 (("jello/activate.mp3",), 3))
                self.assertEqual(fixture.audio_plays[-1], ("jello/activate.mp3", 37))
            finally:
                self.assertTrue(fixture.doCleanups())


if __name__ == "__main__":
    unittest.main(verbosity=2)
