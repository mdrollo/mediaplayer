"""Wiedergabesteuerung auf Basis von QMediaPlayer und QAudioOutput.

Zentrale Verhaltensregeln:

* Vor/Zurück während der Wiedergabe: der neue Titel spielt sofort weiter.
* Vor/Zurück im gestoppten oder pausierten Zustand: der neue Titel wird nur
  ausgewählt und geladen, aber nicht gestartet.
* Regulär beendeter Titel: der nächste Titel startet immer automatisch.
* "Pausen überspringen" (abschaltbar): Stille am Titelanfang wird übersprungen,
  Stille am Titelende gilt als Titelende. Die Grenzen liefert die Analyse.

Ob "gerade Musik läuft", merkt sich der Controller in ``_wants_playing``
(Benutzerabsicht) statt nur ``playbackState()`` abzufragen. Beim Laden eines
neuen Titels durchläuft QMediaPlayer kurz den Zustand "gestoppt"; ein
schneller zweiter Tastendruck würde sonst fälschlich als "war gestoppt"
gewertet.
"""

import math

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..playlist import Playlist

# ------------------------------------------------------------ Konstanten
SPEED_MIN = 0.5
SPEED_MAX = 2.0
SPEED_STEP = 0.01             # Auflösung von Regler, Tasten und Schaltflächen

VOLUME_STEP = 5               # Prozentpunkte pro Tastendruck
VOLUME_DYNAMIC_RANGE_DB = 50  # Regler 1 % ≈ -50 dB, 100 % = 0 dB

END_JUMP_REMAINING_MS = 1000  # "Zum Titelende" lässt so viel Restzeit übrig
SCRUB_INTERVAL_MS = 150       # Takt beim Spulen (Taste gehalten)
SCRUB_STEP_MS = 750           # Sprungweite pro Takt (≈ 5-fache Geschwindigkeit)
SCRUB_END_MARGIN_MS = 500     # Vorspulen hält kurz vor dem Ende an
MIN_SILENCE_SKIP_MS = 500     # kürzere Pausen werden nicht übersprungen
LEAD_SKIP_WINDOW_MS = 3000    # Musikanfang nur anspringen, solange der Titel noch "am Anfang" steht


def perceptual_to_linear(percent: int) -> float:
    """Wandelt den Lautstärkeregler (0–100) in den linearen Wert für QAudioOutput.

    ``QAudioOutput.setVolume`` erwartet eine lineare Amplitude (0.0–1.0). Das
    Ohr empfindet Lautstärke aber logarithmisch – ein linearer Regler wäre
    in der unteren Hälfte kaum hörbar unterschiedlich und oben sehr grob.
    Deshalb bildet der Regler gleichmäßig auf Dezibel ab.
    """
    percent = max(0, min(100, int(percent)))
    if percent == 0:
        return 0.0
    db = -VOLUME_DYNAMIC_RANGE_DB * (1.0 - percent / 100.0)
    return math.pow(10.0, db / 20.0)


def normalize_speed(speed: float) -> float:
    """Begrenzt auf SPEED_MIN..SPEED_MAX.

    Gerundet wird auf 4 Nachkommastellen statt auf SPEED_STEP, damit sich
    beliebige Ziel-BPM exakt einstellen lassen (z. B. 121 BPM bei einem
    Titel mit 123,6 BPM = 0,9790x).
    """
    return max(SPEED_MIN, min(SPEED_MAX, round(float(speed), 4)))


