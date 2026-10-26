"""旧接收端非 IDR 码流的专用策略；本地录制样本只用于解析回归。"""
from pathlib import Path
import os
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend.video_backend import (
    AnnexBRecoveryGate, ContinuousMjpegDecoder, RmVideoBackend, iter_annexb_nal_units,
)

PARAMETERS = bytes.fromhex(
    "0000000167640034ac4d00a00b74d4040405000003000100000300780f1c32a0"
    "0000000168ee3cb0")
FIRST_SLICE = b"\x00\x00\x00\x01\x61\xe0\x80"
MIDDLE_SLICE = b"\x00\x00\x00\x01\x61\x00\x5a\x00"


class LegacyIntraRefreshTests(unittest.TestCase):
    def test_default_policy_keeps_waiting_for_idr(self):
        gate = AnnexBRecoveryGate("h264")
        self.assertIsNone(gate.feed(PARAMETERS + FIRST_SLICE))
        self.assertTrue(gate.blocked)
        self.assertFalse(ContinuousMjpegDecoder("h264").allow_h264_non_idr)

    def test_legacy_policy_requires_parameters_and_first_slice(self):
        gate = AnnexBRecoveryGate("h264", allow_h264_non_idr=True)
        self.assertIsNone(gate.feed(FIRST_SLICE))
        self.assertIsNone(gate.feed(PARAMETERS + MIDDLE_SLICE))
        payload = gate.feed(FIRST_SLICE)
        self.assertEqual(payload, PARAMETERS + FIRST_SLICE)
        self.assertFalse(gate.blocked)
        gate.reset()
        self.assertIsNone(gate.feed(FIRST_SLICE))

    def test_split_slice_header_keeps_first_mb_until_available(self):
        gate = AnnexBRecoveryGate("h264", allow_h264_non_idr=True)
        parts = []
        for byte in PARAMETERS + FIRST_SLICE:
            result = gate.feed(bytes([byte]))
            if result is not None:
                parts.append(result)
        self.assertEqual(b"".join(parts), PARAMETERS + FIRST_SLICE)

    def test_hevc_never_uses_the_legacy_h264_policy(self):
        self.assertFalse(AnnexBRecoveryGate("h265", allow_h264_non_idr=True).allow_h264_non_idr)
        self.assertFalse(ContinuousMjpegDecoder("h265", allow_h264_non_idr=True).allow_h264_non_idr)

    def test_changing_ingress_retires_non_idr_policy(self):
        backend = RmVideoBackend()
        self.addCleanup(backend.stop)
        backend.configure_ingress("legacy-vt02-h264")
        decoder = backend._select_annexb_decoder("h264")
        self.assertTrue(decoder.allow_h264_non_idr)
        self.assertTrue(backend.h265_recovery.allow_h264_non_idr)
        backend.configure_ingress("shark-framed")
        decoder = backend._select_annexb_decoder("h264")
        self.assertFalse(decoder.allow_h264_non_idr)
        self.assertFalse(backend.h265_recovery.allow_h264_non_idr)

    def test_local_genuine_capture_decodes_without_an_idr(self):
        sample = os.environ.get("POLAR_LEGACY_CAPTURE", "")
        if not sample:
            self.skipTest("set POLAR_LEGACY_CAPTURE to the local, unshared receiver capture")
        stream = Path(sample).read_bytes()
        units = iter_annexb_nal_units(stream)
        types = {payload[0] & 31 for _, payload in units}
        self.assertTrue({1, 7, 8}.issubset(types))
        self.assertNotIn(5, types)
        strict = AnnexBRecoveryGate("h264")
        self.assertIsNone(strict.feed(stream))
        backend = RmVideoBackend()
        self.addCleanup(backend.stop)
        backend.configure_ingress("legacy-vt02-h264")
        # 录制样本为 60 FPS。按首 slice 的 first_mb_in_slice=0 统计画面数，
        # 以原速回放；原来的 32 KiB/5 ms 会把约 4 秒码流压进半秒，触发积压保护。
        pictures = sum(1 for _, payload in units if len(payload) > 1
                       and payload[0] & 31 in {1, 5} and payload[1] & 0x80)
        self.assertGreater(pictures, 0)
        bytes_per_second = len(stream) / (pictures / 60)
        next_send = time.perf_counter()
        for offset in range(0, len(stream), 32768):
            chunk = stream[offset:offset + 32768]
            backend._on_assembled_frame(chunk)
            next_send += len(chunk) / bytes_per_second
            time.sleep(max(0.0, next_send - time.perf_counter()))
        deadline = time.perf_counter() + 5
        while not backend.decoded_frame_fresh() and time.perf_counter() < deadline:
            time.sleep(.01)
        image, timestamp = backend.latest_video_frame()
        self.assertIsNotNone(image, backend.stats()["decoder_error"])
        self.assertEqual(image.shape, (720, 1280, 3))
        self.assertGreater(timestamp, 0)
        backend.request_stop()
        self.assertTrue(backend.wait_closed())
        self.assertEqual(backend.latest_video_frame(), (None, 0.0))


if __name__ == "__main__":
    unittest.main()
