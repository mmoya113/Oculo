import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget
from oculo.config import Settings
from oculo.ui.main_window import MainWindow


def test_window_presets_panic_and_cinema(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls()))
    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr("oculo.ui.main_window.screen_capture_allowed", lambda **kw:True)
    window = MainWindow()
    window.show()
    app.processEvents()
    assert window.findChild(QTabWidget).count() == 3
    window.settings.aim_enabled = True
    window._sync_controls()
    window.emergency_stop()
    assert not window.settings.aim_enabled
    window.toggle_cinema(True)
    app.processEvents()
    assert window.isFullScreen()
    window.toggle_cinema(False)
    app.processEvents()
    assert not window.isFullScreen()
    window.close()


def test_capture_permission_blocks_start_and_links_recovery(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls()))
    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr("oculo.ui.main_window.screen_capture_allowed", lambda **kw:False)
    window = MainWindow()
    window.show()
    app.processEvents()
    window.start()
    assert window.worker is None
    assert window.capture_banner.isVisible()
    assert "bloqueada" in window.viewer.text()
    assert "Grabación de pantalla" in window.capture_help.text()
    window.close()


def test_header_drag_fallback_and_button_interaction(monkeypatch):
    from PySide6.QtCore import QPointF, Qt, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QMainWindow, QPushButton
    from PySide6.QtTest import QTest
    from types import SimpleNamespace
    from oculo.ui.titlebar import DraggableHeader
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    header = DraggableHeader()
    button = QPushButton("Keep clickable", header)
    button.move(0,0)
    window.setCentralWidget(header)
    window.resize(500,100)
    window.show()
    app.processEvents()
    monkeypatch.setattr(window, "windowHandle", lambda:SimpleNamespace(startSystemMove=lambda:False))
    original = window.pos()
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(200,50), QPointF(400,400),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    header.mousePressEvent(press)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(230,70), QPointF(430,420),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    header.mouseMoveEvent(move)
    assert window.pos() == original + QPointF(30,20).toPoint()
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(230,70), QPointF(430,420),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    header.mouseReleaseEvent(release)
    assert header._drag_offset is None
    clicked = []
    button.clicked.connect(lambda:clicked.append(True))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert clicked == [True]
    window.close()


def test_desktop_fov_is_passive_separate_and_not_baked_in_preview(monkeypatch):
    import numpy as np
    from PySide6.QtCore import Qt
    from oculo.ui.desktop_overlay import DesktopOverlay
    from oculo.overlay import render
    from oculo.aim import ScreenGeometry
    app = QApplication.instance() or QApplication([])
    overlay = DesktopOverlay()
    overlay.configure((-1000, 50, 1000,800), 180, True)
    assert overlay.isVisible()
    assert overlay.geometry().getRect() == (-1000,50,1000,800)
    assert overlay.radius == 180
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    s = Settings(aim_enabled=True, aim_show_fov=True, show_stats=False)
    image = render(np.zeros((200,200,3),np.uint8), [], s, geometry=
                   ScreenGeometry(0,0,200,200,200,200,100,100))
    assert image.pixelColor(100,100).name() == "#000000"
    overlay.configure(None,180,False)
    assert not overlay.isVisible()
    overlay.close()
