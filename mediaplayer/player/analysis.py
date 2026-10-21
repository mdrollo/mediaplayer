"""Hintergrundanalyse der Titel: Tempo (BPM) sowie Musikanfang und -ende.

* ``AudioAnalyzer`` dekodiert eine Datei mit ``QAudioDecoder`` (gleiches
  FFmpeg-Backend wie die Wiedergabe) zu Mono-Samples mit niedriger Abtastrate.
  Gespeichert werden nur der Anfang (für BPM und Musikanfang) und ein
  gleitendes Fenster der letzten Sekunden (für das Musikende) – so bleibt der
  Speicherbedarf auch bei stundenlangen Hörbüchern klein. Gerechnet wird in
  einem Hintergrund-Thread.
* ``TrackAnalysisService`` analysiert den laufenden Titel sofort und danach
  alle übrigen Titel der Playlist nacheinander. Ergebnisse landen im Cache der
  Einstellungen; jede Datei wird nur einmal analysiert.
"""

import collections
import threading

import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

from ..settings import AppSettings
from .bpm import ANALYSIS_LENGTH_S, ANALYSIS_SKIP_S, analysis_window, estimate_bpm
from .playback import PlaybackController
from .silence import music_end, music_start

ANALYSIS_RATE = 11025   # Hz – reicht für Rhythmus und Lautstärke
TAIL_S = 30             # so viele Sekunden vom Ende für die Stille-Erkennung behalten


