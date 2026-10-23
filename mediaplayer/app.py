"""Anwendungsstart."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORGANIZATION_NAME
from .ui.main_window import MainWindow
from .ui.style import PlayerStyle, scale_for_screen, scaled_stylesheet, set_ui_scale


def asset_path(name: str) -> Path:
    """Pfad zu einer Datei in assets/ – im Projekt wie im PyInstaller-Paket."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "assets" / name


def run() -> int:
    if "--selftest" in sys.argv:
        from .selftest import run_selftest

        index = sys.argv.index("--selftest")
        out = sys.argv[index + 1] if index + 1 < len(sys.argv) else "selftest.txt"
        return run_selftest(out)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setStyle(PlayerStyle())
    # Oberfläche an den verfügbaren Platz anpassen (z. B. 1536×864 bei 125 % Skalierung).
    available = app.primaryScreen().availableGeometry()
    set_ui_scale(scale_for_screen(available.width(), available.height()))
    app.setStyleSheet(scaled_stylesheet())
    icon = asset_path("icon.png")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    window = MainWindow()
    if "--windowed" in sys.argv:
        window.showMaximized()
    else:
        window.showFullScreen()
    code = app.exec()
    # Fenster (samt Player und Decoder) ausdrücklich vor der QApplication
    # abbauen – sonst ist die Reihenfolge beim Funktionsende zufällig und
    # Qt Multimedia kann beim Beenden abstürzen.
    del window
    return code
