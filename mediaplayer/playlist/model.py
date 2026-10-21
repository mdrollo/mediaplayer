"""Playlist-Datenmodell ohne Qt-Abhängigkeit.

Die Playlist kennt nur Dateipfade und den Index des aktuellen Titels.
Wiedergabeentscheidungen (abspielen oder nur auswählen) trifft der
``PlaybackController``.
"""

import random
from pathlib import Path

# MP3 wird garantiert unterstützt; die übrigen Formate hängen vom
# Multimedia-Backend des Betriebssystems ab, funktionieren aber in der Regel.
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}


def is_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def _normalize(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


class Playlist:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.current_index: int = -1
        # Reihenfolge vor dem ersten Mischen; None = nicht gemischt.
        # Wird für die Sitzungsspeicherung verwendet, damit Mischen
        # nichts dauerhaft verändert.
        self._unshuffled: list[str] | None = None

    def __len__(self) -> int:
        return len(self.items)

    def is_valid_index(self, index: int) -> bool:
        return 0 <= index < len(self.items)

    @property
    def current_path(self) -> str | None:
        return self.items[self.current_index] if self.is_valid_index(self.current_index) else None

    def title(self, index: int) -> str:
        return Path(self.items[index]).stem

    # ---------------------------------------------------------- Ändern
    def add(self, paths) -> int:
        """Fügt Audiodateien hinzu (Duplikate werden übersprungen).

        Gibt die Anzahl tatsächlich hinzugefügter Titel zurück.
        """
        known = set(self.items)
        added = 0
        for path in paths:
            if not is_audio_file(path):
                continue
            normalized = _normalize(path)
            if normalized in known:
                continue
            self.items.append(normalized)
            if self._unshuffled is not None:
                self._unshuffled.append(normalized)
            known.add(normalized)
            added += 1
        if self.current_index < 0 and self.items:
            self.current_index = 0
        return added

    def remove(self, index: int) -> bool:
        """Entfernt einen Titel. Gibt True zurück, wenn es der aktuelle war."""
        if not self.is_valid_index(index):
            return False
        was_current = index == self.current_index
        path = self.items.pop(index)
        if self._unshuffled is not None:
            self._unshuffled.remove(path)
        if not self.items:
            self.current_index = -1
        elif index < self.current_index:
            self.current_index -= 1
        elif self.current_index >= len(self.items):
            self.current_index = len(self.items) - 1
        return was_current

    def clear(self) -> None:
        self.items.clear()
        self.current_index = -1
        self._unshuffled = None

    def replace(self, items: list[str], current_index: int = 0) -> None:
        self.items = []
        self.current_index = -1
        self._unshuffled = None
        self.add(items)
        if self.items:
            self.current_index = current_index if self.is_valid_index(current_index) else 0

    def shuffle(self, rng: random.Random | None = None) -> None:
        """Mischt die Reihenfolge einmal durch.

        Der aktuelle Titel rückt an die erste Stelle, damit eine laufende
        Wiedergabe ungestört weiterläuft und danach die gemischten Titel folgen.
        """
        if len(self.items) < 2:
            return
        if self._unshuffled is None:
            self._unshuffled = list(self.items)
        current = self.current_path
        rest = [p for p in self.items if p != current]
        (rng or random).shuffle(rest)
        self.items = ([current] if current else []) + rest
        if current:
            self.current_index = 0

    @property
    def is_shuffled(self) -> bool:
        return self._unshuffled is not None

    def unshuffled_state(self) -> tuple[list[str], int]:
        """Reihenfolge ohne Mischen und Index des aktuellen Titels darin."""
        items = list(self._unshuffled if self._unshuffled is not None else self.items)
        current = self.current_path
        return items, items.index(current) if current in items else -1

    # ------------------------------------------------------- Navigation
    def next_index(self) -> int | None:
        """Index des nächsten Titels oder None am Ende der Playlist."""
        candidate = self.current_index + 1
        return candidate if self.is_valid_index(candidate) else None

    def previous_index(self) -> int | None:
        """Index des vorherigen Titels oder None am Anfang der Playlist."""
        candidate = self.current_index - 1
        return candidate if self.is_valid_index(candidate) else None
