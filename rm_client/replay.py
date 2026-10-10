"""Read-only field-log summaries shared by source and portable CLIs.

This module deliberately imports no backend manager or transport.  Invoking
replay mode therefore cannot construct an MQTT, serial, UDP, or control
publisher.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .backend.field_log import ReadOnlyFieldReplay


def resolve_log_inputs(inputs: Iterable[Path]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for value in inputs:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            resolved.extend(sorted(path.glob("*.jsonl*"), key=lambda item: item.name.casefold()))
        elif path.is_file():
            resolved.append(path)
        else:
            raise FileNotFoundError(path)
    unique = tuple(dict.fromkeys(resolved))
    if not unique:
        raise ValueError("no field JSONL logs were found")
    return unique


def summarize_field_logs(inputs: Iterable[Path]) -> dict[str, object]:
    paths = resolve_log_inputs(inputs)
    counts: dict[str, int] = {}
    first_wall_time: float | None = None
    last_wall_time: float | None = None
    total = 0
    for record in ReadOnlyFieldReplay(paths).records():
        event = str(record.get("event", "unknown"))
        counts[event] = counts.get(event, 0) + 1
        total += 1
        try:
            wall_time = float(record["wall_time"])
        except (KeyError, TypeError, ValueError):
            continue
        first_wall_time = wall_time if first_wall_time is None else min(first_wall_time, wall_time)
        last_wall_time = wall_time if last_wall_time is None else max(last_wall_time, wall_time)
    return {
        "replay_mode": True,
        "uplink": "DISABLED",
        "inputs": [str(path) for path in paths],
        "records": total,
        "first_wall_time": first_wall_time,
        "last_wall_time": last_wall_time,
        "events": dict(sorted(counts.items())),
    }


def write_replay_summary(output: Path, summary: dict[str, object]) -> Path:
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return target
