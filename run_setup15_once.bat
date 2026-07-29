@echo off
rem JVLinkToSQLite one-time 15-year setup (uses setting_setup15.xml).
rem Long run (tens of minutes to a few hours). Do NOT close this window.
rem Keep the PC awake. If interrupted, just run again to resume.
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%jvlink_update.ps1" -Setting "C:\Users\r-ito\JVLinkToSQLite\setting_setup15.xml"
echo.
echo Exit code: %ERRORLEVEL%   (0 = success)
pause
