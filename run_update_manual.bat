@echo off
rem JVLinkToSQLite manual differential update.
rem Calls jvlink_update.ps1 (-m exec with setting.xml). Safe to run anytime.
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%jvlink_update.ps1" %*
echo.
echo Exit code: %ERRORLEVEL%   (0 = success)
pause
