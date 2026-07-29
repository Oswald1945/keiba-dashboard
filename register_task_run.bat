@echo off
rem Register the daily JVLinkToSQLite differential-update task (05:00).
rem Double-click to run. No admin needed.
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%register_task.ps1"
echo.
pause
