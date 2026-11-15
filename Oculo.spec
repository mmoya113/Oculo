# Receta de PyInstaller: convierte el proyecto en Oculo.app.
# Uso:  pyinstaller Oculo.spec --noconfirm
import os

from oculo import __version__

icon = "build/Oculo.icns" if os.path.exists("build/Oculo.icns") else None

a = Analysis(
    ["oculo/__main__.py"],
    pathex=["."],
    datas=[],
    hiddenimports=[],
    # Módulos de Qt que no usamos: excluirlos reduce mucho el tamaño del .app.
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
        "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Oculo",
    console=False,          # app de ventana, sin terminal
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Oculo")
app = BUNDLE(
    coll,
    name="Oculo.app",
    icon=icon,
    bundle_identifier="com.mmoya.oculo",
    version=__version__,
    info_plist={
        "CFBundleDisplayName": "Oculo",
        "CFBundleShortVersionString": __version__,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        # Texto que macOS enseña al pedir permiso de cámara (fuente "Webcam").
        "NSCameraUsageDescription": "Oculo usa la cámara como fuente de imagen para la detección.",
    },
)
