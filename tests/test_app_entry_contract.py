"""The legacy module path launches Qt without loading the retained Tk client."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ApplicationEntryContractTests(unittest.TestCase):
    def run_isolated(self, source: str) -> None:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_import_and_discovery_do_not_load_a_gui_or_devices(self):
        self.run_isolated('''
            import importlib.abc
            import sys

            class RejectRuntimeImports(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.startswith(("tkinter", "PySide6", "rm_client.ui",
                                            "rm_client.legacy_tk_app",
                                            "rm_client.transports", "rm_client.model")):
                        raise AssertionError("unexpected eager dependency: " + fullname)

            sys.meta_path.insert(0, RejectRuntimeImports())
            from rm_client import app
            assert callable(app.main)
            assert "RMClientApp" in dir(app)
            try:
                app.unknown_legacy_symbol
            except AttributeError as error:
                assert "unknown_legacy_symbol" in str(error)
            else:
                raise AssertionError("unknown attributes must not load the Tk client")
        ''')

    def test_function_entry_calls_qt_exactly_once(self):
        self.run_isolated('''
            import sys
            import types
            calls = []
            qt_entry = types.ModuleType("rm_client.ui.polar_app")
            qt_entry.main = lambda: calls.append("qt")
            sys.modules[qt_entry.__name__] = qt_entry
            sys.modules["tkinter"] = None
            from rm_client.app import main
            main()
            assert calls == ["qt"], calls
            assert "rm_client.legacy_tk_app" not in sys.modules
            assert "rm_client.transports" not in sys.modules
        ''')

    def test_module_entry_calls_qt_exactly_once(self):
        self.run_isolated('''
            import runpy
            import sys
            import types
            calls = []
            qt_entry = types.ModuleType("rm_client.ui.polar_app")
            qt_entry.main = lambda: calls.append("qt")
            sys.modules[qt_entry.__name__] = qt_entry
            sys.modules["tkinter"] = None
            runpy.run_module("rm_client.app", run_name="__main__")
            assert calls == ["qt"], calls
            assert "rm_client.legacy_tk_app" not in sys.modules
        ''')

    def test_qt_failure_remains_visible_without_legacy_fallback(self):
        self.run_isolated('''
            import sys
            import types
            failure = RuntimeError("injected Qt construction failure")
            qt_entry = types.ModuleType("rm_client.ui.polar_app")
            def fail():
                raise failure
            qt_entry.main = fail
            sys.modules[qt_entry.__name__] = qt_entry
            sys.modules["tkinter"] = None
            from rm_client.app import main
            try:
                main()
            except RuntimeError as error:
                assert error is failure
            else:
                raise AssertionError("startup failure was swallowed")
            assert "rm_client.legacy_tk_app" not in sys.modules
        ''')

    def test_qt_exit_status_is_preserved(self):
        self.run_isolated('''
            import runpy
            import sys
            import types
            qt_entry = types.ModuleType("rm_client.ui.polar_app")
            def finish():
                raise SystemExit(7)
            qt_entry.main = finish
            sys.modules[qt_entry.__name__] = qt_entry
            runpy.run_module("rm_client.app", run_name="test_import_only")
            try:
                runpy.run_module("rm_client.app", run_name="__main__")
            except SystemExit as error:
                assert error.code == 7, error.code
            else:
                raise AssertionError("Qt event-loop exit status was lost")
        ''')

    def test_existing_qt_application_owns_windows_until_they_close(self):
        self.run_isolated('''
            import gc
            import os
            import sys
            import types
            import weakref
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtWidgets import QApplication, QWidget
            from rm_client.ui.polar import app_entry
            import rm_client.ui.cs2_video_settings as video
            app = QApplication([])
            app.setQuitOnLastWindowClosed(False)
            references = []
            class Window(QWidget):
                def __init__(self):
                    super().__init__()
                    references.append(weakref.ref(self))
            qt_entry = types.ModuleType("rm_client.ui.polar_app")
            qt_entry.PolarRMWindow = Window
            sys.modules[qt_entry.__name__] = qt_entry
            video.restore_startup_window = lambda window: None
            app_entry.main()
            app_entry.main()
            gc.collect()
            assert len(app.topLevelWidgets()) == 2
            assert all(reference() is not None for reference in references)
            references[0]().close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            gc.collect()
            assert references[0]() is None, "closed window is retained"
            assert references[1]() is not None, "closing one window lost the other"
            references[1]().close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            gc.collect()
            assert references[1]() is None
            assert not app.topLevelWidgets()
        ''')

    def test_owned_qt_application_preserves_event_loop_exit_code(self):
        self.run_isolated('''
            import os
            import sys
            import types
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QWidget
            from rm_client.ui.polar import app_entry
            import rm_client.ui.cs2_video_settings as video
            assert QApplication.instance() is None
            class Window(QWidget):
                def __init__(self):
                    super().__init__()
                    QTimer.singleShot(0, lambda: QApplication.instance().exit(7))
            qt_entry = types.ModuleType("rm_client.ui.polar_app")
            qt_entry.PolarRMWindow = Window
            sys.modules[qt_entry.__name__] = qt_entry
            video.configure_surface = lambda surface: None
            video.restore_startup_window = lambda window: None
            try:
                app_entry.main()
            except SystemExit as error:
                assert error.code == 7
            else:
                raise AssertionError("owned application did not run its event loop")
        ''')

    def test_legacy_exports_are_lazy_and_keep_the_same_objects(self):
        self.run_isolated('''
            import sys
            import types
            from rm_client import app
            assert "rm_client.legacy_tk_app" not in sys.modules
            # No display or hardware is required to verify the legacy boundary.
            tkinter = types.ModuleType("tkinter")
            tkinter.font = types.ModuleType("tkinter.font")
            sys.modules["tkinter"] = tkinter
            sys.modules["tkinter.font"] = tkinter.font
            from rm_client.app import RMClientApp, BG, clamp, lerp
            from rm_client import legacy_tk_app
            assert RMClientApp is legacy_tk_app.RMClientApp
            assert app.RMClientApp is RMClientApp
            assert BG == legacy_tk_app.BG
            assert clamp is legacy_tk_app.clamp and clamp(5, 0, 3) == 3
            assert lerp is legacy_tk_app.lerp and lerp(0, 10, .25) == 2.5
            assert "PySide6" not in sys.modules
        ''')


if __name__ == "__main__":
    unittest.main()
