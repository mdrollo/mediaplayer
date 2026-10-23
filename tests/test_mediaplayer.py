"""Automatische Tests für Playlist, Einstellungen, Wiedergabe- und Tastenlogik.

Ausführen (im Projektordner):  python -m unittest discover -s tests -v
"""

import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QEventLoop, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from mediaplayer.player.keyboard import GestureTiming, KeyboardController, TapHoldGesture  # noqa: E402
from mediaplayer.player.playback import (  # noqa: E402
    PlaybackController,
    normalize_speed,
    perceptual_to_linear,
)
from mediaplayer.playlist import Playlist, load_playlist_file, save_playlist_file  # noqa: E402
from mediaplayer.settings import AppSettings, DEFAULT_BINDINGS, display_key, key_from_event  # noqa: E402

app = QApplication.instance() or QApplication([])

FAST = GestureTiming(hold_ms=120, double_press_ms=100)


def wait(ms: int) -> None:
    """Ereignisschleife für ``ms`` Millisekunden laufen lassen.

    Bewusst nicht ``QTest.qWait``: das blockiert mit PySide 6.12, sobald das
    FFmpeg-Audiobackend aktiv ist.
    """
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_wav(path: Path, seconds: float = 1.0) -> Path:
    rate = 22050
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        )
        w.writeframes(frames)
    return path


def drum_track(bpm: float, seconds: float, rate: int):
    """Synthetischer Rhythmus: Bassschlag auf jedem Schlag, Hi-Hat dazwischen."""
    import numpy as np

    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.03, int(rate * seconds)).astype(np.float32)
    beat = 60.0 / bpm
    kick_len, hat_len = int(0.08 * rate), int(0.01 * rate)
    kick = np.exp(-np.arange(kick_len) / (0.015 * rate)) * np.sin(2 * np.pi * 80 * np.arange(kick_len) / rate)
    hat = 0.3 * rng.normal(0, 1, hat_len) * np.exp(-np.arange(hat_len) / (0.002 * rate))
    t, i = 0.0, 0
    while t < seconds - 0.2:
        n, h = int(t * rate), int((t + beat / 2) * rate)
        x[n:n + kick_len] += (1.0 if i % 4 == 0 else 0.6) * kick[: x.size - n]
        if h + hat_len < x.size:
            x[h:h + hat_len] += hat
        t, i = t + beat, i + 1
    return x


