"""Logo de Oculo, dibujado por código.

El mismo dibujo se usa en tres sitios: la cabecera de la ventana, el icono
de la ventana y el icono .icns del .app (scripts/make_icon.py). Al estar
hecho con vectores (QPainter) se ve nítido a cualquier tamaño.

El símbolo: un visor con cuatro esquinas (una caja de detección) y un
círculo dentro (el objetivo de una cámara / una pupila).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient


def paint_logo(p: QPainter, rect: QRectF) -> None:
    """Pinta el logo dentro de `rect` (se asume cuadrado)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = rect.width()

    # Fondo: cuadrado redondeado con degradado oscuro (forma de icono macOS).
    background = QLinearGradient(rect.topLeft(), rect.bottomRight())
    background.setColorAt(0.0, QColor("#1D1B33"))
    background.setColorAt(1.0, QColor("#0B0B12"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(background)
    p.drawRoundedRect(rect, size * 0.225, size * 0.225)

    # Brillo suave detrás del símbolo.
    glow = QRadialGradient(rect.center(), size * 0.45)
    glow.setColorAt(0.0, QColor(139, 124, 255, 90))
    glow.setColorAt(1.0, QColor(139, 124, 255, 0))
    p.setBrush(glow)
    p.drawEllipse(rect.center(), size * 0.45, size * 0.45)

    # Degradado del trazo: violeta -> cian.
    stroke = QLinearGradient(rect.topLeft(), rect.bottomRight())
    stroke.setColorAt(0.0, QColor("#A99BFF"))
    stroke.setColorAt(1.0, QColor("#4CC9F0"))
    pen = QPen(stroke, size * 0.062)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Cuatro esquinas del visor.
    inner = rect.adjusted(size * 0.23, size * 0.23, -size * 0.23, -size * 0.23)
    arm = size * 0.13
    for x, y, dx, dy in (
        (inner.left(), inner.top(), 1, 1), (inner.right(), inner.top(), -1, 1),
        (inner.left(), inner.bottom(), 1, -1), (inner.right(), inner.bottom(), -1, -1),
    ):
        path = QPainterPath(QPointF(x + dx * arm, y))
        path.lineTo(x, y)
        path.lineTo(x, y + dy * arm)
        p.drawPath(path)

    # Círculo central (objetivo) y punto.
    p.drawEllipse(rect.center(), size * 0.125, size * 0.125)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(stroke)
    p.drawEllipse(rect.center(), size * 0.04, size * 0.04)
    p.restore()


def logo_pixmap(size: int) -> QPixmap:
    """Devuelve el logo como imagen con fondo transparente."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    # Margen del ~8 %: los iconos de macOS no ocupan todo el lienzo.
    margin = size * 0.08
    paint_logo(painter, QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    painter.end()
    return pixmap
