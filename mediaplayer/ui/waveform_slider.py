"""Positionsregler mit der Wellenform des geladenen Titels im Hintergrund.

Erbt vom ``MarkerSlider``: Markierungen werden über Wellenform und
Abspielstrich gezeichnet.
"""

import numpy as np
from PySide6.QtCore import QLineF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionSlider

from .widgets import MarkerSlider

# Farben: gespielter Teil blau, Rest grau; RMS (Kern) heller als die Spitzen.
PLAYED_PEAK = QColor("#2a5fb8")
PLAYED_RMS = QColor("#5b97f5")
REST_PEAK = QColor("#3a3d44")
REST_RMS = QColor("#5d616b")
BAR_BACKGROUND = QColor("#3a3d44")
BAR_PLAYED = QColor("#2f6fd6")
PENDING_TEXT = QColor("#8a8f99")
VERTICAL_PADDING = 4


class WaveformSlider(MarkerSlider):
    """MarkerSlider, der hinter Abspielstrich und Markierungen die Wellenform zeichnet.

    Solange keine Wellenform bekannt ist (Analyse läuft noch), erscheint ein
    schlichter Fortschrittsbalken. Klicken springt an die Stelle, Ziehen
    verschiebt die Position (siehe ``PlayerStyle``).
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("positionSlider")
        self._peaks: np.ndarray | None = None
        self._rms: np.ndarray | None = None
        self._pixmaps: tuple[QRect, QPixmap, QPixmap] | None = None
        self._pending = False

    def set_waveform(self, waveform: tuple[bytes, bytes] | None) -> None:
        """(Spitzenwerte, RMS) als Bytes 0–255 oder None/leer für "keine Wellenform"."""
        if waveform and waveform[0]:
            self._peaks = np.frombuffer(waveform[0], dtype=np.uint8).astype(np.float32) / 255.0
            self._rms = np.frombuffer(waveform[1], dtype=np.uint8).astype(np.float32) / 255.0
        else:
            self._peaks = self._rms = None
        self._pixmaps = None
        self.update()

    def has_waveform(self) -> bool:
        return self._peaks is not None

    def set_pending(self, pending: bool) -> None:
        """Hinweis "Wellenform wird berechnet …" anzeigen, solange keine Wellenform da ist."""
        if pending != self._pending:
            self._pending = pending
            self.update()

    # ------------------------------------------------------------ Geometrie
    def _subcontrols(self) -> tuple[QRect, QRect]:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)
        return groove, handle

    def _track_rect(self, groove: QRect, handle: QRect) -> QRect:
        """Bereich zwischen den Mittelpunkten des Abspielstrichs ganz links und ganz rechts."""
        half = handle.width() // 2
        return QRect(
            groove.left() + half,
            groove.top() + VERTICAL_PADDING,
            max(1, groove.width() - 2 * half),
            max(1, groove.height() - 2 * VERTICAL_PADDING),
        )

    # -------------------------------------------------------------- Zeichnen
    def _render(self, rect: QRect, peak_color: QColor, rms_color: QColor) -> QPixmap:
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(int(rect.width() * ratio), int(rect.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        columns = max(1, int(rect.width() * ratio))
        # Je Pixelspalte den größten Wert der zugehörigen Punkte nehmen.
        edges = np.linspace(0, self._peaks.size, columns + 1).astype(int)
        edges = np.minimum(edges, self._peaks.size - 1)
        peaks = np.maximum.reduceat(self._peaks, edges[:-1])
        rms = np.maximum.reduceat(self._rms, edges[:-1])

        middle = rect.height() / 2
        scale = rect.height() / 2
        xs = (np.arange(columns) + 0.5) / ratio
        painter = QPainter(pixmap)
        for values, color in ((peaks, peak_color), (rms, rms_color)):
            pen = painter.pen()
            pen.setColor(color)
            pen.setWidthF(1.0 / ratio)
            painter.setPen(pen)
            heights = np.maximum(values * scale, 0.5 / ratio)
            painter.drawLines([
                QLineF(x, middle - h, x, middle + h) for x, h in zip(xs.tolist(), heights.tolist())
            ])
        painter.end()
        return pixmap

    def resizeEvent(self, event) -> None:
        self._pixmaps = None
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        groove, handle = self._subcontrols()
        track = self._track_rect(groove, handle)
        playhead_x = handle.center().x()
        span = self.maximum() - self.minimum()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._peaks is not None:
            if self._pixmaps is None or self._pixmaps[0] != track:
                self._pixmaps = (
                    QRect(track),
                    self._render(track, PLAYED_PEAK, PLAYED_RMS),
                    self._render(track, REST_PEAK, REST_RMS),
                )
            _, played, rest = self._pixmaps
            painter.drawPixmap(track.topLeft(), rest)
            if span > 0:
                painter.setClipRect(QRect(track.left(), track.top(), playhead_x - track.left(), track.height()))
                painter.drawPixmap(track.topLeft(), played)
                painter.setClipping(False)
        else:
            # Schlichter Balken, solange die Wellenform noch nicht bekannt ist.
            bar = QRect(track.left(), track.center().y() - 8, track.width(), 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(BAR_BACKGROUND)
            painter.drawRoundedRect(bar, 8, 8)
            if span > 0 and playhead_x > bar.left():
                painter.setBrush(BAR_PLAYED)
                painter.drawRoundedRect(QRect(bar.left(), bar.top(), playhead_x - bar.left(), bar.height()), 8, 8)
            if self._pending:
                font = painter.font()
                font.setPixelSize(18)
                painter.setFont(font)
                painter.setPen(PENDING_TEXT)
                painter.drawText(
                    QRect(track.left(), bar.bottom() + 6, track.width(), track.bottom() - bar.bottom() - 6),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    "Wellenform wird berechnet …",
                )
        painter.end()
        # Abspielstrich (Groove ist per Stylesheet unsichtbar) und Markierungen darüber.
        super().paintEvent(event)
