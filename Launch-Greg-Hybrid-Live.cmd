@echo off
setlocal
where pwsh.exe >nul 2>&1
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-greg-hybrid-live.ps1" -ConfirmStart
) else (
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-greg-hybrid-live.ps1" -ConfirmStart
)
if errorlevel 1 pause
endlocal
