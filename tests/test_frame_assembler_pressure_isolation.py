"""Tiny Shark fragments: invalid frames cannot evict valid neighbors."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.transports import FrameAssembler


def packet(frame, index, total, payload):
    return struct.pack('>HHI', frame, index, total) + payload


class FrameAssemblerPressureIsolationTests(unittest.TestCase):
    def setUp(self):
        clock = patch('rm_client.transports.time.monotonic', return_value=100.)
        clock.start(); self.addCleanup(clock.stop)
        self.assembler = FrameAssembler()
        self.assembler.MAX_BUFFERED_BYTES = 5

    def fill(self):
        a = self.assembler
        self.assertIsNone(a.push_packet(packet(1, 0, 4, b'abc')))
        self.assertIsNone(a.push_packet(packet(2, 0, 4, b'xy')))
        self.assertEqual(a.buffered_bytes, 5)

    def test_impossible_unique_chunk_retires_only_corrupt_frame(self):
        self.fill(); a = self.assembler
        self.assertIsNone(a.push_packet(packet(1, 1, 4, b'de')))
        self.assertEqual(set(a.frames), {2})
        self.assertEqual((a.buffered_bytes, a.dropped_count, a.invalid_count), (2, 1, 1))
        self.assertEqual(a.push_packet(packet(2, 1, 4, b'zz')), b'xyzz')
        self.assertEqual(a.buffered_bytes, 0)
        self.assertEqual(a.last_completed_frame_id, 2)

    def test_valid_pressure_still_evicts_oldest_unrelated_frame(self):
        self.fill(); a = self.assembler
        self.assertEqual(a.push_packet(packet(2, 1, 4, b'zz')), b'xyzz')
        self.assertEqual((a.buffered_bytes, a.dropped_count, a.invalid_count), (0, 1, 0))
        self.assertEqual(a.frames, {})

    def test_exact_duplicate_is_free_and_out_of_order_can_complete(self):
        a = self.assembler
        self.assertIsNone(a.push_packet(packet(1, 1, 4, b'cd')))
        self.assertIsNone(a.push_packet(packet(2, 0, 4, b'xyz')))
        self.assertIsNone(a.push_packet(packet(1, 1, 4, b'cd')))
        self.assertEqual((a.buffered_bytes, a.invalid_count, a.dropped_count), (5, 0, 0))
        self.assertEqual(a.push_packet(packet(1, 0, 4, b'ab')), b'abcd')
        self.assertEqual((a.buffered_bytes, a.invalid_count, a.dropped_count), (0, 0, 1))

    def test_conflicting_duplicate_and_total_already_isolate_neighbor(self):
        for bad in (packet(1, 0, 4, b'zzz'), packet(1, 1, 5, b'd')):
            with self.subTest(packet=bad):
                self.assembler.clear(); self.fill(); a = self.assembler
                self.assertIsNone(a.push_packet(bad))
                self.assertEqual(set(a.frames), {2})
                self.assertEqual((a.buffered_bytes, a.invalid_count, a.dropped_count), (2, 1, 1))
                self.assertEqual(a.push_packet(packet(2, 1, 4, b'zz')), b'xyzz')

    def test_invalid_packet_boundaries_do_not_consume_buffer(self):
        self.fill(); a = self.assembler
        bad_packets = (b'', b'1234567', packet(3, 0, 0, b'x'), packet(3, 0, 1, b''),
                       packet(3, 0, 1, b'xx'), packet(3, 0, a.MAX_FRAME_BYTES + 1, b'x'),
                       packet(3, a.MAX_CHUNKS_PER_FRAME, 1, b'x'))
        for bad in bad_packets:
            with self.subTest(packet=bad):
                self.assertIsNone(a.push_packet(bad))
                self.assertEqual(set(a.frames), {1, 2})
                self.assertEqual((a.buffered_bytes, a.dropped_count), (5, 0))
        self.assertEqual(a.invalid_count, len(bad_packets))


if __name__ == '__main__': unittest.main()
