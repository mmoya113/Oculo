"""Captura: de dónde salen las imágenes que analiza el modelo.

Hay tres fuentes (pantalla, archivo de vídeo, webcam) y todas cumplen el
mismo "contrato": un método `read(settings)` que devuelve una imagen como
array de NumPy en formato BGR (alto x ancho x 3), o None si no hay imagen.

Gracias a ese contrato el resto de la app no necesita saber de dónde viene
la imagen. Si algún día quieres añadir otra fuente (por ejemplo, una carpeta
de fotos), basta con escribir otra clase con `read()` y `close()`.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import Settings
from .aim import ScreenGeometry


def zone_rect(frame_w: int, frame_h: int, s: Settings) -> tuple[int, int, int, int]:
    """Calcula el rectángulo (x, y, ancho, alto) de la zona de detección.

    La zona va centrada en la imagen, con un desplazamiento opcional, y se
    recorta para que nunca se salga de los bordes.
    """
    if not s.zone_enabled:
        return 0, 0, frame_w, frame_h

    w = max(32, min(s.zone_width, frame_w))
    h = max(32, min(s.zone_height, frame_h))
    x = (frame_w - w) // 2 + s.zone_offset_x
    y = (frame_h - h) // 2 + s.zone_offset_y
    # "Clamp": obliga a x e y a quedarse dentro de la imagen.
    x = max(0, min(x, frame_w - w))
    y = max(0, min(y, frame_h - h))
    return x, y, w, h


class FrameSource:
    """Clase base. Solo documenta el contrato; no hace nada por sí misma."""

    def read(self, s: Settings) -> np.ndarray | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ScreenSource(FrameSource):
    """Captura de pantalla con la librería `mss`.

    Truco de rendimiento: en vez de capturar la pantalla entera y recortar
    después, le pedimos a mss SOLO el rectángulo de la zona. Capturar 640x640
    es muchísimo más rápido que capturar una pantalla Retina completa.

    Nota macOS: la primera vez el sistema pedirá permiso de "Grabación de
    pantalla". Sin ese permiso mss devuelve solo el fondo de escritorio.
    """

    def __init__(self, monitor: int = 1):
        import mss  # se importa aquí para que los tests no lo necesiten

        self.geometry = None
        self._sct = mss.mss()
        # monitors[0] es "todas las pantallas juntas"; las reales empiezan en 1.
        index = monitor if 0 < monitor < len(self._sct.monitors) else 1
        self._mon = self._sct.monitors[index]

    def read(self, s: Settings) -> np.ndarray | None:
        x, y, w, h = zone_rect(self._mon["width"], self._mon["height"], s)
        region = {
            "left": self._mon["left"] + x,
            "top": self._mon["top"] + y,
            "width": w,
            "height": h,
        }
        shot = self._sct.grab(region)
        # mss entrega BGRA (4 canales). Quitamos el canal alfa -> BGR.
        frame = np.ascontiguousarray(np.asarray(shot)[:, :, :3])
        self.geometry = ScreenGeometry(
            region["left"], region["top"], w, h, frame.shape[1], frame.shape[0],
            self._mon["left"] + self._mon["width"]/2,
            self._mon["top"] + self._mon["height"]/2,
        )
        return frame

    def close(self) -> None:
        self._sct.close()


class _CvSource(FrameSource):
    """Lógica común de vídeo y webcam: ambas usan cv2.VideoCapture."""

    def __init__(self, target, loop: bool = False):
        self._cap = cv2.VideoCapture(target)
        self._loop = loop
        if not self._cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la fuente: {target}")

    def read(self, s: Settings) -> np.ndarray | None:
        ok, frame = self._cap.read()
        if not ok and self._loop:
            # Fin del vídeo: rebobinar al primer fotograma y seguir.
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        if not ok:
            return None
        x, y, w, h = zone_rect(frame.shape[1], frame.shape[0], s)
        return np.ascontiguousarray(frame[y : y + h, x : x + w])

    def close(self) -> None:
        self._cap.release()


class VideoSource(_CvSource):
    """Archivo de vídeo (mp4, mov...). Ideal para revisar partidas grabadas."""

    def __init__(self, path: str, loop: bool = True):
        if not path:
            raise RuntimeError("Elige un archivo de vídeo primero.")
        super().__init__(path, loop=loop)


class CameraSource(_CvSource):
    """Webcam. macOS pedirá permiso de cámara la primera vez."""

    def __init__(self, index: int = 0):
        super().__init__(int(index))


def open_source(s: Settings) -> FrameSource:
    """Fábrica: crea la fuente que corresponda según los ajustes."""
    if s.source == "video":
        return VideoSource(s.video_path, loop=s.video_loop)
    if s.source == "camera":
        return CameraSource(s.camera_index)
    return ScreenSource(s.monitor)
