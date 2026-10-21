"""Speichern und Laden von Playlist-Dateien.

Unterstützte Formate:

- ``.m3u8`` / ``.m3u`` – Standardformat, auch von anderen Playern lesbar.
  Pfade werden absolut gespeichert; relative Pfade beim Laden werden relativ
  zur Playlist-Datei aufgelöst.
- ``.json`` – Liste von Pfaden (Format des ursprünglichen Prototyps) oder
  ``{"version": 1, "items": [...]}``.
"""

import json
from pathlib import Path

from .model import is_audio_file

PLAYLIST_EXTENSIONS = {".m3u8", ".m3u", ".json"}

PLAYLIST_FILTER = (
    "Playlist (*.m3u8 *.m3u *.json);;"
    "M3U8-Playlist (*.m3u8);;"
    "JSON-Playlist (*.json)"
)


def save_playlist_file(path: str | Path, items: list[str]) -> Path:
    """Speichert die Playlist. Ohne Endung wird ``.m3u8`` angehängt."""
    path = Path(path)
    if path.suffix.lower() not in (".m3u8", ".m3u", ".json"):
        path = path.with_name(path.name + ".m3u8")

    if path.suffix.lower() == ".json":
        text = json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2)
    else:
        lines = ["#EXTM3U"]
        for item in items:
            lines.append(f"#EXTINF:-1,{Path(item).stem}")
            lines.append(item)
        text = "\n".join(lines) + "\n"

    # .m3u ist traditionell nicht UTF-8; wir schreiben trotzdem UTF-8,
    # das lesen alle aktuellen Player.
    path.write_text(text, encoding="utf-8")
    return path


def load_playlist_file(path: str | Path) -> tuple[list[str], list[str]]:
    """Lädt eine Playlist.

    Gibt ``(vorhandene_dateien, fehlende_dateien)`` zurück. Nicht existierende
    oder nicht unterstützte Einträge landen in der zweiten Liste.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("items", [])
        if not isinstance(data, list):
            raise ValueError("Die JSON-Datei enthält keine Playlist.")
        raw_entries = [str(entry) for entry in data]
    else:
        raw_entries = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    found, missing = [], []
    for entry in raw_entries:
        candidate = Path(entry).expanduser()
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        if candidate.is_file() and is_audio_file(candidate):
            found.append(str(candidate.resolve()))
        else:
            missing.append(entry)
    return found, missing
