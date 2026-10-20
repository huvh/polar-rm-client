"""Issue 20: Shark-framed H.264 routing and real bundled-sample decode.

Synthetic NAL markers below test routing only. The integration test uses the
repository's valid GOP and installed FFmpeg, never a device or network socket.
"""
from pathlib import Path
import struct
import threading
import sys
import time
import unittest
from unittest.mock import PropertyMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.video_backend import (
    ContinuousMjpegDecoder, RmVideoBackend, detect_frame_codec, iter_annexb_nal_units, resolve_ffmpeg_executable,
)
from rm_client.transports import FrameAssembler

H264 = b'\0\0\0\1\x67sps\0\0\1\x68pps\0\0\0\1\x65idr'
HEVC = b'\0\0\1\x40\x01vps\0\0\1\x42\x01sps\0\0\1\x44\x01pps\0\0\1\x26\x01idr'
INTER = b'\0\0\1\x41\x01slice'  # ambiguous non-IDR H.264 or layered HEVC VPS; stream context owns it


class UdpH264DispatchTests(unittest.TestCase):
    def setUp(self):
        self.backend = RmVideoBackend()
        self.addCleanup(self.backend.stop)

    def test_shark_frame_routes_to_h264_and_continues_interframes(self):
        frame = FrameAssembler().push_packet(struct.pack('>HHI', 1, 0, len(H264)) + H264)
        def start(decoder, **kwargs):
            decoder.available = True
            return True
        with patch.object(ContinuousMjpegDecoder, 'start', start), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True) as write:
            self.backend._on_assembled_frame(frame)
            self.assertEqual(self.backend.codec, 'h264')
            self.assertEqual(self.backend.h265_decoder.codec, 'h264')
            self.assertEqual(self.backend.decoder_backend, 'ffmpeg-mjpeg')
            self.assertEqual(write.call_count, 1)
            self.assertEqual(detect_frame_codec(INTER), 'h265')
            self.backend._on_assembled_frame(INTER)
            self.assertEqual(write.call_args.args, (INTER,))
            self.assertEqual(write.call_count, 2)
            self.backend._assembler.sequence_discontinuities += 1
            self.backend._on_assembled_frame(INTER)
            self.assertEqual(write.call_count, 2)
            self.backend._on_assembled_frame(H264)
            self.assertEqual(write.call_count, 3)

    def test_codec_switch_retains_old_owner_until_close_finishes(self):
        old = self.backend.h265_decoder
        old._latest, old._latest_at = object(), time.perf_counter()
        self.backend.codec = 'h265'
        # Retained close ownership prevents replacement even with no frame.
        with patch.object(type(old), 'cleanup_complete', new_callable=PropertyMock, return_value=False), \
             patch.object(ContinuousMjpegDecoder, 'start') as start:
            self.backend._on_assembled_frame(H264)
            self.assertIs(self.backend.h265_decoder, old)
            self.assertEqual(self.backend.latest_video_frame(), (None, 0.))
            self.assertFalse(self.backend.decoded_frame_fresh())
            start.assert_not_called()
        with patch.object(ContinuousMjpegDecoder, 'start', return_value=False):
            self.backend._on_assembled_frame(H264)
        self.assertIsNot(self.backend.h265_decoder, old)
        self.assertEqual(self.backend.h265_recovery.codec, 'h264')
        self.assertTrue(self.backend.h265_recovery.blocked)

    def test_missing_ffmpeg_is_visible_without_fresh_frame(self):
        with patch('rm_client.backend.video_backend.resolve_ffmpeg_executable', return_value=None):
            self.backend._on_assembled_frame(H264)
        self.assertEqual(self.backend.codec, 'h264')
        self.assertEqual(self.backend.decoder_backend, 'none')
        self.assertFalse(self.backend.decoded_frame_fresh())
        self.assertIn('ffmpeg', self.backend.stats()['decoder_error'])
        self.assertEqual(self.backend.latest_video_frame(), (None, 0.))

    def test_failed_write_requires_parameters_and_keyframe_again(self):
        def start(decoder, **kwargs):
            decoder.available = True
            return True
        with patch.object(ContinuousMjpegDecoder, 'start', start), \
             patch.object(ContinuousMjpegDecoder, 'write', side_effect=[False, True]) as write:
            self.backend._on_assembled_frame(H264)
            self.assertTrue(self.backend.h265_recovery.blocked)
            self.assertEqual(self.backend.dropped_frames, 1)
            self.backend._on_assembled_frame(INTER)
            self.assertEqual(write.call_count, 1)
            self.backend._on_assembled_frame(b'\0\0\1\x67sps')
            self.backend._on_assembled_frame(b'\0\0\1\x68pps')
            self.assertEqual(write.call_count, 1)
            self.backend._on_assembled_frame(b'\0\0\1\x65idr')
            self.assertEqual(write.call_count, 2)
            self.assertFalse(self.backend.h265_recovery.blocked)

    def test_unknown_continuation_and_hevc_switch_select_correct_gate(self):
        def start(decoder, **kwargs):
            decoder.available = True
            return True
        with patch.object(ContinuousMjpegDecoder, 'start', start), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True) as write:
            self.backend._on_assembled_frame(H264)
            continuation = b'continuation bytes'
            self.backend._on_assembled_frame(continuation)
            self.assertEqual(write.call_args.args, (continuation,))
            self.assertEqual(self.backend.codec, 'h264')
            old = self.backend.h265_decoder
            self.backend._on_assembled_frame(HEVC)
            self.assertEqual(self.backend.codec, 'h265')
            self.assertEqual(self.backend.h265_decoder.codec, 'h265')
            self.assertIsNot(self.backend.h265_decoder, old)
            self.assertEqual(self.backend.h265_recovery.codec, 'h265')
            self.assertFalse(self.backend.h265_recovery.blocked)
            self.assertEqual(write.call_args.args, (HEVC,))

    def test_codec_admission_failure_retains_owner_and_can_retry(self):
        old = self.backend.h265_decoder
        with patch('rm_client.backend.video_backend.ContinuousMjpegDecoder', side_effect=OSError('constructor rejected')):
            self.backend._on_assembled_frame(H264)
        self.assertIs(self.backend.h265_decoder, old)
        self.assertIn('constructor rejected', self.backend.last_error)
        self.assertEqual(self.backend.latest_video_frame(), (None, 0.))
        with patch.object(ContinuousMjpegDecoder, 'start', return_value=False):
            self.backend._on_assembled_frame(H264)
        self.assertEqual(self.backend.h265_decoder.codec, 'h264')

    def test_codec_retirement_admission_failure_keeps_owner_retryable(self):
        old = self.backend.h265_decoder
        self.backend.codec = 'h265'
        old.available = True
        old._latest, old._latest_at = object(), time.perf_counter()
        with patch.object(old, 'request_stop', side_effect=RuntimeError('close rejected')), \
             patch.object(ContinuousMjpegDecoder, 'start') as start:
            self.backend._on_assembled_frame(H264)
        start.assert_not_called()
        self.assertIs(self.backend.h265_decoder, old)
        self.assertIn('close rejected', self.backend.last_error)
        self.assertEqual(self.backend.latest_video_frame(), (None, 0.))
        self.assertFalse(self.backend.decoded_frame_fresh())
        self.assertFalse(self.backend.stats()['decoded_connected'])
        with patch.object(ContinuousMjpegDecoder, 'start', return_value=False):
            self.backend._on_assembled_frame(H264)
        self.assertEqual(self.backend.h265_decoder.codec, 'h264')

    def test_admitted_recovery_cannot_replace_newer_codec(self):
        old = self.backend.h265_decoder
        self.backend.running = True  # no receiver/socket; only enable recovery admission
        self.backend.codec = 'h265'
        entered, release = threading.Event(), threading.Event()
        def restart(**kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return True
        with patch.object(old, 'restart', side_effect=restart):
            self.backend._request_h265_restart()
            try:
                self.assertTrue(entered.wait(1))
                self.backend._on_assembled_frame(H264)
                self.assertIs(self.backend.h265_decoder, old)
                self.assertEqual(self.backend.codec, 'h264')
            finally:
                release.set()
                self.backend._h265_restart_thread.join(2)
        self.assertEqual(self.backend.h265_decoder_restarts, 0)
        with patch.object(ContinuousMjpegDecoder, 'start', return_value=False):
            self.backend._on_assembled_frame(H264)
        self.assertEqual(self.backend.h265_decoder.codec, 'h264')
        self.assertTrue(self.backend.h265_recovery.blocked)

    def test_delayed_mjpeg_decode_cannot_publish_into_new_h264_selection(self):
        from types import SimpleNamespace
        image = SimpleNamespace(shape=(24, 32, 3))
        def decode(payload):
            self.backend._on_assembled_frame(H264)
            return image
        with patch('rm_client.backend.video_backend._decode_jpeg_bgr', side_effect=decode), \
             patch.object(ContinuousMjpegDecoder, 'start', return_value=False):
            self.backend._on_assembled_frame(b'\xff\xd8synthetic routing only')
        self.assertEqual(self.backend.codec, 'h264')
        self.assertIsNone(self.backend.latest_bgr)
        self.assertEqual(self.backend.mjpeg_decoded_frames, 0)

    def test_newer_mjpeg_selection_during_start_cannot_queue_old_h264(self):
        import cv2
        import numpy as np
        encoded, jpeg = cv2.imencode('.jpg', np.zeros((24, 32, 3), dtype=np.uint8))
        self.assertTrue(encoded)
        def start(decoder, **kwargs):
            decoder.available = True
            # An established Annex-B stream switches only after a complete,
            # decodable JPEG; a synthetic SOI can be valid slice payload.
            self.backend._on_assembled_frame(jpeg.tobytes())
            return True
        with patch.object(ContinuousMjpegDecoder, 'start', start), \
             patch.object(ContinuousMjpegDecoder, 'write') as write, \
             patch.object(self.backend, '_decode_mjpeg'):
            self.backend._on_assembled_frame(H264)
        write.assert_not_called()
        self.assertEqual(self.backend.codec, 'mjpeg')

    def test_real_codec_switch_waits_for_close_then_requires_new_recovery(self):
        if not resolve_ffmpeg_executable():
            self.skipTest('FFmpeg unavailable: codec-switch integration not executed')
        root = Path(__file__).resolve().parents[1] / 'assets/selftest'
        self.backend._on_assembled_frame((root / 'h264_one_gop.h264').read_bytes())
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and not self.backend.decoded_frame_fresh(4):
            time.sleep(.01)
        self.assertTrue(self.backend.decoded_frame_fresh(4))
        old = self.backend.h265_decoder
        hevc = (root / 'hevc_one_gop.hevc').read_bytes()
        self.backend._on_assembled_frame(hevc)
        # The first HEVC GOP may be dropped while H.264's native pipes retire.
        # Observe the old owner, then feed an interframe with no parameters.
        self.assertTrue(old.wait_closed())
        self.backend._on_assembled_frame(b'\0\0\1\x02\x01slice')
        self.assertEqual(self.backend.latest_video_frame(4), (None, 0.))
        self.assertTrue(self.backend.h265_recovery.blocked)
        self.backend._on_assembled_frame(hevc)
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and not self.backend.decoded_frame_fresh(4):
            time.sleep(.01)
        self.assertEqual(self.backend.h265_decoder.codec, 'h265')
        self.assertTrue(self.backend.decoded_frame_fresh(4), self.backend.h265_decoder.last_error)
        frame, _ = self.backend.latest_video_frame(4)
        self.assertEqual(frame.shape, (120, 160, 3))
        import cv2
        import numpy as np
        ok, jpeg = cv2.imencode('.jpg', np.zeros((24, 32, 3), dtype=np.uint8))
        self.assertTrue(ok)
        self.backend._on_assembled_frame(jpeg.tobytes())
        self.assertEqual(self.backend.codec, 'mjpeg')
        self.assertEqual(self.backend.latest_video_frame(4)[0].shape, (24, 32, 3))
        self.assertTrue(self.backend.h265_decoder.wait_closed())
        self.assertFalse(self.backend.h265_decoder.available)
        self.backend._on_assembled_frame((root / 'h264_one_gop.h264').read_bytes())
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and not self.backend.decoded_frame_fresh(4):
            time.sleep(.01)
        self.assertEqual(self.backend.codec, 'h264')
        self.assertIsNone(self.backend.latest_bgr)
        self.assertEqual(self.backend.latest_video_frame(4)[0].shape, (120, 160, 3))

    def test_valid_bundled_h264_decodes_and_stop_retires_frame(self):
        if not resolve_ffmpeg_executable():
            self.skipTest('FFmpeg unavailable: valid H.264 integration not executed')
        stream = (Path(__file__).resolve().parents[1] / 'assets/selftest/h264_one_gop.h264').read_bytes()
        units = [b'\0\0\0\1' + payload for _, payload in iter_annexb_nal_units(stream)]
        self.assertTrue(any((unit[4] & 31) == 1 for unit in units), 'sample must include non-IDR slices')
        for unit in units:
            self.backend._on_assembled_frame(unit)
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and self.backend.latest_video_frame(4)[0] is None:
            time.sleep(.01)
        frame, at = self.backend.latest_video_frame(4)
        self.assertIsNotNone(frame, self.backend.h265_decoder.last_error)
        self.assertEqual(frame.shape, (120, 160, 3))
        self.assertGreater(at, 0)
        self.assertGreater(self.backend.h265_decoder.frames_decoded, 0)
        self.assertTrue(self.backend.decoded_frame_fresh(4))
        previous_count = self.backend.h265_decoder.frames_decoded
        for unit in units:
            self.backend._on_assembled_frame(unit)
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and self.backend.h265_decoder.frames_decoded <= previous_count:
            time.sleep(.01)
        self.assertGreater(self.backend.h265_decoder.frames_decoded, previous_count)
        self.assertGreater(self.backend.latest_video_frame(4)[1], at)
        self.backend.request_stop()
        self.assertEqual(self.backend.latest_video_frame(4), (None, 0.))
        self.assertTrue(self.backend.wait_closed())


if __name__ == '__main__':
    unittest.main()
