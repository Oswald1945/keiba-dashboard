@echo off
rem ================================================================
rem  Dump confirmed payouts (NL_HR_PAY) to payouts_cache.jsonl.
rem  NO scoring, DB reads only -> fast (a few minutes).
rem  Enables fully-offline ROI comparison across weight sets
rem   (factor_roi_offline.py).
rem  Use the SAME range as the factor backtest.
rem ================================================================
setlocal
set DIR=%~dp0
set /p F=From date YYYYMMDD (e.g. 20250601):
set /p T=To date   YYYYMMDD (e.g. 20260628):
python "%DIR%dump_payouts.py" --from %F% --to %T%
echo.
echo (payouts_cache.jsonl saved)
pause
