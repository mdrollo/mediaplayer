"""Gemeinsames Erscheinungsbild: große Schrift, große Bedienelemente.

Alle Größen sind für einen Bildschirm mit 1920×1080 Punkten ausgelegt. Auf
kleineren Bildschirmen – auch 1920×1080 mit 125 % Windows-Skalierung, was für
Programme nur 1536×864 Punkte ergibt – wird die gesamte Oberfläche gleichmäßig
verkleinert, damit nichts abgeschnitten wird: ``set_ui_scale`` beim Start,
danach liefern ``px()`` und ``scaled_stylesheet()`` die passenden Werte.
"""

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory

# Bezugsgröße der Gestaltung: Full HD abzüglich einer üblichen Taskleiste.
DESIGN_WIDTH = 1920
DESIGN_HEIGHT = 1032
MIN_SCALE = 0.6

ICON_SIZE = 56
BUTTON_HEIGHT = 64          # einheitliche Höhe aller Text-Buttons
TRANSPORT_HEIGHT = 84       # Wiedergabe-Buttons etwas größer

_scale = 1.0


def scale_for_screen(available_width: int, available_height: int) -> float:
    """Verkleinerungsfaktor für einen Bildschirm (nie größer als 1).

    Mit der Umgebungsvariable MEDIAPLAYER_UI_SCALE (z. B. 0.9) lässt sich der
    Wert fest vorgeben.
    """
    override = os.environ.get("MEDIAPLAYER_UI_SCALE")
    if override:
        try:
            return max(MIN_SCALE, min(2.0, float(override)))
        except ValueError:
            pass
    fit = min(available_width / DESIGN_WIDTH, available_height / DESIGN_HEIGHT, 1.0)
    return max(MIN_SCALE, round(fit, 3))


def set_ui_scale(scale: float) -> None:
    global _scale
    _scale = scale


def ui_scale() -> float:
    return _scale


def px(value: float) -> int:
    """Pixelwert der Gestaltung (bei 1920×1080) auf den aktuellen Bildschirm umrechnen."""
    return max(1, round(value * _scale))


def scaled_stylesheet() -> str:
    """STYLESHEET mit allen px-Angaben auf den aktuellen Bildschirm umgerechnet."""
    return re.sub(r"(\d+)px", lambda m: f"{px(int(m.group(1)))}px", STYLESHEET)


class PlayerStyle(QProxyStyle):
    """Fusion-Stil mit "Klick springt an die Position" für Schieberegler.

    Standardmäßig bewegt ein Klick neben den Regler-Knopf diesen nur um eine
    Seite. Mit ``SH_Slider_AbsoluteSetButtons`` springt er direkt an die
    Klickposition und kann ohne Loslassen weitergezogen werden.
    """

    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
            return Qt.MouseButton.LeftButton.value
        return super().styleHint(hint, option, widget, returnData)


STYLESHEET = """
QWidget {
    font-size: 22px;
    color: #f2f2f2;
    background-color: #1e1f22;
}
QMainWindow, QDialog {
    background-color: #1e1f22;
}
QLabel#timeLabel {
    font-size: 40px;
    font-weight: bold;
}
QLabel#playlistTitle {
    font-size: 34px;
    font-weight: 600;
    color: #f2f2f2;
}
QLabel#clockLabel {
    font-size: 40px;
    font-weight: bold;
    color: #b8bcc4;
}
QLabel#speedLabel {
    font-size: 28px;
    min-width: 120px;
}
QLabel#volumeLabel {
    font-size: 24px;
    min-width: 72px;   /* passt genau für "100 %" */
}
QLabel#messageLabel {
    font-size: 22px;
    color: #ffb454;
}
QLabel#dialogTitle {
    font-size: 36px;
    font-weight: bold;
}
QLabel#pathLabel {
    font-size: 24px;
    color: #b8bcc4;
}
QLineEdit {
    font-size: 28px;
    padding: 10px 14px;
    border: 2px solid #4a4d55;
    border-radius: 10px;
    background-color: #17181b;
}
QLineEdit:focus {
    border-color: #2f6fd6;
}
QPushButton#primaryButton {
    background-color: #2f6fd6;
    border-color: #2f6fd6;
}
QPushButton#primaryButton:disabled {
    background-color: #2b2d33;
    border-color: #3a3d44;
    color: #6b6f78;
}
QPushButton:checked {
    background-color: #2f6fd6;
    border-color: #2f6fd6;
}
QPushButton:disabled {
    color: #6b6f78;
}
QListWidget#bigList::item {
    padding: 0;
    border: none;
}
QLabel#sectionLabel {
    font-size: 24px;
    color: #b8bcc4;
}
QPushButton {
    font-size: 24px;
    padding: 8px 14px;
    border: 2px solid #4a4d55;
    border-radius: 10px;
    background-color: #2b2d33;
}
QPushButton:hover {
    background-color: #363941;
}
QPushButton:pressed {
    background-color: #2f6fd6;
}
QPushButton#transportButton {
    min-width: 120px;
}
QPushButton#quitButton {
    border-color: #a5463f;
}
QPushButton#quitButton:pressed {
    background-color: #a5463f;
}
QListWidget {
    font-size: 30px;
    background-color: #17181b;
    border: 2px solid #3a3d44;
    border-radius: 10px;
    padding: 6px;
}
QListWidget::item {
    padding: 14px 10px;
    border-bottom: 1px solid #2a2c31;
}
QListWidget::item:selected {
    background-color: #2f6fd6;
    color: #ffffff;
}
QScrollBar:vertical {
    width: 30px;
    background: #17181b;
    margin: 0;
}
QScrollBar::handle:vertical {
    min-height: 60px;
    border-radius: 12px;
    margin: 3px;
    background: #4a4d55;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QSlider {
    min-height: 48px;
}
QSlider::groove:horizontal {
    height: 16px;
    border-radius: 8px;
    background: #3a3d44;
}
QSlider::sub-page:horizontal {
    border-radius: 8px;
    background: #2f6fd6;
}
QSlider::handle:horizontal {
    width: 40px;
    margin: -14px 0;
    border-radius: 20px;
    background: #f2f2f2;
}
QSlider#positionSlider {
    min-height: 100px;
    background: transparent;  /* sonst übermalt Qt die selbst gezeichnete Wellenform */
}
QSlider#positionSlider::groove:horizontal {
    height: 100px;
    background: transparent;
    border: none;
}
QSlider#positionSlider::sub-page:horizontal,
QSlider#positionSlider::add-page:horizontal {
    background: transparent;
}
QSlider#positionSlider::handle:horizontal {
    width: 6px;
    margin: 0;
    border-radius: 3px;
    background: #ffffff;
}
QTableWidget {
    font-size: 24px;
    background-color: #17181b;
    gridline-color: #3a3d44;
}
QHeaderView::section {
    font-size: 22px;
    padding: 8px;
    background-color: #2b2d33;
    border: none;
}
QToolTip {
    font-size: 20px;
}
"""
