"""在真实 Qt HUD 中有界观察旧接收端；独立配置只启用视频，不打开控制链。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 300:
        parser.error("seconds must be between 5 and 300")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / "runtime"
    config_dir = runtime / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    # 保留用户原配置与进程授权；诊断实例仅启动真实 UDP 视频入口。
    config = json.loads((ROOT / "configs/default.json").read_text(encoding="utf-8"))
    for name, module in config["modules"].items():
        module["enabled"] = name in {"CameraFeed", "UDPVideo", "Chinese"}
    config["modules"]["CameraFeed"]["settings"]["Source"] = "Legacy VT02 UDP"
    (config_dir / "default.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.environ["POLAR_USER_DATA_ROOT"] = str(runtime)
    os.environ["POLAR_AUTOSTART"] = "1"
    os.environ["POLAR_DISABLE_LOCAL_CAPTURE"] = "1"
    os.environ["POLAR_DISABLE_MEDIA_PRELOAD"] = "1"
    from PySide6.QtCore import QTimer
    from rm_client.ui.polar.qt_application import launch_qt_application
    from rm_client.ui.polar_app import PolarRMWindow

    def create_window():
        window = PolarRMWindow()
        began = time.perf_counter()
        samples = []
        first_live = None
        latest_live = None
        last_sequence = None
        last_advance = None
        max_gap = 0.0
        captured = False

        def observe():
            nonlocal first_live, latest_live, last_sequence, last_advance, max_gap, captured
            now = time.perf_counter()
            stats = window.backend.udp.stats()
            ready = window.normal_video_frame_ready()
            sequence = window._display_frame_sequence
            image = window.frame_image
            sample = {
                "elapsed_s": round(now - began, 3),
                "ingress": stats["ingress"],
                "parsed_parameters": not stats["h265_recovery_blocked"],
                "decoded_frames": stats["decoded_frames"],
                "decoded_fresh": stats["decoded_connected"],
                "resolution": [stats["output_width"], stats["output_height"]],
                "hud_ready": ready,
                "hud_sequence": sequence,
                "hud_image": bool(image is not None and not image.isNull()),
                "decoder_health": stats["h265_decoder_health"],
            }
            if ready:
                first_live = now if first_live is None else first_live
                latest_live = now
                if sequence != last_sequence:
                    if last_advance is not None:
                        max_gap = max(max_gap, now - last_advance)
                    last_advance = now
                    last_sequence = sequence
                if image is not None and not image.isNull():
                    color = image.pixelColor(image.width() // 2, image.height() // 2)
                    sample["center_rgb"] = [color.red(), color.green(), color.blue()]
                if not captured and now - first_live >= 3:
                    window.grabFramebuffer().save(str(output / "live-hud.png"))
                    captured = True
            samples.append(sample)
            live_span = latest_live - first_live if first_live is not None else 0.0
            report = {
                "schema": "polar-legacy-hud-observation-v1",
                "real_window": True,
                "video_source": "Legacy VT02 UDP",
                "control_modules_enabled": False,
                "duration_s": round(now - began, 3),
                "first_to_last_live_s": round(live_span, 3),
                "max_observed_hud_update_gap_s": round(max_gap, 3),
                "physical_camera_change_verified": False,
                "physical_disconnect_verified": False,
                "samples": samples,
            }
            temporary = output / "observation.tmp"
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(output / "observation.json")
            if now - began >= args.seconds:
                window._legacy_evidence_timer.stop()
                if ready:
                    window.grabFramebuffer().save(str(output / "last-live-hud.png"))
                window.close()

        window._legacy_evidence_timer = QTimer(window)
        window._legacy_evidence_timer.timeout.connect(observe)
        window._legacy_evidence_timer.start(1000)
        return window

    launch_qt_application(create_window)


if __name__ == "__main__":
    main()
