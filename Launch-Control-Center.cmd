@echo off
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo The project virtual environment is missing.
    echo Run scripts\bootstrap.ps1 from PowerShell first.
    pause
    exit /b 1
)

start "Drum Control Center" "%~dp0.venv\Scripts\pythonw.exe" -m control_center.gui
