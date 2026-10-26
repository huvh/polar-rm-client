"""同一条本地 720p60 码流对比旧 JPEG 中转与直接 BGR；不测量无线或屏幕延迟。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rm_client.backend.video import ContinuousMjpegDecoder, resolve_ffmpeg_executable
from rm_client.backend.video.annexb import iter_annexb_nal_units


def measure(stream: list[bytes], direct_bgr: bool) -> dict:
    sent_at, latency = [], []

    class MeasuredDecoder(ContinuousMjpegDecoder):
        def _publish_bgr(self, frame, session=None):
            before = self.frames_decoded
            super()._publish_bgr(frame, session)
            if self.frames_decoded > before:
                latency.append((time.perf_counter() - sent_at[before]) * 1000)

    decoder = MeasuredDecoder("h264", allow_h264_non_idr=True)
    # 基线保留原有单线程/low_delay 参数，只恢复 JPEG 中转与原队列容量。
    decoder.prefer_native = direct_bgr
    decoder.input_queue_limit = (decoder.LEGACY_INPUT_QUEUE_CHUNKS if direct_bgr
                                 else decoder.INPUT_QUEUE_CHUNKS)
    try:
        if not decoder.start():
            raise RuntimeError(decoder.last_error)
        if direct_bgr and decoder.backend_name != "pyav-bgr":
            raise RuntimeError(decoder.native_decoder_error)
        began = time.perf_counter()
        for index, frame in enumerate(stream):
            remaining = began + index / 60 - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            sent_at.append(time.perf_counter())
            if not decoder.write(frame):
                raise RuntimeError(decoder.last_error)
        # Annex-B parser 的最后一帧需要后续边界；保持 stdin 打开，不用 EOF 冒充低延迟。
        deadline = time.perf_counter() + 1
        while len(latency) < len(stream) - 1 and time.perf_counter() < deadline:
            time.sleep(.005)
        if len(latency) < len(stream) - 2:
            raise RuntimeError(f"Insufficient frames: {len(latency)}/{len(stream)}: {decoder.last_error}")
        steady = sorted(latency[15:])
        if not steady:
            raise RuntimeError("Insufficient steady-state samples")
        return {
            "backend": decoder.backend_name,
            "frames_sent": len(stream), "frames_decoded": len(latency),
            "first_frame_ms": round(latency[0], 2),
            "steady_median_ms": round(statistics.median(steady), 2),
            "steady_p95_ms": round(steady[int((len(steady) - 1) * .95)], 2),
            "input_dropped": decoder.input_chunks_dropped,
            "pipe_output_bytes": decoder.output_bytes_read,
        }
    finally:
        decoder.stop()
        if not decoder.wait_closed():
            raise RuntimeError("Decoder cleanup unconfirmed")


def run(frames: int) -> dict:
    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("Local FFmpeg missing")
    with tempfile.TemporaryDirectory(prefix="polar-video-latency-") as directory:
        path = Path(directory) / "sample.h264"
        subprocess.run([
            ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60",
            "-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast",
            "-tune", "zerolatency", "-threads", "1", "-bf", "0",
            "-x264-params", "aud=1:keyint=60:repeat-headers=1", "-f", "h264", str(path),
        ], check=True, capture_output=True, timeout=45)
        data = path.read_bytes()
    starts = [offset for offset, payload in iter_annexb_nal_units(data) if payload[0] & 31 == 9]
    starts.append(len(data))
    stream = [data[start:end] for start, end in zip(starts, starts[1:])]
    return {
        "scope": "Local H.264 input to BGR publication, 1280x720@60; excludes RF, capture and display",
        "baseline": measure(stream, False), "optimized": measure(stream, True),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.frames < 30:
        parser.error("--frames must be at least 30")
    report = run(args.frames)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
