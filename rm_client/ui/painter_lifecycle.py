"""Retire Qt painters without treating OpenGL's literal false as a fault.

Qt 6.11 QOpenGL2PaintEngineEx::end() unconditionally returns false after
successfully cleaning up. Raster engines and incomplete/exceptional retirement
must still reject the frame. Never accept an inactive or still-owned painter.
"""
from PySide6.QtGui import QPaintEngine, QPainter


def finish_painter(painter: QPainter) -> bool:
    active = painter.isActive()
    device = painter.device() if active else None
    engine = painter.paintEngine() if active else None
    gl_engine = engine is not None and engine.type() == QPaintEngine.Type.OpenGL2
    result = painter.end()
    return result is not False or bool(
        active and gl_engine and not painter.isActive()
        and device is not None and not device.paintingActive()
    )
