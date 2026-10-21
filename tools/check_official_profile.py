"""Offline release/profile diagnostic. No device, network, GUI or writes."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.configuration.official_profile import diagnose_official_profile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Existing JSON to read, never modify")
    parser.add_argument("--client-version", required=True, help="Exact observed official client version")
    parser.add_argument("--engine-version", help="Exact engine version if used; never implies verified pairing")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.config.read_text(encoding="utf-8-sig"))
        report = diagnose_official_profile(data, client_version=args.client_version, engine_version=args.engine_version)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(json.dumps({"status": "INVALID_CONFIG", "detail": str(exc), "hardware_qualified": False}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    if report.status in {"PROFILE_MISMATCH", "UNSUPPORTED_PROFILE"}:
        return 2
    if not report.profile_matches or report.engine_status == "UNVERIFIED_VERSION":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
