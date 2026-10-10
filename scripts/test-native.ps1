$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
New-Item -ItemType Directory -Force tmp | Out-Null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = & $vswhere -latest -products '*' -property installationPath
if (-not $vs) { throw 'MSVC Build Tools required for native C tests' }
$dev = Join-Path $vs 'Common7/Tools/VsDevCmd.bat'
@"
@echo off
call "$dev" -arch=x64 -no_logo
if errorlevel 1 exit /b 1
cl /nologo /std:c11 /W3 /I firmware/include /Fe:tmp/core_tests.exe /Fo:tmp/ tests/core_test.c firmware/src/engine.c firmware/src/protocol.c
if errorlevel 1 exit /b 1
cl /nologo /std:c11 /LD /I firmware/include /Fe:tmp/codec.dll /Fo:tmp/ firmware/src/protocol.c /link /EXPORT:cs_crc32 /EXPORT:cs_encode /EXPORT:cs_feed
if errorlevel 1 exit /b 1
tmp\core_tests.exe
if errorlevel 1 exit /b 1
cl /nologo /std:c11 /W3 /I tests/flash_hal /I firmware/include /Fe:tmp/flash_tests.exe /Fo:tmp/ tests/flash_test.c firmware/src/calibration_flash.c firmware/src/engine.c firmware/src/protocol.c
if errorlevel 1 exit /b 1
tmp\flash_tests.exe
"@ | Set-Content -LiteralPath tmp/native-test.cmd -Encoding ascii
cmd /c tmp\native-test.cmd
if ($LASTEXITCODE) { throw 'Native core tests failed' }
