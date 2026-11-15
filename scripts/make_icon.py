"""Genera el icono de la app a partir del logo dibujado por código.

Uso:  python scripts/make_icon.py
Crea build/Oculo.iconset/ con todos los tamaños que pide macOS. Después, en
un Mac, `iconutil -c icns build/Oculo.iconset` lo convierte en Oculo.icns
(el workflow de GitHub Actions hace ese paso automáticamente).
"""

import os
import sys
from pathlib import Path

# "offscreen" permite usar Qt sin pantalla (por ejemplo en GitHub Actions).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from oculo.ui.branding import logo_pixmap  # noqa: E402

app = QGuiApplication([])
iconset = ROOT / "build" / "Oculo.iconset"
iconset.mkdir(parents=True, exist_ok=True)

# macOS quiere cada tamaño en versión normal y @2x (Retina).
for size in (16, 32, 128, 256, 512):
    logo_pixmap(size).save(str(iconset / f"icon_{size}x{size}.png"))
    logo_pixmap(size * 2).save(str(iconset / f"icon_{size}x{size}@2x.png"))

print(f"Iconset creado en {iconset}")
