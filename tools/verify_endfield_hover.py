"""Exercise the real owned native hover state, not a mocked rendering session.

No game, desktop capture, robot transport or global mouse injection is used.
An explicit --library can compare an immutable diagnostic build before/after a
fix. Ordinary runs resolve the hash-verified installed private renderer.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def hover_reader(menu):
    function = menu.api.lib.pe_hover
    function.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_double)]
    function.restype = None

    def read():
        values = (ctypes.c_double * 2)()
        function(menu.handle, values)
        return {"code": int(values[0]), "changes": int(values[1])}
    return read


def check_hover(menu, wait, until, *, codes=(2, 6, 5, 7, 10), dwell=.45, position=None):
    """Shared by offscreen D3D and the explicit fullscreen desktop check."""
    read = hover_reader(menu)
    results = []
    for code in codes:
        rect = (ctypes.c_double * 4)()
        until(lambda: bool(menu.api.button(menu.handle, code, rect)))
        x, y = rect[0]+rect[2]/2, rect[1]+rect[3]/2
        if position:
            position(x, y)
        menu.pointer(1, x, y)
        # Crossing the whole screen moves the authored parallax camera. Aim
        # once more at the settled projected card, then stop all input. A small
        # edge card can legitimately move away from its former screen centre.
        wait(.65)
        until(lambda: bool(menu.api.button(menu.handle, code, rect)))
        x, y = rect[0]+rect[2]/2, rect[1]+rect[3]/2
        if position:
            position(x, y)
        menu.pointer(1, x, y)
        wait(.65)
        initial = read()
        samples = []
        for _ in range(12):
            wait(dwell/12)
            samples.append(read())
        stationary = initial["code"] == code and all(row == initial for row in samples)
        for _ in range(12):
            menu.pointer(1, x, y)  # duplicate WM_MOUSEMOVE must not retrigger
            wait(.02)
        repeated = read()
        duplicate = repeated == initial
        results.append({"button": code, "stationary": stationary, "duplicate_moves": duplicate,
                        "initial": initial, "final": repeated, "samples": samples})
    return results


def run(pack: Path, out: Path, library: Path | None) -> int:
    if sys.platform != "win32":
        raise RuntimeError("The native D3D renderer requires Windows")
    from rm_client.ui.endfield_native import EndfieldNativeMenu, NativeApi
    menu = EndfieldNativeMenu(pack)
    report = {"scope": "owned native D3D hover only; no match qualification", "cases": []}
    out.mkdir(parents=True, exist_ok=False)

    def until(predicate, timeout=15):
        deadline = time.monotonic()+timeout
        while not predicate():
            if menu.handle and menu.api.status(menu.handle) == -1:
                raise RuntimeError(menu.api.error(menu.handle).decode("utf-8", "replace"))
            if time.monotonic() > deadline:
                raise TimeoutError("Native hover regression timed out")
            time.sleep(.005)

    wait = time.sleep
    try:
        if library:
            menu.api = NativeApi(library)
            menu.attempted = True
            menu.handle = menu.api.create(0, os.fsencode(pack / "native_source_runtime"), 1280, 720, 1)
        else:
            menu.prepare(0, 1280, 720, offscreen=True)
        until(lambda: menu.ready or bool(menu.error), 30)
        if menu.error:
            raise RuntimeError(menu.error)
        for width, height, chinese in ((1280, 720, False), (1920, 1080, True), (3840, 2160, True)):
            menu.tick(width=width, height=height, chinese=chinese, mode="RMUL3v3", paused=False)
            menu.request(True)
            wait(1.2)
            checks = check_hover(menu, wait, until)
            read = hover_reader(menu)
            menu.pointer(6, 0, 0)
            until(lambda: read()["code"] == 0)
            departed = read()
            wait(.2)
            normal_leave_stable = departed == read()
            checks += check_hover(menu, wait, until, codes=(2,), dwell=.2)
            # Blocking a Qt modal clears only the interaction; tracking still
            # receives a real leave, so dismissing it cannot restore a ghost.
            menu.tick(width=width, height=height, chinese=chinese, mode="RMUL3v3", paused=True)
            until(lambda: read()["code"] == 0)
            held = read()
            wait(.15)
            paused = held == read()
            menu.pointer(6, 0, 0)  # true leave has no (0,0) hover position
            until(lambda: read()["code"] == 0)
            left = read()
            wait(.15)
            leave_stable = left == read()
            menu.pointer(1, 1, 1)  # movement while modal is not interactive
            wait(.1)
            paused = paused and read()["code"] == 0
            menu.tick(width=width, height=height, chinese=chinese, mode="RMUL3v3", paused=False)
            wait(.15)
            resumed = read()["code"] == 0
            reentry = check_hover(menu, wait, until, codes=(2,), dwell=.2)
            menu.request(False)
            until(lambda: menu.phase == 0)
            report["cases"].append({"physical_size": [width, height], "chinese": chinese,
                                    "buttons": checks + reentry, "leave_stable": leave_stable,
                                    "normal_leave_stable": normal_leave_stable,
                                    "paused": paused, "no_ghost_after_modal": resumed})
        report["result"] = "PASS" if all(
            case["normal_leave_stable"] and case["leave_stable"] and case["paused"] and case["no_ghost_after_modal"] and all(
                row["stationary"] and row["duplicate_moves"] for row in case["buttons"])
            for case in report["cases"]) else "FAIL"
        report["stats"] = menu.stats()
    finally:
        menu.close()
        menu.wait_closed()
        report["retired"] = menu.handle == 0
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Endfield native hover {report['result']}", flush=True)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--library", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.pack.resolve(), args.out.resolve(), args.library.resolve() if args.library else None))
