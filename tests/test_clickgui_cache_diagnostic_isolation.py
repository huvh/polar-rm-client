"""Ordinary cache diagnostics cannot cancel clear and compatibility fallback."""
import ast
from collections import OrderedDict
import io
import logging
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rm_client
REPO = Path(rm_client.__file__).resolve().parent.parent
WINDOW_SOURCE = REPO / 'rm_client/ui/polar_app.py'
CACHE_SOURCE = REPO / 'rm_client/ui/gui_cache.py'

class Rect:
    def __init__(self, *args):
        self.values = args[0].values if len(args) == 1 else args
    def left(self): return self.values[0]
    def top(self): return self.values[1]
    def width(self): return self.values[2]
    def height(self): return self.values[3]
    def topLeft(self): return self.values[:2]

class Image:
    Format = NS(Format_ARGB32_Premultiplied=1)
    def __init__(self, width, height, kind):
        self.size = (width, height)
        self.dpr = 1.
    def fill(self, color): self.fill_value = color
    def setDevicePixelRatio(self, dpr): self.dpr = dpr

class Painter:
    RenderHint = NS(Antialiasing=1, TextAntialiasing=2, SmoothPixmapTransform=3)
    def __init__(self, image=None):
        self.image, self.trace = image, []
        self.active = True
        self.depth = 0
        self.draw_failure = None
    def setRenderHint(self, *args): self.trace.append(('hint', *args))
    def scale(self, *args): self.trace.append(('scale', *args))
    def save(self): self.depth += 1; self.trace.append('save')
    def restore(self): self.depth -= 1; self.trace.append('restore')
    def translate(self, *args): self.trace.append(('translate', *args))
    def end(self): self.active = False; self.trace.append('end')
    def drawImage(self, point, image):
        self.trace.append(('drawImage', point, image))
        if self.draw_failure is not None:
            raise self.draw_failure


def compiled_node(source, class_name, method_name=None, **scope):
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = cls if method_name is None else next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    module = ast.Module(body=[future, node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), scope)
    return scope[method_name or class_name]


def fixture(logger=None, preference='Unified GPU'):
    trace = []
    logger = logger if logger is not None else Mock(spec=logging.Logger)
    cache_type = compiled_node(CACHE_SOURCE, 'ClickGuiLayerCache', OrderedDict=OrderedDict,
                               QRectF=Rect, QImage=Image, QPainter=Painter)
    cache = cache_type()
    clear = cache.clear
    def traced_clear():
        trace.append('clear')
        clear()
    cache.clear = traced_clear
    settings = NS(value=preference)
    host = NS(gui_cache=cache, registry=NS(get=lambda name: settings),
        setting_mode=lambda module, name, default: module.value,
        devicePixelRatioF=lambda: 1.)
    method = compiled_node(WINDOW_SOURCE, 'PolarRMWindow', 'draw_gui_cached_layer',
                           QRectF=Rect, _LOG=logger)
    host.draw = MethodType(method, host)
    host.trace, host.setting, host.logger = trace, settings, logger
    host.rect, host.painter = Rect(12, 18, 100, 70), Painter()
    host.layers = []
    return host


def failing_build(host, primary=None):
    primary = primary if primary is not None else OSError('cache build failed')
    def build(painter, bounds):
        host.trace.append('fallback' if painter is host.painter else 'cache-build')
        if painter is not host.painter:
            host.layers.append(painter)
            raise primary
    return build

