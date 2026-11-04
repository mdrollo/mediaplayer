"""Einblendbare Anzeige des chromatischen Stimmgeräts.

Links der erkannte Ton, in der Mitte eine Skala von −50 bis +50 Cent mit
Zeiger, rechts Frequenz, Abweichung und der einstellbare Kammerton.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..player.pitch import A4_MAX, A4_MIN
from .style import BUTTON_HEIGHT, px

IN_TUNE_CENTS = 5     # bis hierhin gilt der Ton als gestimmt (grün)
CLOSE_CENTS = 15      # bis hierhin "fast" (orange), darüber rot

GREEN = QColor("#3fbf6f")
ORANGE = QColor("#ffb454")
RED = QColor("#e5534b")
SCALE = QColor("#5d616b")
SCALE_TEXT = QColor("#b8bcc4")
ZONE = QColor(63, 191, 111, 60)


def cents_color(cents: float) -> QColor:
    value = abs(cents)
    if value <= IN_TUNE_CENTS:
        return GREEN
    if value <= CLOSE_CENTS:
        return ORANGE
    return RED


def format_number(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def format_cents(cents: float) -> str:
    rounded = round(cents)
    if rounded == 0:
        return "±0 Cent"
    return f"{'+' if rounded > 0 else '−'}{abs(rounded)} Cent"


class TunerGauge(QWidget):
    """Waagrechte Cent-Skala mit Zeiger; grüner Bereich = gestimmt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cents: float | None = None
        self.setMinimumHeight(px(110))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def cents(self) -> float | None:
        return self._cents

    def set_cents(self, cents: float | None) -> None:
        self._cents = None if cents is None else max(-50.0, min(50.0, cents))
        self.update()

    def _x(self, rect: QRectF, cents: float) -> float:
        return rect.left() + (cents + 50.0) / 100.0 * rect.width()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = px(24)
        label_h = px(30)
        scale = QRectF(margin, px(10), self.width() - 2 * margin, self.height() - px(10) - label_h - px(6))
        mid_y = scale.center().y()

        # Gestimmt-Bereich
        zone = QRectF(self._x(scale, -IN_TUNE_CENTS), scale.top(), 0, scale.height())
        zone.setRight(self._x(scale, IN_TUNE_CENTS))
        p.fillRect(zone, ZONE)

        # Grundlinie und Striche alle 5 Cent (lang bei 0, mittel bei 10er-Schritten).
        p.setPen(QPen(SCALE, px(3)))
        p.drawLine(QPointF(scale.left(), mid_y), QPointF(scale.right(), mid_y))
        for cents in range(-50, 51, 5):
            if cents == 0:
                half = scale.height() / 2
            elif cents % 10 == 0:
                half = scale.height() * 0.28
            else:
                half = scale.height() * 0.14
            x = self._x(scale, cents)
            p.setPen(QPen(GREEN if cents == 0 else SCALE, px(4 if cents == 0 else 2)))
            p.drawLine(QPointF(x, mid_y - half), QPointF(x, mid_y + half))

        font = QFont(self.font())
        font.setPixelSize(px(20))
        p.setFont(font)
        p.setPen(SCALE_TEXT)
        for cents, text in ((-50, "−50"), (-25, "−25"), (0, "0"), (25, "+25"), (50, "+50")):
            x = self._x(scale, cents)
            p.drawText(
                QRectF(x - px(40), scale.bottom() + px(6), px(80), label_h),
                Qt.AlignmentFlag.AlignCenter, text,
            )

        # Zeiger
        if self._cents is not None:
            x = self._x(scale, self._cents)
            color = cents_color(self._cents)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            width = px(12)
            p.drawRoundedRect(QRectF(x - width / 2, scale.top(), width, scale.height()), width / 2, width / 2)
        p.end()


