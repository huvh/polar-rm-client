"""Native activation agreement at real manager caller boundaries, no workers."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager


class ReachedContinuity(Exception):
    pass


class NativeVideoActivationTests(unittest.TestCase):
    def manager(self, source, state):
        manager = BackendManager.__new__(BackendManager)
        manager._active_video_source = source
        manager.state = state
        manager._video_source_failures = ()
        manager._poll_native_decoder_restart = Mock()
        manager.udp = NS(decode_h265=False)
        manager._native_restart_thread = None
        manager.native_decoder = NS(health=Mock(return_value={}))
        manager._native_0310_decoder_started_once = False
        manager._native_recovery = NS(reset=Mock())
        manager._native_0310_last_sequence = 9
        return manager

    def recovery_selected(self, manager):
        manager._recover_video_decoders()
        return manager.native_decoder.health.called

    def chunk_selected(self, manager, state):
        # Stop exactly after the existing activation gate, before any decoder,
        # queue or sequence work. A rejected stream never reaches this seam.
        with patch('rm_client.backend.manager.assess_native_video_sequence',
                   side_effect=ReachedContinuity) as assess:
            try:
                manager._apply_native_video_chunk(state, NS(sequence=1, sequence_modulus=256, reset=False))
            except ReachedContinuity:
                pass
        return assess.called

    def test_both_callers_keep_alias_deploy_and_auto_boundaries(self):
        for source in ('native', 'native 0x0310', '0x0310', 'auto', 'udp hevc', '', 'Native'):
            for mode in (0, 1, 2, '1'):
                expected = source in ('native', 'native 0x0310', '0x0310') or mode in (1, '1')
                for caller in ('recovery', 'chunk'):
                    with self.subTest(source=source, mode=mode, caller=caller):
                        state = NS(deploy_mode=mode)
                        manager = self.manager(source, state)
                        actual = (self.recovery_selected(manager) if caller == 'recovery'
                                  else self.chunk_selected(manager, state))
                        self.assertEqual(actual, expected)
                        if caller == 'chunk' and not expected:
                            self.assertIsNone(manager._native_0310_last_sequence)
                            manager._native_recovery.reset.assert_called_once_with()

    def test_chunk_uses_supplied_state_not_managers_stale_state(self):
        for current, supplied in ((0, 1), (1, 0)):
            manager = self.manager('udp hevc', NS(deploy_mode=current))
            self.assertEqual(self.recovery_selected(manager), current == 1)
            self.assertEqual(self.chunk_selected(manager, NS(deploy_mode=supplied)), supplied == 1)

    def test_absent_state_and_missing_deploy_mode_remain_unselected(self):
        for state in (None, NS()):
            manager = self.manager('auto', state)
            self.assertFalse(self.recovery_selected(manager))
            self.assertFalse(self.chunk_selected(manager, state))

    def test_native_source_short_circuits_malformed_deploy_other_sources_still_raise(self):
        for caller in ('recovery', 'chunk'):
            for value, error in (('broken', ValueError), (None, TypeError)):
                with self.subTest(caller=caller, value=value):
                    state = NS(deploy_mode=value)
                    manager = self.manager('native', state)
                    invoke = lambda: (self.recovery_selected(manager) if caller == 'recovery'
                                      else self.chunk_selected(manager, state))
                    self.assertTrue(invoke())
                    manager._active_video_source = 'auto'
                    with self.assertRaises(error):
                        invoke()

    def test_source_failure_gate_precedes_activation_and_malformed_state(self):
        manager = self.manager('auto', NS(deploy_mode='broken'))
        manager._video_source_failures = ('retained failure',)
        self.assertFalse(self.recovery_selected(manager))
        self.assertFalse(self.chunk_selected(manager, manager.state))


if __name__ == '__main__':
    unittest.main(verbosity=2)
