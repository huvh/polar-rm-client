"""Codec switches need complete-image evidence, not an Annex-B payload coincidence.

The real bundled H.264 fixture contains JPEG SOI byte pairs inside a slice.
These tests use inert decoder adapters except the explicit FFmpeg integration;
none opens a socket, device, or user service.
"""
from pathlib import Path
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from rm_client.backend.video_backend import (
    ContinuousMjpegDecoder, RmVideoBackend, _decode_jpeg_bgr,
    detect_frame_codec, iter_annexb_nal_units, resolve_ffmpeg_executable,
)
from rm_client.transports import FrameAssembler

ROOT = Path(__file__).resolve().parents[1]
H264 = (ROOT / 'assets/selftest/h264_one_gop.h264').read_bytes()
HEVC = (ROOT / 'assets/selftest/hevc_one_gop.hevc').read_bytes()


def admit(decoder, **kwargs):
    decoder.available = True
    return True


class UdpCodecEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.backend = RmVideoBackend()
        self.addCleanup(self.backend.stop)
        ok, jpeg = cv2.imencode('.jpg', np.arange(24 * 32 * 3, dtype=np.uint8).reshape(24, 32, 3))
        self.assertTrue(ok)
        self.jpeg = jpeg.tobytes()

    def _assert_real_continuation(self, prefix_bytes):
        # Assert fixture evidence before using specific, reproducible boundaries.
        for soi_offset in (41256, 44281):
            with self.subTest(soi_offset=soi_offset, prefix_bytes=prefix_bytes):
                self.assertEqual(H264[soi_offset:soi_offset + 2], b'\xff\xd8')
                containing = [(offset, nal) for offset, nal in iter_annexb_nal_units(H264)
                              if offset <= soi_offset][-1]
                self.assertEqual(containing[1][0] & 31, 1, 'SOI must be inside a genuine non-IDR slice')
                self.assertLess(containing[0], soi_offset - prefix_bytes)
                backend = RmVideoBackend()
                self.addCleanup(backend.stop)
                assembler = FrameAssembler()
                cut = soi_offset - prefix_bytes
                blocks = (H264[:cut], H264[cut:soi_offset + 64], H264[soi_offset + 64:])
                self.assertEqual(detect_frame_codec(blocks[1]), 'mjpeg', 'standalone heuristic stays compatible')
                with patch.object(ContinuousMjpegDecoder, 'start', admit), \
                     patch.object(ContinuousMjpegDecoder, 'write', return_value=True) as write:
                    owner = None
                    for frame_id, block in enumerate(blocks, 1):
                        assembled = assembler.push_packet(struct.pack('>HHI', frame_id, 0, len(block)) + block)
                        self.assertEqual(assembled, block)
                        backend._on_assembled_frame(assembled)
                        self.assertEqual(backend.codec, 'h264')
                        if owner is None:
                            owner = backend.h265_decoder
                        self.assertIs(backend.h265_decoder, owner)
                        self.assertTrue(owner.available)
                        self.assertFalse(backend.h265_recovery.blocked)
                    self.assertEqual(write.call_count, 3)
                    # Initial recovery intentionally omits pre-IDR SEI; once
                    # unblocked, both continuation blocks must be byte-exact.
                    self.assertEqual([call.args[0] for call in write.call_args_list][1:], list(blocks[1:]))
                    self.assertEqual(backend.mjpeg_decoded_frames, 0)
                    self.assertEqual(backend.dropped_frames, 0)

    def test_real_h264_soi_continuation_does_not_retire_decoder(self):
        self._assert_real_continuation(0)

    def test_real_h264_false_length_envelope_does_not_retire_decoder(self):
        self._assert_real_continuation(4)

    def test_initial_raw_and_prefixed_mjpeg_acquisition_is_preserved(self):
        for prefix in (b'', len(self.jpeg).to_bytes(4, 'little')):
            with self.subTest(prefixed=bool(prefix)):
                backend = RmVideoBackend()
                self.addCleanup(backend.stop)
                backend._on_assembled_frame(prefix + self.jpeg)
                self.assertEqual(backend.codec, 'mjpeg')
                self.assertEqual(backend.mjpeg_decoded_frames, 1)
                self.assertEqual(backend.latest_video_frame()[0].shape, (24, 32, 3))

    def test_complete_jpeg_switches_both_annexb_codecs_and_decodes_once(self):
        for codec, stream in (('h264', H264), ('h265', HEVC)):
            for prefix in (b'', len(self.jpeg).to_bytes(4, 'little')):
                with self.subTest(codec=codec, prefixed=bool(prefix)):
                    backend = RmVideoBackend()
                    self.addCleanup(backend.stop)
                    with patch.object(ContinuousMjpegDecoder, 'start', admit), \
                         patch.object(ContinuousMjpegDecoder, 'write', return_value=True), \
                         patch('rm_client.backend.video.udp._decode_jpeg_bgr', wraps=_decode_jpeg_bgr) as decode:
                        backend._on_assembled_frame(stream)
                        old = backend.h265_decoder
                        backend._on_assembled_frame(prefix + self.jpeg)
                        self.assertEqual(backend.codec, 'mjpeg')
                        self.assertFalse(old.available)
                        self.assertEqual(backend.mjpeg_decoded_frames, 1)
                        self.assertEqual(backend.latest_video_frame()[0].shape, (24, 32, 3))
                        decode.assert_called_once_with(self.jpeg)
                        backend._on_assembled_frame(stream)
                        self.assertEqual(backend.codec, codec)
                        self.assertIsNone(backend.latest_bgr)
                        self.assertTrue(backend.h265_decoder.available)
                        self.assertFalse(backend.h265_recovery.blocked)

    def test_invalid_complete_jpeg_candidate_preserves_original_annexb_bytes(self):
        candidate = b'\xff\xd8invalid image\xff\xd9'
        with patch.object(ContinuousMjpegDecoder, 'start', admit), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True) as write:
            self.backend._on_assembled_frame(H264)
            owner = self.backend.h265_decoder
            self.backend._on_assembled_frame(candidate)
            self.assertEqual(self.backend.codec, 'h264')
            self.assertIs(self.backend.h265_decoder, owner)
            self.assertTrue(owner.available)
            self.assertEqual(write.call_args.args, (candidate,))

    def test_truncated_candidate_cannot_switch_even_if_decoder_tolerates_it(self):
        with patch.object(ContinuousMjpegDecoder, 'start', admit), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True) as write:
            self.backend._on_assembled_frame(H264)
            with patch('rm_client.backend.video.udp._decode_jpeg_bgr', return_value=np.zeros((2, 2, 3))) as decode:
                self.backend._on_assembled_frame(self.jpeg[:-2])
            decode.assert_not_called()
            self.assertEqual(self.backend.codec, 'h264')
            self.assertEqual(write.call_args.args, (self.jpeg[:-2],))

    def _assert_late_validation_discarded(self, newer_selection):
        entered, release = threading.Event(), threading.Event()
        errors = []
        with patch.object(ContinuousMjpegDecoder, 'start', admit), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True):
            self.backend._on_assembled_frame(H264)
            def delayed_decode(payload):
                result = _decode_jpeg_bgr(payload)
                entered.set()
                if not release.wait(3):
                    raise AssertionError('JPEG validation not released')
                return result
            def receive():
                try:
                    self.backend._on_assembled_frame(self.jpeg, self.backend._video_generation)
                except BaseException as exc:
                    errors.append(exc)
            with patch('rm_client.backend.video.udp._decode_jpeg_bgr', side_effect=delayed_decode):
                worker = threading.Thread(target=receive)
                worker.start()
                try:
                    self.assertTrue(entered.wait(1))
                    if newer_selection:
                        self.backend._on_assembled_frame(HEVC)
                    else:
                        self.backend.request_stop()
                finally:
                    release.set()
                    worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(self.backend.codec, 'h265' if newer_selection else 'h264')
            self.assertIsNone(self.backend.latest_bgr)
            self.assertEqual(self.backend.mjpeg_decoded_frames, 0)

    def test_late_jpeg_validation_cannot_outlive_stop(self):
        self._assert_late_validation_discarded(False)

    def test_late_jpeg_validation_cannot_replace_newer_codec(self):
        self._assert_late_validation_discarded(True)

    def test_stale_callback_is_rejected_before_jpeg_validation(self):
        with patch.object(ContinuousMjpegDecoder, 'start', admit), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True):
            self.backend._on_assembled_frame(H264)
            generation = self.backend._video_generation
            self.backend.request_stop()
            with patch('rm_client.backend.video.udp._decode_jpeg_bgr') as decode:
                self.backend._on_assembled_frame(self.jpeg, generation)
            decode.assert_not_called()
            self.assertIsNone(self.backend.latest_bgr)

    def test_validated_image_cannot_publish_after_codec_changes_away_and_back(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        real_publish = self.backend._decode_mjpeg
        first = True
        def held_publish(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                if not release.wait(3):
                    raise AssertionError('validated JPEG publication not released')
            real_publish(*args, **kwargs)
        def receive():
            try:
                self.backend._on_assembled_frame(self.jpeg, self.backend._video_generation)
            except BaseException as exc:
                errors.append(exc)
        ok, newer_jpeg = cv2.imencode('.jpg', np.zeros((10, 12, 3), dtype=np.uint8))
        self.assertTrue(ok)
        with patch.object(ContinuousMjpegDecoder, 'start', admit), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True), \
             patch.object(self.backend, '_decode_mjpeg', side_effect=held_publish):
            self.backend._on_assembled_frame(H264)
            worker = threading.Thread(target=receive)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.backend.codec, 'mjpeg')
                self.backend._on_assembled_frame(HEVC)
                self.backend._on_assembled_frame(newer_jpeg.tobytes())
                newer_at = self.backend.latest_bgr_at
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.backend.codec, 'mjpeg')
        self.assertEqual(self.backend.latest_video_frame()[0].shape, (10, 12, 3))
        self.assertEqual(self.backend.latest_bgr_at, newer_at)
        self.assertEqual(self.backend.mjpeg_decoded_frames, 1)

    def test_real_ffmpeg_advances_across_bundled_soi_continuation(self):
        if not resolve_ffmpeg_executable():
            self.skipTest('FFmpeg unavailable: real continuation decode not executed')
        self.backend._on_assembled_frame(H264)
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and not self.backend.decoded_frame_fresh(4):
            time.sleep(.01)
        self.assertTrue(self.backend.decoded_frame_fresh(4))
        owner = self.backend.h265_decoder
        count, timestamp = owner.frames_decoded, owner.latest_timestamp()
        cuts = (0, 41256, 41320, 44277, 44345, len(H264))
        for left, right in zip(cuts, cuts[1:]):
            self.backend._on_assembled_frame(H264[left:right])
            self.assertEqual(self.backend.codec, 'h264')
            self.assertIs(self.backend.h265_decoder, owner)
        deadline = time.perf_counter() + 4
        while time.perf_counter() < deadline and owner.frames_decoded <= count:
            time.sleep(.01)
        self.assertGreater(owner.frames_decoded, count)
        self.assertGreater(owner.latest_timestamp(), timestamp)
        self.assertEqual(self.backend.latest_video_frame(4)[0].shape, (120, 160, 3))


if __name__ == '__main__':
    unittest.main()
