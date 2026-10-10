"""Offline native Qt render fixtures. Never starts the client or any backend.

Default: PySide6 (production). Explicit --qt5-compat-preview uses installed
PyQt5 for QPainter visual review ONLY; it is not a PySide6 runtime validation.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "tmp_top_match_bar")
    parser.add_argument("--qt5-compat-preview", action="store_true")
    args = parser.parse_args()
    if args.qt5_compat_preview:
        import PyQt5
        from PyQt5 import QtCore, QtGui, QtWidgets
        # Alias in THIS offline preview process only. Production stays PySide6.
        sys.modules["PySide6"] = PyQt5
        sys.modules["PySide6.QtCore"] = QtCore
        sys.modules["PySide6.QtGui"] = QtGui
        sys.modules["PySide6.QtWidgets"] = QtWidgets
        binding = "PyQt5 compatibility preview; PySide6 runtime NOT verified"
    else:
        from PySide6 import QtCore, QtGui, QtWidgets
        binding = "PySide6 native production binding"
    from rm_client.top_match_bar import LifeState as L, MatchBarFrame, RobotCard, TeamStrip
    from rm_client.ui.top_match_bar import TopMatchBarOptions, TopMatchBarRenderer
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    args.output.mkdir(parents=True, exist_ok=True)

    def team(alliance, ids, lives, score=None, kills=None):
        return TeamStrip(alliance, tuple(RobotCard(rid, {1:"H",2:"E",3:"3",4:"4",6:"A",7:"S",8:"D"}.get(rid % 100,"R"), life,
                                                   (kills or {}).get(rid), str(rid), rid == 103)
                                          for rid, life in zip(ids, lives)), score)
    fixture = MatchBarFrame(team("Blue", [101,102,103,104,107], [L.DEAD,L.ALIVE,L.ALIVE,L.DEAD,L.DEAD], 0, {103:2}),
                            team("Red", [1,2,3,4,7], [L.DEAD,L.DEAD,L.ALIVE,L.ALIVE,L.ALIVE], 3, {1:2,4:1}),
                            85, "DEMO SCORE", "MATCH")
    scenes = [
        ("Reference geometry · 5v5 synthetic fixture", fixture, 1.0),
        ("RMUL · 3v3 · enemy telemetry explicitly unknown", MatchBarFrame(
            team("Blue", [101,103,107], [L.ALIVE,L.ALIVE,L.DEAD]),
            team("Red", [1,3,7], [L.UNKNOWN]*3), 185, "", "MATCH"), 1.0),
        ("Uneven rosters · 7v3 · no invented team scores", MatchBarFrame(
            team("Blue", [101,102,103,104,106,107,108], [L.ALIVE,L.ALIVE,L.DEAD,L.UNKNOWN,L.UNKNOWN,L.ALIVE,L.UNKNOWN]),
            team("Red", [1,3,7], [L.ALIVE,L.DEAD,L.UNKNOWN]), 39, "", "MATCH"), .8),
        ("Disconnected / stale · unknown life, time and score", MatchBarFrame(
            team("Blue", [101,102,103,104,107], [L.UNKNOWN]*5),
            team("Red", [1,2,3,4,7], [L.UNKNOWN]*5)), .82),
    ]
    renderer = TopMatchBarRenderer()
    outputs = []
    images = []
    for index, (title, frame, scale) in enumerate(scenes):
        image = QtGui.QImage(1024, 180, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtGui.QColor("#343c3f"))
        p = QtGui.QPainter(image)
        # Synthetic background checks contrast. No reference pixels are reused.
        gradient = QtGui.QLinearGradient(0, 0, 1024, 150)
        gradient.setColorAt(0, QtGui.QColor("#584b41"))
        gradient.setColorAt(.4, QtGui.QColor("#8d887b"))
        gradient.setColorAt(.65, QtGui.QColor("#535754"))
        gradient.setColorAt(1, QtGui.QColor("#aaa393"))
        p.fillRect(QtCore.QRectF(0, 0, 1024, 145), gradient)
        for x in (40, 278, 651, 878):
            p.fillRect(QtCore.QRectF(x, 0, 25, 145), QtGui.QColor(25, 29, 30, 45))
        options = TopMatchBarOptions(scale=scale, reduced_motion=True)
        renderer.paint(p, frame, 1024, now=10, options=options)
        p.setFont(QtGui.QFont("DejaVu Sans", 9))
        p.setPen(QtGui.QColor("#e5e9e7"))
        p.drawText(QtCore.QRectF(14, 148, 995, 20), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, title)
        p.end()
        filename = f"top-match-bar-{index+1}.png"
        if not image.save(str(args.output / filename)):
            raise RuntimeError("PNG save failed")
        outputs.append(filename)
        images.append(image)
    sheet = QtGui.QImage(1024, len(images) * 180, QtGui.QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(sheet)
    for index, image in enumerate(images):
        p.drawImage(0, index * 180, image)
    p.end()
    sheet.save(str(args.output / "top-match-bar-contact-sheet.png"))
    # Native transparent overlay, useful for reviewing on any camera backdrop.
    overlay = QtGui.QImage(1024, 140, QtGui.QImage.Format_ARGB32_Premultiplied)
    overlay.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(overlay)
    renderer.paint(p, fixture, 1024, now=10, options=TopMatchBarOptions(scale=1, reduced_motion=True))
    p.end()
    overlay.save(str(args.output / "top-match-bar-transparent.png"))
    manifest = {"binding": binding, "qt_version": QtCore.qVersion(), "production_runtime_verified": not args.qt5_compat_preview,
                "render_kind": "native QImage/QPainter, synthetic data and background", "outputs": outputs,
                "limitations": ["Not the full app", "No hardware, sockets, control or vision", "Not a pixel-identical Valve font/avatar copy"]}
    (args.output / "render-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
