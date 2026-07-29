@echo off
rem ================================================================
rem  STAGE (4): build the prediction dashboard from input\ data.
rem  Runs run_new.py which:
rem   - auto/manual SmartRC (smartrc_{race_id}.json)
rem   - going/baba (baba_manual.json takes priority)
rem   - score_horse_v3 -> build_dashboard_v3 -> {race_id}_pred.html
rem  Do STAGE(1) run_predict_data.bat first, then SmartRC + baba,
rem  then run this.
rem ================================================================
setlocal
set DIR=%~dp0
python "%DIR%run_new.py"
echo.
echo === done -> {race_id}_pred.html ===
pause
