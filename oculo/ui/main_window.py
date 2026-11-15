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
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QTabWidget,
)

from .. import APP_NAME, __version__
from ..config import Settings, list_models, logs_dir, models_dir
from ..worker import DetectionWorker
from ..macos_input import BINDINGS, INPUT_METHODS
from . import theme
from .branding import logo_pixmap
from .titlebar import DraggableHeader
from ..screen_access import screen_capture_allowed, PERMISSION_HELP
from .desktop_overlay import DesktopOverlay
from ..aim import options
from .aim_help import AIM_HELP
from ..input_probe import MovementProbe
from ..gfn_probe import GFNMovementProbe


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
        self.settings.aim_show_fov = False  # visual overlay always starts hidden
        self.worker: DetectionWorker | None = None
        self.desktop_overlay = DesktopOverlay()
        self._screen_bounds = None
        self._mouse_probe = None
        self._pending_input_result = None
        self._show_permission_report = False
        self._binders: list = []          # funciones ajustes -> control
        self._last_table_update = 0.0

        self.setWindowTitle(APP_NAME)
        if sys.platform == "darwin":
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.ExpandedClientAreaHint |
                                Qt.WindowType.NoTitleBarBackgroundHint)
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

        self._aim_timer = QTimer(self)
        self._aim_timer.setInterval(100)
        self._aim_timer.timeout.connect(self._refresh_aim_status)
        self._aim_timer.start()
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(20)
        self._probe_timer.timeout.connect(self._poll_mouse_probe)
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(1000)
        self._capture_timer.timeout.connect(self._refresh_capture_access)
        self._capture_timer.start()
        self._refresh_capture_access()
        self.refresh_models()
        self._sync_controls()

        # Atajos del modo cine: F entra/sale, Esc sale.
        QShortcut(QKeySequence("F"), self, activated=self.toggle_cinema)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=lambda: self.toggle_cinema(False))

    # ==================================================================
    # Construcción de la interfaz
    # ==================================================================
    def _build_header(self) -> QWidget:
        header = self.header = DraggableHeader(objectName="header")
        header.setFixedHeight(96 if sys.platform == "darwin" else 76)
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 28 if sys.platform == "darwin" else 0, 20, 0)
        row.setSpacing(12)

        logo = QLabel()
        pixmap = logo_pixmap(76)                      # x2 para pantallas Retina
        pixmap.setDevicePixelRatio(2)
        logo.setPixmap(pixmap)
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addStretch()
        titles.addWidget(QLabel(APP_NAME.upper(), objectName="appName"))
        titles.addWidget(QLabel(f"VISION & CONTROL  /  v{__version__}", objectName="appTag"))
        titles.addStretch()
        for i in range(titles.count()):
            widget = titles.itemAt(i).widget()
            if widget:
                widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
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

        panic = QPushButton("Parada Aim", objectName="danger")
        panic.clicked.connect(self.emergency_stop)
        row.addWidget(panic)
        self.start_button = QPushButton("Iniciar", objectName="primary")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.toggle_running)
        row.addWidget(self.start_button)
        return header

    def _build_sidebar(self) -> QWidget:
        body = QWidget(objectName="sidebarBody")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.addWidget(QLabel("CENTRO DE CONTROL", objectName="sectionTitle"))
        tabs = QTabWidget()
        outer.addWidget(tabs)
        def page(title):
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 14, 0, 0)
            layout.setSpacing(12)
            tabs.addTab(widget, title)
            return layout

        mouse_names = {"right": "Clic derecho", "left": "Clic izquierdo",
                       "middle": "Botón central", "4": "Botón lateral 4", "5": "Botón lateral 5"}
        binding_options = [(mouse_names[b.split(":")[1]] if b.startswith("mouse:")
                            else "Tecla " + b.split(":")[1].upper(), b) for b in BINDINGS]
        column = page("Aim")
        card = self._card(column, "EMPEZAR AQUÍ")
        defaults = QPushButton("Cargar configuración inicial")
        defaults.clicked.connect(self._apply_aim_defaults)
        card.addWidget(defaults)
        permissions = QPushButton("Autorizar control del ratón")
        permissions.clicked.connect(self._request_input_permissions)
        card.addWidget(permissions)
        recheck = QPushButton("Recomprobar permisos y copia de Oculo")
        recheck.clicked.connect(self._recheck_input_permissions)
        card.addWidget(recheck)
        self.probe_button = QPushButton("Probar movimiento del ratón (3 s)")
        self.probe_button.setToolTip("Desactiva Aim y, tras 3 segundos, mueve el cursor 12 puntos a la derecha una sola vez. No necesita modelo ni detecciones. Suelta los botones y deja el ratón quieto, lejos del borde. F8 o tu parada configurada cancela la prueba.")
        self.probe_button.clicked.connect(self._start_mouse_probe)
        card.addWidget(self.probe_button)
        card.addWidget(QLabel("Método de entrada del ratón", objectName="fieldLabel"))
        self._combo(card, "aim_input_method", [(method.label, key) for key, method in INPUT_METHODS.items()])
        self.input_result_label = QLabel("Entrada sin probar en GeForce NOW.", objectName="hint")
        self.input_result_label.setWordWrap(True)
        card.addWidget(self.input_result_label)
        self.gfn_probe_button = QPushButton("Probar entrada en GeForce NOW (5 s)")
        self.gfn_probe_button.setToolTip("Desactiva Aim y da 5 segundos para entrar en la app nativa de GeForce NOW, en un menú o zona de prueba. Envía cuatro pasos pequeños derecha/izquierda con el método seleccionado. Suelta botones. F8 cancela. Después indica si la cámara respondió; Oculo no puede confirmarlo mirando el cursor.")
        self.gfn_probe_button.clicked.connect(self._start_gfn_probe)
        card.addWidget(self.gfn_probe_button)
        feedback = QHBoxLayout()
        self.input_yes_button = QPushButton("Sí, se movió")
        self.input_no_button = QPushButton("No se movió")
        self.input_yes_button.clicked.connect(lambda: self._record_input_result(True))
        self.input_no_button.clicked.connect(lambda: self._record_input_result(False))
        for button in (self.input_yes_button, self.input_no_button):
            button.setEnabled(False)
            feedback.addWidget(button)
        card.addLayout(feedback)
        links = QLabel('<a style="color:#54DCC0" href="x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility">Accesibilidad</a> · '
                       '<a style="color:#54DCC0" href="x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent">Monitorización de entrada</a>')
        links.setOpenExternalLinks(True)
        links.setWordWrap(True)
        card.addWidget(links)
        card = self._card(column, "01  /  ACTIVACIÓN")
        self._check(card, "Habilitar Aim assist", "aim_enabled")
        card.addWidget(QLabel("Mantener para activar", objectName="fieldLabel"))
        self._combo(card, "aim_activation", binding_options)
        card.addWidget(QLabel("Parada global (requiere rearmar)", objectName="fieldLabel"))
        self._combo(card, "aim_emergency", binding_options)
        hint = QLabel("Predeterminado: clic derecho · parada F8.\n"
                      "Activa Accesibilidad y Monitorización de entrada en macOS. "
                      "Teclas por posición física US; usa Fn si tu Mac lo requiere.", objectName="hint")
        hint.setWordWrap(True)
        card.addWidget(hint)
        card = self._card(column, "02  /  OBJETIVO")
        self._check(card, "Limitar búsqueda al círculo FOV", "aim_limit_fov")
        self._slider(card, "Radio del círculo FOV (opcional)", "aim_fov", 10, 800)
        hint = QLabel("Sin límite FOV, busca en todo el monitor seleccionado.", objectName="hint")
        hint.setWordWrap(True)
        card.addWidget(hint)
        self._check(card, "Mantener el mismo objetivo", "aim_sticky")
        self._slider(card, "Radio de asociación", "aim_match_radius", 10, 250)
        self._slider(card, "Retención al perderlo (ms)", "aim_lost_ms", 0, 500)
        self._slider(card, "Punto vertical (0 arriba / 1 abajo)", "aim_point_y", 0, 100, scale=100)
        self._check(card, "Mostrar FOV y mira sobre otras apps", "aim_show_fov")
        card = self._card(column, "03  /  MOVIMIENTO")
        card.addWidget(QLabel("Suavizado del apuntado", objectName="fieldLabel"))
        self._combo(card, "aim_mode", [(m, m.lower()) for m in
                                     ("Linear", "Bezier", "Exponential", "Adaptive")])
        self._slider(card, "Respuesta (ms; más = más lento)", "aim_response_ms", 20, 1000)
        self._slider(card, "EMA (peso de imagen nueva)", "aim_ema", 1, 100, scale=100)
        self._slider(card, "Zona muerta (puntos)", "aim_deadzone", 0, 150, scale=10)
        self._slider(card, "Paso máximo (puntos)", "aim_max_step", 1, 50)
        self._slider(card, "Velocidad máxima (puntos/s)", "aim_max_speed", 20, 1500)
        advanced = QPushButton("Mostrar ajustes avanzados")
        advanced.setCheckable(True)
        column.addWidget(advanced)
        card = self._card(column, "04  /  CALIBRACIÓN Y LATENCIA")
        card.parentWidget().hide()
        advanced.toggled.connect(card.parentWidget().setVisible)
        advanced.toggled.connect(lambda checked: advanced.setText(
            "Ocultar ajustes avanzados" if checked else "Mostrar ajustes avanzados"))
        self._slider(card, "Ganancia visual X por punto enviado", "aim_gain_x", 5, 500, scale=100)
        self._slider(card, "Ganancia visual Y por punto enviado", "aim_gain_y", 5, 500, scale=100)
        self._slider(card, "Predicción (ms; 0 recomendado)", "aim_prediction_ms", 0, 100)
        self._slider(card, "Límite de predicción (puntos)", "aim_prediction_limit", 0, 30)
        self._slider(card, "Caducidad de imagen (ms)", "aim_stale_ms", 20, 500)
        hint = QLabel("GeForce NOW puede ignorar eventos sintéticos o añadir latencia. "
                      "Oculo no puede garantizar la respuesta del juego. Empieza con "
                      "ganancia 1, predicción 0 y pasos pequeños. Vídeo y webcam "
                      "solo analizan: nunca controlan el ratón.", objectName="hint")
        hint.setWordWrap(True)
        card.addWidget(hint)
        column.addStretch()
        column = page("Detección")

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
        hint = QLabel("Pantalla sin límite FOV: se captura todo el monitor; este recorte se usa con límite FOV, vídeo o webcam.", objectName="hint")
        hint.setWordWrap(True)
        card.addWidget(hint)
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

        column.addStretch()
        column = page("Visor / datos")
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
        scroll.setFixedWidth(370)
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

        self.aim_status = QLabel("AIM  /  Desactivado", objectName="aimStatus")
        self.aim_status.setWordWrap(True)
        column.addWidget(self.aim_status)
        self.aim_details = QLabel("Aim: pulsa Iniciar para ver el diagnóstico.", objectName="hint")
        self.aim_details.setWordWrap(True)
        column.addWidget(self.aim_details)
        self.capture_banner = QFrame(objectName="captureBanner")
        notice = QVBoxLayout(self.capture_banner)
        self.capture_help = QLabel(PERMISSION_HELP)
        self.capture_help.setWordWrap(True)
        notice.addWidget(self.capture_help)
        actions = QHBoxLayout()
        grant = QPushButton("Permitir captura de otras apps")
        grant.clicked.connect(self._request_capture_access)
        settings = QPushButton("Abrir permisos de macOS")
        settings.clicked.connect(self._open_capture_settings)
        actions.addWidget(grant)
        actions.addWidget(settings)
        notice.addLayout(actions)
        column.addWidget(self.capture_banner)
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

    def _help_badge(self, row, attr):
        if attr not in AIM_HELP:
            return
        help_label = QLabel("?", objectName="helpBadge")
        help_label.setProperty("setting", attr)
        help_label.setFixedSize(18, 18)
        help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_label.setCursor(Qt.CursorShape.WhatsThisCursor)
        help_label.setToolTip("<qt>" + AIM_HELP[attr] + "</qt>")
        help_label.setAccessibleName("Ayuda: " + attr.removeprefix("aim_"))
        row.addWidget(help_label)

    def _slider(self, card, label, attr, low, high, scale=1, suffix="", percent=False, step=1):
        """Deslizador con etiqueta y valor. `scale` convierte enteros del
        deslizador en decimales (p. ej. 45 -> 0.45 con scale=100)."""
        top = QHBoxLayout()
        top.addWidget(QLabel(label, objectName="fieldLabel"), 1)
        self._help_badge(top, attr)
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
        if attr in AIM_HELP:
            row = QHBoxLayout()
            row.addWidget(box, 1)
            self._help_badge(row, attr)
            card.addLayout(row)
        else:
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
        if attr in AIM_HELP:
            row = QHBoxLayout()
            row.addWidget(combo, 1)
            self._help_badge(row, attr)
            card.addLayout(row)
        else:
            card.addWidget(combo)
        return combo

    # ==================================================================
    # Lógica
    # ==================================================================
    def _changed(self) -> None:
        """Un ajuste ha cambiado: avisar al worker y programar el guardado."""
        self._refresh_input_result()
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

    def _refresh_capture_access(self) -> bool:
        needed = self.settings.source == "screen" and not screen_capture_allowed()
        self.capture_banner.setVisible(needed)
        if needed and self.worker is not None:
            # Stop before showing any wallpaper-only preview or making input.
            self.stop()
            self.viewer.clear_image("Captura bloqueada por macOS. Revisa el aviso de permisos.")
            self._set_status("Falta permiso de grabación de pantalla.", error=True)
        return needed

    def _open_capture_settings(self) -> None:
        QDesktopServices.openUrl(QUrl(
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"))

    def _request_capture_access(self) -> None:
        if not screen_capture_allowed(request=True):
            self._open_capture_settings()
        self._refresh_capture_access()

    def start(self) -> None:
        self._show_permission_report = False
        if self.settings.source == "screen" and not screen_capture_allowed(request=True):
            self.capture_banner.show()
            self.viewer.clear_image("Captura bloqueada por macOS. Revisa el aviso de permisos.")
            self._set_status("Activa la grabación de pantalla y vuelve a abrir Oculo.", error=True)
            return
        self.capture_banner.hide()
        self.worker = DetectionWorker(self.settings)
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.stats.connect(self._on_stats)
        self.worker.error.connect(lambda message: self._set_status(message, error=True))
        self.worker.model_loaded.connect(self._on_model_loaded)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        self._set_running(True)
        self._set_status("En marcha." if self.settings.model else
                         "En marcha sin modelo: solo se muestra la imagen.")

    def _sync_desktop_overlay(self) -> None:
        visible = (self.worker is not None and self.settings.source == "screen"
                   and self.settings.aim_enabled and self.settings.aim_show_fov
                   and not self.worker.aim.status.startswith("PARADA"))
        self.desktop_overlay.configure(self._screen_bounds, options(self.settings)["fov"], visible)

    def _apply_aim_defaults(self) -> None:
        self._cancel_mouse_probe()
        defaults = Settings().to_dict()
        for key, value in defaults.items():
            if key.startswith("aim_"):
                setattr(self.settings, key, value)
        self._sync_controls()
        self._changed()
        self.aim_status.setText("AIM  /  Configuración inicial cargada · habilita Aim cuando estés listo")

    def _request_input_permissions(self) -> None:
        self._show_permission_report = True
        try:
            from ..macos_input import QuartzInput
            backend = QuartzInput(self.settings.aim_input_method)
            backend.request_permissions()
            self.aim_details.setText(backend.permission_report())
        except Exception as exc:
            self.aim_details.setText(str(exc))

    def _recheck_input_permissions(self) -> None:
        self._show_permission_report = True
        try:
            from ..macos_input import QuartzInput
            self.aim_details.setText(QuartzInput(self.settings.aim_input_method).permission_report())
        except Exception as exc:
            self.aim_details.setText(str(exc))

    def _start_mouse_probe(self) -> None:
        self._cancel_mouse_probe()
        self._pending_input_result = None
        self.input_yes_button.setEnabled(False)
        self.input_no_button.setEnabled(False)
        try:
            from ..macos_input import QuartzInput
            backend = QuartzInput(self.settings.aim_input_method)
            if not backend.ready():
                self.aim_details.setText(backend.permission_report())
                return
            self.settings.aim_enabled = False
            self._sync_controls()
            self._changed()
            self._mouse_probe = MovementProbe(backend, self.settings.aim_emergency)
            self.probe_button.setEnabled(False)
            self.gfn_probe_button.setEnabled(False)
            self._probe_timer.start()
            self._poll_mouse_probe()
        except Exception as exc:
            self.aim_details.setText(str(exc))

    def _refresh_input_result(self) -> None:
        result = self.settings.input_test_results.get(self.settings.aim_input_method)
        text = {"accepted": "Según tu prueba: la cámara respondió en GeForce NOW.",
                "ignored": "Según tu prueba: sin respuesta en GeForce NOW; prueba otra entrada."}
        self.input_result_label.setText(text.get(result, "Entrada sin probar en GeForce NOW."))

    def _record_input_result(self, accepted) -> None:
        if self._pending_input_result is None:
            return
        method = self._pending_input_result
        self.settings.input_test_results[method] = "accepted" if accepted else "ignored"
        self._pending_input_result = None
        self.input_yes_button.setEnabled(False)
        self.input_no_button.setEnabled(False)
        self._changed()
        self.aim_details.setText(INPUT_METHODS[method].label +
            (": respuesta confirmada por tu prueba." if accepted else
             ": sin respuesta según tu prueba. Prueba la siguiente entrada."))

    def _start_gfn_probe(self) -> None:
        self._cancel_mouse_probe()
        self._pending_input_result = None
        self.input_yes_button.setEnabled(False)
        self.input_no_button.setEnabled(False)
        try:
            from ..macos_input import QuartzInput
            backend = QuartzInput(self.settings.aim_input_method)
            if not backend.ready():
                self.aim_details.setText(backend.permission_report())
                return
            self.settings.aim_enabled = False
            self._sync_controls()
            self._changed()
            self._mouse_probe = GFNMovementProbe(backend, self.settings.aim_emergency)
            self.probe_button.setEnabled(False)
            self.gfn_probe_button.setEnabled(False)
            self._probe_timer.start()
            self._poll_mouse_probe()
        except Exception as exc:
            self.aim_details.setText(str(exc))

    def _cancel_mouse_probe(self) -> None:
        if self._mouse_probe is not None:
            self.aim_details.setText(self._mouse_probe.cancel())
            self._mouse_probe = None
            self._probe_timer.stop()
            self.probe_button.setEnabled(True)
            self.gfn_probe_button.setEnabled(True)

    def _poll_mouse_probe(self) -> None:
        if self._mouse_probe is None:
            return
        try:
            self.aim_details.setText(self._mouse_probe.tick())
        except Exception as exc:
            self._mouse_probe.cancel()
            self.aim_details.setText(f"Prueba detenida: {exc}")
        if self._mouse_probe.done:
            if isinstance(self._mouse_probe, GFNMovementProbe) and self._mouse_probe.sent_steps == 4:
                self._pending_input_result = self._mouse_probe.method
                self.input_yes_button.setEnabled(True)
                self.input_no_button.setEnabled(True)
            self._probe_timer.stop()
            self.probe_button.setEnabled(True)
            self.gfn_probe_button.setEnabled(True)
            self._mouse_probe = None

    def _refresh_aim_status(self) -> None:
        if self.worker:
            self.aim_status.setText("AIM  /  " + self.worker.aim.status)
            if self._mouse_probe is None and self.settings.aim_enabled and not self._show_permission_report:
                d = self.worker.aim.diagnostics
                age = "—" if d["age_ms"] is None else f'{d["age_ms"]:.0f} ms'
                self.aim_details.setText(
                    f'Tecla: {"detectada" if d["activation"] else "sin pulsar"} · '
                    f'Objetivos válidos: {d["in_fov"]} · Imagen: {age} · '
                    f'Descartadas por retraso: {d["stale"]} · Envíos al ratón: {d["posted"]} · '
                    f'{INPUT_METHODS.get(d["input_method"], INPUT_METHODS["quartz_hid"]).label}')
        self._sync_desktop_overlay()

    def emergency_stop(self) -> None:
        self._cancel_mouse_probe()
        if self.worker:
            self.worker.aim.panic()
        self.settings.aim_enabled = False
        self._sync_controls()
        self._changed()
        self.aim_status.setText("AIM  /  PARADA · activa Aim para rearmar")

    def _worker_finished(self) -> None:
        if self.sender() is self.worker and self.worker is not None and not self.worker.isRunning():
            self.worker = None
            self._set_running(False)
            self.desktop_overlay.hide()
            self._screen_bounds = None

    def stop(self) -> None:
        self._cancel_mouse_probe()
        self.desktop_overlay.hide()
        self._screen_bounds = None
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
        if self.worker is None:
            return
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
        self._screen_bounds = data.get("screen_bounds")
        self._sync_desktop_overlay()
        self.aim_status.setText("AIM  /  " + data.get("aim", "Desactivado"))
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
        self._cancel_mouse_probe()
        self._probe_timer.stop()
        self._aim_timer.stop()
        self._capture_timer.stop()
        self.desktop_overlay.close()
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.settings.save()
        super().closeEvent(event)
