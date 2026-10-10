"""Bounded field telemetry logs and a publish-free replay reader."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterable, Iterator, Mapping


class RotatingJsonlLogger:
    """A tiny dependency-free 5x20 MiB JSONL logger.

    Video payloads are deliberately rejected. Referee payloads may be recorded
    as bounded base64 strings so protocol regressions are reproducible.
    """

    def __init__(
        self,
        directory: Path,
        *,
        filename: str = "polar-field.jsonl",
        max_bytes: int = 20 * 1024 * 1024,
        backups: int = 4,
    ) -> None:
        self.directory = Path(directory)
        self.path = self.directory / filename
        self.max_bytes = max(1024, int(max_bytes))
        self.backups = max(1, int(backups))
        self._lock = threading.Lock()
        self.last_error = ""

    def emit(self, event: str, **fields: Any) -> None:
        if str(event).lower() in {"video_frame", "video_payload", "decoded_frame"}:
            return
        record = {
            "schema": 1,
            "wall_time": time.time(),
            "monotonic": time.perf_counter(),
            "event": str(event),
        }
        record.update({key: self._safe(value) for key, value in fields.items()})
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(line))
                with self.path.open("ab", buffering=0) as handle:
                    handle.write(line)
            self.last_error = ""
        except OSError as exc:
            # Logging must never break the 60/75 Hz control loops.
            self.last_error = str(exc)

    def referee_payload(self, topic: str, payload: bytes) -> None:
        bounded = bytes(payload[:65536])
        self.emit(
            "referee_rx",
            topic=topic,
            payload_b64=base64.b64encode(bounded).decode("ascii"),
            payload_bytes=len(payload),
            truncated=len(payload) > len(bounded),
        )

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        if size + incoming <= self.max_bytes:
            return
        oldest = self.path.with_suffix(self.path.suffix + f".{self.backups}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_suffix(self.path.suffix + f".{index}")
            if source.exists():
                os.replace(source, self.path.with_suffix(self.path.suffix + f".{index + 1}"))
        if self.path.exists():
            os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))

    @classmethod
    def _safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, bytes):
            return base64.b64encode(value[:65536]).decode("ascii")
        if isinstance(value, Mapping):
            return {str(k): cls._safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [cls._safe(item) for item in value]
        return repr(value)


class ReadOnlyFieldReplay:
    """Iterate field records. This class intentionally has no publisher."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self.paths = tuple(Path(path) for path in paths)

    def records(self) -> Iterator[dict[str, Any]]:
        for path in self.paths:
            # Accept a BOM on imported/operator-created logs while the native
            # logger itself continues to write canonical BOM-free UTF-8.
            with path.open("r", encoding="utf-8-sig") as handle:
                for line_number, line in enumerate(handle, 1):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{path}:{line_number}: invalid JSONL") from exc
                    if isinstance(record, dict):
                        yield record
