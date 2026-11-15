"""Punto de entrada: crea la aplicación Qt y muestra la ventana."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor

from . import APP_NAME, __version__
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, "#0B1016"),
                        (QPalette.ColorRole.WindowText, "#EDEDF4"),
                        (QPalette.ColorRole.Base, "#101720"),
                        (QPalette.ColorRole.Text, "#EDEDF4"),
                        (QPalette.ColorRole.Button, "#161F2A"),
                        (QPalette.ColorRole.ButtonText, "#EDEDF4")):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
