"""Eigener Dateidialog in der großen, touch-tauglichen Darstellung des Players.

Drei Modi:

* ``OPEN_FILES`` – mehrere Dateien auswählen (Antippen schaltet die Auswahl um,
  die Auswahl bleibt beim Ordnerwechsel erhalten). Zusätzlich kann ein ganzer
  Ordner samt Unterordnern übernommen werden.
* ``OPEN_FILE``  – genau eine Datei öffnen.
* ``SAVE_FILE``  – Ordner wählen und Dateinamen eingeben.

Ordner öffnen sich mit einem einfachen Antippen/Klick.
"""

import functools
import os
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import (
    QCollator,
    QDir,
    QEvent,
    QItemSelectionModel,
    QStandardPaths,
    QStorageInfo,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from .widgets import IS_DIR_ROLE, PATH_ROLE, SUBTITLE_ROLE, BigListWidget, size_dialog


class Mode(Enum):
    OPEN_FILES = auto()
    OPEN_FILE = auto()
    SAVE_FILE = auto()


def _natural_sort_key():
    collator = QCollator()
    collator.setNumericMode(True)
    collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return functools.cmp_to_key(collator.compare)


_SORT_KEY = _natural_sort_key()


def _format_size(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB".replace(".", ",")
    return f"{max(1, size // 1000)} KB"


def collect_files(folder: str, extensions: set[str]) -> list[str]:
    """Alle passenden Dateien eines Ordners inkl. Unterordnern, natürlich sortiert."""
    result = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted((d for d in dirs if not d.startswith(".")), key=_SORT_KEY)
        for name in sorted(files, key=_SORT_KEY):
            if Path(name).suffix.lower() in extensions:
                result.append(str(Path(root) / name))
    return result


class FileBrowserDialog(QDialog):
    def __init__(
        self,
        mode: Mode,
        title: str,
        start_dir: str,
        extensions: set[str],
        accept_label: str,
        parent=None,
        default_name: str = "",
        default_suffix: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._mode = mode
        self._extensions = {e.lower() for e in extensions}
        self._default_suffix = default_suffix
        self._dir: str | None = None  # None = Laufwerksübersicht
        self._selected: dict[str, None] = {}  # geordnete Menge (OPEN_FILES)
        self._result: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(16)

        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)

        # --- Orte
        places = QHBoxLayout()
        places.setSpacing(12)
        self.up_button = self._button("▲  Nach oben", self.go_up, "Übergeordneter Ordner (Rücktaste)")
        places.addWidget(self.up_button)
        for label, location in (
            ("Musik", QStandardPaths.StandardLocation.MusicLocation),
            ("Persönlicher Ordner", QStandardPaths.StandardLocation.HomeLocation),
            ("Desktop", QStandardPaths.StandardLocation.DesktopLocation),
            ("Downloads", QStandardPaths.StandardLocation.DownloadLocation),
        ):
            path = QStandardPaths.writableLocation(location)
            if path and Path(path).is_dir():
                places.addWidget(self._button(label, lambda _=False, p=path: self.navigate(p)))
        places.addWidget(self._button("Laufwerke", lambda: self.navigate(None)))
        places.addStretch(1)
        layout.addLayout(places)

        self.path_label = QLabel("")
        self.path_label.setObjectName("pathLabel")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        # --- Liste
        self.list = BigListWidget(self)
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
            if mode == Mode.OPEN_FILES
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.installEventFilter(self)
        layout.addWidget(self.list, 1)

        # --- Dateiname (Speichern)
        self.name_edit: QLineEdit | None = None
        if mode == Mode.SAVE_FILE:
            name_row = QHBoxLayout()
            name_label = QLabel("Dateiname:")
            name_row.addWidget(name_label)
            self.name_edit = QLineEdit(default_name)
            self.name_edit.textChanged.connect(self._update_buttons)
            self.name_edit.returnPressed.connect(self._accept)
            name_row.addWidget(self.name_edit, 1)
            layout.addLayout(name_row)

        self.message = QLabel("")
        self.message.setObjectName("messageLabel")
        layout.addWidget(self.message)

        # --- Schaltflächen
        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        if mode == Mode.OPEN_FILES:
            buttons.addWidget(self._button("Alle auswählen", self._select_all))
            buttons.addWidget(self._button("Auswahl aufheben", self._clear_selection))
            buttons.addWidget(self._button(
                "Ganzer Ordner", self._accept_folder, "Alle Titel dieses Ordners inkl. Unterordnern übernehmen"
            ))
        buttons.addStretch(1)
        cancel = self._button("Abbrechen", self.reject)
        buttons.addWidget(cancel)
        self.accept_button = self._button(accept_label, self._accept)
        self.accept_button.setObjectName("primaryButton")
        self._accept_label = accept_label
        buttons.addWidget(self.accept_button)
        layout.addLayout(buttons)

        size_dialog(self, parent, 0.9, fullscreen_like_parent=True)

        start = start_dir if start_dir and Path(start_dir).is_dir() else QDir.homePath()
        self.navigate(start)
        if self.name_edit is not None:
            self.name_edit.setFocus()
            self.name_edit.selectAll()
        else:
            self.list.setFocus()

    # ----------------------------------------------------------- Ergebnis
    def selected_paths(self) -> list[str]:
        return list(self._result)

    @classmethod
    def get_open_files(cls, parent, title, start_dir, extensions, accept_label="Hinzufügen") -> list[str]:
        dialog = cls(Mode.OPEN_FILES, title, start_dir, extensions, accept_label, parent)
        return dialog.selected_paths() if dialog.exec() else []

    @classmethod
    def get_open_file(cls, parent, title, start_dir, extensions, accept_label="Öffnen") -> str:
        dialog = cls(Mode.OPEN_FILE, title, start_dir, extensions, accept_label, parent)
        return dialog.selected_paths()[0] if dialog.exec() and dialog.selected_paths() else ""

    @classmethod
    def get_save_file(
        cls, parent, title, start_dir, extensions, default_name, default_suffix, accept_label="Speichern"
    ) -> str:
        dialog = cls(
            Mode.SAVE_FILE, title, start_dir, extensions, accept_label, parent,
            default_name=default_name, default_suffix=default_suffix,
        )
        return dialog.selected_paths()[0] if dialog.exec() and dialog.selected_paths() else ""

    def current_directory(self) -> str | None:
        return self._dir

    # ---------------------------------------------------------- Navigation
    def navigate(self, directory: str | None) -> None:
        if directory is not None and not QDir(directory).isReadable():
            self.message.setText("Dieser Ordner kann nicht geöffnet werden.")
            return
        self.message.setText("")
        self._dir = None if directory is None else QDir(directory).absolutePath()
        self._populate()

    def go_up(self) -> None:
        if self._dir is None:
            return
        qdir = QDir(self._dir)
        if qdir.isRoot() or not qdir.cdUp():
            self.navigate(None)
        else:
            self.navigate(qdir.absolutePath())

    def _populate(self) -> None:
        style = self.style()
        folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        drive_icon = style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)
        file_icon = style.standardIcon(
            QStyle.StandardPixmap.SP_MediaVolume
            if ".mp3" in self._extensions
            else QStyle.StandardPixmap.SP_FileDialogDetailedView
        )

        self.list.blockSignals(True)
        self.list.clear()

        if self._dir is None:
            self.path_label.setText("Laufwerke")
            self.up_button.setEnabled(False)
            for volume in QStorageInfo.mountedVolumes():
                if not (volume.isValid() and volume.isReady()):
                    continue
                root = volume.rootPath()
                name = volume.displayName() or root
                label = name if name == root else f"{name}  ({QDir.toNativeSeparators(root)})"
                self._add_entry(label, "Laufwerk", root, True, drive_icon)
        else:
            self.path_label.setText(QDir.toNativeSeparators(self._dir))
            self.up_button.setEnabled(True)
            qdir = QDir(self._dir)
            dirs = qdir.entryInfoList(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot, QDir.SortFlag.NoSort)
            files = qdir.entryInfoList(QDir.Filter.Files, QDir.SortFlag.NoSort)
            for info in sorted(dirs, key=lambda i: _SORT_KEY(i.fileName())):
                self._add_entry(info.fileName(), "Ordner", info.absoluteFilePath(), True, folder_icon)
            matching = [i for i in files if f".{i.suffix().lower()}" in self._extensions]
            for info in sorted(matching, key=lambda i: _SORT_KEY(i.fileName())):
                self._add_entry(
                    info.fileName(), _format_size(info.size()), info.absoluteFilePath(), False, file_icon
                )
            if self.list.count() == 0:
                self.message.setText("Dieser Ordner enthält keine passenden Dateien.")

        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.list.scrollToTop()
        self._update_buttons()

    def _add_entry(self, title, subtitle, path, is_dir, icon) -> None:
        item = QListWidgetItem(icon, title)
        item.setData(SUBTITLE_ROLE, subtitle)
        item.setData(PATH_ROLE, path)
        item.setData(IS_DIR_ROLE, is_dir)
        if is_dir:
            # Ordner werden geöffnet, nicht ausgewählt.
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.list.addItem(item)
        if not is_dir and path in self._selected:
            item.setSelected(True)

    # ------------------------------------------------------------ Auswahl
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(IS_DIR_ROLE):
            # Verzögert, weil navigate() die Liste samt angeklicktem Eintrag neu aufbaut.
            path = item.data(PATH_ROLE)
            QTimer.singleShot(0, lambda: self.navigate(path))
        elif self.name_edit is not None:
            self.name_edit.setText(item.text())

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if not item.data(IS_DIR_ROLE) and self._mode != Mode.OPEN_FILES:
            item.setSelected(True)
            self._accept()

    def _on_selection_changed(self) -> None:
        if self._mode == Mode.OPEN_FILES:
            visible = {
                self.list.item(i).data(PATH_ROLE): self.list.item(i).isSelected()
                for i in range(self.list.count())
                if not self.list.item(i).data(IS_DIR_ROLE)
            }
            for path, selected in visible.items():
                if selected:
                    self._selected.setdefault(path, None)
                else:
                    self._selected.pop(path, None)
        self._update_buttons()

    def _select_all(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.data(IS_DIR_ROLE):
                item.setSelected(True)

    def _clear_selection(self) -> None:
        self._selected.clear()
        self.list.clearSelection()
        self._update_buttons()

    def _update_buttons(self) -> None:
        if self._mode == Mode.OPEN_FILES:
            count = len(self._selected)
            self.accept_button.setEnabled(count > 0)
            self.accept_button.setText(f"{self._accept_label} ({count})" if count else self._accept_label)
        elif self._mode == Mode.OPEN_FILE:
            self.accept_button.setEnabled(bool(self.list.selectedItems()))
        else:
            name = self.name_edit.text().strip() if self.name_edit else ""
            self.accept_button.setEnabled(bool(name) and self._dir is not None)

    # ----------------------------------------------------------- Abschluss
    def _accept(self) -> None:
        if self._mode == Mode.OPEN_FILES:
            if not self._selected:
                return
            self._result = sorted(self._selected, key=_SORT_KEY)
        elif self._mode == Mode.OPEN_FILE:
            items = [i for i in self.list.selectedItems() if not i.data(IS_DIR_ROLE)]
            if not items:
                return
            self._result = [items[0].data(PATH_ROLE)]
        else:
            path = self._save_path()
            if path is None:
                return
            if Path(path).exists():
                answer = QMessageBox.question(
                    self, "Datei ersetzen?", f"„{Path(path).name}“ existiert bereits. Ersetzen?"
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self._result = [path]
        self.accept()

    def _save_path(self) -> str | None:
        if self._dir is None or self.name_edit is None:
            return None
        name = self.name_edit.text().strip()
        if not name:
            return None
        if any(ch in name for ch in '\\/:*?"<>|'):
            self.message.setText('Der Dateiname darf keines dieser Zeichen enthalten: \\ / : * ? " < > |')
            return None
        if Path(name).suffix.lower() not in self._extensions:
            name += self._default_suffix
        return str(Path(self._dir) / name)

    def _accept_folder(self) -> None:
        if self._dir is None:
            return
        files = collect_files(self._dir, self._extensions)
        if not files and not self._selected:
            self.message.setText("In diesem Ordner gibt es keine passenden Dateien.")
            return
        combined = dict.fromkeys(sorted(self._selected, key=_SORT_KEY))
        combined.update(dict.fromkeys(files))
        self._result = list(combined)
        self.accept()

    # ------------------------------------------------------------ Tastatur
    def eventFilter(self, obj, event) -> bool:
        if obj is self.list and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Backspace:
                self.go_up()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item is not None and item.data(IS_DIR_ROLE):
                    self.navigate(item.data(PATH_ROLE))
                elif self._mode == Mode.OPEN_FILES:
                    if not self._selected and item is not None:
                        item.setSelected(True)
                    self._accept()
                elif item is not None:
                    item.setSelected(True)
                    self._accept()
                return True
        return super().eventFilter(obj, event)

    def _button(self, text: str, slot, tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(64)
        button.setAutoDefault(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button
