"""Audited offline Qt fixture loader; never imports audio, app or transports.

Executes the actual production MatchProgressRenderer/DigitalScroll definitions
from kill_fx.py unchanged. This keeps Qt5 review independent of Qt6 multimedia
while ensuring previews and regression tests exercise the real BF6 drawing code.
Production code never imports this helper.
"""
from __future__ import annotations
import ast
import math
from pathlib import Path


def load_progress_renderer(QtCore, QtGui):
    source = Path(__file__).resolve().parents[1] / "rm_client/kill_fx.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    names = {"_ease_out_cubic", "DigitalScroll", "MatchProgressRenderer"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in nodes} != names:
        raise RuntimeError("BF6 production definitions changed; review preview loader")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + nodes, type_ignores=[])
    namespace = {"math": math, "QPainter": QtGui.QPainter, "QPen": QtGui.QPen,
                 "QColor": QtGui.QColor, "QFont": QtGui.QFont,
                 "QRectF": QtCore.QRectF, "Qt": QtCore.Qt}
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    return namespace["MatchProgressRenderer"]
