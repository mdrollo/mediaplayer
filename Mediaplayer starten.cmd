@echo off
rem Startet den Mediaplayer per Doppelklick.
rem Beim ersten Start wird die virtuelle Umgebung (.venv) bei Bedarf
rem automatisch angelegt und PySide6 installiert.

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtuelle Umgebung wird eingerichtet, bitte warten ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python wurde nicht gefunden. Bitte Python 3 installieren:
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Die Installation der Abhaengigkeiten ist fehlgeschlagen.
        pause
        exit /b 1
    )
)

rem pythonw startet ohne Konsolenfenster; dieses Fenster schliesst sich sofort.
start "" ".venv\Scripts\pythonw.exe" main.py %*
