@echo off
rem ================================================================
rem  Factor effectiveness backtest (JV).
rem   For each JRA race with a result in the range:
rem     jv_export -> score_horse_v3 -> capture per-horse factor pts
rem     + actual finish / popularity into factor_rows.jsonl
rem  Then factor_analysis.py measures each factor's predictive power
rem   (raw_rho / partial_rho controlling for market / rho_pop).
rem  Resumable. ~3-4 sec per race (same cost as ROI backtest).
rem ================================================================
setlocal
set DIR=%~dp0
set /p RESET=Fresh start? delete previous factor_rows.jsonl (y/n):
if /I "%RESET%"=="y" if exist "%DIR%factor_rows.jsonl" del "%DIR%factor_rows.jsonl"
set /p F=From date YYYYMMDD (e.g. 20260401):
set /p T=To date   YYYYMMDD (e.g. 20260628):
set /p L=Limit races (0 = no limit; try 30 for a quick test):
python "%DIR%factor_backtest.py" --from %F% --to %T% --limit %L%
echo.
echo === Aggregating factor predictive power ===
python "%DIR%factor_analysis.py"
echo.
echo (report saved to factor_analysis_report.md)
pause
