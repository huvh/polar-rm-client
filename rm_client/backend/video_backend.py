"""UDP ??????? SharkClient udp_bridge + video_decoder ????

- 8 ?? Shark ????????? FrameAssembler?
- ? codec ?????MJPEG(FFD8) / H.265(HEVC NAL)
- MJPEG ???? OpenCV ??? BGR ndarray??? QImage?
- H.265 ????? bytes????? ffmpeg ?????????
- ?????/??/??/?????/???????? Shark UDP stats?
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import threading
import time
from typing import Any, Callable

from ..transports import UDPVideoReceiver


def detect_frame_codec(frame: bytes) -> str:
    """?? 'mjpeg' / 'h265' / 'unknown'?"""
    if len(frame) < 4:
        return "unknown"
    if frame[0] == 0xFF and frame[1] == 0xD8:
        return "mjpeg"
    # HEVC NAL?????? 00 00 01 ? 00 00 00 01??? NAL type
    for start in (b"\x00\x00\x00\x01", b"\x00\x00\x01"):
        idx = frame.find(start)
        if idx >= 0:
            nal = frame[idx + len(start)]
            nal_type = (nal >> 1) & 0x3F
            # VPS=32 SPS=33 PPS=34 IDR_W_RADL=19..20 ??32-34/39/40 ????/??
            if nal_type in (19, 20, 21, 32, 33, 34, 39, 40):
                return "h265"
            if nal_type in range(0, 32):
                return "h265"
    return "unknown"


class RmVideoBackend(UDPVideoReceiver):
    """SharkClient ?? UDP ?????? codec ??/MJPEG ??/????"""

    def __init__(self, host: str = "127.0.0.1", port: int = 3334) -> None:
        super().__init__(host=host, port=port)
        self.codec: str = "unknown"
        self.fps: float = 0.0
        self.bitrate: float = 0.0  # bytes/s
        self.dropped_frames: int = 0
        self.decoder_backend: str = "none"
        self.output_width: int = 0
        self.output_height: int = 0
        self.latest_bgr: Any = None  # MJPEG ???? BGR ndarray
        self.latest_h265: bytes = b""
        self.external_on_frame: Callable[[bytes], None] | None = None
        self.decode_h265 = False  # ????? ffmpeg ??????????
        self.ffmpeg_available: bool = shutil.which("ffmpeg") is not None
        self._started_at = 0.0
        self._frame_times: list[float] = []
        self._bytes_this_second = 0
        self._last_stats_at = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def start(self) -> None:
        self.on_frame = self._on_assembled_frame
        self._started_at = time.perf_counter()
        self._last_stats_at = time.perf_counter()
        super().start()

    def _on_assembled_frame(self, frame: bytes) -> None:
        now = time.perf_counter()
        with self._lock:
            self.codec = detect_frame_codec(frame)
            self._frame_times.append(now)
            if len(self._frame_times) > 120:
                self._frame_times.pop(0)
            self._bytes_this_second += len(frame)
            if now - self._last_stats_at >= 1.0:
                span = now - self._last_stats_at
                self.bitrate = self._bytes_this_second / span
                self._bytes_this_second = 0
                self._last_stats_at = now
                if len(self._frame_times) >= 2:
                    window = self._frame_times[-min(60, len(self._frame_times)):]
                    if len(window) >= 2:
                        self.fps = (len(window) - 1) / max(1e-6, window[-1] - window[0])
            if self.codec == "mjpeg":
                self._decode_mjpeg(frame)
            elif self.codec == "h265":
                self.latest_h265 = frame
                if self.decode_h265 and self.ffmpeg_available:
                    bgr = self._ffmpeg_decode_hevc(frame)
                    if bgr is not None:
                        self.latest_bgr = bgr
                        self.decoder_backend = "ffmpeg"
                        h, w = bgr.shape[:2]
                        self.output_width, self.output_height = w, h
        if self.external_on_frame is not None:
            try:
                self.external_on_frame(frame)
            except Exception:
                pass

    def _decode_mjpeg(self, frame: bytes) -> None:
        try:
            import cv2  # type: ignore
            bgr = cv2.imdecode(
                frame, cv2.IMREAD_COLOR
            )  # type: ignore[attr-defined]
            if bgr is not None:
                self.latest_bgr = bgr
                self.decoder_backend = "cv2"
                h, w = bgr.shape[:2]
                self.output_width, self.output_height = w, h
        except Exception:
            self.decoder_backend = "none"

    def _ffmpeg_decode_hevc(self, frame: bytes) -> Any:
        """??? ffmpeg ??? HEVC ?? BGR24 ndarray????? None?"""
        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-f", "hevc", "-i", "pipe:0",
                    "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
                ],
                input=frame, capture_output=True, timeout=5.0,
            )
            if proc.returncode != 0 or not proc.stdout:
                return None
            import cv2  # type: ignore
            # ???????? reshape?? SPS ??????????????? 1280x720
            # ???????? raw bytes ??????
            data = proc.stdout
            for (w, h) in ((1280, 720), (960, 540), (1920, 1080), (640, 480)):
                if len(data) == w * h * 3:
                    import numpy as np  # type: ignore
                    return np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
            return None
        except Exception:
            return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self.frames_received > 0,
                "host": self.host,
                "port": self.port,
                "packets_received": self.packets_received,
                "frames_received": self.frames_received,
                "dropped_frames": self.dropped_frames,
                "codec": self.codec,
                "fps": round(self.fps, 1),
                "bitrate": round(self.bitrate, 1),
                "decoder_backend": self.decoder_backend,
                "output_width": self.output_width,
                "output_height": self.output_height,
                "last_error": self.last_error,
            }
