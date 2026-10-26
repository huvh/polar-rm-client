"""UDP 图传编排：入口、分片、恢复、解码槽与接收端生命周期。"""
from __future__ import annotations

import struct
import subprocess
import threading
import time
from typing import Any, Callable

from ...transports import AnnexBDatagramStream, FrameAssembler, UDPVideoReceiver
from ..video_source import VideoSourceAdmission, VideoStopStatus
from .annexb import AnnexBRecoveryGate, iter_annexb_nal_units
from .codec import _decode_jpeg_bgr, detect_frame_codec, resolve_ffmpeg_executable
from .decoder import ContinuousMjpegDecoder
from .receiver import LegacyReceiverControl
from .receiver_protocol import CHANNEL_FREQUENCIES


class RmVideoBackend(UDPVideoReceiver):
    """SharkClient 风格 UDP 图传后端（含 codec 检测/MJPEG 解码/统计）。"""

    CONNECTION_STALE_S = 2.0

    def __init__(self, host: str = "127.0.0.1", port: int = 3334) -> None:
        super().__init__(host=host, port=port)
        self.ingress_mode = "shark-framed"
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
        self.ffmpeg_executable = resolve_ffmpeg_executable()
        self.ffmpeg_available: bool = self.ffmpeg_executable is not None
        # Always construct the decoder. Its start() re-resolves ffmpeg so a
        # bundled binary becoming available before runtime is picked up.
        self.h265_decoder: ContinuousMjpegDecoder | None = ContinuousMjpegDecoder("h265")
        # Legacy public names denote the single active Annex-B decoder slot.
        # H.264 and HEVC share its existing stop/retry/health ownership.
        self.h265_recovery = AnnexBRecoveryGate("h265")
        self._udp_sequence_discontinuities = 0
        self._started_at = 0.0
        self._frame_times: list[float] = []
        self._bytes_this_second = 0
        self._last_stats_at = 0.0
        self._lock = threading.Lock()
        self._video_generation = 0
        self._h265_generation = 0
        self._h265_restart_lock = threading.Lock()
        self._h265_restart_thread: threading.Thread | None = None
        self._h265_next_restart_at = 0.0
        self._h265_restart_backoff_s = 0.5
        self.h265_decoder_restarts = 0
        self.connection_restarts = 0
        self._connection_recovering = False
        self._connection_retry_at = 0.0
        self._connection_backoff_s = 0.5
        self.event_hook: Callable[..., None] | None = None
        # 单独使用 UDP 诊断器仍只监听；终端 BackendManager 显式启用接收端控制。
        self.legacy_control_enabled = False
        self.legacy_channel = 1
        self.legacy_control: LegacyReceiverControl | None = None

    def configure_legacy_receiver(self, channel: int) -> None:
        """设置接收信道；运行中的所有者由 poll_connection 撤销后重建。"""
        if isinstance(channel, bool) or not isinstance(channel, int) or channel not in CHANNEL_FREQUENCIES:
            raise ValueError("Legacy receiver channel must be 1..6")
        self.legacy_channel = channel

    def receiver_status(self) -> dict[str, Any]:
        """返回接收端值快照，调用方不获取串口所有者。"""
        control = self.legacy_control
        return dict(control.stats()) if control is not None else {}

    def configure_ingress(self, mode: str) -> None:
        """Select an explicit input contract only after the previous owner closes."""
        if mode not in {"shark-framed", "legacy-vt02-h264", "legacy-official-bridge"}:
            raise ValueError(f"Unsupported video ingress: {mode}")
        if mode == self.ingress_mode:
            return
        if self.running or not self.cleanup_complete:
            raise RuntimeError("Previous video owner must close before changing ingress")
        # 契约切换时重建已关闭的解码槽，避免旧图传的非 IDR 策略泄漏到其他视频源。
        decoder = ContinuousMjpegDecoder("h265")
        recovery = AnnexBRecoveryGate("h265")
        self.ingress_mode = mode
        self._h265_generation += 1
        self.h265_decoder = decoder
        self.h265_recovery = recovery

    def _create_assembler(self) -> FrameAssembler:
        return (AnnexBDatagramStream() if self.ingress_mode in {"legacy-vt02-h264", "legacy-official-bridge"}
                else FrameAssembler())

    def _bind_address(self) -> tuple[str, int]:
        # This is the exact observed official 2019 VT02 receive endpoint, not
        # the 2026 custom-client forwarding port and not a guessed USB API.
        if self.ingress_mode == "legacy-official-bridge":
            return "127.0.0.1", 18080
        return ("0.0.0.0", 8080) if self.ingress_mode == "legacy-vt02-h264" else super()._bind_address()

    def _emit_event(self, event: str, **payload: Any) -> None:
        hook = self.event_hook
        if hook is None:
            return
        try:
            hook(event, source=({"legacy-vt02-h264": "legacy_vt02_udp", "legacy-official-bridge": "legacy_official_bridge"}.get(self.ingress_mode, "udp_hevc")), **payload)
        except Exception:
            # Diagnostics must never delay or terminate the UDP worker.
            pass

    # ------------------------------------------------------------------
    def start(self) -> None:
        # A bind failure leaves UDPVideoReceiver.running false. Do not reset
        # counters/decoder state on every retry while an existing receiver is
        # already alive.
        if self.running or not self.cleanup_complete:
            return
        self._connection_recovering = False
        self.ffmpeg_executable = resolve_ffmpeg_executable()
        self.ffmpeg_available = self.ffmpeg_executable is not None
        self._started_at = time.perf_counter()
        self._last_stats_at = time.perf_counter()
        with self._lock:
            self._video_generation += 1
            self._h265_generation += 1
            generation = self._video_generation
            self.on_frame = lambda frame: self._on_assembled_frame(frame, generation)
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
            self.h265_recovery.reset()
            self.dropped_frames = 0
            self._h265_next_restart_at = 0.0
            self._h265_restart_backoff_s = 0.5
            self._assembler.clear()
            self._udp_sequence_discontinuities = 0
        # UDP 的 bind 在接收线程内完成。等 poll_connection 确认监听成功后
        # 再打开 COM，避免 8080 被占用时仍改变接收端配置。
        self.legacy_control = None
        super().start()

    def poll_connection(self) -> None:
        """Owner-thread maintenance for a selected, started UDP source only.

        A restarted bridge normally has a new ephemeral sender port. Never
        splice it into the old assembler: retire the entire receive/decode
        epoch first, then admit a fresh socket with bounded retry backoff.
        No socket close, process wait or thread join runs on this caller.
        Failed native cleanup stays retained for the existing explicit retry UI.
        """
        now = time.perf_counter()
        if (self.legacy_control is not None and self.running
                and self.legacy_control.channel != self.legacy_channel):
            self.request_stop()
            self._connection_recovering = True
            self._connection_retry_at = now
            return
        status = self.stop_status
        if status.errors:
            return
        if self._connection_recovering:
            if status.pending or not self.cleanup_complete or now < self._connection_retry_at:
                return
            self.request_decode_enabled(True)
            self.start()
            if self.running:
                self.connection_restarts += 1
                self._emit_event("connection_restart", count=self.connection_restarts)
            return
        if status.pending:
            return
        ingress = self.ingress_stats()
        if (self.running and ingress["listening"] and self.legacy_control is None
                and self.ingress_mode == "legacy-vt02-h264" and self.legacy_control_enabled):
            self.legacy_control = LegacyReceiverControl(self.legacy_channel)
            try:
                self.legacy_control.start()
            except Exception:
                self.request_stop()
                raise
        last_packet = float(ingress["accepted_fragment_at"])
        if self.running:
            if last_packet <= 0.0 or now - last_packet <= self.CONNECTION_STALE_S:
                if last_packet > 0.0:
                    self._connection_backoff_s = 0.5
                return
            reason = "accepted video traffic timed out; retire sender epoch"
        else:
            if now < self._connection_retry_at:
                return
            reason = "receive worker exited; retry selected source"
        self.request_stop()
        self._connection_recovering = True
        self._connection_retry_at = now + self._connection_backoff_s
        self._connection_backoff_s = min(5.0, self._connection_backoff_s * 2.0)
        self._emit_event("connection_lost", reason=reason)

    def _on_assembled_frame(self, frame: bytes, generation: int | None = None) -> None:
        now = time.perf_counter()
        # Raw legacy datagrams may split even a NAL start code. Never run the
        # framed-stream heuristic on them or discard continuation bytes.
        codec = "h264" if self.ingress_mode in {"legacy-vt02-h264", "legacy-official-bridge"} else detect_frame_codec(frame)
        validated_mjpeg = None
        validation_epoch = None
        if codec == "mjpeg":
            with self._lock:
                if generation is not None and generation != self._video_generation:
                    return
                previous_codec = self.codec
                if previous_codec in {"h264", "h265"}:
                    validation_epoch = (self._video_generation, self._h265_generation)
            if validation_epoch is not None:
                # Shark envelopes delimit transport blocks, not necessarily
                # whole Annex-B NALs. Compressed slice bytes can contain FF D8
                # at either recognized JPEG offset. Retire an established
                # codec only for a self-contained, decodable JPEG image.
                payload = frame if frame.startswith(b"\xff\xd8") else frame[4:]
                if b"\xff\xd9" in payload[2:]:
                    try:
                        validated_mjpeg = _decode_jpeg_bgr(payload)
                    except Exception:
                        pass
                if validated_mjpeg is None:
                    # Preserve every original byte, including a coincidental
                    # four-byte envelope, for the active Annex-B decoder.
                    codec = previous_codec
                # An in-band block that itself is a valid JPEG is inherently
                # ambiguous; the supported complete-MJPEG transition wins.
        with self._lock:
            if generation is not None and generation != self._video_generation:
                return
            if validation_epoch is not None and validation_epoch != (
                self._video_generation, self._h265_generation
            ):
                return
            discontinuities = self._assembler.sequence_discontinuities
            if discontinuities != self._udp_sequence_discontinuities:
                self._udp_sequence_discontinuities = discontinuities
                self.h265_recovery.reset()
            if codec == "h265" and self.codec == "h264":
                # 0x41/0x01 can mean H.264 non-IDR or layered HEVC VPS.
                # Keep an established H.264 stream on its non-IDR slices;
                # ordinary HEVC parameter sets still identify a codec switch.
                units = iter_annexb_nal_units(frame)
                if units and (units[0][1][0] & 0x1F) == 1:
                    codec = "h264"
            # Parameter sets need not accompany every transport frame. Once
            # selected, retain the Annex-B codec for unclassified continuation.
            if codec == "unknown" and self.codec in {"h264", "h265"}:
                codec = self.codec
            if codec != self.codec and self.codec in {"h264", "h265", "mjpeg"}:
                self._h265_generation += 1
                self.h265_recovery.reset()
                self.latest_bgr = None
                self.latest_bgr_at = 0.0
                self.decoder_backend = "none"
                if self.h265_decoder is not None:
                    try:
                        self.h265_decoder.request_stop()
                    except Exception as exc:
                        self.last_error = f"Codec retirement failed: {type(exc).__name__}: {exc}"
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
            mjpeg_epoch = (self._video_generation, self._h265_generation) if codec == "mjpeg" else None
        # 解码不持有状态锁，避免阻塞 stats()；同步 JPEG 解码仍占用当前回调线程。
        if codec == "mjpeg":
            self._decode_mjpeg(
                frame, generation, decoded_bgr=validated_mjpeg, expected_epoch=mjpeg_epoch,
            )
        elif codec in {"h264", "h265"}:
            with self._lock:
                if generation is not None and generation != self._video_generation:
                    return
                if self.codec != codec:
                    return
                self.latest_h265 = frame
                decoder = self.h265_decoder if self.decode_h265 else None
                if decoder is not None and getattr(decoder, "codec", "h265") != codec:
                    decoder = self._select_annexb_decoder(codec)
                decoder_generation = getattr(decoder, "lifecycle_generation", None)
            if decoder is not None:
                # Preserve lazy first-block startup, including a one-GOP source.
                # start() never tears down a failed incarnation; subsequent
                # recovery always belongs to the dedicated worker below.
                if not decoder.available and decoder.restart_count == 0 and not decoder.last_error:
                    decoder.start(expected_generation=decoder_generation)
                # Process teardown/recovery always runs outside the receiver.
                # Gate state is serialized with reset at lifecycle boundaries.
                with self._lock:
                    if generation is not None and generation != self._video_generation:
                        return
                    if not self.decode_h265 or decoder is not self.h265_decoder or self.codec != codec:
                        return
                    if decoder.available:
                        payload = self.h265_recovery.feed(frame)
                        queued = payload is not None and decoder.write(payload)
                        self.decoder_backend = getattr(decoder, "backend_name", "ffmpeg-mjpeg")
                        if payload is not None and not queued:
                            self.dropped_frames += 1
                            self.h265_recovery.reset()
                    else:
                        self.h265_recovery.reset()
                if not decoder.available:
                    self._request_h265_restart(generation=generation)
        if self.external_on_frame is not None:
            try:
                self.external_on_frame(frame)
            except Exception:
                pass

    def _select_annexb_decoder(self, codec: str) -> ContinuousMjpegDecoder | None:
        """Under _lock, retire the old codec without blocking the UDP caller.

        Blocks arriving during retirement are dropped. The next incarnation
        requires repeated parameters/keyframe; never replay a stale GOP.
        """
        decoder = self.h265_decoder
        if decoder is not None:
            try:
                decoder.request_stop()
            except Exception as exc:
                self.last_error = f"Codec retirement failed: {type(exc).__name__}: {exc}"
                return None
            recovery = self._h265_restart_thread
            if (not decoder.cleanup_complete or decoder.stop_status.pending
                    or (recovery is not None and recovery.is_alive())):
                return None
        try:
            legacy = self.ingress_mode in {"legacy-vt02-h264", "legacy-official-bridge"}
            replacement = ContinuousMjpegDecoder(codec, allow_h264_non_idr=legacy)
            recovery_gate = AnnexBRecoveryGate(codec, allow_h264_non_idr=legacy)
        except Exception as exc:
            self.last_error = f"Codec admission failed: {type(exc).__name__}: {exc}"
            return None
        self._h265_generation += 1
        self.h265_decoder = replacement
        self.h265_recovery = recovery_gate
        self._h265_next_restart_at = 0.0
        self._h265_restart_backoff_s = 0.5
        return self.h265_decoder

    def _decode_mjpeg(
        self, frame: bytes, generation: int | None = None, *, decoded_bgr: Any = None,
        expected_epoch: tuple[int, int] | None = None,
    ) -> None:
        try:
            # Match only the exact optional envelope already recognized by
            # detect_frame_codec; raw SOI takes precedence over a prefix.
            payload = frame
            if not frame.startswith(b"\xff\xd8") and frame[4:6] == b"\xff\xd8":
                payload = frame[4:]
            # A codec-switch candidate was already decoded outside the state
            # lock. Reuse that image rather than doing the native work twice.
            bgr = decoded_bgr if decoded_bgr is not None else _decode_jpeg_bgr(payload)
            if bgr is not None:
                h, w = bgr.shape[:2]
                with self._lock:
                    if generation is not None and generation != self._video_generation:
                        return
                    if expected_epoch is not None and expected_epoch != (
                        self._video_generation, self._h265_generation
                    ):
                        return
                    if self.codec not in {"unknown", "mjpeg"}:
                        return
                    self.latest_bgr = bgr
                    self.latest_bgr_at = time.perf_counter()
                    self.mjpeg_decoded_frames += 1
                    self.decoder_backend = "cv2"
                    self.output_width, self.output_height = w, h
        except Exception:
            with self._lock:
                if ((generation is None or generation == self._video_generation)
                        and (expected_epoch is None or expected_epoch == (
                            self._video_generation, self._h265_generation))):
                    self.decoder_backend = "none"

    def _ffmpeg_decode_hevc(self, frame: bytes) -> Any:
        """用系统 ffmpeg 把单帧 HEVC 解成 BGR24 ndarray；失败返回 None。"""
        try:
            proc = subprocess.run(
                [
                    self.ffmpeg_executable or "ffmpeg", "-v", "error", "-f", "hevc", "-i", "pipe:0",
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

    def _annexb_observation_owner(self) -> tuple[Any, tuple[int, int, Any]]:
        """Capture ownership before querying a decoder outside the backend lock."""
        with self._lock:
            decoder = self.h265_decoder
            epoch = (self._video_generation, self._h265_generation,
                     getattr(decoder, "lifecycle_generation", None))
            return decoder, epoch

    def _annexb_observation_current(self, decoder: Any, epoch: tuple[int, int, Any]) -> bool:
        """Called under _lock: stop, disable, codec change and restart revoke reads."""
        return bool(
            decoder is not None and decoder is self.h265_decoder
            and epoch == (self._video_generation, self._h265_generation,
                          getattr(decoder, "lifecycle_generation", None))
            and self.decode_h265 and decoder.available
            and self.codec in {"unknown", getattr(decoder, "codec", "h265")}
        )

    def latest_video_frame(self, timeout_s: float = 0.5) -> tuple[Any, float]:
        """Return a fresh frame only if its decoder still owns this observation."""
        deadline_age = max(0.0, float(timeout_s))
        decoder, epoch = self._annexb_observation_owner()
        h265_frame, h265_at = (decoder.latest_with_timestamp(deadline_age)
                              if decoder is not None else (None, 0.0))
        with self._lock:
            now = time.perf_counter()
            if (not self._annexb_observation_current(decoder, epoch)
                    or h265_at <= 0.0 or not 0.0 <= now - h265_at <= deadline_age):
                h265_frame, h265_at = None, 0.0
            mjpeg_frame, mjpeg_at = self.latest_bgr, float(self.latest_bgr_at)
            if mjpeg_frame is None or mjpeg_at <= 0.0 or not 0.0 <= now - mjpeg_at <= deadline_age:
                mjpeg_frame, mjpeg_at = None, 0.0
            if h265_frame is not None and h265_at >= mjpeg_at:
                return h265_frame, h265_at
            if mjpeg_frame is not None:
                return mjpeg_frame, mjpeg_at
            return None, 0.0

    def clear_stale_decoded_frame(self, timeout_s: float = 0.5) -> bool:
        """Release stale decoded images so callers cannot render a frozen feed."""

        cutoff = max(0.0, float(timeout_s))
        now = time.perf_counter()
        cleared = False
        with self._lock:
            if self.latest_bgr_at > 0.0 and now - self.latest_bgr_at > cutoff:
                self.latest_bgr = None
                self.latest_bgr_at = 0.0
                cleared = True
        # Keep the decoder timestamp until the 2 s health monitor observes it
        # and performs an SPS/keyframe-gated restart. UI callers already reject
        # it by age, so retaining this one frame cannot cause a visual freeze.
        return cleared

    def decoded_frame_fresh(self, timeout_s: float = 2.0) -> bool:
        """Cheap HUD connectivity probe without building the full stats tree."""

        decoder, epoch = self._annexb_observation_owner()
        h265_at = decoder.latest_timestamp() if decoder is not None else 0.0
        with self._lock:
            if not self._annexb_observation_current(decoder, epoch):
                h265_at = 0.0
            decoded_at = max(float(self.latest_bgr_at), float(h265_at))
            return bool(
                decoded_at > 0.0
                and time.perf_counter() - decoded_at <= max(0.0, float(timeout_s))
            )

    def _request_h265_restart(self, *, generation: int | None = None) -> None:
        # This lock only protects scheduling, never process teardown or joins.
        with self._h265_restart_lock:
            if self._h265_restart_thread is not None and self._h265_restart_thread.is_alive():
                return
            with self._lock:
                decoder = self.h265_decoder
                now = time.perf_counter()
                if (
                    decoder is None or not self.running or not self.decode_h265
                    or self.codec not in {"unknown", getattr(decoder, "codec", "h265")}
                    or now < self._h265_next_restart_at
                    or (generation is not None and generation != self._video_generation)
                ):
                    return
                epoch = self._h265_generation
                decoder_generation = getattr(decoder, "lifecycle_generation", None)
                self.h265_recovery.reset()
                self._h265_next_restart_at = now + self._h265_restart_backoff_s

            def restart_worker() -> None:
                try:
                    restarted = decoder.restart(clear_latest=True, expected_generation=decoder_generation)
                except Exception:
                    restarted = False
                with self._lock:
                    if epoch != self._h265_generation or not self.running or not self.decode_h265:
                        return
                    self.h265_recovery.reset()
                    if restarted:
                        self.h265_decoder_restarts += 1
                        self.decoder_backend = getattr(decoder, "backend_name", "ffmpeg-mjpeg")
                        self._h265_restart_backoff_s = 0.5
                    else:
                        self._h265_restart_backoff_s = min(5.0, self._h265_restart_backoff_s * 2.0)
                    self._h265_next_restart_at = time.perf_counter() + self._h265_restart_backoff_s
                    restart_count = self.h265_decoder_restarts
                    backoff = self._h265_restart_backoff_s
                self._emit_event(
                    "decoder_restart", restarted=restarted, restart_count=restart_count,
                    backoff_s=backoff, health=(decoder.health() if hasattr(decoder, "health") else {}),
                )

            worker = threading.Thread(target=restart_worker, name="h265-decoder-restart", daemon=True)
            self._h265_restart_thread = worker
            try:
                worker.start()
            except Exception as exc:
                # A real thread that already started (even if it finished)
                # remains a joinable owner. Never-admitted objects do not.
                if worker.ident is None:
                    self._h265_restart_thread = None
                with self._lock:
                    self.last_error = f"HEVC recovery admission failed: {type(exc).__name__}: {exc}"
                    self._h265_next_restart_at = time.perf_counter() + self._h265_restart_backoff_s
                    self._h265_restart_backoff_s = min(5.0, self._h265_restart_backoff_s * 2.0)
                raise

    def request_stop(self) -> None:
        """Revoke all packet/decode state before independent close admissions."""
        self._connection_recovering = False
        with self._lock:
            self._video_generation += 1
            self._h265_generation += 1
            self.decode_h265 = False
            self.latest_bgr = None
            self.latest_bgr_at = 0.0
            self.last_frame_at = 0.0
        admission = VideoSourceAdmission()
        if self.legacy_control is not None:
            admission.attempt("Legacy receiver stop", self.legacy_control.request_stop)
        admission.attempt("HEVC recovery reset", self.h265_recovery.reset)
        admission.attempt("UDP stop", super().request_stop)
        if self.h265_decoder is not None:
            admission.attempt("HEVC stop", self.h265_decoder.request_stop)
        admission.raise_if_failed()

    @property
    def stop_pending(self) -> bool:
        return (super().stop_pending
                or (self.h265_decoder is not None and self.h265_decoder.stop_pending)
                or (self.legacy_control is not None and self.legacy_control.stop_pending))

    @property
    def stop_status(self) -> VideoStopStatus:
        udp = super().stop_status
        decoder = self.h265_decoder.stop_status if self.h265_decoder is not None else VideoStopStatus()
        recovery = self._h265_restart_thread
        inflight = udp.inflight or decoder.inflight or (recovery is not None and recovery.is_alive())
        control = self.legacy_control
        control_pending = control is not None and control.stop_pending
        inflight = inflight or control_pending
        errors = tuple(f"UDP: {error}" for error in udp.errors) + tuple(
            f"HEVC: {error}" for error in decoder.errors)
        if control is not None and control.stats()["close_error"]:
            errors += (f"Legacy receiver: {control.stats()['close_error']}",)
        return VideoStopStatus(bool(udp.pending or decoder.pending or inflight or errors), inflight, errors)

    def stop(self) -> None:
        self._connection_recovering = False
        with self._lock:
            self._video_generation += 1
            self._h265_generation += 1
            self.latest_bgr = None
            self.latest_bgr_at = 0.0
            self.last_frame_at = 0.0
        # Stop packet production before detaching decoder pipes. No restart
        # lock is held while waiting; stop invalidates the decoder generation.
        if self.legacy_control is not None:
            self.legacy_control.stop()
        super().stop()
        if self.h265_decoder is not None:
            self.h265_decoder.stop()
        with self._lock:
            self.h265_recovery.reset()

    @property
    def cleanup_complete(self) -> bool:
        return (super().cleanup_complete
                and (self.h265_decoder is None or self.h265_decoder.cleanup_complete)
                and (self.legacy_control is None or self.legacy_control.cleanup_complete))

    def wait_closed(self, timeout: float | None = None) -> bool:
        super().wait_closed(timeout)
        control_closed = self.legacy_control is None or self.legacy_control.wait_closed(timeout)
        decoder_closed = self.h265_decoder is None or self.h265_decoder.wait_closed()
        if not decoder_closed:
            self.last_error = self.h265_decoder.last_error or "HEVC decoder close unconfirmed"
        return super().cleanup_complete and decoder_closed and control_closed

    def set_decode_enabled(self, enabled: bool) -> None:
        """Synchronous compatibility: select HEVC and close disabled native state."""
        self._set_decode_enabled(enabled, wait=True)

    def request_decode_enabled(self, enabled: bool) -> None:
        """UI-safe HEVC selection; disabling admits native close off-thread."""
        self._set_decode_enabled(enabled, wait=False)

    def _set_decode_enabled(self, enabled: bool, *, wait: bool) -> None:
        enabled = bool(enabled)
        with self._lock:
            if enabled == self.decode_h265:
                return
            self.decode_h265 = enabled
            self._h265_generation += 1
            self.h265_recovery.reset()
        if not enabled and self.h265_decoder is not None:
            if wait:
                self.h265_decoder.stop()
            else:
                self.h265_decoder.request_stop()

    def stats(self) -> dict[str, Any]:
        decoder, epoch = self._annexb_observation_owner()
        h265_at = decoder.latest_timestamp() if decoder is not None else 0.0
        h265_frames = decoder.frames_decoded if decoder is not None else 0
        decoded_size = decoder.frame_size() if decoder is not None and h265_at > 0.0 else (0, 0)
        with self._lock:
            if not self._annexb_observation_current(decoder, epoch):
                h265_at, decoded_size = 0.0, (0, 0)
            ingress = self.ingress_stats()
            bind_host, bind_port = self._bind_address()
            decoded_at = max(float(self.latest_bgr_at), float(h265_at))
            decoded_connected = bool(
                decoded_at > 0.0 and time.perf_counter() - decoded_at <= 2.0
            )
            connected = (
                (self.frames_received > 0 or int(ingress["stream_blocks_received"]) > 0)
                and self.last_frame_at > 0
                and time.perf_counter() - self.last_frame_at <= 2.0
            )
            return {
                "ingress": ingress,
                "ingress_mode": self.ingress_mode,
                "legacy_receiver": self.legacy_control.stats() if self.legacy_control is not None else None,
                "hardware_verified": False,
                "connected": connected,
                "connection_restarts": self.connection_restarts,
                "connection_recovering": self._connection_recovering,
                "host": bind_host,
                "port": bind_port,
                "packets_received": self.packets_received,
                "frames_received": self.frames_received,
                "dropped_frames": self.dropped_frames + self._assembler.dropped_count,
                "invalid_fragments": self._assembler.invalid_count,
                "stale_fragments": self._assembler.stale_packet_count,
                "sequence_discontinuities": self._assembler.sequence_discontinuities,
                "codec": self.codec,
                "fps": round(self.fps, 1) if self.ingress_mode == "shark-framed" else 0.0,
                "raw_blocks_per_second": (round(self.fps, 1)
                                          if self.ingress_mode in {"legacy-vt02-h264", "legacy-official-bridge"} else 0.0),
                "bitrate": round(self.bitrate, 1),
                "decoder_backend": self.decoder_backend,
                "output_width": (decoded_size[0] if self.codec in {"h264", "h265"}
                                 else self.output_width) if decoded_connected else 0,
                "output_height": (decoded_size[1] if self.codec in {"h264", "h265"}
                                  else self.output_height) if decoded_connected else 0,
                "decoded_connected": decoded_connected,
                "decoded_frames": self.mjpeg_decoded_frames + h265_frames,
                "continuous_decoded_seconds": (
                    self.h265_decoder.continuous_decoded_seconds
                    if self.h265_decoder and self.codec in {"h264", "h265"}
                    else max(0.0, decoded_at - self._started_at) if decoded_at > 0.0 else 0.0
                ),
                "decoded_frame_at": decoded_at,
                "h265_decoder_ready": bool(self.h265_decoder and self.h265_decoder.available),
                "h265_decoded_frames": h265_frames,
                "h265_input_queue": self.h265_decoder.input_queue_depth() if self.h265_decoder else 0,
                "h265_input_dropped": self.h265_decoder.input_chunks_dropped if self.h265_decoder else 0,
                "h265_decoder_restarts": self.h265_decoder_restarts,
                "h265_recovery_blocked": self.h265_recovery.blocked,
                "h265_decoder_health": self.h265_decoder.health() if self.h265_decoder else {},
                "decoder_codec": getattr(self.h265_decoder, "codec", "unknown"),
                "decoder_error": self.h265_decoder.last_error if self.h265_decoder else "",
                "last_error": self.last_error,
            }
