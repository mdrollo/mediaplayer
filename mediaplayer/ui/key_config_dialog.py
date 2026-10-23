"""Dialog zum Konfigurieren der Tastaturbelegung (zwei Tasten je Funktion)."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..settings.key_bindings import (
    ACTION_HINTS,
    ACTION_LABELS,
    ACTIONS,
    DEFAULT_BINDINGS,
    KEYS_PER_ACTION,
    RESERVED_KEYS,
    copy_bindings,
    display_key,
    key_from_event,
)
from .style import px
from .widgets import size_dialog


class KeyCaptureButton(QPushButton):
    """Zeigt eine Taste an; nach dem Anklicken wird der nächste Tastendruck aufgenommen.

    Während der Aufnahme werden *alle* Tasten abgefangen (auch Tab, Leertaste
    und Pfeiltasten). Escape bricht die Aufnahme ab.
    """

    captured = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._capturing = False
        self._key = ""
        self.setMinimumWidth(px(210))
        self.setToolTip("Klicken und dann die neue Taste drücken")
        self.clicked.connect(self.start_capture)
        self._show_key()

    def set_key(self, key: str) -> None:
        self._key = key
        if not self._capturing:
            self._show_key()

    def _show_key(self) -> None:
        self.setText(display_key(self._key) if self._key else "(frei)")

    def start_capture(self) -> None:
        self._capturing = True
        self.setText("Taste drücken …")
        self.setFocus()
        self.grabKeyboard()

    def stop_capture(self) -> None:
        if self._capturing:
            self._capturing = False
            self.releaseKeyboard()
            self._show_key()

    def event(self, event: QEvent) -> bool:
        if self._capturing and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            if event.type() == QEvent.Type.KeyPress:
                self._handle_key(event)
            event.accept()
            return True
        if self._capturing and event.type() == QEvent.Type.FocusOut:
            self.stop_capture()
        return super().event(event)

    def _handle_key(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_Escape:
            self.stop_capture()
            return
        key = key_from_event(event)
        if not key:
            return  # nur Modifikator gedrückt – auf die eigentliche Taste warten
        self.stop_capture()
        self.captured.emit(key)


class KeyConfigDialog(QDialog):
    def __init__(self, bindings: dict[str, list[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tastaturbelegung")
        self.setModal(True)
        size_dialog(self, parent, 0.9, fullscreen_like_parent=False)
        self._bindings = copy_bindings(bindings)
        # _buttons[action][slot] -> KeyCaptureButton
        self._buttons: dict[str, list[KeyCaptureButton]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(28), px(24), px(28), px(24))
        layout.setSpacing(px(16))

        intro = QLabel(
            "Jede Funktion kann zwei Tasten haben. Auf eine Taste klicken und "
            "anschließend die neue Taste drücken; „✕“ entfernt die Belegung. "
            "Escape bricht die Aufnahme ab."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        headers = ["Funktion"] + [f"Taste {slot + 1}" for slot in range(KEYS_PER_ACTION)]
        self.table = QTableWidget(len(ACTIONS), len(headers), self)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        for row, action in enumerate(ACTIONS):
            label = ACTION_LABELS[action]
            hint = ACTION_HINTS.get(action)
            self.table.setItem(row, 0, QTableWidgetItem(f"{label}\n{hint}" if hint else label))
            self._buttons[action] = []
            for slot in range(KEYS_PER_ACTION):
                self.table.setCellWidget(row, slot + 1, self._make_slot_widget(action, slot))
        layout.addWidget(self.table, 1)

        self.message = QLabel("")
        self.message.setObjectName("messageLabel")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        reserved = ", ".join(f"{display_key(k)} = {v}" for k, v in RESERVED_KEYS.items())
        fixed = QLabel(f"Fest belegt: {reserved}")
        fixed.setObjectName("sectionLabel")
        layout.addWidget(fixed)

        buttons = QHBoxLayout()
        defaults = QPushButton("Standard wiederherstellen")
        defaults.clicked.connect(self._restore_defaults)
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Speichern")
        save.clicked.connect(self.accept)
        for b in (defaults, cancel, save):
            b.setAutoDefault(False)
            b.setDefault(False)
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._refresh()

    def _make_slot_widget(self, action: str, slot: int) -> QWidget:
        container = QWidget(self.table)
        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(6)

        capture = KeyCaptureButton(container)
        capture.captured.connect(lambda key, a=action, s=slot: self._assign(a, s, key))
        row_layout.addWidget(capture, 1)

        clear = QPushButton("✕", container)
        clear.setToolTip("Belegung entfernen")
        clear.setFixedWidth(px(60))
        clear.setAutoDefault(False)
        clear.clicked.connect(lambda _=False, a=action, s=slot: self._clear(a, s))
        row_layout.addWidget(clear)

        self._buttons[action].append(capture)
        return container

    def capture_button(self, action: str, slot: int) -> KeyCaptureButton:
        return self._buttons[action][slot]

    def bindings(self) -> dict[str, list[str]]:
        return copy_bindings(self._bindings)

    def _assign(self, action: str, slot: int, key: str) -> None:
        if key in RESERVED_KEYS:
            self.message.setText(
                f"{display_key(key)} ist fest belegt ({RESERVED_KEYS[key]}) "
                "und kann nicht zugewiesen werden."
            )
            return

        # Eine Taste darf nur an einer Stelle vorkommen.
        notes = []
        for other, keys in self._bindings.items():
            for other_slot, other_key in enumerate(keys):
                if other_key != key or (other, other_slot) == (action, slot):
                    continue
                keys[other_slot] = ""
                if other != action:
                    notes.append(
                        f"{display_key(key)} war „{ACTION_LABELS[other]}“ zugeordnet – "
                        "dort wurde sie entfernt."
                    )
        self._bindings[action][slot] = key
        self.message.setText(" ".join(notes))
        self._refresh()

    def _clear(self, action: str, slot: int) -> None:
        self._bindings[action][slot] = ""
        self.message.setText("")
        self._refresh()

    def _restore_defaults(self) -> None:
        self._bindings = copy_bindings(DEFAULT_BINDINGS)
        self.message.setText("Standardbelegung wiederhergestellt (noch nicht gespeichert).")
        self._refresh()

    def _refresh(self) -> None:
        for action in ACTIONS:
            for slot, button in enumerate(self._buttons[action]):
                button.set_key(self._bindings[action][slot])

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Enter soll den Dialog nicht versehentlich schließen.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)
