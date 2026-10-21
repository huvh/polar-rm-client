"""Selected-source reconnection: loopback sockets and inert Native decoder.

Not a physical receiver/robot certification. JPEG decoding is stubbed here;
the actual FFmpeg integration probe is a separate explicit tool.
"""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import socket
import struct
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager
from rm_client.backend.video_backend import AnnexBRecoveryGate, RmVideoBackend
from rm_client.backend.video_source import VideoSourceRequest, VideoStopStatus

GOP = b'\0\0\1\x67sps\0\0\1\x68pps\0\0\1\x65idr'


class VideoReconnectTests(unittest.TestCase):
    def wait(self, predicate, tick=lambda: None):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            tick()
            time.sleep(.005)
        self.assertTrue(predicate())

    def test_changed_sender_port_gets_a_new_epoch_without_splicing_old_fragments(self):
        receiver = RmVideoBackend(port=0)
        self.addCleanup(receiver.stop)
        first, second = socket.socket(socket.AF_INET, socket.SOCK_DGRAM), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for sender in (first, second):
            sender.bind(('127.0.0.1', 0))
            self.addCleanup(sender.close)
        image = NS(shape=(2, 2, 3))
        with patch('rm_client.backend.video_backend._decode_jpeg_bgr', return_value=image):
            receiver.start()
            self.wait(lambda: receiver.ingress_stats()['listening'])
            address = receiver.ingress_stats()['bound_address']
            jpeg = b'\xff\xd8image\xff\xd9'
            first.sendto(struct.pack('>HHI', 500, 0, len(jpeg)) + jpeg, address)
            self.wait(lambda: receiver.latest_video_frame()[0] is image)
            first.sendto(struct.pack('>HHI', 501, 0, 4) + b'AA', address)
            self.wait(lambda: receiver._assembler.buffered_bytes == 2)
            second.sendto(struct.pack('>HHI', 501, 1, 4) + b'BB', address)
            self.wait(lambda: receiver.ingress_stats()['foreign_packets'] == 1)
            old_callback = receiver.on_frame
            # Advance the idle boundary without a multi-second test sleep.
            receiver.CONNECTION_STALE_S = 0.01
            receiver._connection_backoff_s = 0.01
            time.sleep(.02)
            receiver.poll_connection()
            self.assertIsNone(receiver.latest_video_frame()[0])
            self.wait(lambda: receiver.connection_restarts == 1 and receiver.ingress_stats()['listening'], receiver.poll_connection)
            self.assertEqual(receiver._assembler.buffered_bytes, 0)
            self.assertIsNone(receiver.ingress_stats()['sender_address'])
            old_callback(jpeg)
            self.assertIsNone(receiver.latest_video_frame()[0])
            address = receiver.ingress_stats()['bound_address']
            second.sendto(struct.pack('>HHI', 0, 0, len(jpeg)) + jpeg, address)
            self.wait(lambda: receiver.latest_video_frame()[0] is image)
            self.assertEqual(receiver.ingress_stats()['sender_address'], second.getsockname())

    def test_bind_failure_retries_selected_listener_after_port_is_released(self):
        occupied = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(occupied.close)
        occupied.bind(('127.0.0.1', 0))
        receiver = RmVideoBackend(port=occupied.getsockname()[1])
        self.addCleanup(receiver.stop)
        receiver._connection_backoff_s = .01
        receiver.start()
        self.wait(lambda: not receiver.running and bool(receiver.last_error))
        occupied.close()
        self.wait(lambda: receiver.ingress_stats()['listening'], receiver.poll_connection)
        self.assertEqual(receiver.connection_restarts, 1)

    def test_retained_cleanup_failure_never_spawns_replacement(self):
        receiver = RmVideoBackend(port=0)
        receiver._connection_recovering = True
        with patch.object(RmVideoBackend, 'stop_status', new=property(
                lambda _: VideoStopStatus(True, False, ('close unconfirmed',)))), patch.object(receiver, 'start') as start:
            for _ in range(10):
                receiver.poll_connection()
        start.assert_not_called()

    def test_manager_only_maintains_selected_started_udp_not_native_hero_or_preview(self):
        manager = BackendManager.__new__(BackendManager)
        manager._poll_native_decoder_restart = Mock()
        manager._video_source_failures = ()
        manager.udp = NS(poll_connection=Mock(), decode_h265=False)
        manager._native_restart_thread = None
        manager._native_video_selected = Mock(return_value=False)
        manager.state = None
        for source, start, expected in [('udp hevc', True, True), ('legacy vt02 udp', True, True),
                ('legacy official bridge', True, True), ('udp hevc', False, False),
                ('native 0x0310', True, False), ('synthetic', True, False)]:
            manager._active_video_source = source
            manager._video_source_request = VideoSourceRequest(source, start)
            manager.udp.poll_connection.reset_mock()
            manager._recover_video_decoders()
            self.assertEqual(manager.udp.poll_connection.called, expected, (source, start))

    def native(self):
        manager = BackendManager.__new__(BackendManager)
        manager._video_source_failures = ()
        manager._active_video_source = 'native 0x0310'
        manager._native_0310_last_sequence = 100
        manager._native_0310_last_accepted_at = 100.
        manager._native_0310_bytes_since_reset = 5
        manager._native_0310_dropped_chunks = manager._native_0310_out_of_order_chunks = 0
        manager._native_0310_recovery_dropped_chunks = 0
        manager._native_0310_decoder_restarts = 0
        manager._native_0310_decoder_started_once = True
        manager._native_failure_epoch_handled = False
        manager._native_0310_blocked_until_sps = False
        manager._native_restart_thread = None
        manager._native_recovery = AnnexBRecoveryGate('h264')
        manager._native_recovery.feed(GOP)
        manager.native_decoder = NS(available=True, write=Mock(return_value=True), input_queue_depth=lambda: 0,
                                   input_chunks_dropped=0, frames_decoded=1)
        return manager, NS(deploy_mode=1, backend_stats={})

    def test_native_counter_restart_after_idle_waits_for_new_parameters_and_keyframe(self):
        manager, state = self.native()
        with patch('rm_client.backend.manager.time.monotonic', return_value=103.):
            manager._apply_native_video_chunk(state, NS(sequence=0, sequence_modulus=65536, reset=False,
                                                        payload=b'\0\0\1\x41delta'))
        self.assertEqual(manager._native_0310_last_sequence, 0)
        self.assertTrue(manager._native_recovery.blocked)
        self.assertEqual(manager._native_0310_last_accepted_at, 103.)
        manager.native_decoder.write.assert_not_called()
        with patch('rm_client.backend.manager.time.monotonic', return_value=103.01):
            manager._apply_native_video_chunk(state, NS(sequence=1, sequence_modulus=65536, reset=False, payload=GOP))
        self.assertTrue(manager.native_decoder.write.called)
        self.assertFalse(manager._native_recovery.blocked)

    def test_native_late_packet_during_live_epoch_stays_rejected(self):
        manager, state = self.native()
        with patch('rm_client.backend.manager.time.monotonic', return_value=100.1):
            manager._apply_native_video_chunk(state, NS(sequence=0, sequence_modulus=65536, reset=False, payload=GOP))
        self.assertEqual(manager._native_0310_last_sequence, 100)
        self.assertEqual(manager._native_0310_out_of_order_chunks, 1)
        manager.native_decoder.write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
