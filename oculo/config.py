"""Ajustes de la app y rutas de carpetas.

Todo lo que el usuario puede tocar en la interfaz vive en la dataclass
`Settings`. Tener los ajustes en un único objeto tiene dos ventajas:

1. Guardarlos/cargarlos es trivial (se convierten a JSON tal cual).
2. El hilo de trabajo recibe una COPIA en cada cambio, así nunca lee un
   valor a medio modificar desde la interfaz (evita errores de concurrencia).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------
def is_frozen() -> bool:
    """True cuando corremos dentro del .app empaquetado por PyInstaller."""
    return getattr(sys, "frozen", False)


def data_dir() -> Path:
    """Carpeta donde viven models/, logs/ y settings.json.

    - En desarrollo (python -m oculo): la raíz del proyecto, para que la
      carpeta `models/` del repo funcione directamente.
    - En el .app: ~/Library/Application Support/Oculo. No se puede escribir
      dentro del propio .app (macOS lo trata como de solo lectura y además
      rompería la firma), por eso los datos van fuera.
    """
    if is_frozen():
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def list_models() -> list[str]:
    """Nombres de todos los .onnx que haya en la carpeta de modelos."""
    return sorted(p.name for p in models_dir().glob("*.onnx"))


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------
@dataclass
class Settings:
    # --- Modelo ---
    model: str = "best_PfYipLn.onnx"  # nombre del archivo dentro de models/
    confidence: float = 0.11        # descarta detecciones por debajo de esto
    iou: float = 0.10               # umbral de solape para la NMS (ver inference.py)
    max_detections: int = 200       # tope de cajas por imagen
    classes: list[int] = field(default_factory=list)  # vacío = todas las clases

    # --- Fuente de imagen ---
    source: str = "screen"          # "screen" | "video" | "camera"
    monitor: int = 1                # 1 = pantalla principal (numeración de mss)
    video_path: str = ""
    video_loop: bool = True
    camera_index: int = 0
    fps_limit: int = 83             # 0 = sin límite

    # --- Zona de detección ---
    # En vez de analizar la imagen entera se recorta un rectángulo centrado.
    # Menos píxeles = más FPS, y el modelo ve los objetos más grandes.
    zone_enabled: bool = True
    zone_width: int = 640
    zone_height: int = 640
    zone_offset_x: int = 0          # desplazamiento respecto al centro
    zone_offset_y: int = 0

    # --- Aim (distancias en puntos lógicos macOS, no píxeles Retina) ---
    aim_enabled: bool = False
    aim_activation: str = "mouse:right"
    aim_emergency: str = "key:f8"
    aim_mode: str = "exponential"
    aim_input_method: str = "quartz_hid"
    input_test_results: dict[str, str] = field(default_factory=dict)
    aim_limit_fov: bool = False      # apagado = buscar en todo el monitor
    aim_fov: float = 180.0            # radio desde la mira real del monitor
    aim_sticky: bool = True
    aim_match_radius: float = 80.0
    aim_lost_ms: int = 120            # retener identidad; nunca mover sin detección
    aim_point_y: float = 0.5          # 0 = parte superior, 1 = inferior
    aim_response_ms: float = 180.0
    aim_ema: float = 0.65             # peso de la medición nueva a 60 Hz
    aim_prediction_ms: float = 0.0    # apagada por defecto (cámara no observable)
    aim_prediction_limit: float = 8.0
    aim_deadzone: float = 2.0
    aim_max_step: float = 8.0
    aim_max_speed: float = 400.0      # puntos por segundo
    aim_gain_x: float = 1.0           # calibración entrada -> desplazamiento visual
    aim_gain_y: float = 1.0
    aim_stale_ms: int = 200
    aim_show_fov: bool = False

    # --- Visor ---
    box_color: str = "#8B7CFF"
    box_thickness: int = 2
    box_style: str = "corners"      # "corners" | "full"
    color_by_class: bool = False    # un color distinto por clase
    show_labels: bool = True
    show_confidence: bool = True
    show_center: bool = True        # punto en el centro de cada caja
    show_coords: bool = False       # texto (x, y) junto al centro
    show_stats: bool = True         # FPS y milisegundos sobre la imagen

    # --- Registro de datos ---
    log_enabled: bool = False
    log_every_n: int = 1            # guardar 1 de cada N imágenes

    # ----------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Crea Settings ignorando claves desconocidas.

        Así un settings.json antiguo (o de otra versión) no rompe la app:
        lo que no exista se queda con su valor por defecto.
        """
        valid = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in valid}
        from .macos_input import INPUT_METHODS
        method = values.get("aim_input_method", "quartz_hid")
        if not isinstance(method, str) or method not in INPUT_METHODS:
            values["aim_input_method"] = "quartz_hid"
        results = values.get("input_test_results", {})
        values["input_test_results"] = ({k:v for k,v in results.items()
            if k in INPUT_METHODS and v in ("accepted", "ignored")} if isinstance(results, dict) else {})
        return cls(**values)

    def save(self, path: Path | None = None) -> None:
        target = path or settings_path()
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        target = path or settings_path()
        try:
            return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return cls()

    def copy(self) -> "Settings":
        return Settings.from_dict(self.to_dict())