class TunerPanel(QFrame):
    """Komplette Stimmgerät-Leiste. ``a4Changed`` meldet einen neuen Kammerton."""

    a4Changed = Signal(float)
    closeRequested = Signal()

    def __init__(self, a4: float, parent=None):
        super().__init__(parent)
        self.setObjectName("tunerPanel")
        self._a4 = a4

        # Oben: Ton | Abweichung + Frequenz | Kammerton | Schließen
        # Unten: Cent-Skala über die volle Breite.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(24), px(12), px(20), px(10))
        layout.setSpacing(px(4))
        top = QHBoxLayout()
        top.setSpacing(px(20))
        layout.addLayout(top)

        self.note_label = QLabel("–")
        self.note_label.setObjectName("tunerNote")
        self.note_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.note_label.setTextFormat(Qt.TextFormat.RichText)
        self.note_label.setMinimumWidth(px(150))
        top.addWidget(self.note_label)

        values = QVBoxLayout()
        values.setSpacing(px(2))
        self.cents_label = QLabel()
        self.cents_label.setObjectName("tunerCents")
        values.addWidget(self.cents_label)
        self.freq_label = QLabel()
        self.freq_label.setObjectName("sectionLabel")
        values.addWidget(self.freq_label)
        top.addLayout(values, 1)

        a4_box = QHBoxLayout()
        a4_box.setSpacing(px(10))
        self.a4_down = self._button("−", "Kammerton 1 Hz tiefer", lambda: self.set_a4(self._a4 - 1, notify=True))
        self.a4_label = QLabel()
        self.a4_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.a4_label.setToolTip("Kammerton (Bezugston A4)")
        self.a4_label.setMinimumWidth(px(150))
        self.a4_up = self._button("+", "Kammerton 1 Hz höher", lambda: self.set_a4(self._a4 + 1, notify=True))
        for button in (self.a4_down, self.a4_up):
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(120)
        a4_box.addWidget(self.a4_down)
        a4_box.addWidget(self.a4_label)
        a4_box.addWidget(self.a4_up)
        top.addLayout(a4_box)

        close = self._button("✕", "Stimmgerät ausblenden", self.closeRequested.emit)
        close.setFixedWidth(px(BUTTON_HEIGHT))
        top.addWidget(close)

        self.gauge = TunerGauge()
        layout.addWidget(self.gauge, 1)

        self.setFixedHeight(px(270))
        self.set_a4(a4)
        self.show_reading("", 0, 0.0, 0.0, 0.0)

    def a4(self) -> float:
        return self._a4

    def set_a4(self, a4: float, notify: bool = False) -> None:
        self._a4 = max(A4_MIN, min(A4_MAX, round(a4)))
        self.a4_label.setText(f"A = {self._a4:.0f} Hz")
        self.a4_down.setEnabled(self._a4 > A4_MIN)
        self.a4_up.setEnabled(self._a4 < A4_MAX)
        if notify:
            self.a4Changed.emit(self._a4)

    def show_reading(self, name: str, octave: int, cents: float, freq: float, target: float) -> None:
        if not name:
            self.note_label.setText(f"<span style='font-size:{px(96)}px; color:#5d616b'>–</span>")
            self.cents_label.setText("Ton anspielen …")
            self.cents_label.setStyleSheet("color: #b8bcc4")
            self.freq_label.setText(" ")
            self.gauge.set_cents(None)
            return
        color = cents_color(cents).name()
        self.note_label.setText(
            f"<span style='font-size:{px(96)}px; font-weight:bold; color:{color}'>{name}</span>"
            f"<span style='font-size:{px(40)}px; color:#b8bcc4'>{octave}</span>"
        )
        if abs(cents) <= IN_TUNE_CENTS:
            state = "gestimmt"
        elif cents > 0:
            state = "zu hoch"
        else:
            state = "zu tief"
        self.cents_label.setText(f"{format_cents(cents)} · {state}")
        self.cents_label.setStyleSheet(f"color: {color}")
        self.freq_label.setText(f"{format_number(freq)} Hz · Soll {format_number(target)}")
        self.gauge.set_cents(cents)

    def _button(self, text: str, tooltip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setFixedHeight(px(BUTTON_HEIGHT))
        button.setMinimumWidth(px(BUTTON_HEIGHT))
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _=False: slot())
        return button
