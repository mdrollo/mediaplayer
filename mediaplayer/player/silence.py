"""Erkennung von Stille am Anfang und Ende eines Titels.

Viele Album-Rips enthalten mehrere Sekunden Stille vor bzw. nach der Musik.
Für "Pausen überspringen" wird ermittelt, wo die Musik hörbar beginnt und
endet. Die Werte gelten in Medienzeit (unabhängig von der Wiedergabe-
geschwindigkeit).
"""

import numpy as np

SILENCE_DB = -48.0       # leiser als das gilt als Stille (RMS über 50 ms)
WINDOW_S = 0.05
LEAD_MARGIN_S = 0.1      # so viel vor dem ersten hörbaren Ton beginnen
TAIL_MARGIN_S = 0.3      # Nachklang nach dem letzten hörbaren Ton behalten


def _loud_windows(samples: np.ndarray, rate: int) -> np.ndarray:
    win = max(1, int(rate * WINDOW_S))
    n = samples.size // win
    if n == 0:
        return np.zeros(0, dtype=bool)
    frames = samples[: n * win].reshape(n, win).astype(np.float32)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms) > SILENCE_DB


def music_start(head: np.ndarray, rate: int) -> float:
    """Sekunde, ab der die Musik hörbar beginnt (0.0, wenn sofort)."""
    loud = np.nonzero(_loud_windows(head, rate))[0]
    if loud.size == 0:
        return 0.0  # Anfang ganz still oder zu kurz: nichts überspringen
    return max(0.0, loud[0] * WINDOW_S - LEAD_MARGIN_S)


def music_end(tail: np.ndarray, rate: int, tail_offset_s: float, total_s: float) -> float:
    """Sekunde, an der die Musik hörbar endet.

    ``tail`` sind die letzten Samples des Titels, beginnend bei ``tail_offset_s``.
    """
    loud = np.nonzero(_loud_windows(tail, rate))[0]
    if loud.size == 0:
        return total_s
    end = tail_offset_s + (loud[-1] + 1) * WINDOW_S + TAIL_MARGIN_S
    return min(total_s, end)