def make_drum_wav(
    path: Path, bpm: float, seconds: float = 40.0, lead_silence: float = 0.0, trail_silence: float = 0.0
) -> Path:
    import numpy as np

    rate = 22050
    music = drum_track(bpm, seconds, rate)
    signal = np.concatenate([
        np.zeros(int(lead_silence * rate), np.float32), music, np.zeros(int(trail_silence * rate), np.float32)
    ])
    pcm = (np.clip(signal, -1, 1) * 20000).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def key_event(etype, key, mods=Qt.KeyboardModifier.NoModifier, text="", auto=False):
    return QKeyEvent(etype, key, mods, text, auto)


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.files = [make_wav(self.dir / f"t{i}.wav", 0.2) for i in range(3)]
        (self.dir / "notes.txt").write_text("x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_filters_and_dedupes(self):
        pl = Playlist()
        added = pl.add([*map(str, self.files), str(self.files[0]), str(self.dir / "notes.txt")])
        self.assertEqual(added, 3)
        self.assertEqual(pl.current_index, 0)

    def test_remove_adjusts_current(self):
        pl = Playlist()
        pl.add(map(str, self.files))
        pl.current_index = 2
        self.assertFalse(pl.remove(0))
        self.assertEqual(pl.current_index, 1)
        self.assertTrue(pl.remove(1))
        self.assertEqual(pl.current_index, 0)

    def test_navigation_bounds(self):
        pl = Playlist()
        pl.add(map(str, self.files))
        self.assertIsNone(pl.previous_index())
        pl.current_index = 2
        self.assertIsNone(pl.next_index())
        self.assertEqual(pl.previous_index(), 1)

    def test_shuffle_keeps_current_and_original_order(self):
        import random

        more = [make_wav(self.dir / f"x{i}.wav", 0.1) for i in range(7)]
        pl = Playlist()
        pl.add(map(str, self.files + more))
        original = list(pl.items)
        pl.current_index = 4
        current = pl.current_path
        pl.shuffle(random.Random(1))
        self.assertEqual(pl.current_index, 0)
        self.assertEqual(pl.current_path, current)
        self.assertEqual(sorted(pl.items), sorted(original))
        self.assertNotEqual(pl.items, original)
        # Ungemischter Zustand bleibt für die Sitzungsspeicherung erhalten.
        self.assertEqual(pl.unshuffled_state(), (original, 4))
        pl.remove(pl.items.index(original[0]))
        items, index = pl.unshuffled_state()
        self.assertEqual(items, original[1:])
        self.assertEqual(items[index], current)
        pl.replace(original)
        self.assertFalse(pl.is_shuffled)

    def test_save_load_roundtrip(self):
        items = [str(f.resolve()) for f in self.files]
        for name in ("list.m3u8", "list.json", "noext"):
            saved = save_playlist_file(self.dir / name, items + [str(self.dir / "gone.mp3")])
            found, missing = load_playlist_file(saved)
            self.assertEqual(found, items, name)
            self.assertEqual(len(missing), 1, name)
        self.assertTrue((self.dir / "noext.m3u8").exists())

    def test_legacy_json_list(self):
        p = self.dir / "old.json"
        p.write_text('["%s"]' % str(self.files[0]).replace("\\", "\\\\"), encoding="utf-8")
        found, _ = load_playlist_file(p)
        self.assertEqual(len(found), 1)


class SettingsTests(unittest.TestCase):
    def test_bindings_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = str(Path(tmp) / "s.ini")
            s = AppSettings(QSettings(ini, QSettings.Format.IniFormat))
            self.assertEqual(s.key_bindings(), DEFAULT_BINDINGS)
            changed = dict(DEFAULT_BINDINGS, play_pause=["P", "Space"], speed_up=["", "="])
            s.set_key_bindings(changed)
            s.set_session_playlist(["a.mp3"], 0)
            s.set_volume(42)
            s.set_speed(1.3)
            s.sync()
            s2 = AppSettings(QSettings(ini, QSettings.Format.IniFormat))
            self.assertEqual(s2.key_bindings(), changed)
            self.assertEqual(s2.session_playlist(), (["a.mp3"], 0))
            self.assertEqual(s2.volume(), 42)
            self.assertAlmostEqual(s2.speed(), 1.3)

    def test_old_settings_file_without_second_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "old.ini"
            ini.write_text("[keys]\nplay_pause=P\n", encoding="utf-8")
            s = AppSettings(QSettings(str(ini), QSettings.Format.IniFormat))
            self.assertEqual(s.key_bindings()["play_pause"], ["P", ""])
            self.assertEqual(s.key_bindings()["back"], DEFAULT_BINDINGS["back"])


class KeyNormalizationTests(unittest.TestCase):
    def k(self, key, mods=Qt.KeyboardModifier.NoModifier, text=""):
        return key_from_event(key_event(QEvent.Type.KeyPress, key, mods, text))

    def test_defaults_match_events(self):
        self.assertEqual(self.k(Qt.Key.Key_Left), DEFAULT_BINDINGS["back"][0])
        self.assertEqual(self.k(Qt.Key.Key_Right), DEFAULT_BINDINGS["forward"][0])
        self.assertEqual(self.k(Qt.Key.Key_Space, text=" "), DEFAULT_BINDINGS["play_pause"][0])
        self.assertEqual(self.k(Qt.Key.Key_Up), DEFAULT_BINDINGS["volume_up"][0])
        self.assertEqual(self.k(Qt.Key.Key_Down), DEFAULT_BINDINGS["volume_down"][0])
        self.assertEqual(self.k(Qt.Key.Key_Plus, text="+"), DEFAULT_BINDINGS["speed_up"][0])
        self.assertEqual(self.k(Qt.Key.Key_Minus, text="-"), DEFAULT_BINDINGS["speed_down"][0])
        self.assertEqual(self.k(Qt.Key.Key_0, text="0"), DEFAULT_BINDINGS["speed_reset"][0])
        self.assertEqual(self.k(Qt.Key.Key_M, text="m"), DEFAULT_BINDINGS["marker_set"][0])
        self.assertEqual(self.k(Qt.Key.Key_Comma, text=","), DEFAULT_BINDINGS["marker_previous"][0])
        self.assertEqual(self.k(Qt.Key.Key_Period, text="."), DEFAULT_BINDINGS["marker_next"][0])
        self.assertEqual(
            self.k(Qt.Key.Key_M, Qt.KeyboardModifier.ShiftModifier, "M"), DEFAULT_BINDINGS["marker_delete"][0]
        )

    def test_shift_and_keypad_ignored_for_symbols(self):
        self.assertEqual(self.k(Qt.Key.Key_Plus, Qt.KeyboardModifier.ShiftModifier, "+"), "+")
        self.assertEqual(self.k(Qt.Key.Key_Plus, Qt.KeyboardModifier.KeypadModifier, "+"), "+")
        self.assertEqual(self.k(Qt.Key.Key_0, Qt.KeyboardModifier.KeypadModifier, "0"), "0")
        self.assertEqual(self.k(Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier, "A"), "Shift+A")
        self.assertEqual(self.k(Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier), "")

    def test_display(self):
        self.assertEqual(display_key("Left"), "Pfeil links")
        self.assertEqual(display_key("+"), "+")
        self.assertEqual(display_key("Ctrl++"), "Strg + +")
        self.assertEqual(display_key(""), "– nicht belegt –")


class SpeedVolumeTests(unittest.TestCase):
    def test_speed(self):
        self.assertEqual(normalize_speed(0.1), 0.5)
        self.assertEqual(normalize_speed(5), 2.0)
        self.assertEqual(normalize_speed(1.0 + 0.1 + 0.1 + 0.1), 1.3)
        self.assertEqual(normalize_speed(1.04), 1.04)
        self.assertEqual(normalize_speed(1.0 + 7 * 0.01), 1.07)
        self.assertEqual(normalize_speed(121 / 123.6), 0.979)  # fein genug für Ziel-BPM

    def test_volume_curve(self):
        self.assertEqual(perceptual_to_linear(0), 0.0)
        self.assertAlmostEqual(perceptual_to_linear(100), 1.0)
        values = [perceptual_to_linear(p) for p in range(101)]
        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(perceptual_to_linear(50), 10 ** (-25 / 20))


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.g = TapHoldGesture(FAST)
        self.events = []
        self.g.single.connect(lambda: self.events.append("single"))
        self.g.double.connect(lambda: self.events.append("double"))
        self.g.holdStarted.connect(lambda: self.events.append("hold_start"))
        self.g.holdEnded.connect(lambda: self.events.append("hold_end"))

    def test_single(self):
        self.g.press(); wait(30); self.g.release()
        self.assertEqual(self.events, [])  # noch im Doppeldruck-Fenster
        wait(200)
        self.assertEqual(self.events, ["single"])

    def test_double(self):
        self.g.press(); self.g.release(); wait(40)
        self.g.press(); self.g.release()
        wait(250)
        self.assertEqual(self.events, ["double"])

    def test_hold(self):
        self.g.press(); wait(250)
        self.assertEqual(self.events, ["hold_start"])
        self.g.release(); wait(200)
        self.assertEqual(self.events, ["hold_start", "hold_end"])

    def test_reset_while_holding(self):
        self.g.press(); wait(250)
        self.g.reset()
        self.assertEqual(self.events, ["hold_start", "hold_end"])


class KeyboardControllerTests(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        bindings = dict(DEFAULT_BINDINGS, play_pause=["P", ""], back=["Left", "J"], volume_up=["Up", "K"])
        self.kc = KeyboardController(self.window, bindings, FAST)
        self.kc.install()
        self.events = []
        self.kc.triggered.connect(self.events.append)

    def tearDown(self):
        self.kc.uninstall()

    def send(self, etype, key, auto=False, text=""):
        app.sendEvent(self.window, key_event(etype, key, text=text, auto=auto))

    def test_remapped_simple_action(self):
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_P, text="p")
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Space, text=" ")  # nicht mehr belegt
        self.assertEqual(self.events, ["play_pause"])

    def test_autorepeat(self):
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Up)
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Up, auto=True)
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_P, text="p")
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_P, auto=True, text="p")
        self.assertEqual(self.events, ["volume_up", "volume_up", "play_pause"])

    def test_hold_with_autorepeat(self):
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Right)
        for _ in range(5):
            wait(40)
            self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Right, auto=True)
            self.send(QEvent.Type.KeyPress, Qt.Key.Key_Right, auto=True)
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Right)
        wait(200)
        self.assertEqual(self.events, ["forward_hold_start", "forward_hold_end"])

    def test_double_and_single(self):
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Left)
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Left)
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Left)
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Left)
        wait(200)
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Right)
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Right)
        wait(200)
        self.assertEqual(self.events, ["back_double", "forward_single"])

    def test_second_key(self):
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_K, text="k")
        # Zweittaste für "Zurück" hat dieselbe Gestenlogik: J + Pfeil links = Doppeldruck.
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_J, text="j")
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_J, text="j")
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Left)
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Left)
        wait(200)
        self.assertEqual(self.events, ["volume_up", "back_double"])

    def test_both_keys_held_count_as_one(self):
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_Left)
        self.send(QEvent.Type.KeyPress, Qt.Key.Key_J, text="j")
        wait(200)
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_J, text="j")
        wait(50)
        self.assertEqual(self.events, ["back_hold_start"])  # Pfeil links noch gehalten
        self.send(QEvent.Type.KeyRelease, Qt.Key.Key_Left)
        wait(200)
        self.assertEqual(self.events, ["back_hold_start", "back_hold_end"])

    def test_other_window_ignored(self):
        other = QWidget()
        app.sendEvent(other, key_event(QEvent.Type.KeyPress, Qt.Key.Key_P, text="p"))
        self.assertEqual(self.events, [])


