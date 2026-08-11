"""UDP 图传后端（对齐 SharkClient udp_bridge + video_decoder 能力）。

- 8 字节 Shark 包头分片重组（复用 FrameAssembler）
- 帧 codec 自动检测：MJPEG(FFD8) / H.265(HEVC NAL)
- MJPEG 帧直接用 OpenCV 解码为 BGR ndarray（可转 QImage）
- H.265 帧保留原始 bytes，若本机有 ffmpeg 则提供按需解码工具
- 统计：帧率/码率/丢帧/编解码后端/输出分辨率（对齐 Shark UDP stats）
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import threading
import time
from queue import Empty, Full, Queue
from typing import Any, Callable

from ..transports import UDPVideoReceiver


def detect_frame_codec(frame: bytes) -> str:
    """返回 'mjpeg' / 'h264' / 'h265' / 'unknown'。

    注意：UDP 链路预期为 MJPEG 或 H.265（Shark 编码选项），H.264 识别
    仅用于避免把普通 H.264 误判成 H.265。启发式识别不做严格字节流解析。
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


class RmVideoBackend(UDPVideoReceiver):
    """SharkClient 风格 UDP 图传后端（含 codec 检测/MJPEG 解码/统计）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 3334) -> None:
        super().__init__(host=host, port=port)
        self.codec: str = "unknown"
        self.fps: float = 0.0
        self.bitrate: float = 0.0  # bytes/s
        self.dropped_frames: int = 0
        self.decoder_backend: str = "none"
        self.output_width: int = 0
        self.output_height: int = 0
        self.mjpeg_decoded_frames: int = 0
        self.latest_bgr: Any = None  # MJPEG 解码后的 BGR ndarray
        # Timestamp of the *decoded* MJPEG frame.  ``last_frame_at`` tracks
        # encoded UDP traffic and therefore must not be used to refresh an old
        # image when H.265/unknown packets arrive after the last MJPEG frame.
        self.latest_bgr_at = 0.0
        self.latest_h265: bytes = b""
        self.last_frame_at = 0.0
        self.external_on_frame: Callable[[bytes], None] | None = None
        self.decode_h265 = True  # 有 ffmpeg 时自动开持久解码器
        self.ffmpeg_available: bool = shutil.which("ffmpeg") is not None
        self.h265_decoder: ContinuousMjpegDecoder | None = (
            ContinuousMjpegDecoder("h265") if self.ffmpeg_available else None
        )
        self._started_at = 0.0
        self._frame_times: list[float] = []
        self._bytes_this_second = 0
        self._last_stats_at = 0.0
        self._lock = threading.Lock()
        self._h265_restart_lock = threading.Lock()
        self._h265_restart_thread: threading.Thread | None = None
        self._h265_next_restart_at = 0.0
        self.h265_decoder_restarts = 0

    # ------------------------------------------------------------------
    def start(self) -> None:
        self.on_frame = self._on_assembled_frame
        self._started_at = time.perf_counter()
        self._last_stats_at = time.perf_counter()
        with self._lock:
            self._frame_times.clear()
            self._bytes_this_second = 0
            self.fps = 0.0
            self.bitrate = 0.0
            self.codec = "unknown"
            self.mjpeg_decoded_frames = 0
            self.latest_bgr = None
            self.latest_bgr_at = 0.0
            self.latest_h265 = b""
            self.last_frame_at = 0.0
            self.h265_decoder_restarts = 0
            self._h265_next_restart_at = 0.0
            self._assembler.frames.clear()
        if self.h265_decoder is not None and self.decode_h265:
            self.h265_decoder.start()
        super().start()

    def _on_assembled_frame(self, frame: bytes) -> None:
        now = time.perf_counter()
        codec = "unknown"
        with self._lock:
            codec = detect_frame_codec(frame)
            self.codec = codec
            self.last_frame_at = now
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
            if codec == "unknown":
                self.dropped_frames += 1
        # 解码放到锁外，避免 cv2/ffmpeg 阻塞 UDP 接收线程与 stats()
        if codec == "mjpeg":
            self._decode_mjpeg(frame)
        elif codec == "h265":
            with self._lock:
                self.latest_h265 = frame
            if self.decode_h265 and self.h265_decoder is not None:
                if self.h265_decoder.available:
                    queued = self.h265_decoder.write(frame)
                    with self._lock:
                        self.decoder_backend = "ffmpeg-mjpeg"
                        if not queued:
                            self.dropped_frames += 1
                else:
                    # A dead ffmpeg must not be restarted synchronously from
                    # the UDP receive loop.  Recover in a bounded side thread;
                    # a future VPS/SPS/IDR will make the stream decodable.
                    self._request_h265_restart()
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
                h, w = bgr.shape[:2]
                with self._lock:
                    self.latest_bgr = bgr
                    self.latest_bgr_at = time.perf_counter()
                    self.mjpeg_decoded_frames += 1
                    self.decoder_backend = "cv2"
                    self.output_width, self.output_height = w, h
        except Exception:
            self.decoder_backend = "none"

    def _ffmpeg_decode_hevc(self, frame: bytes) -> Any:
        """用系统 ffmpeg 把单帧 HEVC 解成 BGR24 ndarray；失败返回 None。"""
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
            # 需要知道宽高才能 reshape；从 SPS 解析宽高成本高，这里先尝试常见 1280x720
            # 失败则放弃，保持 raw bytes 由上层处理。
            data = proc.stdout
            for (w, h) in ((1280, 720), (960, 540), (1920, 1080), (640, 480)):
                if len(data) == w * h * 3:
                    import numpy as np  # type: ignore
                    return np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
            return None
        except Exception:
            return None

    def latest_video_frame(self, timeout_s: float = 0.5) -> tuple[Any, float]:
        """Return the freshest decoded UDP frame and its monotonic timestamp."""

        deadline_age = max(0.0, float(timeout_s))
        now = time.perf_counter()
        h265_frame: Any = None
        h265_at = 0.0
        if self.decode_h265 and self.h265_decoder is not None and self.h265_decoder.available:
            h265_frame, h265_at = self.h265_decoder.latest_with_timestamp(deadline_age)

        with self._lock:
            mjpeg_frame = self.latest_bgr
            mjpeg_at = float(self.latest_bgr_at)
        if mjpeg_frame is None or mjpeg_at <= 0.0 or now - mjpeg_at > deadline_age:
            mjpeg_frame, mjpeg_at = None, 0.0

        if h265_frame is not None and h265_at >= mjpeg_at:
            return h265_frame, h265_at
        if mjpeg_frame is not None:
            return mjpeg_frame, mjpeg_at
        return None, 0.0

    def _request_h265_restart(self) -> None:
        decoder = self.h265_decoder
        now = time.perf_counter()
        if decoder is None or not self.running or now < self._h265_next_restart_at:
            return
        with self._h265_restart_lock:
            if self._h265_restart_thread is not None and self._h265_restart_thread.is_alive():
                return
            self._h265_next_restart_at = now + 1.0

            def restart_worker() -> None:
                with self._h265_restart_lock:
                    if not self.running:
                        return
                    restarted = decoder.start()
                if restarted and self.running:
                    with self._lock:
                        self.h265_decoder_restarts += 1
                        self.decoder_backend = "ffmpeg-mjpeg"

            self._h265_restart_thread = threading.Thread(
                target=restart_worker,
                name="h265-decoder-restart",
                daemon=True,
            )
            self._h265_restart_thread.start()

    def stop(self) -> None:
        # Stop packet production before touching decoder stdin.
        super().stop()
        with self._h265_restart_lock:
            if self.h265_decoder is not None:
                self.h265_decoder.stop()
        restart_thread = self._h265_restart_thread
        if restart_thread is not None and restart_thread.is_alive():
            restart_thread.join(timeout=1.0)
        self._h265_restart_thread = None

    def stats(self) -> dict[str, Any]:
        h265_at = self.h265_decoder.latest_timestamp() if self.h265_decoder else 0.0
        h265_frames = self.h265_decoder.frames_decoded if self.h265_decoder else 0
        with self._lock:
            decoded_at = max(float(self.latest_bgr_at), float(h265_at))
            decoded_connected = bool(
                decoded_at > 0.0 and time.perf_counter() - decoded_at <= 2.0
            )
            connected = (
                self.frames_received > 0
                and self.last_frame_at > 0
                and time.perf_counter() - self.last_frame_at <= 2.0
            )
            return {
                "connected": connected,
                "host": self.host,
                "port": self.port,
                "packets_received": self.packets_received,
                "frames_received": self.frames_received,
                "dropped_frames": self.dropped_frames + self._assembler.dropped_count,
                "codec": self.codec,
                "fps": round(self.fps, 1),
                "bitrate": round(self.bitrate, 1),
                "decoder_backend": self.decoder_backend,
                "output_width": self.output_width,
                "output_height": self.output_height,
                "decoded_connected": decoded_connected,
                "decoded_frames": self.mjpeg_decoded_frames + h265_frames,
                "decoded_frame_at": decoded_at,
                "h265_decoder_ready": bool(self.h265_decoder and self.h265_decoder.available),
                "h265_decoded_frames": h265_frames,
                "h265_input_queue": self.h265_decoder.input_queue_depth() if self.h265_decoder else 0,
                "h265_input_dropped": self.h265_decoder.input_chunks_dropped if self.h265_decoder else 0,
                "h265_decoder_restarts": self.h265_decoder_restarts,
                "last_error": self.last_error,
            }


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


class ContinuousMjpegDecoder:
    """常驻 ffmpeg → MJPEG 管道的持续 H.264/H.265 解码器。

    与 SharkClient "H.265: 后端解码后以 MJPEG 本机流显示" 同思路：
    ffmpeg 把连续码流解码成自包含 MJPEG 帧（带 SOI/EOI，自带宽高），
    前端按 FFD8/FFD9 切帧后用 cv2.imdecode 得到 BGR 帧，避免 rawvideo
    需要预先知道宽高，也避免每帧 spawn 一个 ffmpeg 进程。
    """

    INPUT_QUEUE_CHUNKS = 256

    def __init__(self, codec: str = "h265", quality: int = 3) -> None:
        self.codec = codec  # "h264" | "h265"
        self.quality = int(quality)
        self.available = False
        self.last_error = ""
        self.frames_decoded = 0
        self._proc: Any = None
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        # Decoder stdin is serviced off the UDP/UI thread.  A bounded queue
        # prevents a stalled ffmpeg process from freezing 144 Hz rendering or
        # growing memory without limit.
        self._input_queue: Queue[bytes] = Queue(maxsize=self.INPUT_QUEUE_CHUNKS)
        self.input_chunks_dropped = 0
        self.input_chunks_written = 0
        self.input_bytes_written = 0
        self._latest: Any = None
        self._latest_at = 0.0
        self._frame_w = 0
        self._frame_h = 0

    def start(self) -> bool:
        if self._running:
            return True
        # A reader/writer failure marks the decoder unavailable but may leave
        # a reaped process handle behind.  Dispose it before spawning the next
        # instance so recovery never leaks ffmpeg children or stale queues.
        if self._proc is not None:
            self.stop(clear_latest=False)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.last_error = "ffmpeg 不可用"
            return False
        try:
            self._drain_input_queue()
            self._proc = subprocess.Popen(
                [
                    ffmpeg, "-v", "error",
                    "-f", self.codec, "-i", "pipe:0",
                    "-f", "mjpeg", "-q:v", str(self.quality), "pipe:1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # Corrupt field packets can produce a large volume of ffmpeg
                # diagnostics.  An unread PIPE eventually deadlocks; DEVNULL
                # keeps the persistent decoder non-blocking.
                stderr=subprocess.DEVNULL,
            )
            self._running = True
            self._writer = threading.Thread(
                target=self._write_loop, name=f"mjpeg-in-{self.codec}", daemon=True
            )
            self._reader = threading.Thread(
                target=self._read_loop, name=f"mjpeg-dec-{self.codec}", daemon=True
            )
            self.available = True
            self.last_error = ""
            self._writer.start()
            self._reader.start()
            return True
        except Exception as exc:  # pragma: no cover - depends on ffmpeg
            message = str(exc)
            self.stop()
            self.last_error = message
            return False

    def write(self, data: bytes) -> bool:
        """Queue stream bytes without blocking the caller on ffmpeg stdin."""

        if self._proc is None or not self._running:
            return False
        payload = bytes(data)
        if not payload:
            return True
        try:
            self._input_queue.put_nowait(payload)
            return True
        except Full:
            with self._lock:
                self.input_chunks_dropped += 1
            return False

    def _write_loop(self) -> None:
        while self._running:
            try:
                payload = self._input_queue.get(timeout=0.10)
            except Empty:
                continue
            proc = self._proc
            if proc is None or proc.stdin is None:
                break
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
                with self._lock:
                    self.input_chunks_written += 1
                    self.input_bytes_written += len(payload)
            except Exception as exc:
                if self._running:
                    self.last_error = str(exc)
                self.available = False
                self._running = False
                break

    def _read_loop(self) -> None:
        buf = bytearray()
        while self._running and self._proc is not None and self._proc.stdout is not None:
            try:
                chunk = self._proc.stdout.read(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                consume_mjpeg_stream(buf, self._decode)
            except Exception:
                break
        self._running = False
        self.available = False

    def _decode(self, frame: bytes) -> None:
        try:
            import cv2  # type: ignore
            bgr = cv2.imdecode(frame, cv2.IMREAD_COLOR)  # type: ignore[attr-defined]
            if bgr is None:
                return
            with self._lock:
                self._latest = bgr
                # All video sources use the same monotonic clock so callers
                # can safely compare native H.264, UDP H.265 and MJPEG frames.
                self._latest_at = time.perf_counter()
                h, w = bgr.shape[:2]
                self._frame_w, self._frame_h = w, h
                self.frames_decoded += 1
        except Exception:
            pass

    def latest(self, timeout_s: float = 0.5) -> Any:
        frame, _timestamp = self.latest_with_timestamp(timeout_s)
        return frame

    def latest_with_timestamp(self, timeout_s: float = 0.5) -> tuple[Any, float]:
        """Return a fresh decoded frame and its monotonic decode timestamp."""

        now = time.perf_counter()
        with self._lock:
            if (
                self._latest is None
                or self._latest_at <= 0.0
                or now - self._latest_at > max(0.0, float(timeout_s))
            ):
                return None, 0.0
            return self._latest, float(self._latest_at)

    def restart(self, *, clear_latest: bool = True) -> bool:
        """Restart ffmpeg after a stream reset or sequence discontinuity."""

        self.stop(clear_latest=clear_latest)
        return self.start()

    def frame_size(self) -> tuple[int, int]:
        with self._lock:
            return self._frame_w, self._frame_h

    def latest_timestamp(self) -> float:
        """Return the monotonic timestamp of the last decoded frame."""

        with self._lock:
            return float(self._latest_at)

    def input_queue_depth(self) -> int:
        return self._input_queue.qsize()

    def _drain_input_queue(self) -> None:
        while True:
            try:
                self._input_queue.get_nowait()
            except Empty:
                return

    def stop(self, *, clear_latest: bool = True) -> None:
        self._running = False
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                # Terminate first: closing a buffered stdin while the writer
                # thread is blocked on a full OS pipe may itself try to flush
                # and stall the caller.  Once ffmpeg exits, close becomes a
                # bounded broken-pipe cleanup instead of a UI-thread wait.
                proc.terminate()
            except Exception:
                pass
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._writer is not None and self._writer.is_alive():
            self._writer.join(timeout=0.6)
        self._writer = None
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=0.6)
        self._reader = None
        self._drain_input_queue()
        self.available = False
        if clear_latest:
            with self._lock:
                self._latest = None
                self._latest_at = 0.0
                self._frame_w = 0
                self._frame_h = 0
