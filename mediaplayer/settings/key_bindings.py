"""Definition der tastaturbedienbaren Aktionen und ihrer Standardbelegung.

Tasten werden als Qt-"PortableText"-Zeichenkette gespeichert (z. B. "Left",
"Space", "+", "Ctrl+P"). Damit sind die gespeicherten Einstellungen zwischen
Windows und macOS austauschbar.

Die Funktion :func:`key_from_event` erzeugt aus einem Tastendruck genau diese
Zeichenkette. Sie wird sowohl beim Auswerten der Tasten im Player als auch
beim Aufnehmen einer neuen Belegung im Einstellungsdialog verwendet, damit
beide Seiten garantiert dieselbe Schreibweise benutzen.
"""

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

# Interne Aktionsnamen in Anzeigereihenfolge.
BACK = "back"
FORWARD = "forward"
PLAY_PAUSE = "play_pause"
VOLUME_UP = "volume_up"
VOLUME_DOWN = "volume_down"
SPEED_UP = "speed_up"
SPEED_DOWN = "speed_down"
SPEED_RESET = "speed_reset"
RECENT_PLAYLISTS = "recent_playlists"
MARKER_SET = "marker_set"
MARKER_PREVIOUS = "marker_previous"
MARKER_NEXT = "marker_next"
MARKER_DELETE = "marker_delete"

ACTIONS = [
    BACK,
    FORWARD,
    PLAY_PAUSE,
    VOLUME_UP,
    VOLUME_DOWN,
    SPEED_UP,
    SPEED_DOWN,
    SPEED_RESET,
    RECENT_PLAYLISTS,
    MARKER_SET,
    MARKER_PREVIOUS,
    MARKER_NEXT,
    MARKER_DELETE,
]

ACTION_LABELS = {
    BACK: "Zurück / zurückspulen",
    FORWARD: "Weiter / vorspulen",
    PLAY_PAUSE: "Play / Pause",
    VOLUME_UP: "Lauter",
    VOLUME_DOWN: "Leiser",
    SPEED_UP: "Tempo erhöhen (+1 BPM)",
    SPEED_DOWN: "Tempo verringern (−1 BPM)",
    SPEED_RESET: "Originaltempo (1,0x)",
    RECENT_PLAYLISTS: "Zuletzt verwendete Playlists",
    MARKER_SET: "Markierung setzen",
    MARKER_PREVIOUS: "Zur vorherigen Markierung",
    MARKER_NEXT: "Zur nächsten Markierung",
    MARKER_DELETE: "Nächstgelegene Markierung löschen",
}

# Zusätzliche Erklärung für Aktionen mit Sonderverhalten (im Dialog angezeigt).
ACTION_HINTS = {
    BACK: "kurz: Anfang · 2×: vorheriger Titel · halten: spulen",
    FORWARD: "kurz: Ende · 2×: nächster Titel · halten: spulen",
}

# Jede Aktion hat KEYS_PER_ACTION Tastenplätze (Haupttaste, Zweittaste).
# Ein leerer String bedeutet "nicht belegt". Belegungen haben daher immer die
# Form {aktion: [taste_1, taste_2]}.
KEYS_PER_ACTION = 2

DEFAULT_BINDINGS = {
    BACK: ["Left", ""],
    FORWARD: ["Right", ""],
    PLAY_PAUSE: ["Space", ""],
    VOLUME_UP: ["Up", ""],
    VOLUME_DOWN: ["Down", ""],
    SPEED_UP: ["+", ""],
    SPEED_DOWN: ["-", ""],
    SPEED_RESET: ["0", ""],
    RECENT_PLAYLISTS: ["L", ""],
    MARKER_SET: ["M", ""],
    MARKER_PREVIOUS: [",", ""],
    MARKER_NEXT: [".", ""],
    MARKER_DELETE: ["Shift+M", ""],
}


def copy_bindings(bindings: dict[str, list[str]]) -> dict[str, list[str]]:
    """Tiefe Kopie mit genau KEYS_PER_ACTION Plätzen je Aktion."""
    result = {}
    for action in ACTIONS:
        keys = list(bindings.get(action, []))[:KEYS_PER_ACTION]
        result[action] = keys + [""] * (KEYS_PER_ACTION - len(keys))
    return result

# Fest vergebene Tasten, die nicht frei belegt werden können.
RESERVED_KEYS = {
    "Esc": "Vollbild verlassen",
    "F11": "Vollbild umschalten",
}

_MODIFIER_KEYS = {
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Meta,
    Qt.Key.Key_Alt,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock,
    Qt.Key.Key_Super_L,
    Qt.Key.Key_Super_R,
    Qt.Key.Key_Hyper_L,
    Qt.Key.Key_Hyper_R,
    Qt.Key.Key_unknown,
}


def _is_symbol_key(key: int) -> bool:
    """True für druckbare ASCII-Zeichen, die keine Buchstaben sind.

    Bei diesen Tasten steckt die Umschalttaste bereits im Zeichen selbst
    (z. B. "+" auf US-Tastaturen = Umschalt + "="). Damit "+" auf deutschen
    und US-Tastaturen gleich erkannt wird, wird Shift hier ignoriert.
    """
    return 0x21 <= key <= 0x7E and not (Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value)


def key_from_event(event: QKeyEvent) -> str:
    """Wandelt einen Tastendruck in eine normalisierte Tastenbezeichnung um.

    - Reine Modifikatortasten liefern "".
    - Der Ziffernblock wird wie die normale Tastatur behandelt
      (Ziffernblock-"+" entspricht "+").
    - Bei Sonderzeichen wird Shift ignoriert (siehe :func:`_is_symbol_key`).
    """
    key = event.key()
    try:
        qt_key = Qt.Key(key)
    except ValueError:
        return ""
    if qt_key in _MODIFIER_KEYS:
        return ""

    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    if _is_symbol_key(key):
        mods &= ~Qt.KeyboardModifier.ShiftModifier

    sequence = QKeySequence(QKeyCombination(mods, qt_key))
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


_DISPLAY_NAMES = {
    "Left": "Pfeil links",
    "Right": "Pfeil rechts",
    "Up": "Pfeil hoch",
    "Down": "Pfeil runter",
    "Space": "Leertaste",
    "Return": "Eingabe",
    "Enter": "Eingabe (Ziffernblock)",
    "Backspace": "Rücktaste",
    "Del": "Entf",
    "Ins": "Einfg",
    "PgUp": "Bild hoch",
    "PgDown": "Bild runter",
    "Home": "Pos1",
    "End": "Ende",
    "Tab": "Tab",
}

_MODIFIER_NAMES = {
    "Ctrl": "Strg",
    "Shift": "Umschalt",
    "Alt": "Alt",
    "Meta": "Meta",
}


def display_key(key: str) -> str:
    """Lesbare deutsche Bezeichnung für eine gespeicherte Tastenbezeichnung."""
    if not key:
        return "– nicht belegt –"
    # Sonderfall: die Taste "+" selbst bzw. "Strg++".
    if key.endswith("++"):
        parts = key[:-2].split("+") + ["+"]
    elif key == "+":
        parts = ["+"]
    else:
        parts = key.split("+")
    *mods, main = parts
    names = [_MODIFIER_NAMES.get(m, m) for m in mods]
    names.append(_DISPLAY_NAMES.get(main, main))
    return " + ".join(names) if len(names) > 1 else names[0]
