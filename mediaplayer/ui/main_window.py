"""Hauptfenster des Players (für die Bedienung im Vollbild ausgelegt)."""

from pathlib import Path

from PySide6.QtCore import QDir, QEvent, QSize, QStandardPaths, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..player.keyboard import KeyboardController
from ..player.analysis import TrackAnalysisService
from ..player.markers import MarkerController
from ..player.tempo import TempoController
from ..player.playback import (
    SPEED_MAX,
    SPEED_MIN,
    SPEED_STEP,
    VOLUME_STEP,
    PlaybackController,
    format_ms,
)
from ..playlist import (
    AUDIO_EXTENSIONS,
    PLAYLIST_EXTENSIONS,
    is_audio_file,
    load_playlist_file,
    save_playlist_file,
)
from ..settings import AppSettings
from ..settings import key_bindings as kb
from .file_browser import FileBrowserDialog
from .key_config_dialog import KeyConfigDialog
from .recent_playlists_dialog import RecentPlaylistsDialog
from .style import BUTTON_HEIGHT, ICON_SIZE
from .widgets import MarkerSlider, enable_touch_scrolling

MESSAGE_TIMEOUT_MS = 6000


def format_speed(speed: float) -> str:
    return f"{speed:.2f}x".replace(".", ",")


def format_bpm(bpm: float) -> str:
    return f"{bpm:.1f}".replace(".", ",").removesuffix(",0")


