"""图传包的兼容入口和纯协议依赖边界；不启动设备或图传监听。"""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class VideoPackageTests(unittest.TestCase):
    def test_compatibility_paths_share_the_same_owners(self):
        from rm_client.backend import RmVideoBackend as backend_export
        from rm_client.backend import video, video_backend, legacy_receiver, legacy_angle_egress
        from rm_client.backend.video import receiver_protocol, angle_egress, receiver

        self.assertIs(backend_export, video.RmVideoBackend)
        for name in ("RmVideoBackend", "ContinuousMjpegDecoder", "AnnexBRecoveryGate",
                     "resolve_ffmpeg_executable"):
            self.assertIs(getattr(video_backend, name), getattr(video, name))
        self.assertIs(legacy_receiver.LegacyReceiverControl, receiver.LegacyReceiverControl)
        self.assertIs(legacy_receiver.ReceiverFrameParser, receiver_protocol.ReceiverFrameParser)
        self.assertIs(legacy_angle_egress.LegacyAngleEgress, angle_egress.LegacyAngleEgress)
        self.assertIs(legacy_angle_egress.encode_receiver_angles,
                      receiver_protocol.encode_receiver_angles)

    def test_protocol_import_and_roundtrip_need_no_native_or_transport_modules(self):
        # 独立解释器避免已导入模块掩盖包初始化时的可选依赖泄漏。
        script = '''
import importlib.abc
import sys

blocked = {"av", "cv2", "numpy", "serial", "PySide6", "rm_client.transports"}
class NoNativeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("unexpected dependency: " + fullname)
sys.meta_path.insert(0, NoNativeImports())
from rm_client.backend.video.annexb import AnnexBRecoveryGate
from rm_client.backend.video.receiver_protocol import (
    QUERY_STATUS, ReceiverFrameParser, encode_receiver_command,
)
packet = encode_receiver_command(QUERY_STATUS)
frames = ReceiverFrameParser().feed(packet)
assert len(frames) == 1 and frames[0].packet == packet
assert AnnexBRecoveryGate("h264").blocked
assert not any(name in sys.modules for name in blocked)
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
