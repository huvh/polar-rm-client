import argparse
import json
from pathlib import Path
import sys

from rm_client.runtime_paths import RuntimePaths


def _preflight_options(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--official", action="store_true")
    parser.add_argument("--codec-selftest", action="store_true")
    parser.add_argument("--preflight-output", type=Path)
    options, _ = parser.parse_known_args(argv)
    return options


def _run_replay(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only POLAR field-log replay; no uplink objects are constructed"
    )
    parser.add_argument("--replay-field-log", nargs="+", required=True, type=Path)
    parser.add_argument(
        "--replay-output",
        type=Path,
        default=Path.cwd() / "POLAR-field-replay-summary.json",
    )
    options = parser.parse_args(argv)
    from rm_client.replay import summarize_field_logs, write_replay_summary

    summary = summarize_field_logs(options.replay_field_log)
    output = write_replay_summary(options.replay_output, summary)
    print(json.dumps({**summary, "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if "--replay-field-log" in sys.argv:
        raise SystemExit(_run_replay(sys.argv[1:]))
    paths = RuntimePaths.discover()
    paths.ensure_writable_dirs()
    paths.seed_default_config()
    if "--preflight" in sys.argv:
        from rm_client.preflight import run_preflight

        options = _preflight_options(sys.argv[1:])
        report = run_preflight(
            paths,
            official=options.official,
            codec_selftest=options.codec_selftest,
        )
        rendered = json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
        if options.preflight_output is not None:
            options.preflight_output.parent.mkdir(parents=True, exist_ok=True)
            options.preflight_output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        raise SystemExit(0 if report.passed else 2)
    from rm_client.ui.polar_app import main

    main()
