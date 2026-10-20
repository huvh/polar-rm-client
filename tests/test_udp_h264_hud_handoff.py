"""Valid local H.264 reaches the actual normal HUD, without devices or sockets.

Both existing UDP source labels share the same backend. This is an offscreen
client handoff contract, not old-receiver compatibility or native GPU evidence.
"""
from pathlib import Path
import struct
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import test_normal_video_timeline_contract as window_fixture
from rm_client.backend.video_backend import resolve_ffmpeg_executable
from rm_client.transports import FrameAssembler


class UdpH264HudHandoffTests(unittest.TestCase):
    def setUp(self):
        if not resolve_ffmpeg_executable():
            self.skipTest('FFmpeg unavailable: real H.264 HUD handoff not executed')
        self.fixture = window_fixture.NormalVideoTimelineContractTests()
        self.addCleanup(self.close_fixture)
        self.fixture.setUp()
        self.window = self.fixture.window

    def close_fixture(self):
        self.assertTrue(self.fixture.doCleanups(), 'actual-window cleanup failed')

    def test_both_udp_labels_deliver_to_hud_while_hero_and_stop_keep_ownership(self):
        window = self.window
        stream = (ROOT / 'assets/selftest/h264_one_gop.h264').read_bytes()
        # FrameAssembler exercises the documented Shark envelope. No UDP
        # receiver starts: the fixture also audits and rejects network access.
        assembled = FrameAssembler().push_packet(struct.pack('>HHI', 1, 0, len(stream)) + stream)
        self.assertEqual(assembled, stream)
        for mode in ('Shark UDP', 'UDP HEVC'):
            with self.subTest(source=mode):
                self.fixture.source.value = mode
                window.backend.set_active_video_source(mode, start=False)
                self.assertTrue(window.backend.udp.decode_h265)
                window.backend.udp._on_assembled_frame(assembled)
                deadline = time.perf_counter() + 4.
                bgr, frame_at, source = None, 0., ''
                while time.perf_counter() < deadline:
                    bgr, frame_at, source = window.backend.latest_video_frame(.65, mode)
                    if bgr is not None:
                        break
                    time.sleep(.01)
                self.assertIsNotNone(bgr, window.backend.udp.h265_decoder.last_error)
                self.assertEqual(source, 'udp')
                self.assertEqual(bgr.shape, (120, 160, 3))
                self.assertGreater(frame_at, 0.)
                window.consume_capture_frame()
                self.assertIsNotNone(window.frame_image)
                self.assertFalse(window.frame_image.isNull())
                self.assertIsNotNone(window.frame_pixmap)
                self.assertFalse(window.frame_pixmap.isNull())
                self.assertEqual((window.frame_image.width(), window.frame_image.height()), (160, 120))
                self.assertEqual(window._normal_frame_source, 'backend')
                self.assertTrue(window.normal_video_frame_ready())
        window.state.deploy_mode = 1
        with patch.object(window.backend.udp, 'latest_video_frame',
                          side_effect=AssertionError('deployed Hero must not query UDP')):
            window.consume_capture_frame()
        window.state.deploy_mode = 0
        window.backend.udp.request_stop()
        self.assertTrue(window.backend.udp.wait_closed())
        window.consume_capture_frame()
        self.assertIsNone(window.frame_image)
        self.assertIsNone(window.frame_pixmap)
        self.assertFalse(window.normal_video_frame_ready())
        self.assertEqual(window_fixture._NETWORK_ATTEMPTS, [])


if __name__ == '__main__':
    unittest.main()
