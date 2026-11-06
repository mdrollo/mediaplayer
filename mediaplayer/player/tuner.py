"""Chromatisches Stimmgerät: Mikrofon lesen, Tonhöhe erkennen, glätten.

``TunerController`` nimmt über ``QAudioSource`` vom Standard-Mikrofon auf,
sammelt die letzten ``WINDOW_SECONDS`` Audio und wertet sie alle
``UPDATE_MS`` Millisekunden mit :func:`pitch.detect_pitch` aus.

Ausgabe (Signal ``reading``): ``(ton, oktave, cent, frequenz, soll)`` – oder
``("", 0, 0.0, 0.0, 0.0)``, wenn gerade kein Ton zu hören ist.

Das Mikrofon ist nur geöffnet, solange das Stimmgerät eingeblendet ist
(``start()``/``stop()``). Zum Testen lassen sich mit ``feed()`` Samples direkt
einspeisen, ganz ohne Audiogerät.
"""

from collections import deque
from statistics import median

import numpy as np
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices

from .pitch import (
    A4_DEFAULT,
    A4_MAX,
    A4_MIN,
    detect_pitch,
    frequency_from_midi,
    midi_from_frequency,
    note_for_frequency,
)

SAMPLE_RATE = 44100
WINDOW_SECONDS = 0.1      # ~4400 Samples: reicht bis zum tiefsten Klavier-A
UPDATE_MS = 50            # 20 Anzeigen pro Sekunde
HISTORY = 5               # Median über die letzten Messungen gegen Ausreißer
HOLD_MS = 600             # nach dem Verklingen den letzten Ton noch so lange zeigen
NOTE_JUMP = 0.6           # Halbtöne: größerer Sprung = neuer Ton, Glättung neu beginnen
SMOOTHING = 0.35          # Anteil des neuen Werts (0..1) – kleiner = ruhigere Nadel


