"""Inert decoder ownership checks before and immediately after process acquisition."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rm_client.backend.video_backend as video
from test_video_close_ownership import Process


class DecoderOwnerPrefixTests(unittest.TestCase):
    def test_queue_rejection_precedes_process_acquisition(self):
        decoder = video.ContinuousMjpegDecoder()
        real_queue = video.Queue
        calls = 0
        def queue(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('owner queue rejected')
            return real_queue(*args, **kwargs)
        with patch.object(video, 'Queue', side_effect=queue), \
                patch.object(video, 'resolve_ffmpeg_executable', return_value='inert'), \
                patch.object(video.subprocess, 'Popen', return_value=Process()) as spawn:
            self.assertFalse(decoder.start())
        spawn.assert_not_called()
        self.assertIn('owner queue rejected', decoder.last_error)
        self.assertTrue(decoder.cleanup_complete)

    def test_session_rejection_precedes_process_acquisition(self):
        decoder = video.ContinuousMjpegDecoder()
        with patch.object(video, '_DecoderSession', side_effect=RuntimeError('owner session rejected')), \
                patch.object(video, 'resolve_ffmpeg_executable', return_value='inert'), \
                patch.object(video.subprocess, 'Popen', return_value=Process()) as spawn:
            self.assertFalse(decoder.start())
        spawn.assert_not_called()
        self.assertIn('owner session rejected', decoder.last_error)
        self.assertTrue(decoder.cleanup_complete)

    def test_spawn_rejection_has_no_phantom_retired_owner(self):
        decoder = video.ContinuousMjpegDecoder()
        with patch.object(video, 'resolve_ffmpeg_executable', return_value='inert'), \
                patch.object(video.subprocess, 'Popen', side_effect=OSError('spawn rejected')):
            self.assertFalse(decoder.start())
        self.assertIn('spawn rejected', decoder.last_error)
        self.assertTrue(decoder.cleanup_complete)
        self.assertEqual(decoder._retired_sessions, [])

    def test_acquired_process_failed_close_retained_until_explicit_retry(self):
        for failure in ('pipe', 'reap'):
            with self.subTest(failure=failure):
                decoder = video.ContinuousMjpegDecoder()
                process = Process()
                process.stdout.fail_close = failure == 'pipe'
                process.fail_reap = failure == 'reap'
                with patch.object(video, 'resolve_ffmpeg_executable', return_value='inert'), \
                        patch.object(video.subprocess, 'Popen', return_value=process), \
                        patch.object(video.threading, 'Thread', side_effect=RuntimeError('worker rejected')):
                    self.assertFalse(decoder.start())
                self.assertFalse(decoder.cleanup_complete)
                self.assertIs(decoder._retired_sessions[0].proc, process)
                self.assertIn('worker rejected', decoder.last_error)
                self.assertTrue(decoder._retired_sessions[0].close_error)
                with patch.object(video.subprocess, 'Popen') as spawn:
                    self.assertFalse(decoder.start())
                spawn.assert_not_called()
                process.stdout.fail_close = process.fail_reap = False
                decoder.stop()
                self.assertTrue(decoder.wait_closed())
                self.assertTrue(decoder.cleanup_complete)
                self.assertFalse(process.alive)
                self.assertTrue(all(p.closed for p in (process.stdin, process.stdout, process.stderr)))

    def test_old_start_failure_cannot_overwrite_new_stop_admission_error(self):
        decoder = video.ContinuousMjpegDecoder()
        process = Process()
        process.stdout.fail_close = True
        close = decoder._close_retired_session
        def close_then_advance(session, **kwargs):
            result = close(session, **kwargs)
            if not result:
                with patch.object(video.threading.Thread, 'start',
                                  side_effect=RuntimeError('new epoch stop admission rejected')):
                    with self.assertRaisesRegex(RuntimeError, 'new epoch stop admission rejected'):
                        decoder.request_stop()
            return result
        with patch.object(video, 'resolve_ffmpeg_executable', return_value='inert'), \
                patch.object(video.subprocess, 'Popen', return_value=process), \
                patch.object(video.threading.Thread, 'start',
                             side_effect=RuntimeError('old startup worker rejected')), \
                patch.object(decoder, '_close_retired_session', side_effect=close_then_advance):
            self.assertFalse(decoder.start())
        self.assertEqual(decoder.lifecycle_generation, 1)
        self.assertIn('new epoch stop admission rejected', decoder.last_error)
        self.assertNotIn('old startup worker rejected', decoder.last_error)
        self.assertFalse(decoder.cleanup_complete)
        process.stdout.fail_close = False
        self.assertTrue(decoder.wait_closed())


if __name__ == '__main__':
    unittest.main()
