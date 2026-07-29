@echo off
rem ================================================================
rem  Small validation rescore with the CURRENT scorer + exporter.
rem  Used to sanity-check logic changes (e.g. P3 pace-adjusted late
rem  pace / new past-race schema) BEFORE a full overnight rescore.
rem  Writes a NEW file, keeps factor_rows.jsonl (5yr) intact.
rem  About 300 races = ~15-30 min.
rem ================================================================
setlocal
set DIR=%~dp0
if exist "%DIR%factor_rows_cal.jsonl" del "%DIR%factor_rows_cal.jsonl"
python "%DIR%factor_backtest.py" --from 20260101 --to 20260628 --limit 300 --out "%DIR%factor_rows_cal.jsonl"
echo.
echo (factor_rows_cal.jsonl saved)
pause
