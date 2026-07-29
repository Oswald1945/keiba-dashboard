@echo off
rem ================================================================
rem  JV ROI backtest. For each JRA race with a result in the range:
rem    jv_export -> score_horse_v3 -> bet_recon judgment -> ROI
rem  Resumable (roi_rows.jsonl). Long run: ~3-4 sec per race.
rem  First time: use a small range or LIMIT to test (e.g. 30 races).
rem ================================================================
setlocal
set DIR=%~dp0
set /p RESET=Fresh start? delete previous roi_rows.jsonl (y/n):
if /I "%RESET%"=="y" if exist "%DIR%roi_rows.jsonl" del "%DIR%roi_rows.jsonl"
set /p F=From date YYYYMMDD (e.g. 20260601):
set /p T=To date   YYYYMMDD (e.g. 20260628):
set /p L=Limit races (0 = no limit; try 30 for a quick test):
python "%DIR%roi_backtest.py" run --from %F% --to %T% --limit %L%
echo.
echo (report saved to roi_backtest_report.md)
pause
