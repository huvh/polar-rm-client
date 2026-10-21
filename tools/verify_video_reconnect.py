"""Explicit loopback UDP + real FFmpeg restart probe, no physical devices.

Keeps decoder stdin open. Interrupts the sender, waits for stale-frame removal
and receive-epoch retirement, then resumes from a different sender port/frame 0.
Does not certify hardware, referee interoperability or robot control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(out: Path) -> dict:
    from rm_client.backend.video_backend import RmVideoBackend, resolve_ffmpeg_executable
    executable = resolve_ffmpeg_executable()
    if not executable:
        raise RuntimeError('FFmpeg is required; explicitly pass --ffmpeg or configure POLAR_FFMPEG')
    out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'real FFmpeg and loopback UDP only; NOT physical receiver/match qualification',
              'ffmpeg_sha256': hashlib.sha256(Path(executable).read_bytes()).hexdigest(), 'cases': []}
    for codec, filename in [('h264', 'h264_one_gop.h264'), ('h265', 'hevc_one_gop.hevc')]:
        stream = (ROOT / 'assets/selftest' / filename).read_bytes()
        receiver = RmVideoBackend(port=0)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.bind(('127.0.0.1', 0))
        result = {'codec': codec, 'fixture_sha256': hashlib.sha256(stream).hexdigest()}

        def until(predicate, seconds):
            deadline = time.perf_counter() + seconds
            while not predicate():
                if time.perf_counter() > deadline:
                    raise TimeoutError(json.dumps(receiver.stats(), default=str))
                receiver.poll_connection()
                time.sleep(.005)

        def decode(start_id):
            began, next_send, frame = time.perf_counter(), 0., start_id
            deadline = began + 3
            while receiver.latest_video_frame()[0] is None:
                now = time.perf_counter()
                if now > deadline:
                    raise TimeoutError(json.dumps(receiver.stats(), default=str))
                receiver.poll_connection()
                if now >= next_send:
                    for index, offset in enumerate(range(0, len(stream), 1200)):
                        sender.sendto(struct.pack('>HHI', frame & 65535, index, len(stream)) + stream[offset:offset+1200], address)
                    frame += 1
                    next_send = now + .2
                time.sleep(.005)
            return time.perf_counter() - began

        try:
            receiver.start()
            until(lambda: receiver.ingress_stats()['listening'], 2)
            address = receiver.ingress_stats()['bound_address']
            receiver.port = address[1]  # Keep the configured receive port across epochs.
            result['first_frame_s'] = decode(500)
            old_sender = sender.getsockname()
            sender.close()
            until(lambda: receiver.connection_restarts >= 1 and receiver.ingress_stats()['listening'], 5)
            assert receiver.ingress_stats()['bound_address'] == address
            assert receiver.latest_video_frame()[0] is None, 'Old decoded frame survived reconnect'
            assert receiver.ingress_stats()['sender_address'] is None
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sender.bind(('127.0.0.1', 0))
            assert sender.getsockname() != old_sender
            result['resume_frame_s'] = decode(0)
            result['new_sender_selected'] = receiver.ingress_stats()['sender_address'] == sender.getsockname()
            result['decoder_stdin_still_open'] = bool(receiver.h265_decoder.available)
            assert result['new_sender_selected'] and result['decoder_stdin_still_open']
            result['connection_restarts'] = receiver.connection_restarts
            result['status'] = 'PASS'
        finally:
            sender.close()
            receiver.stop()
            result['cleanup_complete'] = receiver.wait_closed(3)
            report['cases'].append(result)
            (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        assert result['cleanup_complete'], 'Receive/decode owner leaked'
    report['status'] = 'PASS'
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, help='Explicit local executable, never downloaded')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.ffmpeg is not None:
        os.environ['POLAR_FFMPEG'] = str(args.ffmpeg.resolve(strict=True))
    print(json.dumps(run(args.out), indent=2))
