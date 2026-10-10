param([switch]$Hardware)
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& ./scripts/test-native.ps1
& ./.venv/Scripts/python.exe -m pytest -q
if ($LASTEXITCODE) { throw 'Python tests failed' }
cmake --preset debug -S firmware
if ($LASTEXITCODE) { throw 'Configure failed' }
cmake --build firmware/build
if ($LASTEXITCODE) { throw 'Firmware build failed' }
if ($Hardware) {
    & ./.venv/Scripts/python.exe -m scripts.hardware_smoke --output docs/hardware-smoke.json
    if ($LASTEXITCODE) { throw 'Hardware smoke failed' }
}
