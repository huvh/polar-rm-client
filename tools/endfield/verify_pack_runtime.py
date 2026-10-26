"""Explicit owned Windows D3D check of all prepared fields; never hardware I/O."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.endfield.pack import validate


def run(pack: Path, out: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Native D3D verification requires Windows x64")
    checked = validate(pack)
    out.mkdir(parents=True, exist_ok=False)
    from PySide6.QtGui import QImage
    from rm_client.ui.endfield.menu.native import EndfieldNativeMenu
    menu = EndfieldNativeMenu(pack)
    report = {"scope": "actual owned D3D rendering; no game/device/robot I/O", "cases": [],
              "pack": checked, "boot_audio_absent": not any((pack / key).exists() for key in ("boot", "audio"))}
    def until(predicate, timeout=30.):
        deadline = time.monotonic() + timeout
        while not predicate():
            if menu.error:
                raise RuntimeError(menu.error)
            if menu.handle and menu.api.status(menu.handle) == -1:
                raise RuntimeError(menu.api.error(menu.handle).decode("utf-8", "replace"))
            if time.monotonic() > deadline:
                raise TimeoutError("Owned native renderer timed out")
            time.sleep(.01)
    try:
        menu.prepare(0, 1280, 720, offscreen=True)
        until(lambda: menu.ready)
        menu.request(True)
        for mode in checked["maps"]:
            for width, height, chinese in ((1280, 720, False), (2560, 1440, True)):
                frames = menu.stats()["frames"]
                menu.tick(width=width, height=height, chinese=chinese, mode=mode, paused=False)
                until(lambda: menu.stats()["frames"] > frames + 15)
                time.sleep(1.)  # Let the original authored entrance settle.
                raw = out / f"{mode}_{width}x{height}.bgra"
                menu.api.capture(menu.handle, os.fsencode(raw))
                until(lambda: menu.api.captured(menu.handle) != 0)
                if menu.api.captured(menu.handle) != 1:
                    raise RuntimeError("Owned native framebuffer capture failed")
                pixels = raw.read_bytes()
                if len(pixels) != width * height * 4 or sum(v > 0 for v in pixels[3::4]) < width * height // 100:
                    raise ValueError("Native framebuffer is truncated or blank")
                image = QImage(pixels, width, height, width * 4, QImage.Format.Format_ARGB32)
                target = raw.with_suffix(".png")
                if not image.save(str(target)):
                    raise OSError("Could not save owned framebuffer")
                report["cases"].append({"mode": mode, "width": width, "height": height,
                                        "chinese": chinese, "image": target.name, "stats": menu.stats()})
    finally:
        menu.close()
        menu.wait_closed()
        report["owner_retired"] = menu.handle == 0
    report["status"] = "PASS"
    report["limits"] = "Not exact pixel parity, full app regression, throughput, packaging or match qualification."
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.pack.resolve(), args.out.resolve())
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
