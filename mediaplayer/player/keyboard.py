"""Tastatursteuerung.

Aufbau in zwei klar getrennten Schichten:

1. **Belegung** (``KeyboardController``): ordnet einer gedrückten Taste über die
   konfigurierbare Tabelle eine Aktion zu ("Leertaste" → ``play_pause``).
   Jede Aktion kann zwei Tasten haben; beide verhalten sich identisch.
2. **Gestenerkennung** (``TapHoldGesture``): nur für die Aktionen ``back`` und
   ``forward``. Sie unterscheidet kurzen Druck, Doppeldruck und Gedrückthalten,
   unabhängig davon, *welche* Taste der Aktion zugeordnet ist.

Dadurch kollidieren frei wählbare Tasten nicht mit der Sonderlogik: Wird
"Zurück" z. B. auf "J" gelegt, verhält sich "J" genau wie vorher der linke Pfeil.

Ereignisse, die der Controller ausgibt (Signal ``triggered``):

=================  ==================================================
``play_pause``      einfache Aktionen, direkt aus der Belegung
``volume_up`` …
``back_single``     kurzer Druck auf "Zurück"  → Titelanfang
``back_double``     Doppeldruck "Zurück"       → vorheriger Titel
``back_hold_start`` / ``back_hold_end``  → Zurückspulen starten/beenden
``forward_*``       entsprechend für "Weiter"
=================  ==================================================
"""

from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

from ..settings.key_bindings import (
    BACK,
    FORWARD,
    SPEED_DOWN,
    SPEED_UP,
    VOLUME_DOWN,
    VOLUME_UP,
    key_from_event,
)


@dataclass(frozen=True)
class GestureTiming:
    """Zeitfenster der Gestenerkennung in Millisekunden – hier anpassen."""

    # Ab dieser Haltedauer gilt ein Tastendruck als "gehalten" (Spulen).
    hold_ms: int = 400
    # Nach dem Loslassen so lange auf einen zweiten Druck warten.
    # Ein kurzer Einzeldruck wird erst nach Ablauf dieser Zeit ausgeführt.
    double_press_ms: int = 300


DEFAULT_TIMING = GestureTiming()

# Aktionen mit Sonderlogik (kurz / doppelt / halten).
GESTURE_ACTIONS = (BACK, FORWARD)

# Aktionen, die beim Gedrückthalten per Tasten-Wiederholung mehrfach auslösen.
REPEATABLE_ACTIONS = {VOLUME_UP, VOLUME_DOWN, SPEED_UP, SPEED_DOWN}


class _State(Enum):
    IDLE = auto()
    FIRST_DOWN = auto()      # erster Druck, Halte-Timer läuft
    WAIT_SECOND = auto()     # losgelassen, warte auf möglichen zweiten Druck
    HOLDING = auto()         # gehalten → Spulen aktiv
    SECOND_DOWN = auto()     # Doppeldruck erkannt, warte auf Loslassen


class TapHoldGesture(QObject):
    """Zustandsautomat für eine Taste: kurz, doppelt oder gehalten.

    ::

        IDLE --press--> FIRST_DOWN --hold_ms--> HOLDING --release--> IDLE (hold_end)
                             |
                          release
                             v
                        WAIT_SECOND --double_press_ms--> IDLE (single)
                             |
                           press
                             v
                        SECOND_DOWN (double) --release--> IDLE

    Automatische Tastenwiederholungen des Betriebssystems müssen vom Aufrufer
    herausgefiltert werden (``QKeyEvent.isAutoRepeat()``).
    """

    single = Signal()
    double = Signal()
    holdStarted = Signal()
    holdEnded = Signal()

    def __init__(self, timing: GestureTiming = DEFAULT_TIMING, parent: QObject | None = None):
        super().__init__(parent)
        self._state = _State.IDLE

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._on_hold_timeout)

        self._double_timer = QTimer(self)
        self._double_timer.setSingleShot(True)
        self._double_timer.timeout.connect(self._on_double_timeout)

        self.set_timing(timing)

    def set_timing(self, timing: GestureTiming) -> None:
        self._hold_timer.setInterval(timing.hold_ms)
        self._double_timer.setInterval(timing.double_press_ms)

    @property
    def is_down(self) -> bool:
        return self._state in (_State.FIRST_DOWN, _State.HOLDING, _State.SECOND_DOWN)

    def press(self) -> None:
        if self._state == _State.IDLE:
            self._state = _State.FIRST_DOWN
            self._hold_timer.start()
        elif self._state == _State.WAIT_SECOND:
            self._double_timer.stop()
            self._state = _State.SECOND_DOWN
            self.double.emit()
        # In allen anderen Zuständen ist die Taste bereits unten: ignorieren.

    def release(self) -> None:
        if self._state == _State.FIRST_DOWN:
            self._hold_timer.stop()
            self._state = _State.WAIT_SECOND
            self._double_timer.start()
        elif self._state == _State.HOLDING:
            self._state = _State.IDLE
            self.holdEnded.emit()
        elif self._state == _State.SECOND_DOWN:
            self._state = _State.IDLE

    def reset(self) -> None:
        """Abbrechen, z. B. wenn das Fenster den Fokus verliert."""
        was_holding = self._state == _State.HOLDING
        self._hold_timer.stop()
        self._double_timer.stop()
        self._state = _State.IDLE
        if was_holding:
            self.holdEnded.emit()

    def _on_hold_timeout(self) -> None:
        if self._state == _State.FIRST_DOWN:
            self._state = _State.HOLDING
            self.holdStarted.emit()

    def _on_double_timeout(self) -> None:
        if self._state == _State.WAIT_SECOND:
            self._state = _State.IDLE
            self.single.emit()


