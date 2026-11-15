"""Tests de las piezas sin interfaz: zona, letterbox, NMS, decode, detector y log.

Ejecutar con:  python -m pytest
"""

import csv

import numpy as np
import pytest

from oculo.capture import zone_rect
from oculo.config import Settings
from oculo.datalog import HEADER, DataLogger
from oculo.inference import Detection, Detector, decode, letterbox, nms


def test_zone_is_centered_and_clamped():
    s = Settings(zone_enabled=True, zone_width=640, zone_height=640)
    assert zone_rect(1920, 1080, s) == (640, 220, 640, 640)
    s.zone_offset_x = 5000                      # desplazamiento absurdo
    x, y, w, h = zone_rect(1920, 1080, s)
    assert x + w == 1920                        # pegado al borde, sin salirse
    s.zone_enabled = False
    assert zone_rect(1920, 1080, s) == (0, 0, 1920, 1080)


def test_letterbox_keeps_aspect_ratio():
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    boxed, scale, pad_x, pad_y = letterbox(image, (640, 640))
    assert boxed.shape == (640, 640, 3)
    assert scale == 1.0 and pad_x == 0 and pad_y == 140
    assert boxed[0, 0, 0] == 114                # el relleno es gris


def test_nms_removes_overlapping_box():
    boxes = np.array([[0, 0, 100, 100], [5, 5, 105, 105], [300, 300, 400, 400]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    assert nms(boxes, scores, 0.5) == [0, 2]


def _yolov8_output(candidates, num_classes=2, total=100):
    """Fabrica una salida falsa con forma (1, 4 + clases, N)."""
    out = np.zeros((1, 4 + num_classes, total), dtype=np.float32)
    for i, (cx, cy, w, h, cls, score) in enumerate(candidates):
        out[0, :4, i] = (cx, cy, w, h)
        out[0, 4 + cls, i] = score
    return out


def test_decode_yolov8_format():
    out = _yolov8_output([
        (320, 320, 100, 200, 0, 0.90),
        (322, 321, 100, 200, 0, 0.60),          # duplicado -> lo quita la NMS
        (100, 100, 50, 50, 1, 0.80),
        (500, 500, 40, 40, 1, 0.10),            # por debajo del umbral
    ])
    rows = decode(out, conf_threshold=0.25, iou_threshold=0.5)
    assert rows.shape == (2, 6)
    assert rows[0].tolist() == pytest.approx([270, 220, 370, 420, 0.9, 0])
    assert int(rows[1][5]) == 1


def test_decode_same_place_different_class_survives():
    out = _yolov8_output([(320, 320, 100, 100, 0, 0.9), (320, 320, 100, 100, 1, 0.8)])
    assert decode(out, 0.25, 0.5).shape[0] == 2


def test_decode_end2end_format():
    out = np.zeros((1, 300, 6), dtype=np.float32)
    out[0, 0] = (10, 20, 110, 220, 0.95, 3)
    out[0, 1] = (0, 0, 5, 5, 0.05, 1)
    rows = decode(out, 0.25, 0.5)
    assert rows.shape == (1, 6) and int(rows[0][5]) == 3


def test_decode_empty():
    assert decode(_yolov8_output([]), 0.25, 0.5).shape == (0, 6)


def _make_dummy_model(path, candidates):
    """Crea un .onnx mínimo que ignora la imagen y siempre devuelve lo mismo.

    Sirve para probar Detector de punta a punta sin descargar un modelo real.
    """
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    fixed = _yolov8_output(candidates, total=8400)
    nodes = [
        helper.make_node("ReduceMean", ["images"], ["mean"], keepdims=0),
        helper.make_node("Mul", ["mean", "zero"], ["nothing"]),
        helper.make_node("Add", ["nothing", "fixed"], ["output0"]),
    ]
    graph = helper.make_graph(
        nodes, "dummy",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(fixed.shape))],
        initializer=[
            numpy_helper.from_array(np.zeros((), dtype=np.float32), "zero"),
            numpy_helper.from_array(fixed, "fixed"),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    entry = model.metadata_props.add()
    entry.key, entry.value = "names", "{0: 'gato', 1: 'perro'}"
    onnx.save(model, str(path))


def test_detector_end_to_end(tmp_path):
    model_path = tmp_path / "dummy.onnx"
    # Caja centrada en (320, 320) del tensor 640x640.
    _make_dummy_model(model_path, [(320, 320, 100, 100, 1, 0.9)])
    detector = Detector(model_path)
    assert detector.names == {0: "gato", 1: "perro"}

    # Imagen 1280x720: escala 0.5 y relleno vertical de 140 px.
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    detections = detector.detect(frame)
    assert len(detections) == 1
    d = detections[0]
    assert d.class_name == "perro"
    assert (d.cx, d.cy) == pytest.approx((640, 360))     # centro de la imagen
    assert (d.width, d.height) == pytest.approx((200, 200))
    assert detector.detect(frame, classes=[0]) == []      # filtro de clases


def test_datalogger_writes_centers(tmp_path):
    logger = DataLogger(tmp_path)
    logger.write(7, "m.onnx", [Detection(10, 20, 110, 220, 0.87, 0, "gato")], 640, 640)
    logger.close()
    rows = list(csv.reader(logger.path.open(encoding="utf-8")))
    assert rows[0] == HEADER
    record = dict(zip(HEADER, rows[1]))
    assert (record["cx"], record["cy"]) == ("60.0", "120.0")
    assert record["frame"] == "7" and record["class_name"] == "gato"
