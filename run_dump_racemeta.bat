@echo off
rem ================================================================
rem  Dump race condition metadata (course / surface / distance /
rem  going) to racemeta_cache.jsonl. NO scoring, DB reads only -> fast.
rem  Enables condition-sliced ROI analysis (factor_segment.py).
rem  Use the SAME range as the factor backtest.
rem ================================================================
setlocal
set DIR=%~dp0
rem Schema now includes class / kaiji / nichiji -> rebuild fresh
if exist "%DIR%racemeta_cache.jsonl" del "%DIR%racemeta_cache.jsonl"
set /p F=From date YYYYMMDD (e.g. 20210601):
set /p T=To date   YYYYMMDD (e.g. 20260628):
python "%DIR%dump_racemeta.py" --from %F% --to %T%
echo.
echo (racemeta_cache.jsonl saved)
pause
