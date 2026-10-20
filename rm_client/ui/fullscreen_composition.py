"""Windows-only guard for Qt's documented fullscreen OpenGL/DWM limitation.

Qt recommends a native one-pixel WS_BORDER for fullscreen OpenGL windows:
https://doc.qt.io/qt-6/windows-issues.html#fullscreen-opengl-based-windows
This preserves the renderer and Qt's screen selection/normal-window restore.
It is a compatibility workaround, not a GPU/driver qualification result.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import logging
import sys

from PySide6.QtCore import QEvent, QObject, QTimer


_LOG = logging.getLogger(__name__)
_GWL_STYLE = -16
_WS_BORDER = 0x00800000


@lru_cache(maxsize=1)
def _window_style_functions():
    """Use the pointer-width ABI, including Windows' 32-bit API aliases."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8
    suffix = "LongPtrW" if is_64_bit else "LongW"
    long_type = ctypes.c_ssize_t if is_64_bit else ctypes.c_int32
    getter = getattr(user32, "GetWindow" + suffix)
    setter = getattr(user32, "SetWindow" + suffix)
    getter.argtypes = (ctypes.c_void_p, ctypes.c_int)
    getter.restype = long_type
    setter.argtypes = (ctypes.c_void_p, ctypes.c_int, long_type)
    setter.restype = long_type
    return getter, setter


def _checked_style_call(function, *args):
    # A zero previous style is a valid success; only last-error disambiguates.
    ctypes.set_last_error(0)
    result = function(*args)
    error = ctypes.get_last_error()
    if result == 0 and error:
        raise OSError(error, "Windows fullscreen style operation failed")
    return result


def _ensure_native_border(hwnd: int) -> bool:
    """Set just WS_BORDER; return whether a native style change was needed."""
    getter, setter = _window_style_functions()
    style = _checked_style_call(getter, hwnd, _GWL_STYLE)
    if style & _WS_BORDER:
        return False
    _checked_style_call(setter, hwnd, _GWL_STYLE, style | _WS_BORDER)
    if not _checked_style_call(getter, hwnd, _GWL_STYLE) & _WS_BORDER:
        raise OSError("Windows did not retain the fullscreen composition border")
    # Deliberately follow Qt's SetWindowLongPtr-only workaround. Forcing a
    # SWP_FRAMECHANGED resize here disagrees with Qt's private fullscreen
    # margins and can make Qt infer that the window has left fullscreen.
    return True


class _FullscreenCompositionGuard(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        host.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.host and event.type() in (
            QEvent.Type.WinIdChange,
            QEvent.Type.WindowStateChange,
            QEvent.Type.Show,
        ):
            # Qt rewrites the style during state transitions. Wait until the
            # transition finishes, and re-read both state and handle then.
            self.timer.start(0)
        return False

    def apply(self):
        self.timer.stop()
        host = self.host
        if not host.isVisible() or not host.isFullScreen() or host.isMinimized():
            return
        # internalWinId never forces creation/recreation during teardown.
        hwnd = int(host.internalWinId() or 0)
        if not hwnd:
            return
        try:
            _ensure_native_border(hwnd)
        except (OSError, AttributeError) as exc:
            # Leave the window usable and report an unsupported/failed guard.
            # No renderer preference, refresh rate or control gate is changed.
            _LOG.warning("Windows fullscreen composition guard failed: %s", exc)


def install_fullscreen_composition_guard(host):
    """Install once on this host, and leave other platforms/windows alone."""
    if sys.platform != "win32":
        return None
    guard = getattr(host, "_fullscreen_composition_guard", None)
    if guard is None:
        guard = _FullscreenCompositionGuard(host)
        host._fullscreen_composition_guard = guard
    return guard


class FullscreenDialogGuard(QObject):
    """Keep an owned modal from demoting its fullscreen OpenGL parent.

    A Windows activation/style notification can report a normal window while
    showing a native dialog. Repair only that unintended transition, not an
    explicit F11/settings change, minimization, or a dialog that already closed.
    The saved normal geometry belongs to the host and is never recaptured here.
    """

    def __init__(self, host, dialog):
        super().__init__(dialog)
        self.host = host
        self.dialog = dialog
        self.generation = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._restore)
        dialog.installEventFilter(self)
        host.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.dialog:
            if event.type() == QEvent.Type.Show:
                self.generation = (getattr(self.host, "_fullscreen_request_generation", 0)
                                   if self.host.isFullScreen() else None)
                self.timer.start(0)
            elif event.type() == QEvent.Type.Hide:
                self.generation = None
                self.timer.stop()
        elif watched is self.host and event.type() == QEvent.Type.WindowStateChange:
            if self.dialog.isVisible() and self.host.isFullScreen():
                self.generation = getattr(self.host, "_fullscreen_request_generation", 0)
            if self.generation is not None:
                self.timer.start(0)
        return False

    def _restore(self):
        if (self.generation is None or not self.dialog.isVisible()
                or not self.host.isVisible() or self.host.isMinimized()
                or bool(getattr(getattr(self.host, "_window_lifecycle", None), "closing", False))
                or self.generation != getattr(self.host, "_fullscreen_request_generation", 0)):
            return
        if not self.host.isFullScreen():
            self.host.showFullScreen()
        guard = install_fullscreen_composition_guard(self.host)
        if guard is not None:
            guard.apply()
