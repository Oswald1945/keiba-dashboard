@echo off
rem ============================================================
rem  Regression test
rem  Rebuilds 100 saved races with the current code and checks
rem  that every score, HTML and EV value still matches.
rem  Takes about 5 minutes.
rem ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -m pytest app/tests -q -p no:cacheprovider
echo.
pause
