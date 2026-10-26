"""新旧图传共用一个来源设置；占位源不得启动设备或沿用旧图像。"""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import test_normal_video_timeline_contract as window_fixture
from rm_client.config_store import ClientConfigStore, apply_registry_config, export_client_config
from rm_client.model import build_default_registry
from rm_client.video_sources import (
    LEGACY_VIDEO_SOURCE, NEW_VIDEO_SOURCE, VIDEO_SOURCE_CHOICES, video_source_notice,
)


class VideoGenerationSelectionTests(unittest.TestCase):
    def test_options_preserve_existing_sources_and_one_selection_value(self):
        registry = build_default_registry()
        source = registry.get("CameraFeed").get_setting("Source")
        self.assertEqual(source.options, list(VIDEO_SOURCE_CHOICES))
        self.assertTrue({"Webcam", "Shark UDP", "UDP HEVC", "Native 0x0310", "Synthetic"}
                        .issubset(source.options))
        self.assertIn(LEGACY_VIDEO_SOURCE, source.options)
        self.assertIn(NEW_VIDEO_SOURCE, source.options)
        self.assertIn("暂未实现", video_source_notice(NEW_VIDEO_SOURCE))

    def test_both_generation_values_survive_saved_configuration(self):
        registry = build_default_registry()
        with tempfile.TemporaryDirectory() as folder:
            store = ClientConfigStore(Path(folder))
            for mode in (LEGACY_VIDEO_SOURCE, NEW_VIDEO_SOURCE):
                registry.get("CameraFeed").get_setting("Source").value = mode
                data = export_client_config(
                    registry, gui_mode="JelloSigma", selected_category="Vision",
                    selected_module="CameraFeed", module_expanded=set(),
                    old_panels={}, new_panels={}, dropdown_panels={})
                store.save("video", data)
                restored = build_default_registry()
                apply_registry_config(restored, store.load("video"))
                self.assertEqual(restored.get("CameraFeed").get_setting("Source").value, mode)

    def test_new_selection_clears_real_decoded_hud_and_starts_no_transport(self):
        fixture = window_fixture.NormalVideoTimelineContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        window = fixture.window
        source = fixture.source
        stream = (ROOT / "assets/selftest/h264_one_gop.h264").read_bytes()

        def feed_legacy():
            source.value = LEGACY_VIDEO_SOURCE
            window.backend.set_active_video_source(LEGACY_VIDEO_SOURCE, start=False)
            window.backend.udp.wait_closed()
            window.backend.set_active_video_source(LEGACY_VIDEO_SOURCE, start=False)
            window.backend.udp._on_assembled_frame(stream)
            deadline = time.perf_counter() + 4
            while not window.backend.udp.decoded_frame_fresh() and time.perf_counter() < deadline:
                time.sleep(.01)
            window.consume_capture_frame()
            self.assertTrue(window.normal_video_frame_ready())
            self.assertIsNotNone(window.frame_image)

        feed_legacy()
        with patch.object(window.backend.udp, "start") as udp_start, \
             patch.object(window.backend.native_decoder, "start") as native_start, \
             patch.object(window.camera_worker, "start") as camera_start:
            source.value = NEW_VIDEO_SOURCE
            window.backend.set_active_video_source(NEW_VIDEO_SOURCE)
            window.consume_capture_frame()
            self.assertIsNone(window.frame_image)
            self.assertIsNone(window.frame_pixmap)
            self.assertFalse(window.normal_video_frame_ready())
            self.assertEqual(window.backend.latest_video_frame(source_mode=NEW_VIDEO_SOURCE),
                             (None, 0.0, "not-implemented"))
            self.assertEqual(window.backend.stats()["video_source"]["state"], "not_implemented")
            painter = Mock()
            window.draw_backend_video_lost(painter, 1280, 720)
            self.assertIn("暂未实现", painter.drawText.call_args.args[-1])
            udp_start.assert_not_called()
            native_start.assert_not_called()
            camera_start.assert_not_called()
        self.assertTrue(window.backend.udp.wait_closed())
        feed_legacy()


if __name__ == "__main__":
    unittest.main()
