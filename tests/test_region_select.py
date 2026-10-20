"""NOVA's own "select part of the screen" overlay (used on Windows). The screen is a stand-in picture here."""
import os
import pytest
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QPixmap, QColor, QPainter, QImage
from PySide6.QtTest import QTest
import region_select


def _overlay(app, tmp_path, scale=1):
    """An overlay over a 400x300 'screen' whose picture is `scale` times as fine (a scaled display): left half red, right half blue."""
    shot = QPixmap(400 * scale, 300 * scale); shot.fill(QColor("red"))
    p = QPainter(shot); p.fillRect(200 * scale, 0, 200 * scale, 300 * scale, QColor("blue")); p.end()
    path = str(tmp_path / "part.png"); got = []
    o = region_select.RegionOverlay(path, shot=shot, geometry=QRect(0, 0, 400, 300))
    o.done.connect(got.append); o.start(); app.processEvents()
    return o, path, got


def _drag(app, o, a, b):
    QTest.mousePress(o, Qt.MouseButton.LeftButton, pos=QPoint(*a))
    QTest.mouseMove(o, QPoint(*b)); app.processEvents()
    QTest.mouseRelease(o, Qt.MouseButton.LeftButton, pos=QPoint(*b)); app.processEvents()


@pytest.mark.parametrize("scale", [1, 2])
def test_dragged_part_is_saved(app, tmp_path, scale):
    o, path, got = _overlay(app, tmp_path, scale)
    _drag(app, o, (150, 100), (250, 160))                         # 100 x 60 points, half on red and half on blue
    assert got == [path]
    img = QImage(path)
    assert (img.width(), img.height()) == (100 * scale, 60 * scale)          # every pixel of a scaled display is kept
    assert QColor(img.pixel(5, 5)) == QColor("red") and QColor(img.pixel(img.width() - 5, 5)) == QColor("blue")


def test_drag_in_any_direction_and_past_the_edge(app, tmp_path):
    o, path, got = _overlay(app, tmp_path)
    _drag(app, o, (300, 200), (-50, -50))                         # up and left, off the screen
    img = QImage(path)
    assert got == [path] and (img.width(), img.height()) == (300, 200)


def test_escape_right_click_and_a_stray_click_cancel(app, tmp_path):
    o, path, got = _overlay(app, tmp_path)
    QTest.keyClick(o, Qt.Key.Key_Escape); app.processEvents()
    assert got == [""] and not os.path.exists(path)
    o, path, got = _overlay(app, tmp_path)
    QTest.mouseClick(o, Qt.MouseButton.RightButton, pos=QPoint(10, 10)); app.processEvents()
    assert got == [""]
    o, path, got = _overlay(app, tmp_path)
    _drag(app, o, (100, 100), (102, 101))                          # not a selection
    assert got == [""] and not os.path.exists(path)
    o, path, got = _overlay(app, tmp_path)
    o.close(); app.processEvents()
    assert got == [""]                                             # answered exactly once, whatever closes it
