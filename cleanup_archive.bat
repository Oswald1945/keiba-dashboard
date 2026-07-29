@echo off
rem ================================================================
rem  cleanup_archive.bat
rem  Move dated intermediate/output files into _archive\ (REVERSIBLE).
rem  This is a MOVE, not a delete. Review _archive\ and delete manually
rem  only if you are sure. To restore, move files back to the root.
rem
rem  PROTECTED (never moved): core .py, all .bat/.ps1, *.jsonl,
rem    course_*.json, baba_manual.json, baba_manual.example.json,
rem    memo_horses.json, setting*.xml, requirements.txt, docs\, CLAUDE.md,
rem    input\, jv_out\, *_report/handoff/etc .md .
rem  KEEP window: files whose name contains %KEEP% (latest race day)
rem    are LEFT in place so that day stays fully reproducible.
rem
rem  Families archived (all regenerable or already published to Pages):
rem    baba_YYYYMMDD_*.json    (auto-fetch cache; source is baba_manual.json)
rem    smartrc_YYYYMMDD_*.json horses_data_YYYYMMDD_*.json
rem    scores_YYYYMMDD_*.csv   haraimodoshi_YYYYMMDD_*.json
rem    *_pred.html  *_review.html
rem ================================================================
setlocal
set DIR=%~dp0
set ARC=%DIR%_archive
set KEEP=20260726
if not exist "%ARC%" mkdir "%ARC%"

echo === Archiving dated files (keeping day %KEEP%) into %ARC% ===

for %%f in ("%DIR%baba_2*.json")         do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul
for %%f in ("%DIR%smartrc_2*.json")      do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul
for %%f in ("%DIR%horses_data_2*.json")  do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul
for %%f in ("%DIR%scores_2*.csv")        do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul
for %%f in ("%DIR%haraimodoshi_2*.json") do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul
for %%f in ("%DIR%*_pred.html")          do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul
for %%f in ("%DIR%*_review.html")        do @echo %%~nf|findstr /C:"%KEEP%" >nul || move "%%f" "%ARC%" >nul

echo.
echo Done. Moved files are in: %ARC%
echo (Nothing was deleted.) Delete _archive contents manually only if unneeded.
pause
