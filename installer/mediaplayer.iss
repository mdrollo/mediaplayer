; Inno-Setup-Skript für den Mediaplayer (Windows-Installer).
;
; Voraussetzung: dist\Mediaplayer\ wurde mit PyInstaller gebaut
; (pyinstaller mediaplayer.spec). Am einfachsten über tools\build_windows.ps1.
;
; Manuell:  ISCC.exe /DAppVersion=1.0.0 installer\mediaplayer.iss
; Ergebnis: dist\installer\Mediaplayer-Setup-<Version>.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Mediaplayer"
#define AppExe "Mediaplayer.exe"

[Setup]
; Die AppId kennzeichnet das Programm dauerhaft – nie ändern, sonst werden
; Updates als zweites Programm installiert.
AppId={{537E6C7F-7DF5-4275-90AD-CDB36E3F32DF}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Michael Droll
AppPublisherURL=https://github.com/mdrollo/mediaplayer
AppSupportURL=https://github.com/mdrollo/mediaplayer/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Ohne Administratorrechte installierbar; auf Wunsch für alle Benutzer.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=Mediaplayer-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Bei Updates alte Programmdateien entfernen (Einstellungen liegen im Benutzerprofil
; und bleiben erhalten).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Mediaplayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
