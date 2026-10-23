"""Markierungen (Sprungmarken) im aktuell geladenen Titel.

Markierungen werden pro Datei dauerhaft gespeichert (``AppSettings.markers``)
und beim Titelwechsel automatisch geladen. Positionen sind Medienzeit in ms,
also unabhängig vom eingestellten Tempo.

Sprungregeln:

* "Vorherige Markierung" springt zur letzten Markierung vor der aktuellen
  Position. Liegt die Position nur knapp hinter einer Markierung
  (``PREVIOUS_GRACE_MS``, z. B. weil man gerade dorthin gesprungen ist und die
  Musik weiterläuft), geht es eine weiter zurück, so dass mehrfaches Drücken
  Markierung für Markierung zurückführt.
* "Nächste Markierung" springt zur ersten Markierung hinter der Position.
* "Löschen" entfernt die Markierung, die der aktuellen Position am nächsten ist.
"""

from PySide6.QtCore import QObject, Signal

from ..settings import AppSettings
from .playback import PlaybackController, format_ms

MIN_MARKER_DISTANCE_MS = 500   # näher beieinander liegende Markierungen gelten als gleich
PREVIOUS_GRACE_MS = 1500       # siehe "Vorherige Markierung" oben
NEXT_TOLERANCE_MS = 100        # eine Markierung direkt an der Position zählt nicht als "nächste"


def previous_marker(markers: list[int], position: int) -> int | None:
    candidates = [m for m in markers if m < position - PREVIOUS_GRACE_MS]
    return candidates[-1] if candidates else None


def next_marker(markers: list[int], position: int) -> int | None:
    return next((m for m in markers if m > position + NEXT_TOLERANCE_MS), None)


def nearest_marker(markers: list[int], position: int) -> int | None:
    return min(markers, key=lambda m: abs(m - position)) if markers else None


class MarkerController(QObject):
    """Verwaltet die Markierungen des geladenen Titels."""

    markersChanged = Signal(list)   # sortierte Positionen in ms
    message = Signal(str)

    def __init__(self, controller: PlaybackController, settings: AppSettings, parent: QObject | None = None):
        super().__init__(parent)
        self._controller = controller
        self._settings = settings
        self._path: str | None = None
        self._markers: list[int] = []
        controller.currentIndexChanged.connect(self._on_track_changed)
        self._on_track_changed()

    def markers(self) -> list[int]:
        return list(self._markers)

    # ---------------------------------------------------------- Aktionen
    def add_at_current(self) -> None:
        if not self._has_track():
            return
        position = max(0, int(self._controller.position()))
        nearest = nearest_marker(self._markers, position)
        if nearest is not None and abs(nearest - position) < MIN_MARKER_DISTANCE_MS:
            self.message.emit(f"An dieser Stelle ({format_ms(nearest)}) ist bereits eine Markierung.")
            return
        self._store(self._markers + [position])
        self.message.emit(f"Markierung bei {format_ms(position)} gesetzt.")

    def jump_previous(self) -> None:
        if not self._has_track(need_markers=True):
            return
        target = previous_marker(self._markers, self._controller.position())
        if target is None:
            self.message.emit("Keine Markierung davor.")
            return
        self._controller.seek(target)

    def jump_next(self) -> None:
        if not self._has_track(need_markers=True):
            return
        target = next_marker(self._markers, self._controller.position())
        if target is None:
            self.message.emit("Keine weitere Markierung.")
            return
        self._controller.seek(target)

    def delete_nearest(self) -> None:
        if not self._has_track(need_markers=True):
            return
        target = nearest_marker(self._markers, self._controller.position())
        self._store([m for m in self._markers if m != target])
        self.message.emit(f"Markierung bei {format_ms(target)} gelöscht.")

    def clear(self) -> None:
        if not self._has_track(need_markers=True):
            return
        count = len(self._markers)
        self._store([])
        self.message.emit(f"{count} Markierung(en) gelöscht.")

    # ------------------------------------------------------------ intern
    def _has_track(self, need_markers: bool = False) -> bool:
        if not self._path:
            self.message.emit("Kein Titel geladen.")
            return False
        if need_markers and not self._markers:
            self.message.emit("Dieser Titel hat keine Markierungen.")
            return False
        return True

    def _store(self, markers: list[int]) -> None:
        self._markers = sorted(set(markers))
        if self._path:
            self._settings.set_markers(self._path, self._markers)
        self.markersChanged.emit(self.markers())

    def _on_track_changed(self, *_args) -> None:
        path = self._controller.playlist.current_path
        if path == self._path:
            return
        self._path = path
        self._markers = self._settings.markers(path) if path else []
        self.markersChanged.emit(self.markers())
