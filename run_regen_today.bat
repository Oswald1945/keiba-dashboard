@echo off
rem ================================================================
rem  Regenerate ALL 20260725 predictions with NAR(local) excluded.
rem  1) re-export the 17 races (new jv_export = JRA-only past runs)
rem  2) run_new.py --force  (re-score + rebuild + re-push to Pages)
rem  SmartRC json and baba_manual.json (20260725) are already in place.
rem  Jyo: 07=Chukyo 04=Niigata 01=Sapporo
rem ================================================================
setlocal
set DIR=%~dp0
echo === clean previous 20260725 CSVs (avoid _dup accumulation) ===
del /q "%DIR%input\*_20260725_*.csv" 2>nul
del /q "%DIR%input\done\*_20260725_*.csv" 2>nul
echo === re-export Chukyo R6-R11 ===
for %%r in (6 7 8 9 10 11) do python "%DIR%jv_export.py" --date 20260725 --jyo 07 --r %%r --outdir "%DIR%input"
echo === re-export Niigata R5,6,7,8,12 ===
for %%r in (5 6 7 8 12) do python "%DIR%jv_export.py" --date 20260725 --jyo 04 --r %%r --outdir "%DIR%input"
echo === re-export Sapporo R7-R12 ===
for %%r in (7 8 9 10 11 12) do python "%DIR%jv_export.py" --date 20260725 --jyo 01 --r %%r --outdir "%DIR%input"
echo.
echo === re-score + rebuild + re-push (force) ===
python "%DIR%run_new.py" --force
echo.
echo === done ===
pause
