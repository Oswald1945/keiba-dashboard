@echo off
rem Build baseline-time / track-condition tables from race.db.
rem Writes TF_BASELINE / TF_BABA_ADJUST into race.db and baseline_summary.txt here.
setlocal
set SCRIPT_DIR=%~dp0
python "%SCRIPT_DIR%baseline_time.py"
echo.
echo (baseline_summary.txt in this folder)
pause
