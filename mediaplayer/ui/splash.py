"""Startbildschirm, solange der Player lädt.

Der erste Start (vor allem aus dem Installationspaket und unter Windows mit
Virenscanner) dauert einige Sekunden, weil Qt Multimedia, FFmpeg und numpy
von der Festplatte geladen werden. Der Startbildschirm erscheint direkt nach
dem Start von Qt – bevor diese schweren Teile geladen werden – und zeigt
Symbol, Name, Version und den aktuellen Ladeschritt mit Fortschrittsbalken.

Dieses Modul importiert bewusst nur QtCore/QtGui/QtWidgets und ``style``,
damit es selbst schnell geladen ist.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .style import px

WIDTH = 720
HEIGHT = 400

BACKGROUND = QColor("#1e1f22")
BORDER = QColor("#3a3d44")
TEXT = QColor("#f2f2f2")
SUBTEXT = QColor("#b8bcc4")
TRACK = QColor("#3a3d44")
ACCENT = QColor("#2f6fd6")


class SplashScreen(QSplashScreen):
    """Startbildschirm mit Ladeschritt und Fortschritt (0.0 – 1.0)."""

    def __init__(self, title: str, version: str, icon_path: str = ""):
        self._title = title
        self._version = version
        self._icon = QPixmap(icon_path) if icon_path else QPixmap()
        self._status = ""
        self._progress = 0.0

        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1.0
        size_w, size_h = px(WIDTH), px(HEIGHT)
        canvas = QPixmap(round(size_w * ratio), round(size_h * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        super().__init__(canvas)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # runde Ecken
        self.setCursor(Qt.CursorShape.WaitCursor)

    def status(self) -> str:
        return self._status

    def progress(self) -> float:
        return self._progress

    def set_step(self, text: str, progress: float) -> None:
        """Ladeschritt anzeigen und sofort zeichnen (die Ereignisschleife läuft noch nicht)."""
        self._status = text
        self._progress = max(0.0, min(1.0, progress))
        self.repaint()
        QApplication.processEvents()

    # Ein Klick soll den Startbildschirm nicht vorzeitig schließen.
    def mousePressEvent(self, event) -> None:
        event.ignore()

    def drawContents(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = px(WIDTH), px(HEIGHT)
        pad = px(40)

        # Karte mit runden Ecken
        card = QPainterPath()
        card.addRoundedRect(QRectF(1, 1, w - 2, h - 2), px(18), px(18))
        painter.fillPath(card, BACKGROUND)
        painter.setPen(BORDER)
        painter.drawPath(card)

        # Symbol links, Name und Version rechts daneben
        icon_size = px(150)
        icon_rect = QRectF(pad, px(70), icon_size, icon_size)
        if not self._icon.isNull():
            painter.drawPixmap(icon_rect.toRect(), self._icon)
        text_left = icon_rect.right() + px(36)
        text_width = w - text_left - pad

        title_font = QFont(self.font())
        title_font.setPixelSize(px(58))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(TEXT)
        painter.drawText(
            QRectF(text_left, icon_rect.top() + px(10), text_width, px(76)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title,
        )
        small = QFont(self.font())
        small.setPixelSize(px(24))
        painter.setFont(small)
        painter.setPen(SUBTEXT)
        painter.drawText(
            QRectF(text_left, icon_rect.top() + px(92), text_width, px(36)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"Version {self._version}",
        )

        # Ladeschritt und Fortschrittsbalken unten
        bar_h = px(10)
        bar = QRectF(pad, h - pad - bar_h, w - 2 * pad, bar_h)
        painter.drawText(
            QRectF(pad, bar.top() - px(50), bar.width(), px(36)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._status,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(TRACK)
        painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)
        if self._progress > 0:
            done = QRectF(bar.left(), bar.top(), max(bar_h, bar.width() * self._progress), bar_h)
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(done, bar_h / 2, bar_h / 2)
