"""Exercise the actual activation subprocess with native audio fail-fast guards."""
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_window_activation_failure as activation_tests


class ActivationAudioIsolationTests(unittest.TestCase):
    def guarded_probe(self, fault):
        run = subprocess.run
        guard = '''
from unittest.mock import Mock
from PySide6 import QtMultimedia
forbidden_audio = []
for name in ('QMediaDevices', 'QSoundEffect', 'QMediaPlayer', 'QAudioOutput'):
    rejected = Mock(side_effect=AssertionError('unisolated native audio: ' + name))
    rejected.audioOutputs.side_effect = AssertionError('unisolated audio enumeration')
    rejected.defaultAudioOutput.side_effect = AssertionError('unisolated default audio')
    forbidden_audio.append(rejected)
    setattr(QtMultimedia, name, rejected)
'''
        restoration = """
from rm_client import ui_audio, audio_preferences, kill_audio
assert all(not item.called and not item.audioOutputs.called and
           not item.defaultAudioOutput.called for item in forbidden_audio)
for module in (ui_audio, audio_preferences, kill_audio):
    assert module.QMediaDevices is QtMultimedia.QMediaDevices
for name in ('QSoundEffect', 'QMediaPlayer', 'QAudioOutput'):
    assert getattr(ui_audio, name) is getattr(QtMultimedia, name)
sentinel = RuntimeError('isolated setup failure')
try:
    with isolated_activation_audio():
        raise sentinel
except RuntimeError as caught:
    assert caught is sentinel
for module in (ui_audio, audio_preferences, kill_audio):
    assert module.QMediaDevices is QtMultimedia.QMediaDevices
for name in ('QSoundEffect', 'QMediaPlayer', 'QAudioOutput'):
    assert getattr(ui_audio, name) is getattr(QtMultimedia, name)
assert audio_preferences.selected_output.cache_info().currsize == 0
"""
        def guarded(args, **kwargs):
            self.assertEqual(kwargs['timeout'], 30)
            self.assertTrue(kwargs['capture_output'])
            self.assertEqual(args[1], '-c')
            return run([args[0], '-c', guard + args[2] + restoration], **kwargs)
        with patch('test_window_activation_failure.subprocess.run', side_effect=guarded):
            return activation_tests.WindowActivationFailureTests().probe(fault)

    def test_timer_failure_retires_without_native_audio(self):
        self.assertEqual(self.guarded_probe('timer'), dict(timer=True, closing=True,
            retained=True, pending=True, finalized=True, pending_after_events=False, starts=0))

    def test_unavailable_rescue_retains_owner_without_native_audio(self):
        self.assertEqual(self.guarded_probe('timer_unavailable'), dict(timer=False, closing=True,
            retained=True, pending=True, finalized=False, pending_after_events=True, starts=0))


if __name__ == '__main__':
    unittest.main()
