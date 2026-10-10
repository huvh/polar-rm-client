"""Portable startup preflight; never performs downloads or installs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from typing import Any

from .runtime_paths import RuntimePaths


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    key: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(item.passed for item in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {"key": item.key, "passed": item.passed, "detail": item.detail}
                for item in self.checks
            ],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".polar-write-", dir=path)
        os.close(fd)
        Path(name).unlink()
        return True, str(path)
    except OSError as exc:
        return False, str(exc)


def _port_available(host: str, port: int) -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        return True, f"{host}:{port}"
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()


def _qt_opengl_context() -> tuple[bool, str]:
    """Create and bind a real offscreen OpenGL context.

    Import-only checks miss absent platform plugins and drivers.  This check is
    safe both before QApplication startup and from the in-app qualification
    panel; when an application already exists it is reused.
    """

    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

        owned_app = None
        app = QCoreApplication.instance()
        if app is None:
            owned_app = QGuiApplication([])
            app = owned_app
        if not isinstance(app, QGuiApplication):
            return False, "existing Qt application is not GUI-capable"

        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        context = QOpenGLContext()
        context.setFormat(fmt)
        created = context.create()
        current = bool(created and surface.isValid() and context.makeCurrent(surface))
        actual = context.format()
        detail = (
            f"OpenGL {actual.majorVersion()}.{actual.minorVersion()} "
            f"profile={actual.profile().name} offscreen={surface.isValid()}"
        )
        if current:
            context.doneCurrent()
        # Keep the local reference alive through context destruction. Qt owns
        # the singleton and tears it down after this function returns.
        _ = owned_app
        return current, detail
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def run_preflight(
    paths: RuntimePaths | None = None,
    *,
    official: bool = False,
    codec_selftest: bool = False,
    active_udp_owned_by_client: bool = False,
) -> PreflightReport:
    paths = paths or RuntimePaths.discover()
    checks: list[PreflightCheck] = []
    manifest: dict[str, Any] = {}
    manifest_ok = not official
    manifest_present = paths.manifest_path.is_file()
    if manifest_present:
        try:
            manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8-sig"))
            if not isinstance(manifest, dict) or any(
                not isinstance(manifest.get(key, {}), dict)
                for key in ("ffmpeg", "critical_files", "resources")
            ):
                raise ValueError("manifest sections must be objects")
            checks.append(PreflightCheck("manifest", True, str(paths.manifest_path)))
            sidecar = paths.app_root / "BUILD_MANIFEST.sha256"
            if sidecar.is_file():
                parts = sidecar.read_text(encoding="ascii").strip().split()
                expected_manifest = parts[0].upper() if parts else ""
                actual_manifest = _sha256(paths.manifest_path)
                manifest_ok = bool(expected_manifest and expected_manifest == actual_manifest)
                checks.append(PreflightCheck(
                    "manifest_sidecar", manifest_ok,
                    actual_manifest if manifest_ok else "manifest digest mismatch",
                ))
            else:
                manifest_ok = not official
                checks.append(PreflightCheck(
                    "manifest_sidecar", manifest_ok, "BUILD_MANIFEST.sha256 missing",
                ))
        except Exception as exc:
            manifest = {}
            manifest_ok = False
            checks.append(PreflightCheck("manifest", False, f"invalid: {exc}"))
    else:
        checks.append(PreflightCheck("manifest", not official, "source mode / manifest absent"))

    # Check integrity before executing any bundled dependency, including the
    # codec probes. A failed manifest must not merely be logged then ignored.
    integrity_ok = manifest_ok
    if manifest:
        for relative in manifest.get("critical_files", {}):
            critical = paths.app_root / Path(str(relative))
            ok, detail = paths.validate_manifest_file(critical)
            integrity_ok = integrity_ok and ok
            checks.append(PreflightCheck(f"integrity:{relative}", ok, detail))
        expected_tree = str(manifest.get("resources", {}).get("tree_sha256", "")).upper()
        if expected_tree:
            try:
                actual_tree = RuntimePaths.hash_tree(paths.resource_root)
                ok = bool(actual_tree and actual_tree == expected_tree)
                detail = actual_tree or "resources directory missing"
            except OSError as exc:
                ok, detail = False, str(exc)
            integrity_ok = integrity_ok and ok
            checks.append(PreflightCheck("integrity:resources", ok, detail))
        elif official:
            integrity_ok = False
            checks.append(PreflightCheck("integrity:resources", False, "tree hash absent"))

    ffmpeg = paths.ffmpeg_path
    if not ffmpeg.is_file() and not official and not manifest_present:
        configured = os.environ.get("POLAR_FFMPEG", "")
        ffmpeg = Path(configured) if configured else ffmpeg
    ffmpeg_ok = ffmpeg.is_file() and integrity_ok
    ffmpeg_detail = str(ffmpeg) if integrity_ok else "not executed: bundle integrity check failed"
    if ffmpeg_ok and (official or manifest_present):
        try:
            expected = str(manifest.get("ffmpeg", {}).get("sha256", "")).upper()
            ffmpeg_ok = bool(expected and _sha256(ffmpeg) == expected)
            ffmpeg_detail = (str(ffmpeg) + "; manifest hash matched" if ffmpeg_ok
                             else "not executed: FFmpeg manifest hash missing/mismatch")
        except OSError as exc:
            ffmpeg_ok, ffmpeg_detail = False, f"not executed: {exc}"
    if ffmpeg_ok:
        try:
            result = subprocess.run(
                [str(ffmpeg), "-hide_banner", "-version"],
                capture_output=True, text=True, timeout=5.0,
            )
            ffmpeg_ok = result.returncode == 0 and "ffmpeg version" in result.stdout
            ffmpeg_detail = result.stdout.splitlines()[0] if result.stdout else result.stderr[:200]
        except Exception as exc:
            ffmpeg_ok, ffmpeg_detail = False, str(exc)
    checks.append(PreflightCheck("ffmpeg", ffmpeg_ok, ffmpeg_detail))

    try:
        from .backend.polar_link import SPEC_STATUS
        from .backend.polar_spec import load_spec
        from .backend.cc_link import KEY_USAGE_FILE

        spec = load_spec()
        spec_ok = bool(spec.ok and SPEC_STATUS.get("ok") and not SPEC_STATUS.get("fell_back", True))
        checks.append(PreflightCheck(
            "protocol_spec", spec_ok,
            spec.source if spec_ok else spec.error_text() or str(SPEC_STATUS),
        ))
        key_usage = json.loads(KEY_USAGE_FILE.read_text(encoding="utf-8-sig"))
        keys_ok = isinstance(key_usage, dict) and bool(key_usage)
        checks.append(PreflightCheck("cc_key_usage", keys_ok, str(KEY_USAGE_FILE)))
    except Exception as exc:
        checks.append(PreflightCheck("protocol_data", False, f"{type(exc).__name__}: {exc}"))

    for key, directory in (
        ("configs_writable", paths.configs_root),
        ("calibrations_writable", paths.calibrations_root),
        ("evidence_writable", paths.evidence_root),
        ("logs_writable", paths.logs_root),
    ):
        ok, detail = _writable(directory)
        checks.append(PreflightCheck(key, ok, detail))
    if active_udp_owned_by_client:
        port_ok, port_detail = True, "0.0.0.0:3334 held by this POLAR-RM backend"
    else:
        port_ok, port_detail = _port_available("0.0.0.0", 3334)
    checks.append(PreflightCheck("udp_3334", port_ok, port_detail))

    qt_ok, qt_detail = _qt_opengl_context()
    checks.append(PreflightCheck("qt_opengl", qt_ok, qt_detail))
    if codec_selftest and not ffmpeg_ok:
        checks.append(PreflightCheck("codec_selftest", False, "not run: FFmpeg validation failed"))
    elif codec_selftest:
        from .backend.codec_selftest import run_all_codec_selftests

        for result in run_all_codec_selftests():
            checks.append(
                PreflightCheck(
                    f"{result.codec}_continuous_decode",
                    result.passed,
                    f"first_frame={result.first_frame_s:.3f}s frames={result.frames} {result.detail}",
                )
            )
    return PreflightReport(tuple(checks))
