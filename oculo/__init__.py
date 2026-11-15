"""Oculo — detección de objetos en tiempo real con modelos YOLO (ONNX) para macOS.

Mapa rápido de módulos (léelos en este orden para entender el flujo):

    config.py     -> ajustes de la app y rutas de carpetas (models/, logs/)
    capture.py    -> de dónde salen las imágenes (pantalla, vídeo, webcam)
    inference.py  -> pasa cada imagen por el modelo y devuelve detecciones
    overlay.py    -> dibuja las cajas encima de la imagen
    datalog.py    -> guarda los datos numéricos en un CSV
    worker.py     -> hilo que une todo: captura -> inferencia -> dibujo -> log
    ui/           -> la ventana, los controles y el tema visual

El control del ratón es opcional y requiere activación explícita y permisos.
"""

__version__ = "1.0.3"
APP_NAME = "Oculo"