class KeyConfigDialogTests(unittest.TestCase):
    def test_capture_and_conflict(self):
        from mediaplayer.ui.key_config_dialog import KeyConfigDialog

        dlg = KeyConfigDialog(DEFAULT_BINDINGS)
        second = dlg.capture_button("play_pause", 1)
        second.click()
        app.sendEvent(second, key_event(QEvent.Type.KeyPress, Qt.Key.Key_Left))
        result = dlg.bindings()
        self.assertEqual(result["play_pause"], ["Space", "Left"])
        self.assertEqual(result["back"], ["", ""])  # Konflikt aufgelöst
        self.assertEqual(second.text(), "Pfeil links")

        second.click()
        app.sendEvent(second, key_event(QEvent.Type.KeyPress, Qt.Key.Key_F11))
        self.assertEqual(dlg.bindings()["play_pause"], ["Space", "Left"])  # reserviert
        second.stop_capture()

        # Gleiche Taste im anderen Platz derselben Funktion wird verschoben.
        first = dlg.capture_button("play_pause", 0)
        first.click()
        app.sendEvent(first, key_event(QEvent.Type.KeyPress, Qt.Key.Key_Left))
        self.assertEqual(dlg.bindings()["play_pause"], ["Left", ""])

        dlg._clear("play_pause", 0)
        self.assertEqual(dlg.bindings()["play_pause"], ["", ""])
        self.assertEqual(DEFAULT_BINDINGS["play_pause"], ["Space", ""])  # Original unverändert
        dlg.deleteLater()


class RecentPlaylistsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.settings = AppSettings(QSettings(str(self.dir / "s.ini"), QSettings.Format.IniFormat))
        self.lists = []
        for i in range(3):
            p = self.dir / f"liste{i}.m3u8"
            p.write_text("#EXTM3U\n", encoding="utf-8")
            self.lists.append(str(p))

    def tearDown(self):
        self.tmp.cleanup()

    def test_settings_order_and_limit(self):
        for p in self.lists:
            self.settings.add_recent_playlist(p)
        self.settings.add_recent_playlist(self.lists[0])
        recent = self.settings.recent_playlists()
        self.assertEqual([Path(p).name for p in recent], ["liste0.m3u8", "liste2.m3u8", "liste1.m3u8"])
        for i in range(15):
            self.settings.add_recent_playlist(str(self.dir / f"x{i}.m3u8"))
        self.assertEqual(len(self.settings.recent_playlists()), 10)

    def test_dialog_digits_toggle_remove(self):
        from mediaplayer.ui.recent_playlists_dialog import RecentPlaylistsDialog

        missing = str(self.dir / "weg.m3u8")
        paths = [self.lists[0], missing, self.lists[1]]

        dlg = RecentPlaylistsDialog(paths, toggle_keys=["L", ""])
        app.sendEvent(dlg.list, key_event(QEvent.Type.KeyPress, Qt.Key.Key_3, text="3"))
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dlg.chosen_path(), self.lists[1])

        dlg = RecentPlaylistsDialog(paths, toggle_keys=["L", ""])
        app.sendEvent(dlg.list, key_event(QEvent.Type.KeyPress, Qt.Key.Key_2, text="2"))
        self.assertEqual(dlg.chosen_path(), "")  # fehlende Datei nicht ladbar
        dlg.list.setCurrentRow(1)
        app.sendEvent(dlg.list, key_event(QEvent.Type.KeyPress, Qt.Key.Key_Delete))
        self.assertEqual(dlg.remaining_paths(), [self.lists[0], self.lists[1]])
        app.sendEvent(dlg.list, key_event(QEvent.Type.KeyPress, Qt.Key.Key_L, text="l"))
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)


class FileBrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "Album 10").mkdir()
        (self.dir / "Album 2").mkdir()
        for name in ("Track 10.mp3", "Track 2.mp3", "notiz.txt"):
            (self.dir / name).write_bytes(b"x")
        (self.dir / "Album 2" / "Song.mp3").write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def titles(self, dlg):
        return [dlg.list.item(i).text() for i in range(dlg.list.count())]

    def test_listing_and_multi_select_across_folders(self):
        from mediaplayer.ui.file_browser import FileBrowserDialog, Mode

        dlg = FileBrowserDialog(Mode.OPEN_FILES, "Test", str(self.dir), {".mp3"}, "Hinzufügen")
        # Ordner zuerst, natürlich sortiert; nur passende Dateien.
        self.assertEqual(self.titles(dlg), ["Album 2", "Album 10", "Track 2.mp3", "Track 10.mp3"])
        dlg.list.item(2).setSelected(True)
        dlg.navigate(str(self.dir / "Album 2"))
        dlg.list.item(0).setSelected(True)
        self.assertEqual(dlg.accept_button.text(), "Hinzufügen (2)")
        dlg.go_up()
        self.assertTrue(dlg.list.item(2).isSelected())  # Auswahl blieb erhalten
        dlg._accept()
        self.assertEqual(
            [Path(p).name for p in dlg.selected_paths()], ["Song.mp3", "Track 2.mp3"]
        )

    def test_whole_folder(self):
        from mediaplayer.ui.file_browser import FileBrowserDialog, Mode

        dlg = FileBrowserDialog(Mode.OPEN_FILES, "Test", str(self.dir), {".mp3"}, "Hinzufügen")
        dlg._accept_folder()
        # Erst die Titel des Ordners selbst, dann die Unterordner.
        self.assertEqual(
            [Path(p).name for p in dlg.selected_paths()], ["Track 2.mp3", "Track 10.mp3", "Song.mp3"]
        )

    def test_save_adds_suffix(self):
        from mediaplayer.ui.file_browser import FileBrowserDialog, Mode

        dlg = FileBrowserDialog(
            Mode.SAVE_FILE, "Test", str(self.dir), {".m3u8", ".json"}, "Speichern",
            default_name="Meine Liste", default_suffix=".m3u8",
        )
        dlg._accept()
        self.assertEqual(dlg.selected_paths(), [str(self.dir / "Meine Liste.m3u8")])
        dlg.name_edit.setText("a/b")
        dlg._result = []
        dlg._accept()
        self.assertEqual(dlg.selected_paths(), [])  # ungültiger Name abgelehnt


class BpmDetectionTests(unittest.TestCase):
    def test_estimate_synthetic(self):
        from mediaplayer.player.bpm import analysis_window, estimate_bpm

        for bpm in (72, 100, 128, 174):
            est = estimate_bpm(analysis_window(drum_track(bpm, 60, 11025), 11025), 11025)
            self.assertIsNotNone(est, bpm)
            self.assertAlmostEqual(est, bpm, delta=1.5)

    def test_noise_has_no_tempo(self):
        import numpy as np

        from mediaplayer.player.bpm import estimate_bpm

        noise = np.random.default_rng(1).normal(0, 0.3, 11025 * 40).astype(np.float32)
        self.assertIsNone(estimate_bpm(noise, 11025))

    def test_analyzer_decodes_file(self):
        from mediaplayer.player.analysis import AudioAnalyzer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            # 3 s Stille + 40 s Rhythmus + 5 s Stille
            path = str(make_drum_wav(Path(tmp) / "beat.wav", 124, 40, lead_silence=3, trail_silence=5))
            analyzer = AudioAnalyzer()
            results = []
            analyzer.finished.connect(lambda *args: results.append(args))
            analyzer.analyze(path)
            for _ in range(100):
                if results:
                    break
                wait(100)
            analyzer.cancel()
            analyzer.deleteLater()
            wait(100)
            self.assertEqual(len(results), 1)
            p, bpm, start, end, (peaks, rms) = results[0]
            self.assertEqual(p, path)
            self.assertAlmostEqual(bpm, 124, delta=1.5)
            self.assertAlmostEqual(start, 2.9, delta=0.15)
            self.assertAlmostEqual(end, 43.1, delta=0.4)
            # Wellenform: 2000 Punkte, still am Anfang (3 von 48 s), laut in der Mitte.
            self.assertEqual(len(peaks), 2000)
            self.assertEqual(len(rms), 2000)
            self.assertLess(max(peaks[:100]), 10)
            self.assertGreater(max(peaks[500:1500]), 200)


