"""Pure AST checks of smoke audio isolation; no smoke/native imports occur."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from functools import lru_cache
import io
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'rm_client').is_dir():
    ROOT = Path('/workspace/scratch/8fc313400f06/client-clean-recovered')
SMOKE_SOURCE = ROOT / 'tests/smoke_test.py'


def selected_function(path, name, namespace):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(nodes) == 1, name
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), nodes[0]], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace[name]


class SmokeAudioIsolationTests(unittest.TestCase):
    def setUp(self):
        self.native_calls = []
        self.modules = {}
        package = ModuleType('rm_client')
        package.__path__ = []
        self.modules['rm_client'] = package
        for name in ('ui_audio', 'audio_preferences', 'kill_audio'):
            module = ModuleType('rm_client.' + name)
            self.modules[module.__name__] = module
            setattr(package, name, module)
            device = self.forbidden(name + '.QMediaDevices')
            device.audioOutputs = self.forbidden(name + '.audioOutputs')
            device.defaultAudioOutput = self.forbidden(name + '.defaultAudioOutput')
            module.QMediaDevices = device
        self.ui = package.ui_audio
        self.preferences = package.audio_preferences
        for name in ('QSoundEffect', 'QMediaPlayer', 'QAudioOutput'):
            setattr(self.ui, name, self.forbidden(name))
        self.preferences.current_audio = lambda: SimpleNamespace(device_id='default')
        self.preferences.lru_cache = lru_cache
        selected_function(ROOT / 'rm_client/audio_preferences.py', 'selected_output', self.preferences.__dict__)
        self.ui.selected_output = self.preferences.selected_output
        self.ui.QUrl = SimpleNamespace(fromLocalFile=lambda value: value)
        self.ui._effect_status_listener = lambda *_: (lambda: None)
        self.preload = selected_function(ROOT / 'rm_client/ui_audio.py', 'preload', self.ui.__dict__)
        self.helper = selected_function(ROOT / 'tests/test_window_activation_failure.py', 'isolated_activation_audio', {})
        self.original_aliases = {
            (name, key): getattr(module, key)
            for name, module in self.modules.items() if name != 'rm_client'
            for key in ('QMediaDevices', 'QSoundEffect', 'QMediaPlayer', 'QAudioOutput')
            if hasattr(module, key)}
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'cue.wav'
        path.write_bytes(b'inert fixture, never decoded')
        self.pool = SimpleNamespace(_sound_path=lambda _: path, _effects={}, voices_per_sound=2)
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def forbidden(self, label):
        def rejected(*args, **kwargs):
            self.native_calls.append(label)
            raise AssertionError('Unisolated native audio: ' + label)
        return Mock(side_effect=rejected, name=label)

    def runner(self, callbacks):
        namespace = dict(__name__='inert_smoke', SMOKE_SKIPS=[], unittest=unittest,
                         isolated_activation_audio=self.helper)
        for name, callback in callbacks:
            callback.__module__ = 'inert_smoke'
            namespace[name] = callback
        function = selected_function(SMOKE_SOURCE, 'run_all_smoke_tests', namespace)
        return function, namespace

    def assert_restored(self):
        for (name, key), original in self.original_aliases.items():
            self.assertIs(getattr(self.modules[name], key), original)
        self.assertEqual(self.preferences.selected_output.cache_info().currsize, 0)

    def test_actual_preload_runs_inside_fixture_and_restores_all_aliases(self):
        def exercise():
            self.preload(self.pool, ['cue.wav', 'cue.wav'])
            self.assertEqual(len(self.pool._effects['cue.wav']), 2)
            for voice in self.pool._effects['cue.wav']:
                self.assertEqual(voice.setSource.call_count, 1)
            for name in ('ui_audio', 'audio_preferences', 'kill_audio'):
                self.modules['rm_client.' + name].QMediaDevices()
        runner, _ = self.runner([('test_render', exercise)])
        with redirect_stdout(io.StringIO()): self.assertEqual(runner(), 0)
        self.assertFalse(self.native_calls)
        self.assert_restored()

    def test_all_current_test_names_keep_definition_order_and_completion(self):
        tree = ast.parse(SMOKE_SOURCE.read_text())
        names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
        self.assertEqual(len(names), 71)
        visited = []
        callbacks = []
        for name in names:
            def exercise(name=name):
                self.pool._effects.clear()
                self.preload(self.pool, ['cue.wav'])
                visited.append(name)
            callbacks.append((name, exercise))
        runner, _ = self.runner(callbacks)
        stream = io.StringIO()
        with redirect_stdout(stream): self.assertEqual(runner(), 0)
        self.assertEqual(visited, names)
        self.assertEqual(stream.getvalue().count('[PASS] '), 71)
        self.assertIn('71/71 complete test functions; 0 skipped checks', stream.getvalue())
        self.assertFalse(self.native_calls)
        self.assert_restored()

    def test_skip_and_incomplete_status_remain_unchanged(self):
        def skipped():
            self.preload(self.pool, ['cue.wav'])
            raise unittest.SkipTest('inert skip')
        runner, namespace = self.runner([('test_skipped', skipped)])
        stream = io.StringIO()
        with redirect_stdout(stream): self.assertEqual(runner(), 77)
        self.assertEqual(namespace['SMOKE_SKIPS'], ['inert skip'])
        self.assertIn('[SKIP] test_skipped: inert skip', stream.getvalue())
        self.assertIn('[INCOMPLETE] test_skipped:', stream.getvalue())
        self.assertFalse(self.native_calls)
        self.assert_restored()

    def test_primary_exception_identity_and_test_finally_cleanup_are_preserved(self):
        for failure in (AssertionError('assertion'), RuntimeError('runtime'), KeyboardInterrupt('interrupt'), SystemExit(9)):
            with self.subTest(kind=type(failure).__name__):
                closed = []
                def exercise():
                    try:
                        self.preload(self.pool, ['cue.wav'])
                        raise failure
                    finally:
                        self.assertIsNot(self.ui.QSoundEffect, self.original_aliases[('rm_client.ui_audio', 'QSoundEffect')])
                        self.pool._effects.clear()
                        closed.append(True)
                runner, _ = self.runner([('test_failure', exercise)])
                with redirect_stdout(io.StringIO()), self.assertRaises(type(failure)) as caught:
                    runner()
                self.assertIs(caught.exception, failure)
                self.assertEqual(closed, [True])
                self.assertFalse(self.native_calls)
                self.assert_restored()

    def test_existing_helper_rejects_unexpected_playback(self):
        with self.helper():
            self.preload(self.pool, ['cue.wav'])
            with self.assertRaisesRegex(AssertionError, 'unexpected activation playback'):
                self.pool._effects['cue.wav'][0].play()
        self.assertFalse(self.native_calls)
        self.assert_restored()

    def test_unisolated_actual_preload_hits_fail_closed_constructor(self):
        with self.assertRaisesRegex(AssertionError, 'Unisolated native audio: QSoundEffect'):
            self.preload(self.pool, ['cue.wav'])
        self.assertEqual(self.native_calls, ['QSoundEffect'])
        self.assert_restored()

    def test_swallowed_native_attempt_is_still_detected_by_ledger(self):
        def exercise():
            self.preload(self.pool, ['cue.wav'])
            try:
                self.original_aliases[('rm_client.ui_audio', 'QSoundEffect')]()
            except AssertionError:
                pass
        runner, _ = self.runner([('test_swallowed', exercise)])
        with redirect_stdout(io.StringIO()): self.assertEqual(runner(), 0)
        self.assertEqual(self.native_calls, ['QSoundEffect'])
        with self.assertRaises(AssertionError): self.assertFalse(self.native_calls)
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
