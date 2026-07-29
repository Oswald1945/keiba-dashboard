@echo off
rem ================================================================
rem  STAGE (1): make prediction input data only (no scoring).
rem   1) update race.db (latest shutuba / training)
rem   2) list predictable races (results not confirmed yet)
rem   3) you pick date / jyo / R range (FROM-TO)
rem   4) jv_export -> input\  (shutuba / kako / sakuro / wood) per R
rem  Then do SmartRC (2) and going baba (3), and run STAGE(4)
rem   run_predict_dash.bat to build the dashboard.
rem  Jyo code: 01Sapporo 02Hakodate 03Fukushima 04Niigata 05Tokyo
rem            06Nakayama 07Chukyo 08Kyoto 09Hanshin 10Kokura
rem  NOTE: enter Race numbers as plain numbers (7), NOT R7.
rem ================================================================
setlocal enabledelayedexpansion
set DIR=%~dp0
echo === [1/4] Updating race.db (latest shutuba / training) ===
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DIR%jvlink_update.ps1"
echo.
echo === [2/4] Races you can predict (results not confirmed yet) ===
python "%DIR%inspect_upcoming.py"
echo.
set /p D=Race date YYYYMMDD:
set /p J=Jyo code 01-10:
set /p RF=Race number FROM (number only, e.g. 7):
set /p RT=Race number TO   (same as FROM for a single race, e.g. 12):
echo.
echo === [3/4] Exporting JV input CSVs to input\ (R%RF% - R%RT%) ===
for /L %%r in (%RF%,1,%RT%) do (
  echo --- exporting R%%r ---
  python "%DIR%jv_export.py" --date %D% --jyo %J% --r %%r --outdir "%DIR%input"
)
echo.
echo === [4/4] Data ready in input\. Next: SmartRC + baba, then run_predict_dash.bat ===
pause
