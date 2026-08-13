# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas = []
binaries = []
hiddenimports = []
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
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="POLAR-RM")
