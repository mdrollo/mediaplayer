"""Tempo in BPM: Erkennung pro Titel, Einstellen von Ziel-BPM, "BPM fest", Mittippen.

Begriffe:

* **Original-BPM** – Tempo der Datei (erkannt, aus dem Cache oder korrigiert).
* **Aktuelle BPM** – Original-BPM × Wiedergabegeschwindigkeit.
* **BPM fest** – beim Titelwechsel wird die Geschwindigkeit so gewählt, dass
  der neue Titel mit denselben aktuellen BPM läuft (begrenzt auf 0,5x–2,0x).

Ist für einen Titel kein Tempo bekannt, arbeitet alles wie bisher mit der
Geschwindigkeit (0,01x-Schritte).
"""

import statistics
import time

from PySide6.QtCore import QObject, Signal

from ..settings import AppSettings
from .analysis import TrackAnalysisService
from .playback import PlaybackController

TAP_TIMEOUT_S = 2.0   # längere Pause beginnt eine neue Tap-Folge
TAP_MIN_TAPS = 4      # ab so vielen Taps wird ein Tempo übernommen
TAP_MAX_TAPS = 12     # nur die letzten Taps zählen


class TempoController(QObject):
    # original_bpm (0 = unbekannt), aktuelle BPM, Geschwindigkeit, Analyse läuft
    tempoChanged = Signal(float, float, float, bool)
    message = Signal(str)

    def __init__(
        self,
        playback: PlaybackController,
        settings: AppSettings,
        analysis: TrackAnalysisService,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._playback = playback
        self._settings = settings
        self._analysis = analysis
        analysis.analyzed.connect(self._on_analyzed)

        self._path = ""
        self._original = 0.0
        self._analyzing = False
        self._locked, self._target = settings.bpm_lock()
        self._taps: list[float] = []

        playback.currentIndexChanged.connect(self._on_track_changed)
        playback.speedChanged.connect(lambda _speed: self._emit())

    # ------------------------------------------------------------ Status
    def original_bpm(self) -> float:
        return self._original

    def current_bpm(self) -> float:
        return self._original * self._playback.speed() if self._original else 0.0

    def is_locked(self) -> bool:
        return self._locked

    def is_analyzing(self) -> bool:
        return self._analyzing

    # --------------------------------------------------------- Einstellen
    def set_bpm(self, bpm: float) -> None:
        """Aktuelle BPM einstellen (nur wenn das Original-Tempo bekannt ist)."""
        if not self._original:
            return
        self._playback.set_speed(bpm / self._original)
        self._remember_target()

    def step(self, steps: int) -> None:
        """+/-: 1 BPM pro Schritt, ohne bekanntes Tempo 0,01x."""
        if self._original:
            current = round(self.current_bpm())
            self.set_bpm(current + steps)
        else:
            self._playback.change_speed(steps)

    def reset(self) -> None:
        """Originaltempo (1,0x)."""
        self._playback.reset_speed()
        self._remember_target()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        if locked and self._original:
            self._target = round(self.current_bpm(), 1)
        self._settings.set_bpm_lock(self._locked, self._target)
        if locked:
            self.message.emit(
                f"BPM fest: alle Titel laufen mit {self._target:.0f} BPM." if self._target
                else "BPM fest: aktiv, sobald das Tempo bekannt ist."
            )
        self._emit()

    def _remember_target(self) -> None:
        if self._locked and self._original:
            self._target = round(self.current_bpm(), 1)
            self._settings.set_bpm_lock(True, self._target)

    # ----------------------------------------------------------- Korrektur
    def halve(self) -> None:
        self._correct(self._original / 2)

    def double(self) -> None:
        self._correct(self._original * 2)

    def tap(self) -> None:
        """Im Takt mittippen; ab TAP_MIN_TAPS Taps wird das Tempo übernommen."""
        now = time.monotonic()
        if self._taps and now - self._taps[-1] > TAP_TIMEOUT_S:
            self._taps = []
        self._taps = (self._taps + [now])[-TAP_MAX_TAPS:]
        if len(self._taps) < TAP_MIN_TAPS:
            self.message.emit(f"Im Takt tippen … ({len(self._taps)}/{TAP_MIN_TAPS})")
            return
        intervals = [b - a for a, b in zip(self._taps, self._taps[1:])]
        tapped = 60.0 / statistics.median(intervals)
        # Getippt wird zum hörbaren Tempo – das enthält die aktuelle Geschwindigkeit.
        self._correct(tapped / self._playback.speed(), quiet=True)
        self.message.emit(f"Getippt: {tapped:.0f} BPM")

    def _correct(self, original: float, quiet: bool = False) -> None:
        if not self._path or not (20 <= original <= 400):
            return
        self._original = round(original, 1)
        self._settings.store_bpm(self._path, self._original, manual=True)
        if not quiet:
            self.message.emit(f"Original-Tempo: {self._original:.1f} BPM".replace(".", ","))
        self._apply_lock()
        self._emit()

    # ----------------------------------------------------- Titel / Analyse
    def _on_track_changed(self, index: int) -> None:
        playlist = self._playback.playlist
        path = playlist.items[index] if playlist.is_valid_index(index) else ""
        if path == self._path:
            return
        self._path = path
        self._taps = []
        self._original = 0.0
        self._analyzing = False
        if path:
            cached = self._settings.cached_bpm(path)
            if cached is not None:
                self._original = cached[0]
                self._apply_lock()
            else:
                self._analyzing = True  # die Analyse startet der TrackAnalysisService
        self._emit()

    def _on_analyzed(self, path: str) -> None:
        if path != self._path:
            return
        cached = self._settings.cached_bpm(path)
        self._analyzing = False
        new_original = cached[0] if cached else 0.0
        if new_original != self._original:
            self._original = new_original
            self._apply_lock()
        self._emit()

    def _apply_lock(self) -> None:
        if self._locked and self._original and self._target:
            self._playback.set_speed(self._target / self._original)

    def _emit(self) -> None:
        self.tempoChanged.emit(self._original, self.current_bpm(), self._playback.speed(), self._analyzing)
