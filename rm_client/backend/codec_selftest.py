"""Bundled decoder self-test using one GOP per supported codec."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .video_backend import ContinuousMjpegDecoder, resolve_ffmpeg_executable
from ..runtime_paths import RuntimePaths


SELFTEST_STREAMS = {
    "h264": "h264_one_gop.h264",
    "h265": "hevc_one_gop.hevc",
}


@dataclass(frozen=True, slots=True)
class CodecSelfTestResult:
    codec: str
    passed: bool
    first_frame_s: float
    frames: int
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "codec": self.codec,
            "passed": self.passed,
            "first_frame_s": self.first_frame_s,
            "frames": self.frames,
            "detail": self.detail,
        }


def run_codec_selftest(codec: str, *, timeout_s: float = 3.0) -> CodecSelfTestResult:
    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        return CodecSelfTestResult(codec, False, 0.0, 0, "ffmpeg unavailable")
    normal = "h265" if str(codec).lower() in {"h265", "hevc"} else "h264"
    try:
        fixture = RuntimePaths.discover().asset("selftest", SELFTEST_STREAMS[normal])
        if not fixture.is_file():
            return CodecSelfTestResult(normal, False, 0.0, 0, f"bundled GOP missing: {fixture}")
        stream = fixture.read_bytes()
        if len(stream) < 1024:
            return CodecSelfTestResult(normal, False, 0.0, 0, "bundled GOP is empty/truncated")
        decoder = ContinuousMjpegDecoder(normal)
        if not decoder.start():
            return CodecSelfTestResult(normal, False, 0.0, 0, decoder.last_error)
        started = time.perf_counter()
        for offset in range(0, len(stream), 1200):
            chunk = stream[offset:offset + 1200]
            queue_deadline = time.perf_counter() + 0.1
            while not decoder.write(chunk) and time.perf_counter() < queue_deadline:
                time.sleep(0.001)
        deadline = started + timeout_s
        while time.perf_counter() < deadline and decoder.frames_decoded == 0:
            time.sleep(0.01)
        latency = max(0.0, decoder.first_frame_at - started) if decoder.first_frame_at else 0.0
        frames = decoder.frames_decoded
        detail = decoder.last_error
        still_open = decoder.available
        decoder.stop()
        return CodecSelfTestResult(
            normal,
            bool(frames > 0 and latency < timeout_s and still_open),
            latency,
            frames,
            detail,
        )
    except Exception as exc:
        return CodecSelfTestResult(normal, False, 0.0, 0, f"{type(exc).__name__}: {exc}")


def run_all_codec_selftests() -> tuple[CodecSelfTestResult, CodecSelfTestResult]:
    return run_codec_selftest("h264"), run_codec_selftest("h265")
