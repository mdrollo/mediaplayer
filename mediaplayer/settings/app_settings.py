"""Dauerhafte Einstellungen (Tastenbelegung, Lautstärke, Geschwindigkeit, Sitzung, Markierungen).

Gespeichert wird über ``QSettings`` im INI-Format im Benutzerprofil:

- Windows: ``%APPDATA%\\LocalMediaPlayer\\Mediaplayer.ini``
- macOS:   ``~/.config/LocalMediaPlayer/Mediaplayer.ini``

Komplexe Werte (Listen) werden als JSON abgelegt, weil ``QSettings`` Listen mit
nur einem Element je nach Plattform als einfache Zeichenkette zurückgibt.
"""

import json
import os

from PySide6.QtCore import QSettings

from .. import APP_NAME, ORGANIZATION_NAME
from .key_bindings import ACTIONS, DEFAULT_BINDINGS, KEYS_PER_ACTION, copy_bindings

MAX_RECENT_PLAYLISTS = 10


class AppSettings:
    def __init__(self, qsettings: QSettings | None = None):
        self._s = qsettings or QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            ORGANIZATION_NAME,
            APP_NAME,
        )
        self._bpm_cache: dict | None = None
        self._markers: dict | None = None

    @property
    def file_name(self) -> str:
        return self._s.fileName()

    def sync(self) -> None:
        self._s.sync()

    # ----------------------------------------------------------- Tastatur
    @staticmethod
    def _key_name(action: str, slot: int) -> str:
        # Platz 1 behält den alten Schlüsselnamen, damit vorhandene
        # Einstellungsdateien ohne Zweittaste weiter gelten.
        return f"keys/{action}" if slot == 0 else f"keys/{action}_{slot + 1}"

    def key_bindings(self) -> dict[str, list[str]]:
        """Aktuelle Belegung; fehlende Einträge werden mit Standardwerten gefüllt."""
        bindings = {}
        for action in ACTIONS:
            keys = []
            for slot in range(KEYS_PER_ACTION):
                value = self._s.value(self._key_name(action, slot), None)
                keys.append(DEFAULT_BINDINGS[action][slot] if value is None else str(value))
            bindings[action] = keys
        return bindings

    def set_key_bindings(self, bindings: dict[str, list[str]]) -> None:
        for action, keys in copy_bindings(bindings).items():
            for slot, key in enumerate(keys):
                self._s.setValue(self._key_name(action, slot), key)
        self._s.sync()

    # ------------------------------------------------------------- Audio
    def volume(self, default: int = 80) -> int:
        return _clamp_int(self._s.value("audio/volume", default), 0, 100, default)

    def set_volume(self, percent: int) -> None:
        self._s.setValue("audio/volume", int(percent))

    def speed(self, default: float = 1.0) -> float:
        try:
            return float(self._s.value("audio/speed", default))
        except (TypeError, ValueError):
            return default

    def set_speed(self, speed: float) -> None:
        self._s.setValue("audio/speed", f"{speed:.4f}")

    # ----------------------------------------------------------- Sitzung
    def session_playlist(self) -> tuple[list[str], int]:
        """Zuletzt verwendete Playlist und ausgewählter Index."""
        raw = self._s.value("session/playlist", "[]")
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                items = []
        except (TypeError, ValueError):
            items = []
        index = _clamp_int(self._s.value("session/index", -1), -1, len(items) - 1, -1)
        return [str(p) for p in items], index

    def set_session_playlist(self, items: list[str], index: int) -> None:
        self._s.setValue("session/playlist", json.dumps(items, ensure_ascii=False))
        self._s.setValue("session/index", int(index))

    # ------------------------------------------- Zuletzt verwendete Playlists
    def recent_playlists(self) -> list[str]:
        try:
            items = json.loads(self._s.value("recent/playlists", "[]"))
        except (TypeError, ValueError):
            return []
        return [str(p) for p in items] if isinstance(items, list) else []

    def set_recent_playlists(self, paths: list[str]) -> None:
        self._s.setValue("recent/playlists", json.dumps(paths[:MAX_RECENT_PLAYLISTS], ensure_ascii=False))

    def add_recent_playlist(self, path: str) -> None:
        """Playlist an den Anfang der Liste setzen (ohne Duplikate)."""
        key = os.path.normcase(os.path.abspath(path))
        others = [p for p in self.recent_playlists() if os.path.normcase(os.path.abspath(p)) != key]
        self.set_recent_playlists([os.path.abspath(path)] + others)

    def skip_silence(self) -> bool:
        return str(self._s.value("audio/skip_silence", "true")).lower() == "true"

    def set_skip_silence(self, enabled: bool) -> None:
        self._s.setValue("audio/skip_silence", "true" if enabled else "false")

    # ------------------------------------------------------------- Tempo
    def bpm_lock(self) -> tuple[bool, float]:
        """("BPM fest" aktiv?, Ziel-BPM)."""
        locked = str(self._s.value("tempo/lock", "false")).lower() == "true"
        try:
            target = float(self._s.value("tempo/target_bpm", 0))
        except (TypeError, ValueError):
            target = 0.0
        return locked, target

    def set_bpm_lock(self, locked: bool, target: float) -> None:
        self._s.setValue("tempo/lock", "true" if locked else "false")
        self._s.setValue("tempo/target_bpm", f"{target:.1f}")

    # ---------------------------------------------------------- BPM-Cache
    # Eigene JSON-Datei neben der INI: kann viele Einträge enthalten.
    @property
    def _bpm_cache_file(self) -> str:
        return os.path.join(os.path.dirname(self.file_name), "bpm_cache.json")

    def _load_bpm_cache(self) -> dict:
        if self._bpm_cache is None:
            try:
                with open(self._bpm_cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._bpm_cache = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._bpm_cache = {}
        return self._bpm_cache

    @staticmethod
    def _file_signature(path: str) -> tuple[str, int, float] | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        # realpath: gleiche Datei = gleicher Schlüssel, auch bei Kurznamen (8.3) oder Links.
        return os.path.normcase(os.path.realpath(path)), st.st_size, round(st.st_mtime, 1)

    def cached_analysis(self, path: str) -> dict | None:
        """Gespeicherte Analyse einer Datei oder None (unbekannt/Datei verändert).

        Schlüssel: ``bpm`` (0.0 = kein Takt erkennbar), ``manual`` (BPM von Hand
        korrigiert), ``start``/``end`` (Musikanfang/-ende in Sekunden; fehlen
        bei Einträgen aus älteren Versionen).
        """
        sig = self._file_signature(path)
        if sig is None:
            return None
        entry = self._load_bpm_cache().get(sig[0])
        if not isinstance(entry, dict) or entry.get("size") != sig[1] or entry.get("mtime") != sig[2]:
            return None
        return entry

    def is_analysis_complete(self, path: str) -> bool:
        entry = self.cached_analysis(path)
        return entry is not None and "bpm" in entry and "start" in entry and "end" in entry

    def cached_bpm(self, path: str) -> tuple[float, bool] | None:
        """(BPM, manuell korrigiert?) oder None, wenn unbekannt."""
        entry = self.cached_analysis(path)
        try:
            return (float(entry["bpm"]), bool(entry.get("manual", False))) if entry else None
        except (KeyError, TypeError, ValueError):
            return None

    def store_bpm(self, path: str, bpm: float, manual: bool = False) -> None:
        self.store_analysis(path, bpm=bpm, manual=manual)

    def store_analysis(
        self,
        path: str,
        bpm: float | None = None,
        start: float | None = None,
        end: float | None = None,
        manual: bool = False,
    ) -> None:
        """Analyseergebnis speichern; vorhandene Felder werden ergänzt.

        Eine von Hand korrigierte BPM-Angabe wird von einer automatischen
        Analyse nicht überschrieben.
        """
        sig = self._file_signature(path)
        if sig is None:
            return
        cache = self._load_bpm_cache()
        entry = self.cached_analysis(path) or {}
        entry = dict(entry, size=sig[1], mtime=sig[2])
        if bpm is not None and (manual or not entry.get("manual", False)):
            entry["bpm"] = round(bpm, 1)
            entry["manual"] = manual
        if start is not None:
            entry["start"] = round(start, 2)
        if end is not None:
            entry["end"] = round(end, 2)
        cache[sig[0]] = entry
        try:
            os.makedirs(os.path.dirname(self._bpm_cache_file), exist_ok=True)
            tmp = self._bpm_cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            os.replace(tmp, self._bpm_cache_file)
        except OSError:
            pass  # Cache ist nur eine Beschleunigung

    # -------------------------------------------------------- Markierungen
    # Eigene JSON-Datei neben der INI: {Dateipfad: [Position in ms, …]}.
    # Anders als der BPM-Cache ohne Größe/Änderungsdatum im Schlüssel, damit
    # Markierungen z. B. das Bearbeiten der Titel-Tags überstehen.
    @property
    def _markers_file(self) -> str:
        return os.path.join(os.path.dirname(self.file_name), "markers.json")

    def _load_markers(self) -> dict:
        if self._markers is None:
            try:
                with open(self._markers_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._markers = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._markers = {}
        return self._markers

    @staticmethod
    def _marker_key(path: str) -> str:
        return os.path.normcase(os.path.realpath(path))

    def markers(self, path: str) -> list[int]:
        """Gespeicherte Markierungen eines Titels in ms, aufsteigend sortiert."""
        raw = self._load_markers().get(self._marker_key(path), [])
        if not isinstance(raw, list):
            return []
        result = set()
        for value in raw:
            try:
                result.add(max(0, int(value)))
            except (TypeError, ValueError):
                continue
        return sorted(result)

    def set_markers(self, path: str, positions: list[int]) -> None:
        data = self._load_markers()
        key = self._marker_key(path)
        if positions:
            data[key] = sorted({int(p) for p in positions})
        else:
            data.pop(key, None)
        try:
            os.makedirs(os.path.dirname(self._markers_file), exist_ok=True)
            tmp = self._markers_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._markers_file)
        except OSError:
            pass

    # ------------------------------------------------------ Dateidialoge
    def last_directory(self) -> str:
        return str(self._s.value("paths/last_directory", ""))

    def set_last_directory(self, directory: str) -> None:
        self._s.setValue("paths/last_directory", directory)


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if high < low:
        return default
    return max(low, min(high, number))
