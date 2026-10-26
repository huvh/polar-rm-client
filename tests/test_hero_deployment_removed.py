"""部署功能移除后，旧动作及裁判遥测都不能恢复控制台或改变图传。"""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager
from rm_client.backend.referee.rm2026.state_adapter import Rm2026StateAdapter
from rm_client.backend.safety import ControlState, OfficialSafety
from rm_client.configuration.commands import resolve_config_command
from rm_client.model import RobotState, build_default_registry
from rm_client.ui.overlay_coordinator import OverlayKind
from rm_client.ui.polar_app import PolarRMWindow


class HeroDeploymentRemovedTests(unittest.TestCase):
    def test_no_public_console_or_publish_route_remains(self):
        for name in ("open_hero_deploy_interface", "close_hero_deploy_interface",
                     "send_hero_deploy_request", "update_hero_deploy_state",
                     "draw_hero_deploy_interface", "consume_hero_native_video_frame"):
            self.assertFalse(hasattr(PolarRMWindow, name), name)
        self.assertFalse(hasattr(BackendManager, "publish_hero_deploy"))
        self.assertFalse(hasattr(OverlayKind, "HERO_DEPLOY"))
        self.assertIsNone(resolve_config_command("Open Deploy Interface"))
        self.assertIsNone(resolve_config_command("Record Hero Test"))
        lob = build_default_registry().get("HeroLob")
        self.assertIsNone(lob.get_setting("Open Deploy Interface"))
        self.assertIsNotNone(lob.get_setting("Preview Lob"))

    def test_status_sync_only_updates_telemetry(self):
        host = NS(set_active_video_source=Mock(), field_log=NS(emit=Mock()),
                  _active_video_source="udp hevc", _hero_native_override=False)
        adapter = Rm2026StateAdapter(host)
        state = RobotState()
        # 无论进入或退出部署，原视频源与采样所有权均不变化。
        for status in (1, 1, 0):
            adapter._apply_one(state, "DeployModeStatusSync", {"status": status})
            self.assertEqual(state.deploy_mode, status)
            self.assertEqual(host._active_video_source, "udp hevc")
            host.set_active_video_source.assert_not_called()
        self.assertEqual(state.deploy_status_revision, 2)

    def test_stale_authorization_cannot_publish_a_deploy_command(self):
        for phase in ControlState:
            safety = OfficialSafety()
            safety.allow_mqtt_publish = True
            safety.control_state = phase
            safety._authorized_capabilities = frozenset({"hero", "core_kmc"})
            for mode in (0, 1):
                allowed, reason = safety.can_publish(
                    "HeroDeployModeEventCommand", intent="hero")
                self.assertFalse(allowed)
                self.assertIn("removed", reason)


if __name__ == "__main__":
    unittest.main()
