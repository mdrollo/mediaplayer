# Mediaplayer

Einfacher, gut bedienbarer Vollbild-Mediaplayer für lokale Audiodateien –
Python 3 und PySide6 (Qt 6), lauffähig unter Windows und macOS.

## Installation

Voraussetzung: Python 3.10 oder neuer.

```bash
python -m venv .venv
```

Umgebung aktivieren:

- Windows: `.venv\Scripts\activate`
- macOS: `source .venv/bin/activate`

Abhängigkeiten installieren und starten:

```bash
pip install -r requirements.txt
python main.py
```

**Windows per Doppelklick:** `Mediaplayer starten.cmd` im Projektordner
startet den Player ohne Konsolenfenster. Fehlt die virtuelle Umgebung, wird
sie beim ersten Start automatisch angelegt und PySide6 installiert.

Der Player startet im Vollbild. Mit `python main.py --windowed` startet er
stattdessen als maximiertes Fenster.

## Bedienung

| Element | Funktion |
|---|---|
| Zeitanzeige + Positionsregler | Klicken springt direkt an die Stelle, Ziehen verschiebt die Position |
| ⏮ ⏯ ⏹ ⏭ | Vorheriger Titel · Play/Pause · Stop · Nächster Titel |
| Pausen überspringen | Stille am Anfang und Ende der Titel überspringen (Standard: an; blau = aktiv) |
| Lautstärkeregler | 0–100 %, gehörrichtig (logarithmisch) skaliert |
| Tempo | Anzeige und Einstellung in **BPM** (siehe unten). Ist das Tempo eines Titels unbekannt, wie bisher 0,50x – 2,00x in 0,01-Schritten. „1,00x“ = Originaltempo |
| Playlist | Doppelklick oder Eingabetaste startet einen Titel; ▶ und Fettschrift markieren den aktuellen Titel |
| Hinzufügen | Audiodateien auswählen (Dateien/Ordner können auch ins Fenster gezogen werden) |
| Entfernen | Markierten Titel aus der Playlist entfernen |
| Mischen | Reihenfolge einmal zufällig durchmischen. Der aktuelle Titel rückt nach oben und spielt ungestört weiter. Die gemischte Reihenfolge wird nicht gespeichert – beim nächsten Start gilt wieder die ursprüngliche (außer man speichert sie bewusst mit „Playlist speichern“) |
| Playlist laden / speichern | `.m3u8`/`.m3u` (auch für andere Player) oder `.json` |
| Zuletzt | Schnellauswahl der 10 zuletzt geladenen oder gespeicherten Playlists (Taste `L`). Antippen + „Laden“, Doppelklick, Eingabetaste oder Ziffern 1–9; nicht mehr vorhandene Playlists erscheinen grau und lassen sich mit „Aus Liste entfernen“ (oder Entf) löschen. `L` schließt das Panel wieder |
| Tastatur | Tastaturbelegung konfigurieren |
| Beenden | Programm schließen |

**Escape** verlässt den Vollbildmodus, **F11** schaltet ihn um.

### Pausen überspringen

Viele Album-Rips enthalten mehrere Sekunden Stille vor und nach der Musik –
zusammen oft 5–7 Sekunden Pause zwischen zwei Titeln. Ist „Pausen
überspringen“ aktiv (Standard), beginnt jeder Titel direkt mit der Musik, und
sobald die Musik am Ende verklungen ist, startet der nächste Titel.

- Wo die Musik beginnt und endet, ermittelt die Hintergrundanalyse zusammen mit
  den BPM (einmal pro Datei, danach aus dem Cache). Beim allerersten Abspielen
  einer neuen Datei kann die Analyse noch laufen; dann greift das Überspringen
  ab dem Moment, in dem sie fertig ist (meist nach wenigen Sekunden).
- Als Stille gilt alles unter −48 dB. Ausklingende Töne bleiben
  0,3 s länger erhalten; Pausen unter 0,5 s werden nicht übersprungen.
- „Zurück“ (kurz) springt ebenfalls zum Musikanfang.
- Stille *mitten* im Titel (z. B. vor einem versteckten Bonustrack) wird nicht
  übersprungen.

### Tempo in BPM

Der Player ermittelt das Tempo jeder Datei automatisch: zuerst den laufenden
Titel, danach im Hintergrund den Rest der Playlist. Jede Datei wird nur
einmal analysiert, das Ergebnis landet in `bpm_cache.json` neben der
Einstellungsdatei und wird nach einer Änderung der Datei neu ermittelt.

- **Anzeige:** groß die aktuellen BPM, darunter Original-BPM und
  Geschwindigkeit, z. B. „132 BPM · Original 95,8 · 1,38x“. Während der Analyse
  steht dort „BPM wird ermittelt …“.
- **Einstellen:** Der Regler arbeitet in ganzen BPM, −/+ sowie die Tasten `+`/`-`
  ändern um 1 BPM. Möglich ist der Bereich 0,5x bis 2,0x des Originaltempos.
