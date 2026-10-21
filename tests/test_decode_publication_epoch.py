"""A decoder read that overlaps revocation must not revive a retired image."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.video_backend import ContinuousMjpegDecoder, RmVideoBackend


class DecodePublicationEpochTests(unittest.TestCase):
    def check_revoked_read(self, reader, revoke):
        backend = RmVideoBackend()
        self.addCleanup(backend.stop)
        backend.codec = 'h265'
        decoder = backend.h265_decoder
        decoder.available = True
        stamp, image = time.perf_counter(), object()
        called = False

        def sample(*args):
            nonlocal called
            if not called:
                called = True
                revoke(backend)
                return (image, stamp) if reader == 'frame' else stamp
            return (None, 0.0) if reader == 'frame' else 0.0

        method = 'latest_with_timestamp' if reader == 'frame' else 'latest_timestamp'
        with patch.object(decoder, method, side_effect=sample):
            if reader == 'frame':
                self.assertEqual(backend.latest_video_frame(), (None, 0.0))
            elif reader == 'fresh':
                self.assertFalse(backend.decoded_frame_fresh())
            else:
                stats = backend.stats()
                self.assertFalse(stats['decoded_connected'])
                self.assertEqual(stats['decoded_frame_at'], 0.0)
                self.assertEqual((stats['output_width'], stats['output_height']), (0, 0))

    def test_frame_age_is_rechecked_at_final_publication(self):
        backend = RmVideoBackend()
        self.addCleanup(backend.stop)
        backend.codec = 'h265'
        backend.h265_decoder.available = True
        # Model a successful native read delayed before backend publication.
        for age in (1.0, -1.0):
            with self.subTest(age=age), patch.object(
                    backend.h265_decoder, 'latest_with_timestamp',
                    return_value=(object(), time.perf_counter() - age)):
                self.assertEqual(backend.latest_video_frame(.5), (None, 0.0))

    def test_stop_revokes_all_pending_observations(self):
        for reader in ('frame', 'fresh', 'stats'):
            with self.subTest(reader=reader):
                self.check_revoked_read(reader, lambda b: b.request_stop())

    def test_decode_disable_revokes_all_pending_observations(self):
        for reader in ('frame', 'fresh', 'stats'):
            with self.subTest(reader=reader):
                self.check_revoked_read(reader, lambda b: b.request_decode_enabled(False))

    def test_decoder_replacement_revokes_all_pending_observations(self):
        def replace(backend):
            backend.h265_decoder = ContinuousMjpegDecoder('h265')
            backend.h265_decoder.available = True
        for reader in ('frame', 'fresh', 'stats'):
            with self.subTest(reader=reader):
                self.check_revoked_read(reader, replace)

    def test_decoder_restart_generation_revokes_all_pending_observations(self):
        def restart(backend):
            # A recovery restart can retain the decoder object while replacing
            # its native process. Model its actual generation fence, no process.
            with backend.h265_decoder._lock:
                backend.h265_decoder._generation += 1
        for reader in ('frame', 'fresh', 'stats'):
            with self.subTest(reader=reader):
                self.check_revoked_read(reader, restart)


if __name__ == '__main__':
    unittest.main()
