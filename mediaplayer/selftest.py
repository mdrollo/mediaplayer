"""Selbsttest für gepackte Versionen (PyInstaller): ``Mediaplayer --selftest ergebnis.txt``.

Prüft ohne Fenster und ohne Tonausgabe, ob alle Bestandteile im Paket
enthalten sind und funktionieren: numpy, Audio-Decoder (FFmpeg),
BPM-/Stille-Analyse und das Laden einer Datei in den Player. Benötigt kein
Audiogerät, läuft also auch auf Build-Servern.

Das Ergebnis wird in die angegebene Datei geschrieben (eine gepackte
Fenster-Anwendung hat keine Konsole); Rückgabewert 0 = alles in Ordnung.
"""

import math
import struct
import sys
import tempfile
import time
import traceback
import wave
from pathlib import Path


def _wait(condition, timeout_s: float) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer

    end = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < end:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return condition()


def _click_track(path: Path, bpm: float = 120.0, seconds: float = 20.0, lead_s: float = 2.0) -> None:
    rate = 22050
    frames = bytearray()
    beat = 60.0 / bpm
    for i in range(int(rate * (seconds + lead_s))):
        t = i / rate - lead_s
        value = 0.0
        if t >= 0:
            phase = t % beat
            if phase < 0.06:
                value = math.exp(-phase / 0.012) * math.sin(2 * math.pi * 90 * phase)
        frames += struct.pack("<h", int(value * 20000))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def run_selftest(out_file: str) -> int:
    lines: list[str] = []
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        lines.append(f"{'OK    ' if passed else 'FEHLER'} {name}{': ' + detail if detail else ''}")

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # kein Fenster, auch ohne Bildschirm
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtWidgets import QApplication

        import numpy

        from . import __version__
        from .player.analysis import AudioAnalyzer

        app = QApplication.instance() or QApplication(sys.argv)
        lines.append(f"Mediaplayer {__version__}, Python {sys.version.split()[0]}, numpy {numpy.__version__}")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            track = Path(tmp) / "selftest.wav"
            _click_track(track)

            results = []
            analyzer = AudioAnalyzer()
            analyzer.finished.connect(lambda *args: results.append(args))
            analyzer.analyze(str(track))
            _wait(lambda: bool(results), 30)
            if results:
                _, bpm, start, end, (peaks, _rms) = results[0]
                check("Audio-Decoder", start >= 0, f"Musik {start:.1f}–{end:.1f} s")
                check("Wellenform", len(peaks) > 100, f"{len(peaks)} Punkte")
                check("BPM-Erkennung", abs(bpm - 120) <= 2, f"{bpm:.1f} BPM (erwartet 120)")
                check("Stille-Erkennung", 1.5 <= start <= 2.1, f"Musikanfang {start:.2f} s (erwartet ~1,9)")
            else:
                check("Audio-Decoder", False, "keine Antwort")
            analyzer.cancel()

            player = QMediaPlayer()
            output = QAudioOutput()
            output.setVolume(0.0)
            player.setAudioOutput(output)
            player.setSource(QUrl.fromLocalFile(str(track)))
            loaded = _wait(lambda: player.duration() > 0, 15)
            check("Wiedergabe (Laden)", loaded, f"Dauer {player.duration() / 1000:.1f} s")
            player.setSource(QUrl())
            del player, output, analyzer

            # Oberfläche mit temporären Einstellungen aufbauen (echte bleiben unberührt).
            from PySide6.QtCore import QSettings

            from .settings import AppSettings
            from .ui.main_window import MainWindow
            from .ui.style import STYLESHEET, PlayerStyle

            app.setStyle(PlayerStyle())
            app.setStyleSheet(STYLESHEET)
            settings = AppSettings(QSettings(str(Path(tmp) / "selftest.ini"), QSettings.Format.IniFormat))
            window = MainWindow(settings)
            window.resize(1280, 800)
            window.show()
            _wait(lambda: False, 0.3)
            check("Oberfläche", window.isVisible(), f"{window.playlist_view.__class__.__name__} bereit")
            window.close()
            del window
        app.processEvents()
    except Exception:
        check("Ausnahme", False, traceback.format_exc())

    lines.append("ERGEBNIS: " + ("alles in Ordnung" if ok else "FEHLER"))
    Path(out_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1
