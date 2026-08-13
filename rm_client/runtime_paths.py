"""Runtime path discovery for source and self-contained portable builds.

The application used to derive its root from ``__file__.parents[3]``.  That
works only in this checkout layout and silently points at a temporary
PyInstaller directory in a frozen build.  RuntimePaths is the single path
authority used by both the UI and the backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    app_root: Path
    resource_root: Path
    defaults_root: Path
    user_data_root: Path
    configs_root: Path
    calibrations_root: Path
    evidence_root: Path
    logs_root: Path
    bin_root: Path
    manifest_path: Path
    source_mode: bool

    @classmethod
    def discover(
        cls,
        *,
        executable: str | os.PathLike[str] | None = None,
        module_file: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
        frozen: bool | None = None,
    ) -> "RuntimePaths":
        env = os.environ if environ is None else environ
        override = str(env.get("POLAR_APP_ROOT", "")).strip()
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        if override:
            app_root = Path(override).expanduser().resolve()
            is_frozen = True
        elif is_frozen:
            app_root = Path(executable or sys.executable).resolve().parent
        else:
            current = Path(module_file or __file__).resolve()
            # runtime_paths.py lives directly under rm_client/.
            app_root = current.parents[1]

        if is_frozen:
            resource_root = app_root / "resources"
            defaults_root = app_root / "defaults"
            user_data_root = app_root / "user_data"
            configs_root = user_data_root / "configs"
            calibrations_root = user_data_root / "calibrations"
            evidence_root = app_root / "field_evidence"
            logs_root = user_data_root / "logs"
            bin_root = app_root / "bin"
        else:
            resource_root = app_root
            defaults_root = app_root / "configs"
            runtime_override = str(env.get("POLAR_USER_DATA_ROOT", "")).strip()
            user_data_root = (
                Path(runtime_override).expanduser().resolve()
                if runtime_override
                else app_root / "user_data"
            )
            # Source defaults are immutable inputs too. This also prevents
            # tests/application startup from rewriting a developer's tracked
            # configs/default.json.
            configs_root = user_data_root / "configs"
            calibrations_root = user_data_root / "calibrations"
            evidence_root = user_data_root / "field_evidence"
            logs_root = user_data_root / "logs"
            bin_root = app_root / "bin"

        return cls(
            app_root=app_root,
            resource_root=resource_root,
            defaults_root=defaults_root,
            user_data_root=user_data_root,
            configs_root=configs_root,
            calibrations_root=calibrations_root,
            evidence_root=evidence_root,
            logs_root=logs_root,
            bin_root=bin_root,
            manifest_path=app_root / "BUILD_MANIFEST.json",
            source_mode=not is_frozen,
        )

    @property
    def workspace_root(self) -> Path:
        """Compatibility root expected by a few legacy source-only helpers."""

        return self.app_root.parent if self.source_mode else self.app_root

    @property
    def ffmpeg_path(self) -> Path:
        return self.bin_root / "ffmpeg.exe"

    def asset(self, *parts: str) -> Path:
        return self.resource_root.joinpath("assets", *parts)

    def ensure_writable_dirs(self) -> None:
        for path in (
            self.user_data_root,
            self.configs_root,
            self.calibrations_root,
            self.evidence_root,
            self.evidence_root / "sessions",
            self.logs_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def seed_default_config(self) -> Path:
        """Copy the immutable portable default to user_data on first launch."""

        target = self.configs_root / "default.json"
        if target.exists():
            return target
        source = self.defaults_root / "default.json"
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            # Keep the immutable default untouched and avoid partial writes.
            temporary = target.with_suffix(".json.new")
            temporary.write_bytes(source.read_bytes())
            os.replace(temporary, target)
        return target

    def validate_manifest_file(self, path: Path) -> tuple[bool, str]:
        """Validate a packaged critical file against BUILD_MANIFEST.json."""

        import hashlib
        import json

        if not self.manifest_path.is_file():
            return self.source_mode, "source mode / manifest absent"
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8-sig"))
            relative = str(Path(path).resolve().relative_to(self.app_root.resolve())).replace("\\", "/")
            expected = str(manifest.get("critical_files", {}).get(relative, "")).upper()
            if not expected:
                return False, f"{relative} is not listed as a critical file"
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()
            return digest == expected, f"{relative}: {digest}"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def hash_tree(root: Path) -> str:
        """Hash a resource tree independently of copy order and timestamps.

        Each relative POSIX path and its file SHA-256 are included in the
        digest.  This makes the manifest sensitive to missing, renamed and
        modified resources without trusting directory metadata.
        """

        import hashlib

        root = Path(root)
        digest = hashlib.sha256()
        if not root.is_dir():
            return ""
        for path in sorted(
            (entry for entry in root.rglob("*") if entry.is_file()),
            key=lambda entry: entry.relative_to(root).as_posix().casefold(),
        ):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            file_digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    file_digest.update(chunk)
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(file_digest.digest())
        return digest.hexdigest().upper()


def runtime_paths() -> RuntimePaths:
    return RuntimePaths.discover()