class AudioAnalyzer(QObject):
    """Analysiert eine Datei; ``analyze(path)`` ersetzt eine laufende Analyse.

    ``finished(path, bpm, start_s, end_s)``: bpm = 0.0, wenn kein Takt erkannt
    wurde; start/end = -1.0, wenn die Datei nicht dekodiert werden konnte.
    """

    finished = Signal(str, float, float, float)
    _computed = Signal(str, float, float, float)  # intern: aus dem Rechen-Thread zurück

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._decoder = QAudioDecoder(self)
        fmt = QAudioFormat()
        fmt.setSampleRate(ANALYSIS_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self._decoder.setAudioFormat(fmt)
        self._decoder.bufferReady.connect(self._on_buffer)
        self._decoder.finished.connect(self._on_decoded)
        self._decoder.error.connect(self._on_error)
        self._computed.connect(self._on_computed)
        self._path = ""
        self._decoding = False
        self._generation = 0  # Laufnummer: verwirft Ergebnisse abgebrochener Läufe
        self._rate = ANALYSIS_RATE
        self._reset_buffers()

    def _reset_buffers(self) -> None:
        self._head: list[np.ndarray] = []
        self._head_size = 0
        self._tail: collections.deque[np.ndarray] = collections.deque()
        self._tail_size = 0
        self._total = 0

    def current_path(self) -> str:
        return self._path

    def analyze(self, path: str) -> None:
        if path == self._path:
            return  # läuft bereits
        # Erst als "nicht dekodierend" markieren: stop() kann noch Signale des
        # alten Laufs auslösen, die sonst als (Teil-)Ergebnis gewertet würden.
        self._decoding = False
        self._generation += 1
        self._decoder.stop()
        self._path = path
        self._reset_buffers()
        self._decoding = True
        self._decoder.setSource(QUrl.fromLocalFile(path))
        self._decoder.start()

    def cancel(self) -> None:
        self._decoding = False
        self._generation += 1
        self._decoder.stop()
        self._path = ""
        self._reset_buffers()

    @Slot()
    def _on_buffer(self) -> None:
        buffer = self._decoder.read()
        if not buffer.isValid() or not self._decoding:
            return
        fmt = buffer.format()
        data = self._convert(bytes(buffer.constData()), fmt)
        channels = max(1, fmt.channelCount())
        if channels > 1:
            data = data[: data.size - data.size % channels].reshape(-1, channels).mean(axis=1)
        data = np.array(data, dtype=np.float32)  # eigene Kopie
        self._rate = fmt.sampleRate() or ANALYSIS_RATE
        self._total += data.size

        head_limit = (ANALYSIS_SKIP_S + ANALYSIS_LENGTH_S) * self._rate
        if self._head_size < head_limit:
            self._head.append(data)
            self._head_size += data.size
        self._tail.append(data)
        self._tail_size += data.size
        tail_limit = TAIL_S * self._rate
        while self._tail and self._tail_size - self._tail[0].size >= tail_limit:
            self._tail_size -= self._tail.popleft().size

    @staticmethod
    def _convert(raw: bytes, fmt: QAudioFormat) -> np.ndarray:
        kind = fmt.sampleFormat()
        if kind == QAudioFormat.SampleFormat.Int16:
            return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if kind == QAudioFormat.SampleFormat.Int32:
            return np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        if kind == QAudioFormat.SampleFormat.UInt8:
            return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        return np.frombuffer(raw, dtype=np.float32)

    @Slot()
    def _on_decoded(self) -> None:
        if not self._decoding:
            return
        self._decoding = False
        path, generation, rate = self._path, self._generation, self._rate
        empty = np.zeros(0, dtype=np.float32)
        head = np.concatenate(self._head) if self._head else empty
        tail = np.concatenate(self._tail) if self._tail else empty
        total_s = self._total / rate
        tail_offset_s = (self._total - tail.size) / rate
        self._reset_buffers()

        def work():
            try:
                bpm = estimate_bpm(analysis_window(head, rate), rate) or 0.0
                start = music_start(head, rate)
                end = music_end(tail, rate, tail_offset_s, total_s)
                if end <= start:  # durchgehend still – nichts überspringen
                    start, end = 0.0, total_s
            except Exception:  # Analyse darf die Wiedergabe nie stören
                bpm, start, end = 0.0, 0.0, total_s
            self._computed.emit(f"{generation}|{path}", float(bpm), float(start), float(end))

        threading.Thread(target=work, name="Audio-Analyse", daemon=True).start()

    @Slot(QAudioDecoder.Error)
    def _on_error(self, _error) -> None:
        path, self._path = self._path, ""
        self._decoding = False
        self._reset_buffers()
        if path:
            self.finished.emit(path, 0.0, -1.0, -1.0)

    @Slot(str, float, float, float)
    def _on_computed(self, tagged_path: str, bpm: float, start: float, end: float) -> None:
        generation, _, path = tagged_path.partition("|")
        if int(generation) == self._generation and path == self._path:
            self._path = ""
            self.finished.emit(path, bpm, start, end)


class TrackAnalysisService(QObject):
    """Steuert die Analyse aller Titel und hält die Ergebnisse im Cache.

    ``analyzed(path)`` wird gesendet, sobald neue Werte für eine Datei vorliegen.
    """

    analyzed = Signal(str)

    def __init__(self, playback: PlaybackController, settings: AppSettings, parent: QObject | None = None):
        super().__init__(parent)
        self._playback = playback
        self._settings = settings
        self._analyzer = AudioAnalyzer(self)
        self._analyzer.finished.connect(self._on_finished)
        self._queue: list[str] = []
        self._current = ""
        playback.currentIndexChanged.connect(self._on_track_changed)
        playback.playlistChanged.connect(self._queue_playlist)

    def info(self, path: str) -> dict | None:
        return self._settings.cached_analysis(path)

    def is_pending(self, path: str) -> bool:
        return bool(path) and not self._settings.is_analysis_complete(path)

    def shutdown(self) -> None:
        self._queue = []
        self._analyzer.cancel()

    def _on_track_changed(self, index: int) -> None:
        playlist = self._playback.playlist
        path = playlist.items[index] if playlist.is_valid_index(index) else ""
        if path == self._current:
            self._push_bounds(path)  # derselbe Titel neu geladen
            return
        self._current = path
        self._push_bounds(path)
        if path and self.is_pending(path):
            interrupted = self._analyzer.current_path()
            if interrupted and interrupted != path:
                self._queue.insert(0, interrupted)  # später fortsetzen
            self._analyzer.analyze(path)  # laufender Titel hat Vorrang

    def _push_bounds(self, path: str) -> None:
        """Musikanfang/-ende an die Wiedergabe weitergeben (für "Pausen überspringen")."""
        entry = self.info(path) if path else None
        if entry and "start" in entry and "end" in entry:
            self._playback.set_music_bounds(path, int(entry["start"] * 1000), int(entry["end"] * 1000))

    def _queue_playlist(self) -> None:
        self._queue = [p for p in self._playback.playlist.items if self.is_pending(p)]
        if not self._analyzer.current_path():
            self._next_in_queue()

    def _next_in_queue(self) -> None:
        while self._queue:
            path = self._queue.pop(0)
            if self.is_pending(path):
                self._analyzer.analyze(path)
                return

    def _on_finished(self, path: str, bpm: float, start: float, end: float) -> None:
        if start < 0:  # nicht dekodierbar: nur "kein Takt" vermerken
            self._settings.store_analysis(path, bpm=0.0, start=0.0, end=0.0)
        else:
            self._settings.store_analysis(path, bpm=bpm, start=start, end=end)
        if path == self._current:
            self._push_bounds(path)
        self.analyzed.emit(path)
        self._next_in_queue()
