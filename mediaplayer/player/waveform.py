"""Wellenform eines Titels für die Anzeige im Positionsregler.

Beim Dekodieren (``analysis.AudioAnalyzer``) werden fortlaufend kurze Fenster
zusammengefasst: Spitzenwert und mittlere Leistung je ``WINDOW_S``. Daraus
entsteht am Ende eine feste Anzahl von Punkten (``POINTS``), unabhängig von
der Länge des Titels – ein Hörbuch braucht so nicht mehr Speicher als ein Song.

Gespeichert werden zwei Bytefolgen gleicher Länge (0–255): Spitzenwerte und
RMS, beide auf den lautesten Punkt des Titels normiert.
"""

import numpy as np

WINDOW_S = 0.02     # 20 ms je Fenster beim Mitrechnen
POINTS = 2000       # Auflösung der gespeicherten Wellenform (≈ breiter Bildschirm)


class WaveformAccumulator:
    """Sammelt Spitzenwert und mittlere Leistung je Fenster, Puffer für Puffer."""

    def __init__(self, rate: int):
        self.window = max(1, int(rate * WINDOW_S))
        self._carry = np.zeros(0, dtype=np.float32)
        self._peaks: list[np.ndarray] = []
        self._power: list[np.ndarray] = []

    def add(self, samples: np.ndarray) -> None:
        data = np.concatenate([self._carry, samples]) if self._carry.size else samples
        n = data.size // self.window
        if n:
            frames = np.abs(data[: n * self.window]).reshape(n, self.window)
            self._peaks.append(frames.max(axis=1))
            self._power.append((frames * frames).mean(axis=1))
        self._carry = data[n * self.window:].copy()

    def finish(self) -> tuple[np.ndarray, np.ndarray]:
        """(Spitzenwerte, Leistung) aller Fenster inklusive des angebrochenen letzten."""
        if self._carry.size:
            rest = np.abs(self._carry)
            self._peaks.append(np.array([rest.max()], dtype=np.float32))
            self._power.append(np.array([(rest * rest).mean()], dtype=np.float32))
            self._carry = np.zeros(0, dtype=np.float32)
        if not self._peaks:
            empty = np.zeros(0, dtype=np.float32)
            return empty, empty
        return np.concatenate(self._peaks), np.concatenate(self._power)


def build_waveform(peaks: np.ndarray, power: np.ndarray, points: int = POINTS) -> tuple[bytes, bytes]:
    """Fasst die Fenster zu höchstens ``points`` Punkten zusammen (je 0–255).

    Gibt (b"", b"") zurück, wenn nichts Hörbares vorhanden ist.
    """
    if peaks.size == 0:
        return b"", b""
    count = min(points, peaks.size)
    # Gleichmäßig über die Zeit verteilen: Punkt i deckt die Fenster ab Index
    # starts[i] ab. (np.array_split wäre ungleichmäßig – vorne größere Gruppen –
    # und würde die Wellenform zeitlich verzerren.)
    starts = np.floor(np.arange(count) * peaks.size / count).astype(np.int64)
    sizes = np.diff(np.append(starts, peaks.size))
    peak = np.maximum.reduceat(peaks, starts).astype(np.float32)
    rms = np.sqrt(np.add.reduceat(power, starts) / sizes).astype(np.float32)
    top = float(peak.max())
    if top <= 1e-6:
        return b"", b""
    to_bytes = lambda values: np.clip(np.round(values / top * 255), 0, 255).astype(np.uint8).tobytes()
    return to_bytes(peak), to_bytes(rms)
