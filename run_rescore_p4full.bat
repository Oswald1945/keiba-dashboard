@echo off
rem ================================================================
rem  P4 full validation: rescore ALL 5 years with the current scorer
rem  (P3 pace-adjusted agari + P4 performance-weighted course aptitude)
rem  into a SEPARATE file factor_rows_p4.jsonl.
rem  Keeps factor_rows.jsonl (baseline) and factor_rows_p3.jsonl intact.
rem  HEAVY: ~20-25h. Resumable (rerun with fresh=n to continue).
rem ================================================================
setlocal
set DIR=%~dp0
set /p RESET=Fresh start? delete factor_rows_p4.jsonl (y/n):
if /I "%RESET%"=="y" if exist "%DIR%factor_rows_p4.jsonl" del "%DIR%factor_rows_p4.jsonl"
python "%DIR%factor_backtest.py" --from 20210601 --to 20260628 --limit 0 --out "%DIR%factor_rows_p4.jsonl"
echo.
echo (factor_rows_p4.jsonl saved)
pause