class ClickGuiCacheDiagnosticTests(unittest.TestCase):
    def no_escape(self, call):
        caught = None
        try: call()
        except Exception as error: caught = error
        self.assertIsNone(caught, 'ordinary logger failure must not cancel cache fallback')

    def test_raising_logger_still_clears_retained_entries_and_paints_fallback(self):
        host = fixture(Mock(exception=Mock(side_effect=OSError('logger failed'))))
        host.gui_cache._images[('prior',)] = object()
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('new',), failing_build(host)))
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])
        self.assertEqual(host.gui_cache._images, {})
        self.assertEqual(host.setting.value, 'Unified GPU')

    def test_cached_hit_draw_failure_clears_entry_even_when_logger_raises(self):
        host = fixture(Mock(exception=Mock(side_effect=OSError('logger failed'))))
        retained = object()
        host.gui_cache._images[('key', 100, 70, 1.)] = retained
        host.painter.draw_failure = OSError('compose failed')
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('key',), failing_build(host)))
        self.assertEqual(host.trace, ['clear', 'fallback'])
        self.assertEqual(host.gui_cache._images, {})

    def test_standard_closed_stderr_does_not_cancel_fallback(self):
        stream = io.StringIO(); stream.close()
        logger = logging.Logger('closed-clickgui-probe')
        logger.addHandler(logging.StreamHandler(stream))
        host = fixture(logger)
        with patch('sys.stderr', stream), patch('logging.raiseExceptions', True):
            self.no_escape(lambda: host.draw(host.painter, host.rect, ('key',), failing_build(host)))
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])

    def test_healthy_diagnostic_preserves_restore_clear_and_fallback_order(self):
        host = fixture()
        host.draw(host.painter, host.rect, ('key',), failing_build(host))
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])
        self.assertEqual(host.layers[0].depth, 0)
        self.assertFalse(host.layers[0].active)
        self.assertEqual(host.layers[0].trace[-2:], ['restore', 'end'])
        host.logger.exception.assert_called_once_with('ClickGUI cache failed; using compatibility painting')

    def test_compatibility_preference_bypasses_cache_and_diagnostics(self):
        host = fixture(preference='Compatibility Painter')
        host.gui_cache.draw = Mock(side_effect=AssertionError('cache must be bypassed'))
        host.devicePixelRatioF = Mock(side_effect=AssertionError('DPR must be bypassed'))
        host.draw(host.painter, host.rect, ('key',), failing_build(host))
        self.assertEqual(host.trace, ['fallback'])
        host.logger.exception.assert_not_called()

    def test_logger_baseexception_preserves_original_prefix_and_cache_retention(self):
        for error in [KeyboardInterrupt(), SystemExit(19)]:
            with self.subTest(kind=type(error).__name__):
                host = fixture(Mock(exception=Mock(side_effect=error)))
                host.gui_cache._images[('prior',)] = object()
                with self.assertRaises(BaseException) as caught:
                    host.draw(host.painter, host.rect, ('new',), failing_build(host))
                self.assertIs(caught.exception, error)
                self.assertEqual(host.trace, ['cache-build'])
                self.assertIn(('prior',), host.gui_cache._images)
                self.assertFalse(host.layers[0].active)

    def test_failed_cache_clear_propagates_and_does_not_invoke_fallback(self):
        host = fixture()
        error = OSError('clear failed')
        host.gui_cache.clear = Mock(side_effect=error)
        with self.assertRaises(Exception) as caught:
            host.draw(host.painter, host.rect, ('key',), failing_build(host))
        self.assertIs(caught.exception, error)
        self.assertEqual(host.trace, ['cache-build'])

    def test_fallback_builder_failure_propagates_after_clear(self):
        host = fixture()
        error = OSError('fallback failed')
        first = failing_build(host)
        def build(painter, bounds):
            first(painter, bounds)
            raise error
        with self.assertRaises(Exception) as caught:
            host.draw(host.painter, host.rect, ('key',), build)
        self.assertIs(caught.exception, error)
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])
        self.assertEqual(host.gui_cache._images, {})

    def test_logger_attribute_lookup_failure_still_runs_clear_then_fallback(self):
        class BrokenLogger:
            @property
            def exception(self):
                raise OSError('logger lookup failed')
        host = fixture(BrokenLogger())
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('key',), failing_build(host)))
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])

    def test_healthy_logger_observes_original_exception_before_cache_clear(self):
        host = fixture()
        primary = OSError('original cache error')
        host.gui_cache._images[('prior',)] = object()
        observed = []
        def log(message):
            host.trace.append('log')
            observed.append((message, sys.exc_info()[1], tuple(host.gui_cache._images)))
        host.logger.exception = log
        host.draw(host.painter, host.rect, ('new',), failing_build(host, primary))
        self.assertEqual(host.trace, ['cache-build', 'log', 'clear', 'fallback'])
        self.assertEqual(observed, [('ClickGUI cache failed; using compatibility painting', primary, (('prior',),))])

    def test_failed_logger_does_not_change_preference_or_prevent_next_frame_rebuild(self):
        host = fixture(Mock(exception=Mock(side_effect=OSError('logger failed'))))
        host.gui_cache._images[('prior',)] = object()
        calls = []
        def build(painter, bounds):
            calls.append(painter)
            if len(calls) == 1:
                raise OSError('first cache build failed')
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('key',), build))
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[1], host.painter)
        self.assertEqual(host.gui_cache._images, {})
        self.assertEqual(host.setting.value, 'Unified GPU')
        host.draw(host.painter, host.rect, ('key',), build)
        self.assertEqual(len(calls), 3)
        image = next(iter(host.gui_cache._images.values()))
        host.draw(host.painter, host.rect, ('key',), build)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(host.gui_cache._images), 1)
        self.assertIs(host.painter.trace[-1][-1], image)
        self.assertEqual(host.setting.value, 'Unified GPU')

    def test_dpr_lookup_error_remains_cache_failure_with_ordinary_logger_isolation(self):
        host = fixture(Mock(exception=Mock(side_effect=OSError('logger failed'))))
        host.devicePixelRatioF = Mock(side_effect=OSError('DPR unavailable'))
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('key',), failing_build(host)))
        self.assertEqual(host.trace, ['clear', 'fallback'])
        self.assertEqual(host.layers, [])

    def test_successful_cache_preserves_coordinates_dpr_copy_and_hit_reuse(self):
        host = fixture()
        host.devicePixelRatioF = lambda: 1.5
        builds = []
        def build(painter, bounds):
            builds.append((painter, bounds))
        host.draw(host.painter, host.rect, ('key',), build)
        self.assertEqual(len(builds), 1)
        layer, bounds = builds[0]
        self.assertIsNot(bounds, host.rect)
        self.assertEqual(bounds.values, host.rect.values)
        self.assertIn(('scale', 1.5, 1.5), layer.trace)
        self.assertIn(('translate', -12, -18), layer.trace)
        self.assertEqual(layer.trace[-2:], ['restore', 'end'])
        image = next(iter(host.gui_cache._images.values()))
        self.assertEqual((image.size, image.dpr), ((150, 105), 1.5))
        self.assertEqual(host.painter.trace, [('drawImage', (12, 18), image)])
        host.draw(host.painter, host.rect, ('key',), build)
        self.assertEqual(len(builds), 1)
        host.logger.exception.assert_not_called()
        self.assertEqual(host.trace, [])

    def test_empty_cache_bounds_keep_existing_no_build_or_diagnostic_behavior(self):
        host = fixture()
        build = Mock()
        host.draw(host.painter, Rect(0, 0, .5, 20), ('key',), build)
        build.assert_not_called()
        host.logger.exception.assert_not_called()
        self.assertEqual(host.trace, [])
        self.assertEqual(host.painter.trace, [])

    def test_cache_build_baseexception_retains_identity_restore_end_and_no_fallback(self):
        for error in [KeyboardInterrupt(), SystemExit(31)]:
            with self.subTest(kind=type(error).__name__):
                host = fixture()
                host.gui_cache._images[('prior',)] = object()
                with self.assertRaises(BaseException) as caught:
                    host.draw(host.painter, host.rect, ('new',), failing_build(host, error))
                self.assertIs(caught.exception, error)
                self.assertEqual(host.trace, ['cache-build'])
                self.assertEqual(host.layers[0].trace[-2:], ['restore', 'end'])
                self.assertIn(('prior',), host.gui_cache._images)
                host.logger.exception.assert_not_called()

    def test_clear_failure_after_broken_logger_preserves_clear_exception_identity(self):
        host = fixture(Mock(exception=Mock(side_effect=OSError('logger failed'))))
        error = OSError('clear failed')
        def clear():
            host.trace.append('clear')
            raise error
        host.gui_cache.clear = clear
        with self.assertRaises(Exception) as caught:
            host.draw(host.painter, host.rect, ('key',), failing_build(host))
        self.assertIs(caught.exception, error)
        self.assertEqual(host.trace, ['cache-build', 'clear'])

    def test_fallback_failure_after_broken_logger_preserves_fallback_exception_identity(self):
        host = fixture(Mock(exception=Mock(side_effect=OSError('logger failed'))))
        error = OSError('fallback failed')
        first = failing_build(host)
        def build(painter, bounds):
            first(painter, bounds)
            raise error
        with self.assertRaises(Exception) as caught:
            host.draw(host.painter, host.rect, ('key',), build)
        self.assertIs(caught.exception, error)
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])

    def test_reentrant_logger_keeps_log_before_clear_publication_order(self):
        host = fixture()
        def log(message):
            host.trace.append('log')
            host.draw(host.painter, host.rect, ('nested',), lambda p, r: host.trace.append('nested-build'))
            self.assertIn(('nested', 100, 70, 1.), host.gui_cache._images)
            raise OSError('logger failed after reentry')
        host.logger.exception = log
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('outer',), failing_build(host)))
        self.assertEqual(host.trace, ['cache-build', 'log', 'nested-build', 'clear', 'fallback'])
        self.assertEqual(host.gui_cache._images, {})
        self.assertEqual(host.setting.value, 'Unified GPU')

    def test_primary_error_rendering_failure_inside_logger_cannot_cancel_recovery(self):
        class BrokenTextError(Exception):
            def __str__(self):
                raise ValueError('rendering failed')
        primary = BrokenTextError()
        host = fixture()
        calls = []
        def log(message):
            calls.append(sys.exc_info()[1])
            str(calls[-1])
        host.logger.exception = log
        self.no_escape(lambda: host.draw(host.painter, host.rect, ('key',), failing_build(host, primary)))
        self.assertEqual(calls, [primary])
        self.assertEqual(host.trace, ['cache-build', 'clear', 'fallback'])

if __name__ == '__main__': unittest.main(verbosity=2)