class SilenceTests(unittest.TestCase):
    def test_start_and_end(self):
        import numpy as np

        from mediaplayer.player.silence import music_end, music_start

        rate = 11025
        tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(5 * rate) / rate).astype(np.float32)
        x = np.concatenate([np.zeros(2 * rate, np.float32), tone, np.zeros(3 * rate, np.float32)])
        self.assertAlmostEqual(music_start(x, rate), 1.9, delta=0.06)
        self.assertAlmostEqual(music_end(x, rate, 0.0, x.size / rate), 7.3, delta=0.06)
        # Ausschnitt vom Ende mit Versatz
        tail = x[6 * rate:]
        self.assertAlmostEqual(music_end(tail, rate, 6.0, x.size / rate), 7.3, delta=0.06)
        # Keine Stille: nichts abschneiden
        self.assertEqual(music_start(tone, rate), 0.0)
        self.assertEqual(music_end(tone, rate, 0.0, 5.0), 5.0)

    def test_cache_merge_keeps_manual_bpm(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            s = AppSettings(QSettings(str(d / "s.ini"), QSettings.Format.IniFormat))
            f = str(make_wav(d / "a.wav", 0.2))
            s.store_bpm(f, 120.0)  # alter Eintrag ohne Stille-Angaben
            self.assertFalse(s.is_analysis_complete(f))
            s.store_bpm(f, 61.0, manual=True)
            s.store_analysis(f, bpm=122.0, start=1.5, end=100.0)  # automatische Analyse
            self.assertEqual(s.cached_bpm(f), (61.0, True))
            self.assertFalse(s.is_analysis_complete(f))  # Wellenform fehlt noch
            s.store_waveform(f, b"\x01\x02", b"\x00\x01")
            self.assertTrue(s.is_analysis_complete(f))
            self.assertEqual(s.cached_waveform(f), (b"\x01\x02", b"\x00\x01"))
            self.assertEqual(s.cached_analysis(f)["start"], 1.5)
            Path(f).write_bytes(b"geaendert")  # Datei geändert -> alles neu analysieren
            self.assertIsNone(s.cached_waveform(f))
            self.assertIsNone(s.cached_analysis(f))


class WaveformTests(unittest.TestCase):
    def test_accumulator_independent_of_buffer_sizes(self):
        import numpy as np

        from mediaplayer.player.waveform import WaveformAccumulator, build_waveform

        rng = np.random.default_rng(3)
        x = (rng.normal(0, 0.2, 11025 * 30) * np.linspace(0, 1, 11025 * 30)).astype(np.float32)
        whole = WaveformAccumulator(11025)
        whole.add(x)
        chunked = WaveformAccumulator(11025)
        for part in np.array_split(x, 977):  # ungerade Puffergrößen wie vom Decoder
            chunked.add(part)
        a, b = whole.finish(), chunked.finish()
        np.testing.assert_allclose(a[0], b[0])
        peaks, rms = build_waveform(*a, points=500)
        self.assertEqual((len(peaks), len(rms)), (500, 500))
        self.assertEqual(max(peaks), 255)            # auf den lautesten Punkt normiert
        self.assertLess(peaks[0], peaks[-1])          # Lautstärke steigt an
        self.assertTrue(all(r <= p for p, r in zip(peaks, rms)))

    def test_silence_gives_empty_waveform(self):
        import numpy as np

        from mediaplayer.player.waveform import build_waveform

        zeros = np.zeros(100, dtype=np.float32)
        self.assertEqual(build_waveform(zeros, zeros), (b"", b""))

    def test_slider_draws_waveform(self):
        import numpy as np

        from mediaplayer.ui.style import STYLESHEET, PlayerStyle
        from mediaplayer.ui.waveform_slider import WaveformSlider

        style = PlayerStyle()  # Referenz halten: QWidget.setStyle übernimmt das Objekt nicht
        slider = WaveformSlider()
        slider.setStyle(style)
        slider.setStyleSheet(STYLESHEET)
        slider.resize(800, 100)
        slider.setRange(0, 1000)
        slider.setValue(500)
        self.assertFalse(slider.has_waveform())
        slider.grab()  # Balken ohne Wellenform darf nicht abstürzen
        peaks = (np.abs(np.sin(np.linspace(0, 20, 2000))) * 255).astype(np.uint8).tobytes()
        slider.set_waveform((peaks, bytes(len(peaks))))
        self.assertTrue(slider.has_waveform())
        image = slider.grab().toImage()
        # Links vom Abspielstrich blau (gespielt), rechts grau.
        left = image.pixelColor(200, 50)
        right = image.pixelColor(600, 50)
        self.assertGreater(left.blue(), left.red() + 40)
        self.assertLess(abs(right.blue() - right.red()), 30)
        slider.set_waveform(None)
        self.assertFalse(slider.has_waveform())
        slider.deleteLater()


class PlaylistTitleTests(unittest.TestCase):
    """Name der aktuellen Playlist oben mittig im Hauptfenster."""

    def test_title_shown_centered_and_restored(self):
        from mediaplayer.ui.main_window import MainWindow
        from mediaplayer.ui.style import STYLESHEET, PlayerStyle

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            d = Path(tmp)
            song = make_wav(d / "lied.wav", 0.3)
            playlist = save_playlist_file(d / "Sonntag Jazz.m3u8", [str(song)])
            settings = AppSettings(QSettings(str(d / "s.ini"), QSettings.Format.IniFormat))
            style = PlayerStyle()
            app.setStyle(style)
            app.setStyleSheet(STYLESHEET)

            w = MainWindow(settings)
            w.resize(1600, 900)
            w.show()
            wait(100)
            self.assertEqual(w.playlist_title.full_text(), "")
            w.open_playlist_file(str(playlist))
            wait(100)
            self.assertEqual(w.playlist_title.full_text(), "Sonntag Jazz")  # ohne Pfad und Endung
            self.assertEqual(w.playlist_title.text(), "Sonntag Jazz")
            # Exakt mittig im Fenster (±2 px), unabhängig von Zeit und Uhr.
            center = w.playlist_title.mapTo(w, w.playlist_title.rect().center()).x()
            self.assertAlmostEqual(center, w.width() / 2, delta=2)

            # Sehr lange Namen werden gekürzt statt das Layout zu verschieben.
            w.playlist_title.set_full_text("Sehr langer Playlistname " * 10)
            self.assertTrue(w.playlist_title.text().endswith("…"))
            self.assertAlmostEqual(
                w.playlist_title.mapTo(w, w.playlist_title.rect().center()).x(), w.width() / 2, delta=2
            )
            w.close()
            w.deleteLater()
            wait(100)

            # Neustart: Name bleibt erhalten; nach Leeren der Playlist verschwindet er.
            w2 = MainWindow(settings)
            self.assertEqual(w2.playlist_title.full_text(), "Sonntag Jazz")
            w2.playlist_view.setCurrentRow(0)
            w2.remove_selected()
            self.assertEqual(w2.playlist_title.full_text(), "")
            w2.close()
            w2.deleteLater()
            wait(100)


class PlaylistTitleMigrationTests(unittest.TestCase):
    def test_name_found_for_older_session(self):
        """Sitzung ohne gemerkten Namen: passende zuletzt verwendete Playlist wird erkannt."""
        from mediaplayer.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            d = Path(tmp)
            songs = [str(make_wav(d / f"s{i}.wav", 0.2)) for i in range(3)]
            other = save_playlist_file(d / "Andere.m3u8", songs[:2])
            match = save_playlist_file(d / "Passend.m3u8", list(reversed(songs)))  # Reihenfolge egal
            settings = AppSettings(QSettings(str(d / "s.ini"), QSettings.Format.IniFormat))
            settings.set_session_playlist(songs, 0)
            settings.set_recent_playlists([str(other), str(match)])
            self.assertEqual(settings.session_playlist_file(), "")

            w = MainWindow(settings)
            self.assertEqual(w.playlist_title.full_text(), "Passend")
            self.assertEqual(settings.session_playlist_file(), str(match))  # ab jetzt gemerkt
            w.analysis.shutdown()
            w.close()
            w.deleteLater()
            wait(100)

    def test_slider_pending_hint(self):
        from mediaplayer.ui.waveform_slider import WaveformSlider

        slider = WaveformSlider()
        slider.resize(600, 100)
        slider.set_pending(True)
        slider.grab()  # Hinweis zeichnen darf nicht abstürzen
        slider.set_waveform((bytes([100] * 50), bytes([50] * 50)))
        self.assertTrue(slider.has_waveform())
        slider.grab()
        slider.deleteLater()


class TempoTests(unittest.TestCase):
    """BPM-Steuerung mit vorbefülltem Cache (ohne Dekodierung)."""

    def setUp(self):
        from mediaplayer.player.analysis import TrackAnalysisService
        from mediaplayer.player.tempo import TempoController

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.tmp.name)
        self.settings = AppSettings(QSettings(str(d / "s.ini"), QSettings.Format.IniFormat))
        self.files = [str(make_wav(d / f"t{i}.wav", 0.5)) for i in range(3)]
        for f, bpm in zip(self.files, (120.0, 100.0, 0.0)):  # 0.0 = kein Takt erkannt
            self.settings.store_analysis(f, bpm=bpm, start=0.0, end=0.5)
            self.settings.store_waveform(f, b"", b"")  # gilt als vollständig analysiert
        self.c = PlaybackController()
        self.analysis = TrackAnalysisService(self.c, self.settings)
        self.tempo = TempoController(self.c, self.settings, self.analysis)
        self.c.add_files(self.files)
        wait(50)

    def tearDown(self):
        self.analysis.shutdown()
        self.c.replace_playlist([])
        for obj in (self.tempo, self.analysis, self.c):
            obj.deleteLater()
        wait(100)
        self.tmp.cleanup()

    def test_cache_invalidated_when_file_changes(self):
        self.assertEqual(self.settings.cached_bpm(self.files[0]), (120.0, False))
        Path(self.files[0]).write_bytes(b"anders")
        self.assertIsNone(self.settings.cached_bpm(self.files[0]))

    def test_set_and_step_bpm(self):
        self.assertEqual(self.tempo.original_bpm(), 120.0)
        self.tempo.set_bpm(126)
        self.assertEqual(self.c.speed(), 1.05)
        self.tempo.step(1)
        self.assertAlmostEqual(self.tempo.current_bpm(), 127, places=1)
        self.tempo.reset()
        self.assertEqual(self.tempo.current_bpm(), 120.0)

    def test_lock_keeps_bpm_across_tracks(self):
        self.tempo.set_bpm(110)
        self.tempo.set_locked(True)
        self.c.next_track()
        self.assertEqual(self.tempo.original_bpm(), 100.0)
        self.assertAlmostEqual(self.tempo.current_bpm(), 110, places=1)
        self.assertEqual(self.c.speed(), 1.1)
        self.tempo.step(-2)  # Ziel ändert sich mit
        self.c.previous_track()
        self.assertAlmostEqual(self.tempo.current_bpm(), 108, places=1)
        self.assertEqual(self.settings.bpm_lock(), (True, 108.0))

    def test_unknown_tempo_uses_speed_steps(self):
        self.c.select_index(2)
        self.assertEqual(self.tempo.original_bpm(), 0.0)
        self.tempo.step(1)
        self.assertEqual(self.c.speed(), 1.01)

    def test_corrections_are_saved(self):
        from unittest import mock

        self.tempo.double()
        self.assertEqual(self.tempo.original_bpm(), 240.0)
        self.tempo.halve()
        self.assertEqual(self.settings.cached_bpm(self.files[0]), (120.0, True))
        # Mittippen bei 1,1x: 0,5 s Abstand = 120 hörbare BPM → Original 109,1 BPM.
        self.c.set_speed(1.1)
        clock = iter([10.0, 10.5, 11.0, 11.5])
        with mock.patch("mediaplayer.player.tempo.time.monotonic", lambda: next(clock)):
            for _ in range(4):
                self.tempo.tap()
        self.assertAlmostEqual(self.tempo.original_bpm(), 109.1, places=1)
        self.assertAlmostEqual(self.tempo.current_bpm(), 120, delta=0.1)