class TunerController(QObject):
    reading = Signal(str, int, float, float, float)
    message = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self, a4: float = A4_DEFAULT, parent: QObject | None = None):
        super().__init__(parent)
        self._a4 = clamp_a4(a4)
        self._source: QAudioSource | None = None
        self._io = None
        self._format: QAudioFormat | None = None
        self._rate = SAMPLE_RATE
        self._buffer = np.zeros(0, dtype=np.float32)
        self._history: deque[float] = deque(maxlen=HISTORY)
        self._smoothed: float | None = None   # geglättete Tonhöhe (MIDI, gebrochen)
        self._silent_ms = 0
        self._wanted = False

        self._timer = QTimer(self)
        self._timer.setInterval(UPDATE_MS)
        self._timer.timeout.connect(self._analyze)

    # ------------------------------------------------------- Kammerton
    def a4(self) -> float:
        return self._a4

    def set_a4(self, a4: float) -> None:
        self._a4 = clamp_a4(a4)
        self._emit_current()

    # ------------------------------------------------------- Mikrofon
    def is_running(self) -> bool:
        return self._source is not None

    def start(self) -> None:
        """Mikrofon öffnen (fragt unter macOS beim ersten Mal nach der Erlaubnis)."""
        self._wanted = True
        if self._source is not None:
            return
        if not self._request_permission():
            return  # Antwort kommt asynchron, siehe _on_permission
        self._open()

    def stop(self) -> None:
        self._wanted = False
        self._timer.stop()
        if self._source is not None:
            self._source.stop()
            self._source.deleteLater()
            self._source = None
            self._io = None
            self.runningChanged.emit(False)
        self._reset_reading()

    def _request_permission(self) -> bool:
        """True = Zugriff erlaubt (oder die Plattform fragt nicht)."""
        try:
            from PySide6.QtCore import QMicrophonePermission, Qt
        except ImportError:  # ältere Qt-Versionen kennen keine Berechtigungen
            return True
        app = QCoreApplication.instance()
        permission = QMicrophonePermission()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Granted:
            return True
        if status == Qt.PermissionStatus.Denied:
            self._permission_denied()
            return False
        app.requestPermission(permission, self, self._on_permission)
        return False

    def _on_permission(self, permission) -> None:
        from PySide6.QtCore import Qt

        if QCoreApplication.instance().checkPermission(permission) == Qt.PermissionStatus.Granted:
            if self._wanted:
                self._open()
        else:
            self._permission_denied()

    def _permission_denied(self) -> None:
        self.message.emit(
            "Kein Zugriff auf das Mikrofon – bitte in den Datenschutz-Einstellungen "
            "des Systems erlauben."
        )

    def _open(self) -> None:
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.message.emit("Kein Mikrofon gefunden.")
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self._format = fmt
        self._rate = fmt.sampleRate() or SAMPLE_RATE
        self._buffer = np.zeros(0, dtype=np.float32)

        source = QAudioSource(device, fmt, self)
        # Kleiner Puffer = kurze Verzögerung zwischen Ton und Anzeige.
        source.setBufferSize(max(1024, fmt.bytesForDuration(UPDATE_MS * 1000)))
        io = source.start()
        if io is None:
            source.deleteLater()
            self.message.emit("Mikrofon konnte nicht geöffnet werden.")
            return
        self._source, self._io = source, io
        io.readyRead.connect(self._read)
        self._timer.start()
        self.runningChanged.emit(True)

    def _read(self) -> None:
        if self._io is None or self._format is None:
            return
        data = bytes(self._io.readAll())
        if data:
            self.feed(decode_samples(data, self._format), self._rate)

    # ------------------------------------------------------- Auswertung
    def feed(self, samples: np.ndarray, rate: int | None = None) -> None:
        """Mono-Samples (−1 … 1) anhängen; nur das jüngste Analysefenster bleibt."""
        if rate:
            self._rate = rate
        size = int(self._rate * WINDOW_SECONDS)
        self._buffer = np.concatenate((self._buffer, np.asarray(samples, dtype=np.float32)))[-size:]

    def process(self) -> None:
        """Eine Messung sofort auswerten (für Tests, sonst per Zeitgeber)."""
        self._analyze()

    def _analyze(self) -> None:
        if len(self._buffer) < int(self._rate * WINDOW_SECONDS):
            return
        result = detect_pitch(self._buffer, self._rate)
        if result is None:
            self._silent_ms += UPDATE_MS
            if self._silent_ms >= HOLD_MS and self._smoothed is not None:
                self._reset_reading()
            return
        self._silent_ms = 0
        # Fester Bezug (440 Hz), damit eine Änderung des Kammertons die
        # Glättung nicht durcheinanderbringt; umgerechnet wird erst bei der Anzeige.
        midi = midi_from_frequency(result[0], A4_DEFAULT)
        if self._history and abs(midi - median(self._history)) > NOTE_JUMP:
            self._history.clear()
            self._smoothed = None
        self._history.append(midi)
        target = median(self._history)
        if self._smoothed is None:
            self._smoothed = target
        else:
            self._smoothed += SMOOTHING * (target - self._smoothed)
        self._emit_current()

    def _reset_reading(self) -> None:
        self._history.clear()
        self._smoothed = None
        self._silent_ms = 0
        self.reading.emit("", 0, 0.0, 0.0, 0.0)

    def _emit_current(self) -> None:
        if self._smoothed is None:
            return
        freq = frequency_from_midi(self._smoothed, A4_DEFAULT)
        name, octave, cents, target = note_for_frequency(freq, self._a4)
        self.reading.emit(name, octave, cents, freq, target)


def clamp_a4(a4: float) -> float:
    try:
        value = float(a4)
    except (TypeError, ValueError):
        return A4_DEFAULT
    return max(A4_MIN, min(A4_MAX, value))


def decode_samples(data: bytes, fmt: QAudioFormat) -> np.ndarray:
    """Rohdaten des Mikrofons in Mono-Gleitkommawerte (−1 … 1) umwandeln."""
    kind = fmt.sampleFormat()
    F = QAudioFormat.SampleFormat
    if kind == F.Float:
        samples = np.frombuffer(data, dtype=np.float32, count=len(data) // 4)
    elif kind == F.Int16:
        samples = np.frombuffer(data, dtype=np.int16, count=len(data) // 2) / 32768.0
    elif kind == F.Int32:
        samples = np.frombuffer(data, dtype=np.int32, count=len(data) // 4) / 2147483648.0
    elif kind == F.UInt8:
        samples = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        return np.zeros(0, dtype=np.float32)
    channels = max(1, fmt.channelCount())
    if channels > 1:
        usable = len(samples) // channels * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32, copy=False)
