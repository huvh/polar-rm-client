"""Owned Windows settings/search/SC_CLOSE check with inert device transports."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]


def run(out: Path):
    if sys.platform != 'win32':
        raise RuntimeError('Requires a real Windows desktop, not Qt offscreen')
    os.environ.update(QT_QPA_PLATFORM='windows', POLAR_AUTOSTART='0', CI='true',
                      POLAR_DISABLE_LOCAL_CAPTURE='1', POLAR_DISABLE_MEDIA_PRELOAD='1')
    from PySide6.QtCore import QTimer, Qt, QEvent
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid
    from rm_client.backend.mqtt_backend import RmMqttBackend
    from rm_client.backend.serial_backend import RmSerialBackend
    from rm_client.backend.video_backend import RmVideoBackend
    from rm_client.ui.cs2_settings_center import open_settings_center
    from rm_client.ui.polar_app import PolarRMWindow
    from window_lifecycle_helpers import close_window_safely, settle_window_lifecycle
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)  # Harness must survive all three exit cases.
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.IsWindowEnabled.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'Owned Windows OpenGL + native close message; inert transports, no robot I/O', 'cases': []}

    def until(predicate, timeout=10):
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= end:
                raise TimeoutError('Settings/window owner did not retire')
            app.processEvents()
            time.sleep(.003)

    try:
        for name, fullscreen, delay in (('entrance', False, 0), ('search-ime', False, 650),
                                        ('fullscreen-search', True, 650)):
            with tempfile.TemporaryDirectory() as profile, patch.dict(os.environ, POLAR_USER_DATA_ROOT=profile), \
                 patch.object(RmMqttBackend, 'start'), patch.object(RmSerialBackend, 'start'), \
                 patch.object(RmVideoBackend, 'start'):
                window = PolarRMWindow()
                errors, settings, last_closed = [], [], []
                def closed(): last_closed.append(True)
                app.lastWindowClosed.connect(closed)
                try:
                    window.resize(1280, 720)
                    window.showFullScreen() if fullscreen else window.show()
                    window.raise_(); window.activateWindow()
                    assert QTest.qWaitForWindowExposed(window, 5000)
                    settle_window_lifecycle(window, app)
                    until(lambda: window.gpu_compositor.available)
                    def search_then_close():
                        dialog = window._settings_session
                        settings.append(dialog)
                        try:
                            dialog.search.setFocus()
                            dialog.search.setText('mouse ')
                            ime = QInputMethodEvent()
                            ime.setCommitString('鼠标')
                            app.sendEvent(dialog.search, ime)
                            assert '鼠标' in dialog.search.text()
                            assert QApplication.activeModalWidget() is None
                            assert user.IsWindowEnabled(int(window.winId())), 'Native host close button is disabled'
                            assert not window.combat_control_input_allowed()
                            assert window.isFullScreen() == fullscreen
                            with patch.object(window.backend, 'trigger_estop', return_value=(True, 'test-only')) as stop:
                                QTest.keyClick(dialog.search, Qt.Key_F12)
                                assert stop.call_count == 1
                            # Same system command as the client's own title-bar
                            # X. Never discover, inject or close another app.
                            assert user.PostMessageW(int(window.winId()), 0x0112, 0xF060, 0)
                        except BaseException as error:
                            errors.append(error)
                            dialog.close_for_shutdown()
                    QTimer.singleShot(delay, search_then_close)
                    open_settings_center(window)
                    if errors: raise errors[0]
                    until(lambda: window._window_close_finalized)
                    # Manual harness pumping has no outer QApplication.exec()
                    # turn to consume deleteLater queued after the local loop.
                    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    app.processEvents()
                    assert not window.isVisible()
                    assert window._settings_session is None
                    assert settings and not isValid(settings[0]), 'Settings Qt owner survived close'
                    native = window._endfield_menu
                    assert native is None or native.handle == 0
                    assert not any(w.isVisible() for w in app.topLevelWidgets())
                    assert last_closed, 'Settings kept the last application window alive'
                    report['cases'].append({'case': name, 'fullscreen': fullscreen, 'native_host_enabled': True,
                        'native_sc_close_completed': True, 'search_ime_committed': True,
                        'settings_owner_retired': True, 'native_renderer_retired': True, 'last_window_closed': True})
                finally:
                    close_window_safely(window, app)
                    app.lastWindowClosed.disconnect(closed)
                    window.deleteLater(); app.processEvents()
        report['result'] = 'PASS'
    except BaseException as error:
        report.update(result='FAIL', error_type=type(error).__name__)
        raise
    finally:
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Settings search + native host close PASS (3 Windows cases)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Requires a real Windows desktop')
    # lastWindowClosed is an application-event-loop contract, not a promise
    # made by a manual processEvents-only probe.
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    app = QApplication.instance() or QApplication([])
    failures = []
    def verify():
        try:
            run(args.out)
        except BaseException as error:
            failures.append(error)
        finally:
            app.quit()
    QTimer.singleShot(0, verify)
    app.exec()
    if failures:
        raise failures[0]
