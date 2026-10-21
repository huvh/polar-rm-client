"""Original EndfieldHUD scene owner; no CPU render/copy in ordinary frames.

The bounded native worker owns D3D/DirectComposition, its source clocks and
private fonts. Qt owns modal input and every semantic client action. No native
callback can publish a robot command or arm match control.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
import time

_LIBRARIES: dict[str, object] = {}  # Never unload code while a worker retires.


def library_path(pack: Path) -> Path:
    root = pack / "native_renderer"
    active = root / "CURRENT.json"
    if active.is_file():
        data = json.loads(active.read_text(encoding="utf-8"))
        name = data["directory"]
        if not isinstance(name, str) or not re.fullmatch(r"build_[0-9a-f]{16}", name):
            raise ValueError("Invalid source renderer version directory")
        root /= name
    manifest = json.loads((root / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest["reference_commit"] != "cdbd4f573c8fa3b9c2048fa3d1b089e69196537b":
        raise ValueError("Source renderer revision differs")
    library = root / "polar_endfield.dll"
    with library.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["binary_sha256"]:
            raise ValueError("Source renderer hash differs")
    return library


class NativeApi:
    def __init__(self, path: Path):
        key = str(path.resolve())
        if key not in _LIBRARIES:
            lib = ctypes.CDLL(key)
            u64, uint, number, ptr = ctypes.c_uint64, ctypes.c_uint, ctypes.c_double, ctypes.c_char_p
            signatures = {
                "create": ([ctypes.c_size_t, ptr, uint, uint, ctypes.c_int], u64),
                "status": ([u64], ctypes.c_int), "phase": ([u64], ctypes.c_int), "action": ([u64], ctypes.c_int),
                "visible": ([u64, ctypes.c_int], None), "pause": ([u64, ctypes.c_int], None),
                "resize": ([u64, uint, uint], None), "input": ([u64, ctypes.c_int, number, number, number], None),
                "context": ([u64, ptr], None), "error": ([u64], ptr), "stats": ([u64, ctypes.POINTER(number)], None),
                "destroy": ([u64], None), "release": ([u64], None), "capture": ([u64, ptr], None),
                "captured": ([u64], ctypes.c_int),
                "button": ([u64, ctypes.c_int, ctypes.POINTER(number)], ctypes.c_int),
            }
            for name, (arguments, result) in signatures.items():
                function = getattr(lib, "pe_" + name)
                function.argtypes, function.restype = arguments, result
            _LIBRARIES[key] = lib
        self.lib = _LIBRARIES[key]

    def __getattr__(self, name):
        return getattr(self.lib, "pe_" + name)


class EndfieldNativeMenu:
    def __init__(self, pack: Path):
        self.pack = pack
        self.api = None
        self.handle = 0
        self.error = ""
        self.requested = False
        self.attempted = False
        self.retiring = False
        self._awaiting_backdrop = False
        self._backdrop_frame_ready = False
        self._context = None
        self._size = None

    def prepare(self, parent: int, width: int, height: int, *, offscreen=False) -> None:
        if self.attempted or self.retiring:
            return
        self.attempted = True
        try:
            self.api = NativeApi(library_path(self.pack))
            self.handle = int(self.api.create(parent, os.fsencode(self.pack / "native_source_runtime"), width, height, int(offscreen)))
            if not self.handle:
                raise RuntimeError("Could not create source renderer owner")
            self.api.visible(self.handle, self.requested and not self._awaiting_backdrop)
        except (OSError, ValueError, KeyError, RuntimeError, AttributeError) as error:
            self.error = str(error)

    @property
    def ready(self) -> bool:
        return bool(self.handle and self.api.status(self.handle) == 1)

    @property
    def phase(self) -> int:
        if self._awaiting_backdrop:
            return 3
        return self.api.phase(self.handle) if self.handle else 0

    def request(self, visible: bool, *, wait_for_backdrop=False) -> None:
        self.requested = visible
        self._awaiting_backdrop = bool(visible and wait_for_backdrop)
        self._backdrop_frame_ready = False
        if self.handle:
            self.api.visible(self.handle, visible and not self._awaiting_backdrop)

    def backdrop_frame_ready(self, accepted: bool) -> None:
        self._backdrop_frame_ready = bool(accepted and self.requested)

    def backdrop_presented(self) -> None:
        # A covering native HWND can make Qt stop painting the parent. Reveal
        # only after a successful Esc backdrop has actually reached Qt's swap.
        if self._awaiting_backdrop and self._backdrop_frame_ready and self.handle and not self.retiring:
            self._awaiting_backdrop = False
            self.api.visible(self.handle, True)

    def tick(self, *, width: int, height: int, chinese: bool, mode: str, paused: bool) -> int:
        if not self.handle or self.retiring:
            return 0
        status = self.api.status(self.handle)
        if status == -1:
            self.error = self.api.error(self.handle).decode("utf-8", "replace")
            return 0
        size = (width, height)
        if size != self._size:
            self.api.resize(self.handle, width, height)
            self._size = size
        context = (bool(chinese), mode)
        if context != self._context:
            self.api.context(self.handle, json.dumps({"chinese": chinese, "mode": mode}).encode("utf-8"))
            self._context = context
        self.api.pause(self.handle, paused)
        return self.api.action(self.handle) if not paused else 0

    def pointer(self, kind: int, x: float, y: float, value=0.0) -> None:
        if self.ready:
            self.api.input(self.handle, kind, x, y, value)

    def close(self) -> None:
        self.retiring = True
        self.requested = False
        self._awaiting_backdrop = self._backdrop_frame_ready = False
        if self.handle:
            self.api.destroy(self.handle)

    def wait_closed(self, timeout=5.0) -> None:
        if not self.handle:
            return
        deadline = time.monotonic() + timeout
        while self.api.status(self.handle) not in (-1, 2):
            if time.monotonic() > deadline:
                raise TimeoutError("Source render owner did not retire")
            time.sleep(.02)
        self.api.release(self.handle)
        self.handle = 0

    def stats(self) -> dict:
        values = (ctypes.c_double * 5)()
        if self.handle:
            self.api.stats(self.handle, values)
        return dict(zip(("frames", "last_ms", "textures", "meshes", "owners"), values))