class PlaylistWidget(QListWidget):
    """Playlist-Ansicht; Doppelklick oder Eingabetaste startet einen Titel."""

    playRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.setUniformItemSizes(False)
        self.itemDoubleClicked.connect(lambda item: self.playRequested.emit(self.row(item)))
        enable_touch_scrolling(self)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentRow() >= 0:
            self.playRequested.emit(self.currentRow())
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None):
        super().__init__()
        self.settings = settings or AppSettings()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 700)
        self.setAcceptDrops(True)

        self.controller = PlaybackController(parent=self)
        self.controller.set_skip_silence(self.settings.skip_silence())
        # Reihenfolge wichtig: die Analyse muss Titelwechsel vor dem Tempo sehen.
        self.analysis = TrackAnalysisService(self.controller, self.settings, parent=self)
        self.tempo = TempoController(self.controller, self.settings, self.analysis, parent=self)
        self.markers = MarkerController(self.controller, self.settings, parent=self)
        self._message_token = 0

        self._build_ui()
        self._connect_controller()
        self._connect_tempo()
        self._connect_markers()

        self.keyboard = KeyboardController(self, self.settings.key_bindings())
        self.keyboard.triggered.connect(self._on_key_action)
        self.keyboard.install()
        self._key_actions = self._build_key_actions()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._leave_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self._toggle_fullscreen)

        self._restore_state()

    # ================================================================= UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(20)

        # --- Zeit und Meldungen
        top = QHBoxLayout()
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("timeLabel")
        top.addWidget(self.time_label)
        top.addStretch(1)
        self.message_label = QLabel("")
        self.message_label.setObjectName("messageLabel")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.message_label.setWordWrap(True)
        top.addWidget(self.message_label, 2)
        top.addSpacing(30)
        self.clock_label = QLabel("")
        self.clock_label.setObjectName("clockLabel")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.clock_label)
        root.addLayout(top)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        # --- Positionsregler (anklickbar und verschiebbar, siehe PlayerStyle)
        self.position_slider = MarkerSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.position_slider.setToolTip("Klicken oder ziehen, um die Position zu ändern")
        self.position_slider.sliderReleased.connect(self._on_position_released)
        self.position_slider.valueChanged.connect(self._on_position_value_changed)
        self._updating_position = False
        root.addWidget(self.position_slider)

        # --- Transport + Lautstärke
        transport = QHBoxLayout()
        transport.setSpacing(16)
        self.prev_button = self._make_icon_button(
            QStyle.StandardPixmap.SP_MediaSkipBackward, "Vorheriger Titel", self.controller.previous_track
        )
        self.play_button = self._make_icon_button(
            QStyle.StandardPixmap.SP_MediaPlay, "Play / Pause", self.toggle_play_pause
        )
        self.stop_button = self._make_icon_button(
            QStyle.StandardPixmap.SP_MediaStop, "Stop", self.controller.stop
        )
        self.next_button = self._make_icon_button(
            QStyle.StandardPixmap.SP_MediaSkipForward, "Nächster Titel", self.controller.next_track
        )
        for button in (self.prev_button, self.play_button, self.stop_button, self.next_button):
            transport.addWidget(button)
        transport.addSpacing(16)
        self.skip_button = self._make_text_button(
            "Pausen\nüberspringen", "Stille am Anfang und Ende der Titel überspringen", lambda: None
        )
        self.skip_button.setCheckable(True)
        self.skip_button.setChecked(self.settings.skip_silence())
        self.skip_button.setMinimumHeight(BUTTON_HEIGHT)
        self.skip_button.setObjectName("skipButton")
        self.skip_button.toggled.connect(self._on_skip_toggled)
        transport.addWidget(self.skip_button)
        transport.addSpacing(30)

        volume_icon = QLabel()
        volume_icon.setPixmap(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume).pixmap(40, 40)
        )
        volume_icon.setToolTip("Lautstärke")
        transport.addWidget(volume_icon)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setPageStep(VOLUME_STEP * 2)
        self.volume_slider.setSingleStep(VOLUME_STEP)
        self.volume_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume_slider.setToolTip("Lautstärke")
        self.volume_slider.valueChanged.connect(self.controller.set_volume)
        transport.addWidget(self.volume_slider, 1)
        self.volume_label = QLabel("80 %")
        self.volume_label.setObjectName("volumeLabel")
        transport.addWidget(self.volume_label)
        root.addLayout(transport)

        # --- Markierungen (Sprungmarken im aktuellen Titel)
        marker_row = QHBoxLayout()
        marker_row.setSpacing(16)
        marker_title = QLabel("Markierungen")
        marker_title.setObjectName("sectionLabel")
        marker_row.addWidget(marker_title)
        marker_row.addWidget(self._make_text_button(
            "Setzen", "Markierung an der gerade gespielten Stelle setzen", self.markers.add_at_current
        ))
        self.marker_prev_button = self._make_text_button(
            "◀", "Zur vorherigen Markierung springen", self.markers.jump_previous
        )
        marker_row.addWidget(self.marker_prev_button)
        self.marker_next_button = self._make_text_button(
            "▶", "Zur nächsten Markierung springen", self.markers.jump_next
        )
        marker_row.addWidget(self.marker_next_button)
        self.marker_delete_button = self._make_text_button(
            "Löschen", "Die Markierung löschen, die der aktuellen Stelle am nächsten ist",
            self.markers.delete_nearest,
        )
        marker_row.addWidget(self.marker_delete_button)
        self.marker_clear_button = self._make_text_button(
            "Alle löschen", "Alle Markierungen dieses Titels löschen", self.clear_markers
        )
        marker_row.addWidget(self.marker_clear_button)
        self.marker_count_label = QLabel()
        self.marker_count_label.setObjectName("sectionLabel")
        marker_row.addWidget(self.marker_count_label)
        marker_row.addStretch(1)
        root.addLayout(marker_row)

        # --- Geschwindigkeit
        speed_row = QHBoxLayout()
        speed_row.setSpacing(16)
        speed_title = QLabel("Tempo")
        speed_title.setObjectName("sectionLabel")
        speed_row.addWidget(speed_title)
        # Die Tempo-Zeile wird mit dem TempoController verbunden, siehe _connect_tempo().
        slower = self._make_text_button("−", "Langsamer (1 BPM bzw. 0,01x)", lambda: self.tempo.step(-1))
        speed_row.addWidget(slower)
        # Regler arbeitet in ganzen BPM, wenn das Tempo bekannt ist, sonst in 0,01x-Schritten.
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setPageStep(10)
        self.speed_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed_slider.valueChanged.connect(self._on_speed_slider)
        self._slider_in_bpm = False
        speed_row.addWidget(self.speed_slider, 1)
        faster = self._make_text_button("+", "Schneller (1 BPM bzw. 0,01x)", lambda: self.tempo.step(1))
        speed_row.addWidget(faster)
        # Kurz tippen = ein Schritt; gedrückt halten = läuft schnell weiter.
        for button in (slower, faster):
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(50)
        self.speed_label = QLabel()
        self.speed_label.setObjectName("speedLabel")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speed_label.setTextFormat(Qt.TextFormat.RichText)
        self.speed_label.setMinimumWidth(260)
        speed_row.addWidget(self.speed_label)
        speed_row.addWidget(self._make_text_button("1,00x", "Originaltempo", lambda: self.tempo.reset()))
        self.tap_button = self._make_text_button(
            "Tap", "Im Takt mehrmals antippen, um das Tempo selbst festzulegen", lambda: self.tempo.tap()
        )
        speed_row.addWidget(self.tap_button)
        self.half_button = self._make_text_button("½", "Erkanntes Tempo halbieren", lambda: self.tempo.halve())
        speed_row.addWidget(self.half_button)
        self.double_button = self._make_text_button("×2", "Erkanntes Tempo verdoppeln", lambda: self.tempo.double())
        speed_row.addWidget(self.double_button)
        self.lock_button = self._make_text_button(
            "BPM fest", "Alle Titel mit denselben BPM abspielen", lambda: None
        )
        self.lock_button.setCheckable(True)
        self.lock_button.toggled.connect(lambda on: self.tempo.set_locked(on))
        speed_row.addWidget(self.lock_button)
        root.addLayout(speed_row)

        # --- Playlist
        self.playlist_view = PlaylistWidget()
        self.playlist_view.playRequested.connect(self.controller.play_index)
        root.addWidget(self.playlist_view, 1)
        self.playlist_view.setFocus()

        # --- Untere Leiste
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._make_text_button("Hinzufügen", "Audiodateien hinzufügen", self.add_files))
        bottom.addWidget(self._make_text_button("Entfernen", "Markierten Titel entfernen", self.remove_selected))
        bottom.addWidget(self._make_text_button(
            "Mischen", "Reihenfolge einmal zufällig mischen (wird nicht gespeichert)", self.shuffle_playlist
        ))
        bottom.addWidget(self._make_text_button("Playlist laden", "Playlist-Datei laden", self.load_playlist))
        bottom.addWidget(self._make_text_button(
            "Zuletzt", "Zuletzt verwendete Playlists (Schnellauswahl)", self.show_recent_playlists
        ))
        bottom.addWidget(self._make_text_button("Playlist speichern", "Playlist-Datei speichern", self.save_playlist))
        bottom.addStretch(1)
        bottom.addWidget(self._make_text_button("Tastatur", "Tastaturbelegung konfigurieren", self.configure_keys))
        quit_button = self._make_text_button("Beenden", "Programm beenden", self.close)
        quit_button.setObjectName("quitButton")
        bottom.addWidget(quit_button)
        root.addLayout(bottom)

    def _on_skip_toggled(self, enabled: bool) -> None:
        self.controller.set_skip_silence(enabled)
        self.settings.set_skip_silence(enabled)
        self.show_message("Pausen werden übersprungen." if enabled else "Pausen werden abgespielt.")

    def _update_clock(self) -> None:
        self.clock_label.setText(QTime.currentTime().toString("HH:mm"))

    def _make_icon_button(self, pixmap, tooltip: str, slot) -> QPushButton:
        button = QPushButton()
        button.setObjectName("transportButton")
        button.setIcon(self.style().standardIcon(pixmap))
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setMinimumHeight(BUTTON_HEIGHT)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(slot)
        return button

    def _make_text_button(self, text: str, tooltip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(64)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(slot)
        return button

    # ====================================================== Controller
    def _connect_controller(self) -> None:
        c = self.controller
        c.positionChanged.connect(self._on_position_changed)
        c.durationChanged.connect(self._on_duration_changed)
        c.playingChanged.connect(self._on_playing_changed)
        c.currentIndexChanged.connect(self._on_current_index_changed)
        c.playlistChanged.connect(self._refresh_playlist)
        c.volumeChanged.connect(self._on_volume_changed)
        c.speedChanged.connect(self._on_speed_changed)
        c.errorMessage.connect(self.show_message)

    def _build_key_actions(self) -> dict:
        c = self.controller
        return {
            kb.PLAY_PAUSE: self.toggle_play_pause,
            kb.VOLUME_UP: lambda: c.change_volume(VOLUME_STEP),
            kb.VOLUME_DOWN: lambda: c.change_volume(-VOLUME_STEP),
            kb.SPEED_UP: lambda: self.tempo.step(1),
            kb.SPEED_DOWN: lambda: self.tempo.step(-1),
            kb.SPEED_RESET: self.tempo.reset,
            # Verzögert öffnen, damit der Dialog nicht innerhalb des Tastenereignisses startet.
            kb.RECENT_PLAYLISTS: lambda: QTimer.singleShot(0, self.show_recent_playlists),
            kb.MARKER_SET: self.markers.add_at_current,
            kb.MARKER_PREVIOUS: self.markers.jump_previous,
            kb.MARKER_NEXT: self.markers.jump_next,
            kb.MARKER_DELETE: self.markers.delete_nearest,
            f"{kb.BACK}_single": c.seek_to_start,
            f"{kb.BACK}_double": c.previous_track,
            f"{kb.BACK}_hold_start": lambda: c.start_scrub(-1),
            f"{kb.BACK}_hold_end": c.stop_scrub,
            f"{kb.FORWARD}_single": c.seek_to_end,
            f"{kb.FORWARD}_double": c.next_track,
            f"{kb.FORWARD}_hold_start": lambda: c.start_scrub(1),
            f"{kb.FORWARD}_hold_end": c.stop_scrub,
        }

    def _on_key_action(self, name: str) -> None:
        handler = self._key_actions.get(name)
        if handler is not None:
            handler()

    def toggle_play_pause(self) -> None:
        selected = self.playlist_view.currentRow()
        self.controller.toggle_play_pause(selected if selected >= 0 else None)

    def _on_position_changed(self, position: int) -> None:
        if not self.position_slider.isSliderDown():
            self._updating_position = True
            self.position_slider.setValue(position)
            self._updating_position = False
            self._update_time_label(position)

    def _on_duration_changed(self, duration: int) -> None:
        self._updating_position = True
        self.position_slider.setRange(0, max(0, duration))
        self._updating_position = False
        self._update_time_label(self.controller.position())

    def _on_position_value_changed(self, value: int) -> None:
        if self._updating_position:
            return
        if self.position_slider.isSliderDown():
            self._update_time_label(value)  # Vorschau beim Ziehen
        else:
            self.controller.seek(value)     # z. B. Mausrad

    def _on_position_released(self) -> None:
        self.controller.seek(self.position_slider.value())

    def _update_time_label(self, position: int) -> None:
        self.time_label.setText(f"{format_ms(position)} / {format_ms(self.controller.duration())}")

    def _on_playing_changed(self, playing: bool) -> None:
        icon = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))

    def _on_current_index_changed(self, index: int) -> None:
        self._refresh_playlist()
        playlist = self.controller.playlist
        if playlist.is_valid_index(index):
            self.setWindowTitle(f"{playlist.title(index)} – {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)
            self._on_duration_changed(0)
        self._save_session()

    def _on_volume_changed(self, percent: int) -> None:
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(percent)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{percent} %")
        self.settings.set_volume(percent)

    def _on_speed_changed(self, speed: float) -> None:
        self.settings.set_speed(speed)

    # ============================================================ Tempo
    def _connect_tempo(self) -> None:
        self.tempo.tempoChanged.connect(self._on_tempo_changed)
        self.tempo.message.connect(self.show_message)
        self.lock_button.blockSignals(True)
        self.lock_button.setChecked(self.tempo.is_locked())
        self.lock_button.blockSignals(False)
        self._on_tempo_changed(0.0, 0.0, self.controller.speed(), False)

    def _on_tempo_changed(self, original: float, current: float, speed: float, analyzing: bool) -> None:
        slider = self.speed_slider
        slider.blockSignals(True)
        self._slider_in_bpm = original > 0
        if self._slider_in_bpm:
            slider.setRange(round(original * SPEED_MIN), round(original * SPEED_MAX))
            slider.setValue(round(current))
            slider.setToolTip(f"Tempo {slider.minimum()} – {slider.maximum()} BPM")
            main = f"{current:.0f} BPM"
            detail = f"Original {format_bpm(original)} · {format_speed(speed)}"
        else:
            slider.setRange(round(SPEED_MIN / SPEED_STEP), round(SPEED_MAX / SPEED_STEP))
            slider.setValue(round(speed / SPEED_STEP))
            slider.setToolTip(f"Geschwindigkeit {format_speed(SPEED_MIN)} – {format_speed(SPEED_MAX)}")
            main = format_speed(speed)
            if analyzing:
                detail = "BPM wird ermittelt …"
            elif self.controller.playlist.current_path:
                detail = "BPM unbekannt – Tap"
            else:
                detail = ""
        slider.blockSignals(False)
        self.speed_label.setText(
            f"<div style='font-size:30px; font-weight:bold'>{main}</div>"
            f"<div style='font-size:18px; color:#b8bcc4'>{detail}</div>"
        )
        self.half_button.setEnabled(original > 0)
        self.double_button.setEnabled(original > 0)
        self.tap_button.setEnabled(bool(self.controller.playlist.current_path))

    def _on_speed_slider(self, value: int) -> None:
        if self._slider_in_bpm:
            self.tempo.set_bpm(value)
        else:
            self.controller.set_speed(value * SPEED_STEP)

    # ===================================================== Markierungen
    def _connect_markers(self) -> None:
        self.markers.markersChanged.connect(self._on_markers_changed)
        self.markers.message.connect(self.show_message)
        self._on_markers_changed(self.markers.markers())

    def _on_markers_changed(self, positions: list) -> None:
        self.position_slider.set_markers(positions)
        has_markers = bool(positions)
        for button in (
            self.marker_prev_button, self.marker_next_button,
            self.marker_delete_button, self.marker_clear_button,
        ):
            button.setEnabled(has_markers)
        self.marker_count_label.setText(f"{len(positions)} gesetzt" if has_markers else "keine")

    def clear_markers(self) -> None:
        count = len(self.markers.markers())
        if not count:
            return
        answer = self._run_modal(lambda: QMessageBox.question(
            self, "Markierungen löschen", f"Alle {count} Markierung(en) dieses Titels löschen?"
        ))
        if answer == QMessageBox.StandardButton.Yes:
            self.markers.clear()

    def _refresh_playlist(self) -> None:
        playlist = self.controller.playlist
        view = self.playlist_view
        view.blockSignals(True)
        view.clear()
        for i in range(len(playlist)):
            is_current = i == playlist.current_index
            marker = "▶  " if is_current else "     "
            item = QListWidgetItem(f"{marker}{i + 1:02d}   {playlist.title(i)}")
            item.setToolTip(playlist.items[i])
            if is_current:
                font = QFont(view.font())
                font.setBold(True)
                item.setFont(font)
            view.addItem(item)
        if playlist.is_valid_index(playlist.current_index):
            view.setCurrentRow(playlist.current_index)
            view.scrollToItem(view.currentItem(), QAbstractItemView.ScrollHint.EnsureVisible)
        view.blockSignals(False)

    # ======================================================== Aktionen
    def _start_directory(self) -> str:
        last = self.settings.last_directory()
        if last and Path(last).is_dir():
            return last
        music = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
        return music if music and Path(music).is_dir() else QDir.homePath()

    def _run_modal(self, func):
        """Dialog ausführen; Player-Tasten solange aus, danach Fokus zurück zur Playlist."""
        self.keyboard.set_enabled(False)
        try:
            return func()
        finally:
            self.keyboard.set_enabled(True)
            self.playlist_view.setFocus()

    def add_files(self) -> None:
        paths = self._run_modal(lambda: FileBrowserDialog.get_open_files(
            self, "Audiodateien hinzufügen", self._start_directory(), AUDIO_EXTENSIONS, "Hinzufügen"
        ))
        if paths:
            self.settings.set_last_directory(str(Path(paths[0]).parent))
            self._add_paths(paths)

    def _add_paths(self, paths) -> None:
        added = self.controller.add_files(paths)
        skipped = len(paths) - added
        if skipped:
            self.show_message(f"{skipped} Datei(en) übersprungen (bereits vorhanden oder kein Audioformat).")
        self._save_session()

    def shuffle_playlist(self) -> None:
        if len(self.controller.playlist) < 2:
            self.show_message("Zum Mischen werden mindestens zwei Titel benötigt.")
            return
        self.controller.shuffle_playlist()
        self.playlist_view.scrollToTop()
        self.show_message("Playlist gemischt (nicht gespeichert).")

    def remove_selected(self) -> None:
        row = self.playlist_view.currentRow()
        if row >= 0:
            self.controller.remove_index(row)
            self._save_session()

    def save_playlist(self) -> None:
        if not len(self.controller.playlist):
            self.show_message("Die Playlist ist leer.")
            return
        path = self._run_modal(lambda: FileBrowserDialog.get_save_file(
            self, "Playlist speichern", self._start_directory(), PLAYLIST_EXTENSIONS,
            default_name="Playlist.m3u8", default_suffix=".m3u8",
        ))
        if not path:
            return
        try:
            saved = save_playlist_file(path, self.controller.playlist.items)
        except OSError as exc:
            QMessageBox.critical(self, "Fehler", f"Playlist konnte nicht gespeichert werden:\n{exc}")
            return
        self.settings.set_last_directory(str(saved.parent))
        self.settings.add_recent_playlist(str(saved))
        self.show_message(f"Playlist gespeichert: {saved.name}")

    def load_playlist(self) -> None:
        path = self._run_modal(lambda: FileBrowserDialog.get_open_file(
            self, "Playlist laden", self._start_directory(), PLAYLIST_EXTENSIONS, "Laden"
        ))
        if path:
            self.open_playlist_file(path)

    def show_recent_playlists(self) -> None:
        if not self.keyboard.is_enabled():
            return  # es ist bereits ein Dialog offen
        dialog = RecentPlaylistsDialog(
            self.settings.recent_playlists(),
            toggle_keys=self.settings.key_bindings()[kb.RECENT_PLAYLISTS],
            parent=self,
        )
        accepted = self._run_modal(dialog.exec)
        self.settings.set_recent_playlists(dialog.remaining_paths())
        if accepted and dialog.chosen_path():
            self.open_playlist_file(dialog.chosen_path())

    def open_playlist_file(self, path: str) -> None:
        try:
            items, missing = load_playlist_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Fehler", f"Playlist konnte nicht geladen werden:\n{exc}")
            return
        self.settings.set_last_directory(str(Path(path).parent))
        self.settings.add_recent_playlist(path)
        self.controller.replace_playlist(items)
        self._save_session()
        text = f"Playlist „{Path(path).stem}“ geladen: {len(self.controller.playlist)} Titel"
        if missing:
            text += f", {len(missing)} Datei(en) nicht gefunden"
        self.show_message(text)

    def configure_keys(self) -> None:
        dialog = KeyConfigDialog(self.settings.key_bindings(), self)
        if self._run_modal(dialog.exec):
            bindings = dialog.bindings()
            self.settings.set_key_bindings(bindings)
            self.keyboard.set_bindings(bindings)
            self.show_message("Tastaturbelegung gespeichert.")

    def show_message(self, text: str) -> None:
        self._message_token += 1
        token = self._message_token
        self.message_label.setText(text)
        QTimer.singleShot(MESSAGE_TIMEOUT_MS, lambda: self._clear_message(token))

    def _clear_message(self, token: int) -> None:
        if token == self._message_token:
            self.message_label.clear()

    # ======================================================== Vollbild
    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    # ================================================ Zustand speichern
    def _restore_state(self) -> None:
        self.controller.set_volume(self.settings.volume())
        self.controller.set_speed(self.settings.speed())
        items, index = self.settings.session_playlist()
        existing = [p for p in items if Path(p).is_file()]
        if existing:
            if 0 <= index < len(items) and items[index] in existing:
                index = existing.index(items[index])
            else:
                index = 0
            self.controller.replace_playlist(existing, index)
        else:
            self._refresh_playlist()

    def _save_session(self) -> None:
        # Ungemischte Reihenfolge sichern: Mischen gilt nur bis zum Beenden.
        items, index = self.controller.playlist.unshuffled_state()
        self.settings.set_session_playlist(items, index)

    # ========================================================= Events
    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            # Losgelassene Tasten werden in einem anderen Fenster nicht gemeldet.
            self.keyboard.reset()
            self.controller.stop_scrub()
        super().changeEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir():
                paths.extend(sorted(str(p) for p in path.iterdir() if p.is_file() and is_audio_file(p)))
            else:
                paths.append(str(path))
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        self.analysis.shutdown()
        self.controller.stop()
        self._save_session()
        self.settings.sync()
        self.keyboard.uninstall()
        super().closeEvent(event)
