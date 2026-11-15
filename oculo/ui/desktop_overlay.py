"""Transparent FOV on the selected monitor, not painted into the preview."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .native_window import configure_overlay


class DesktopOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.radius = 180.

    def configure(self, bounds, radius, visible):
        if not visible or bounds is None:
            self.hide()
            return
        self.radius = radius
        x, y, w, h = bounds
        self.setGeometry(round(x), round(y), round(w), round(h))
        if not self.isVisible():
            # Create the native NSPanel and configure it before showing it.
            self.winId()
            configure_overlay(self)
            self.show()
            # Qt can update collection behavior when ordering its window in.
            configure_overlay(self)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width()/2, self.height()/2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # One logical point maps automatically to the screen devicePixelRatio.
        for color, width in ((QColor(0, 0, 0, 180), 3), (QColor("#54DCC0"), 1)):
            p.setPen(QPen(color, width))
            p.drawEllipse(center, self.radius, self.radius)
            p.drawLine(center+QPointF(-7,0), center+QPointF(7,0))
            p.drawLine(center+QPointF(0,-7), center+QPointF(0,7))
        p.end()
