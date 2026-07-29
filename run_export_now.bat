@echo off
rem ================================================================
rem  One-shot export for the races you asked for:
rem    Sapporo (01), 2026-07-25, R7 - R12
rem  Creates input\ CSVs (shutuba / kako / sakuro / wood) per race.
rem  race.db is already up to date, so no JV update here.
rem  (Just double-click. No prompts.)
rem ================================================================
setlocal
set DIR=%~dp0
for /L %%r in (7,1,12) do (
  echo --- exporting Sapporo 20260725 R%%r ---
  python "%DIR%jv_export.py" --date 20260725 --jyo 01 --r %%r --outdir "%DIR%input"
)
echo.
echo === done. input\ now has R7-R12 data. ===
pause
