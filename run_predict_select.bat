@echo off
rem ================================================================
rem  STAGE (1): update race.db, then pick venue+races interactively
rem  and export input\ CSVs in bulk (predict_select.py).
rem   - choose venue(s) by number
rem   - choose races as all / 7-12 / 7,9,11
rem  Then do SmartRC (2) + going baba (3), and run_predict_dash.bat (4).
rem ================================================================
setlocal
set DIR=%~dp0
echo === Updating race.db (latest shutuba / training) ===
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DIR%jvlink_update.ps1"
echo.
python "%DIR%predict_select.py"
pause
