"""Registro de datos: guarda cada detección como una fila de un CSV.

Sirve para estudiar la salida del modelo con números: abre el archivo en
Numbers/Excel, o cárgalo con pandas, y mira cómo cambian las coordenadas y
la confianza de un fotograma a otro.

Columnas
--------
time_s      segundos desde que empezó la sesión
frame       número de fotograma analizado
model       archivo del modelo usado
class_id    número de clase            class_name  nombre de la clase
confidence  puntuación de 0 a 1
x1,y1,x2,y2 esquinas de la caja (píxeles de la imagen analizada)
cx,cy       CENTRO de la caja (píxeles de la imagen analizada)
w,h         ancho y alto de la caja
cx_norm,cy_norm  centro normalizado de 0 a 1 (independiente de la resolución)

El origen (0, 0) es la esquina superior izquierda de la imagen analizada,
con X hacia la derecha e Y hacia abajo (convención habitual en imagen).
"""

from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

from .inference import Detection

HEADER = [
    "time_s", "frame", "model", "class_id", "class_name", "confidence",
    "x1", "y1", "x2", "y2", "cx", "cy", "w", "h", "cx_norm", "cy_norm",
]


class DataLogger:
    """Abre un CSV nuevo por sesión y va añadiendo filas."""

    def __init__(self, folder: Path):
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = folder / f"detecciones_{stamp}.csv"
        # newline="" es lo que pide el módulo csv para no duplicar saltos.
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(HEADER)
        self._start = time.perf_counter()
        self.rows = 0

    def write(
        self,
        frame_index: int,
        model: str,
        detections: list[Detection],
        frame_w: int,
        frame_h: int,
    ) -> None:
        elapsed = round(time.perf_counter() - self._start, 4)
        for d in detections:
            self._writer.writerow([
                elapsed, frame_index, model, d.class_id, d.class_name,
                round(d.confidence, 4),
                round(d.x1, 1), round(d.y1, 1), round(d.x2, 1), round(d.y2, 1),
                round(d.cx, 1), round(d.cy, 1),
                round(d.width, 1), round(d.height, 1),
                round(d.cx / frame_w, 5), round(d.cy / frame_h, 5),
            ])
            self.rows += 1

    def close(self) -> None:
        self._file.close()
