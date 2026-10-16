"""Configure Qt/OpenGL and own windows launched through the public entry point.

``polar_app`` re-exports ``main`` for compatibility. Its window class is imported
inside ``main`` so that either module can be imported first without a cycle.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QWidget


def _retain_window_until_close(application: QApplication, window: QWidget) -> None:
    """Keep top-level Python wrappers alive when reusing a host event loop."""
    windows = getattr(application, "_polar_client_windows", None)
    if windows is None:
        windows = {}
        application._polar_client_windows = windows
    window_id = id(window)
    windows[window_id] = window
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda: windows.pop(window_id, None))


def main() -> None:
    from rm_client.ui.polar_app import PolarRMWindow

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        surface = QSurfaceFormat()
        surface.setVersion(3, 3)
        surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        surface.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
        # Configure swaps from the saved preference before creating any GL
        # context. The window's frame scheduler separately controls HUD updates.
        from ..cs2_video_settings import configure_surface
        configure_surface(surface)
        surface.setDepthBufferSize(0)
        surface.setStencilBufferSize(0)
        QSurfaceFormat.setDefaultFormat(surface)
        app = QApplication(sys.argv)
    app.setApplicationName("POLAR-RM Custom Client")
    window = PolarRMWindow()
    window.show()
    from ..cs2_video_settings import restore_startup_window
    restore_startup_window(window)
    _retain_window_until_close(app, window)
    if owns_app:
        raise SystemExit(app.exec())
