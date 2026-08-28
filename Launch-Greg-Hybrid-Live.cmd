@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-greg-hybrid-live.ps1" -ConfirmStart
if errorlevel 1 pause
endlocal
