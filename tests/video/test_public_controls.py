"""公共图传接口验证配置准入和状态快照，不访问设备或创建监听。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rm_client.backend.manager import BackendManager
from rm_client.backend.video import RmVideoBackend


class PublicVideoControlsTests(unittest.TestCase):
    def setUp(self):
        self.manager = object.__new__(BackendManager)
        self.manager.udp = RmVideoBackend()
        self.manager.set_active_video_source = Mock()

    def test_invalid_channel_cannot_change_selection_or_receiver_configuration(self):
        for channel in (0, 7, -1, 1.5, True, "1"):
            with self.subTest(channel=channel):
                with self.assertRaises(ValueError):
                    self.manager.configure_video_source("Legacy VT02 UDP", legacy_channel=channel)
                self.assertEqual(self.manager.udp.legacy_channel, 1)
                self.manager.set_active_video_source.assert_not_called()
        self.manager.configure_video_source("Legacy VT02 UDP", legacy_channel=6)
        self.assertEqual(self.manager.udp.legacy_channel, 6)
        self.manager.set_active_video_source.assert_called_once_with("Legacy VT02 UDP")

    def test_diagnostic_snapshot_does_not_expose_or_mutate_receiver_owner(self):
        self.assertEqual(self.manager.video_receiver_status(), {})
        observed = {"port": "COM14", "ready": True, "angle_packets_written": 3}
        self.manager.udp.legacy_control = SimpleNamespace(stats=lambda: observed)
        self.manager.controller_angles = SimpleNamespace(stats=lambda: {"armed": False})
        snapshot = self.manager.controller_angle_snapshot()
        snapshot["receiver"]["ready"] = False
        self.assertTrue(observed["ready"])
        self.assertEqual(snapshot["angles"], {"armed": False})
        self.assertEqual(self.manager.video_receiver_status(), observed)


if __name__ == "__main__":
    unittest.main()