class SkipSilenceTests(unittest.TestCase):
    """Pausen überspringen mit echter Wiedergabe: 1 s Stille + 1 s Ton + 2 s Stille."""

    def setUp(self):
        import numpy as np

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.tmp.name)
        rate = 22050
        tone = (0.4 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 32767).astype(np.int16)
        pcm = np.concatenate([np.zeros(rate, np.int16), tone, np.zeros(2 * rate, np.int16)])
        self.files = []
        for i in range(2):
            p = d / f"s{i}.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm.tobytes())
            self.files.append(str(p))
        self.c = PlaybackController()
        self.c.add_files(self.files)
        wait(100)

    def tearDown(self):
        self.c.replace_playlist([])
        self.c.deleteLater()
        wait(100)
        self.tmp.cleanup()

    def wait_for_track(self, index, timeout_ms):
        waited = 0
        while self.c.current_index() != index and waited < timeout_ms:
            wait(50)
            waited += 50
        return waited

    def test_skips_lead_and_trail(self):
        self.c.set_music_bounds(self.c.playlist.items[0], 900, 2300)
        self.c.play()
        wait(400)
        if self.c.position() == 0:
            self.skipTest("Kein Audio-Backend verfügbar.")
        self.assertGreaterEqual(self.c.position(), 900)  # Anfangsstille übersprungen
        waited = self.wait_for_track(1, 4000)
        # Ohne Überspringen würde der 4-s-Titel erst nach ~3,6 s weiterer Wartezeit enden.
        self.assertEqual(self.c.current_index(), 1)
        self.assertLess(waited, 2500)
        self.assertTrue(self.c.is_playing())

    def test_disabled_plays_everything(self):
        self.c.set_skip_silence(False)
        self.c.set_music_bounds(self.c.playlist.items[0], 900, 2300)
        self.c.play()
        wait(400)
        if self.c.position() == 0:
            self.skipTest("Kein Audio-Backend verfügbar.")
        self.assertLess(self.c.position(), 900)
        wait(2200)  # liegt hinter dem Musikende, aber vor dem Dateiende
        self.assertEqual(self.c.current_index(), 0)

    def test_bounds_for_other_file_ignored(self):
        self.c.set_music_bounds(self.c.playlist.items[1], 900, 2300)  # nicht der geladene Titel
        self.c.play()
        wait(400)
        if self.c.position() == 0:
            self.skipTest("Kein Audio-Backend verfügbar.")
        self.assertLess(self.c.position(), 900)


