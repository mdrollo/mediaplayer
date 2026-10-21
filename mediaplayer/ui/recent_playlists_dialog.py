"""Schnellauswahl der zuletzt verwendeten Playlists."""

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from ..settings.key_bindings import key_from_event
from .widgets import DIMMED_ROLE, PATH_ROLE, SUBTITLE_ROLE, BigListWidget, size_dialog


class RecentPlaylistsDialog(QDialog):
    """Liste der zuletzt geladenen/gespeicherten Playlists.

    Bedienung: antippen + „Laden“, Doppelklick, Eingabetaste oder die Ziffern
    1–9 laden direkt. Die Taste, mit der das Panel geöffnet wurde
    (``toggle_keys``), schließt es wieder.
    """

    def __init__(self, paths: list[str], toggle_keys: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zuletzt verwendete Playlists")
        self.setModal(True)
        self._paths = list(paths)
        self._toggle_keys = {k for k in (toggle_keys or []) if k}
        self._chosen = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(16)

        heading = QLabel("Zuletzt verwendete Playlists")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)

        self.list = BigListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _item: self._load())
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.installEventFilter(self)
        layout.addWidget(self.list, 1)

        self.empty_label = QLabel("Noch keine Playlists geladen oder gespeichert.")
        self.empty_label.setObjectName("sectionLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        hint = QLabel("Ziffern 1–9 laden direkt · Eingabe lädt die markierte Playlist")
        hint.setObjectName("sectionLabel")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        self.remove_button = self._button("Aus Liste entfernen", self._remove)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self._button("Schließen", self.reject))
        self.load_button = self._button("Laden", self._load)
        self.load_button.setObjectName("primaryButton")
        buttons.addWidget(self.load_button)
        layout.addLayout(buttons)

        size_dialog(self, parent, 0.7, fullscreen_like_parent=False)
        self._populate()
        self.list.setFocus()

    def chosen_path(self) -> str:
        return self._chosen

    def remaining_paths(self) -> list[str]:
        """Liste nach eventuellem Entfernen von Einträgen."""
        return list(self._paths)

    def _populate(self) -> None:
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.list.clear()
        for number, path in enumerate(self._paths, start=1):
            exists = Path(path).is_file()
            prefix = f"{number}   " if number <= 9 else "     "
            item = QListWidgetItem(icon, f"{prefix}{Path(path).stem}")
            folder = str(Path(path).parent)
            item.setData(SUBTITLE_ROLE, folder if exists else f"{folder}  ·  nicht gefunden")
            item.setData(PATH_ROLE, path)
            item.setData(DIMMED_ROLE, not exists)  # sichtbar und entfernbar, aber nicht ladbar
            self.list.addItem(item)
        first_loadable = next(
            (i for i in range(self.list.count()) if self._is_loadable(self.list.item(i))), -1
        )
        if first_loadable >= 0:
            self.list.setCurrentRow(first_loadable)
        self.empty_label.setVisible(not self._paths)
        self._update_buttons()

    @staticmethod
    def _is_loadable(item) -> bool:
        return item is not None and Path(item.data(PATH_ROLE)).is_file()

    def _update_buttons(self) -> None:
        item = self.list.currentItem() if self.list.selectedItems() else None
        self.load_button.setEnabled(self._is_loadable(item))
        self.remove_button.setEnabled(item is not None)

    def _load(self, row: int | None = None) -> None:
        item = self.list.item(row) if row is not None else self.list.currentItem()
        if not self._is_loadable(item):
            return
        self._chosen = item.data(PATH_ROLE)
        self.accept()

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self._paths.remove(item.data(PATH_ROLE))
        self._populate()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.list and event.type() == QEvent.Type.KeyPress:
            if key_from_event(event) in self._toggle_keys:
                self.reject()
                return True
            key = event.key()
            if Qt.Key.Key_1.value <= key <= Qt.Key.Key_9.value:
                row = key - Qt.Key.Key_1.value
                if row < self.list.count():
                    self._load(row)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._load()
                return True
            if key == Qt.Key.Key_Delete:
                self._remove()
                return True
        return super().eventFilter(obj, event)

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(64)
        button.setAutoDefault(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _=False: slot())
        return button
