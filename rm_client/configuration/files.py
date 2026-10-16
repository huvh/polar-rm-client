"""Exact local preference-file snapshots and atomic byte replacement."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile


def atomic_write_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    contents: bytes | None

    @classmethod
    def capture(cls, path: Path) -> FileSnapshot:
        return cls(path, path.read_bytes() if path.exists() else None)

    def restore(self) -> None:
        if self.contents is None:
            self.path.unlink(missing_ok=True)
        else:
            atomic_write_bytes(self.path, self.contents)
