"""Dialog „Playlist laden“: zuletzt verwendete Playlists und Dateiauswahl in einem.

Oben zwei Umschalter – „Zuletzt verwendet“ und „Datei auswählen“ –, darunter
die jeweilige Seite. Umschalten per Antippen oder mit der Tabulatortaste.
Beide Seiten sind die bekannten Dialoge (``RecentPlaylistsDialog``,
``FileBrowserDialog``) in eingebetteter Form; wählt man auf einer Seite eine
Playlist, schließt sich der ganze Dialog.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from ..playlist import PLAYLIST_EXTENSIONS
from .file_browser import FileBrowserDialog, Mode
from .recent_playlists_dialog import RecentPlaylistsDialog
from .style import px
from .widgets import size_dialog

RECENT_PAGE = 0
FILES_PAGE = 1


class LoadPlaylistDialog(QDialog):
    def __init__(
        self,
        recent_paths: list[str],
        start_dir: str,
        page: int | None = None,
        toggle_keys: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Playlist laden")
        self.setModal(True)
        self._chosen = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(32), px(26), px(32), px(26))
        layout.setSpacing(px(16))

        head = QHBoxLayout()
        head.setSpacing(px(14))
        heading = QLabel("Playlist laden")
        heading.setObjectName("dialogTitle")
        head.addWidget(heading)
        head.addStretch(1)
        self.recent_tab = self._tab("Zuletzt verwendet")
        self.files_tab = self._tab("Datei auswählen")
        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        self._tabs.addButton(self.recent_tab, RECENT_PAGE)
        self._tabs.addButton(self.files_tab, FILES_PAGE)
        self._tabs.idClicked.connect(self.set_page)
        head.addWidget(self.recent_tab)
        head.addWidget(self.files_tab)
        layout.addLayout(head)

        self.recent = RecentPlaylistsDialog(recent_paths, toggle_keys, self, embedded=True)
        self.files = FileBrowserDialog(
            Mode.OPEN_FILE, "Playlist laden", start_dir, PLAYLIST_EXTENSIONS, "Laden", self, embedded=True
        )
        self.stack = QStackedWidget()
        self.stack.addWidget(self.recent)
        self.stack.addWidget(self.files)
        layout.addWidget(self.stack, 1)

        # Ergebnis der Seiten übernehmen: Laden → Dialog annehmen, Schließen/Abbrechen → verwerfen.
        self.recent.accepted.connect(lambda: self._finish(self.recent.chosen_path()))
        self.files.accepted.connect(
            lambda: self._finish(self.files.selected_paths()[0] if self.files.selected_paths() else "")
        )
        self.recent.rejected.connect(self.reject)
        self.files.rejected.connect(self.reject)

        size_dialog(self, parent, 0.9, fullscreen_like_parent=True)
        if page is None:
            page = RECENT_PAGE if recent_paths else FILES_PAGE
        self.set_page(page)
        QApplication.instance().installEventFilter(self)

    # ----------------------------------------------------------- Ergebnis
    def chosen_path(self) -> str:
        return self._chosen

    def remaining_recent_paths(self) -> list[str]:
        """Liste „Zuletzt“ nach eventuellem Entfernen von Einträgen."""
        return self.recent.remaining_paths()

    def current_directory(self) -> str | None:
        return self.files.current_directory()

    # ----------------------------------------------------------- Seiten
    def page(self) -> int:
        return self.stack.currentIndex()

    def set_page(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self._tabs.button(page).setChecked(True)
        # Seiten bleiben sichtbar, auch nachdem eine Seite done() aufgerufen hat.
        widget = self.stack.currentWidget()
        widget.show()
        widget.list.setFocus()

    def _finish(self, path: str) -> None:
        if path:
            self._chosen = path
            self.accept()
        else:
            self.reject()

    def done(self, result: int) -> None:
        QApplication.instance().removeEventFilter(self)
        super().done(result)

    def eventFilter(self, obj, event) -> bool:
        # Tabulatortaste wechselt die Seite (statt den Fokus zu verschieben).
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
            and obj is not None
            and hasattr(obj, "window")
            and obj.window() is self
        ):
            self.set_page(FILES_PAGE if self.page() == RECENT_PAGE else RECENT_PAGE)
            return True
        return super().eventFilter(obj, event)

    def _tab(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setMinimumHeight(px(64))
        button.setAutoDefault(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button
