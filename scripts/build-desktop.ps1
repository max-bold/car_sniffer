$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& ./.venv/Scripts/python.exe -m PyInstaller --noconfirm --windowed --onedir --name CarSniffer --paths . desktop/launcher.py
if ($LASTEXITCODE) { throw 'Desktop build failed' }
# Qt uses Windows' unversioned ICU API. PATH may contain an incompatible
# icuuc.dll (for example from embedded development tools); collect the OS pair.
Copy-Item "$env:WINDIR/System32/icuuc.dll" dist/CarSniffer/_internal/icuuc.dll -Force
Copy-Item "$env:WINDIR/System32/icu.dll" dist/CarSniffer/_internal/icu.dll -Force
