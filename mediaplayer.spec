# PyInstaller-Konfiguration für den Mediaplayer (Windows und macOS).
#
# Bauen im Projektordner:  pyinstaller mediaplayer.spec --noconfirm
# Ergebnis: dist/Mediaplayer/ (Windows, mit Mediaplayer.exe)
#           dist/Mediaplayer.app (macOS)
#
# "onedir" statt einer einzelnen EXE: startet deutlich schneller, weil nichts
# bei jedem Start entpackt werden muss; der Installer verpackt den Ordner.

import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from mediaplayer import APP_NAME, __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
ICON = "assets/icon.png" if IS_MAC else "assets/icon.ico"

a = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,          # kein Konsolenfenster
    icon=ICON,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier="de.mdrollo.mediaplayer",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
