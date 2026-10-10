"""Native QPainter checks. Default requires PySide6; no installation happens.

For the explicit Qt5 compatibility-only review: TOP_MATCH_BAR_QT5_PREVIEW=1
/usr/bin/python3 -m unittest discover -s tests -p top_match_bar_qt_test.py -v
"""
import os
import sys
import unittest
from unittest.mock import patch
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QT_AVAILABLE = False
if os.environ.get("TOP_MATCH_BAR_QT5_PREVIEW") == "1":
    import PyQt5
    from PyQt5 import QtCore, QtGui, QtWidgets
    for module, value in (("PySide6", PyQt5), ("PySide6.QtCore", QtCore), ("PySide6.QtGui", QtGui)):
        sys.modules[module] = value
    QT_AVAILABLE = True
else:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        QT_AVAILABLE = True
    except ImportError:
        pass
if QT_AVAILABLE:
    from rm_client.top_match_bar import LifeState as L, MatchBarFrame, RobotCard, TeamStrip
    from rm_client.ui.top_match_bar import TopMatchBarOptions, TopMatchBarRenderer


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed; production binding not verified")
class NativePainterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.renderer = TopMatchBarRenderer()
        self.frame = MatchBarFrame(TeamStrip("Blue", (RobotCard(103, "3", L.ALIVE, 2, "103", True),), 0),
                                   TeamStrip("Red", (RobotCard(3, "3", L.DEAD, 1),), 3), 85, "RM SCORE", "MATCH")

    def render(self, frame=None, options=None, width=600, dpr=1, opacity=1, now=10, avatars=None):
        image = QtGui.QImage(width * dpr, 150 * dpr, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setOpacity(opacity)
        layout = self.renderer.paint(painter, frame or self.frame, width, now=now,
                                     options=options or TopMatchBarOptions(scale=1, reduced_motion=True), avatars=avatars)
        painter.end()
        return image, layout

    def test_actual_nonempty_native_image(self):
        image, layout = self.render()
        self.assertGreater(image.pixelColor(300, 30).alpha(), 0)
        self.assertIsNotNone(layout)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(300, 140).alpha(), 0)

    def test_disabled_returns_empty_and_clears_motion(self):
        self.render()
        self.assertTrue(self.renderer._transitions)
        image, layout = self.render(options=TopMatchBarOptions(enabled=False))
        self.assertIsNone(layout)
        self.assertFalse(self.renderer._transitions)
        self.assertEqual(image.pixelColor(300, 30).alpha(), 0)

    def test_painter_state_is_restored(self):
        image = QtGui.QImage(600, 200, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(image)
        p.translate(7, 9)
        p.setOpacity(.6)
        p.setPen(QtGui.QPen(QtGui.QColor("red"), 3))
        p.setFont(QtGui.QFont("DejaVu Sans", 11))
        p.setClipRect(QtCore.QRectF(2, 3, 580, 180))
        before = (p.transform(), p.opacity(), p.pen(), p.font(), p.clipBoundingRect(), p.renderHints())
        self.renderer.paint(p, self.frame, 600, now=10)
        after = (p.transform(), p.opacity(), p.pen(), p.font(), p.clipBoundingRect(), p.renderHints())
        p.end()
        self.assertEqual(before, after)

    def test_parent_opacity_respected_for_avatar(self):
        full, layout = self.render()
        half, _ = self.render(opacity=.5)
        rect = layout.left_cards[0]
        x, y = round(rect.x + 35), round(rect.y + 35)
        self.assertLess(half.pixelColor(x, y).alpha(), full.pixelColor(x, y).alpha())

    def test_skull_failure_restores_caller_painter_state(self):
        image = QtGui.QImage(600, 200, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(image)
        p.translate(7, 9)
        p.setOpacity(.6)
        p.setClipRect(QtCore.QRectF(2, 3, 580, 180))
        before = (p.transform(), p.opacity(), p.pen(), p.font(), p.clipBoundingRect(), p.renderHints())
        try:
            with patch("rm_client.ui.top_match_bar._skull", side_effect=RuntimeError("glyph failed")):
                with self.assertRaises(RuntimeError):
                    self.renderer.paint(p, self.frame, 600, now=10)
            after = (p.transform(), p.opacity(), p.pen(), p.font(), p.clipBoundingRect(), p.renderHints())
            self.assertEqual(before, after)
        finally:
            p.end()

    def test_skull_internal_failure_restores_its_own_painter_frame(self):
        from rm_client.ui.top_match_bar import _skull
        image = QtGui.QImage(40, 40, QtGui.QImage.Format_ARGB32_Premultiplied)
        p = QtGui.QPainter(image)
        class FailingPainter:
            def __getattr__(self, name):
                if name == "drawLine":
                    raise RuntimeError("glyph line failed")
                return getattr(p, name)
        before = (p.transform(), p.opacity(), p.pen(), p.brush())
        try:
            with self.assertRaises(RuntimeError):
                _skull(FailingPainter(), 3, 5, 12, QtGui.QColor("white"))
            self.assertEqual(before, (p.transform(), p.opacity(), p.pen(), p.brush()))
        finally:
            p.end()

    def test_unknown_and_dead_are_visually_different(self):
        dead, _ = self.render()
        unknown_frame = replace(self.frame, right=TeamStrip("Red", (RobotCard(3, "3", L.UNKNOWN),)))
        unknown, _ = self.render(unknown_frame)
        self.assertNotEqual(dead, unknown)

    def test_death_changes_immediately_without_invented_crossfade(self):
        options = TopMatchBarOptions(scale=1)
        alive, _ = self.render(options=options, now=10)
        dead_frame = replace(self.frame, left=TeamStrip("Blue", (RobotCard(103, "3", L.DEAD),)))
        initial, _ = self.render(dead_frame, options, now=10.01)
        repeat, _ = self.render(dead_frame, options, now=10.60)
        self.assertNotEqual(alive, initial)
        self.assertEqual(initial, repeat)

    def test_source_kill_pop_affects_only_new_skull_and_settles(self):
        options = TopMatchBarOptions(scale=1, reduced_motion=False)
        self.render(options=options, now=10)
        frame = replace(self.frame, left=TeamStrip("Blue", (RobotCard(103, "3", L.ALIVE, 3, "103", True),)))
        initial, _ = self.render(frame, options, now=10.01)
        middle, _ = self.render(frame, options, now=10.16)
        settled, _ = self.render(frame, options, now=10.32)
        repeat, _ = self.render(frame, options, now=11)
        self.assertNotEqual(initial, middle)
        self.assertNotEqual(initial, settled)
        self.assertEqual(settled, repeat)

    def test_source_motion_requires_explicit_opt_in(self):
        options = TopMatchBarOptions(scale=1)
        self.assertTrue(options.reduced_motion)
        self.render(options=options, now=10)
        frame = replace(self.frame, left=TeamStrip("Blue", (RobotCard(103, "3", L.ALIVE, 3, "103", True),)))
        initial, _ = self.render(frame, options, now=10.01)
        settled, _ = self.render(frame, options, now=10.32)
        self.assertEqual(initial, settled)

    def test_reduced_motion_immediately_settles(self):
        dead_frame = replace(self.frame, left=TeamStrip("Blue", (RobotCard(103, "3", L.DEAD),)))
        self.render()
        a, _ = self.render(dead_frame, now=10.01)
        b, _ = self.render(dead_frame, now=10.30)
        self.assertEqual(a, b)

    def test_missing_or_null_avatar_falls_back_without_io(self):
        normal, _ = self.render()
        null, _ = self.render(avatars={"103": QtGui.QImage()})
        self.assertEqual(normal, null)

    def test_extreme_avatar_is_cropped_before_resizing(self):
        square = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32_Premultiplied)
        square.fill(QtGui.QColor("red"))
        class ExtremeAvatar:
            cacheKey = lambda self: 987654
            isNull = lambda self: False
            width = lambda self: 1
            height = lambda self: 100000
            def copy(self, x, y, width, height):
                assert (x, y, width, height) == (0, 49999, 1, 1)
                return square
            def scaled(self, *args):
                raise AssertionError("must not expand the full extreme aspect ratio")
        image, gray = self.renderer._portrait(self.frame.left.cards[0], ExtremeAvatar())
        self.assertEqual((image.width(), image.height()), (140, 140))
        self.assertEqual((gray.width(), gray.height()), (140, 140))

    def test_local_flag_does_not_fabricate_a_health_bar(self):
        local, _ = self.render()
        unmarked = replace(self.frame, left=replace(self.frame.left,
                          cards=(replace(self.frame.left.cards[0], local=False),)))
        other, _ = self.render(unmarked)
        self.assertEqual(local, other)

    def test_dead_border_inherits_source_opacity(self):
        image = QtGui.QImage(80, 100, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(image)
        try:
            self.renderer._paint_card(p, RobotCard(3, "3", L.DEAD), 10, TopMatchBarOptions(), None)
        finally:
            p.end()
        self.assertGreater(image.pixelColor(1, 35).alpha(), 0)
        self.assertLess(image.pixelColor(1, 35).alpha(), 128)

    def test_dead_kill_markers_use_source_deadwhite(self):
        colors = []
        with patch("rm_client.ui.top_match_bar._skull", side_effect=lambda p, x, y, size, color: colors.append(color.name())):
            self.render()
        self.assertEqual(colors, ["#f9faf7", "#f9faf7", "#dddddd"])

    def test_cached_avatar_change_takes_effect(self):
        a = QtGui.QImage(30, 10, QtGui.QImage.Format_ARGB32_Premultiplied)
        a.fill(QtGui.QColor("red"))
        first, _ = self.render(avatars={"103": a})
        a.fill(QtGui.QColor("blue"))
        second, _ = self.render(avatars={"103": a})
        self.assertNotEqual(first, second)

    def test_dead_portrait_preserves_authorized_image_transparency(self):
        supplied = QtGui.QImage(140, 140, QtGui.QImage.Format_ARGB32_Premultiplied)
        supplied.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(supplied)
        p.fillRect(QtCore.QRectF(40, 40, 60, 60), QtGui.QColor("red"))
        p.end()
        _, gray = self.renderer._portrait(self.frame.left.cards[0], supplied)
        self.assertEqual(gray.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(gray.pixelColor(70, 70).alpha(), 255)

    def test_hi_dpi_layout_stays_in_logical_coordinates(self):
        image, layout = self.render(dpr=2)
        self.assertEqual(image.size().width(), 1200)
        self.assertEqual(layout.center.x + layout.center.width / 2, 300)

    def test_compact_mode_preserves_all_alive_counts(self):
        cards = tuple(RobotCard(i, str(i), L.ALIVE) for i in range(1, 10))
        f = MatchBarFrame(TeamStrip("Blue", cards), TeamStrip("Red", cards), 420)
        image, layout = self.render(f, width=300)
        self.assertTrue(layout.compact)
        self.assertEqual(f.left.alive_text, "9")
        self.assertGreater(image.pixelColor(150, 30).alpha(), 0)

    def test_source_reset_drops_animation_records(self):
        self.render()
        self.renderer.reset_motion()
        self.assertFalse(self.renderer._transitions)


if __name__ == "__main__":
    unittest.main()
