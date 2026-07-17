from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.tongji_bridge import DEFAULT_PORT, PolarPublisher, build_tongji_packet
from rm_client.tongji_yolo import TongjiYoloV5


def main() -> int:
    parser = argparse.ArgumentParser(description="同济 YOLOv5 桌面 UDP 检测发布器")
    parser.add_argument("--source", default="0", help="摄像头编号或视频文件路径")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--device", default="AUTO", choices=["AUTO", "GPU", "CPU"])
    parser.add_argument("--model", type=Path, default=ROOT.parent / "同济自瞄" / "sp_vision_25" / "assets" / "yolov5.xml")
    args = parser.parse_args()

    import cv2  # type: ignore

    source: int | str = int(args.source) if args.source.isdigit() else args.source
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        print(f"无法打开图传源: {args.source}")
        return 2
    detector = TongjiYoloV5(args.model, args.device)
    publisher = PolarPublisher(port=args.port)
    print(f"同济桌面 runner: {detector.active_device} -> UDP 127.0.0.1:{args.port}")
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            started = time.perf_counter()
            detections = detector.detect(frame)
            armors = [item.payload(index, locked=index == 0) for index, item in enumerate(detections)]
            primary = armors[0] if armors else None
            publisher.publish(build_tongji_packet(frame.shape[1], frame.shape[0], armors, primary=primary))
            elapsed = time.perf_counter() - started
            print(f"\r{len(armors)} armor | {1.0 / max(elapsed, 0.0001):.1f} FPS", end="", flush=True)
    finally:
        capture.release()
        publisher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
