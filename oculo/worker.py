"""Worker: el hilo que une captura -> inferencia -> overlay -> log.

¿Por qué un hilo aparte? La interfaz de Qt vive en el hilo principal. Si
ejecutásemos el modelo ahí, la ventana se quedaría congelada en cada
fotograma. Con un QThread el trabajo pesado va por separado y la interfaz
sigue fluida.

Comunicación entre hilos
------------------------
* Interfaz -> worker: `update_settings()` entrega una copia de los ajustes,
  protegida con un candado (Lock) para que no se lea a medio escribir.
* Worker -> interfaz: señales de Qt (`frame_ready`, `stats`, `error`). Las
  señales son la forma segura de enviar datos al hilo principal.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from . import capture, overlay
from .aim_runtime import AimRuntime
from .config import Settings, logs_dir, models_dir
from .datalog import DataLogger
from .inference import Detector


class DetectionWorker(QThread):
    frame_ready = Signal(QImage, list)   # imagen dibujada + lista de detecciones
    stats = Signal(object)                 # fps, ms de inferencia, motor, etc.
    error = Signal(str)                  # mensaje para mostrar al usuario
    model_loaded = Signal(object)        # nombres de clases del modelo cargado

    def __init__(self, settings: Settings):
        super().__init__()
        self._settings = settings.copy()
        self._lock = threading.Lock()
        self._running = False
        self._stop_requested = threading.Event()
        self.aim = AimRuntime(settings)

    # ------------------------------------------------------------------
    def update_settings(self, settings: Settings) -> None:
        """Llamado desde la interfaz cada vez que cambia un control."""
        with self._lock:
            self._settings = settings.copy()
        self.aim.configure(settings)

    def stop(self) -> None:
        self._stop_requested.set()
        self.aim.close()
        self._running = False
        self.wait()

    def _snapshot(self) -> Settings:
        with self._lock:
            return self._settings

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: C901 - es el bucle principal, se lee de arriba abajo
        self._running = True
        self.aim.start()
        source = None
        source_key = None        # qué fuente hay abierta ahora mismo
        detector = None
        detector_name = None     # qué modelo hay cargado ahora mismo
        logger = None
        frame_index = 0
        fps = 0.0
        last_time = time.perf_counter()

        try:
            while not self._stop_requested.is_set():
                s = self._snapshot()
                loop_start = time.perf_counter()

                # 1) ¿Ha cambiado el modelo? Recargar solo si hace falta.
                if s.model != detector_name:
                    detector, detector_name = None, s.model
                    if s.model:
                        try:
                            detector = Detector(models_dir() / s.model)
                            self.model_loaded.emit(dict(detector.names))
                        except Exception as exc:  # noqa: BLE001
                            self.error.emit(str(exc))

                # 2) ¿Ha cambiado la fuente? Cerrar la anterior y abrir la nueva.
                key = (s.source, s.monitor, s.video_path, s.video_loop, s.camera_index)
                if key != source_key:
                    if source:
                        source.close()
                    source, source_key = None, key
                    try:
                        source = capture.open_source(s)
                    except Exception as exc:  # noqa: BLE001
                        self.error.emit(str(exc))

                if source is None:
                    time.sleep(0.2)      # esperar a que el usuario arregle la fuente
                    continue

                # Timestamp before capture: inference latency counts toward freshness.
                captured_at = time.monotonic()
                # 3) Capturar una imagen.
                frame = source.read(s)
                if frame is None:
                    self.error.emit("La fuente no devuelve imágenes (¿fin del vídeo?).")
                    time.sleep(0.3)
                    continue

                # 4) Inferencia (si hay modelo; sin modelo se ve solo la imagen).
                detections = []
                infer_ms = 0.0
                if detector is not None:
                    t0 = time.perf_counter()
                    detections = detector.detect(
                        frame, s.confidence, s.iou, s.max_detections, s.classes
                    )
                    infer_ms = (time.perf_counter() - t0) * 1000

                geometry = getattr(source, "geometry", None)
                if geometry is not None:
                    self.aim.submit(geometry.targets(detections), geometry.crosshair,
                                    captured_at, (source_key, s.model, geometry), s)

                # 5) Log en CSV: se abre al activar la opción y se cierra al quitarla.
                if s.log_enabled and logger is None:
                    logger = DataLogger(logs_dir())
                elif not s.log_enabled and logger is not None:
                    logger.close()
                    logger = None
                if logger and detections and frame_index % max(1, s.log_every_n) == 0:
                    logger.write(frame_index, s.model, detections,
                                 frame.shape[1], frame.shape[0])

                # 6) FPS suavizados (media móvil exponencial: evita que el
                #    número baile de un fotograma a otro).
                now = time.perf_counter()
                instant = 1.0 / max(now - last_time, 1e-6)
                fps = instant if fps == 0 else fps * 0.9 + instant * 0.1
                last_time = now

                # 7) Dibujar y enviar a la interfaz.
                text = f"{fps:.0f} FPS  ·  {infer_ms:.1f} ms  ·  {len(detections)} det."
                self.frame_ready.emit(overlay.render(frame, detections, s, text, geometry), detections)
                self.stats.emit({
                    "aim": self.aim.status,
                    "screen_bounds": getattr(source, "bounds", None),
                    "fps": fps,
                    "infer_ms": infer_ms,
                    "count": len(detections),
                    "size": f"{frame.shape[1]}×{frame.shape[0]}",
                    "provider": detector.provider if detector else "—",
                    "log_rows": logger.rows if logger else 0,
                    "log_path": str(logger.path) if logger else "",
                })
                frame_index += 1

                # 8) Límite de FPS: dormir lo que sobre del "presupuesto" de tiempo.
                if s.fps_limit > 0:
                    budget = 1.0 / s.fps_limit
                    spent = time.perf_counter() - loop_start
                    if spent < budget:
                        time.sleep(budget - spent)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.aim.close()
            # Pase lo que pase, liberar la fuente y cerrar el CSV.
            if source:
                source.close()
            if logger:
                logger.close()
