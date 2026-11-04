"""Tonhöhenerkennung für das chromatische Stimmgerät (reines numpy, ohne Qt).

Verfahren: McLeod Pitch Method (normierte quadratische Differenzfunktion,
"NSDF"). Sie ist robust gegen Obertöne – das größte Problem einfacher
Autokorrelation, die bei Gitarre oder Klavier gern eine Oktave daneben liegt –
und genau genug für ein Stimmgerät (Abweichung deutlich unter 1 Cent bei
sauberen Tönen).

1. Autokorrelation per FFT, normiert mit der Signalenergie → Werte −1 … 1.
2. In jedem positiven Abschnitt der Kurve den höchsten Punkt suchen.
3. Den *ersten* dieser Gipfel nehmen, der fast so hoch ist wie der höchste
   (verhindert Fehler um eine Oktave nach unten).
4. Parabel durch die Gipfel legen → Höhe und Periodendauer mit Bruchteilen
   von Samples.
"""

import math

import numpy as np

# Deutsche Tonnamen: H statt B; der Halbton zwischen A und H heißt B.
NOTE_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "B", "H"]

A4_DEFAULT = 440.0
A4_MIN = 415.0
A4_MAX = 466.0

FREQ_MIN = 27.0      # tiefstes A des Klaviers (27,5 Hz)
FREQ_MAX = 4200.0    # höchstes C des Klaviers (4186 Hz)

MIN_LEVEL = 0.003    # leiser (RMS) gilt als Stille, kein Ton
MIN_CLARITY = 0.80   # darunter ist das Signal zu geräuschhaft für eine sichere Aussage
PEAK_RATIO = 0.90    # erster Gipfel, der mindestens 90 % des höchsten erreicht


def detect_pitch(
    samples: np.ndarray,
    rate: int,
    fmin: float = FREQ_MIN,
    fmax: float = FREQ_MAX,
) -> tuple[float, float] | None:
    """Grundfrequenz eines Signalausschnitts ermitteln.

    Gibt ``(frequenz_hz, klarheit)`` zurück oder ``None``, wenn kein Ton
    erkennbar ist (Stille, Rauschen). ``klarheit`` liegt zwischen 0 und 1.
    """
    x = np.asarray(samples, dtype=np.float64)
    n = len(x)
    if n < 64 or rate <= 0:
        return None
    x = x - x.mean()
    if math.sqrt(float(np.mean(x * x))) < MIN_LEVEL:
        return None

    tau_min = max(2, int(rate / fmax))
    tau_max = min(n // 2, int(math.ceil(rate / fmin)) + 1)
    if tau_max <= tau_min + 2:
        return None

    # Autokorrelation r(τ) per FFT (mit Nullen aufgefüllt → keine Umlaufeffekte).
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(x, size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum), size)[:tau_max + 1]
    # m(τ) = Σ x[j]² + x[j+τ]² über die überlappenden Teile.
    energy = np.concatenate(([0.0], np.cumsum(x * x)))
    taus = np.arange(tau_max + 1)
    m = energy[n - taus] + (energy[n] - energy[taus])
    nsdf = np.where(m > 0, 2.0 * acf / np.where(m > 0, m, 1.0), 0.0)

    peaks = _key_maxima(nsdf, tau_min, tau_max)
    if not peaks:
        return None
    # Gipfel per Parabel verfeinern: Bei hohen Tönen (wenige Samples pro
    # Periode) liegt der wahre Gipfel zwischen zwei Samples und wäre sonst zu
    # niedrig bewertet → Oktavfehler nach unten.
    refined = [_parabola(nsdf, p) for p in peaks]
    highest = max(value for _shift, value in refined)
    if highest < MIN_CLARITY:
        return None
    index = next(i for i, (_s, v) in enumerate(refined) if v >= PEAK_RATIO * highest)
    tau = peaks[index]
    shift, value = refined[index]
    period = tau + shift
    if period <= 0:
        return None
    period = _refine_period(nsdf, period, tau_max)
    freq = rate / period
    if not fmin <= freq <= fmax:
        return None
    return freq, min(1.0, value)


