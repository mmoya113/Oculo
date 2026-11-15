"""Ventana principal: cabecera, panel de ajustes, visor y tabla de datos.

Idea central de este archivo: el "enlace" entre controles y ajustes.
Cada control (deslizador, casilla, desplegable...) se crea con un método
`_slider`, `_check`, `_combo`... que hace dos cosas:

1. Cuando el usuario lo mueve -> escribe el valor en `self.settings`
   y llama a `_changed()`, que avisa al worker y guarda en disco.
2. Registra una función en `self._binders` que hace el camino inverso
   (ajustes -> control). Así, al cargar un preset, basta con recorrer
   esa lista para que toda la interfaz se actualice sola.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..config import Settings, list_models, logs_dir, models_dir
from ..worker import DetectionWorker
from . import theme
from .branding import logo_pixmap


class Viewer(QLabel):
    """Etiqueta que muestra la imagen escalada sin deformarla."""

    def __init__(self):
        super().__init__("Pulsa «Iniciar» para empezar")
        self.setObjectName("viewer")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 300)
        # "Ignored": el tamaño de la imagen no empuja el tamaño de la ventana.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image: QImage | None = None

    def show_image(self, image: QImage) -> None:
        self._image = image
        self._refresh()

    def clear_image(self, text: str) -> None:
        self._image = None
        self.setPixmap(QPixmap())
        self.setText(text)

    def resizeEvent(self, event) -> None:  # noqa: N802 - nombre impuesto por Qt
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._image is None:
            return
        target = self.size() - QSize(12, 12)
        self.setPixmap(QPixmap.fromImage(self._image).scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.worker: DetectionWorker | None = None
        self._binders: list = []          # funciones ajustes -> control
        self._last_table_update = 0.0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(logo_pixmap(256)))
        self.resize(1280, 800)
        self.setMinimumSize(1020, 640)
        self.setStyleSheet(theme.STYLESHEET)

        # Guardado "con retardo": si el usuario arrastra un deslizador no
        # escribimos el archivo 100 veces, solo 0,4 s después del último cambio.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.settings_save)

        root = QWidget(objectName="root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_main(), 1)
        layout.addLayout(body, 1)
        self.setCentralWidget(root)

        self.refresh_models()
        self._sync_controls()

        # Atajos del modo cine: F entra/sale, Esc sale.
        QShortcut(QKeySequence("F"), self, activated=self.toggle_cinema)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=lambda: self.toggle_cinema(False))

    # ==================================================================
    # Construcción de la interfaz
    # ==================================================================
    def _build_header(self) -> QWidget:
        header = self.header = QWidget(objectName="header")
        header.setFixedHeight(64)
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(12)

        logo = QLabel()
        pixmap = logo_pixmap(76)                      # x2 para pantallas Retina
        pixmap.setDevicePixelRatio(2)
        logo.setPixmap(pixmap)
        row.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addStretch()
        titles.addWidget(QLabel(APP_NAME.upper(), objectName="appName"))
        titles.addWidget(QLabel(f"Detección en tiempo real · v{__version__}", objectName="appTag"))
        titles.addStretch()
        row.addLayout(titles)
        row.addStretch()

        for text, slot in (
            ("Pantalla completa (F)", lambda: self.toggle_cinema()),
            ("Carpeta de modelos", lambda: self._open_folder(models_dir())),
            ("Cargar preset", self.load_preset),
            ("Guardar preset", self.save_preset),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)

        self.start_button = QPushButton("Iniciar", objectName="primary")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.toggle_running)
        row.addWidget(self.start_button)
        return header

    def _build_sidebar(self) -> QWidget:
        body = QWidget(objectName="sidebarBody")
        column = QVBoxLayout(body)
        column.setContentsMargins(14, 14, 14, 14)
        column.setSpacing(12)

        # ---------------- MODELO ----------------
        card = self._card(column, "MODELO")
        row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._model_selected)
        reload_button = QPushButton("↻")
        reload_button.setFixedWidth(36)
        reload_button.setToolTip("Volver a leer la carpeta de modelos")
        reload_button.clicked.connect(self.refresh_models)
        row.addWidget(self.model_combo, 1)
        row.addWidget(reload_button)
        card.addLayout(row)
        self.model_hint = QLabel("Copia tus archivos .onnx en la carpeta de modelos.", objectName="hint")
        self.model_hint.setWordWrap(True)
        card.addWidget(self.model_hint)
        self._slider(card, "Confianza mínima", "confidence", 5, 95, scale=100, suffix="%", percent=True)
        self._slider(card, "Solape NMS (IoU)", "iou", 10, 90, scale=100, suffix="%", percent=True)
        self._slider(card, "Máximo de detecciones", "max_detections", 1, 200)
        card.addWidget(QLabel("Clases a mostrar (vacío = todas)", objectName="fieldLabel"))
        self.classes_edit = QLineEdit(placeholderText="ej. 0, 2, 5")
        self.classes_edit.editingFinished.connect(self._classes_edited)
        self._binders.append(lambda s: self.classes_edit.setText(", ".join(map(str, s.classes))))
        card.addWidget(self.classes_edit)

        # ---------------- FUENTE ----------------
        card = self._card(column, "FUENTE DE IMAGEN")
        self._combo(card, "source", [("Pantalla", "screen"), ("Archivo de vídeo", "video"), ("Webcam", "camera")])
        self._spin(card, "Monitor", "monitor", 1, 8)
        row = QHBoxLayout()
        self.video_edit = QLineEdit(placeholderText="Ruta del vídeo…", readOnly=True)
        self._binders.append(lambda s: self.video_edit.setText(Path(s.video_path).name))
        browse = QPushButton("Elegir…")
        browse.clicked.connect(self._choose_video)
        row.addWidget(self.video_edit, 1)
        row.addWidget(browse)
        card.addLayout(row)
        self._check(card, "Repetir el vídeo en bucle", "video_loop")
        self._spin(card, "Número de cámara", "camera_index", 0, 9)
        self._slider(card, "Límite de FPS (0 = sin límite)", "fps_limit", 0, 240)

        # ---------------- ZONA ----------------
        card = self._card(column, "ZONA DE DETECCIÓN")
        self._check(card, "Analizar solo una zona centrada", "zone_enabled")
        self._slider(card, "Ancho", "zone_width", 128, 2560, suffix=" px", step=32)
        self._slider(card, "Alto", "zone_height", 128, 1600, suffix=" px", step=32)
        self._slider(card, "Desplazamiento X", "zone_offset_x", -1200, 1200, suffix=" px")
        self._slider(card, "Desplazamiento Y", "zone_offset_y", -800, 800, suffix=" px")
        row = QHBoxLayout()
        for label, size in (("320²", 320), ("640²", 640), ("1280×720", (1280, 720))):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, v=size: self._zone_preset(v))
            row.addWidget(button)
        card.addLayout(row)

        # ---------------- VISOR ----------------
        card = self._card(column, "VISOR")
        row = QHBoxLayout()
        row.addWidget(QLabel("Color de las cajas", objectName="fieldLabel"), 1)
        self.color_button = QPushButton()
        self.color_button.setFixedSize(54, 26)
        self.color_button.clicked.connect(self._choose_color)
        self._binders.append(lambda s: self.color_button.setStyleSheet(
            f"background: {s.box_color}; border: 1px solid {theme.BORDER}; border-radius: 7px;"))
        row.addWidget(self.color_button)
        card.addLayout(row)
        self._check(card, "Un color distinto por clase", "color_by_class")
        self._combo(card, "box_style", [("Solo esquinas", "corners"), ("Caja completa", "full")])
        self._slider(card, "Grosor de línea", "box_thickness", 1, 8, suffix=" px")
        self._check(card, "Nombre de la clase", "show_labels")
        self._check(card, "Porcentaje de confianza", "show_confidence")
        self._check(card, "Punto en el centro de la caja", "show_center")
        self._check(card, "Coordenadas (x, y) junto al centro", "show_coords")
        self._check(card, "FPS y tiempos sobre la imagen", "show_stats")

        # ---------------- DATOS ----------------
        card = self._card(column, "REGISTRO DE DATOS (CSV)")
        self._check(card, "Guardar detecciones en un CSV", "log_enabled")
        self._spin(card, "Guardar 1 de cada N imágenes", "log_every_n", 1, 120)
        self.log_hint = QLabel("Cada fila incluye el centro (cx, cy) de la caja.", objectName="hint")
        self.log_hint.setWordWrap(True)
        card.addWidget(self.log_hint)
        logs_button = QPushButton("Abrir carpeta de logs")
        logs_button.clicked.connect(lambda: self._open_folder(logs_dir()))
        card.addWidget(logs_button)

        column.addStretch()

        scroll = self.sidebar = QScrollArea(objectName="sidebar")
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(348)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _build_main(self) -> QWidget:
        main = QWidget()
        column = self.main_column = QVBoxLayout(main)
        column.setContentsMargins(18, 16, 18, 14)
        column.setSpacing(12)

        # Fila de estadísticas (dentro de un widget para poder ocultarla entera)
        self.chips_row = QWidget()
        chips = QHBoxLayout(self.chips_row)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(10)
        self.stat_labels: dict[str, QLabel] = {}
        for key, name in (("fps", "FPS"), ("infer", "INFERENCIA"), ("count", "DETECCIONES"),
                          ("size", "RESOLUCIÓN"), ("provider", "MOTOR")):
            chip = QFrame(objectName="statChip")
            box = QVBoxLayout(chip)
            box.setContentsMargins(14, 9, 14, 9)
            box.setSpacing(2)
            box.addWidget(QLabel(name, objectName="statName"))
            value = QLabel("—", objectName="statValue")
            box.addWidget(value)
            self.stat_labels[key] = value
            chips.addWidget(chip, 1)
        column.addWidget(self.chips_row)

        self.viewer = Viewer()
        column.addWidget(self.viewer, 1)

        # Tabla con los datos numéricos de la imagen actual
        headers = ["CLASE", "CONFIANZA", "CENTRO X", "CENTRO Y", "ANCHO", "ALTO"]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.setFixedHeight(168)
        column.addWidget(self.table)

        self.status = QLabel("Listo.", objectName="status")
        column.addWidget(self.status)
        return main

    # ==================================================================
    # Fábricas de controles (control <-> ajuste)
    # ==================================================================
    def _card(self, parent: QVBoxLayout, title: str) -> QVBoxLayout:
        frame = QFrame(objectName="card")
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(9)
        box.addWidget(QLabel(title, objectName="cardTitle"))
        parent.addWidget(frame)
        return box

    def _slider(self, card, label, attr, low, high, scale=1, suffix="", percent=False, step=1):
        """Deslizador con etiqueta y valor. `scale` convierte enteros del
        deslizador en decimales (p. ej. 45 -> 0.45 con scale=100)."""
        top = QHBoxLayout()
        top.addWidget(QLabel(label, objectName="fieldLabel"), 1)
        value_label = QLabel(objectName="value")
        top.addWidget(value_label)
        card.addLayout(top)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(step)
        slider.setPageStep(step * 4)
        card.addWidget(slider)

        def show(raw: int) -> None:
            value_label.setText(f"{raw}{suffix}" if percent or scale == 1 else f"{raw / scale:.2f}{suffix}")

        def on_change(raw: int) -> None:
            setattr(self.settings, attr, raw / scale if scale != 1 else raw)
            show(raw)
            self._changed()

        def bind(s: Settings) -> None:
            raw = round(getattr(s, attr) * scale)
            slider.blockSignals(True)       # evitar que dispare on_change
            slider.setValue(raw)
            slider.blockSignals(False)
            show(slider.value())

        slider.valueChanged.connect(on_change)
        self._binders.append(bind)
        return slider

    def _check(self, card, label, attr):
        box = QCheckBox(label)

        def on_change(checked: bool) -> None:
            setattr(self.settings, attr, checked)
            self._changed()

        def bind(s: Settings) -> None:
            box.blockSignals(True)
            box.setChecked(bool(getattr(s, attr)))
            box.blockSignals(False)

        box.toggled.connect(on_change)
        self._binders.append(bind)
        card.addWidget(box)
        return box

    def _spin(self, card, label, attr, low, high):
        row = QHBoxLayout()
        row.addWidget(QLabel(label, objectName="fieldLabel"), 1)
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setFixedWidth(72)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(spin)
        card.addLayout(row)

        def on_change(value: int) -> None:
            setattr(self.settings, attr, value)
            self._changed()

        def bind(s: Settings) -> None:
            spin.blockSignals(True)
            spin.setValue(int(getattr(s, attr)))
            spin.blockSignals(False)

        spin.valueChanged.connect(on_change)
        self._binders.append(bind)
        return spin

    def _combo(self, card, attr, options):
        """Desplegable. `options` es una lista de (texto visible, valor interno)."""
        combo = QComboBox()
        for text, value in options:
            combo.addItem(text, value)

        def on_change(_index: int) -> None:
            setattr(self.settings, attr, combo.currentData())
            self._changed()

        def bind(s: Settings) -> None:
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(getattr(s, attr))))
            combo.blockSignals(False)

        combo.currentIndexChanged.connect(on_change)
        self._binders.append(bind)
        card.addWidget(combo)
        return combo

    # ==================================================================
    # Lógica
    # ==================================================================
    def _changed(self) -> None:
        """Un ajuste ha cambiado: avisar al worker y programar el guardado."""
        if self.worker:
            self.worker.update_settings(self.settings)
        self._save_timer.start()

    def settings_save(self) -> None:
        self.settings.save()

    def _sync_controls(self) -> None:
        """Ajustes -> controles (al arrancar y al cargar un preset)."""
        for bind in self._binders:
            bind(self.settings)

    def refresh_models(self) -> None:
        models = list_models()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if self.settings.model in models:
            self.model_combo.setCurrentText(self.settings.model)
        self.model_combo.blockSignals(False)
        # Si el modelo guardado ya no existe, usar el primero que haya.
        self.settings.model = self.model_combo.currentText()
        if not models:
            self.model_hint.setText("No hay modelos. Pulsa «Carpeta de modelos», copia ahí "
                                    "tus archivos .onnx y pulsa ↻.")
        else:
            self.model_hint.setText(f"{len(models)} modelo(s) en la carpeta.")
        self._changed()

    def _model_selected(self, name: str) -> None:
        self.settings.model = name
        self._changed()

    def _classes_edited(self) -> None:
        """Convierte el texto "0, 2, 5" en la lista [0, 2, 5]."""
        numbers = []
        for chunk in self.classes_edit.text().replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                numbers.append(int(chunk))
        self.settings.classes = numbers
        self.classes_edit.setText(", ".join(map(str, numbers)))
        self._changed()

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir vídeo", str(Path.home()), "Vídeo (*.mp4 *.mov *.m4v *.avi *.mkv)")
        if path:
            self.settings.video_path = path
            self.settings.source = "video"
            self._sync_controls()
            self._changed()

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.settings.box_color), self, "Color de las cajas")
        if color.isValid():
            self.settings.box_color = color.name()
            self._sync_controls()
            self._changed()

    def _zone_preset(self, size) -> None:
        width, height = size if isinstance(size, tuple) else (size, size)
        self.settings.zone_enabled = True
        self.settings.zone_width, self.settings.zone_height = width, height
        self.settings.zone_offset_x = self.settings.zone_offset_y = 0
        self._sync_controls()
        self._changed()

    def _open_folder(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def save_preset(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Guardar preset", "preset.json", "JSON (*.json)")
        if path:
            self.settings.save(Path(path))
            self._set_status(f"Preset guardado en {path}")

    def load_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cargar preset", "", "JSON (*.json)")
        if path:
            self.settings = Settings.load(Path(path))
            self.refresh_models()
            self._sync_controls()
            self._set_status(f"Preset cargado: {Path(path).name}")

    def toggle_cinema(self, enable: bool | None = None) -> None:
        """Modo cine: el visor ocupa toda la pantalla y se oculta lo demás.

        Pensado para revisar un vídeo (fuente «Archivo de vídeo») a pantalla
        completa con las detecciones dibujadas encima.
        """
        active = self.isFullScreen()
        enable = (not active) if enable is None else enable
        if enable == active:
            return
        for widget in (self.header, self.sidebar, self.chips_row, self.table, self.status):
            widget.setVisible(not enable)
        margin = 0 if enable else 18
        self.main_column.setContentsMargins(margin, 0 if enable else 16, margin, 0 if enable else 14)
        if enable:
            self.showFullScreen()
        else:
            self.showNormal()

    # ------------------------------------------------------------------
    def toggle_running(self) -> None:
        if self.worker:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        self.worker = DetectionWorker(self.settings)
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.stats.connect(self._on_stats)
        self.worker.error.connect(lambda message: self._set_status(message, error=True))
        self.worker.model_loaded.connect(self._on_model_loaded)
        self.worker.start()
        self._set_running(True)
        self._set_status("En marcha." if self.settings.model else
                         "En marcha sin modelo: solo se muestra la imagen.")

    def stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self.worker = None
        self._set_running(False)
        self.viewer.clear_image("Detenido. Pulsa «Iniciar» para continuar")
        self._set_status("Detenido.")

    def _set_running(self, running: bool) -> None:
        self.start_button.setText("Detener" if running else "Iniciar")
        self.start_button.setProperty("running", "true" if running else "false")
        # Reaplicar el estilo para que el cambio de propiedad surta efecto.
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("kind", "error" if error else "")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # ------------------------------------------------------------------
    # Señales que llegan del worker
    # ------------------------------------------------------------------
    def _on_frame(self, image: QImage, detections: list) -> None:
        self.viewer.show_image(image)
        # La tabla se refresca como mucho 8 veces por segundo: a 60 FPS los
        # números serían ilegibles y redibujar la tabla tiene su coste.
        now = time.perf_counter()
        if now - self._last_table_update < 0.125:
            return
        self._last_table_update = now
        self.table.setRowCount(len(detections))
        for row, d in enumerate(detections):
            cells = (d.class_name, f"{d.confidence * 100:.1f} %", f"{d.cx:.1f}", f"{d.cy:.1f}",
                     f"{d.width:.0f}", f"{d.height:.0f}")
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)

    def _on_stats(self, data: dict) -> None:
        self.stat_labels["fps"].setText(f"{data['fps']:.0f}")
        self.stat_labels["infer"].setText(f"{data['infer_ms']:.1f} ms")
        self.stat_labels["count"].setText(str(data["count"]))
        self.stat_labels["size"].setText(data["size"])
        self.stat_labels["provider"].setText(data["provider"])
        if data["log_path"]:
            self.log_hint.setText(f"{data['log_rows']} filas → {Path(data['log_path']).name}")

    def _on_model_loaded(self, names: dict) -> None:
        if names:
            listing = ", ".join(f"{k}: {v}" for k, v in list(names.items())[:12])
            extra = "…" if len(names) > 12 else ""
            self.model_hint.setText(f"Clases — {listing}{extra}")
        else:
            self.model_hint.setText("Modelo cargado (sin nombres de clase en sus metadatos).")

    def closeEvent(self, event) -> None:  # noqa: N802 - nombre impuesto por Qt
        """Al cerrar la ventana: parar el hilo y guardar los ajustes."""
        if self.worker:
            self.worker.stop()
        self.settings.save()
        super().closeEvent(event)
