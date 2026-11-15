import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget
from oculo.config import Settings
from oculo.ui.main_window import MainWindow


def test_window_presets_panic_and_cinema(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls()))
    monkeypatch.setattr(Settings, "save", lambda self: None)
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
