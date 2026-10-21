"""Anwendungsstart."""

import sys

from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORGANIZATION_NAME
from .ui.main_window import MainWindow
from .ui.style import STYLESHEET, PlayerStyle


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setStyle(PlayerStyle())
    app.setStyleSheet(STYLESHEET)

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
