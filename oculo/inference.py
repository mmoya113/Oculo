"""Inferencia: pasar una imagen por un modelo YOLO en formato ONNX.

Este es el módulo más interesante para aprender. El recorrido completo es:

    imagen BGR  --preprocess-->  tensor  --modelo-->  salida cruda
                --decode-->  cajas candidatas  --NMS-->  detecciones finales

Usamos ONNX Runtime directamente (sin Ultralytics ni PyTorch) por dos motivos:
la app pesa ~10 veces menos, y así se ve TODO lo que pasa, sin cajas negras.

Formatos de salida soportados
-----------------------------
* YOLOv8 / YOLO11 (el más común):  forma (1, 4 + num_clases, N)
  Cada una de las N columnas es una caja candidata:
  [cx, cy, ancho, alto, puntuación_clase_0, puntuación_clase_1, ...]
* Modelos "end2end" (YOLOv10, o exportados con nms=True):  forma (1, N, 6)
  Cada fila ya es una detección final: [x1, y1, x2, y2, confianza, clase]
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Detection:
    """Una detección final, en píxeles de la imagen analizada."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_id: int
    class_name: str

    # El centro y el tamaño se calculan a partir de las esquinas.
    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1


# --------------------------------------------------------------------------
# Funciones puras (sin estado): fáciles de probar y de reutilizar
# --------------------------------------------------------------------------
def letterbox(image: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, float, int, int]:
    """Redimensiona la imagen al tamaño del modelo SIN deformarla.

    El modelo espera un tamaño fijo (p. ej. 640x640). Si estirásemos una
    imagen 16:9 a un cuadrado, los objetos saldrían deformados y detectaría
    peor. La solución: escalar manteniendo la proporción y rellenar lo que
    sobra con gris (114 es el valor con el que se entrenan los YOLO).

    Devuelve (imagen_rellenada, escala, relleno_x, relleno_y). Esos tres
    números hacen falta luego para deshacer la transformación.
    """
    target_h, target_w = size
    h, w = image.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = round(w * scale), round(h * scale)

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((target_h, target_w, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (target_w - new_w) // 2, (target_h - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Non-Maximum Suppression: elimina cajas duplicadas.

    El modelo suele proponer varias cajas casi iguales para el mismo objeto.
    La NMS se queda con la de mayor puntuación y descarta las que se solapan
    demasiado con ella. El solape se mide con IoU (Intersection over Union):

        IoU = área de la intersección / área de la unión      (de 0 a 1)

    Devuelve los índices de las cajas que sobreviven.
    """
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]          # de mayor a menor puntuación
    keep: list[int] = []

    while order.size > 0:
        best = order[0]
        keep.append(int(best))
        rest = order[1:]

        # Intersección de la mejor caja con todas las demás.
        ix1 = np.maximum(x1[best], x1[rest])
        iy1 = np.maximum(y1[best], y1[rest])
        ix2 = np.minimum(x2[best], x2[rest])
        iy2 = np.minimum(y2[best], y2[rest])
        inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)

        iou = inter / (areas[best] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_threshold]  # solo siguen las que NO se solapan

    return keep


def decode(
    output: np.ndarray,
    conf_threshold: float,
    iou_threshold: float,
    max_detections: int = 50,
) -> np.ndarray:
    """Convierte la salida cruda del modelo en un array (M, 6).

    Cada fila: [x1, y1, x2, y2, confianza, clase], todavía en coordenadas
    del tensor de entrada (p. ej. 0..640). Falta deshacer el letterbox.
    """
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]                        # quitar la dimensión de lote

    # --- Formato end2end: (N, 6) con la NMS ya hecha dentro del modelo ---
    if out.shape[-1] == 6 and out.shape[0] != 6:
        result = out[out[:, 4] >= conf_threshold]
        return result[np.argsort(-result[:, 4])][:max_detections]

    # --- Formato YOLOv8: (4 + clases, N). Lo giramos a (N, 4 + clases) ---
    if out.shape[0] < out.shape[1]:
        out = out.T

    class_scores = out[:, 4:]
    class_ids = class_scores.argmax(axis=1)         # clase más probable
    confidences = class_scores.max(axis=1)          # y su puntuación

    mask = confidences >= conf_threshold            # filtro de confianza
    boxes, confidences, class_ids = out[mask, :4], confidences[mask], class_ids[mask]
    if boxes.shape[0] == 0:
        return np.empty((0, 6), dtype=np.float32)

    # El modelo da (centro_x, centro_y, ancho, alto). Pasamos a esquinas.
    xyxy = np.empty_like(boxes)
    xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2

    # NMS "por clase": desplazamos cada clase muy lejos de las demás para que
    # cajas de clases distintas nunca se solapen (y por tanto no se eliminen
    # entre sí). Es un truco estándar para hacer una sola pasada de NMS.
    offsets = class_ids[:, None].astype(np.float32) * 4096.0
    keep = nms(xyxy + offsets, confidences, iou_threshold)[:max_detections]

    return np.column_stack([xyxy[keep], confidences[keep], class_ids[keep]])


# --------------------------------------------------------------------------
# Detector: el objeto con estado (modelo cargado en memoria)
# --------------------------------------------------------------------------
class Detector:
    """Carga un modelo .onnx y lo ejecuta sobre imágenes."""

    def __init__(self, model_path: str | Path):
        import onnxruntime as ort

        self.path = Path(model_path)
        self.session, self.provider = self._create_session(ort, self.path)

        # Información de la entrada: nombre, tamaño y tipo de dato.
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        shape = model_input.shape                      # p. ej. [1, 3, 640, 640]
        # Si el modelo tiene tamaño "dinámico", las dimensiones no son números.
        self.input_h = shape[2] if isinstance(shape[2], int) else 640
        self.input_w = shape[3] if isinstance(shape[3], int) else 640
        self.half = "float16" in model_input.type      # modelos exportados en FP16

        self.names = self._read_class_names()

    @staticmethod
    def _create_session(ort, path: Path):
        """Crea la sesión probando primero el acelerador de Apple.

        Un "execution provider" es el motor que ejecuta la red. CoreML usa la
        GPU / Neural Engine del Mac; si falla (algunos modelos no son
        compatibles) caemos a CPU, que funciona siempre.
        """
        available = ort.get_available_providers()
        attempts = []
        if "CoreMLExecutionProvider" in available:
            attempts.append(["CoreMLExecutionProvider", "CPUExecutionProvider"])
        attempts.append(["CPUExecutionProvider"])

        last_error: Exception | None = None
        for providers in attempts:
            try:
                session = ort.InferenceSession(str(path), providers=providers)
                return session, session.get_providers()[0].replace("ExecutionProvider", "")
            except Exception as exc:  # noqa: BLE001 - probamos el siguiente motor
                last_error = exc
        raise RuntimeError(f"No se pudo cargar el modelo {path.name}: {last_error}")

    def _read_class_names(self) -> dict[int, str]:
        """Lee los nombres de las clases guardados dentro del .onnx.

        Ultralytics los guarda en los metadatos como texto con forma de
        diccionario de Python: "{0: 'person', 1: 'car'}". Si no están,
        usaremos "clase 0", "clase 1", etc.
        """
        try:
            raw = self.session.get_modelmeta().custom_metadata_map.get("names", "")
            parsed = ast.literal_eval(raw) if raw else {}
            if isinstance(parsed, (list, tuple)):
                parsed = dict(enumerate(parsed))
            return {int(k): str(v) for k, v in parsed.items()}
        except (ValueError, SyntaxError, AttributeError):
            return {}

    def name_of(self, class_id: int) -> str:
        return self.names.get(class_id, f"clase {class_id}")

    def preprocess(self, image: np.ndarray):
        """Imagen BGR (alto, ancho, 3) -> tensor (1, 3, alto, ancho) de 0 a 1."""
        boxed, scale, pad_x, pad_y = letterbox(image, (self.input_h, self.input_w))
        rgb = boxed[:, :, ::-1]                         # BGR -> RGB
        tensor = rgb.transpose(2, 0, 1)[None]           # HWC -> CHW + lote
        tensor = np.ascontiguousarray(tensor, dtype=np.float32) / 255.0
        if self.half:
            tensor = tensor.astype(np.float16)
        return tensor, scale, pad_x, pad_y

    def detect(
        self,
        image: np.ndarray,
        conf: float = 0.45,
        iou: float = 0.5,
        max_detections: int = 50,
        classes: list[int] | None = None,
    ) -> list[Detection]:
        """Ejecuta el recorrido completo y devuelve la lista de detecciones."""
        tensor, scale, pad_x, pad_y = self.preprocess(image)
        raw = self.session.run(None, {self.input_name: tensor})[0]
        rows = decode(raw, conf, iou, max_detections)

        h, w = image.shape[:2]
        detections: list[Detection] = []
        for x1, y1, x2, y2, score, cls in rows:
            cls = int(cls)
            if classes and cls not in classes:
                continue
            # Deshacer el letterbox: quitar el relleno y dividir por la escala
            # para volver a píxeles de la imagen original.
            detections.append(
                Detection(
                    x1=float(np.clip((x1 - pad_x) / scale, 0, w)),
                    y1=float(np.clip((y1 - pad_y) / scale, 0, h)),
                    x2=float(np.clip((x2 - pad_x) / scale, 0, w)),
                    y2=float(np.clip((y2 - pad_y) / scale, 0, h)),
                    confidence=float(score),
                    class_id=cls,
                    class_name=self.name_of(cls),
                )
            )
        return detections
