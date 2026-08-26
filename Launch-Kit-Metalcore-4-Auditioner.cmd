@echo off
setlocal
set "TOOLCHAIN_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
set "CAPTURE_PACKAGE=D:\Studio\ddrum4-packs\kit-metalcore-4-hd-c4-r15-tom-rr-final"

if not exist "%TOOLCHAIN_PYTHON%" (
  echo Python environment missing: %TOOLCHAIN_PYTHON%
  echo Run scripts\bootstrap.ps1, then try again.
  pause
  exit /b 1
)

if not exist "%CAPTURE_PACKAGE%\ddrum4-routing-simulation.json" (
  echo Capture package missing: %CAPTURE_PACKAGE%
  pause
  exit /b 1
)

start "DDrum4 Capture Auditioner" "%TOOLCHAIN_PYTHON%" -m ddrum4_bank.auditioner --package "%CAPTURE_PACKAGE%"
