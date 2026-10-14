# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
# Keep data beside its importing frozen module, independent of the launch cwd.
datas = [
    (str(root / "rm_client/backend/polar_protocol.json"), "rm_client/backend"),
    (str(root / "configs/cc_key_usage.json"), "configs"),
]
binaries = []
hiddenimports = []
# Public exports are lazy to keep schema imports free of Qt/OpenCV. Explicit
# inclusion is required because import_module names are otherwise invisible.
hiddenimports += ["rm_client.backend." + name for name in (
    "manager", "safety", "mqtt_backend", "video_backend", "serial_backend",
    "readiness", "qualification", "protocol", "team_control",
)]
for package in ("cv2", "openvino"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += [name for name in h if ".tests" not in name and ".scripts" not in name]
    except Exception:
        pass

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="POLAR-RM",
    console=False,
    disable_windowed_traceback=False,
    target_arch="x86_64",
    version=str(root / "BUILD_VERSION_INFO.txt") if (root / "BUILD_VERSION_INFO.txt").is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="POLAR-RM")
