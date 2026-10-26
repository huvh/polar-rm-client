"""旧图传直接像素输出、积压恢复和短写行为；不连接真实接收端。"""
from pathlib import Path
from queue import Queue
import importlib.util
import threading
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rm_client.backend.video_backend import (
    ContinuousMjpegDecoder, _DecoderSession, _TimedDecoderInput, resolve_ffmpeg_executable,
)


class LegacyVideoLatencyTests(unittest.TestCase):
    def session(self, decoder, pipe):
        session = _DecoderSession(SimpleNamespace(stdin=pipe, poll=lambda: None), Queue())
        decoder._session, decoder._proc = session, session.proc
        decoder._input_queue = session.input_queue
        decoder._running = decoder.available = True
        decoder.started_at = time.perf_counter() - 1
        return session

    def test_stale_input_invalidates_whole_compressed_session(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        writes = []
        session = self.session(decoder, SimpleNamespace(write=writes.append))
        session.input_queue.put(_TimedDecoderInput(b"old slice", time.perf_counter() - .1))
        session.input_queue.put(_TimedDecoderInput(b"dependent slice", time.perf_counter()))
        decoder._write_loop(session)
        self.assertEqual(writes, [])
        self.assertFalse(decoder.available)
        self.assertTrue(session.stopped.is_set())
        self.assertEqual(decoder.input_chunks_dropped, 2)
        self.assertIn("50 ms", decoder.last_error)

    def test_queue_overflow_retires_instead_of_splicing_compressed_slices(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        session = self.session(decoder, SimpleNamespace())
        session.input_queue = decoder._input_queue = Queue(maxsize=1)
        self.assertTrue(decoder.write(b"first slice"))
        self.assertFalse(decoder.write(b"missing slice"))
        self.assertFalse(decoder.write(b"dependent slice"))
        self.assertTrue(session.stopped.is_set())
        self.assertFalse(decoder.available)

    def test_short_pipe_writes_preserve_every_byte(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        received = bytearray()
        def write(data):
            received.extend(data[:2])
            return min(2, len(data))
        pipe = SimpleNamespace(write=write, flush=lambda: session.stopped.set())
        session = self.session(decoder, pipe)
        session.input_queue.put(_TimedDecoderInput(b"whole NAL bytes", time.perf_counter()))
        decoder._write_loop(session)
        self.assertEqual(received, b"whole NAL bytes")

    def test_old_generation_image_cannot_publish(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        frame = np.zeros((5, 7, 3), dtype=np.uint8)
        old = self.session(decoder, SimpleNamespace())
        self.session(decoder, SimpleNamespace())
        decoder._publish_bgr(frame, old)
        self.assertEqual(decoder.latest_with_timestamp(), (None, 0.0))
        self.assertEqual(decoder.frames_decoded, 0)

    def test_native_stop_retains_context_until_worker_returns(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        entered, release = threading.Event(), threading.Event()
        def parse(payload):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test decode was not released")
            return []
        context = SimpleNamespace(parse=parse)
        session = _DecoderSession(None, Queue(), codec_context=context)
        decoder._session, decoder._input_queue = session, session.input_queue
        decoder._running = decoder.available = True
        session.input_queue.put(b"slice")
        session.threads = [threading.Thread(target=decoder._native_decode_loop, args=(session,))]
        fake_av = SimpleNamespace(error=SimpleNamespace(InvalidDataError=ValueError))
        with patch.dict(sys.modules, {"av": fake_av}):
            session.threads[0].start()
            try:
                self.assertTrue(entered.wait(1))
                decoder.request_stop()
                self.assertTrue(decoder.stop_pending)
                self.assertFalse(decoder.cleanup_complete)
                self.assertIs(session.codec_context, context)
                self.assertFalse(decoder.start())
                decoder._publish_bgr(np.zeros((2, 2, 3), dtype=np.uint8), session)
                self.assertEqual(decoder.latest_with_timestamp(), (None, 0.0))
            finally:
                release.set()
                self.assertTrue(decoder.wait_closed())
        self.assertIsNone(session.codec_context)
        self.assertEqual(decoder.frames_decoded, 0)

    def test_native_worker_admission_failure_releases_context(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        with patch.object(decoder, "_create_native_context", return_value=object()), \
             patch.object(threading.Thread, "start", side_effect=RuntimeError("worker rejected")):
            self.assertFalse(decoder.start())
        self.assertTrue(decoder.cleanup_complete)
        self.assertIsNone(decoder._session)
        self.assertFalse(decoder.available)
        self.assertIn("worker rejected", decoder.last_error)

    @unittest.skipUnless(resolve_ffmpeg_executable(), "Local FFmpeg missing")
    def test_native_missing_falls_back_to_working_ffmpeg_decoder(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        self.addCleanup(decoder.stop)
        with patch.object(decoder, "_create_native_context", return_value=None):
            self.assertTrue(decoder.start(), decoder.last_error)
        self.assertEqual(decoder.backend_name, "ffmpeg-mjpeg")
        stream = (ROOT / "assets/selftest/h264_one_gop.h264").read_bytes()
        self.assertTrue(decoder.write(stream + stream))
        deadline = time.perf_counter() + 3
        while decoder.frames_decoded == 0 and time.perf_counter() < deadline:
            time.sleep(.005)
        self.assertEqual(decoder.frame_size(), (160, 120), decoder.last_error)
        decoder.request_stop()
        self.assertTrue(decoder.wait_closed())

    @unittest.skipUnless(importlib.util.find_spec("av"), "PyAV not provided in this test runtime")
    def test_real_h264_decodes_with_no_jpeg_transcode(self):
        decoder = ContinuousMjpegDecoder("h264", allow_h264_non_idr=True)
        self.addCleanup(decoder.stop)
        self.assertTrue(decoder.start(), decoder.last_error)
        stream = (ROOT / "assets/selftest/h264_one_gop.h264").read_bytes()
        with patch("rm_client.backend.video.decoder._decode_jpeg_bgr",
                   side_effect=AssertionError("JPEG path used")):
            for offset in range(0, len(stream), 113):
                self.assertTrue(decoder.write(stream[offset:offset + 113]))
                time.sleep(.001)
            deadline = time.perf_counter() + 3
            while decoder.frames_decoded == 0 and time.perf_counter() < deadline:
                time.sleep(.005)
        image, timestamp = decoder.latest_with_timestamp(3)
        self.assertIsNotNone(image, decoder.last_error)
        self.assertEqual(image.shape, (120, 160, 3))
        self.assertGreater(timestamp, 0)
        self.assertEqual(decoder.health()["backend"], "pyav-bgr")
        decoder.request_stop()
        self.assertTrue(decoder.wait_closed())
        self.assertEqual(decoder.latest_with_timestamp(), (None, 0.0))


if __name__ == "__main__":
    unittest.main()
