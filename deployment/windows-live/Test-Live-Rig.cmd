@echo off
setlocal
where pwsh.exe >nul 2>&1
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Test-Live-Rig.ps1"
) else (
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Test-Live-Rig.ps1"
)
if errorlevel 1 pause
endlocal
