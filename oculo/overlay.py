"""Overlay: dibuja las detecciones encima de la imagen.

Recibe la imagen (array BGR) y la lista de detecciones, y devuelve un QImage
listo para mostrar en la ventana. Se dibuja con QPainter (el "pincel" de Qt)
porque da bordes suavizados y texto nítido, mejor que cv2.putText.

Importante: el overlay se pinta sobre una COPIA de la imagen dentro del
visor de la app. No se dibuja nada encima de otras ventanas.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from .config import Settings
from .inference import Detection

# Paleta para "un color por clase". Se recorre en bucle si hay más clases.
CLASS_PALETTE = [
    "#8B7CFF", "#3DDC97", "#FFB454", "#FF6B8B", "#4CC9F0",
    "#F4E04D", "#C77DFF", "#5EEAD4", "#FF8FA3", "#A3E635",
]


def to_qimage(frame: np.ndarray) -> QImage:
    """Array BGR de NumPy -> QImage.

    QImage no copia los datos por defecto: solo apunta a la memoria del
    array. Con .copy() nos aseguramos de que la imagen sigue siendo válida
    aunque el array se libere o se reutilice en el siguiente fotograma.
    """
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, 3 * w, QImage.Format.Format_BGR888).copy()


def _draw_corners(p: QPainter, r: QRectF) -> None:
    """Dibuja solo las cuatro esquinas de la caja (estilo "visor")."""
    length = max(6.0, min(r.width(), r.height()) * 0.22)
    for cx, cy, dx, dy in (
        (r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
        (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1),
    ):
        p.drawLine(QPointF(cx, cy), QPointF(cx + dx * length, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * length))


def render(
    frame: np.ndarray,
    detections: list[Detection],
    s: Settings,
    stats_text: str = "",
) -> QImage:
    """Devuelve la imagen con cajas, etiquetas, centros y estadísticas."""
    image = to_qimage(frame)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # El tamaño del texto se adapta a la imagen para que se lea igual de bien
    # en una zona de 320 px que en un vídeo 4K.
    font = QFont()
    font.setPixelSize(max(11, image.height() // 45))
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    metrics = p.fontMetrics()

    for d in detections:
        color = QColor(
            CLASS_PALETTE[d.class_id % len(CLASS_PALETTE)] if s.color_by_class else s.box_color
        )
        rect = QRectF(d.x1, d.y1, d.width, d.height)

        # --- Caja ---
        pen = QPen(color, s.box_thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if s.box_style == "full":
            p.drawRoundedRect(rect, 3, 3)
        else:
            _draw_corners(p, rect)

        # --- Etiqueta (nombre y/o confianza) ---
        parts = []
        if s.show_labels:
            parts.append(d.class_name)
        if s.show_confidence:
            parts.append(f"{d.confidence * 100:.0f}%")
        if parts:
            text = "  ".join(parts)
            tw, th = metrics.horizontalAdvance(text) + 12, metrics.height() + 4
            # Encima de la caja; si no cabe (caja pegada arriba), por dentro.
            ty = rect.top() - th - 3 if rect.top() - th - 3 >= 0 else rect.top() + 3
            pill = QRectF(rect.left(), ty, tw, th)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(pill, th / 2, th / 2)
            p.setPen(QColor("#0B0B10"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)

        # --- Centro de la caja ---
        if s.show_center:
            p.setPen(QPen(QColor("#0B0B10"), 1))
            p.setBrush(color)
            p.drawEllipse(QPointF(d.cx, d.cy), 3.5, 3.5)
        if s.show_coords:
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QPointF(d.cx + 7, d.cy + metrics.ascent() / 2),
                       f"({d.cx:.0f}, {d.cy:.0f})")

    # --- Estadísticas en la esquina ---
    if s.show_stats and stats_text:
        tw, th = metrics.horizontalAdvance(stats_text) + 16, metrics.height() + 8
        box = QRectF(8, 8, tw, th)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(11, 11, 16, 190))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("#EDEDF4"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, stats_text)

    p.end()
    return image
