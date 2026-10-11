"""Deterministic byte-stream and typed-payload regressions; never opens hardware."""
from pathlib import Path
import math
import importlib.util
import os
import subprocess
import tempfile
import random
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.protocol import RefereeFrameCodec, crc8, crc16
from rm_client.backend.polar_link import PolarFrameCodec, SEG_IMU, SEG_EVENT
from rm_client.backend.team_control import encode_km_control_payload, decode_km_control_payload


class SerialCodecTests(unittest.TestCase):
    def test_firmware_prepare_import_outside_script_directory(self):
        source = Path(__file__).resolve().parents[1] / 'tools/firmware/prepare_hero_build.py'
        code = ("import importlib.util; s=importlib.util.spec_from_file_location('prepare_probe', "
                + repr(str(source)) + "); m=importlib.util.module_from_spec(s); "
                "s.loader.exec_module(m); assert m.FileJournal and m.SnapshotError")
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-I', '-c', code], cwd=folder,
                                    env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_firmware_fixture_restores_usb_callback_dependency(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('serial_fixture_probe', root / 'tools/firmware/bridge_fixture.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            usb = repo / 'application/communication/usb_task.c'
            cdc = repo / 'Src/usbd_cdc_if.c'
            usb.parent.mkdir(parents=True); cdc.parent.mkdir(parents=True)
            usb.write_bytes(b'original task'); cdc.write_bytes(b'original callback')
            snap = fixture.stage(repo, ['application/communication/usb_task.c'])
            usb.write_bytes(b'changed task'); cdc.write_bytes(b'changed callback')
            fixture.restore(snap, repo)
            self.assertEqual(usb.read_bytes(), b'original task')
            self.assertEqual(cdc.read_bytes(), b'original callback')
            cdc.unlink()
            snap = fixture.stage(repo, ['application/communication/usb_task.c'])
            cdc.write_bytes(b'new callback')
            fixture.restore(snap, repo)
            self.assertFalse(cdc.exists())
        prepare = (root / 'tools/firmware/prepare_hero_build.py').read_text()
        self.assertIn('"Src/usbd_cdc_if.c"', prepare)

    def test_crc_published_check_vectors(self):
        self.assertEqual(crc8(b'123456789'), 0x0B)
        self.assertEqual(crc16(b'123456789'), 0x6F91)

    def test_referee_every_split_and_sequence_wrap(self):
        codec = RefereeFrameCodec()
        codec.seq = 255
        a = codec.encode(0x0201, b'\xA5\x00noise')
        b = codec.encode(0x0202, b'next')
        for split in range(len(a + b) + 1):
            buffer = bytearray()
            got = []
            for chunk in ((a + b)[:split], (a + b)[split:]):
                buffer.extend(chunk)
                frames, consumed = codec.decode_with_consumed(buffer)
                got.extend(frames)
                del buffer[:consumed]
            self.assertEqual([f.seq for f in got], [255, 0])
            self.assertEqual([bytes(f.data) for f in got], [b'\xA5\x00noise', b'next'])
            self.assertFalse(buffer)

    def test_oversized_header_does_not_block_following_frame(self):
        codec = RefereeFrameCodec()
        head = b'\xA5\xFF\xFF\x00'
        poison = head + bytes([crc8(head)])
        good = codec.encode(0x0201, b'abc')
        frames, consumed = codec.decode_with_consumed(poison + good)
        self.assertEqual(len(frames), 1)
        self.assertEqual(consumed, len(poison + good))
        for count in (301, 65536):
            with self.assertRaises(ValueError):
                codec.encode(1, b'x' * count)
        self.assertEqual(len(codec.decode(codec.encode(0x0310, b'x' * 300))), 1)

    def test_noise_is_consumed_but_header_prefix_is_preserved(self):
        for codec, sof in ((RefereeFrameCodec(), b'\xA5'), (PolarFrameCodec(), b'\x5A')):
            for n in range(1, 20):
                self.assertEqual(codec.decode_with_consumed(b'\x00' * n)[1], n)
                self.assertEqual(codec.decode_with_consumed(b'\x00' * n + sof)[1], n)

    def test_polar_poison_known_length_and_nonfinite(self):
        codec = PolarFrameCodec()
        h = bytes((0x5A, 255, SEG_IMU))
        poison = h + bytes([crc8(h)])
        good = codec._wrap(SEG_EVENT, 1, struct.pack('<I', 13))
        frames, consumed = codec.decode_with_consumed(poison + good)
        self.assertEqual(len(frames), 1)
        self.assertEqual(consumed, len(poison + good))
        for value in (math.nan, math.inf, -math.inf):
            bad = codec._wrap(SEG_IMU, 2, struct.pack('<6f', value, 0, 0, 0, 0, 0))
            self.assertFalse(codec.decode_with_consumed(bad)[0])
            with self.assertRaises(ValueError):
                codec.encode_robot_cmd(raw_timestamp=1, gimbal_pitch_rad=value, gimbal_yaw_rad=0)
        for invalid in (257, 258, -255):
            wire = codec.encode_chassis_cmd(raw_timestamp=1, spin_cmd=invalid)
            self.assertEqual(wire[8], 0)

    def test_seeded_stream_chunking_and_mutation(self):
        rng = random.Random(20261011)
        for codec, make in ((RefereeFrameCodec(), lambda c, i: c.encode(0x0201, struct.pack('<I', i))),
                            (PolarFrameCodec(), lambda c, i: c._wrap(SEG_EVENT, i, struct.pack('<I', i)))):
            expected = 200
            stream = b''.join(b'\x00' * rng.randrange(10) + make(codec, i) for i in range(expected))
            buffer = bytearray()
            count = 0
            offset = 0
            while offset < len(stream):
                size = rng.randrange(1, 32)
                buffer.extend(stream[offset:offset+size]); offset += size
                frames, used = codec.decode_with_consumed(buffer)
                count += len(frames); del buffer[:used]
                self.assertLessEqual(len(buffer), 308)
            self.assertEqual(count, expected)
            self.assertFalse(buffer)
            for _ in range(500):
                junk = rng.randbytes(rng.randrange(400))
                frames, used = codec.decode_with_consumed(junk)
                self.assertTrue(0 <= used <= len(junk))

    def test_custom_downlink_bounded_and_declared_telemetry_length(self):
        from rm_client.backend.referee.rm2026.codec import decode_message
        from rm_client.backend.referee.wire import encode_bytes
        from rm_client.native_viewer_telemetry import _FIXED, parse_vehicle_telemetry
        self.assertEqual(len(decode_message('CustomByteBlock', encode_bytes(1, b'x' * 300))['data']), 300)
        for name in ('CustomByteBlock', ' CustomByteBlock '):
            self.assertEqual(decode_message(name, encode_bytes(1, b'x' * 301)), {})
        for declared in (74, 75, 76):
            data = _FIXED.pack(b'PDL1', 1, declared, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, *([0.0] * 9))
            self.assertEqual(parse_vehicle_telemetry(data) is not None, declared == 76)

    def test_explicit_crc_reference_must_exist(self):
        import ast
        import os
        from unittest.mock import patch
        source = (Path(__file__).parent / 'polar_link_test.py').read_text()
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'load_team_crc')
        namespace = {'os': os}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<crc-loader>', 'exec'), namespace)
        with patch.dict(os.environ, {'POLAR_TEAM_CRC_REFERENCE': '/nonexistent/explicit-crc.py'}):
            with self.assertRaises(FileNotFoundError):
                namespace['load_team_crc']()

    def test_km_rejects_reserved_bits_and_length_aliases(self):
        good = encode_km_control_payload(sequence=65535, mouse_x=-32768, keyboard_value=0xFFFF)
        for n in range(26, 31):
            self.assertIsNotNone(decode_km_control_payload(good.ljust(n, b'\x00')))
        for malformed in (good[:-1], good + b'\x00' * 5, good + b'\x01'):
            self.assertIsNone(decode_km_control_payload(malformed))
        for index, value in ((16, 8), (17, 2), (18, 1), (25, 1)):
            bad = bytearray(good); bad[index] = value
            self.assertIsNone(decode_km_control_payload(bad))


if __name__ == '__main__':
    unittest.main()