class KeyboardController(QObject):
    """Anwendungsweiter Tastatur-Filter für das Hauptfenster.

    Der Filter wird an der ``QApplication`` installiert, damit Pfeiltasten und
    Leertaste auch dann beim Player ankommen, wenn z. B. die Playlist den
    Fokus hat (die Liste würde Pfeiltasten sonst selbst verbrauchen).
    Tastendrücke in anderen Fenstern (Dialoge) bleiben unberührt.
    """

    triggered = Signal(str)

    def __init__(
        self,
        window: QWidget,
        bindings: dict[str, list[str]],
        timing: GestureTiming = DEFAULT_TIMING,
        parent: QObject | None = None,
    ):
        super().__init__(parent or window)
        self._window = window
        self._key_to_action: dict[str, str] = {}
        # Für Gestentasten: Qt-Tastencode → Aktion (für das Loslassen,
        # bei dem sich gedrückte Modifikatoren geändert haben können).
        self._down_keys: dict[int, str] = {}
        self._enabled = True

        self._gestures: dict[str, TapHoldGesture] = {}
        for action in GESTURE_ACTIONS:
            gesture = TapHoldGesture(timing, self)
            gesture.single.connect(lambda a=action: self.triggered.emit(f"{a}_single"))
            gesture.double.connect(lambda a=action: self.triggered.emit(f"{a}_double"))
            gesture.holdStarted.connect(lambda a=action: self.triggered.emit(f"{a}_hold_start"))
            gesture.holdEnded.connect(lambda a=action: self.triggered.emit(f"{a}_hold_end"))
            self._gestures[action] = gesture

        self.set_bindings(bindings)

    # ------------------------------------------------------- Konfiguration
    def install(self) -> None:
        QApplication.instance().installEventFilter(self)

    def uninstall(self) -> None:
        QApplication.instance().removeEventFilter(self)

    def set_bindings(self, bindings: dict[str, list[str]]) -> None:
        """Belegung setzen: {aktion: [taste_1, taste_2]}; jede Taste löst die Aktion aus."""
        self.reset()
        self._key_to_action = {
            key: action for action, keys in bindings.items() for key in keys if key
        }

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.reset()
        self._enabled = enabled

    def reset(self) -> None:
        self._down_keys.clear()
        for gesture in self._gestures.values():
            gesture.reset()

    # ------------------------------------------------------- Ereignisse
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        # Qt liefert Tastenereignisse zuerst an das QWindow und dann an das
        # Widget mit Fokus – nur das Widget-Ereignis auswerten, sonst doppelt.
        if not self._enabled or not isinstance(obj, QWidget) or obj.window() is not self._window:
            return False

        if etype == QEvent.Type.KeyPress:
            return self._on_press(event)
        return self._on_release(event)

    def _on_press(self, event: QKeyEvent) -> bool:
        action = self._key_to_action.get(key_from_event(event))
        if action is None:
            return False

        if action in self._gestures:
            if not event.isAutoRepeat() and event.key() not in self._down_keys:
                # Ist die andere Taste derselben Aktion schon unten, zählt das
                # nicht als neuer Druck (beide Tasten zusammen = eine Taste).
                already_down = action in self._down_keys.values()
                self._down_keys[event.key()] = action
                if not already_down:
                    self._gestures[action].press()
            return True

        if event.isAutoRepeat() and action not in REPEATABLE_ACTIONS:
            return True
        self.triggered.emit(action)
        return True

    def _on_release(self, event: QKeyEvent) -> bool:
        if event.isAutoRepeat():
            # Auto-Repeat-Release (Windows/X11) gehört zu einer gehaltenen Taste.
            return event.key() in self._down_keys
        action = self._down_keys.pop(event.key(), None)
        if action is None:
            return False
        if action not in self._down_keys.values():  # letzte gehaltene Taste der Aktion
            self._gestures[action].release()
        return True
