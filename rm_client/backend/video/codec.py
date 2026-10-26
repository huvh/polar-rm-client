"""图像格式识别、JPEG 转换及本地 FFmpeg 定位；不持有运行会话。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable

from ...runtime_paths import RuntimePaths


def resolve_ffmpeg_executable() -> str | None:
    """Resolve bundled/system/wheel ffmpeg without downloading at runtime."""
    paths = RuntimePaths.discover()
    candidates = [
        str(paths.ffmpeg_path),
        os.environ.get("POLAR_FFMPEG", "") if paths.source_mode else "",
        (shutil.which("ffmpeg") or "") if paths.source_mode else "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def _decode_jpeg_bgr(frame: bytes) -> Any:
    """Decode one raw encoded image; callers own envelopes and publication.

    OpenCV requires a uint8 array, not Python bytes. Keep this conversion shared
    by UDP MJPEG and the continuous decoder without sharing their lifecycle,
    timestamp, counter or error-reporting policies.
    """
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    encoded = np.frombuffer(frame, dtype=np.uint8)
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)  # type: ignore[attr-defined]


def detect_frame_codec(frame: bytes) -> str:
    """返回 'mjpeg' / 'h264' / 'h265' / 'unknown'。

    输入仍须经过 Shark 分片重组；识别 Annex-B 不代表支持裸 UDP/USB。
    启发式识别不做严格字节流解析。
    """
    if len(frame) < 4:
        return "unknown"
    # MJPEG：裸 SOI 或 4 字节长度前缀 + SOI
    if frame[0] == 0xFF and frame[1] == 0xD8:
        return "mjpeg"
    if len(frame) >= 6 and frame[4] == 0xFF and frame[5] == 0xD8:
        return "mjpeg"
    for start in (b"\x00\x00\x00\x01", b"\x00\x00\x01"):
        idx = frame.find(start)
        if idx < 0:
            continue
        if idx + len(start) >= len(frame):
            continue  # 起始码在帧尾，无 NAL 头字节，跳过避免越界
        nal = frame[idx + len(start)]
        h264_type = nal & 0x1F
        hevc_type = (nal >> 1) & 0x3F
        second = frame[idx + len(start) + 1] if idx + len(start) + 1 < len(frame) else 0
        temporal_ok = (second & 0x07) in range(1, 8) and ((second >> 3) & 0x1F) == 0
        # 先排除明确的 H.264 参数集/分隔符
        if h264_type in (7, 8, 9):
            return "h264"
        # HEVC 参数集/前缀/IDR/尾随帧：要求 HEVC 双字节头格式成立
        if hevc_type in (32, 33, 34, 35, 39, 40) and temporal_ok:
            return "h265"
        if hevc_type in (19, 20, 21) and temporal_ok:
            return "h265"
        # 兜底：H.264 IDR/非参考帧明确标识
        if h264_type in (1, 5, 6) and not temporal_ok:
            return "h264"
    return "unknown"


def consume_mjpeg_stream(buf: bytearray, on_frame: Callable[[bytes], None]) -> None:
    """从字节流中切出完整 MJPEG 帧（SOI/EOI）并回调；保留可能跨块的尾部。"""
    while True:
        start = buf.find(b"\xff\xd8")
        if start < 0:
            # 保留末尾 3 字节，防止 SOI 标志跨块
            if len(buf) > 3:
                del buf[:-3]
            return
        end = buf.find(b"\xff\xd9", start + 2)
        if end < 0:
            del buf[:start]
            return
        frame = bytes(buf[start:end + 2])
        del buf[:end + 2]
        on_frame(frame)
