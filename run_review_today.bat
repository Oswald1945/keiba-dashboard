@echo off
rem ================================================================
rem  Build REVIEW dashboards for 20260725 using realtime (RT_) results.
rem  1) re-export the predicted races (jv_export now falls back to
rem     RT_SE_RACE_UMA, so a "race result" CSV is produced same-day)
rem  2) run_new.py --review  (generate review HTML + re-push to Pages)
rem  Prereq: realtime (RT_) results already fetched into race.db
rem          (JVRealTimeDataUpdateSetting enabled + -m exec).
rem  Jyo: 07=Chukyo 04=Niigata 01=Sapporo
rem ================================================================
setlocal
set DIR=%~dp0
echo === re-export Chukyo R6-R11 (with results) ===
for %%r in (6 7 8 9 10 11) do python "%DIR%jv_export.py" --date 20260725 --jyo 07 --r %%r --outdir "%DIR%input"
echo === re-export Niigata R5,6,7,8,12 (with results) ===
for %%r in (5 6 7 8 12) do python "%DIR%jv_export.py" --date 20260725 --jyo 04 --r %%r --outdir "%DIR%input"
echo === re-export Sapporo R7-R12 (with results) ===
for %%r in (7 8 9 10 11 12) do python "%DIR%jv_export.py" --date 20260725 --jyo 01 --r %%r --outdir "%DIR%input"
echo.
echo === generate review dashboards (--review --force) ===
python "%DIR%run_new.py" --review --force
echo.
echo === done ===
pause
