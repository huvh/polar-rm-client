"""2019-evidenced raw H.264 ingress; loopback fixtures are not receiver acceptance."""
from pathlib import Path
import os
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import PropertyMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend.manager import BackendManager
from rm_client.backend.video_backend import ContinuousMjpegDecoder, RmVideoBackend, resolve_ffmpeg_executable
from rm_client.transports import AnnexBDatagramStream, FrameAssembler


H264 = b'\0\0\0\1\x67sps\0\0\1\x68pps\0\0\0\1\x65idr'


class LegacyVt02IngressTests(unittest.TestCase):
    def wait_for(self, predicate, seconds=3):
        deadline = time.perf_counter() + seconds
        while not predicate() and time.perf_counter() < deadline:
            time.sleep(.005)
        self.assertTrue(predicate())

    def backend(self, mode="legacy-vt02-h264"):
        backend = RmVideoBackend()
        self.addCleanup(backend.stop)
        backend.configure_ingress(mode)
        return backend

    def test_raw_input_keeps_every_byte_and_never_invents_frames(self):
        parser = AnnexBDatagramStream()
        for chunk in (b'\0', b'\0\0', b'\1\x67', b'SPS', b'\0\0\1\x68PPS'):
            self.assertEqual(parser.push_packet(chunk), chunk)
        self.assertEqual(parser.frames, {})
        self.assertEqual(parser.buffered_bytes, 0)
        self.assertEqual(parser.sequence_discontinuities, 0)
        self.assertIsNone(parser.push_packet(b''))
        self.assertEqual(parser.invalid_count, 1)

    def test_modes_have_distinct_assemblers_and_endpoints(self):
        backend = self.backend()
        self.assertEqual(backend._bind_address(), ('0.0.0.0', 8080))
        self.assertIsInstance(backend._create_assembler(), AnnexBDatagramStream)
        backend.configure_ingress('shark-framed')
        self.assertEqual(backend._bind_address(), ('127.0.0.1', 3334))
        self.assertIs(type(backend._create_assembler()), FrameAssembler)
        with self.assertRaises(ValueError):
            backend.configure_ingress('auto-detect-raw-usb')

    def test_split_start_codes_and_parameter_sets_reach_h264_recovery(self):
        backend = self.backend()
        def start(decoder, **kwargs):
            decoder.available = True
            return True
        with patch.object(ContinuousMjpegDecoder, 'start', start), \
             patch.object(ContinuousMjpegDecoder, 'write', return_value=True) as writer:
            for byte in H264:
                backend._on_assembled_frame(bytes([byte]))
            self.assertEqual(backend.codec, 'h264')
            self.assertEqual(backend.h265_decoder.codec, 'h264')
            self.assertFalse(backend.h265_recovery.blocked)
            self.assertEqual(b''.join(call.args[0] for call in writer.call_args_list), H264)

    def test_continuations_cannot_publish_before_parameters_and_idr(self):
        backend = self.backend()
        with patch.object(ContinuousMjpegDecoder, 'start', return_value=True), \
             patch.object(ContinuousMjpegDecoder, 'write') as writer:
            for value in (b'arbitrary continuation', b'\0\0\1\x41slice', b'\0\0\1\x65idr'):
                backend._on_assembled_frame(value)
            self.assertTrue(backend.h265_recovery.blocked)
            writer.assert_not_called()
            self.assertFalse(backend.decoded_frame_fresh())

    def test_live_socket_decodes_raw_h264_without_shark_envelope(self):
        self.check_live_socket('legacy-vt02-h264')

    def test_bridge_loopback_input_decodes_raw_h264(self):
        self.check_live_socket('legacy-official-bridge')

    def check_live_socket(self, mode):
        if not resolve_ffmpeg_executable():
            self.skipTest('FFmpeg missing; real raw H.264 decoding not executed')
        backend = self.backend(mode)
        with patch.object(backend, '_bind_address', return_value=('127.0.0.1', 0)):
            backend.start()
        self.wait_for(lambda: backend.ingress_stats()['listening'])
        endpoint = backend.ingress_stats()['bound_address']
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        stream = (ROOT / 'assets/selftest/h264_one_gop.h264').read_bytes()
        for _ in range(2):
            for offset in range(0, len(stream), 1316):
                sender.sendto(stream[offset:offset + 1316], endpoint)
                time.sleep(.001)
        self.wait_for(backend.decoded_frame_fresh, 5)
        image, timestamp = backend.latest_video_frame()
        self.assertIsNotNone(image)
        self.assertEqual(image.shape, (120, 160, 3))
        self.assertGreater(timestamp, 0)
        stats = backend.stats()
        self.assertEqual(stats['codec'], 'h264')
        self.assertEqual((stats['output_width'], stats['output_height']), (160, 120))
        self.assertEqual(stats['frames_received'], 0)
        self.assertGreater(stats['ingress']['stream_blocks_received'], 0)
        self.assertFalse(stats['hardware_verified'])
        with self.assertRaises(RuntimeError):
            backend.configure_ingress('shark-framed')
        backend.request_stop()
        self.assertTrue(backend.wait_closed())
        self.assertEqual(backend.latest_video_frame(), (None, 0.0))
        self.assertEqual((backend.stats()['output_width'], backend.stats()['output_height']), (0, 0))

    def manager(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch.dict(os.environ, {'POLAR_USER_DATA_ROOT': directory.name}), \
             patch.object(BackendManager, '_build_commit', return_value='TEST'):
            manager = BackendManager(workspace=directory.name)
        self.addCleanup(manager.shutdown)
        self.assertTrue(manager.udp.wait_closed())
        self.assertTrue(manager.native_decoder.wait_closed())
        return manager

    def test_manager_selects_raw_explicitly_without_modern_qualification(self):
        manager = self.manager()
        manager.set_active_video_source('Legacy VT02 UDP', start=False)
        self.assertEqual(manager._active_video_source, 'legacy vt02 udp')
        self.assertEqual(manager.udp.ingress_mode, 'legacy-vt02-h264')
        self.assertEqual(manager._canonical_readiness_video_source(), 'legacy_vt02_udp')
        manager.udp.latest_bgr = object()
        manager.udp.latest_bgr_at = time.perf_counter()
        frame, _, source = manager.latest_video_frame(source_mode='Legacy VT02 UDP')
        self.assertIsNotNone(frame)
        self.assertEqual(source, 'legacy-vt02-udp')
        self.assertEqual(manager.latest_video_frame(source_mode='UDP HEVC'), (None, 0., 'none'))
        manager.set_active_video_source('UDP HEVC', start=False)
        self.wait_for(lambda: manager.udp.cleanup_complete)
        manager.set_active_video_source('UDP HEVC', start=False)
        self.assertEqual(manager.udp.ingress_mode, 'shark-framed')
        self.assertEqual(manager.udp.latest_video_frame(), (None, 0.))
        self.assertEqual(manager.latest_video_frame(source_mode='Legacy VT02 UDP'), (None, 0., 'none'))

    def test_bridge_source_is_explicit_loopback_with_distinct_identity(self):
        manager = self.manager()
        manager.set_active_video_source('Legacy VT02 UDP', start=False)
        manager.set_active_video_source('Legacy Official Bridge', start=False)
        self.wait_for(lambda: manager.udp.cleanup_complete)
        manager.set_active_video_source('Legacy Official Bridge', start=False)
        self.assertEqual(manager.udp.ingress_mode, 'legacy-official-bridge')
        self.assertEqual(manager.udp._bind_address(), ('127.0.0.1', 18080))
        self.assertEqual(manager._canonical_readiness_video_source(), 'legacy_official_bridge')
        self.assertIsInstance(manager.udp._create_assembler(), AnnexBDatagramStream)
        manager.udp.latest_bgr, manager.udp.latest_bgr_at = object(), time.perf_counter()
        self.assertEqual(manager.latest_video_frame(source_mode='Legacy Official Bridge')[2],
                         'legacy-official-bridge')
        for other in ('Legacy VT02 UDP', 'UDP HEVC'):
            self.assertIsNone(manager.latest_video_frame(source_mode=other)[0])

    def test_mode_switch_waits_for_old_owner_and_discards_late_callback(self):
        manager = self.manager()
        manager.set_active_video_source('UDP HEVC', start=False)
        old_generation = manager.udp._video_generation
        with patch.object(type(manager.udp), 'cleanup_complete', new_callable=PropertyMock, return_value=False), \
             patch.object(manager.udp, 'start') as start:
            manager.set_active_video_source('Legacy VT02 UDP')
            self.assertEqual(manager._active_video_source, '')
            self.assertEqual(manager.udp.ingress_mode, 'shark-framed')
            start.assert_not_called()
        manager.set_active_video_source('Legacy VT02 UDP', start=False)
        self.assertEqual(manager.udp.ingress_mode, 'legacy-vt02-h264')
        with patch.object(ContinuousMjpegDecoder, 'start') as start:
            manager.udp._on_assembled_frame(H264, old_generation)
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
