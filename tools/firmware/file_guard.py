"""Byte-preserving journal for a tool's explicitly enumerated file changes.

This module does not apply patches or run firmware. Missing/incomplete journals,
symlinks and edits made after a tool run fail closed rather than using checkout.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable


class SnapshotError(RuntimeError):
    pass


def _target(repo: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise SnapshotError(f"Unsafe journal path: {relative}")
    path = repo / rel
    cursor = path
    while cursor != repo:
        if cursor.is_symlink():
            raise SnapshotError(f"Refusing symlink: {relative}")
        cursor = cursor.parent
    if path.exists() and not path.is_file():
        raise SnapshotError(f"Not a regular file: {relative}")
    return path


def _state(path: Path) -> dict:
    if not path.exists():
        return {"data": None, "mode": None}
    return {"data": base64.b64encode(path.read_bytes()).decode("ascii"),
            "mode": path.stat().st_mode & 0o777}


def _digest(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class FileJournal:
    def __init__(self, repo: Path, relatives: Iterable[str]) -> None:
        self.repo = Path(repo).resolve()
        self.relatives = sorted(set(relatives))
        gitdir = self.repo / ".git"
        if gitdir.is_file():
            value = gitdir.read_text(encoding="utf-8").strip()
            if not value.startswith("gitdir: "):
                raise SnapshotError("Unrecognized .git file")
            gitdir = (self.repo / value[len("gitdir: "):]).resolve()
        if not gitdir.is_dir():
            raise SnapshotError("Git metadata directory missing")
        self.path = gitdir / "polar-prepare-snapshot.json"
        self.lock = gitdir / "polar-prepare-snapshot.lock"
        self.record: dict | None = None

    @contextmanager
    def locked(self):
        try:
            fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SnapshotError("Another operation or interrupted run owns the journal lock; inspect it before retrying") from exc
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            yield
        finally:
            self.lock.unlink(missing_ok=True)

    def _load(self) -> dict:
        if not self.path.is_file():
            raise SnapshotError("No saved pre-operation snapshot; refusing destructive fallback")
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            if (record.get("version") != 1 or record.get("repo") != str(self.repo)
                    or record.get("status") != "complete"
                    or set(record["files"]) != set(self.relatives)):
                raise ValueError("wrong target, incomplete run or different file inventory")
            for relative, item in record["files"].items():
                _target(self.repo, relative)
                before = item["before"]
                if before["data"] is not None:
                    base64.b64decode(before["data"], validate=True)
                    if not isinstance(before["mode"], int) or not 0 <= before["mode"] <= 0o777:
                        raise ValueError("invalid file mode")
                if not isinstance(item["after"], str):
                    raise ValueError("missing post-operation fingerprint")
            return record
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise SnapshotError(f"Snapshot cannot be safely restored: {exc}") from exc

    def begin(self) -> None:
        if self.path.exists():
            record = self._load()
            for rel, item in record["files"].items():
                if _digest(_state(_target(self.repo, rel))) != item["after"]:
                    raise SnapshotError(f"File changed since the last tool run: {rel}")
        else:
            record = {"version": 1, "repo": str(self.repo), "files": {
                rel: {"before": _state(_target(self.repo, rel))} for rel in self.relatives
            }}
        record["status"] = "preparing"
        _write_json(self.path, record)
        self.record = record

    def finish(self) -> None:
        if self.record is None:
            return
        for rel, item in self.record["files"].items():
            item["after"] = _digest(_state(_target(self.repo, rel)))
        self.record["status"] = "complete"
        _write_json(self.path, self.record)

    def revert(self) -> int:
        record = self._load()
        # Validate the full set before touching even one file. Already-restored
        # files are accepted so a filesystem-error retry remains safe.
        for rel, item in record["files"].items():
            current = _digest(_state(_target(self.repo, rel)))
            if current not in (item["after"], _digest(item["before"])):
                raise SnapshotError(f"Refusing to overwrite a later edit: {rel}")
        changed = 0
        for rel, item in record["files"].items():
            path = _target(self.repo, rel)
            before = item["before"]
            if _state(path) == before:
                continue
            if before["data"] is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(base64.b64decode(before["data"], validate=True))
                    os.chmod(temporary, before["mode"])
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            changed += 1
        self.path.unlink()
        return changed