class PlaybackController(QObject):
    currentIndexChanged = Signal(int)
    playlistChanged = Signal()
    playingChanged = Signal(bool)
    # Millisekunden als qint64, passend zu den QMediaPlayer-Signalen.
    positionChanged = Signal("qint64")
    durationChanged = Signal("qint64")
    volumeChanged = Signal(int)
    speedChanged = Signal(float)
    errorMessage = Signal(str)

    def __init__(self, playlist: Playlist | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.playlist = playlist or Playlist()

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        if hasattr(self._player, "setPitchCompensation"):
            # Tonhöhe bei geänderter Geschwindigkeit beibehalten (falls unterstützt).
            self._player.setPitchCompensation(True)

        self._volume = 80
        self._speed = 1.0
        self._wants_playing = False
        self._loaded_index = -1
        self._scrub_direction = 0

        # "Pausen überspringen": Musikanfang/-ende des geladenen Titels in ms
        # (0 = unbekannt), geliefert vom TrackAnalysisService.
        self._skip_silence = True
        self._music_start_ms = 0
        self._music_end_ms = 0
        self._pending_seek_ms: int | None = None  # Sprung, sobald das Medium geladen ist
        self._lead_on_play = False                # Sprung beim nächsten Start (war gestoppt)
        self._early_end_done = False

        self._scrub_timer = QTimer(self)
        self._scrub_timer.setInterval(SCRUB_INTERVAL_MS)
        self._scrub_timer.timeout.connect(self._scrub_tick)

        # Bewusst echte Slots statt Lambdas: so stellt Qt die Aufrufe sicher
        # im GUI-Thread zu, auch wenn das Backend aus einem eigenen Thread meldet.
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error)

        self.set_volume(self._volume)

    # ------------------------------------------------------------ Status
    def is_playing(self) -> bool:
        return self._wants_playing

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    def volume(self) -> int:
        return self._volume

    def speed(self) -> float:
        return self._speed

    def current_index(self) -> int:
        return self.playlist.current_index

    # ------------------------------------------------------ Titel laden
    def load_index(self, index: int, play: bool) -> None:
        """Lädt einen Titel; startet ihn nur, wenn ``play`` True ist."""
        if not self.playlist.is_valid_index(index):
            return
        self.stop_scrub()
        self.playlist.current_index = index
        self._loaded_index = index
        self._wants_playing = play
        self._music_start_ms = self._music_end_ms = 0
        self._pending_seek_ms = None
        self._lead_on_play = False
        self._early_end_done = False
        self._player.setSource(QUrl.fromLocalFile(self.playlist.items[index]))
        # Manche Backends setzen die Rate beim Quellenwechsel zurück.
        self._player.setPlaybackRate(self._speed)
        if play:
            self._player.play()
        self.currentIndexChanged.emit(index)
        self.playingChanged.emit(play)

    def play_index(self, index: int) -> None:
        """Titel direkt starten (z. B. Doppelklick in der Playlist)."""
        self.load_index(index, play=True)

    def select_index(self, index: int) -> None:
        """Titel nur auswählen/laden, ohne die Wiedergabe zu starten."""
        self.load_index(index, play=False)

    def _ensure_current_loaded(self) -> bool:
        index = self.playlist.current_index
        if not self.playlist.is_valid_index(index):
            return False
        if self._loaded_index != index or self._player.source().isEmpty():
            self.load_index(index, play=False)
        return True

    # ------------------------------------------------- Transportfunktionen
    def play(self) -> None:
        if not self._ensure_current_loaded():
            return
        self._wants_playing = True
        self._player.play()
        if self._lead_on_play:
            self._lead_on_play = False
            if self._skips_lead():
                self._jump_to_music_start()
        self.playingChanged.emit(True)

    def pause(self) -> None:
        self.stop_scrub()
        self._wants_playing = False
        self._player.pause()
        self.playingChanged.emit(False)

    def stop(self) -> None:
        self.stop_scrub()
        self._wants_playing = False
        self._player.stop()
        self.playingChanged.emit(False)

    def toggle_play_pause(self, preferred_index: int | None = None) -> None:
        """Play/Pause umschalten.

        Ist die Wiedergabe angehalten und in der Playlist ein *anderer* Titel
        markiert (``preferred_index``), wird dieser gestartet.
        """
        if self._wants_playing:
            self.pause()
        elif (
            preferred_index is not None
            and self.playlist.is_valid_index(preferred_index)
            and preferred_index != self.playlist.current_index
        ):
            self.play_index(preferred_index)
        else:
            self.play()

    def next_track(self) -> None:
        """Nächster Titel; spielt nur weiter, wenn vorher Musik lief."""
        index = self.playlist.next_index()
        if index is not None:
            self.load_index(index, play=self._wants_playing)

    def previous_track(self) -> None:
        """Vorheriger Titel; beim ersten Titel wird an den Anfang gesprungen."""
        index = self.playlist.previous_index()
        if index is not None:
            self.load_index(index, play=self._wants_playing)
        else:
            self.seek_to_start()

    # ---------------------------------------------------------- Position
    def seek(self, position_ms: int) -> None:
        if not self._ensure_current_loaded():
            return
        duration = self._player.duration()
        if duration > 0:
            position_ms = min(position_ms, duration)
        self._early_end_done = False
        self._lead_on_play = False  # der Benutzer hat die Position selbst gewählt
        self._player.setPosition(max(0, int(position_ms)))

    def seek_to_start(self) -> None:
        """An den Titelanfang – bei "Pausen überspringen" an den Musikanfang."""
        self.seek(self._music_start_ms if self._skips_lead() else 0)

    # --------------------------------------------------- Pausen überspringen
    def skip_silence(self) -> bool:
        return self._skip_silence

    def set_skip_silence(self, enabled: bool) -> None:
        self._skip_silence = enabled

    def set_music_bounds(self, path: str, start_ms: int, end_ms: int) -> None:
        """Musikanfang/-ende für ``path`` mitteilen (wirkt nur auf den geladenen Titel).

        Steht der Titel noch am Anfang, wird sofort zum Musikanfang gesprungen;
        das Ende wird laufend in ``_check_early_end`` geprüft.
        """
        if path != self.playlist.current_path or self._loaded_index != self.playlist.current_index:
            return
        self._music_start_ms = max(0, int(start_ms))
        self._music_end_ms = max(0, int(end_ms))
        if self._skips_lead() and self._player.position() < min(self._music_start_ms, LEAD_SKIP_WINDOW_MS):
            if self._wants_playing:
                self._jump_to_music_start()
            else:
                # Im gestoppten Zustand hält Qt eine neue Position nicht fest.
                self._lead_on_play = True

    def _skips_lead(self) -> bool:
        return self._skip_silence and self._music_start_ms >= MIN_SILENCE_SKIP_MS

    def _jump_to_music_start(self) -> None:
        if self._player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._player.setPosition(self._music_start_ms)
        else:
            self._pending_seek_ms = self._music_start_ms  # nach dem Laden

    def _check_early_end(self, position: int) -> None:
        duration = self._player.duration()
        if (
            self._skip_silence
            and self._wants_playing
            and not self._early_end_done
            and not self._scrub_direction
            and self._music_end_ms > self._music_start_ms
            and duration - self._music_end_ms >= MIN_SILENCE_SKIP_MS
            and position >= self._music_end_ms
        ):
            # Restliche Stille überspringen: wie ein reguläres Titelende behandeln.
            self._early_end_done = True
            QTimer.singleShot(0, self._advance_after_silence)

    def _advance_after_silence(self) -> None:
        if not self._early_end_done or not self._wants_playing:
            return
        index = self.playlist.next_index()
        if index is not None:
            self.load_index(index, play=True)
        else:
            self.stop()

    def seek_to_end(self) -> None:
        duration = self._player.duration()
        if duration > 0:
            self.seek(max(0, duration - END_JUMP_REMAINING_MS))

    def start_scrub(self, direction: int) -> None:
        """Spulen starten: direction = -1 (zurück) oder +1 (vor)."""
        if not self._ensure_current_loaded():
            return
        self._scrub_direction = 1 if direction > 0 else -1
        self._scrub_tick()
        self._scrub_timer.start()

    def stop_scrub(self) -> None:
        self._scrub_direction = 0
        self._scrub_timer.stop()

    def is_scrubbing(self) -> bool:
        return self._scrub_direction != 0

    def _scrub_tick(self) -> None:
        if not self._scrub_direction:
            self._scrub_timer.stop()
            return
        duration = self._player.duration()
        if duration <= 0:
            return
        target = self._player.position() + self._scrub_direction * SCRUB_STEP_MS
        upper = max(0, duration - SCRUB_END_MARGIN_MS)
        self._player.setPosition(max(0, min(upper, target)))

    # -------------------------------------------------------- Lautstärke
    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        self._volume = percent
        self._audio.setVolume(perceptual_to_linear(percent))
        self.volumeChanged.emit(percent)

    def change_volume(self, delta: int) -> None:
        self.set_volume(self._volume + delta)

    # ---------------------------------------------------- Geschwindigkeit
    def set_speed(self, speed: float) -> None:
        self._speed = normalize_speed(speed)
        self._player.setPlaybackRate(self._speed)
        self.speedChanged.emit(self._speed)

    def change_speed(self, steps: int) -> None:
        # Auf das SPEED_STEP-Raster einrasten (nach BPM-Einstellung kann der
        # Wert z. B. 0,979 sein; +1 Schritt ergibt dann 0,99).
        if steps == 0:
            return
        position = self._speed / SPEED_STEP
        if steps > 0:
            target = math.floor(position + 1e-6) + steps
        else:
            target = math.ceil(position - 1e-6) + steps
        self.set_speed(target * SPEED_STEP)

    def reset_speed(self) -> None:
        self.set_speed(1.0)

    # ------------------------------------------------- Playlist-Änderungen
    def add_files(self, paths) -> int:
        had_items = len(self.playlist) > 0
        added = self.playlist.add(paths)
        if added:
            self.playlistChanged.emit()
            if not had_items:
                self.select_index(self.playlist.current_index)
        return added

    def remove_index(self, index: int) -> None:
        was_current = self.playlist.remove(index)
        if was_current:
            self.stop()
            self._player.setSource(QUrl())
            self._loaded_index = -1
            if self.playlist.is_valid_index(self.playlist.current_index):
                self.select_index(self.playlist.current_index)
        elif self._loaded_index > index:
            self._loaded_index -= 1
        self.playlistChanged.emit()
        self.currentIndexChanged.emit(self.playlist.current_index)

    def shuffle_playlist(self) -> None:
        """Reihenfolge mischen; der aktuelle Titel bleibt geladen bzw. spielt weiter."""
        if len(self.playlist) < 2:
            return
        current_was_loaded = self._loaded_index == self.playlist.current_index
        self.playlist.shuffle()
        if current_was_loaded:
            self._loaded_index = self.playlist.current_index
        self.playlistChanged.emit()
        self.currentIndexChanged.emit(self.playlist.current_index)

    def replace_playlist(self, items: list[str], current_index: int = 0) -> None:
        self.stop()
        self._player.setSource(QUrl())
        self._loaded_index = -1
        self.playlist.replace(items, current_index)
        self.playlistChanged.emit()
        if self.playlist.is_valid_index(self.playlist.current_index):
            self.select_index(self.playlist.current_index)
        else:
            self.currentIndexChanged.emit(-1)

    # ------------------------------------------------- Player-Ereignisse
    @Slot("qint64")
    def _on_position_changed(self, position: int) -> None:
        self.positionChanged.emit(position)
        self._check_early_end(position)

    @Slot("qint64")
    def _on_duration_changed(self, duration: int) -> None:
        self.durationChanged.emit(duration)

    @Slot(QMediaPlayer.PlaybackState)
    def _on_state_changed(self, state) -> None:
        # Fremdgesteuerte Pause (z. B. Audiogerät entfernt) übernehmen.
        if state == QMediaPlayer.PlaybackState.PausedState and self._wants_playing:
            self._wants_playing = False
            self.playingChanged.emit(False)

    def _on_media_status_changed(self, status) -> None:
        if self._pending_seek_ms is not None and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._player.setPosition(self._pending_seek_ms)
            self._pending_seek_ms = None
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_scrub()
            # Über die Ereignisschleife entkoppeln, statt mitten im
            # Signal-Handler von QMediaPlayer die Quelle zu wechseln.
            QTimer.singleShot(0, self._advance_after_end)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._wants_playing = False
            self.playingChanged.emit(False)

    def _advance_after_end(self) -> None:
        if self._player.mediaStatus() != QMediaPlayer.MediaStatus.EndOfMedia:
            return  # inzwischen hat der Benutzer etwas anderes gewählt
        index = self.playlist.next_index()
        if index is not None:
            self.load_index(index, play=True)
        else:
            self._wants_playing = False
            self.playingChanged.emit(False)

    def _on_error(self, error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        path = self.playlist.current_path
        name = self.playlist.title(self.playlist.current_index) if path else ""
        text = f"„{name}“ kann nicht abgespielt werden: {message}" if name else message
        self.errorMessage.emit(text)