- **BPM fest:** Ist der Knopf aktiv, laufen alle Titel mit denselben BPM. Beim
  Titelwechsel wird die Geschwindigkeit automatisch angepasst, begrenzt auf
  0,5x bis 2,0x.
- **Korrigieren:** Automatische Erkennung verwechselt manchmal halbes und
  doppeltes Tempo, das korrigieren „½“ und „×2“. Mit **Tap** tippst du
  mindestens viermal im Takt mit, dann übernimmt der Player dieses Tempo.
  Korrekturen werden gespeichert und bei der nächsten Wiedergabe verwendet.
- Musik ohne klaren Takt (Hörbücher, Klassik) wird als „BPM unbekannt“
  angezeigt und dann wie bisher über die Geschwindigkeit gesteuert.

### Dateiauswahl

Hinzufügen, Playlist laden und Playlist speichern verwenden einen eigenen
Dateidialog in derselben großen Darstellung wie der Player (im Vollbild
ebenfalls bildschirmfüllend, per Touch scrollbar):

- Ordner öffnen sich mit einem Antippen; „Nach oben“ (oder Rücktaste) wechselt
  in den übergeordneten Ordner. Schnellzugriff auf Musik, persönlichen Ordner,
  Desktop, Downloads und alle Laufwerke.
- Es werden nur passende Dateien angezeigt (Audiodateien bzw. Playlists),
  natürlich sortiert („Track 2“ vor „Track 10“).
- Beim Hinzufügen schaltet Antippen die Auswahl einer Datei um; die Auswahl
  bleibt beim Ordnerwechsel erhalten, so lassen sich Titel aus mehreren Ordnern
  auf einmal hinzufügen. „Ganzer Ordner“ übernimmt alle Titel des Ordners samt
  Unterordnern.
- Beim Speichern gibt man den Dateinamen ein (Antippen einer vorhandenen
  Playlist übernimmt deren Namen); ohne Endung wird `.m3u8` angehängt.

### Wiedergaberegeln

- **Vor/Zurück während der Wiedergabe:** Der neue Titel spielt sofort weiter.
- **Vor/Zurück im gestoppten oder pausierten Zustand:** Der neue Titel wird nur
  ausgewählt und geladen. Gestartet wird er mit Play.
- **Ende eines Titels:** Der nächste Titel startet automatisch.
- **Play bei markiertem anderen Titel:** Ist die Wiedergabe angehalten und ist in
  der Playlist ein anderer Titel markiert, startet Play diesen Titel.
- „Zurück“ beim ersten Titel springt an dessen Anfang.

Die zuletzt verwendete Playlist, Lautstärke und Geschwindigkeit werden beim
Beenden gespeichert und beim nächsten Start wiederhergestellt (der Titel wird
dann nur geladen, nicht automatisch abgespielt).

### Tastatur (Standardbelegung)

| Taste | Funktion |
|---|---|
| Pfeil links – kurz | Zum Anfang des aktuellen Titels |
| Pfeil links – zweimal schnell | Vorheriger Titel |
| Pfeil links – halten | Zurückspulen, solange die Taste gehalten wird |
| Pfeil rechts – kurz | Zum Ende des aktuellen Titels (letzte Sekunde) |
| Pfeil rechts – zweimal schnell | Nächster Titel |
| Pfeil rechts – halten | Vorspulen, solange die Taste gehalten wird |
| Leertaste | Play/Pause |
| Pfeil hoch / runter | Lauter / leiser (5 %-Schritte) |
| `+` / `-` | Tempo ±1 BPM (ohne bekanntes Tempo ±0,01x); gedrückt halten läuft weiter |
| `0` | Originaltempo (1,0x) |
| `L` | Zuletzt verwendete Playlists öffnen/schließen |

`+`, `-` und `0` funktionieren auch auf dem Ziffernblock und unabhängig vom
Tastaturlayout (auf US-Tastaturen ist `+` = Umschalt + `=`).

Ein kurzer Druck wird erst ausgeführt, wenn das Doppeldruck-Zeitfenster
(300 ms nach dem Loslassen) abgelaufen ist – nur so lassen sich kurzer Druck
und Doppeldruck sicher unterscheiden.

**Belegung ändern:** Schaltfläche „Tastatur“ → bei der gewünschten Funktion
auf „Taste 1“ oder „Taste 2“ klicken → neue Taste drücken → „Speichern“.
„✕“ entfernt eine Belegung. Jede Funktion kann so zwei Tasten haben, die sich
gleich verhalten (ab Werk ist „Taste 2“ überall frei). Wird eine Taste
vergeben, die schon an anderer Stelle belegt ist, wird sie dort entfernt.
Das Sonderverhalten (kurz/doppelt/halten) gehört zur *Funktion* „Zurück“ bzw.
„Weiter“ und gilt für jede Taste, die ihr zugewiesen wird.

Die Einstellungen liegen in einer INI-Datei:

- Windows: `%APPDATA%\LocalMediaPlayer\Mediaplayer.ini`
- macOS: `~/.config/LocalMediaPlayer/Mediaplayer.ini`

