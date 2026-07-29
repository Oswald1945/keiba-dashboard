@echo off
rem ================================================================
rem  P3 full validation: rescore ALL 5 years with the new scorer
rem  (pace-adjusted late pace / relative-agari) into a SEPARATE file.
rem  Keeps the baseline factor_rows.jsonl intact for A/B comparison.
rem  HEAVY: ~20-25h (jv_export now also fetches field agari per race).
rem  Resumable: rerun to continue (does NOT delete unless fresh).
rem ================================================================
setlocal
set DIR=%~dp0
set /p RESET=Fresh start? delete factor_rows_p3.jsonl (y/n):
if /I "%RESET%"=="y" if exist "%DIR%factor_rows_p3.jsonl" del "%DIR%factor_rows_p3.jsonl"
python "%DIR%factor_backtest.py" --from 20210601 --to 20260628 --limit 0 --out "%DIR%factor_rows_p3.jsonl"
echo.
echo (factor_rows_p3.jsonl saved)
pause
