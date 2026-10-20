# region_select.py — "drag out a part of the screen", for systems that have no built-in tool NOVA can wait for
# (on the Mac that is `screencapture -i`; Windows has none).
#
# The screen the mouse is on is photographed once and shown frozen and slightly dimmed, edge to edge. The part
# you drag over is saved as a picture. Esc or a right-click cancels.
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QRectF, Signal
from PySide6.QtGui import QGuiApplication, QCursor, QPainter, QColor, QPen

MIN_SIDE = 6            # smaller than this is a stray click, not a selection


class RegionOverlay(QWidget):
    done = Signal(str)                  # the picture's path, or "" when cancelled

    def __init__(self, path: str, shot=None, geometry: QRect = None):
        """`shot` and `geometry` are for the tests; normally the screen under the mouse is used."""
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self._path = path
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._shot = shot if shot is not None else screen.grabWindow(0)
        self._origin = None
        self._sel = QRect()
        self._finished = False
        self.setGeometry(geometry or screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def start(self) -> None:
        self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    # ── from widget points to the picture's own pixels (they differ on a scaled display) ──
    def _in_shot(self, r: QRect) -> QRect:
        sx = self._shot.width() / max(1, self.width()); sy = self._shot.height() / max(1, self.height())
        return QRect(round(r.x() * sx), round(r.y() * sy), round(r.width() * sx), round(r.height() * sy))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self._shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 96))
        if not self._sel.isEmpty():
            p.drawPixmap(QRectF(self._sel), self._shot, QRectF(self._in_shot(self._sel)))          # the chosen part, undimmed
            p.setPen(QPen(QColor(255, 255, 255), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._sel.adjusted(0, 0, -1, -1))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = e.position().toPoint(); self._sel = QRect()
        else:
            self._finish("")

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            a, b = self._origin, e.position().toPoint()
            self._sel = QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(a.x() - b.x()), abs(a.y() - b.y())).intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._origin is None: return
        sel, self._origin = self._sel, None
        if sel.width() < MIN_SIDE or sel.height() < MIN_SIDE:
            self._finish(""); return
        ok = self._shot.copy(self._in_shot(sel)).save(self._path, "PNG")
        self._finish(self._path if ok else "")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape: self._finish("")

    def closeEvent(self, e):
        self._finish("", close=False)            # closed some other way: that is a cancel, too
        super().closeEvent(e)

    def _finish(self, path: str, close: bool = True) -> None:
        if self._finished: return
        self._finished = True
        self.done.emit(path)
        if close: self.close()
