"""Gemeinsames Erscheinungsbild: große Schrift, große Bedienelemente."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory

ICON_SIZE = 56
BUTTON_HEIGHT = 84


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
QLabel#clockLabel {
    font-size: 40px;
    font-weight: bold;
    color: #b8bcc4;
}
QLabel#speedLabel, QLabel#volumeLabel {
    font-size: 28px;
    min-width: 120px;
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
    font-size: 26px;
    padding: 10px 22px;
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
QPushButton#skipButton {
    font-size: 20px;
    padding: 6px 16px;
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
