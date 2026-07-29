@echo off
rem One-time: remove downloaded-file block (Mark of the Web) from JVLinkToSQLite files, then report.
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%unblock_tool.ps1"
echo.
pause