class MarkerTests(unittest.TestCase):
    """Markierungen setzen, anspringen, löschen und dauerhaft speichern."""

    def setUp(self):
        from mediaplayer.player.markers import MarkerController

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.tmp.name)
        self.ini = str(d / "s.ini")
        self.settings = AppSettings(QSettings(self.ini, QSettings.Format.IniFormat))
        self.files = [str(make_wav(d / f"song{i}.wav", 10.0)) for i in range(2)]
        self.c = PlaybackController()
        self.markers = MarkerController(self.c, self.settings)
        self.messages = []
        self.markers.message.connect(self.messages.append)
        self.c.add_files(self.files)
        wait(300)

    def tearDown(self):
        self.c.replace_playlist([])
        for obj in (self.markers, self.c):
            obj.deleteLater()
        wait(100)
        self.tmp.cleanup()

    def seek(self, ms):
        self.c.seek(ms)
        deadline = 2000
        while abs(self.c.position() - ms) > 50 and deadline > 0:
            wait(20)
            deadline -= 20
        if abs(self.c.position() - ms) > 50:
            self.skipTest("Kein Audio-Backend verfügbar (Position nicht übernommen).")

    def seek_done(self, ms):
        wait(200)
        self.assertAlmostEqual(self.c.position(), ms, delta=50)

    def test_neighbours(self):
        from mediaplayer.player.markers import nearest_marker, next_marker, previous_marker

        marks = [2000, 5000, 8000]
        self.assertEqual(previous_marker(marks, 6000), 2000)  # 5000 liegt im Toleranzfenster
        self.assertEqual(previous_marker(marks, 7000), 5000)
        self.assertIsNone(previous_marker(marks, 3000))
        self.assertEqual(next_marker(marks, 5000), 8000)       # die Markierung selbst zählt nicht
        self.assertEqual(next_marker(marks, 0), 2000)
        self.assertIsNone(next_marker(marks, 8000))
        self.assertEqual(nearest_marker(marks, 6000), 5000)
        self.assertIsNone(nearest_marker([], 6000))

    def test_set_jump_delete(self):
        for ms in (6000, 2000):
            self.seek(ms)
            self.markers.add_at_current()
        self.seek(2200)
        self.markers.add_at_current()  # zu nah an 2000: keine zweite Markierung
        self.assertEqual(self.markers.markers(), [2000, 6000])

        self.markers.jump_next()
        self.seek_done(6000)
        self.markers.jump_previous()
        self.seek_done(2000)

        self.markers.delete_nearest()
        self.assertEqual(self.markers.markers(), [6000])
        self.markers.clear()
        self.assertEqual(self.markers.markers(), [])
        self.assertEqual(self.settings.markers(self.files[0]), [])

    def test_markers_follow_track_and_persist(self):
        self.seek(4000)
        self.markers.add_at_current()
        self.c.next_track()
        self.assertEqual(self.markers.markers(), [])
        self.c.previous_track()
        self.assertEqual(len(self.markers.markers()), 1)
        reloaded = AppSettings(QSettings(self.ini, QSettings.Format.IniFormat))
        self.assertEqual(reloaded.markers(self.files[0]), self.markers.markers())

    def test_without_markers(self):
        self.markers.jump_next()
        self.markers.delete_nearest()
        self.assertEqual(self.messages, ["Dieser Titel hat keine Markierungen."] * 2)