def _parabola(curve: np.ndarray, i: int) -> tuple[float, float]:
    """Scheitel der Parabel durch drei Punkte um ``i``: (Verschiebung, Höhe)."""
    if not 0 < i < len(curve) - 1:
        return 0.0, float(curve[i])
    left, mid, right = curve[i - 1], curve[i], curve[i + 1]
    denom = left - 2 * mid + right
    if denom >= 0:
        return 0.0, float(mid)
    shift = 0.5 * (left - right) / denom
    return float(shift), float(mid - 0.25 * (left - right) * shift)


REFINE_SAMPLES = 200  # kurze Perioden über ein Vielfaches dieser Länge nachmessen


def _refine_period(nsdf: np.ndarray, period: float, tau_max: int) -> float:
    """Kurze Perioden genauer bestimmen.

    Bei hohen Tönen umfasst eine Periode nur wenige Samples; die Parabel um
    den Gipfel ist dann einige Cent ungenau. Der Gipfel beim k-fachen der
    Periode hat denselben absoluten Fehler, geteilt durch k wird er k-mal kleiner.
    """
    k = int(REFINE_SAMPLES // period)
    if k < 2:
        return period
    guess = int(round(k * period))
    if guess + 3 >= min(len(nsdf), tau_max + 1):
        return period
    window = nsdf[guess - 2: guess + 3]
    peak = guess - 2 + int(np.argmax(window))
    shift, _value = _parabola(nsdf, peak)
    refined = (peak + shift) / k
    # Nur übernehmen, wenn es wirklich derselbe Ton ist (Sicherheitsnetz).
    return refined if abs(refined - period) < 0.5 else period


def _key_maxima(nsdf: np.ndarray, tau_min: int, tau_max: int) -> list[int]:
    """Höchster Punkt jedes positiven Abschnitts nach dem ersten Nulldurchgang."""
    # Erster Abschnitt um τ = 0 ist immer maximal (Signal mit sich selbst) – überspringen.
    negative = np.nonzero(nsdf[: tau_max + 1] < 0)[0]
    if not len(negative):
        return []
    start = int(negative[0])
    peaks: list[int] = []
    best = -1
    for tau in range(start, tau_max):
        value = nsdf[tau]
        if value > 0:
            if best < 0 or value > nsdf[best]:
                best = tau
        elif best >= 0:
            if best >= tau_min:
                peaks.append(best)
            best = -1
    if best >= tau_min and best < tau_max - 1:  # Abschnitt am Ende nur, wenn Gipfel sicher drin
        peaks.append(best)
    return peaks


def midi_from_frequency(freq: float, a4: float = A4_DEFAULT) -> float:
    """Tonhöhe als (gebrochene) MIDI-Nummer; 69 = A4."""
    return 69.0 + 12.0 * math.log2(freq / a4)


def frequency_from_midi(midi: float, a4: float = A4_DEFAULT) -> float:
    return a4 * 2.0 ** ((midi - 69.0) / 12.0)


def note_for_frequency(freq: float, a4: float = A4_DEFAULT) -> tuple[str, int, float, float]:
    """Nächstgelegener Ton: ``(name, oktave, abweichung_cent, sollfrequenz)``.

    Oktaven in wissenschaftlicher Schreibweise (A4 = Kammerton, C4 = eingestrichenes c).
    Die Abweichung liegt zwischen −50 und +50 Cent; positiv = zu hoch.
    """
    midi = midi_from_frequency(freq, a4)
    nearest = int(round(midi))
    cents = (midi - nearest) * 100.0
    return NOTE_NAMES[nearest % 12], nearest // 12 - 1, cents, frequency_from_midi(nearest, a4)
