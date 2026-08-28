@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-greg-hybrid-live.ps1"
if errorlevel 1 pause
endlocal
