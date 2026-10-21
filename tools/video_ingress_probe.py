"""Bounded receive-only evidence for the explicit framed or legacy raw UDP video ingress.

This tool does not configure receivers, launch the official client, transmit
packets, capture screens or substitute a bundled sample. It deliberately cannot
certify a legacy receiver merely because arbitrary network video decodes.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.video_backend import RmVideoBackend


def positive_duration(value: str) -> float:
    duration = float(value)
    if not math.isfinite(duration) or not 0.1 <= duration <= 300.0:
        raise argparse.ArgumentTypeError("duration must be between 0.1 and 300 seconds")
    return duration


def local_ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError("bind host must be a numeric local IPv4 address") from exc


def udp_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def summarize(stats: dict, *, observed: dict, cleanup_complete: bool) -> dict:
    """Pure report projection; no stage can imply a genuine receiver identity."""
    ingress = stats.get("ingress", {})
    fresh = bool(stats.get("decoded_connected", False))
    if fresh:
        stage = "fresh_decoded_video"
    elif observed["decoded"]:
        stage = "decoded_video_became_stale"
    elif observed.get("stream", False):
        stage = "raw_stream_but_not_decoded"
    elif observed["assembled"]:
        stage = "assembled_but_not_decoded"
    elif observed["packets"]:
        stage = "packets_but_no_complete_frame"
    elif observed["listening"]:
        stage = "listening_without_packets"
    else:
        stage = "listener_not_started"
    return {
        "schema": "polar-video-ingress-probe-v1",
        "transport": stats.get("ingress_mode", "shark-framed"),
        "stage": stage,
        "hardware_verified": False,
        "receiver_identity": "unverified",
        "official_client_required": (
            "For the documented official 2026 forwarding path, the official client "
            "must already show video and both clients must select the same robot ID. "
            "This does not establish legacy receiver compatibility."
        ) if stats.get("ingress_mode") != "legacy-vt02-h264" else (
            "The legacy 2019 raw H.264 listener exclusively owns UDP 8080. The "
            "official display process must not own that port concurrently. Receiver "
            "pairing/channel/network initialization must be supplied by a separately "
            "validated control session; this tool neither starts nor verifies it."
        ),
        "snapshot_phase": "end_of_observation_before_stop",
        "observed": dict(observed),
        "fresh_at_end": fresh,
        "cleanup_complete": cleanup_complete,
        "ingress": ingress,
        "video": {key: stats.get(key) for key in (
            "packets_received", "frames_received", "decoded_frames", "codec",
            "invalid_fragments", "stale_fragments", "sequence_discontinuities",
            "output_width", "output_height", "decoder_error", "last_error",
        )},
    }


def probe(host: str, port: int, duration: float, transport: str = "shark-framed") -> tuple[dict, int]:
    backend = RmVideoBackend(host=host, port=port)
    backend.configure_ingress(transport)
    observed = dict(listening=False, packets=False, assembled=False, stream=False, decoded=False)
    stats: dict = {}
    try:
        backend.start()
        deadline = time.monotonic() + duration
        while True:
            stats = backend.stats()
            observed["listening"] |= bool(stats["ingress"]["listening"])
            observed["packets"] |= stats["packets_received"] > 0
            observed["assembled"] |= stats["frames_received"] > 0
            observed["stream"] |= stats["ingress"]["stream_blocks_received"] > 0
            observed["decoded"] |= bool(stats["decoded_connected"])
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (not backend.running and backend.last_error):
                break
            time.sleep(min(0.05, remaining))
    finally:
        cleanup_error = ""
        try:
            backend.request_stop()
        except Exception as exc:
            cleanup_error = f"{type(exc).__name__}: {exc}"
        # Do not call wait_closed(timeout): the decoder compatibility method
        # has an unbounded join. Observe the already-admitted owner instead.
        cleanup_deadline = time.monotonic() + 5.0
        while not backend.cleanup_complete and time.monotonic() < cleanup_deadline:
            time.sleep(0.01)
        cleanup_complete = backend.cleanup_complete
    report = summarize(stats, observed=observed, cleanup_complete=cleanup_complete)
    report["cleanup_error"] = cleanup_error
    if transport == "legacy-official-bridge":
        report["official_client_required"] = (
            "Keep the working official client and its receiver control session running. "
            "An explicitly configured passive Npcap bridge forwards selected receiver "
            "UDP8080 payloads to loopback18080. This is a POLAR engineering bridge, "
            "not a DJI-supported export API; Windows/Npcap/hardware validation is pending."
        )
    # Exit zero means only that a fresh decoded frame was observed at the end
    # and owners closed. It never upgrades hardware_verified.
    return report, 0 if report["fresh_at_end"] and cleanup_complete else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("shark-framed", "legacy-vt02-h264", "legacy-official-bridge"), default="shark-framed")
    parser.add_argument("--host", type=local_ipv4, default=None,
                        help="local bind IPv4, NOT the official server address")
    parser.add_argument("--port", type=udp_port, default=None)
    parser.add_argument("--duration", type=positive_duration, default=10.0)
    args = parser.parse_args(argv)
    if args.transport == "legacy-official-bridge":
        if args.host not in (None, "127.0.0.1") or args.port not in (None, 18080):
            parser.error("legacy-official-bridge uses fixed loopback 127.0.0.1:18080")
        host, port = "127.0.0.1", 18080
    elif args.transport == "legacy-vt02-h264":
        if args.host not in (None, "0.0.0.0") or args.port not in (None, 8080):
            parser.error("legacy-vt02-h264 uses the evidenced fixed listener 0.0.0.0:8080")
        host, port = "0.0.0.0", 8080
    else:
        host, port = args.host or "127.0.0.1", args.port or 3334
    report, result = probe(host, port, args.duration, args.transport)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
