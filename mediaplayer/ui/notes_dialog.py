"""Dialog zum Schreiben einer Notiz zu einem Titel."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .style import px
from .widgets import ElidedLabel, size_dialog


class NotesDialog(QDialog):
    """Großes Textfeld für die Notiz; „Speichern“ oder Strg+Eingabe übernimmt.

    Escape bzw. „Abbrechen“ verwirft die Änderungen. Ein leerer Text löscht
    die Notiz beim Speichern.
    """

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Notiz – {title}")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(32), px(26), px(32), px(26))
        layout.setSpacing(px(16))

        heading = QLabel("Notiz")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        song = ElidedLabel(title)
        song.setObjectName("pathLabel")
        layout.addWidget(song)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("notesEditor")
        self.editor.setPlainText(text)
        self.editor.setPlaceholderText("z. B. Tonart, Capo, Einsätze, Text-Hänger, Tempo-Hinweise …")
        self.editor.moveCursor(self.editor.textCursor().MoveOperation.End)
        layout.addWidget(self.editor, 1)

        hint = QLabel("Strg + Eingabe speichert · Escape bricht ab")
        hint.setObjectName("sectionLabel")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(px(14))
        self.clear_button = self._button("Leeren", self.editor.clear)
        self.clear_button.setToolTip("Text entfernen (nach dem Speichern ist die Notiz gelöscht)")
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self._button("Abbrechen", self.reject))
        self.save_button = self._button("Speichern", self.accept)
        self.save_button.setObjectName("primaryButton")
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        for key in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(key), self, self.accept)

        size_dialog(self, parent, 0.7, fullscreen_like_parent=False)
        self.editor.setFocus()

    def text(self) -> str:
        return self.editor.toPlainText().strip()

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(px(64))
        button.setAutoDefault(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _=False: slot())
        return button
