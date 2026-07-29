@echo off
rem ================================================================
rem  LIVE prediction for one upcoming race, fully from JV (no TARGET)
rem  1) update race.db (latest entries + training)
rem  2) list races that can be predicted (results not yet in)
rem  3) you pick date / jyo / R
rem  4) export input CSVs to input\  and build the prediction dashboard
rem  Jyo code: 01Sapporo 02Hakodate 03Fukushima 04Niigata 05Tokyo
rem            06Nakayama 07Chukyo 08Kyoto 09Hanshin 10Kokura
rem ================================================================
setlocal
set DIR=%~dp0
echo === [1/4] Updating race.db (latest shutuba / training) ===
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DIR%jvlink_update.ps1"
echo.
echo === [2/4] Races you can predict (results not confirmed yet) ===
python "%DIR%inspect_upcoming.py"
echo.
set /p D=Race date YYYYMMDD:
set /p J=Jyo code 01-10:
set /p R=Race number:
echo.
echo === [3/4] Exporting JV input CSVs to input\ ===
python "%DIR%jv_export.py" --date %D% --jyo %J% --r %R% --outdir "%DIR%input"
echo.
echo === [4/4] Building prediction dashboard (run_new.py) ===
python "%DIR%run_new.py"
echo.
echo === done ===
pause