Löschen dieser Datei setzt alles auf die Standardwerte zurück.

## Unterstützte Formate

MP3 funktioniert immer. M4A/AAC, WAV, FLAC, OGG, Opus und WMA werden ebenfalls
angeboten; ob sie abspielbar sind, hängt vom Multimedia-Backend ab (bei
aktuellen PySide6-Versionen FFmpeg, das alle genannten Formate beherrscht).

## Projektstruktur

```
main.py                         Startpunkt
mediaplayer/
  app.py                        QApplication, Stil, Vollbildstart
  player/
    playback.py                 PlaybackController (QMediaPlayer, QAudioOutput,
                                Vor/Zurück-Regeln, Spulen, Lautstärke, Tempo)
    keyboard.py                 KeyboardController (Belegung → Aktion) und
                                TapHoldGesture (kurz / doppelt / halten)
    analysis.py                 Hintergrundanalyse (Decoder, Warteschlange, Cache)
    bpm.py                      Tempo-Erkennung (numpy)
    silence.py                  Erkennung von Musikanfang/-ende
    tempo.py                    TempoController (BPM einstellen, BPM fest, Tap)
  playlist/
    model.py                    Playlist-Datenmodell (ohne Qt)
    storage.py                  Laden/Speichern von M3U8- und JSON-Playlists
  settings/
    key_bindings.py             Aktionen, Standardbelegung, Tastennormalisierung
    app_settings.py             Dauerhafte Einstellungen (QSettings, INI)
  ui/
    main_window.py              Hauptfenster
    key_config_dialog.py        Dialog „Tastatur“
    file_browser.py             Eigener großer Dateidialog
    recent_playlists_dialog.py  Schnellauswahl „Zuletzt“
    widgets.py                  Große Listen, Touch-Scrollen, Dialoggröße
    style.py                    Stylesheet, Klick-springt-Stil für Regler
  selftest.py                   Selbsttest für gepackte Versionen (--selftest)
tests/
  test_mediaplayer.py           Automatische Tests
assets/                         App-Symbol (PNG, ICO)
installer/mediaplayer.iss       Inno-Setup-Skript (Windows-Installer)
mediaplayer.spec                PyInstaller-Konfiguration
tools/                          build_windows.ps1, make_icon.py
.github/workflows/build.yml     Automatischer Bau (Windows + macOS)
```

### Anpassbare Werte

- Zeitfenster der Tastengesten: `GestureTiming` in `mediaplayer/player/keyboard.py`
  (`hold_ms` = ab wann „gehalten“, `double_press_ms` = Doppeldruck-Fenster).
- Spulgeschwindigkeit, Tempo-Grenzen und -Schritte, Lautstärkeschritte und
  -kurve: Konstanten oben in `mediaplayer/player/playback.py`.

## Installationspaket

**Fertige Pakete** baut GitHub Actions bei jedem Push automatisch: unter
*Actions → Build → letzter Lauf → Artifacts* liegen `Mediaplayer-Windows`
(Setup-Datei) und `Mediaplayer-macOS` (DMG). Für ein Release mit beiden Dateien
einen Tag pushen, der zur Version in `mediaplayer/__init__.py` passt:

```bash
git tag v1.0.0
```

```bash
git push origin v1.0.0
```

**Windows-Setup lokal bauen** (Voraussetzung: `pip install pyinstaller` und
Inno Setup 6, z. B. `winget install JRSoftware.InnoSetup`):

```bash
powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
```

Ergebnis: `dist\installer\Mediaplayer-Setup-<Version>.exe`. Der Installer
braucht keine Administratorrechte, legt Startmenü- und auf Wunsch
Desktop-Verknüpfung an und lässt sich über „Apps & Features“ entfernen.
Einstellungen, Playlists und BPM-Cache liegen im Benutzerprofil und bleiben
bei Updates erhalten. Auf dem Zielrechner wird kein Python benötigt.

Hinweise:

- Die Pakete sind nicht signiert. Windows zeigt beim ersten Start „Der Computer
  wurde durch Windows geschützt“ → *Weitere Informationen → Trotzdem ausführen*.
  Auf dem Mac die App beim ersten Mal per Rechtsklick → *Öffnen* starten.
- Das Mac-Paket wird für Apple-Silicon-Macs (M1 und neuer) gebaut.
- `Mediaplayer --selftest bericht.txt` prüft ein gepacktes Programm ohne
  Fenster und ohne Tonausgabe (Decoder, BPM-/Stille-Analyse, Wiedergabe,
  Oberfläche); die Build-Skripte nutzen das automatisch.
- Das App-Symbol erzeugt `python tools/make_icon.py` (`assets/`).

## Tests

```bash
python -m unittest discover -s tests -v
```

Die Tests prüfen Playlist, Dateiformate, gespeicherte Einstellungen,
Tastennormalisierung, die Gestenerkennung, die Tastenzuordnung sowie die
Wiedergaberegeln mit einem echten `QMediaPlayer` (kurze erzeugte WAV-Dateien).
