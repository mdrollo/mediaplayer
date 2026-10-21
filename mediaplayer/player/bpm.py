"""Tempo-Erkennung (BPM) aus Audio-Samples (reine Rechenfunktionen).

``estimate_bpm`` berechnet eine Onset-Kurve (spektraler Fluss: wie stark
nimmt die Energie pro Frequenzband von Frame zu Frame zu) und sucht per
Autokorrelation die dominante Periodizität. Das Dekodieren der Dateien
übernimmt ``analysis.AudioAnalyzer``.

Typische Fehlerquelle jeder automatischen Erkennung ist die "Oktave"
(halbes oder doppeltes Tempo). Die Bewertung bevorzugt deshalb Tempi um
``PREFERRED_BPM``; in der Oberfläche lässt sich das Ergebnis mit ½ / ×2 oder
per Mittippen korrigieren.
"""

import numpy as np

ANALYSIS_SKIP_S = 10        # Intro überspringen (wenn der Titel lang genug ist)
ANALYSIS_LENGTH_S = 120     # höchstens so viel Audio auswerten
N_FFT = 1024
HOP = 128                   # ≈ 86 Onset-Werte pro Sekunde
MIN_BPM = 60.0
MAX_BPM = 200.0
PREFERRED_BPM = 120.0       # Mitte der Oktav-Gewichtung
OCTAVE_WIDTH = 1.0          # Breite der Gewichtung in Oktaven


def onset_envelope(samples: np.ndarray, rate: int) -> tuple[np.ndarray, float]:
    """Spektraler Fluss als Onset-Kurve; gibt (Kurve, Frames pro Sekunde) zurück."""
    x = np.asarray(samples, dtype=np.float32)
    if x.size < N_FFT * 4:
        return np.zeros(0, dtype=np.float32), rate / HOP
    frames = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::HOP]
    window = np.hanning(N_FFT).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float32)
    spectrum = np.log1p(100.0 * spectrum)
    flux = np.maximum(0.0, np.diff(spectrum, axis=0)).sum(axis=1)
    # Langsame Lautstärkeänderungen entfernen (gleitender Mittelwert über ~0,5 s).
    fps = rate / HOP
    width = max(1, int(fps * 0.5))
    local_mean = np.convolve(flux, np.ones(width) / width, mode="same")
    envelope = np.maximum(0.0, flux - local_mean)
    std = envelope.std()
    return (envelope / std if std > 0 else envelope), fps


def estimate_bpm(samples: np.ndarray, rate: int) -> float | None:
    """Schätzt das Tempo in BPM oder gibt None zurück, wenn kein Takt erkennbar ist."""
    envelope, fps = onset_envelope(samples, rate)
    if envelope.size < fps * 8:  # weniger als ~8 s Material
        return None

    # Autokorrelation per FFT.
    n = envelope.size
    size = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(envelope - envelope.mean(), size)
    ac = np.fft.irfft(spec * np.conj(spec), size)[:n]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]

    min_lag = int(np.floor(fps * 60.0 / MAX_BPM))
    max_lag = int(np.ceil(fps * 60.0 / MIN_BPM))
    if max_lag * 2 >= n:
        return None
    lags = np.arange(min_lag, max_lag + 1)

    # Harmonische mitbewerten: ein echter Takt wiederholt sich auch nach 2 und 4 Schlägen.
    score = ac[lags] + 0.5 * ac[2 * lags] + 0.25 * ac[np.minimum(4 * lags, n - 1)]
    bpm_of_lag = 60.0 * fps / lags
    weight = np.exp(-0.5 * (np.log2(bpm_of_lag / PREFERRED_BPM) / OCTAVE_WIDTH) ** 2)
    weighted = score * weight

    best = int(np.argmax(weighted))
    if score[best] < 0.05:
        return None

    # Parabolische Interpolation um das Maximum für feinere Auflösung.
    lag = float(lags[best])
    if 0 < best < len(lags) - 1:
        a, b, c = score[best - 1], score[best], score[best + 1]
        denom = a - 2 * b + c
        if denom != 0:
            lag += 0.5 * (a - c) / denom
    return round(60.0 * fps / lag, 1)


def analysis_window(samples: np.ndarray, rate: int) -> np.ndarray:
    """Ausschnitt für die Analyse: Intro überspringen, Länge begrenzen."""
    skip = ANALYSIS_SKIP_S * rate
    if samples.size < skip + 30 * rate:
        skip = 0
    return samples[skip: skip + ANALYSIS_LENGTH_S * rate]

