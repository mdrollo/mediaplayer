# Baut den Windows-Installer: PyInstaller -> Selbsttest -> Inno Setup.
#
# Aufruf im Projektordner (mit aktivierter .venv oder über deren Python):
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
#
# Voraussetzungen: pip install -r requirements.txt pyinstaller
#                  Inno Setup 6 (winget install JRSoftware.InnoSetup)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$version = & $python -c "import mediaplayer; print(mediaplayer.__version__)"
Write-Host "Mediaplayer $version wird gebaut ..."

& $python -m PyInstaller mediaplayer.spec --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller ist fehlgeschlagen." }

Write-Host "Selbsttest der gepackten Version ..."
$report = Join-Path $env:TEMP "mediaplayer-selftest.txt"
$proc = Start-Process -FilePath "dist\Mediaplayer\Mediaplayer.exe" -ArgumentList "--selftest", "`"$report`"" -Wait -PassThru
Get-Content $report -Encoding UTF8
if ($proc.ExitCode -ne 0) { throw "Selbsttest fehlgeschlagen." }

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 nicht gefunden (winget install JRSoftware.InnoSetup)." }

& $iscc "/DAppVersion=$version" "installer\mediaplayer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup ist fehlgeschlagen." }
Write-Host "Fertig: dist\installer\Mediaplayer-Setup-$version.exe"
