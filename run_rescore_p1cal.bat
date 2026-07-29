@echo off
rem ================================================================
rem  P1 calibration: rescore a small sample with the new scorer.
rem  Checks distribution of best-corrected-time (for HP_ABS_STD) and
rem  the new max-power pts. Writes a NEW file, keeps factor_rows.jsonl.
rem  About 300 races = ~15 min.
rem ================================================================
setlocal
set DIR=%~dp0
if exist "%DIR%factor_rows_cal.jsonl" del "%DIR%factor_rows_cal.jsonl"
python "%DIR%factor_backtest.py" --from 20260101 --to 20260628 --limit 300 --out "%DIR%factor_rows_cal.jsonl"
echo.
echo (factor_rows_cal.jsonl saved)
pause
