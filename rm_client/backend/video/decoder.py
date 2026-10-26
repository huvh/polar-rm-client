"""连续解码会话：有界输入、PyAV/BGR 与 FFmpeg 回退、代际发布和资源退出。"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import Any, Callable

from ..resource_close import close_resource
from ..video_source import VideoStopStatus
from .codec import _decode_jpeg_bgr, consume_mjpeg_stream, resolve_ffmpeg_executable


@dataclass
class _TimedDecoderInput:
    payload: bytes
    queued_at: float


@dataclass
class _DecoderSession:
    """Process, queue and cancellation belong to one decoder incarnation."""

    proc: Any
    input_queue: Queue[bytes | _TimedDecoderInput]
    stopped: threading.Event = field(default_factory=threading.Event)
    threads: list[threading.Thread] = field(default_factory=list)
    close_lock: threading.Lock = field(default_factory=threading.Lock)
    close_error: str = ""
    closed: bool = False
    codec_context: Any = None


class ContinuousMjpegDecoder:
    """持续解码槽；旧图传优先 PyAV 直出 BGR，其余入口保持 FFmpeg/MJPEG。

    两种实现共用代际校验、最新帧发布与退出所有权；PyAV 上下文只在单个
    解码线程中使用，FFmpeg 的进程和管道仍由各自工作线程持有。
    """

    INPUT_QUEUE_CHUNKS = 256
    LEGACY_INPUT_QUEUE_CHUNKS = 128
    LEGACY_MAX_QUEUE_AGE_S = 0.050
    LEGACY_STARTUP_GRACE_S = 0.250
    STDERR_LIMIT = 32 * 1024
    FIRST_FRAME_TIMEOUT_S = 3.0
    STALE_TIMEOUT_S = 2.0

    def __init__(self, codec: str = "h265", quality: int = 3,
                 *, allow_h264_non_idr: bool = False) -> None:
        self.codec = codec  # "h264" | "h265"
        self.allow_h264_non_idr = bool(allow_h264_non_idr and codec == "h264")
        # 参考 Pacific_doorlock_sniper 的 parse -> decode -> BGR 链路。
        # 单线程避免 FRAME 线程缓存；未提供 PyAV 时保留随附 FFmpeg 兼容路径。
        self.prefer_native = self.allow_h264_non_idr
        self.backend_name = "ffmpeg-mjpeg"
        self.native_decoder_error = ""
        self.input_queue_limit = (self.LEGACY_INPUT_QUEUE_CHUNKS if self.allow_h264_non_idr
                                  else self.INPUT_QUEUE_CHUNKS)
        self.quality = int(quality)
        self.available = False
        self.last_error = ""
        self.dependency_error = ""
        self.frames_decoded = 0
        self._proc: Any = None
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._generation = 0
        self._session: _DecoderSession | None = None
        self._retired_sessions: list[_DecoderSession] = []
        self._stop_worker: threading.Thread | None = None
        # Decoder stdin is serviced off the UDP/UI thread.  A bounded queue
        # prevents a stalled ffmpeg process from freezing 144 Hz rendering or
        # growing memory without limit.
        self._input_queue: Queue[bytes | _TimedDecoderInput] = Queue(maxsize=self.input_queue_limit)
        self.input_chunks_dropped = 0
        self.input_chunks_written = 0
        self.input_bytes_written = 0
        self._latest: Any = None
        self._latest_at = 0.0
        self._frame_w = 0
        self._frame_h = 0
        self.output_bytes_read = 0
        self.started_at = 0.0
        self.last_exit_code: int | None = None
        self.restart_count = 0
        self._stderr_chunks: deque[bytes] = deque()
        self._stderr_bytes = 0
        self._next_restart_at = 0.0
        self._restart_backoff_s = 0.5
        self.first_frame_at = 0.0
        self._process_frames_decoded = 0
        self._decoded_window_started_at = 0.0
        self.continuous_decoded_seconds = 0.0

    @property
    def lifecycle_generation(self) -> int:
        with self._lock:
            return self._generation

    def start(self, *, expected_generation: int | None = None) -> bool:
        # Check dependencies before spawning or claiming readiness. Keep this
        # fast failure path usable by headless dependency diagnostics as well.
        try:
            import cv2  # type: ignore  # noqa: F401
            import numpy  # type: ignore  # noqa: F401
        except Exception as exc:
            self.dependency_error = f"video decode dependency unavailable: {type(exc).__name__}: {exc}"
            self.last_error = self.dependency_error
            self.available = False
            return False
        # A failed incarnation needs restart(), which runs on a recovery
        # worker. start() must not reap stale workers on a UI/receive callback.
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return False
            if (self._retired_sessions or self._stop_in_progress_locked()
                    or (self._session is not None and not self._running)):
                return False
            generation = self._generation
        # A concurrent recovery owns process creation. Never make a receive or
        # UI caller wait behind its pipe teardown.
        if not self._lifecycle_lock.acquire(blocking=False):
            return False
        try:
            return self._start_generation(generation)
        finally:
            self._lifecycle_lock.release()

    def _start_generation(self, generation: int) -> bool:
        with self._lock:
            if (generation != self._generation or self._retired_sessions
                    or self._stop_in_progress_locked()):
                return False
            if self._running:
                return True
            old = self._detach_session_locked(clear_latest=False)
        if not self._close_retired_session(old):
            return False
        with self._lock:
            if generation != self._generation:
                return False
        session = None
        try:
            demuxer = "hevc" if self.codec.lower() in {"h265", "hevc"} else "h264"
            # Allocate fallible bookkeeping before acquiring a native process.
            session = _DecoderSession(None, Queue(maxsize=self.input_queue_limit))
            context = self._create_native_context() if self.prefer_native else None
            session.codec_context = context
            proc = None
            if context is not None:
                session.threads = [threading.Thread(
                    target=self._native_decode_loop, args=(session,),
                    name=f"pyav-dec-{self.codec}", daemon=True,
                )]
            else:
                ffmpeg = resolve_ffmpeg_executable()
                if not ffmpeg:
                    raise RuntimeError("ffmpeg 不可用")
                proc = subprocess.Popen(
                    [
                        ffmpeg, "-v", "error",
                        "-probesize", "32", "-analyzeduration", "0",
                        # 720p60 实机需避免解码/再编码两端帧线程各缓存多帧。
                        *(["-flags2", "+showall", "-flags", "low_delay", "-threads", "1"]
                          if self.allow_h264_non_idr else []),
                        "-f", demuxer, "-i", "pipe:0",
                        "-flush_packets", "1",
                        "-c:v", "mjpeg", "-q:v", str(self.quality),
                        *(["-threads", "1", "-vsync", "0"] if self.allow_h264_non_idr else []),
                        "-f", "image2pipe", "pipe:1",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                session.proc = proc
                session.threads = [
                    threading.Thread(
                        target=self._run_session_worker, args=(target, session, pipe),
                        name=f"{name}-{self.codec}", daemon=True,
                    )
                    for target, name, pipe in (
                        (self._write_loop, "mjpeg-in", "stdin"),
                        (self._read_loop, "mjpeg-dec", "stdout"),
                        (self._stderr_loop, "mjpeg-err", "stderr"),
                    )
                ]
            with self._lock:
                if generation != self._generation:
                    session.stopped.set()
                else:
                    self._session = session
                    self._proc = proc
                    self._input_queue = session.input_queue
                    self._writer = session.threads[0]
                    self._reader = session.threads[0] if context is not None else session.threads[1]
                    self._stderr_reader = None if context is not None else session.threads[2]
                    self.backend_name = "pyav-bgr" if context is not None else "ffmpeg-mjpeg"
                    self._running = True
                    self.available = True
                    self.started_at = time.perf_counter()
                    self.first_frame_at = 0.0
                    self._process_frames_decoded = 0
                    self.last_exit_code = None
                    self.dependency_error = ""
                    self.last_error = ""
                    self._stderr_chunks.clear()
                    self._stderr_bytes = 0
                    # Publish and start atomically with respect to stop().
                    for worker in session.threads:
                        worker.start()
            if session.stopped.is_set():
                self._close_retired_session(session)
                return False
            return True
        except Exception as exc:  # pragma: no cover - platform process failure
            with self._lock:
                if generation == self._generation:
                    self.last_error = str(exc)
                    if session is not None and self._session is session:
                        self._detach_session_locked(clear_latest=True)
            if session is not None and (session.proc is not None or session.codec_context is not None):
                if not self._close_retired_session(session):
                    with self._lock:
                        if generation == self._generation:
                            self.last_error = f"{exc}; cleanup: {session.close_error}"
            return False

    def write(self, data: bytes, *, expected_generation: int | None = None) -> bool:
        """Queue bytes to the captured process without blocking on its stdin."""

        payload = bytes(data)
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return False
            if self._session is None or not self._running:
                return False
            if not payload:
                return True
            try:
                item = (_TimedDecoderInput(payload, time.perf_counter())
                        if self.allow_h264_non_idr else payload)
                self._input_queue.put_nowait(item)
                return True
            except Full:
                self.input_chunks_dropped += 1
                self.last_error = "decoder input queue overflow; waiting for stream recovery"
                if self.allow_h264_non_idr and self._session is not None:
                    # 压缩分片不能像显示帧一样任意丢弃；整个解码代际退出后再等参数集恢复。
                    self._session.stopped.set()
                    self.available = self._running = False
                return False

    def _session_current_locked(self, session: _DecoderSession) -> bool:
        return self._session is session and not session.stopped.is_set()

    def _create_native_context(self) -> Any:
        """建立参考工程同类的 H.264 增量解码器；兼容入口保留可观察的回退原因。"""
        try:
            import av
            context = av.CodecContext.create("h264", "r")
            context.thread_count = 1
            context.thread_type = "SLICE"
            context.options = {"flags": "low_delay", "flags2": "+showall"}
            context.open()
        except Exception as exc:
            self.native_decoder_error = f"PyAV unavailable: {type(exc).__name__}: {exc}"
            return None
        self.native_decoder_error = ""
        return context

    def _input_payload(self, item: bytes | _TimedDecoderInput,
                       session: _DecoderSession) -> bytes | None:
        """限制待解码数据的停留时间；过期时撤销整段压缩状态。"""
        if not isinstance(item, _TimedDecoderInput):
            return item
        now = time.perf_counter()
        if (now - self.started_at > self.LEGACY_STARTUP_GRACE_S
                and now - item.queued_at > self.LEGACY_MAX_QUEUE_AGE_S):
            with self._lock:
                if self._session_current_locked(session):
                    self.input_chunks_dropped += 1 + session.input_queue.qsize()
            self._session_failed(session, "decoder input exceeded 50 ms; waiting for recovery")
            return None
        return item.payload

    def _native_decode_loop(self, session: _DecoderSession) -> None:
        """单个线程独占 parse/decode；只发布最新图像，不经子进程或 JPEG 中转。"""
        context = session.codec_context
        try:
            import av
            while not session.stopped.is_set():
                try:
                    item = session.input_queue.get(timeout=.05)
                except Empty:
                    continue
                if session.stopped.is_set():
                    return
                payload = self._input_payload(item, session)
                if payload is None:
                    return
                with self._lock:
                    if not self._session_current_locked(session):
                        return
                    self.input_chunks_written += 1
                    self.input_bytes_written += len(payload)
                try:
                    for packet in context.parse(payload):
                        if session.stopped.is_set():
                            return
                        for frame in context.decode(packet):
                            if session.stopped.is_set():
                                return
                            if frame.width > 0 and frame.height > 0:
                                self._publish_bgr(frame.to_ndarray(format="bgr24"), session)
                except av.error.InvalidDataError as exc:
                    # 与参考解码器一致，坏片段不终止接收；由后续参数集/刷新帧恢复。
                    with self._lock:
                        if self._session_current_locked(session):
                            self.last_error = f"H.264 decode error: {exc}"
        except Exception as exc:
            self._session_failed(session, f"native decoder failed: {type(exc).__name__}: {exc}")

    def _publish_bgr(self, bgr: Any, session: _DecoderSession | None = None) -> None:
        """最终发布点再次校验所有权，迟到的旧解码线程不能覆盖新画面。"""
        with self._lock:
            if session is not None and not self._session_current_locked(session):
                return
            self._latest = bgr
            self._latest_at = time.perf_counter()
            if self.first_frame_at <= 0.0:
                self.first_frame_at = self._latest_at
                self._decoded_window_started_at = self._latest_at
            if self._decoded_window_started_at > 0.0:
                self.continuous_decoded_seconds = max(
                    0.0, self._latest_at - self._decoded_window_started_at
                )
            h, w = bgr.shape[:2]
            self._frame_w, self._frame_h = w, h
            self.frames_decoded += 1
            self._process_frames_decoded += 1

    def _session_failed(self, session: _DecoderSession, message: str = "") -> None:
        with self._lock:
            if not self._session_current_locked(session):
                return
            self.available = False
            self._running = False
            session.stopped.set()
            self.last_exit_code = session.proc.poll() if session.proc is not None else None
            if message:
                self.last_error = message
            elif self.last_exit_code not in (None, 0) and not self.last_error:
                self.last_error = f"ffmpeg exited with code {self.last_exit_code}"

    def _run_session_worker(self, target: Callable[[_DecoderSession], None],
                            session: _DecoderSession, pipe_name: str) -> None:
        try:
            target(session)
        finally:
            # If OS I/O outlives the bounded stop deadline, its owner still
            # closes the captured handle when it eventually returns.
            pipe = getattr(session.proc, pipe_name, None)
            if pipe is not None:
                try:
                    close_resource(pipe)
                except Exception as exc:
                    session.close_error = f"Decoder pipe close unconfirmed: {type(exc).__name__}: {exc}"

    def _write_loop(self, session: _DecoderSession) -> None:
        proc = session.proc
        while not session.stopped.is_set():
            try:
                item = session.input_queue.get(timeout=0.10)
            except Empty:
                continue
            if session.stopped.is_set() or proc.stdin is None:
                break
            payload = self._input_payload(item, session)
            if payload is None:
                break
            try:
                # 无缓冲管道允许短写，必须补齐当前分片，不能静默截断 H.264 NAL。
                remaining = memoryview(payload)
                while remaining and not session.stopped.is_set():
                    written = proc.stdin.write(remaining)
                    if written is None or written <= 0:
                        raise OSError("decoder stdin made no write progress")
                    remaining = remaining[written:]
                if session.stopped.is_set():
                    break
                proc.stdin.flush()
                with self._lock:
                    if self._session_current_locked(session):
                        self.input_chunks_written += 1
                        self.input_bytes_written += len(payload)
            except Exception as exc:
                self._session_failed(session, str(exc))
                break

    def _read_loop(self, session: _DecoderSession) -> None:
        proc = session.proc
        buf = bytearray()
        while not session.stopped.is_set() and proc.stdout is not None:
            try:
                # os.read returns available bytes instead of waiting for a
                # full buffered read, preserving low-latency JPEG delivery.
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk or session.stopped.is_set():
                    break
                with self._lock:
                    if not self._session_current_locked(session):
                        return
                    self.output_bytes_read += len(chunk)
                buf.extend(chunk)
                consume_mjpeg_stream(buf, lambda frame: self._decode_frame(frame, session))
            except Exception as exc:
                self._session_failed(session, f"decoder reader failed: {type(exc).__name__}: {exc}")
                return
        self._session_failed(session)

    def _stderr_loop(self, session: _DecoderSession) -> None:
        proc = session.proc
        if proc.stderr is None:
            return
        while not session.stopped.is_set():
            try:
                chunk = os.read(proc.stderr.fileno(), 4096)
            except OSError:
                break
            if not chunk:
                break
            with self._lock:
                if not self._session_current_locked(session):
                    return
                self._stderr_chunks.append(chunk)
                self._stderr_bytes += len(chunk)
                while self._stderr_bytes > self.STDERR_LIMIT and self._stderr_chunks:
                    removed = self._stderr_chunks.popleft()
                    self._stderr_bytes -= len(removed)
                diagnostic = b"".join(self._stderr_chunks).decode("utf-8", "replace").strip()
                if diagnostic:
                    self.last_error = diagnostic[-self.STDERR_LIMIT:]

    def _decode_frame(self, frame: bytes, session: _DecoderSession | None = None) -> None:
        try:
            bgr = _decode_jpeg_bgr(frame)
            if bgr is None:
                return
            self._publish_bgr(bgr, session)
        except Exception as exc:
            with self._lock:
                if session is None or self._session_current_locked(session):
                    self.last_error = f"frame decode failed: {type(exc).__name__}: {exc}"

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

    def restart(self, *, clear_latest: bool = True,
                expected_generation: int | None = None) -> bool:
        """Restart on a worker; stop() invalidates even an in-flight spawn."""

        if not self._lifecycle_lock.acquire(blocking=False):
            return False
        try:
            now = time.perf_counter()
            with self._lock:
                generation = self._generation
                if self._stop_in_progress_locked():
                    return False
                if expected_generation is not None and expected_generation != generation:
                    return False
                if now < self._next_restart_at:
                    return False
                session = self._detach_session_locked(clear_latest=clear_latest)
                self.restart_count += 1
            self._close_retired_session(session)
            with self._lock:
                retired = tuple(self._retired_sessions)
            for owner in retired:
                self._close_retired_session(owner)
            # The start helper must not reacquire the lifecycle lock. A stop
            # during teardown/spawn advances the generation and wins.
            try:
                import cv2  # type: ignore  # noqa: F401
                import numpy  # type: ignore  # noqa: F401
            except Exception as exc:
                with self._lock:
                    if generation == self._generation:
                        self.dependency_error = f"video decode dependency unavailable: {type(exc).__name__}: {exc}"
                        self.last_error = self.dependency_error
                started = False
            else:
                started = self._start_generation(generation)
            with self._lock:
                if generation != self._generation:
                    return False
                if started:
                    self._restart_backoff_s = 0.5
                    self._next_restart_at = 0.0
                else:
                    self._next_restart_at = time.perf_counter() + self._restart_backoff_s
                    self._restart_backoff_s = min(5.0, self._restart_backoff_s * 2.0)
            return started
        finally:
            self._lifecycle_lock.release()

    def health(self, now: float | None = None) -> dict[str, Any]:
        current = time.perf_counter() if now is None else float(now)
        latest = self.latest_timestamp()
        return {
            "available": self.available,
            "backend": self.backend_name,
            "input_queue_limit": self.input_queue_limit,
            "max_queue_age_s": self.LEGACY_MAX_QUEUE_AGE_S if self.allow_h264_non_idr else None,
            "native_decoder_error": self.native_decoder_error,
            "dependency_error": self.dependency_error,
            "first_frame_timeout": bool(
                self._running and self._process_frames_decoded == 0
                and self.started_at > 0.0 and current - self.started_at > self.FIRST_FRAME_TIMEOUT_S
            ),
            "stale": bool(latest > 0.0 and current - latest > self.STALE_TIMEOUT_S),
            "exit_code": self.last_exit_code,
            "restart_count": self.restart_count,
            "first_frame_latency_s": (
                self.first_frame_at - self.started_at
                if self.first_frame_at > 0.0 and self.started_at > 0.0
                else None
            ),
            "stderr": self.stderr_tail(),
        }

    def stderr_tail(self) -> str:
        with self._lock:
            return b"".join(self._stderr_chunks).decode("utf-8", "replace")[-self.STDERR_LIMIT:]

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

    def _detach_session_locked(self, *, clear_latest: bool) -> _DecoderSession | None:
        session = self._session
        if session is not None:
            session.stopped.set()
            if not any(owner is session for owner in self._retired_sessions):
                self._retired_sessions.append(session)
        self._session = None
        self._proc = None
        self._running = False
        self.available = False
        self._writer = self._reader = self._stderr_reader = None
        # A new queue prevents an old blocked writer consuming new input.
        self._input_queue = Queue(maxsize=self.input_queue_limit)
        if clear_latest:
            self._latest = None
            self._latest_at = 0.0
            self._frame_w = self._frame_h = 0
            self.first_frame_at = 0.0
            self._process_frames_decoded = 0
            self._decoded_window_started_at = 0.0
            self.continuous_decoded_seconds = 0.0
        return session

    @staticmethod
    def _close_session(session: _DecoderSession | None, *,
                       worker_timeout: float | None = 1.0) -> bool:
        if session is None:
            return True
        with session.close_lock:
            if session.closed:
                return True
            session.stopped.set()
            proc = session.proc
            deadline = time.perf_counter() + 1.0
            if session.codec_context is not None:
                # CodecContext 只由解码线程使用；必须确认线程退出后才能释放原生状态。
                for worker in session.threads:
                    if worker is not threading.current_thread() and worker.is_alive():
                        worker.join(None if worker_timeout is None else max(0.0, deadline - time.perf_counter()))
                if any(worker.is_alive() for worker in session.threads):
                    session.close_error = "Native decoder worker still owns codec context"
                    return False
                session.codec_context = None
                session.close_error = ""
                session.closed = True
                return True
            try:
                proc.terminate()
            except Exception:
                # Already-exited processes may reject termination. Only the
                # final poll/reap confirmation decides whether ownership ends.
                pass
            try:
                proc.wait(timeout=max(0.0, deadline - time.perf_counter()))
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=0.2)
                except Exception:
                    pass
            for worker in session.threads:
                if worker is not threading.current_thread() and worker.is_alive():
                    wait = None if worker_timeout is None else max(0.0, deadline - time.perf_counter())
                    worker.join(timeout=wait)
            if any(worker.is_alive() for worker in session.threads):
                session.close_error = "Decoder workers still own process pipes"
                return False
            try:
                if proc.poll() is None:
                    session.close_error = "Decoder process exit unconfirmed"
                    return False
            except Exception as exc:
                session.close_error = f"Decoder process exit unconfirmed: {exc}"
                return False
            errors = []
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe is not None and getattr(pipe, "closed", None) is not True:
                    try:
                        close_resource(pipe)
                        if getattr(pipe, "closed", None) is False:
                            raise OSError("Decoder pipe remained open after close")
                    except Exception as exc:
                        errors.append(f"{type(exc).__name__}: {exc}")
            session.close_error = "; ".join(errors)
            session.closed = not errors
            return session.closed

    def _close_retired_session(self, session: _DecoderSession | None, *,
                               worker_timeout: float | None = 1.0) -> bool:
        if session is None:
            return True
        with self._lock:
            if not any(owner is session for owner in self._retired_sessions):
                self._retired_sessions.append(session)
        closed = self._close_session(session, worker_timeout=worker_timeout)
        with self._lock:
            if closed:
                self._retired_sessions = [owner for owner in self._retired_sessions if owner is not session]
            else:
                self.last_error = session.close_error or "Decoder resource close unconfirmed"
        return bool(closed)

    @property
    def stop_pending(self) -> bool:
        """Retained close or process-lifecycle work remains unconfirmed."""
        with self._lock:
            # A failed stop admission may leave an unpublished Popen behind
            # the lifecycle lock, before it can enter the retired inventory.
            return bool(self._retired_sessions or self._stop_in_progress_locked()
                        or self._lifecycle_lock.locked())

    @property
    def stop_status(self) -> VideoStopStatus:
        with self._lock:
            retired = tuple(self._retired_sessions)
            # This also observes a Popen not yet published into a session.
            inflight = self._stop_in_progress_locked() or self._lifecycle_lock.locked()
            # A retired data reader can require terminate() to unblock. Its
            # liveness retains ownership, but must not prevent admitting the
            # missing closer after a stop-worker admission failure.
            inflight = inflight or any(session.close_lock.locked() for session in retired)
            errors = tuple(session.close_error for session in retired if session.close_error)
            return VideoStopStatus(bool(retired or inflight), inflight, errors)

    @property
    def cleanup_complete(self) -> bool:
        with self._lock:
            return (self._session is None and not self._retired_sessions and not self._running
                    and not self._stop_in_progress_locked())

    def wait_closed(self) -> bool:
        """Worker/CLI only: observe in-flight startup and finish retained owners."""
        with self._lock:
            stopper = self._stop_worker
        if stopper is not None and stopper is not threading.current_thread():
            stopper.join()
        with self._lifecycle_lock:
            with self._lock:
                if self._session is not None:
                    return False
                retired = tuple(self._retired_sessions)
            for session in retired:
                self._close_retired_session(session, worker_timeout=None)
            return self.cleanup_complete

    def _stop_in_progress_locked(self) -> bool:
        return self._stop_worker is not None and self._stop_worker.is_alive()

    def request_stop(self, *, clear_latest: bool = True) -> None:
        """Invalidate now; one retained worker closes native owners off caller."""
        with self._lock:
            self._generation += 1
            self._detach_session_locked(clear_latest=clear_latest)
            if self._stop_in_progress_locked():
                return
            if not self._retired_sessions and not self._lifecycle_lock.locked():
                return  # No current, retained, or in-flight spawn owner to wait for.
            worker = threading.Thread(target=self._finish_requested_stop,
                                      name=f"mjpeg-stop-{self.codec}", daemon=True)
            self._stop_worker = worker
            try:
                worker.start()
            except Exception as exc:
                if worker.ident is None:
                    self._stop_worker = None
                self.last_error = f"Decoder stop worker failed: {type(exc).__name__}: {exc}"
                raise

    def _finish_requested_stop(self) -> None:
        # An unpublished Popen belongs to the lifecycle lock. Its generation
        # was invalidated above; wait for it to publish into retained ownership
        # before taking the final owner snapshot. Never join this worker while
        # holding that lock.
        with self._lifecycle_lock:
            with self._lock:
                retired = tuple(self._retired_sessions)
            for session in retired:
                self._close_retired_session(session, worker_timeout=None)

    def stop(self, *, clear_latest: bool = True) -> None:
        # Do not wait for the lifecycle lock: an in-progress restart might be
        # blocked in OS teardown. Its generation check prevents resurrection.
        with self._lock:
            self._generation += 1
            session = self._detach_session_locked(clear_latest=clear_latest)
        self._close_retired_session(session)
