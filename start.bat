@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Run scripts\bootstrap.ps1 first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m desktop %*
set "launch_result=%errorlevel%"
if not "%launch_result%"=="0" (
    echo.
    echo Car Sniffer exited with error %launch_result%.
    pause
)
exit /b %launch_result%
