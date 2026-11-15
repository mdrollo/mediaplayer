"""Anwendungsstart."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORGANIZATION_NAME, __version__
from .ui.splash import SplashScreen
from .ui.style import PlayerStyle, scale_for_screen, scaled_stylesheet, set_ui_scale

# Hauptfenster, Qt Multimedia und numpy werden erst nach dem Einblenden des
# Startbildschirms geladen – das ist der langsame Teil des Starts.


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

    splash = SplashScreen(APP_NAME, __version__, str(icon) if icon.is_file() else "")
    splash.show()
    splash.set_step("Programm wird geladen …", 0.1)

    from PySide6.QtMultimedia import QMediaDevices

    splash.set_step("Audioausgabe wird vorbereitet …", 0.35)
    QMediaDevices.audioOutputs()  # lädt das Audio-Backend (FFmpeg) und sucht die Geräte

    splash.set_step("Oberfläche wird aufgebaut …", 0.6)
    from .ui.main_window import MainWindow

    splash.set_step("Playlist und Einstellungen werden geladen …", 0.8)
    window = MainWindow()

    splash.set_step("Fertig", 1.0)
    if "--windowed" in sys.argv:
        window.showMaximized()
    else:
        window.showFullScreen()
    splash.finish(window)  # schließt, sobald das Hauptfenster zu sehen ist
    code = app.exec()
    # Fenster (samt Player und Decoder) ausdrücklich vor der QApplication
    # abbauen – sonst ist die Reihenfolge beim Funktionsende zufällig und
    # Qt Multimedia kann beim Beenden abstürzen.
    del window
    return code