class PlaybackTests(unittest.TestCase):
    """Wiedergaberegeln mit echtem QMediaPlayer (kurze WAV-Dateien)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.tmp.name)
        self.files = [str(make_wav(d / f"song{i}.wav", 1.0)) for i in range(3)]
        self.c = PlaybackController()
        self.c.add_files(self.files)
        wait(100)

    def tearDown(self):
        self.c.replace_playlist([])  # gibt die Datei frei
        self.c.deleteLater()
        wait(100)
        self.tmp.cleanup()

    def test_next_while_stopped_does_not_play(self):
        self.assertFalse(self.c.is_playing())
        self.c.next_track()
        self.assertEqual(self.c.current_index(), 1)
        self.assertFalse(self.c.is_playing())
        self.c.previous_track()
        self.assertEqual(self.c.current_index(), 0)
        self.assertFalse(self.c.is_playing())

    def test_next_while_paused_does_not_play(self):
        self.c.play(); wait(100)
        self.c.pause()
        self.c.next_track()
        self.assertEqual(self.c.current_index(), 1)
        self.assertFalse(self.c.is_playing())

    def test_next_while_playing_keeps_playing(self):
        self.c.play(); wait(50)
        self.c.next_track()
        self.c.next_track()  # schneller zweiter Wechsel während des Ladens
        self.assertEqual(self.c.current_index(), 2)
        self.assertTrue(self.c.is_playing())
        self.c.previous_track()
        self.assertTrue(self.c.is_playing())

    def test_toggle_prefers_selected_row(self):
        self.c.toggle_play_pause(preferred_index=2)
        self.assertEqual(self.c.current_index(), 2)
        self.assertTrue(self.c.is_playing())
        self.c.toggle_play_pause(preferred_index=2)
        self.assertFalse(self.c.is_playing())

    def test_auto_advance_at_end(self):
        self.c.play()
        deadline = 4000
        while self.c.current_index() == 0 and deadline > 0:
            wait(50)
            deadline -= 50
        if self.c.current_index() == 0:
            self.skipTest("Kein Audio-Backend verfügbar (Titel endete nicht).")
        self.assertEqual(self.c.current_index(), 1)
        self.assertTrue(self.c.is_playing())

    def test_speed_and_volume(self):
        self.c.change_speed(3)
        self.assertEqual(self.c.speed(), 1.03)
        self.c.set_speed(1.27)
        self.c.change_speed(-1)
        self.assertEqual(self.c.speed(), 1.26)
        # Zwischenwerte (z. B. nach BPM-Einstellung) rasten auf das 0,01-Raster ein.
        self.c.set_speed(0.979)
        self.c.change_speed(1)
        self.assertEqual(self.c.speed(), 0.98)
        self.c.set_speed(0.979)
        self.c.change_speed(-1)
        self.assertEqual(self.c.speed(), 0.97)
        self.c.change_speed(-500)
        self.assertEqual(self.c.speed(), 0.5)
        self.c.reset_speed()
        self.assertEqual(self.c.speed(), 1.0)
        self.c.set_volume(130)
        self.assertEqual(self.c.volume(), 100)

    def test_shuffle_keeps_playing(self):
        self.c.next_track()  # Titel 2 auswählen
        self.c.play(); wait(50)
        current = self.c.playlist.current_path
        self.c.shuffle_playlist()
        self.assertTrue(self.c.is_playing())
        self.assertEqual(self.c.current_index(), 0)
        self.assertEqual(self.c.playlist.current_path, current)
        self.c.pause()
        self.c.toggle_play_pause(preferred_index=0)  # kein Neuladen, nur fortsetzen
        self.assertTrue(self.c.is_playing())

    def test_remove_current_stops(self):
        self.c.play(); wait(50)
        self.c.remove_index(0)
        self.assertFalse(self.c.is_playing())
        self.assertEqual(self.c.current_index(), 0)
        self.assertEqual(len(self.c.playlist), 2)


def tearDownModule():
    """Alle Qt-Objekte abbauen, solange die QApplication noch existiert.

    Sonst zerstört Python beim Prozessende Fenster und Multimedia-Objekte in
    zufälliger Reihenfolge nach der QApplication, was sporadisch abstürzt.
    """
    import gc

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    wait(200)
    gc.collect()
    wait(100)


if __name__ == "__main__":
    unittest.main()
