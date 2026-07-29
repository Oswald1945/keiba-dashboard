@echo off
rem ============================================================
rem  Rebuild the regression baseline (about 5 minutes)
rem  Run this ONLY when a score change is intended and approved.
rem  Add --force to overwrite an existing baseline.
rem ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python app\tests\make_golden.py --limit 100 %*
echo.
pause
