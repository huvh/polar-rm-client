from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_client.replay import summarize_field_logs, write_replay_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only POLAR field-log replay (uplink disabled by design)")
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = summarize_field_logs(args.logs)
    if args.output is not None:
        write_replay_summary(args.output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
